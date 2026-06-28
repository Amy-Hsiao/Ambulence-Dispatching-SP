import time

import gurobipy as gp
from gurobipy import GRB

import config


def sp_callback(model, where):
    """Print incumbent/bound progress when Gurobi finds a better UB or every 10 seconds."""
    if where == GRB.Callback.MIP:
        current_time = time.time()
        if not hasattr(model._cb_data, "last_print_time"):
            model._cb_data.last_print_time = current_time
            model._cb_data.best_ub = float("inf")

        obj_bst = model.cbGet(GRB.Callback.MIP_OBJBST)
        obj_bnd = model.cbGet(GRB.Callback.MIP_OBJBND)

        if obj_bst < GRB.INFINITY and abs(obj_bst) > 1e-6:
            gap = abs(obj_bst - obj_bnd) / abs(obj_bst) * 100
        else:
            gap = float("inf")

        found_new_best = obj_bst < model._cb_data.best_ub
        time_elapsed = current_time - model._cb_data.last_print_time

        if found_new_best or time_elapsed >= 10.0:
            runtime = model.cbGet(GRB.Callback.RUNTIME)
            print(
                f"[Time: {runtime:.1f}s] Best LB: {obj_bnd:12.2f} | "
                f"Best UB: {obj_bst:12.2f} | Gap: {gap:6.2f}%"
            )
            model._cb_data.last_print_time = current_time
            if found_new_best:
                model._cb_data.best_ub = obj_bst


