#!/usr/bin/env python3
"""
Batch DRO risk-parameter experiment runner（實驗一，plan/10）。

目前以 ellipsoidal-only 恢復模式執行 α × λ 網格（模型 = SP + MCVaR +
DRO，B&BC 引擎）。第一個 case 成功後才繼續其餘網格；若失敗則保留當下
CSV/Excel/log 並停止，避免浪費後續求解時間。
This script is only a runner. It temporarily changes values in the imported
config module while it runs each case, then restores them. It does not
rewrite config.py and does not change the model core logic.

輸出（experiment result/）：
* raw CSV（來源真相，每 case 一列，逐 case 重寫）
* Excel（目前 ellipsoidal-only，輸出兩分頁）：
    - "ellipsoidal"：明細表（欄位同 stress test：
      factor | I | J | H | S | T | obj_value | First Stage Decision |
      Best LB | Best UB | CPU Time(s) | num_vars | num_constrs | Nodes |
      Iteration | Final Gap(%) + risk/B&BC 統計欄）
    - "ellipsoidal_matrix"：
      α（列）× λ（欄）的 obj_value 矩陣（Jin et al. Table 4 格式），
      下方另附 CPU Time 與 Final Gap 矩陣
* first_stage/{test_id}.json：完整一階解（供 out-of-sample 等後續實驗重用）
* console：每 case 一行摘要；全部結束後印出 ellipsoidal α×λ 矩陣與單調性警告
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


# =============================================================================
# Parameter setting area
# =============================================================================

# ── 實驗網格（Jin et al. 2024 Table 4 的 α × λ 組合）─────────────────────────
AMBIGUITY_SETS = ["ellipsoidal"]
ALPHA_VALUES   = [0.5, 0.9]
LAMBDA_VALUES  = [0.3, 0.9]

# ── ambiguity scope（固定；box 需 ≤ 1/BASE_SCENARIOS，main() 會檢查）─────────
SCOPES = {
    "box":         0.01,
    "ellipsoidal": 0.0005,
    "polyhedral":  0.001,
}

# ── Fixed base settings ──────────────────────────────────────────────────────
BASE_SCENARIOS                    = 30
BASE_CCP_SAMPLE_SIZE              = None    # None = 全部 CCP
BASE_SAMPLE_RATIO                 = 1.0
BASE_TIME_PERIODS                 = 8
BASE_DEMAND_MULTIPLIER            = 1.0
BASE_ROAD_CAPACITY_MULTIPLIER     = 1.0
BASE_HOSPITAL_CAPACITY_MULTIPLIER = 1.0

# ── Solver settings ──────────────────────────────────────────────────────────
TIME_LIMIT   = 10800.0
MIP_GAP      = 1e-4     # 正式論文表採 0.01% relative gap，降低參數敏感度比較的求解誤差
COMPUTE_KPIS = False    # 實驗一不需 KPI 重解（省時）；要 KPI 改 True

# Full-size ellipsoidal safe mode: fractional root solutions can satisfy the
# master only within feasibility tolerance, then become infeasible when every
# first-stage value is fixed exactly in a scenario oracle.  Keep the exact
# MIPSOL lazy-cut path, but do not evaluate fractional root/core-point values.
BENDERS_ROOT_SEED_ITERS = 0
BENDERS_ROOT_CUT_ROUNDS = 0
BENDERS_USE_USER_CUTS   = False
BENDERS_PARETO_ENABLED  = False

# ── Output settings ──────────────────────────────────────────────────────────
RESULT_PREFIX   = "DRO_alpha_lambda_ellipsoidal"
LOG_SUBDIR_NAME = "dro alpha lambda"
STOP_ON_ERROR   = False   # 單一 case 失敗記 FAIL 續跑，不中斷整批
REQUIRE_FIRST_CASE_SUCCESS = True  # 首 case 是正式規模 pilot；失敗就停止本批


# =============================================================================
# Setup
# =============================================================================
ROOT_DIR   = Path(__file__).resolve().parents[1]
LOG_DIR    = ROOT_DIR / "logs"
LOG_SUBDIR = LOG_DIR / LOG_SUBDIR_NAME
RESULT_DIR = ROOT_DIR / "experiment result"
FS_DIR     = RESULT_DIR / "first_stage"

os.chdir(ROOT_DIR)
for _p in (str(ROOT_DIR / "model core"), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as cfg  # noqa: E402

DRO_MODEL_PATH = ROOT_DIR / "model portal" / "dro bbc.py"

FIELDNAMES = [
    "test_id",
    "ambiguity_set",
    "alpha",
    "lambda",
    "scope",
    "factor",
    "I", "J", "H", "S", "T",
    "obj_value",
    "first_stage_decision",
    "best_lb",
    "best_ub",
    "cpu_s",
    "wall_s",
    "num_vars",
    "num_constrs",
    "nodes",
    "iterations",
    "gap_pct",
    # ---- risk 統計（由 summary["risk"] 取得）----
    "n_opened_ccp",
    "sum_V",
    "sum_U",
    "sum_Y",
    "first_stage_cost",
    "expected_Q",
    "VaR_phi",
    "CVaR",
    "MCVaR",
    "WMCVaR",
    "worst_p_max_dev",
    # ---- B&BC 引擎統計 ----
    "engine",
    "total_cuts",
    "seed_cuts",
    "lazy_cuts",
    "user_cuts",
    "root_seed_iters_done",
    "root_seed_lb",
    "root_seed_stop_reason",
    "root_seed_time_s",
    "root_cut_rounds_done",
    "parallel_oracles",
    "oracle_solves",
    "incumbent_evals",
    "callback_time_s",
    "solver_status",
    "log_path",
    "status",
    "note",
]


# =============================================================================
# Helpers
# =============================================================================
def fmt_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def blank_row() -> dict[str, Any]:
    return {key: "NA" for key in FIELDNAMES}


def write_results(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return max(0, sum(1 for row in csv.reader(f) if any(row)) - 1)


def estimate_counts() -> dict[str, int]:
    full_i = csv_row_count(ROOT_DIR / "data" / cfg.DISASTER_CSV)
    full_j = csv_row_count(ROOT_DIR / "data" / cfg.CCP_CSV)
    full_h = csv_row_count(ROOT_DIR / "data" / cfg.HOSPITAL_CSV)
    ratio = float(BASE_SAMPLE_RATIO)
    ccp = BASE_CCP_SAMPLE_SIZE
    return {
        "I": max(1, math.ceil(full_i * ratio)) if ratio < 1.0 else full_i,
        "J": min(ccp, full_j) if ccp is not None else full_j,
        "H": max(1, math.ceil(full_h * ratio)) if ratio < 1.0 else full_h,
    }


def first_stage_string(fs: dict[str, Any] | None) -> str:
    """把一階解 dict 轉成與 stress test 相同格式的多行字串。"""
    if not fs:
        return "NA"
    lines = []
    ys_by_j: dict[str, float] = {}
    for (h, j), val in fs["Y"].items():
        ys_by_j[j] = ys_by_j.get(j, 0.0) + float(val)
    for j in sorted(fs["X"]):
        if float(fs["X"][j]) > 0.5:
            lines.append(
                f"CCP {j:4s} -> X: 1, Staff(V): {float(fs['V'][j]):2.0f}, "
                f"Amb(U): {float(fs['U'][j]):2.0f}, "
                f"MedicalSupply(Y): {ys_by_j.get(j, 0.0):.2f}"
            )
    return "\n".join(lines) if lines else "none opened"


def first_stage_totals(fs: dict[str, Any] | None) -> dict[str, Any]:
    if not fs:
        return {"n_opened_ccp": "NA", "sum_V": "NA", "sum_U": "NA", "sum_Y": "NA"}
    return {
        "n_opened_ccp": sum(1 for v in fs["X"].values() if float(v) > 0.5),
        "sum_V": sum(float(v) for v in fs["V"].values()),
        "sum_U": sum(float(v) for v in fs["U"].values()),
        "sum_Y": sum(float(v) for v in fs["Y"].values()),
    }


def save_first_stage_json(test_id: str, fs: dict[str, Any] | None) -> None:
    if not fs:
        return
    FS_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {
        "X": {j: float(v) for j, v in fs["X"].items()},
        "V": {j: float(v) for j, v in fs["V"].items()},
        "U": {j: float(v) for j, v in fs["U"].items()},
        "Y": {f"{h},{j}": float(v) for (h, j), v in fs["Y"].items()},
    }
    with (FS_DIR / f"{test_id}.json").open("w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)


def snapshot_logs() -> set[Path]:
    if not LOG_DIR.exists():
        return set()
    return {p.resolve() for p in LOG_DIR.glob("*.log")}


def newest_created_log(before: set[Path]) -> Path | None:
    if not LOG_DIR.exists():
        return None
    created = [p for p in LOG_DIR.glob("*.log") if p.resolve() not in before]
    if not created:
        return None
    return max(created, key=lambda p: p.stat().st_mtime)


def move_log_to_subdir(log_path: Path | None) -> Path | None:
    if log_path is None or not log_path.exists():
        return log_path
    LOG_SUBDIR.mkdir(parents=True, exist_ok=True)
    dest = LOG_SUBDIR / log_path.name
    shutil.move(str(log_path), str(dest))
    return dest


# =============================================================================
# Context managers (temporarily patch config, restore on exit)
# =============================================================================
@contextmanager
def temporary_config():
    keys: dict[str, Any] = {
        "SCENARIOS":                    BASE_SCENARIOS,
        "TIME_PERIODS":                 BASE_TIME_PERIODS,
        "SAMPLE_RATIO":                 BASE_SAMPLE_RATIO,
        "SP_SAMPLE_RATIO":              BASE_SAMPLE_RATIO,
        "DEMAND_MULTIPLIER":            BASE_DEMAND_MULTIPLIER,
        "ROAD_CAPACITY_MULTIPLIER":     BASE_ROAD_CAPACITY_MULTIPLIER,
        "HOSPITAL_CAPACITY_MULTIPLIER": BASE_HOSPITAL_CAPACITY_MULTIPLIER,
        "SP_TIME_LIMIT":                TIME_LIMIT,
        "SP_MIP_GAP":                   MIP_GAP,
        "BENDERS_ROOT_SEED_ITERS":      BENDERS_ROOT_SEED_ITERS,
        "BENDERS_ROOT_CUT_ROUNDS":      BENDERS_ROOT_CUT_ROUNDS,
        "BENDERS_USE_USER_CUTS":        BENDERS_USE_USER_CUTS,
        "BENDERS_PARETO_ENABLED":       BENDERS_PARETO_ENABLED,
    }
    if hasattr(cfg, "CCP_SAMPLE_SIZE"):
        keys["CCP_SAMPLE_SIZE"] = BASE_CCP_SAMPLE_SIZE
    original = {key: getattr(cfg, key) for key in keys}
    try:
        for key, value in keys.items():
            setattr(cfg, key, value)
        yield
    finally:
        for key, value in original.items():
            setattr(cfg, key, value)


@contextmanager
def patched_generate_data():
    original = cfg.generate_data

    def _patched(*args, **kwargs):
        kwargs.setdefault("ccp_sample_size", BASE_CCP_SAMPLE_SIZE)
        return original(*args, **kwargs)

    cfg.generate_data = _patched
    try:
        yield
    finally:
        cfg.generate_data = original


@contextmanager
def patched_generate_scenarios():
    original = cfg.generate_scenarios

    def _patched(*args, **kwargs):
        kwargs.setdefault("demand_multiplier",            BASE_DEMAND_MULTIPLIER)
        kwargs.setdefault("road_capacity_multiplier",     BASE_ROAD_CAPACITY_MULTIPLIER)
        kwargs.setdefault("hospital_capacity_multiplier", BASE_HOSPITAL_CAPACITY_MULTIPLIER)
        kwargs.setdefault("num_periods",                  BASE_TIME_PERIODS)
        return original(*args, **kwargs)

    cfg.generate_scenarios = _patched
    try:
        yield
    finally:
        cfg.generate_scenarios = original


# =============================================================================
# Core run logic
# =============================================================================
def load_dro_module() -> Any:
    spec = importlib.util.spec_from_file_location("dro_bbc_portal", DRO_MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_one_case(
    dro_module: Any,
    run_idx: int,
    total_runs: int,
    aset: str,
    alpha: float,
    lam: float,
    counts: dict[str, int],
) -> dict[str, Any]:
    scope = SCOPES[aset]
    test_id = f"{aset}_a{alpha}_l{lam}".replace(".", "p")
    row = blank_row()
    row.update({
        "test_id":       test_id,
        "ambiguity_set": aset,
        "alpha":         alpha,
        "lambda":        lam,
        "scope":         scope,
        "factor":        f"{aset}, alpha={alpha}, lambda={lam}",
        "I": counts["I"], "J": counts["J"], "H": counts["H"],
        "S": BASE_SCENARIOS, "T": BASE_TIME_PERIODS,
        "status": "RUNNING",
        "note": "",
    })

    print(f"\n[{run_idx}/{total_runs}] {test_id}"
          f" | scope={scope} | S={BASE_SCENARIOS}, T={BASE_TIME_PERIODS}")

    logs_before = snapshot_logs()
    wall_start = time.time()
    model = None
    summary = None
    log_path = None
    try:
        try:
            with (
                temporary_config(),
                patched_generate_data(),
                patched_generate_scenarios(),
            ):
                model, summary = dro_module.run_dro_model(
                    ambiguity_set=aset,
                    scenario_size=BASE_SCENARIOS,
                    sample_ratio=BASE_SAMPLE_RATIO,
                    time_limit=TIME_LIMIT,
                    mip_gap=MIP_GAP,
                    alpha=alpha,
                    lam=lam,
                    scope=scope,
                    compute_kpis=COMPUTE_KPIS,
                )
        finally:
            log_path = move_log_to_subdir(newest_created_log(logs_before))
            row["log_path"] = str(log_path) if log_path else "NA"
            row["wall_s"] = f"{time.time() - wall_start:.2f}"
    except Exception as exc:  # noqa: BLE001
        row["status"] = "FAIL"
        row["note"] = f"{type(exc).__name__}: {exc}"
        print(f"  -> FAIL: {row['note']}")
        if STOP_ON_ERROR:
            raise
        return row

    if model is None or summary is None:
        row["status"] = "FAIL"
        row["note"] = "no feasible solution (see log)"
        print(f"  -> FAIL: {row['note']}")
        return row

    fs = summary.get("first_stage")
    risk = summary.get("risk", {})
    st = summary.get("bbc_stats", {})

    row.update({
        "obj_value": f"{summary['objective']:.4f}",
        "first_stage_decision": first_stage_string(fs),
        "best_lb":  f"{summary['best_lb']:.4f}",
        "best_ub":  f"{summary['objective']:.4f}",
        "cpu_s":    f"{st.get('runtime', float('nan')):.2f}",
        "num_vars":    getattr(model, "NumVars", "NA"),
        "num_constrs": getattr(model, "NumConstrs", "NA"),
        "nodes":       f"{getattr(model, 'NodeCount', float('nan')):.0f}",
        "iterations":  f"{getattr(model, 'IterCount', float('nan')):.0f}",
        "gap_pct":  f"{summary['gap_pct']:.4f}",
        "first_stage_cost": f"{summary.get('first_stage_cost', float('nan')):.2f}",
        "expected_Q": f"{risk.get('expected_Q', float('nan')):.2f}",
        "VaR_phi":    f"{risk.get('phi_star_VaR', float('nan')):.2f}",
        "CVaR":       f"{risk.get('CVaR', float('nan')):.2f}",
        "MCVaR":      f"{risk.get('MCVaR', float('nan')):.2f}",
        "WMCVaR":     f"{risk.get('WMCVaR', float('nan')):.2f}",
        "worst_p_max_dev": f"{risk.get('worst_p_max_dev', float('nan')):.6f}",
        "engine":               st.get("engine", "NA"),
        "total_cuts":           st.get("cuts_added", "NA"),
        "seed_cuts":            st.get("seed_cuts_added", "NA"),
        "lazy_cuts":            st.get("lazy_cuts_added", "NA"),
        "user_cuts":            st.get("user_cuts_added", "NA"),
        "root_seed_iters_done": st.get("root_seed_iters_done", "NA"),
        "root_seed_lb":         st.get("root_seed_lb", "NA"),
        "root_seed_stop_reason": st.get("root_seed_stop_reason", "NA"),
        "root_seed_time_s":     st.get("root_seed_time", "NA"),
        "root_cut_rounds_done": st.get("root_cut_rounds_done", "NA"),
        "parallel_oracles":     st.get("parallel_oracles", "NA"),
        "oracle_solves":        st.get("oracle_solves", "NA"),
        "incumbent_evals":      st.get("incumbent_evals", "NA"),
        "callback_time_s":      st.get("callback_time", "NA"),
        "solver_status":        st.get("solver_status", "NA"),
        "status": "OK",
    })
    row.update(first_stage_totals(fs))
    save_first_stage_json(test_id, fs)

    print(f"  -> OK obj={row['obj_value']} gap={row['gap_pct']}% "
          f"cpu={row['cpu_s']}s opened={row['n_opened_ccp']}")
    return row


# =============================================================================
# Excel export（六分頁：三明細 + 三矩陣）
# =============================================================================
XLSX_DETAIL_COLUMNS = [
    ("factor",               "factor"),
    ("|I| Disaster",         "I"),
    ("|J| CCP",              "J"),
    ("|H| Hosp",             "H"),
    ("|S| Scen",             "S"),
    ("|T| Per",              "T"),
    ("obj_value",            "obj_value"),
    ("First Stage Decision", "first_stage_decision"),
    ("Best LB",              "best_lb"),
    ("Best UB",              "best_ub"),
    ("CPU Time(s)",          "cpu_s"),
    ("num_vars",             "num_vars"),
    ("num_constrs",          "num_constrs"),
    ("Nodes",                "nodes"),
    ("Iteration",            "iterations"),
    ("Final Gap(%)",         "gap_pct"),
    ("alpha",                "alpha"),
    ("lambda",               "lambda"),
    ("scope",                "scope"),
    ("Opened CCPs",          "n_opened_ccp"),
    ("Sum V",                "sum_V"),
    ("Sum U",                "sum_U"),
    ("Sum Y",                "sum_Y"),
    ("First Stage Cost",     "first_stage_cost"),
    ("E[Q] (p0)",            "expected_Q"),
    ("VaR (phi*)",           "VaR_phi"),
    ("CVaR (p0)",            "CVaR"),
    ("MCVaR (p0)",           "MCVaR"),
    ("WMCVaR",               "WMCVaR"),
    ("worst_p_max_dev",      "worst_p_max_dev"),
    ("Total Cuts",           "total_cuts"),
    ("Oracle Solves",        "oracle_solves"),
    ("Solver Status",        "solver_status"),
    ("Status",               "status"),
]

_TEXT_KEYS = ("factor", "first_stage_decision", "engine", "solver_status",
              "status", "root_seed_stop_reason", "log_path", "note",
              "ambiguity_set", "test_id")


def _matrix_value(rows: list[dict[str, Any]], aset: str, alpha: float,
                  lam: float, key: str) -> Any:
    for row in rows:
        if (row.get("ambiguity_set") == aset
                and row.get("alpha") == alpha and row.get("lambda") == lam):
            if row.get("status") != "OK":
                return row.get("status", "NA")
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                return row.get(key, "NA")
    return None  # not run yet


def export_xlsx(rows: list[dict[str, Any]], xlsx_path: Path) -> None:
    """CSV 為來源真相；匯出失敗（openpyxl 未裝、檔案被開啟）不中斷實驗。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        print("  [xlsx] openpyxl 未安裝，略過 Excel 匯出（pip install openpyxl）")
        return
    try:
        xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        wb.remove(wb.active)
        header_fill = PatternFill("solid", fgColor="2E74B5")
        header_font = Font(bold=True, color="FFFFFF")

        # ---- 三個明細分頁 -------------------------------------------------
        for aset in AMBIGUITY_SETS:
            ws = wb.create_sheet(aset)
            for col_idx, (title, _key) in enumerate(XLSX_DETAIL_COLUMNS, start=1):
                cell = ws.cell(row=1, column=col_idx, value=title)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center",
                                           vertical="center", wrap_text=True)
            r_idx = 2
            for row in rows:
                if row.get("ambiguity_set") != aset:
                    continue
                for col_idx, (_title, key) in enumerate(XLSX_DETAIL_COLUMNS, start=1):
                    value = row.get(key, "NA")
                    if key not in _TEXT_KEYS:
                        try:
                            value = float(value)
                        except (TypeError, ValueError):
                            pass
                    cell = ws.cell(row=r_idx, column=col_idx, value=value)
                    if key == "first_stage_decision":
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                r_idx += 1
            ws.column_dimensions["A"].width = 30
            ws.column_dimensions["H"].width = 62   # First Stage Decision

        # ---- 三個矩陣分頁（Jin et al. Table 4 格式）-----------------------
        blocks = [("obj_value", "obj_value"), ("CPU Time(s)", "cpu_s"),
                  ("Final Gap(%)", "gap_pct")]
        for aset in AMBIGUITY_SETS:
            ws = wb.create_sheet(f"{aset}_matrix")
            r = 1
            for block_title, key in blocks:
                cell = ws.cell(row=r, column=1, value=block_title)
                cell.font = Font(bold=True)
                for c_idx, lam in enumerate(LAMBDA_VALUES, start=2):
                    cell = ws.cell(row=r, column=c_idx, value=f"λ = {lam:g}")
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center")
                r += 1
                for alpha in ALPHA_VALUES:
                    ws.cell(row=r, column=1, value=f"α = {alpha:g}").font = Font(bold=True)
                    for c_idx, lam in enumerate(LAMBDA_VALUES, start=2):
                        val = _matrix_value(rows, aset, alpha, lam, key)
                        ws.cell(row=r, column=c_idx, value=val)
                    r += 1
                r += 1   # 區塊間空一列
            ws.column_dimensions["A"].width = 14
            for c_idx in range(2, len(LAMBDA_VALUES) + 2):
                ws.column_dimensions[chr(ord("A") + c_idx - 1)].width = 16

        wb.save(xlsx_path)
    except Exception as exc:  # noqa: BLE001
        print(f"  [xlsx] Excel 匯出失敗（不影響 CSV）: {exc}")


