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

import math
from typing import Any

import gurobipy as gp
from gurobipy import GRB


# ====================================================================== #
# 有效不等式 Valid Inequalities                                           #
#                                                                        #
# 編號與 docs/有效不等式_實作規格.docx 完全一致；正確性驗證程式為            #
# tests/validate_vi.py（三關 + 八條反向對照）。開關在 config.py 的 VI_* 。 #
#                                                                        #
# 本檔負責 VI-1 ~ VI-5（作用於模型本身）；VI-6 ~ VI-8 只在 Benders master  #
# 出現，實作於 lshaped_core.py。                                          #
# ====================================================================== #
VI_KEYS = ("VI-1", "VI-2", "VI-3", "VI-4", "VI-5", "VI-6", "VI-7", "VI-8")
_VI_CONFIG_NAMES = {
    "VI-1": "VI_1_ROADCAP_IJ", "VI-2": "VI_2_ROADCAP_JH",
    "VI-3": "VI_3_HOSP_MERGE", "VI-4": "VI_4_STAFF_UB",
    "VI-5": "VI_5_OPEN_USE",   "VI-6": "VI_6_THETA_LB",
    "VI-7": "VI_7_THETA_UB",   "VI-8": "VI_8_AGG_RELAX",
}


def vi_flags(vi_cfg: dict[str, Any] | None = None) -> dict[str, bool]:
    """解析八條 VI 的開關。

    vi_cfg=None            → 全部讀 config.VI_*（正常執行路徑）
    vi_cfg={"VI-3": False} → 只覆寫該條，其餘仍讀 config（ablation 用）
    vi_cfg={"all": False}  → 全部關閉（驗證程式的基準線）
    """
    try:
        import config as _cfg
    except ImportError:            # 不在 model core 的 sys.path 下也要能 import
        _cfg = None
    master_on = bool(getattr(_cfg, "VI_ENABLED", False)) if _cfg is not None else False
    out = {k: (master_on and bool(getattr(_cfg, _VI_CONFIG_NAMES[k], False)))
           for k in VI_KEYS}
    if vi_cfg:
        if "all" in vi_cfg:
            out = {k: bool(vi_cfg["all"]) for k in VI_KEYS}
        for k in VI_KEYS:
            if k in vi_cfg:
                out[k] = bool(vi_cfg[k])
    return out


def vi_cumulative_demand(scenario_data: dict[str, Any], s: str,
                         I: list[str], L: list[str], T: list[str]):
    """{(i, t): Σ_{l∈L} Σ_{r=1}^{t} ξ_ilrs} —— VI-1 收緊係數所需的累積傷患數。"""
    out = {}
    for i in I:
        run = 0.0
        for t in T:
            run += sum(scenario_data["demand"][s][t][i].get(l, 0.0) for l in L)
            out[(i, t)] = run
    return out


def vi_staff_ub(params: dict[str, Any], j: str, L: list[str]) -> float:
    """VI-4 的收緊係數 min{ v̄_j, ⌈Σ_{l∈L} k_jl/α_l⌉ }。

    由 (22)(23) 得 TRT_jlt ≤ k_jl X_j，代入 (24) 可知 V_j 的實質需求恆不超過
    Σ_l k_jl/α_l；V_j 為整數故取上取整。務必是 ceil 而非 floor —— floor 會
    切掉「需求落在兩個整數之間」時唯一夠用的那個整數配置。
    """
    need = sum(params["ccp_physical_capacity_by_severity"][l]
               / params["staff_treatment_rate_by_severity"][l] for l in L)
    return min(float(params["ccp_staff_upper_bound"][j]), float(math.ceil(need - 1e-9)))