def run_sp_model(scenario_size=5, network_scale="Small", time_limit=3600, mip_gap=0.01):
    print("=" * 50)
    print("RUNNING STOCHASTIC PROGRAMMING (SP) MODEL")
    print(f" - Scenarios: {scenario_size}")
    print(f" - Network Scale: {network_scale}")

    instance = config.generate_data()
    sets = instance["sets"]
    I = sets["I"]
    J = sets["J"]
    H = sets["H"]
    L = sets["L"]
    L_transfer = sets["L_transfer"]
    T = sets["T"]
    S = sets["S"][:scenario_size]

    print(f" - Disaster Areas: {len(I)}")
    print(f" - Candidate CCPs: {len(J)}")
    print(f" - Hospitals: {len(H)}")
    print("=" * 50 + "\n")

    params = instance["deterministic_parameters"]
    scenario_data = instance["scenario_data"]
    cap_ij = instance["road_capacity"]["cap_ij"]
    cap_jh = instance["road_capacity"]["cap_jh"]
    cost_ij = instance["transport_cost"]["cost_ij"]
    cost_jh = instance["transport_cost"]["cost_jh"]

    model = gp.Model("SP_Model")
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", time_limit)
    model.setParam("MIPGap", mip_gap)

    class CallbackData:
        pass

    model._cb_data = CallbackData()

    # First-stage variables.
    X = model.addVars(J, vtype=GRB.BINARY, name="X")
    V = model.addVars(J, vtype=GRB.INTEGER, lb=0, name="V")
    U = model.addVars(J, vtype=GRB.INTEGER, lb=0, name="U")
    Y = model.addVars(H, J, vtype=GRB.INTEGER, lb=0, name="Y")

    # Scenario-dependent second-stage variables.
    FI = model.addVars(S, I, J, L, T, vtype=GRB.CONTINUOUS, lb=0, name="FI")
    FO = model.addVars(S, J, H, L_transfer, T, vtype=GRB.CONTINUOUS, lb=0, name="FO")
    RM = model.addVars(S, I, L, T, vtype=GRB.CONTINUOUS, lb=0, name="RM")
    REG = model.addVars(S, J, L, T, vtype=GRB.CONTINUOUS, lb=0, name="REG")
    TRT = model.addVars(S, J, L, T, vtype=GRB.CONTINUOUS, lb=0, name="TRT")
    WAT = model.addVars(S, J, L_transfer, T, vtype=GRB.CONTINUOUS, lb=0, name="WAT")

    first_stage_cost = (
        gp.quicksum(params["ccp_fixed_opening_cost"][j] * X[j] for j in J)
        + params["staff_unit_assignment_cost"] * gp.quicksum(V[j] for j in J)
        + params["ccp_ambulance_unit_assignment_cost"] * gp.quicksum(U[j] for j in J)
        + gp.quicksum(
            params["supply_allocation_cost_from_hospital_to_ccp"][h][j] * Y[h, j]
            for h in H
            for j in J
        )
    )

    expected_second_stage_cost = 0
    for s in S:
        probability = scenario_data["probability"][s]
        scenario_cost = (
            gp.quicksum(
                params["disaster_area_remaining_penalty_by_severity"][l] * RM[s, i, l, t]
                for i in I
                for l in L
                for t in T
            )
            + gp.quicksum(
                params["ccp_waiting_penalty_by_severity"][l] * WAT[s, j, l, t]
                for j in J
                for l in L_transfer
                for t in T
            )
            + gp.quicksum(
                cost_ij[i][j] * FI[s, i, j, l, t]
                for i in I
                for j in J
                for l in L
                for t in T
            )
            + gp.quicksum(
                cost_jh[j][h] * FO[s, j, h, l, t]
                for j in J
                for h in H
                for l in L_transfer
                for t in T
            )
        )
        expected_second_stage_cost += probability * scenario_cost

    model.setObjective(first_stage_cost + expected_second_stage_cost, GRB.MINIMIZE)

    model.addConstr(gp.quicksum(V[j] for j in J) <= params["total_available_staff"], "Total_Staff")
    model.addConstr(
        gp.quicksum(U[j] for j in J) <= params["total_available_ccp_ambulances"],
        "Total_CCP_Ambulances",
    )

    for h in H:
        model.addConstr(
            gp.quicksum(Y[h, j] for j in J) <= params["hospital_supply_upper_bound"][h],
            f"Hospital_Supply_{h}",
        )

    for j in J:
        model.addConstr(V[j] <= params["ccp_staff_upper_bound"][j] * X[j], f"Logic_V_{j}")
        model.addConstr(U[j] <= params["ccp_ambulance_upper_bound"][j] * X[j], f"Logic_U_{j}")
        model.addConstr(
            gp.quicksum(Y[h, j] for h in H) <= params["ccp_supply_upper_bound"][j] * X[j],
            f"Logic_Y_{j}",
        )

    for s in S:
        for t_idx, t in enumerate(T):
            prev_t = T[t_idx - 1] if t_idx > 0 else None

            for i in I:
                for j in J:
                    model.addConstr(
                        gp.quicksum(FI[s, i, j, l, t] for l in L)
                        <= cap_ij[i][j] * scenario_data["road_availability_ij"][s][i][j][t] * X[j],
                        f"RoadCap_IJ_{s}_{i}_{j}_{t}",
                    )

            for j in J:
                for h in H:
                    model.addConstr(
                        gp.quicksum(FO[s, j, h, l, t] for l in L_transfer)
                        <= cap_jh[j][h] * scenario_data["road_availability_jh"][s][j][h][t] * X[j],
                        f"RoadCap_JH_{s}_{j}_{h}_{t}",
                    )

            for j in J:
                model.addConstr(
                    gp.quicksum(FI[s, i, j, l, t] for i in I for l in L_transfer)
                    <= params["ccp_ambulance_casualty_capacity"] * U[j],
                    f"CCP_AmbCap_{s}_{j}_{t}",
                )

            for h in H:
                model.addConstr(
                    gp.quicksum(FO[s, j, h, l, t] for j in J for l in L_transfer)
                    <= params["hospital_ambulance_casualty_capacity"]
                    * params["hospital_ambulance_fleet"][h],
                    f"Hosp_AmbCap_{s}_{h}_{t}",
                )
                model.addConstr(
                    gp.quicksum(FO[s, j, h, l, t] for j in J for l in L_transfer)
                    <= scenario_data["hospital_receiving_capacity"][s][h][t],
                    f"Hosp_ReceiveCap_{s}_{h}_{t}",
                )

            for i in I:
                for l in L:
                    prev_rm = RM[s, i, l, prev_t] if prev_t else 0
                    demand = scenario_data["demand"][s][t][i].get(l, 0)
                    model.addConstr(
                        RM[s, i, l, t]
                        == prev_rm - gp.quicksum(FI[s, i, j, l, t] for j in J) + demand,
                        f"Flow_RM_{s}_{i}_{l}_{t}",
                    )

            for j in J:
                for l in L:
                    model.addConstr(
                        REG[s, j, l, t] == gp.quicksum(FI[s, i, j, l, t] for i in I),
                        f"Flow_REG_{s}_{j}_{l}_{t}",
                    )

                    tau = int(params["treatment_duration_by_severity"][l])
                    start_idx = max(0, t_idx - tau + 1)
                    rolling_periods = T[start_idx : t_idx + 1]
                    model.addConstr(
                        TRT[s, j, l, t]
                        == gp.quicksum(REG[s, j, l, rolling_t] for rolling_t in rolling_periods),
                        f"Flow_TRT_{s}_{j}_{l}_{t}",
                    )

                for l in L_transfer:
                    tau = int(params["treatment_duration_by_severity"][l])
                    prev_wat = WAT[s, j, l, prev_t] if prev_t else 0
                    completed = REG[s, j, l, T[t_idx - tau]] if (t_idx - tau) >= 0 else 0
                    model.addConstr(
                        WAT[s, j, l, t]
                        == prev_wat
                        + completed
                        - gp.quicksum(FO[s, j, h, l, t] for h in H),
                        f"Flow_WAT_{s}_{j}_{l}_{t}",
                    )

                for l in L_transfer:
                    model.addConstr(
                        TRT[s, j, l, t] + WAT[s, j, l, t]
                        <= params["ccp_physical_capacity_by_severity"][l] * X[j],
                        f"CCP_PhysicalCap_{s}_{j}_{l}_{t}",
                    )

                for l in [severity for severity in L if severity not in L_transfer]:
                    model.addConstr(
                        TRT[s, j, l, t] <= params["ccp_physical_capacity_by_severity"][l] * X[j],
                        f"CCP_PhysicalCap_{s}_{j}_{l}_{t}",
                    )

                model.addConstr(
                    gp.quicksum(
                        TRT[s, j, l, t] / params["staff_treatment_rate_by_severity"][l] for l in L
                    )
                    <= V[j],
                    f"StaffCap_{s}_{j}_{t}",
                )

        for j in J:
            model.addConstr(
                gp.quicksum(
                    params["supply_consumption_by_severity"][l] * REG[s, j, l, t]
                    for l in L
                    for t in T
                )
                <= gp.quicksum(Y[h, j] for h in H),
                f"SupplyCap_{s}_{j}",
            )

    print("Optimizing SP Model...\n")
    model.optimize(sp_callback)

    print("\n" + "=" * 50)
    if model.status == GRB.OPTIMAL or model.status == GRB.TIME_LIMIT:
        print("SP MODEL RESULT SUMMARY")
        print("-" * 50)
        print(f" - Best UB (Objective): {model.ObjVal:.2f}")
        print(f" - Best LB (Bound):     {model.ObjBound:.2f}")
        print(f" - Final Gap:           {model.MIPGap * 100:.4f}%")
        print(f" - CPU Time:            {model.Runtime:.2f} s")
        print("-" * 50)
        print(" - First-stage decisions (Here and Now):")
        for j in J:
            if X[j].X > 0.5:
                print(f"   CCP {j:4s} -> X: 1, Staff(V): {V[j].X:2.0f}, Amb(U): {U[j].X:2.0f}")
        print("=" * 50)
        return model

    if model.status == GRB.INFEASIBLE:
        print("MODEL IS INFEASIBLE.")
        return None

    print(f"Optimization ended with status {model.status}")
    return None


if __name__ == "__main__":
    run_sp_model(scenario_size=5, network_scale="Small", time_limit=3600, mip_gap=0.01)
