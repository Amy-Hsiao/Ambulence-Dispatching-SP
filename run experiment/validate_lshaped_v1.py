#!/usr/bin/env python3
"""
validate_lshaped_v1.py — Phase 1 驗收（V1）：ScenarioOracle 正確性測試。

需要 gurobipy，請在本機執行：
    python "run experiment/validate_lshaped_v1.py"

測試項目
--------
V1a  Oracle 目標值 = extensive form 固定同一組一階解後的單情境目標值（相對誤差 < 1e-6）
V1b  cut 在評估點 x̄ 取等式（cut(x̄) == Q_s(x̄)）
V1c  cut 是全域下界：對擾動後的一階解 x'，cut(x') ≤ Q_s(x') + tol（多組擾動）
V1d  多情境一致性：對 S 中每個情境重複 V1a

全部 PASS 才算通過 Phase 1，之後才進 Phase 2。
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

REL_TOL = 1e-6


def reference_value(instance, s, fs):
    """extensive form：單情境 + 固定一階，直接求解，回傳 (total, Q_s)。"""
    sets = instance["sets"]
    sd_full = instance["scenario_data"]
    sub_sd = {
        "demand":                      {s: sd_full["demand"][s]},
        "road_availability_ij":        {s: sd_full["road_availability_ij"][s]},
        "road_availability_jh":        {s: sd_full["road_availability_jh"][s]},
        "hospital_receiving_capacity": {s: sd_full["hospital_receiving_capacity"][s]},
    }
    m, v = model_core.build_gurobi_model(
        sets["I"], sets["J"], sets["H"], sets["L"], sets["L_transfer"], sets["T"], [s],
        instance["deterministic_parameters"], sub_sd, {s: 1.0},
        instance["road_capacity"]["cap_ij"], instance["road_capacity"]["cap_jh"],
        instance["transport_cost"]["cost_ij"], instance["transport_cost"]["cost_jh"],
        model_name=f"Ref[{s}]", time_limit=300.0, mip_gap=1e-9,
        fixed_first_stage=fs,
    )
    m.setParam("OutputFlag", 0)
    m.optimize()
    assert m.SolCount > 0, f"reference model infeasible for scenario {s}"
    total = m.ObjVal
    params = instance["deterministic_parameters"]
    J, H = sets["J"], sets["H"]
    f_cost = (
        sum(params["ccp_fixed_opening_cost"][j] * fs["X"][j] for j in J)
        + params["staff_unit_assignment_cost"] * sum(fs["V"][j] for j in J)
        + params["ccp_ambulance_unit_assignment_cost"] * sum(fs["U"][j] for j in J)
        + sum(params["supply_allocation_cost_from_hospital_to_ccp"][h][j] * fs["Y"].get((h, j), 0)
              for h in H for j in J)
    )
    return total, total - f_cost


def make_first_stage(J, H, open_all=True, staff=50, amb=13, supply=60):
    """建一組滿足一階資源限制式的可行解。"""
    xs = {j: (1 if open_all else 0) for j in J}
    return {
        "X": xs,
        "V": {j: staff * xs[j] for j in J},
        "U": {j: amb   * xs[j] for j in J},
        "Y": {(h, j): (supply if (h == H[0] and xs[j]) else 0) for h in H for j in J},
    }


def main():
    print("=" * 70)
    print("PHASE 1 VALIDATION — ScenarioOracle (V1)")
    print("=" * 70)
    instance = config.generate_data()
    sets = instance["sets"]
    J, H, S = sets["J"], sets["H"], sets["S"]

    fs = make_first_stage(J, H)
    results = []

    # ---- V1a + V1b + V1c on first scenario -------------------------------
    s0 = S[0]
    oracle = lshaped_core.ScenarioOracle(instance, s0)
    q_oracle, cut = oracle.evaluate(fs)
    total_ref, q_ref = reference_value(instance, s0, fs)

    rel = abs(q_oracle - q_ref) / max(1.0, abs(q_ref))
    ok = rel < REL_TOL
    results.append(("V1a oracle Q_s == reference Q_s", ok,
                    f"oracle={q_oracle:.4f} ref={q_ref:.4f} rel_err={rel:.2e}"))

    cut_at_xbar = oracle.cut_value_at(cut, fs)
    ok = abs(cut_at_xbar - q_oracle) / max(1.0, abs(q_oracle)) < REL_TOL
    results.append(("V1b cut tight at x̄", ok,
                    f"cut(x̄)={cut_at_xbar:.4f} Q_s(x̄)={q_oracle:.4f}"))

    # V1c：多組擾動，cut 必須是下界
    perturbations = [
        make_first_stage(J, H, staff=45, amb=12, supply=55),
        make_first_stage(J, H, staff=54, amb=13, supply=60),
        make_first_stage(J, H, staff=50, amb=10, supply=40),
    ]
    lower_bound_ok = True
    detail = []
    for k, fs_p in enumerate(perturbations):
        q_true, _ = oracle.evaluate(fs_p)
        pred = oracle.cut_value_at(cut, fs_p)
        good = pred <= q_true * (1 + 1e-7) + 1e-4
        lower_bound_ok &= good
        detail.append(f"p{k}: cut={pred:.2f} <= Q={q_true:.2f} {'OK' if good else 'VIOLATED'}")
    results.append(("V1c cut is global lower bound", lower_bound_ok, "; ".join(detail)))

    # ---- V1d：所有情境 ---------------------------------------------------
    all_ok = True
    detail = []
    for s in S:
        orc = lshaped_core.ScenarioOracle(instance, s)
        q_o, _ = orc.evaluate(fs)
        _, q_r = reference_value(instance, s, fs)
        rel = abs(q_o - q_r) / max(1.0, abs(q_r))
        good = rel < REL_TOL
        all_ok &= good
        detail.append(f"{s}: rel={rel:.1e}")
    results.append(("V1d all scenarios match", all_ok, "; ".join(detail)))

    # ---- report -----------------------------------------------------------
    print()
    n_pass = 0
    for name, ok, info in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"       {info}")
        n_pass += ok
    print("-" * 70)
    print(f"{n_pass}/{len(results)} checks passed."
          + ("  Phase 1 驗收通過，可進 Phase 2。" if n_pass == len(results)
             else "  有項目未通過，請勿進入 Phase 2。"))


if __name__ == "__main__":
    main()