def vi_ccp_transfer_capacity(params: dict[str, Any], L_transfer: list[str]) -> float:
    """VI-2 的收緊係數 Σ_{l∈L^Amb} k_jl（本模型的 k_jl 對 j 為常數）。"""
    return sum(params["ccp_physical_capacity_by_severity"][l] for l in L_transfer)


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
    vi_cfg: dict[str, Any] | None = None,
    env: gp.Env | None = None,
) -> tuple[gp.Model, dict[str, Any]]:
    """Build and return a (model, vars_dict) pair.

    Parameters
    ----------
    fixed_first_stage
        When provided, the first-stage variables X/V/U/Y are fixed to the
        supplied values by setting lb == ub.  Used for EEV evaluation.
        Expected keys: "X" ({j: 0|1}), "V" ({j: int}), "U" ({j: int}),
                       "Y" ({(h, j): int}).
    vi_cfg
        有效不等式開關；None = 讀 config.VI_*。詳見 vi_flags()。
        全部關閉時本函式建出的模型與加入 VI 之前逐位相同。
    env
        Optional dedicated Gurobi environment（平行求解時每執行緒各一個）。
        None = 預設環境，行為與舊版完全相同。純管線參數，不影響模型邏輯。
    """
    model = gp.Model(model_name, env=env) if env is not None else gp.Model(model_name)
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", time_limit)
    model.setParam("MIPGap", mip_gap)

    # ------------------------------------------------------------------ #
    # 有效不等式開關與預先計算                                              #
    # ------------------------------------------------------------------ #
    _vi = vi_flags(vi_cfg)
    if fixed_first_stage is not None:
        # 第一階段被外部固定時（Benders 的 ScenarioOracle、EEV 評估），
        # VI-4 與 VI-5 一律關閉。這兩條是「決定 x 的時候」才成立的最佳性論證，
        # 硬加在一個外部給定的 x 上會讓模型不可行 —— 例如 master 的取整啟發式
        # 交來 X_j=1, V_j=0 的點，VI-5 會把它判成無解，整個 Benders 迴圈就斷了。
        _vi = dict(_vi); _vi["VI-4"] = False; _vi["VI-5"] = False
    _vi_tr_cap = vi_ccp_transfer_capacity(params, L_transfer) if _vi["VI-2"] else 0.0
    _vi_cum = ({s: vi_cumulative_demand(scenario_data, s, I, L, T) for s in S}
               if _vi["VI-1"] else {})

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
    scenario_cost_expr: dict[str, Any] = {}
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
        scenario_cost_expr[s] = scenario_cost

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
        # VI-4：(5) → (5′)，把 X_j 的係數由 v̄_j 收緊為 min{ v̄_j, ⌈Σ_l k_jl/α_l⌉ }
        _v_ub = (vi_staff_ub(params, j, L) if _vi["VI-4"]
                 else params["ccp_staff_upper_bound"][j])
        model.addConstr(V[j] <= _v_ub * X[j], f"Logic_V_{j}")
        model.addConstr(U[j] <= params["ccp_ambulance_upper_bound"][j] * X[j], f"Logic_U_{j}")
        model.addConstr(
            gp.quicksum(Y[h, j] for h in H) <= params["ccp_supply_upper_bound"][j] * X[j],
            f"Logic_Y_{j}",
        )
        if _vi["VI-5"]:
            # VI-5：開了站就必須配置醫護與物資。否則該站在所有情境中完全不會被
            # 使用（(24)(25) 會把 TRT/REG 壓成 0），而關掉它可省下 f_j > 0。
            model.addConstr(X[j] <= V[j], f"VI5_staff_{j}")
            model.addConstr(X[j] <= gp.quicksum(Y[h, j] for h in H), f"VI5_supply_{j}")

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
                    _coef = cap_ij[i][j] * sd["road_availability_ij"][s][i][j][t]
                    if _vi["VI-1"]:
                        # (11) → (11′)：災區 i 到第 t 期為止累積產生的傷患數也是
                        # 有效上界（由 (15)(16) 與 RM ≥ 0 推得），取兩者較小者。
                        _coef = min(_coef, _vi_cum[s][(i, t)])
                    model.addConstr(
                        gp.quicksum(FI[s, i, j, l, t] for l in L) <= _coef * X[j],
                        f"RoadCap_IJ_{s}_{i}_{j}_{t}",
                    )

            # Road capacity j→h
            for j in J:
                for h in H:
                    _coef = cap_jh[j][h] * sd["road_availability_jh"][s][j][h][t]
                    if _vi["VI-2"]:
                        # (12) → (12′)：單期能送出 CCP j 的人數不超過該站需後送
                        # 嚴重度的床位總和 Σ_{l∈L^Amb} k_jl（由 (19)(18)(21)(22) 推得）。
                        _coef = min(_coef, _vi_tr_cap)
                    model.addConstr(
                        gp.quicksum(FO[s, j, h, l, t] for l in L_transfer) <= _coef * X[j],
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
                _eta_b = (params["hospital_ambulance_casualty_capacity"]
                          * params["hospital_ambulance_fleet"][h])
                _hcap = sd["hospital_receiving_capacity"][s][h][t]
                _out_h = gp.quicksum(FO[s, j, h, l, t]
                                     for j in J for l in L_transfer)
                if _vi["VI-3"]:
                    # VI-3：(14) 與 (26) 的左手邊逐字相同，同一個左式受兩個上界
                    # 拘束等價於受較小者拘束，故合併為一條（省 |H|·|T|·|S| 條）。
                    model.addConstr(_out_h <= min(_eta_b, _hcap),
                                    f"Hosp_AmbCap_{s}_{h}_{t}")
                else:
                    model.addConstr(_out_h <= _eta_b, f"Hosp_AmbCap_{s}_{h}_{t}")
                    model.addConstr(_out_h <= _hcap, f"Hosp_ReceiveCap_{s}_{h}_{t}")

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
        # 供 extensive-form 風險入口重用（純附加，不改目標式/限制式）
        "first_stage_cost_expr": first_stage_cost,
        "scenario_cost_expr": scenario_cost_expr,
        "vi_flags": _vi,
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
