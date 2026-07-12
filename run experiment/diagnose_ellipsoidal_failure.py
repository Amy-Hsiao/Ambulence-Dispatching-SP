#!/usr/bin/env python3
"""快速定位 full-size ellipsoidal B&BC 失敗階段。

先驗證原始完整 root-seeding 路徑，再執行四個隔離測試；每個測試在
root seeding 或第一次 MIPSOL 後主動停止，
不等待完整模型收斂。所有 stdout、stderr、例外 traceback 與結論寫入單一 log。
正常實驗不會啟用 lshaped_core 的 diagnostic early-stop 參數。
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any


# =============================================================================
# Parameter setting area（重現使用者提供的失敗 case）
# =============================================================================

SCENARIOS = 30
TIME_PERIODS = 8
MASTER_SEED = 42
SAMPLE_RATIO = 1.0
CCP_SAMPLE_SIZE = None
DEMAND_MULTIPLIER = 1.0
ROAD_CAPACITY_MULTIPLIER = 1.0
HOSPITAL_CAPACITY_MULTIPLIER = 1.0
TIME_LIMIT_PER_TEST = 300.0   # safety cap；通常 early stop 會更早結束
MIP_GAP = 0.01                # 沿用失敗 log；診斷不需解到正式論文 gap
ALPHA = 0.9
LAMBDA = 0.3
A_E = 0.0005
PARALLEL_ORACLES = 5


ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "logs" / "ellipsoidal diagnostics"
os.chdir(ROOT_DIR)
for _p in (str(ROOT_DIR / "model core"), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as cfg  # noqa: E402
import logging_utils  # noqa: E402
import lshaped_core  # noqa: E402
import risk_core  # noqa: E402


TESTS = [
    {
        "id": "T0_original_root_seed",
        "purpose": "原始 Pareto+parallel 配置跑一輪；直接驗證修正後完整加速路徑",
        "root_seed_iters": 1,
        "parallel_oracles": PARALLEL_ORACLES,
        "use_user_cuts": True,
        "root_cut_rounds": 15,
        "pareto_enabled": True,
        "stop_after_root": True,
        "stop_after_incumbent": False,
    },
    {
        "id": "T1_pareto_off",
        "purpose": "關閉 Pareto；判斷是否為 core-point/Pareto oracle",
        "root_seed_iters": 1,
        "parallel_oracles": PARALLEL_ORACLES,
        "use_user_cuts": True,
        "root_cut_rounds": 15,
        "pareto_enabled": False,
        "stop_after_root": True,
        "stop_after_incumbent": False,
    },
    {
        "id": "T2_pareto_off_parallel1",
        "purpose": "另關閉 parallel oracle；判斷 environment/thread 問題",
        "root_seed_iters": 1,
        "parallel_oracles": 1,
        "use_user_cuts": True,
        "root_cut_rounds": 15,
        "pareto_enabled": False,
        "stop_after_root": True,
        "stop_after_incumbent": False,
    },
    {
        "id": "T3_root_seeding_off",
        "purpose": "關閉 root seeding；測到第一次 MIPSOL oracle 評估",
        "root_seed_iters": 0,
        "parallel_oracles": PARALLEL_ORACLES,
        "use_user_cuts": True,
        "root_cut_rounds": 15,
        "pareto_enabled": True,
        "stop_after_root": False,
        "stop_after_incumbent": True,
    },
    {
        "id": "T4_root_seeding_and_usercuts_off",
        "purpose": "再關閉 root user cuts；只保留 EV + MIPSOL lazy cuts",
        "root_seed_iters": 0,
        "parallel_oracles": PARALLEL_ORACLES,
        "use_user_cuts": False,
        "root_cut_rounds": 0,
        "pareto_enabled": False,
        "stop_after_root": False,
        "stop_after_incumbent": True,
    },
]


@contextmanager
def temporary_config():
    values = {
        "SCENARIOS": SCENARIOS,
        "TIME_PERIODS": TIME_PERIODS,
        "MASTER_SEED": MASTER_SEED,
        "SAMPLE_RATIO": SAMPLE_RATIO,
        "SP_SAMPLE_RATIO": SAMPLE_RATIO,
        "DEMAND_MULTIPLIER": DEMAND_MULTIPLIER,
        "ROAD_CAPACITY_MULTIPLIER": ROAD_CAPACITY_MULTIPLIER,
        "HOSPITAL_CAPACITY_MULTIPLIER": HOSPITAL_CAPACITY_MULTIPLIER,
        "SP_TIME_LIMIT": TIME_LIMIT_PER_TEST,
        "SP_MIP_GAP": MIP_GAP,
        "BENDERS_MULTI_CUT": True,
        "BENDERS_EV_WARM_START": True,
    }
    if hasattr(cfg, "CCP_SAMPLE_SIZE"):
        values["CCP_SAMPLE_SIZE"] = CCP_SAMPLE_SIZE
    old = {key: getattr(cfg, key) for key in values}
    try:
        for key, value in values.items():
            setattr(cfg, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(cfg, key, value)


def run_test(instance: dict[str, Any], selected_scenarios: list[str],
             risk_cfg: dict[str, Any], test: dict[str, Any]) -> dict[str, Any]:
    print("\n" + "=" * 88)
    print(f"START {test['id']}: {test['purpose']}")
    print("settings=" + repr({k: v for k, v in test.items() if k not in {"purpose"}}))
    print("=" * 88)
    started = time.time()
    result = None
    master = None
    try:
        result = lshaped_core.solve_bbc(
            instance,
            selected_scenarios,
            time_limit=TIME_LIMIT_PER_TEST,
            mip_gap=MIP_GAP,
            multi_cut=True,
            root_seed_iters=test["root_seed_iters"],
            root_cut_rounds=test["root_cut_rounds"],
            parallel_oracles=test["parallel_oracles"],
            use_user_cuts=test["use_user_cuts"],
            ev_warm_start=True,
            pareto_enabled=test["pareto_enabled"],
            diagnostic_stop_after_root_seeding=test["stop_after_root"],
            diagnostic_stop_after_first_incumbent=test["stop_after_incumbent"],
            verbose=True,
            risk_cfg=risk_cfg,
        )
        master = result.get("master")
        expected_stop = (
            result.get("diagnostic_stop") == "after_root_seeding"
            if test["stop_after_root"]
            else bool(result.get("diagnostic_first_incumbent_reached"))
        )
        outcome = "PASS" if expected_stop else "INCONCLUSIVE"
        print(
            f"RESULT {test['id']}: {outcome} | solver_status={result.get('status')} "
            f"diagnostic_stop={result.get('diagnostic_stop')} "
            f"root_iters={result.get('root_seed_iters_done')} "
            f"incumbent_evals={result.get('incumbent_evals')} "
            f"elapsed={time.time() - started:.2f}s"
        )
        return {
            "id": test["id"], "outcome": outcome,
            "message": result.get("status"),
            "diagnostic_stop": result.get("diagnostic_stop"),
            "elapsed": time.time() - started,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"RESULT {test['id']}: FAIL | {type(exc).__name__}: {exc}")
        print("TRACEBACK BEGIN")
        traceback.print_exc()
        print("TRACEBACK END")
        return {
            "id": test["id"], "outcome": "FAIL",
            "message": f"{type(exc).__name__}: {exc}",
            "diagnostic_stop": None,
            "elapsed": time.time() - started,
        }
    finally:
        if master is not None:
            try:
                master.dispose()
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] master.dispose failed: {exc}")


def print_diagnosis(results: list[dict[str, Any]]) -> None:
    by_id = {row["id"]: row for row in results}
    passed = lambda test_id: by_id[test_id]["outcome"] == "PASS"  # noqa: E731
    print("\n" + "#" * 88)
    print("AUTOMATIC DIAGNOSIS")
    print("#" * 88)
    if passed("T0_original_root_seed"):
        print("T0 PASS：原始 Pareto+parallel root seeding 已通過；fractional WMCVaR 修正有效且加速路徑保留。")
    elif passed("T1_pareto_off"):
        print("T0 FAIL / T1 PASS：standard root seeding 可行，剩餘問題指向 Pareto core-point evaluation。")
    elif passed("T2_pareto_off_parallel1"):
        print("T1 FAIL / T2 PASS：高度指向 parallel oracle environment/thread 問題。")
    elif passed("T3_root_seeding_off"):
        print("T1/T2 FAIL / T3 PASS：高度指向 root-seeding fractional oracle；正式 MISOCP 可進入 MIPSOL。")
    elif passed("T4_root_seeding_and_usercuts_off"):
        print("T3 FAIL / T4 PASS：高度指向 root MIPNODE user cuts/Pareto evaluation。")
    else:
        print("所有測試均未 PASS：問題位於共同路徑（EV、MIPSOL lazy oracle、license/數值）或 safety time limit。")
    print("\nPer-test summary:")
    for row in results:
        print(
            f"- {row['id']}: {row['outcome']} | {row['message']} | "
            f"stop={row['diagnostic_stop']} | {row['elapsed']:.2f}s"
        )


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"ellipsoidal_diagnostic_{stamp}.log"
    with logging_utils.tee_output(log_path), temporary_config():
        print("ELLIPSOIDAL FAILURE DIAGNOSTIC")
        print(f"project={ROOT_DIR}")
        print(f"seed={MASTER_SEED} S={SCENARIOS} T={TIME_PERIODS} sample={SAMPLE_RATIO}")
        print(
            f"multipliers=D{DEMAND_MULTIPLIER}/R{ROAD_CAPACITY_MULTIPLIER}/"
            f"H{HOSPITAL_CAPACITY_MULTIPLIER}"
        )
        print(f"alpha={ALPHA} lambda={LAMBDA} a_E={A_E}")
        print(f"time_limit_per_test={TIME_LIMIT_PER_TEST} mip_gap={MIP_GAP}")
        print("Generating one shared full-size instance...")
        instance = cfg.generate_data(
            sample_ratio=SAMPLE_RATIO,
            ccp_sample_size=CCP_SAMPLE_SIZE,
        )
        selected = instance["sets"]["S"][:SCENARIOS]
        risk_cfg = risk_core.make_risk_cfg(
            "dro_ellipsoidal", alpha=ALPHA, lam=LAMBDA, a_e=A_E,
        )
        print(
            "instance_counts="
            + repr({key: len(instance["sets"][key]) for key in ("I", "J", "H", "S", "T")})
        )
        results = [run_test(instance, selected, risk_cfg, test) for test in TESTS]
        print_diagnosis(results)
        print(f"\nFINAL LOG: {log_path}")
    print(f"Diagnostic complete. Log: {log_path}")


if __name__ == "__main__":
    main()
