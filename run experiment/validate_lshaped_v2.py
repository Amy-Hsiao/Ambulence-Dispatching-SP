#!/usr/bin/env python3
"""
Phase 2 validation for the classic multi-cut L-shaped implementation.

Run:
    python "run experiment/validate_lshaped_v2.py"

Checks:
    V2a  S=1 classic L-shaped matches single-scenario extensive form.
    V2b  S=5 classic L-shaped matches extensive form within combined gap.
    V2c  L-shaped LB history is monotone nondecreasing.
    V2d  UB history comes from oracle re-evaluation and is finite.
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


TIME_LIMIT = 3600.0
MIP_GAP = 0.01
REL_TOL = 1e-5


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


def rel_diff(a, b):
    return abs(a - b) / max(1.0, abs(b))


def within_combined_gap(lshaped, extensive):
    diff = abs(lshaped["best_ub"] - extensive["obj"])
    allowance = (
        abs(lshaped["best_ub"]) * (lshaped["gap_pct"] or 0.0) / 100.0
        + abs(extensive["obj"]) * extensive["gap_pct"] / 100.0
        + 1e-4
    )
    return diff <= allowance, diff, allowance


def lb_monotone(history):
    lbs = [row["lb"] for row in history]
    return all(lbs[i] + 1e-6 >= lbs[i - 1] for i in range(1, len(lbs)))


def run_case(instance, S_selected, label):
    print("-" * 70)
    print(f"{label}: scenarios={len(S_selected)}")
    ls = lshaped_core.solve_classic(
        instance,
        S_selected,
        time_limit=TIME_LIMIT,
        mip_gap=MIP_GAP,
        multi_cut=True,
        verbose=True,
    )
    ef = solve_extensive(instance, S_selected, f"EF_{label}")
    return ls, ef


def report(name, ok, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"       {detail}")
    return int(ok)


def main():
    print("=" * 70)
    print("PHASE 2 VALIDATION - Classic Multi-cut L-shaped")
    print("=" * 70)

    instance = config.generate_data()
    S = instance["sets"]["S"]
    results = []

    ls1, ef1 = run_case(instance, S[:1], "V2_S1")
    ok = rel_diff(ls1["best_ub"], ef1["obj"]) <= REL_TOL
    results.append((
        "V2a S=1 matches extensive form",
        ok,
        f"L-shaped={ls1['best_ub']:.4f} EF={ef1['obj']:.4f} rel={rel_diff(ls1['best_ub'], ef1['obj']):.2e}",
    ))

    s5 = S[: min(5, len(S))]
    ls5, ef5 = run_case(instance, s5, "V2_S5")
    ok, diff, allowance = within_combined_gap(ls5, ef5)
    results.append((
        "V2b S=5 matches extensive form within combined gap",
        ok,
        f"L-shaped={ls5['best_ub']:.4f} EF={ef5['obj']:.4f} diff={diff:.4f} allowance={allowance:.4f}",
    ))

    ok = lb_monotone(ls5["history"])
    results.append((
        "V2c LB history is monotone nondecreasing",
        ok,
        "; ".join(f"it{r['iteration']}={r['lb']:.2f}" for r in ls5["history"]),
    ))

    ok = all(row["ub"] is not None and row["ub"] < float("inf") for row in ls5["history"])
    results.append((
        "V2d UB is finite after oracle re-evaluation",
        ok,
        "; ".join(f"it{r['iteration']}={r['ub']:.2f}" for r in ls5["history"]),
    ))

    print("-" * 70)
    passed = 0
    for name, ok, detail in results:
        passed += report(name, ok, detail)
    print("-" * 70)
    print(
        f"{passed}/{len(results)} checks passed."
        + ("  Phase 2 validation passed." if passed == len(results)
           else "  Phase 2 validation failed.")
    )


if __name__ == "__main__":
    main()
