#!/usr/bin/env python3
"""
Phase 3 validation for Branch-and-Benders-Cut.

Default smoke test uses a reduced sample ratio so it can finish quickly:
    python "run experiment/validate_lshaped_v3.py"

Checks:
    V3a  S=1 B&BC matches extensive form within combined gap.
    V3b  S=1 B&BC matches classic L-shaped within combined gap.
    V3c  S=5 B&BC matches extensive form within combined gap.
    V3d  B&BC records cuts / oracle solves / callback timing.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT / "model core"), str(PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config
import extensive_form_core as model_core
import lshaped_core


SAMPLE_RATIO = 0.25
TIME_LIMIT = 1800.0
MIP_GAP = 0.01


def selected_scenario_data(instance, S_selected):
    sd = instance["scenario_data"]
    return {
        "demand": {s: sd["demand"][s] for s in S_selected},
        "road_availability_ij": {s: sd["road_availability_ij"][s] for s in S_selected},
        "road_availability_jh": {s: sd["road_availability_jh"][s] for s in S_selected},
        "hospital_receiving_capacity": {
            s: sd["hospital_receiving_capacity"][s] for s in S_selected
        },
    }


def normalized_probs(instance, S_selected):
    sd = instance["scenario_data"]
    raw = {s: sd["probability"][s] for s in S_selected}
    total = sum(raw.values())
    return {s: p / total for s, p in raw.items()}


def solve_extensive(instance, S_selected, label):
    sets = instance["sets"]
    m, _ = model_core.build_gurobi_model(
        sets["I"],
        sets["J"],
        sets["H"],
        sets["L"],
        sets["L_transfer"],
        sets["T"],
        S_selected,
        instance["deterministic_parameters"],
        selected_scenario_data(instance, S_selected),
        normalized_probs(instance, S_selected),
        instance["road_capacity"]["cap_ij"],
        instance["road_capacity"]["cap_jh"],
        instance["transport_cost"]["cost_ij"],
        instance["transport_cost"]["cost_jh"],
        model_name=label,
        time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
    )
    m.optimize()
    if m.SolCount == 0:
        raise RuntimeError(f"{label} found no incumbent solution; status={m.Status}")
    return {
        "obj": m.ObjVal,
        "lb": m.ObjBound,
        "gap_pct": m.MIPGap * 100.0,
        "status": m.Status,
    }


def within_combined_gap(left_ub, left_gap_pct, right_ub, right_gap_pct):
    diff = abs(left_ub - right_ub)
    allowance = (
        abs(left_ub) * (left_gap_pct or 0.0) / 100.0
        + abs(right_ub) * (right_gap_pct or 0.0) / 100.0
        + 1e-4
    )
    return diff <= allowance, diff, allowance


def report(name, ok, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"       {detail}")
    return int(ok)


def main():
    print("=" * 70)
    print("PHASE 3 VALIDATION - Branch-and-Benders-Cut")
    print("=" * 70)
    print(f"sample_ratio={SAMPLE_RATIO} time_limit={TIME_LIMIT} mip_gap={MIP_GAP}")

    instance = config.generate_data(sample_ratio=SAMPLE_RATIO)
    S = instance["sets"]["S"]
    S1 = S[:1]
    S5 = S[: min(5, len(S))]
    results = []

    print("-" * 70)
    print("V3_S1 B&BC")
    bbc1 = lshaped_core.solve_bbc(
        instance,
        S1,
        time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
        root_cut_rounds=5,
        use_user_cuts=True,
        ev_warm_start=True,
        verbose=True,
    )
    ef1 = solve_extensive(instance, S1, "EF_V3_S1")
    ok, diff, allowance = within_combined_gap(
        bbc1["best_ub"], bbc1["gap_pct"], ef1["obj"], ef1["gap_pct"]
    )
    results.append((
        "V3a S=1 B&BC matches extensive form",
        ok,
        f"B&BC={bbc1['best_ub']:.4f} EF={ef1['obj']:.4f} diff={diff:.4f} allowance={allowance:.4f}",
    ))

    print("-" * 70)
    print("V3_S1 classic cross-check")
    classic1 = lshaped_core.solve_classic(
        instance,
        S1,
        time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
        max_iterations=2000,
        verbose=False,
    )
    ok, diff, allowance = within_combined_gap(
        bbc1["best_ub"], bbc1["gap_pct"], classic1["best_ub"], classic1["gap_pct"]
    )
    results.append((
        "V3b S=1 B&BC matches classic L-shaped",
        ok,
        f"B&BC={bbc1['best_ub']:.4f} classic={classic1['best_ub']:.4f} diff={diff:.4f} allowance={allowance:.4f}",
    ))

    print("-" * 70)
    print("V3_S5 B&BC")
    bbc5 = lshaped_core.solve_bbc(
        instance,
        S5,
        time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
        root_cut_rounds=5,
        use_user_cuts=True,
        ev_warm_start=True,
        verbose=True,
    )
    ef5 = solve_extensive(instance, S5, "EF_V3_S5")
    ok, diff, allowance = within_combined_gap(
        bbc5["best_ub"], bbc5["gap_pct"], ef5["obj"], ef5["gap_pct"]
    )
    results.append((
        "V3c S=5 B&BC matches extensive form",
        ok,
        f"B&BC={bbc5['best_ub']:.4f} EF={ef5['obj']:.4f} diff={diff:.4f} allowance={allowance:.4f}",
    ))

    ok = (
        bbc5["cuts_added"] >= 0
        and bbc5["oracle_solves"] > 0
        and bbc5["callback_time"] >= 0.0
        and bbc5["root_cut_rounds"] == 5
    )
    results.append((
        "V3d B&BC records cut/oracle/callback statistics",
        ok,
        f"cuts={bbc5['cuts_added']} user_cuts={bbc5['user_cuts_added']} "
        f"lazy_cuts={bbc5['lazy_cuts_added']} rootCutRounds={bbc5['root_cut_rounds_done']}/"
        f"{bbc5['root_cut_rounds']} oracle_solves={bbc5['oracle_solves']} "
        f"callback_time={bbc5['callback_time']:.2f}s",
    ))

    print("-" * 70)
    passed = 0
    for name, ok, detail in results:
        passed += report(name, ok, detail)
    print("-" * 70)
    print(
        f"{passed}/{len(results)} checks passed."
        + ("  Phase 3 validation passed." if passed == len(results)
           else "  Phase 3 validation failed.")
    )


if __name__ == "__main__":
    main()
