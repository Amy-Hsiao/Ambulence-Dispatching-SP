import gurobipy as gp
from gurobipy import GRB
import config  # 載入您的設定檔

def custom_callback(model, where):
    """自定義的回呼函數，用於印出求解進度"""
    if where == GRB.Callback.MIP:
        node_cnt = int(model.cbGet(GRB.Callback.MIP_NODCNT))
        
        # 為了避免洗版，設定每 100 個 Nodes 印出一次，或者在找到新解時印出
        # 您可以將 100 改為 1 來印出「每一個」節點，但速度會受到 I/O 拖慢
        if node_cnt % 100 == 0:
            obj_bst = model.cbGet(GRB.Callback.MIP_OBJBST)
            obj_bnd = model.cbGet(GRB.Callback.MIP_OBJBND)
            
            # 計算 Gap
            if obj_bst < GRB.INFINITY and obj_bst > 0:
                gap = abs(obj_bst - obj_bnd) / obj_bst * 100
            else:
                gap = float('inf')
                
            runtime = model.cbGet(GRB.Callback.RUNTIME)
            print(f"[Time: {runtime:.1f}s] Best LB: {obj_bnd:12.2f} | Best UB: {obj_bst:12.2f} | Gap: {gap:6.2f}%")

def solve_deterministic_model():
    print("正在生成資料與載入 Config...")
    instance = config.generate_data()
    
    # 提取所需資料
    sets = instance["sets"]
    I, J, H, L, L_Amb, T = sets["I"], sets["J"], sets["H"], sets["L"], sets["L_transfer"], sets["T"]
    
    # 取出基準確定性資料 (Deterministic Baseline)
    baseline = instance["deterministic_data"]["baseline"]
    params = instance["deterministic_parameters"]
    
    cap_ij = instance["road_capacity"]["cap_ij"]
    cap_jh = instance["road_capacity"]["cap_jh"]
    cost_ij = instance["transport_cost"]["cost_ij"]
    cost_jh = instance["transport_cost"]["cost_jh"]
    
    # 建立模型
    m = gp.Model("Deterministic_Baseline_Model")
    m.Params.OutputFlag = 0  # 關閉 Gurobi 預設輸出
    
    # ---------------------------------------------------------
    # 1. 定義決策變數
    # ---------------------------------------------------------
    X = m.addVars(J, vtype=GRB.BINARY, name="X")
    V = m.addVars(J, vtype=GRB.INTEGER, lb=0, name="V")
    U = m.addVars(J, vtype=GRB.INTEGER, lb=0, name="U")
    Y = m.addVars(H, J, vtype=GRB.INTEGER, lb=0, name="Y")
    
    FI = m.addVars(I, J, L, T, vtype=GRB.CONTINUOUS, lb=0, name="FI")
    FO = m.addVars(J, H, L_Amb, T, vtype=GRB.CONTINUOUS, lb=0, name="FO")
    RM = m.addVars(I, L, T, vtype=GRB.CONTINUOUS, lb=0, name="RM")
    REG = m.addVars(J, L, T, vtype=GRB.CONTINUOUS, lb=0, name="REG")
    TRT = m.addVars(J, L, T, vtype=GRB.CONTINUOUS, lb=0, name="TRT")
    WAT = m.addVars(J, L_Amb, T, vtype=GRB.CONTINUOUS, lb=0, name="WAT")
    
    # ---------------------------------------------------------
    # 2. 目標函數 (第一階段成本 + 第二階段(基準情境)成本)
    # ---------------------------------------------------------
    first_stage_cost = (
        gp.quicksum(params["ccp_fixed_opening_cost"][j] * X[j] for j in J) +
        params["staff_unit_assignment_cost"] * gp.quicksum(V[j] for j in J) +
        params["ccp_ambulance_unit_assignment_cost"] * gp.quicksum(U[j] for j in J) +
        gp.quicksum(params["supply_allocation_cost_from_hospital_to_ccp"][h][j] * Y[h, j] for h in H for j in J)
    )
    
    second_stage_cost = (
        gp.quicksum(params["disaster_area_remaining_penalty_by_severity"][l] * RM[i, l, t] for l in L for i in I for t in T) +
        gp.quicksum(params["ccp_waiting_penalty_by_severity"][l] * WAT[j, l, t] for l in L_Amb for j in J for t in T) +
        gp.quicksum(cost_ij[i][j] * FI[i, j, l, t] for l in L for j in J for i in I for t in T) +
        gp.quicksum(cost_jh[j][h] * FO[j, h, l, t] for l in L_Amb for h in H for j in J for t in T)
    )
    
    m.setObjective(first_stage_cost + second_stage_cost, GRB.MINIMIZE)
    
    # ---------------------------------------------------------
    # 3. 限制式
    # ---------------------------------------------------------
    # 第一階段資源限制
    m.addConstr(gp.quicksum(V[j] for j in J) <= params["total_available_staff"])
    m.addConstr(gp.quicksum(U[j] for j in J) <= params["total_available_ccp_ambulances"])
    for h in H:
        m.addConstr(gp.quicksum(Y[h, j] for j in J) <= params["hospital_supply_upper_bound"][h])
    for j in J:
        m.addConstr(V[j] <= params["ccp_staff_upper_bound"][j] * X[j])
        m.addConstr(U[j] <= params["ccp_ambulance_upper_bound"][j] * X[j])
        m.addConstr(gp.quicksum(Y[h, j] for h in H) <= params["ccp_supply_upper_bound"][j] * X[j])

    # 運輸能量與病患流動
    for t_idx, t in enumerate(T):
        prev_t = T[t_idx - 1] if t_idx > 0 else None
        
        for i in I:
            for j in J:
                m.addConstr(gp.quicksum(FI[i, j, l, t] for l in L) <= cap_ij[i][j] * baseline["road_availability_ij"][i][j][t] * X[j])
        
        for j in J:
            for h in H:
                m.addConstr(gp.quicksum(FO[j, h, l, t] for l in L_Amb) <= cap_jh[j][h] * baseline["road_availability_jh"][j][h][t] * X[j])
                
        for j in J:
            m.addConstr(gp.quicksum(FI[i, j, l, t] for l in L_Amb for i in I) <= params["ccp_ambulance_casualty_capacity"] * U[j])
            
        for h in H:
            m.addConstr(gp.quicksum(FO[j, h, l, t] for l in L_Amb for j in J) <= params["hospital_ambulance_casualty_capacity"] * params["hospital_ambulance_fleet"][h])

        for i in I:
            for l in L:
                prev_rm = RM[i, l, prev_t] if prev_t else 0
                m.addConstr(RM[i, l, t] == prev_rm + baseline["demand"][t][i].get(l, 0) - gp.quicksum(FI[i, j, l, t] for j in J))

        for j in J:
            for l in L:
                m.addConstr(REG[j, l, t] == gp.quicksum(FI[i, j, l, t] for i in I))
                
                tau = int(params["treatment_duration_by_severity"][l])
                start_idx = max(0, t_idx - tau + 1)
                rolling_periods = T[start_idx : t_idx + 1]
                m.addConstr(TRT[j, l, t] == gp.quicksum(REG[j, l, r] for r in rolling_periods))

            for l in L_Amb:
                tau = int(params["treatment_duration_by_severity"][l])
                prev_wat = WAT[j, l, prev_t] if prev_t else 0
                completed = REG[j, l, T[t_idx - tau]] if (t_idx - tau) >= 0 else 0
                m.addConstr(WAT[j, l, t] == prev_wat + completed - gp.quicksum(FO[j, h, l, t] for h in H))

            # 治療容量限制
            for l in L_Amb:
                m.addConstr(TRT[j, l, t] + WAT[j, l, t] <= params["ccp_physical_capacity_by_severity"][l] * X[j])
            for l in [l for l in L if l not in L_Amb]:
                m.addConstr(TRT[j, l, t] <= params["ccp_physical_capacity_by_severity"][l] * X[j])
                
            m.addConstr(gp.quicksum(TRT[j, l, t] / params["staff_treatment_rate_by_severity"][l] for l in L) <= V[j])

        for h in H:
            m.addConstr(gp.quicksum(FO[j, h, l, t] for l in L_Amb for j in J) <= baseline["hospital_receiving_capacity"][h][t])

    # 物資消耗限制
    for j in J:
        m.addConstr(gp.quicksum(params["supply_consumption_by_severity"][l] * REG[j, l, t] for l in L for t in T) <= gp.quicksum(Y[h, j] for h in H))

    # ---------------------------------------------------------
    # 4. 開始求解與觸發 Callback
    # ---------------------------------------------------------
    print("\n--- 開始求解 Deterministic Model ---")
    m.optimize(custom_callback)
    
    if m.Status != GRB.OPTIMAL:
        print(f"Model did not solve to optimality. Status: {m.Status}")
        return

    # ---------------------------------------------------------
    # 5. 計算報表所需數據
    # ---------------------------------------------------------
    # 總需求量
    total_demand = sum(baseline["demand"][t][i].get(l, 0) for t in T for i in I for l in L)
    
    # 總運送與轉送
    tot_FI = sum(FI[i, j, l, t].X for i in I for j in J for l in L for t in T)
    tot_FO = sum(FO[j, h, l, t].X for j in J for h in H for l in L_Amb for t in T)
    
    # 總殘留與等待
    tot_RM = sum(RM[i, l, t].X for i in I for l in L for t in T)
    tot_WAT = sum(WAT[j, l, t].X for j in J for l in L_Amb for t in T)
    
    # 計算最大利用率 (Utilization = Used / Capacity)
    def safe_div(num, den):
        return (num / den * 100) if den > 1e-6 else 0.0

    max_ccp_util = 0.0
    for j in J:
        for l in L:
            cap = params["ccp_physical_capacity_by_severity"][l] * X[j].X
            for t in T:
                used = TRT[j, l, t].X + (WAT[j, l, t].X if l in L_Amb else 0)
                max_ccp_util = max(max_ccp_util, safe_div(used, cap))

    max_hosp_util = 0.0
    for h in H:
        for t in T:
            cap = baseline["hospital_receiving_capacity"][h][t]
            used = sum(FO[j, h, l, t].X for j in J for l in L_Amb)
            max_hosp_util = max(max_hosp_util, safe_div(used, cap))

    max_road_ij_util = 0.0
    for i in I:
        for j in J:
            for t in T:
                cap = cap_ij[i][j] * baseline["road_availability_ij"][i][j][t] * X[j].X
                used = sum(FI[i, j, l, t].X for l in L)
                max_road_ij_util = max(max_road_ij_util, safe_div(used, cap))

    max_road_jh_util = 0.0
    for j in J:
        for h in H:
            for t in T:
                cap = cap_jh[j][h] * baseline["road_availability_jh"][j][h][t] * X[j].X
                used = sum(FO[j, h, l, t].X for l in L_Amb)
                max_road_jh_util = max(max_road_jh_util, safe_div(used, cap))
                
    max_staff_util = 0.0
    for j in J:
        cap = V[j].X
        for t in T:
            used = sum(TRT[j, l, t].X / params["staff_treatment_rate_by_severity"][l] for l in L)
            max_staff_util = max(max_staff_util, safe_div(used, cap))
            
    max_ccp_amb_util = 0.0
    for j in J:
        cap = params["ccp_ambulance_casualty_capacity"] * U[j].X
        for t in T:
            used = sum(FI[i, j, l, t].X for i in I for l in L_Amb)
            max_ccp_amb_util = max(max_ccp_amb_util, safe_div(used, cap))
            
    max_hosp_amb_util = 0.0
    for h in H:
        cap = params["hospital_ambulance_casualty_capacity"] * params["hospital_ambulance_fleet"][h]
        for t in T:
            used = sum(FO[j, h, l, t].X for j in J for l in L_Amb)
            max_hosp_amb_util = max(max_hosp_amb_util, safe_div(used, cap))

    # ---------------------------------------------------------
    # 6. 排版輸出報表
    # ---------------------------------------------------------
    print("\n" + "="*50)
    print(" 📊 DETERMINISTIC MODEL OPTIMIZATION REPORT ")
    print("="*50)
    
    # 基礎參數設定
    print(f"- Scenario數量: 1 (Baseline B00)")
    print(f"- Time Period數量: {len(T)}")
    print(f"- Disaster Area數量: {len(I)}")
    print(f"- Candidate CCP數量: {len(J)}")
    print(f"- Hospital數量: {len(H)}")
    print(f"- demand multiplier: {baseline['multipliers']['demand_multiplier']}")
    print(f"- hospital capacity multiplier: {baseline['multipliers']['hospital_capacity_multiplier']}")
    print(f"- road capacity multiplier: {baseline['multipliers']['road_capacity_multiplier']}")
    print("-" * 50)
    
    # Gurobi 求解狀態
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
    
    # 一階決策變數輸出
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
    
    # 業務指標 (KPIs)
    print("- total_demand:                  {:.2f}".format(total_demand))
    print("- total_transported_to_ccp (FI): {:.2f}".format(tot_FI))
    print("- total_transferred_to_hospital (FO): {:.2f}".format(tot_FO))
    print("- total_remaining_disaster_area (RM): {:.2f} (所有期別加總)".format(tot_RM))
    print("- total_waiting_at_ccp (WAT):         {:.2f} (所有期別加總)".format(tot_WAT))
    print("-" * 50)
    
    # 利用率
    print("- max_ccp_utilization_%:                {:6.2f} %".format(max_ccp_util))
    print("- max_hospital_utilization_%:           {:6.2f} %".format(max_hosp_util))
    print("- max_road_ij_utilization_%:            {:6.2f} %".format(max_road_ij_util))
    print("- max_road_jh_utilization_%:            {:6.2f} %".format(max_road_jh_util))
    print("- max_staff_utilization_%:              {:6.2f} %".format(max_staff_util))
    print("- max_ccp_ambulance_utilization_%:      {:6.2f} %".format(max_ccp_amb_util))
    print("- max_hospital_ambulance_utilization_%: {:6.2f} %".format(max_hosp_amb_util))
    print("="*50)

if __name__ == "__main__":
    solve_deterministic_model()
