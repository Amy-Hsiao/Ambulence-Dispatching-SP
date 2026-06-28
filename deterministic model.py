import gurobipy as gp
from gurobipy import GRB

import config
import model_core


def custom_callback(model, where):
    """Print solve progress every 100 nodes."""
    if where == GRB.Callback.MIP:
        node_cnt = int(model.cbGet(GRB.Callback.MIP_NODCNT))
        if node_cnt % 100 == 0:
            obj_bst = model.cbGet(GRB.Callback.MIP_OBJBST)
            obj_bnd = model.cbGet(GRB.Callback.MIP_OBJBND)
            if obj_bst < GRB.INFINITY and obj_bst > 0:
                gap = abs(obj_bst - obj_bnd) / obj_bst * 100
            else:
                gap = float("inf")
            runtime = model.cbGet(GRB.Callback.RUNTIME)
            print(
                f"[Time: {runtime:.1f}s] Best LB: {obj_bnd:12.2f} | "
                f"Best UB: {obj_bst:12.2f} | Gap: {gap:6.2f}%"
            )


def solve_deterministic_model():
    print("正在生成資料與載入 Config...")
    instance = config.generate_data()

    sets = instance["sets"]
    I, J, H, L, L_Amb, T = (
        sets["I"], sets["J"], sets["H"],
        sets["L"], sets["L_transfer"], sets["T"],
    )

    params   = instance["deterministic_parameters"]
    cap_ij   = instance["road_capacity"]["cap_ij"]
    cap_jh   = instance["road_capacity"]["cap_jh"]
    cost_ij  = instance["transport_cost"]["cost_ij"]
    cost_jh  = instance["transport_cost"]["cost_jh"]

    # Wrap baseline B00 as a single-scenario dict for model_core
    baseline   = instance["deterministic_data"]["baseline"]
    S_DET      = "B00"
    sd         = model_core.wrap_det_scenario(baseline, S_DET)
    probs      = {S_DET: 1.0}

    # Build model via shared core
    m, v = model_core.build_gurobi_model(
        I, J, H, L, L_Amb, T, [S_DET],
        params, sd, probs,
        cap_ij, cap_jh, cost_ij, cost_jh,
        model_name="Deterministic_Baseline_Model",
    )
    X, V, U, Y = v["X"], v["V"], v["U"], v["Y"]
    FI, FO, RM, REG, TRT, WAT = (
        v["FI"], v["FO"], v["RM"], v["REG"], v["TRT"], v["WAT"],
    )

    print("\n--- 開始求解 Deterministic Model ---")
    m.optimize(custom_callback)

    if m.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT) or m.SolCount == 0:
        print(f"Model did not solve to optimality. Status: {m.Status}")
        return

    # ------------------------------------------------------------------ #
    # KPI calculation                                                      #
    # ------------------------------------------------------------------ #
    s = S_DET   # single scenario alias

    total_demand = sum(
        baseline["demand"][t][i].get(l, 0)
        for t in T for i in I for l in L
    )
    tot_FI  = sum(FI[s, i, j, l, t].X  for i in I for j in J for l in L       for t in T)
    tot_FO  = sum(FO[s, j, h, l, t].X  for j in J for h in H for l in L_Amb   for t in T)
    tot_RM  = sum(RM[s, i, l, t].X     for i in I for l in L                   for t in T)
    tot_WAT = sum(WAT[s, j, l, t].X    for j in J for l in L_Amb               for t in T)

    def safe_div(num, den):
        return (num / den * 100) if den > 1e-6 else 0.0

    max_ccp_util = 0.0
    for j in J:
        for l in L:
            cap = params["ccp_physical_capacity_by_severity"][l] * X[j].X
            for t in T:
                used = TRT[s, j, l, t].X + (WAT[s, j, l, t].X if l in L_Amb else 0)
                max_ccp_util = max(max_ccp_util, safe_div(used, cap))

    max_hosp_util = 0.0
    for h in H:
        for t in T:
            cap  = baseline["hospital_receiving_capacity"][h][t]
            used = sum(FO[s, j, h, l, t].X for j in J for l in L_Amb)
            max_hosp_util = max(max_hosp_util, safe_div(used, cap))

    max_road_ij_util = 0.0
    for i in I:
        for j in J:
            for t in T:
                cap  = cap_ij[i][j] * baseline["road_availability_ij"][i][j][t] * X[j].X
                used = sum(FI[s, i, j, l, t].X for l in L)
                max_road_ij_util = max(max_road_ij_util, safe_div(used, cap))

    max_road_jh_util = 0.0
    for j in J:
        for h in H:
            for t in T:
                cap  = cap_jh[j][h] * baseline["road_availability_jh"][j][h][t] * X[j].X
                used = sum(FO[s, j, h, l, t].X for l in L_Amb)
                max_road_jh_util = max(max_road_jh_util, safe_div(used, cap))

    max_staff_util = 0.0
    for j in J:
        cap = V[j].X
        for t in T:
            used = sum(
                TRT[s, j, l, t].X / params["staff_treatment_rate_by_severity"][l]
                for l in L
            )
            max_staff_util = max(max_staff_util, safe_div(used, cap))

    max_ccp_amb_util = 0.0
    for j in J:
        cap = params["ccp_ambulance_casualty_capacity"] * U[j].X
        for t in T:
            used = sum(FI[s, i, j, l, t].X for i in I for l in L_Amb)
            max_ccp_amb_util = max(max_ccp_amb_util, safe_div(used, cap))

    max_hosp_amb_util = 0.0
    for h in H:
        cap = params["hospital_ambulance_casualty_capacity"] * params["hospital_ambulance_fleet"][h]
        for t in T:
            used = sum(FO[s, j, h, l, t].X for j in J for l in L_Amb)
            max_hosp_amb_util = max(max_hosp_amb_util, safe_div(used, cap))

    # ------------------------------------------------------------------ #
    # Report                                                               #
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 50)
    print(" DETERMINISTIC MODEL OPTIMIZATION REPORT ")
    print("=" * 50)
    print(f"- Scenario數量: 1 (Baseline B00)")
    print(f"- Time Period數量: {len(T)}")
    print(f"- Disaster Area數量: {len(I)}")
    print(f"- Candidate CCP數量: {len(J)}")
    print(f"- Hospital數量: {len(H)}")
    print(f"- demand multiplier: {baseline['multipliers']['demand_multiplier']}")
    print(f"- hospital capacity multiplier: {baseline['multipliers']['hospital_capacity_multiplier']}")
    print(f"- road capacity multiplier: {baseline['multipliers']['road_capacity_multiplier']}")
    print("-" * 50)
    print(f"- obj_value:   {m.ObjVal:15.2f}")
    print(f"- Best LB:     {m.ObjBound:15.2f}")
    print(f"- Best UB:     {m.ObjVal:15.2f}")
    print(f"- Final Gap(%):{m.MIPGap * 100:15.4f} %")
    print(f"- CPU Time(s): {m.Runtime:15.2f} s")
    print(f"- Nodes:       {m.NodeCount:15.0f}")
    print(f"- Iteration:   {m.IterCount:15.0f} (Simplex iterations)")
    print(f"- num_vars:    {m.NumVars:15d}")
    print(f"- num_constrs: {m.NumConstrs:15d}")
    print("-" * 50)
    print("- 第一階決策變數 (X, V, U):")
    for j in J:
        if X[j].X > 0.5:
            print(f"  CCP {j:4s} -> X: 1, Staff(V): {V[j].X:2.0f}, Amb(U): {U[j].X:2.0f}")
    print("\n- 第一階決策變數 (Y - 醫療物資分配):")
    for h in H:
        for j in J:
            if Y[h, j].X > 0:
                print(f"  Hosp {h} -> CCP {j:4s} : {Y[h, j].X:.2f} 單位")
    print("-" * 50)
    print("- total_demand:                  {:.2f}".format(total_demand))
    print("- total_transported_to_ccp (FI): {:.2f}".format(tot_FI))
    print("- total_transferred_to_hospital (FO): {:.2f}".format(tot_FO))
    print("- total_remaining_disaster_area (RM): {:.2f} (所有期別加總)".format(tot_RM))
    print("- total_waiting_at_ccp (WAT):         {:.2f} (所有期別加總)".format(tot_WAT))
    print("-" * 50)
    print("- max_ccp_utilization_%:                {:6.2f} %".format(max_ccp_util))
    print("- max_hospital_utilization_%:           {:6.2f} %".format(max_hosp_util))
    print("- max_road_ij_utilization_%:            {:6.2f} %".format(max_road_ij_util))
    print("- max_road_jh_utilization_%:            {:6.2f} %".format(max_road_jh_util))
    print("- max_staff_utilization_%:              {:6.2f} %".format(max_staff_util))
    print("- max_ccp_ambulance_utilization_%:      {:6.2f} %".format(max_ccp_amb_util))
    print("- max_hospital_ambulance_utilization_%: {:6.2f} %".format(max_hosp_amb_util))
    print("=" * 50)


if __name__ == "__main__":
    solve_deterministic_model()