# =============================================================================
# Console 矩陣與單調性檢查
# =============================================================================
def print_matrices(rows: list[dict[str, Any]]) -> None:
    for aset in AMBIGUITY_SETS:
        print("\n" + "=" * 70)
        print(f"OBJECTIVE VALUE MATRIX — {aset} ambiguity set "
              f"(scope={SCOPES[aset]})")
        header = "          " + "".join(f"λ = {lam:<12g}" for lam in LAMBDA_VALUES)
        print(header)
        for alpha in ALPHA_VALUES:
            cells = []
            for lam in LAMBDA_VALUES:
                val = _matrix_value(rows, aset, alpha, lam, "obj_value")
                if isinstance(val, float):
                    cells.append(f"{val:<16.2f}")
                else:
                    cells.append(f"{str(val):<16s}")
            print(f"α = {alpha:<6g}" + "".join(cells))


def monotonicity_warnings(rows: list[dict[str, Any]]) -> list[str]:
    """趨勢檢查：固定 α 時 obj 隨 λ 遞增、固定 λ 時隨 α 遞增（容差 = gap）。"""
    warnings = []
    for aset in AMBIGUITY_SETS:
        for alpha in ALPHA_VALUES:
            vals = [_matrix_value(rows, aset, alpha, lam, "obj_value")
                    for lam in LAMBDA_VALUES]
            nums = [v for v in vals if isinstance(v, float)]
            for i in range(1, len(nums)):
                tol = abs(nums[i]) * MIP_GAP + abs(nums[i - 1]) * MIP_GAP
                if nums[i] < nums[i - 1] - tol:
                    warnings.append(
                        f"{aset} α={alpha}: obj 隨 λ 下降超過 gap 容差 "
                        f"({nums[i - 1]:.2f} -> {nums[i]:.2f})"
                    )
        for lam in LAMBDA_VALUES:
            vals = [_matrix_value(rows, aset, alpha, lam, "obj_value")
                    for alpha in ALPHA_VALUES]
            nums = [v for v in vals if isinstance(v, float)]
            for i in range(1, len(nums)):
                tol = abs(nums[i]) * MIP_GAP + abs(nums[i - 1]) * MIP_GAP
                if nums[i] < nums[i - 1] - tol:
                    warnings.append(
                        f"{aset} λ={lam}: obj 隨 α 下降超過 gap 容差 "
                        f"({nums[i - 1]:.2f} -> {nums[i]:.2f})"
                    )
    return warnings


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    if SCOPES["box"] > 1.0 / BASE_SCENARIOS + 1e-12:
        raise ValueError(
            f"box scope {SCOPES['box']} > 1/S = {1.0 / BASE_SCENARIOS:.6f}；"
            f"等權重下 box ambiguity set 需 ε̄_B ≤ 1/S，請調小 SCOPES['box']。"
        )

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path  = RESULT_DIR / f"{RESULT_PREFIX}_raw_{timestamp}.csv"
    xlsx_path = RESULT_DIR / f"{RESULT_PREFIX}_{timestamp}.xlsx"

    cases = [(aset, alpha, lam)
             for aset in AMBIGUITY_SETS
             for alpha in ALPHA_VALUES
             for lam in LAMBDA_VALUES]
    counts = estimate_counts()

    print("=" * 70)
    print("BATCH DRO RISK-PARAMETER EXPERIMENT (實驗一)")
    print("=" * 70)
    print(f"sets={AMBIGUITY_SETS}")
    print(f"alpha={ALPHA_VALUES}")
    print(f"lambda={LAMBDA_VALUES}")
    print(f"scopes={SCOPES}")
    print(f"S={BASE_SCENARIOS} T={BASE_TIME_PERIODS} "
          f"sample_ratio={BASE_SAMPLE_RATIO} ccp={BASE_CCP_SAMPLE_SIZE}")
    print(f"time_limit={TIME_LIMIT} mip_gap={MIP_GAP} cases={len(cases)}")
    print("oracle_mode=integer-incumbent safe mode "
          f"(root_seed_iters={BENDERS_ROOT_SEED_ITERS}, "
          f"root_cut_rounds={BENDERS_ROOT_CUT_ROUNDS}, "
          f"user_cuts={BENDERS_USE_USER_CUTS}, "
          f"pareto={BENDERS_PARETO_ENABLED})")
    print(f"CSV   : {csv_path}")
    print(f"Excel : {xlsx_path}")

    dro_module = load_dro_module()
    rows: list[dict[str, Any]] = []
    for idx, (aset, alpha, lam) in enumerate(cases, start=1):
        row = run_one_case(dro_module, idx, len(cases), aset, alpha, lam, counts)
        rows.append(row)
        write_results(csv_path, rows)     # 每 case 跑完立即重寫（可中斷續看）
        export_xlsx(rows, xlsx_path)
        if idx == 1 and REQUIRE_FIRST_CASE_SUCCESS and row.get("status") != "OK":
            print("\n[ABORT] 第一個 ellipsoidal pilot 失敗；已保留 CSV/Excel/log，"
                  f"不執行其餘 {len(cases) - 1} cases。")
            break
        if idx == 1 and REQUIRE_FIRST_CASE_SUCCESS:
            print(f"\n[PILOT PASS] 第一個 ellipsoidal case 成功，"
                  f"繼續其餘 {len(cases) - 1} cases。")

    print_matrices(rows)
    warnings = monotonicity_warnings(rows)
    print("\n" + "-" * 70)
    n_ok = sum(1 for r in rows if r.get("status") == "OK")
    print(f"Done: {n_ok}/{len(rows)} cases OK.")
    if warnings:
        print("趨勢警告（obj 未隨 α/λ 單調遞增，超出 gap 容差）：")
        for w in warnings:
            print(f"  [WARN] {w}")
    else:
        print("趨勢檢查通過：obj 隨 α、λ 單調遞增（gap 容差內）。")
    print(f"CSV   : {csv_path}")
    print(f"Excel : {xlsx_path}")


if __name__ == "__main__":
    main()
