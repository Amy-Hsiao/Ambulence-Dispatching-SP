"""
extensive_form_core.py  —  shared Gurobi model builder for deterministic and SP models.
(Phase R 重構：原 model_core.py，僅改檔名，邏輯零改動)

Both the deterministic baseline and the SP extensive form share identical
constraint logic; the only difference is the set of scenarios S and their
probabilities.  This module owns that shared logic once.

Scenario data conventions (same indexing as config.generate_data):
    scenario_data["demand"][s][t][i][l]
    scenario_data["road_availability_ij"][s][i][j][t]
    scenario_data["road_availability_jh"][s][j][h][t]
    scenario_data["hospital_receiving_capacity"][s][h][t]

For a deterministic model, callers should wrap the flat baseline/expected-value
data into a single-scenario dict with s_label (e.g. "B00" or "EV") and pass
probabilities = {s_label: 1.0}.
"""
from __future__ import annotations

from typing import Any

import gurobipy as gp
from gurobipy import GRB


def build_gurobi_model(
    I: list[str],
    J: list[str],
    H: list[str],
    L: list[str],
    L_transfer: list[str],
    T: list[str],
    S: list[str],
    params: dict[str, Any],
    scenario_data: dict[str, Any],
    probabilities: dict[str, float],
    cap_ij: dict[str, dict[str, float]],
    cap_jh: dict[str, dict[str, float]],
    cost_ij: dict[str, dict[str, float]],
    cost_jh: dict[str, dict[str, float]],
    model_name: str = "Model",
    time_limit: float = 3600.0,
    mip_gap: float = 0.01,
    fixed_first_stage: dict[str, Any] | None = None,
) -> tuple[gp.Model, dict[str, Any]]:
    """Build and return a (model, vars_dict) pair.

    Parameters
    ----------
    fixed_first_stage
        When provided, the first-stage variables X/V/U/Y are fixed to the
        supplied values by setting lb == ub.  Used for EEV evaluation.
        Expected keys: "X" ({j: 0|1}), "V" ({j: int}), "U" ({j: int}),
                       "Y" ({(h, j): int}).
    """
    model = gp.Model(model_name)
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", time_limit)
    model.setParam("MIPGap", mip_gap)

    # ------------------------------------------------------------------ #
    # First-stage variables                                                #
    # ------------------------------------------------------------------ #
    X = model.addVars(J, vtype=GRB.BINARY,   name="X")
    V = model.addVars(J, vtype=GRB.INTEGER, lb=0, name="V")
    U = model.addVars(J, vtype=GRB.INTEGER, lb=0, name="U")
    Y = model.addVars(H, J, vtype=GRB.INTEGER, lb=0, name="Y")

    if fixed_first_stage is not None:
        X_val = fixed_first_stage["X"]   # {j: 0|1}
        V_val = fixed_first_stage["V"]   # {j: int}
        U_val = fixed_first_stage["U"]   # {j: int}
        Y_val = fixed_first_stage["Y"]   # {(h, j): int}
        for j in J:
            X[j].lb = X_val[j]; X[j].ub = X_val[j]
            V[j].lb = V_val[j]; V[j].ub = V_val[j]
            U[j].lb = U_val[j]; U[j].ub = U_val[j]
        for h in H:
            for j in J:
                val = Y_val.get((h, j), 0.0)
                Y[h, j].lb = val; Y[h, j].ub = val

    # ------------------------------------------------------------------ #
    # Second-stage variables (indexed by scenario)                        #
    # ------------------------------------------------------------------ #
    FI  = model.addVars(S, I, J, L,          T, vtype=GRB.CONTINUOUS, lb=0, name="FI")
    FO  = model.addVars(S, J, H, L_transfer, T, vtype=GRB.CONTINUOUS, lb=0, name="FO")
    RM  = model.addVars(S, I, L,             T, vtype=GRB.CONTINUOUS, lb=0, name="RM")
    REG = model.addVars(S, J, L,             T, vtype=GRB.CONTINUOUS, lb=0, name="REG")
    TRT = model.addVars(S, J, L,             T, vtype=GRB.CONTINUOUS, lb=0, name="TRT")
    WAT = model.addVars(S, J, L_transfer,    T, vtype=GRB.CONTINUOUS, lb=0, name="WAT")

    # ------------------------------------------------------------------ #
    # Objective                                                            #
    # ------------------------------------------------------------------ #
    first_stage_cost = (
        gp.quicksum(params["ccp_fixed_opening_cost"][j] * X[j] for j in J)
        + params["staff_unit_assignment_cost"] * gp.quicksum(V[j] for j in J)
        + params["ccp_ambulance_unit_assignment_cost"] * gp.quicksum(U[j] for j in J)
        + gp.quicksum(
            params["supply_allocation_cost_from_hospital_to_ccp"][h][j] * Y[h, j]
            for h in H for j in J
        )
    )

    expected_second_stage_cost = gp.LinExpr()
    for s in S:
        prob = probabilities[s]
        scenario_cost = (
            gp.quicksum(
                params["disaster_area_remaining_penalty_by_severity"][l] * RM[s, i, l, t]
                for i in I for l in L for t in T
            )
            + gp.quicksum(
                params["ccp_waiting_penalty_by_severity"][l] * WAT[s, j, l, t]
                for j in J for l in L_transfer for t in T
            )
            + gp.quicksum(
                cost_ij[i][j] * FI[s, i, j, l, t]
                for i in I for j in J for l in L for t in T
            )
            + gp.quicksum(
                cost_jh[j][h] * FO[s, j, h, l, t]
                for j in J for h in H for l in L_transfer for t in T
            )
        )
        expected_second_stage_cost += prob * scenario_cost

    model.setObjective(first_stage_cost + expected_second_stage_cost, GRB.MINIMIZE)

    # ------------------------------------------------------------------ #
    # First-stage resource constraints                                     #
    # ------------------------------------------------------------------ #
    model.addConstr(gp.quicksum(V[j] for j in J) <= params["total_available_staff"],
                    "Total_Staff")
    model.addConstr(gp.quicksum(U[j] for j in J) <= params["total_available_ccp_ambulances"],
                    "Total_CCP_Ambulances")
    for h in H:
        model.addConstr(
            gp.quicksum(Y[h, j] for j in J) <= params["hospital_supply_upper_bound"][h],
            f"Hosp_Supply_{h}",
        )
    for j in J:
        model.addConstr(V[j] <= params["ccp_staff_upper_bound"][j]     * X[j], f"Logic_V_{j}")
        model.addConstr(U[j] <= params["ccp_ambulance_upper_bound"][j] * X[j], f"Logic_U_{j}")
        model.addConstr(
            gp.quicksum(Y[h, j] for h in H) <= params["ccp_supply_upper_bound"][j] * X[j],
            f"Logic_Y_{j}",
        )

    # ------------------------------------------------------------------ #
    # Scenario-indexed constraints                                         #
    # ------------------------------------------------------------------ #
    sd = scenario_data  # alias

    for s in S:
        for t_idx, t in enumerate(T):
            prev_t = T[t_idx - 1] if t_idx > 0 else None

            # Road capacity i→j
            for i in I:
                for j in J:
                    model.addConstr(
                        gp.quicksum(FI[s, i, j, l, t] for l in L)
                        <= cap_ij[i][j] * sd["road_availability_ij"][s][i][j][t] * X[j],
                        f"RoadCap_IJ_{s}_{i}_{j}_{t}",
                    )

            # Road capacity j→h
            for j in J:
                for h in H:
                    model.addConstr(
                        gp.quicksum(FO[s, j, h, l, t] for l in L_transfer)
                        <= cap_jh[j][h] * sd["road_availability_jh"][s][j][h][t] * X[j],
                        f"RoadCap_JH_{s}_{j}_{h}_{t}",
                    )

            # CCP ambulance capacity
            for j in J:
                model.addConstr(
                    gp.quicksum(FI[s, i, j, l, t] for i in I for l in L_transfer)
                    <= params["ccp_ambulance_casualty_capacity"] * U[j],
                    f"CCP_AmbCap_{s}_{j}_{t}",
                )

            # Hospital receiving capacity
            for h in H:
                model.addConstr(
                    gp.quicksum(FO[s, j, h, l, t] for j in J for l in L_transfer)
                    <= params["hospital_ambulance_casualty_capacity"]
                       * params["hospital_ambulance_fleet"][h],
                    f"Hosp_AmbCap_{s}_{h}_{t}",
                )
                model.addConstr(
                    gp.quicksum(FO[s, j, h, l, t] for j in J for l in L_transfer)
                    <= sd["hospital_receiving_capacity"][s][h][t],
                    f"Hosp_ReceiveCap_{s}_{h}_{t}",
                )

            # Remaining patients at disaster area
            for i in I:
                for l in L:
                    prev_rm = RM[s, i, l, prev_t] if prev_t else 0
                    demand_val = sd["demand"][s][t][i].get(l, 0)
                    model.addConstr(
                        RM[s, i, l, t]
                        == prev_rm - gp.quicksum(FI[s, i, j, l, t] for j in J) + demand_val,
                        f"Flow_RM_{s}_{i}_{l}_{t}",
                    )

            for j in J:
                # REG and TRT
                for l in L:
                    model.addConstr(
                        REG[s, j, l, t] == gp.quicksum(FI[s, i, j, l, t] for i in I),
                        f"Flow_REG_{s}_{j}_{l}_{t}",
                    )
                    tau = int(params["treatment_duration_by_severity"][l])
                    start_idx = max(0, t_idx - tau + 1)
                    rolling = T[start_idx: t_idx + 1]
                    model.addConstr(
                        TRT[s, j, l, t] == gp.quicksum(REG[s, j, l, r] for r in rolling),
                        f"Flow_TRT_{s}_{j}_{l}_{t}",
                    )

                # WAT (ambulance-severity only)
                for l in L_transfer:
                    tau = int(params["treatment_duration_by_severity"][l])
                    prev_wat = WAT[s, j, l, prev_t] if prev_t else 0
                    completed = REG[s, j, l, T[t_idx - tau]] if (t_idx - tau) >= 0 else 0
                    model.addConstr(
                        WAT[s, j, l, t]
                        == prev_wat + completed - gp.quicksum(FO[s, j, h, l, t] for h in H),
                        f"Flow_WAT_{s}_{j}_{l}_{t}",
                    )

                # Physical capacity (TRT + WAT for ambulance severities)
                for l in L_transfer:
                    model.addConstr(
                        TRT[s, j, l, t] + WAT[s, j, l, t]
                        <= params["ccp_physical_capacity_by_severity"][l] * X[j],
                        f"CCP_PhysicalCap_{s}_{j}_{l}_{t}",
                    )
                for l in [sev for sev in L if sev not in L_transfer]:
                    model.addConstr(
                        TRT[s, j, l, t]
                        <= params["ccp_physical_capacity_by_severity"][l] * X[j],
                        f"CCP_PhysicalCap_{s}_{j}_{l}_{t}",
                    )

                # Staff capacity
                model.addConstr(
                    gp.quicksum(
                        TRT[s, j, l, t] / params["staff_treatment_rate_by_severity"][l]
                        for l in L
                    ) <= V[j],
                    f"StaffCap_{s}_{j}_{t}",
                )

        # Supply consumption (per scenario, outside t loop)
        for j in J:
            model.addConstr(
                gp.quicksum(
                    params["supply_consumption_by_severity"][l] * REG[s, j, l, t]
                    for l in L for t in T
                ) <= gp.quicksum(Y[h, j] for h in H),
                f"SupplyCap_{s}_{j}",
            )

    vars_dict = {
        "X": X, "V": V, "U": U, "Y": Y,
        "FI": FI, "FO": FO, "RM": RM, "REG": REG, "TRT": TRT, "WAT": WAT,
    }
    return model, vars_dict


def wrap_det_scenario(det_data: dict[str, Any], s_label: str) -> dict[str, Any]:
    """Wrap a flat deterministic data dict as a single-scenario dict for model_core.

    det_data expected keys:
        "demand"                    : {t: {i: {l: val}}}
        "road_availability_ij"      : {i: {j: {t: val}}}
        "road_availability_jh"      : {j: {h: {t: val}}}
        "hospital_receiving_capacity": {h: {t: val}}
    """
    return {
        "demand":                     {s_label: det_data["demand"]},
        "road_availability_ij":       {s_label: det_data["road_availability_ij"]},
        "road_availability_jh":       {s_label: det_data["road_availability_jh"]},
        "hospital_receiving_capacity": {s_label: det_data["hospital_receiving_capacity"]},
    }
