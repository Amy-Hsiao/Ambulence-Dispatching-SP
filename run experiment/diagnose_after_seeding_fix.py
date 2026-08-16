#!/usr/bin/env python3
"""plan/17 修正後的診斷實驗：確認 root seeding 修正是否有效，並決定收斂門檻。

背景（plan/17）
--------------
上一輪實驗 7 個 case 全部跑滿 2 小時、gap 45~74%。診斷出三個原因，其中
**最好修的**是：Benders root seeding 在只拿到 LP 下界 56% 的地方就提前停止
（第 151/300 輪、LB=10,029,725，而 Extensive 的根節點 LP 下界是 17,865,909）。

已調整（都只是 config 調參，未動求解核心）：
  BENDERS_ROOT_SEED_ITERS       300  → 1000
  BENDERS_ROOT_SEED_LB_REL_TOL  5e-4 → 5e-5
  BENDERS_ROOT_SEED_STALL_ROUNDS 10  → 40
  BENDERS_PARALLEL_ORACLES        5  → 10
  SCENARIOS                      30  → 50（老師指示）

這支腳本要回答三個問題
---------------------
Q1. 修正後 BBC 的下界能不能追上 Extensive 的根節點 LP 下界？
    （上一輪只有 56%，這是 BBC 反而輸給 Extensive 的直接原因）
Q2. 修正後 gap 掉到多少？→ 用來決定正式實驗的收斂門檻該設 1% / 5% / 還是
    乾脆改成「固定 2 小時比 gap」。
Q3. 最佳解比較靠近 LP 下界還是靠近目前的 UB？→ 判斷主要瓶頸是「下界太弱」
    還是「找不到好解」，這兩者的後續解法完全不同。

只跑 small case 的 3 個代表性 config（不是 72 個），預設約 3~4 小時。

用法
----
    python "run experiment/diagnose_after_seeding_fix.py"

結果輸出到 experiment result/diagnosis_after_seeding_fix_<timestamp>.csv
與同名 .md（人看的摘要），log 在 logs/diagnosis/<timestamp>/。
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

LOCAL_PYTHON_PACKAGE_CANDIDATES = [
    ROOT_DIR / ".codex_spreadsheet" / "python_packages",
    Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime"
    / "dependencies" / "python" / "Lib" / "site-packages",
]
if os.environ.get("CODEX_PRIMARY_PYTHON_PACKAGES"):
    LOCAL_PYTHON_PACKAGE_CANDIDATES.insert(
        0, Path(os.environ["CODEX_PRIMARY_PYTHON_PACKAGES"])
    )
for package_dir in reversed(LOCAL_PYTHON_PACKAGE_CANDIDATES):
    if package_dir.exists():
        sys.path.insert(0, str(package_dir))

os.chdir(ROOT_DIR)
for _p in (str(ROOT_DIR / "model core"), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as cfg  # noqa: E402
import logging_utils  # noqa: E402

# =============================================================================
# 參數區
# =============================================================================
SCALE = "small"          # 只跑 small；確認有效再推到 medium/large
MODEL = "SP+MCVaR"       # 只跑一個 model 維度就夠回答問題
SCENARIOS = 50
TIME_PERIODS = 8
TIME_LIMIT = 7200.0
MIP_GAP = 0.01           # 維持 1%，目的是「看它掉到哪」而不是真的要達成
RISK_ALPHA = 0.9
RISK_LAMBDA = 0.5

# 三個代表性 config：最弱的、最強的、以及作為 LP 下界基準的 Extensive
CASES = [
    {"name": "Extensive", "engine": "extensive",
     "ev": False, "seed": 0, "rounds": 0, "user": False, "pareto": False,
     "why": "提供根節點 LP 下界基準（Benders 收斂後理論上應等於此值）"},
    {"name": "BBC", "engine": "bbc",
     "ev": False, "seed": 0, "rounds": 0, "user": False, "pareto": False,
     "why": "沒有任何加速的對照組"},
    {"name": "BBC+WS+RS+UC+Pareto", "engine": "bbc",
     "ev": True, "seed": None, "rounds": None, "user": True, "pareto": True,
     "why": "全開；seeding 修正的效果主要看這個"},
]

RESULT_DIR = ROOT_DIR / "experiment result"
LOG_DIR = ROOT_DIR / "logs" / "diagnosis"

MCVAR_MODEL_PATH = ROOT_DIR / "model portal" / "mcvar bbc.py"
EXTENSIVE_MODEL_PATH = ROOT_DIR / "model portal" / "extensive_dro.py"

# 上一輪（S=30、舊 seeding 參數）的實測值，用來對照
PREVIOUS_RUN = {
    "Extensive":           {"ub": 33123533.9, "lb": 17865909.3, "gap": 46.06},
    "BBC":                 {"ub": 37377986.8, "lb":  9876489.1, "gap": 73.58},
    "BBC+WS+RS+UC+Pareto": {"ub": 25852742.5, "lb": 12539634.5, "gap": 51.50},
}


def load_portal(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scaled_instance_generation():
    original = cfg.generate_data
    cache: dict[str, object] = {}

    def _scaled(*args, **kwargs):
        kwargs.pop("sample_ratio", None)
        kwargs.pop("ccp_sample_size", None)
        scale = cfg.EXPERIMENT_SCALE
        if scale not in cache:
            cache[scale] = original(scale=scale)
        return cache[scale]

    cfg.generate_data = _scaled
    return original


def apply_case_config(case: dict) -> dict:
    is_ext = case.get("engine") == "extensive"
    seed = cfg.BENDERS_ROOT_SEED_ITERS if case["seed"] is None else case["seed"]
    rounds = cfg.BENDERS_ROOT_CUT_ROUNDS if case["rounds"] is None else case["rounds"]
    values = {
        "SCENARIOS": SCENARIOS,
        "TIME_PERIODS": TIME_PERIODS,
        "SP_TIME_LIMIT": TIME_LIMIT,
        "SP_MIP_GAP": MIP_GAP,
        "BENDERS_MULTI_CUT": True,
        "BENDERS_EV_WARM_START": case["ev"],
        "BENDERS_ROOT_SEED_ITERS": seed,
        "BENDERS_ROOT_CUT_ROUNDS": rounds,
        "BENDERS_USE_USER_CUTS": case["user"],
        "BENDERS_PARETO_ENABLED": case["pareto"],
        "BENDERS_MIPFOCUS": 0 if is_ext else 3,
        "BENDERS_HEURISTICS": 0.0 if is_ext else 0.05,
        "BENDERS_NUMERIC_FOCUS": 0 if is_ext else 1,
        "BENDERS_X_BRANCH_PRIORITY_ENABLED": not is_ext,
        "BENDERS_X_BRANCH_PRIORITY": 0 if is_ext else 10,
    }
    original = {k: getattr(cfg, k) for k in values}
    for k, v in values.items():
        setattr(cfg, k, v)
    return original


def main() -> int:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_run_dir = LOG_DIR / timestamp
    log_run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = RESULT_DIR / f"diagnosis_after_seeding_fix_{timestamp}.csv"
    md_path = RESULT_DIR / f"diagnosis_after_seeding_fix_{timestamp}.md"
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("plan/17 修正後的診斷實驗")
    print("=" * 78)
    counts = cfg.SCALE_PROFILES[SCALE]
    print(f"規模 : {SCALE}  I={counts['n_disaster']} J={counts['n_ccp']} "
          f"H={counts['n_hospital']}  S={SCENARIOS} T={TIME_PERIODS}")
    print(f"模型 : {MODEL}   時限 {TIME_LIMIT:.0f}s   gap 門檻 {MIP_GAP}")
    print("已調整的參數（相對上一輪）：")
    print(f"  BENDERS_ROOT_SEED_ITERS        300  → {cfg.BENDERS_ROOT_SEED_ITERS}")
    print(f"  BENDERS_ROOT_SEED_LB_REL_TOL   5e-4 → {cfg.BENDERS_ROOT_SEED_LB_REL_TOL:.0e}")
    print(f"  BENDERS_ROOT_SEED_STALL_ROUNDS  10  → {cfg.BENDERS_ROOT_SEED_STALL_ROUNDS}")
    print(f"  BENDERS_PARALLEL_ORACLES         5  → {cfg.BENDERS_PARALLEL_ORACLES}")
    print(f"  SCENARIOS                       30  → {SCENARIOS}")
    print(f"\n共 {len(CASES)} 個 case，最壞情況約 {len(CASES) * TIME_LIMIT / 3600:.0f} 小時")
    print(f"CSV : {csv_path}\nLogs: {log_run_dir}\n")

    ext_portal = load_portal(EXTENSIVE_MODEL_PATH, "diag_ext_portal")
    bbc_portal = load_portal(MCVAR_MODEL_PATH, "diag_bbc_portal")
    original_generate = scaled_instance_generation()
    original_scale = cfg.EXPERIMENT_SCALE
    cfg.EXPERIMENT_SCALE = SCALE

    rows: list[dict] = []
    try:
        for idx, case in enumerate(CASES, 1):
            print(f"\n[{idx}/{len(CASES)}] {case['name']}  — {case['why']}")
            saved = apply_case_config(case)
            log_path = log_run_dir / f"{idx:02d}_{case['name'].replace('+', '_plus_')}.log"
            start = time.time()
            row = {"config": case["name"], "status": "FAIL", "note": ""}
            try:
                with logging_utils.tee_output(log_path):
                    portal = ext_portal if case.get("engine") == "extensive" else bbc_portal
                    model, summary = portal.run_mcvar_model(
                        scenario_size=SCENARIOS, sample_ratio=1.0,
                        time_limit=TIME_LIMIT, mip_gap=MIP_GAP,
                        alpha=RISK_ALPHA, lam=RISK_LAMBDA, compute_kpis=False,
                    )
                # 取值來源與 batch_ablation_experiment.py 完全一致
                stats = summary.get("bbc_stats", {}) or {}
                first_stage = summary.get("first_stage") or {}
                opened = [j for j, v in (first_stage.get("X") or {}).items() if float(v) > 0.5]
                runtime = stats.get("runtime")
                row.update({
                    "status": "OK",
                    "ub": float(summary["objective"]),
                    "lb": float(summary["best_lb"]),
                    "gap_pct": float(summary["gap_pct"]),
                    "cpu_s": float(runtime) if runtime is not None else (time.time() - start),
                    "nodes": f"{float(getattr(model, 'NodeCount', float('nan'))):.0f}",
                    "seeded_lb": stats.get("root_seed_lb", "NA"),
                    "seed_iters_done": stats.get("root_seed_iters_done", "NA"),
                    "seed_stop_reason": stats.get("root_seed_stop_reason", "NA"),
                    "root_seed_time_s": stats.get("root_seed_time", "NA"),
                    "total_cuts": stats.get("cuts_added", "NA"),
                    "opened_ccps": len(opened),
                    "solver_status": stats.get("solver_status", "NA"),
                    "log": str(log_path),
                })
                try:
                    model.dispose()
                except Exception:  # noqa: BLE001
                    pass
                seed_t = row["root_seed_time_s"]
                seed_t = f"{seed_t:.0f}s" if isinstance(seed_t, (int, float)) else str(seed_t)
                print(f"  -> OK  UB={row['ub']:,.0f}  LB={row['lb']:,.0f}  "
                      f"gap={row['gap_pct']:.2f}%  開設 {row['opened_ccps']} 座  "
                      f"seeding={row['seed_iters_done']} 輪 / {seed_t}")
            except Exception as exc:  # noqa: BLE001
                row["note"] = f"{type(exc).__name__}: {exc}"
                print(f"  -> FAIL {row['note']}")
            finally:
                for k, v in saved.items():
                    setattr(cfg, k, v)
            rows.append(row)
            write_csv(csv_path, rows)
    finally:
        cfg.EXPERIMENT_SCALE = original_scale
        cfg.generate_data = original_generate

    write_report(md_path, rows)
    print("\n" + "=" * 78)
    print(f"完成。CSV: {csv_path}")
    print(f"      摘要: {md_path}")
    summarize(rows)
    return 0


FIELDS = ["config", "status", "ub", "lb", "gap_pct", "cpu_s", "nodes",
          "seeded_lb", "seed_iters_done", "seed_stop_reason", "root_seed_time_s",
          "total_cuts", "opened_ccps", "solver_status", "log", "note"]


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def summarize(rows: list[dict]) -> None:
    ok = {r["config"]: r for r in rows if r["status"] == "OK"}
    print("\n--- 對照上一輪（S=30、舊 seeding 參數）---")
    print(f"{'config':24}{'gap 上一輪':>12}{'gap 本輪':>11}{'LB 上一輪':>14}{'LB 本輪':>14}")
    for name, prev in PREVIOUS_RUN.items():
        cur = ok.get(name)
        if not cur:
            continue
        print(f"{name:24}{prev['gap']:>11.1f}%{cur['gap_pct']:>10.1f}%"
              f"{prev['lb']:>14,.0f}{cur['lb']:>14,.0f}")

    ext = ok.get("Extensive")
    full = ok.get("BBC+WS+RS+UC+Pareto")
    if ext and full:
        ratio = full["lb"] / ext["lb"] * 100 if ext["lb"] else 0
        print(f"\nQ1 — BBC 下界 / Extensive 根節點 LP 下界 = {ratio:.0f}%"
              f"（上一輪只有 56%，越接近 100% 越好）")
        best_ub = min(r["ub"] for r in ok.values())
        print(f"Q2 — 最佳 gap = {min(r['gap_pct'] for r in ok.values()):.1f}%")
        print(f"Q3 — 最佳 UB = {best_ub:,.0f}，Extensive LP 下界 = {ext['lb']:,.0f}"
              f" → optimum 落在這個區間內")


def write_report(path: Path, rows: list[dict]) -> None:
    lines = [
        "# 診斷實驗結果（plan/17 修正後）", "",
        f"規模 {SCALE}、模型 {MODEL}、S={SCENARIOS}、T={TIME_PERIODS}、"
        f"時限 {TIME_LIMIT:.0f}s、gap 門檻 {MIP_GAP}", "",
        "| config | UB | LB | gap | 開設座數 | seeding 輪數 | seeding 停止原因 | 節點數 |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for r in rows:
        if r["status"] != "OK":
            lines.append(f"| {r['config']} | FAIL | | | | | {r.get('note','')} | |")
            continue
        lines.append(
            f"| {r['config']} | {r['ub']:,.0f} | {r['lb']:,.0f} | {r['gap_pct']:.2f}% "
            f"| {r['opened_ccps']} | {r['seed_iters_done']} | {r['seed_stop_reason']} "
            f"| {r['nodes']} |"
        )
    lines += ["", "## 對照上一輪（S=30、舊 seeding 參數）", "",
              "| config | gap 上一輪 | gap 本輪 | LB 上一輪 | LB 本輪 |",
              "|---|---:|---:|---:|---:|"]
    ok = {r["config"]: r for r in rows if r["status"] == "OK"}
    for name, prev in PREVIOUS_RUN.items():
        cur = ok.get(name)
        if cur:
            lines.append(f"| {name} | {prev['gap']:.1f}% | {cur['gap_pct']:.1f}% "
                         f"| {prev['lb']:,.0f} | {cur['lb']:,.0f} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
