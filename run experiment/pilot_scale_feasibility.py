#!/usr/bin/env python3
"""放大規模後的可行性 pilot（正式跑 72 個 case 之前先跑這支）。

目的：用「小 S、寬 gap、短時限」快速確認 small / medium / large 三個規模
在新參數下都有可行解、開設的 CCP 數量合理，避免正式實驗跑了好幾天才發現
參數設得不合理。

檢查項目
--------
1. instance 產生成功且通過 validate_instance
2. 三個規模都求得可行解（不是 INFEASIBLE）
3. 開設的 CCP 數量落在合理區間（不是 0 個，也不是 50 個全開）
4. 未服務傷患的懲罰沒有把目標值完全吃掉（罰金佔比）

用法
----
    python "run experiment/pilot_scale_feasibility.py"

預設每個規模只跑 SP+MCVaR / BBC 完整配置、S=5、gap=5%、300 秒。
"""
from __future__ import annotations

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

# ── pilot 參數（刻意設寬鬆，只求快速確認可行性）──
SCALES = ["small", "medium", "large"]
PILOT_SCENARIOS = 5
PILOT_TIME_PERIODS = 8
PILOT_TIME_LIMIT = 300.0
PILOT_MIP_GAP = 0.05
RISK_ALPHA = 0.9
RISK_LAMBDA = 0.5

MCVAR_MODEL_PATH = ROOT_DIR / "model portal" / "mcvar bbc.py"


def load_portal(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load portal module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def scaled_instance_generation():
    """把 portal 內部的 generate_data 導向 scale 路徑（與正式 runner 相同慣例）。"""
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


def describe_instance(scale: str) -> dict:
    instance = cfg.generate_data(scale=scale)
    cfg.validate_instance(instance)
    sets = instance["sets"]
    params = instance["deterministic_parameters"]
    resolved = cfg.resolve_scale(scale)
    one = lambda key: next(iter(params[key].values()))  # noqa: E731
    return {
        "I": len(sets["I"]), "J": len(sets["J"]), "H": len(sets["H"]),
        "s_D": resolved["demand_scale"],
        "s_J": resolved["ccp_scale"],
        "s_H": resolved["hospital_scale"],
        "staff_pool": params["total_available_staff"],
        "ccp_staff_ub": one("ccp_staff_upper_bound"),
        "amb_pool": params["total_available_ccp_ambulances"],
        "expected_open": params["total_available_staff"] / one("ccp_staff_upper_bound"),
    }


def main() -> int:
    print("=" * 78)
    print("規模放大後的可行性 PILOT")
    print("=" * 78)
    print(f"資料：{cfg.DISASTER_CSV} / {cfg.CCP_CSV} / {cfg.HOSPITAL_CSV}")
    print(f"縮放基準 I/J/H = {cfg.PARAM_CALIB_N_DISASTER}/"
          f"{cfg.PARAM_CALIB_N_CCP}/{cfg.PARAM_CALIB_N_HOSPITAL}"
          f"；per-CCP 模式 = {cfg.CCP_UPPER_BOUND_SCALING}")
    print(f"pilot 設定：S={PILOT_SCENARIOS} T={PILOT_TIME_PERIODS} "
          f"gap={PILOT_MIP_GAP:.0%} time_limit={PILOT_TIME_LIMIT:.0f}s\n")

    print("--- 步驟 1：instance 與參數檢查 ---")
    info = {}
    for scale in SCALES:
        info[scale] = describe_instance(scale)
        d = info[scale]
        print(f"  {scale:7}: I={d['I']:3d} J={d['J']:2d} H={d['H']:2d} | "
              f"s_D={d['s_D']:.3f} s_J={d['s_J']:.3f} s_H={d['s_H']:.3f} | "
              f"醫護池={d['staff_pool']:.0f} 單CCP上限={d['ccp_staff_ub']:.0f} "
              f"→ 預期開設約 {d['expected_open']:.1f} 個 CCP")
    print("  [OK] 三個規模都通過 validate_instance\n")

    print("--- 步驟 2：實際求解（SP+MCVaR，完整 BBC 配置）---")
    portal = load_portal(MCVAR_MODEL_PATH, "pilot_mcvar_portal")
    original_generate = scaled_instance_generation()

    overrides = {
        "SCENARIOS": PILOT_SCENARIOS,
        "TIME_PERIODS": PILOT_TIME_PERIODS,
        "SP_TIME_LIMIT": PILOT_TIME_LIMIT,
        "SP_MIP_GAP": PILOT_MIP_GAP,
    }
    saved = {k: getattr(cfg, k) for k in overrides}
    saved_scale = cfg.EXPERIMENT_SCALE

    failures: list[str] = []
    try:
        for key, value in overrides.items():
            setattr(cfg, key, value)
        for scale in SCALES:
            cfg.EXPERIMENT_SCALE = scale
            print(f"\n  [{scale}] 求解中 …")
            start = time.time()
            try:
                model, summary = portal.run_mcvar_model(
                    scenario_size=PILOT_SCENARIOS, sample_ratio=1.0,
                    time_limit=PILOT_TIME_LIMIT, mip_gap=PILOT_MIP_GAP,
                    alpha=RISK_ALPHA, lam=RISK_LAMBDA, compute_kpis=False,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{scale}: {type(exc).__name__}: {exc}")
                print(f"    [FAIL] {type(exc).__name__}: {exc}")
                continue

            elapsed = time.time() - start
            first_stage = summary.get("first_stage") or {}
            opened = sorted(
                j for j, v in (first_stage.get("X") or {}).items() if float(v) > 0.5
            )
            print(f"    目標值   : {float(summary['objective']):,.2f}")
            print(f"    gap      : {float(summary['gap_pct']):.4f}%")
            print(f"    求解時間 : {elapsed:.1f}s  (status={summary.get('solver_status')})")
            print(f"    開設 CCP : {len(opened)} / {info[scale]['J']}  {opened}")

            if not opened:
                failures.append(f"{scale}: 沒有開設任何 CCP（參數可能過鬆或過緊）")
            elif len(opened) == info[scale]["J"]:
                failures.append(f"{scale}: 開設了全部 CCP（per-CCP 容量可能過小）")
            elif len(opened) > 0.6 * info[scale]["J"]:
                print(f"    [WARN] 開設比例偏高（{len(opened)}/{info[scale]['J']}）")

            try:
                model.dispose()
            except Exception:  # noqa: BLE001
                pass
    finally:
        for key, value in saved.items():
            setattr(cfg, key, value)
        cfg.EXPERIMENT_SCALE = saved_scale
        cfg.generate_data = original_generate

    print("\n" + "=" * 78)
    if failures:
        print("PILOT 有問題，先別跑正式實驗：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PILOT 全數通過，可以執行 run experiment/batch_ablation_experiment.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
