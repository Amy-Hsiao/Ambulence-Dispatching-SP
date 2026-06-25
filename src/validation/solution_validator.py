"""Post-solve solution validation for the extensive-form SP model."""

from __future__ import annotations

from typing import Any

from src.data.schema import has_period, hosp_cap, p, periods, prev_period, u, w, xi


def _val(var: Any) -> float:
    return float(var.X)


def _max_abs(current: float, residual: float) -> float:
    return max(current, abs(float(residual)))


def _max_pos(current: float, residual: float) -> float:
    return max(current, max(0.0, float(residual)))


def validate_solution(model: Any, tol: float = 1e-6) -> dict[str, Any]:
    instance = model._sp_instance
    v = model._sp_vars
    sets = instance["sets"]
    I, J, H, L, L_Amb, S = sets["I"], sets["J"], sets["H"], sets["L"], sets["L_Amb"], sets["S"]
    T = periods(instance)
    L_non_amb = [l for l in L if l not in set(L_Amb)]
    sec = instance["second_stage"]

    max_v = {
        "rm_balance": 0.0,
        "reg_definition": 0.0,
        "trt_definition": 0.0,
        "wat_balance": 0.0,
        "road_in_capacity": 0.0,
        "road_out_capacity": 0.0,
        "ccp_ambulance_capacity": 0.0,
        "hospital_ambulance_capacity": 0.0,
        "hospital_receiving_capacity": 0.0,
        "ccp_physical_capacity": 0.0,
        "staff_workload": 0.0,
        "supply_consumption": 0.0,
        "nonnegativity": 0.0,
    }

    X, V, U, Y = v["X"], v["V"], v["U"], v["Y"]
    FI, FO, RM, REG, TRT, WAT = v["FI"], v["FO"], v["RM"], v["REG"], v["TRT"], v["WAT"]

    for i in I:
        for l in L:
            for t in T:
                for s in S:
                    prev = prev_period(instance, t)
                    lhs = _val(RM[i, l, t, s])
                    rhs = (0.0 if prev is None else _val(RM[i, l, prev, s])) + xi(instance, i, l, t, s)
                    rhs -= sum(_val(FI[i, j, l, t, s]) for j in J)
                    max_v["rm_balance"] = _max_abs(max_v["rm_balance"], lhs - rhs)
    for j in J:
        for l in L:
            for t in T:
                for s in S:
                    lhs = _val(REG[j, l, t, s])
                    rhs = sum(_val(FI[i, j, l, t, s]) for i in I)
                    max_v["reg_definition"] = _max_abs(max_v["reg_definition"], lhs - rhs)

                    tau = int(sec["tau_l"][l])
                    start = t - tau + 1
                    rhs = sum(_val(REG[j, l, r, s]) for r in T if start <= r <= t)
                    max_v["trt_definition"] = _max_abs(max_v["trt_definition"], _val(TRT[j, l, t, s]) - rhs)

    for j in J:
        for l in L_Amb:
            tau = int(sec["tau_l"][l])
            for t in T:
                for s in S:
                    prev = prev_period(instance, t)
                    completed_t = t - tau
                    completed = _val(REG[j, l, completed_t, s]) if has_period(instance, completed_t) else 0.0
                    rhs = (0.0 if prev is None else _val(WAT[j, l, prev, s])) + completed
                    rhs -= sum(_val(FO[j, h, l, t, s]) for h in H)
                    max_v["wat_balance"] = _max_abs(max_v["wat_balance"], _val(WAT[j, l, t, s]) - rhs)

    for i in I:
        for j in J:
            for t in T:
                for s in S:
                    lhs = sum(_val(FI[i, j, l, t, s]) for l in L)
                    rhs = sec["c_ij"][i][j] * u(instance, i, j, t, s) * _val(X[j])
                    max_v["road_in_capacity"] = _max_pos(max_v["road_in_capacity"], lhs - rhs)
    for j in J:
        for h in H:
            for t in T:
                for s in S:
                    lhs = sum(_val(FO[j, h, l, t, s]) for l in L_Amb)
                    rhs = sec["c_jh"][j][h] * w(instance, j, h, t, s) * _val(X[j])
                    max_v["road_out_capacity"] = _max_pos(max_v["road_out_capacity"], lhs - rhs)
    for j in J:
        for t in T:
            for s in S:
                lhs = sum(_val(FI[i, j, l, t, s]) for l in L_Amb for i in I)
                max_v["ccp_ambulance_capacity"] = _max_pos(max_v["ccp_ambulance_capacity"], lhs - sec["kappa"] * _val(U[j]))
    for h in H:
        for t in T:
            for s in S:
                lhs = sum(_val(FO[j, h, l, t, s]) for l in L_Amb for j in J)
                max_v["hospital_ambulance_capacity"] = _max_pos(
                    max_v["hospital_ambulance_capacity"], lhs - sec["eta"] * sec["b_h"][h]
                )
                max_v["hospital_receiving_capacity"] = _max_pos(
                    max_v["hospital_receiving_capacity"], lhs - hosp_cap(instance, h, t, s)
                )
    for j in J:
        for t in T:
            for s in S:
                for l in L_Amb:
                    lhs = _val(TRT[j, l, t, s]) + _val(WAT[j, l, t, s])
                    max_v["ccp_physical_capacity"] = _max_pos(max_v["ccp_physical_capacity"], lhs - sec["k_jl"][j][l] * _val(X[j]))
                for l in L_non_amb:
                    lhs = _val(TRT[j, l, t, s])
                    max_v["ccp_physical_capacity"] = _max_pos(max_v["ccp_physical_capacity"], lhs - sec["k_jl"][j][l] * _val(X[j]))
                lhs = sum(_val(TRT[j, l, t, s]) / sec["alpha_l"][l] for l in L)
                max_v["staff_workload"] = _max_pos(max_v["staff_workload"], lhs - _val(V[j]))
    for j in J:
        for s in S:
            lhs = sum(sec["beta_l"][l] * _val(REG[j, l, t, s]) for l in L for t in T)
            rhs = sum(_val(Y[h, j]) for h in H)
            max_v["supply_consumption"] = _max_pos(max_v["supply_consumption"], lhs - rhs)

    for var_group in (X, V, U, Y, FI, FO, RM, REG, TRT, WAT):
        for var in var_group.values():
            max_v["nonnegativity"] = max(max_v["nonnegativity"], max(0.0, -_val(var)))

    return {
        "passed": all(value <= tol for value in max_v.values()),
        "tolerance": tol,
        "max_violations": max_v,
    }


def objective_decomposition(model: Any) -> dict[str, Any]:
    instance = model._sp_instance
    exprs = model._sp_exprs
    scenario = {s: float(exprs["scenario_cost"][s].getValue()) for s in instance["sets"]["S"]}
    expected = sum(p(instance, s) * scenario[s] for s in instance["sets"]["S"])
    return {
        "objective_value": float(model.ObjVal),
        "first_stage_cost": float(exprs["first_stage_cost"].getValue()),
        "expected_second_stage_cost": float(expected),
        "scenario_second_stage_cost": scenario,
    }
