"""Extensive-form two-stage stochastic program built directly with gurobipy."""

from __future__ import annotations

from typing import Any

from src.data.schema import (
    has_period,
    hosp_cap,
    nested_get_2,
    p,
    period_key,
    periods,
    prev_period,
    rv,
    ss,
    u,
    w,
    xi,
)


def build_model(instance: dict[str, Any]):
    """Build the deterministic equivalent extensive-form model."""
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as exc:
        raise RuntimeError("gurobipy is required to build and solve the SP model.") from exc

    sets = instance["sets"]
    I, J, H, L, L_Amb, S = sets["I"], sets["J"], sets["H"], sets["L"], sets["L_Amb"], sets["S"]
    T = periods(instance)
    L_non_amb = [l for l in L if l not in set(L_Amb)]

    m = gp.Model(f"two_stage_sp_{instance.get('name', 'instance')}")

    fs = instance["first_stage"]
    sec = instance["second_stage"]

    X = m.addVars(J, vtype=GRB.BINARY, name="X")
    V = m.addVars(J, vtype=GRB.INTEGER, lb=0, name="V")
    U = m.addVars(J, vtype=GRB.INTEGER, lb=0, name="U")
    # Y is integer per the V1 model. It can be relaxed intentionally by changing this vtype.
    Y = m.addVars(H, J, vtype=GRB.INTEGER, lb=0, name="Y")

    FI = m.addVars(I, J, L, T, S, vtype=GRB.CONTINUOUS, lb=0, name="FI")
    FO = m.addVars(J, H, L_Amb, T, S, vtype=GRB.CONTINUOUS, lb=0, name="FO")
    RM = m.addVars(I, L, T, S, vtype=GRB.CONTINUOUS, lb=0, name="RM")
    REG = m.addVars(J, L, T, S, vtype=GRB.CONTINUOUS, lb=0, name="REG")
    TRT = m.addVars(J, L, T, S, vtype=GRB.CONTINUOUS, lb=0, name="TRT")
    WAT = m.addVars(J, L_Amb, T, S, vtype=GRB.CONTINUOUS, lb=0, name="WAT")

    first_stage_cost = (
        gp.quicksum(fs["f_j"][j] * X[j] for j in J)
        + fs["cv"] * gp.quicksum(V[j] for j in J)
        + fs["ca"] * gp.quicksum(U[j] for j in J)
        + gp.quicksum(fs["cy_hj"][h][j] * Y[h, j] for h in H for j in J)
    )

    scenario_cost = {}
    for s in S:
        scenario_cost[s] = (
            gp.quicksum(sec["rho_l"][l] * RM[i, l, t, s] for l in L for i in I for t in T)
            + gp.quicksum(sec["delta_l"][l] * WAT[j, l, t, s] for l in L_Amb for j in J for t in T)
            + gp.quicksum(sec["t_ij"][i][j] * FI[i, j, l, t, s] for l in L for j in J for i in I for t in T)
            + gp.quicksum(sec["t_jh"][j][h] * FO[j, h, l, t, s] for l in L_Amb for h in H for j in J for t in T)
        )
    expected_second_stage_cost = gp.quicksum(p(instance, s) * scenario_cost[s] for s in S)
    m.setObjective(first_stage_cost + expected_second_stage_cost, GRB.MINIMIZE)

    m.addConstr(gp.quicksum(V[j] for j in J) <= fs["nv"], name="first_staff_total")
    m.addConstr(gp.quicksum(U[j] for j in J) <= fs["na"], name="first_ccp_ambulance_total")
    for h in H:
        m.addConstr(gp.quicksum(Y[h, j] for j in J) <= fs["sbar_h"][h], name=f"first_supply_from[{h}]")
    for j in J:
        m.addConstr(V[j] <= fs["vbar_j"][j] * X[j], name=f"first_staff_open[{j}]")
        m.addConstr(U[j] <= fs["ubar_j"][j] * X[j], name=f"first_ambulance_open[{j}]")
        m.addConstr(gp.quicksum(Y[h, j] for h in H) <= fs["ybar_j"][j] * X[j], name=f"first_supply_open[{j}]")

    for i in I:
        for j in J:
            for t in T:
                for s in S:
                    m.addConstr(
                        gp.quicksum(FI[i, j, l, t, s] for l in L)
                        <= sec["c_ij"][i][j] * u(instance, i, j, t, s) * X[j],
                        name=f"road_in[{i},{j},{t},{s}]",
                    )
    for j in J:
        for h in H:
            for t in T:
                for s in S:
                    m.addConstr(
                        gp.quicksum(FO[j, h, l, t, s] for l in L_Amb)
                        <= sec["c_jh"][j][h] * w(instance, j, h, t, s) * X[j],
                        name=f"road_out[{j},{h},{t},{s}]",
                    )
    for j in J:
        for t in T:
            for s in S:
                m.addConstr(
                    gp.quicksum(FI[i, j, l, t, s] for l in L_Amb for i in I) <= sec["kappa"] * U[j],
                    name=f"ccp_ambulance[{j},{t},{s}]",
                )
    for h in H:
        for t in T:
            for s in S:
                m.addConstr(
                    gp.quicksum(FO[j, h, l, t, s] for l in L_Amb for j in J) <= sec["eta"] * sec["b_h"][h],
                    name=f"hospital_ambulance[{h},{t},{s}]",
                )

    for i in I:
        for l in L:
            for t in T:
                for s in S:
                    prev = prev_period(instance, t)
                    prev_rm = 0 if prev is None else RM[i, l, prev, s]
                    m.addConstr(
                        RM[i, l, t, s] == prev_rm + xi(instance, i, l, t, s) - gp.quicksum(FI[i, j, l, t, s] for j in J),
                        name=f"rm_balance[{i},{l},{t},{s}]",
                    )
    for j in J:
        for l in L:
            for t in T:
                for s in S:
                    m.addConstr(
                        REG[j, l, t, s] == gp.quicksum(FI[i, j, l, t, s] for i in I),
                        name=f"reg_definition[{j},{l},{t},{s}]",
                    )
                    tau = int(sec["tau_l"][l])
                    start = t - tau + 1
                    rolling_periods = [r for r in T if start <= r <= t]
                    m.addConstr(
                        TRT[j, l, t, s] == gp.quicksum(REG[j, l, r, s] for r in rolling_periods),
                        name=f"trt_definition[{j},{l},{t},{s}]",
                    )

    for j in J:
        for l in L_Amb:
            tau = int(sec["tau_l"][l])
            for t in T:
                for s in S:
                    prev = prev_period(instance, t)
                    prev_wat = 0 if prev is None else WAT[j, l, prev, s]
                    completed_t = t - tau
                    completed = REG[j, l, completed_t, s] if has_period(instance, completed_t) else 0
                    m.addConstr(
                        WAT[j, l, t, s]
                        == prev_wat + completed - gp.quicksum(FO[j, h, l, t, s] for h in H),
                        name=f"wat_balance[{j},{l},{t},{s}]",
                    )

    for j in J:
        for t in T:
            for s in S:
                for l in L_Amb:
                    m.addConstr(
                        TRT[j, l, t, s] + WAT[j, l, t, s] <= sec["k_jl"][j][l] * X[j],
                        name=f"ccp_capacity_amb[{j},{l},{t},{s}]",
                    )
                for l in L_non_amb:
                    m.addConstr(
                        TRT[j, l, t, s] <= sec["k_jl"][j][l] * X[j],
                        name=f"ccp_capacity_nonamb[{j},{l},{t},{s}]",
                    )
                m.addConstr(
                    gp.quicksum(TRT[j, l, t, s] / sec["alpha_l"][l] for l in L) <= V[j],
                    name=f"staff_workload[{j},{t},{s}]",
                )
    for j in J:
        for s in S:
            m.addConstr(
                gp.quicksum(sec["beta_l"][l] * REG[j, l, t, s] for l in L for t in T)
                <= gp.quicksum(Y[h, j] for h in H),
                name=f"supply_consumption[{j},{s}]",
            )
    for h in H:
        for t in T:
            for s in S:
                m.addConstr(
                    gp.quicksum(FO[j, h, l, t, s] for l in L_Amb for j in J) <= hosp_cap(instance, h, t, s),
                    name=f"hospital_receiving[{h},{t},{s}]",
                )

    m._sp_instance = instance
    m._sp_vars = {"X": X, "V": V, "U": U, "Y": Y, "FI": FI, "FO": FO, "RM": RM, "REG": REG, "TRT": TRT, "WAT": WAT}
    m._sp_exprs = {
        "first_stage_cost": first_stage_cost,
        "scenario_cost": scenario_cost,
        "expected_second_stage_cost": expected_second_stage_cost,
    }
    return m
