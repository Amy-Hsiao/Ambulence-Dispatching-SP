"""vi_reference.py — 八條有效不等式的「獨立參考實作」，僅供正確性驗證使用。

本模組刻意不放進 model core/，也不修改任何既有模組。它是規格書
docs/有效不等式_實作規格.docx 的第二份實作，用來對照 model core 的原始模型。

為什麼要獨立寫一份：讓同一份程式自己檢查自己是抓不到錯的。本模組與
model core 各自獨立實作同一套數學，兩者互相驗證才有意義。日後把 VI 正式
寫進 model core 之後，本模組仍應保留，繼續當獨立的對照組。

編號與規格書完全一致：
    VI-1  收緊式 (11) 的道路容量係數     [EXACT]  第二階段
    VI-2  收緊式 (12) 的道路容量係數     [EXACT]  第二階段
    VI-3  合併式 (14) 與式 (26)          [EXACT]  第二階段
    VI-4  收緊式 (5) 的醫護配置上界      [OPT]    第一階段
    VI-5  開站使用連結                   [OPT]    第一階段
    VI-6  θ_s 的情境下界                 [RELAX]  Benders master
    VI-7  θ_s 的情境上界                 [OPT]    Benders master
    VI-8  每情境彙總鬆弛（十條 + 連結式） [RELAX]  Benders master

VI-1..VI-5 作用於模型本身，故以「就地改寫已建好的 Gurobi model」的方式套用
（chgCoeff / 改 RHS / 加限制式），完全不動 build_gurobi_model。
VI-6..VI-8 只在 master 出現，extensive form 沒有 θ_s，故不套用到模型，
改以「計算它們給出的下界／上界」的方式驗證。
"""
from __future__ import annotations

import math
from typing import Any

import gurobipy as gp
from gurobipy import GRB

import extensive_form_core as model_core


class SolveFailed(RuntimeError):
    """子問題／彙總 LP 未達最佳。status 供呼叫端分辨超時與不可行。"""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


# ===================================================================== #
# 目錄                                                                   #
# ===================================================================== #
VI_META = [
    dict(id="VI-1", name="收緊式 (11) 的道路容量係數", kind="EXACT",
         stage="第二階段", gates=(1, 2, 3)),
    dict(id="VI-2", name="收緊式 (12) 的道路容量係數", kind="EXACT",
         stage="第二階段", gates=(1, 2, 3)),
    dict(id="VI-3", name="合併式 (14) 與式 (26)", kind="EXACT",
         stage="第二階段", gates=(1, 2, 3)),
    dict(id="VI-4", name="收緊式 (5) 的醫護配置上界", kind="OPT",
         stage="第一階段", gates=(1, 3)),
    dict(id="VI-5", name="開站使用連結", kind="OPT",
         stage="第一階段", gates=(1, 3)),
    dict(id="VI-6", name="θ_s 的情境下界", kind="RELAX",
         stage="master", gates=(2,)),
    dict(id="VI-7", name="θ_s 的情境上界", kind="OPT",
         stage="master", gates=(2, 3)),
    dict(id="VI-8", name="每情境彙總鬆弛", kind="RELAX",
         stage="master", gates=(2,)),
]
MODEL_VIS = ("VI-1", "VI-2", "VI-3", "VI-4", "VI-5")     # 可套進 extensive form
MASTER_VIS = ("VI-6", "VI-7", "VI-8")                     # 只驗證界，不套進模型


# --------------------------------------------------------------------- #
# 反向對照（negative control）用的故意破壞開關。                            #
#                                                                       #
# 驗證程式全綠有一個致命的可能：它根本沒在檢查任何東西。唯一能排除這點的      #
# 辦法，是故意寫錯一條 VI，確認驗證程式真的會判 FAIL。                      #
# validate_vi.py --self-test 會依序打開下列開關各跑一次。                   #
# 正常執行時本 dict 恆為空，對結果沒有任何影響。                            #
# --------------------------------------------------------------------- #
SABOTAGE: dict[str, float] = {}


def _sab(key):
    return SABOTAGE.get(key, 1.0)


# 每條 VI 都要有自己的破壞點，否則反向對照只證明了「有掛鉤的那幾條」有效。
# 每個破壞都刻意錨在一個「該界本來就是緊的」樣本上，確保一定會被抓到：
#   vi1/vi2/vi3_scale：右手邊過度收緊 → 切掉可行解 → 關卡一的最佳值上升
#   vi4_bound        ：把 V_j 上界壓到 1 → 切掉最佳解 → 關卡一
#   vi5_mult         ：把 X_j ≤ V_j 改成 2·X_j ≤ V_j → 切掉最佳解 → 關卡一
#   vi6_scale        ：下界灌水（x̄ 樣本上本來相等）→ 關卡二
#   vi7_scale        ：上界縮水（全零樣本上本來相等）→ 關卡二
#   vi8_scale        ：彙總界灌水（全零樣本上本來相等）→ 關卡二
SABOTAGE_CASES = {
    "VI-1": ({"vi1_scale": 0.5}, 1, "式 (11′) 右手邊 ×0.5（過度收緊）"),
    "VI-2": ({"vi2_scale": 0.5}, 1, "式 (12′) 右手邊 ×0.5（過度收緊）"),
    "VI-3": ({"vi3_scale": 0.5}, 1, "合併後右手邊 ×0.5（過度收緊）"),
    "VI-4": ({"vi4_bound": 1.0}, 1, "V_j 上界壓成 1（切掉最佳解）"),
    "VI-5": ({"vi5_mult": 1.0}, 1, "改成 (nv+1)·X_j ≤ V_j（強到開不了站）"),
    "VI-6": ({"vi6_scale": 1.5}, 2, "下界 ×1.5（灌水，會超過真實 Q）"),
    "VI-7": ({"vi7_scale": 0.5}, 2, "上界 ×0.5（縮水，會低於真實 Q）"),
    "VI-8": ({"vi8_scale": 2.0}, 2, "彙總界 ×2.0（灌水）"),
}


# ===================================================================== #
# 參數存取小工具                                                          #
# ===================================================================== #
def _ix(obj, key):
    """params 裡有些欄位是 dict（per j / per h），有些是純量；一律用這個取。"""
    return obj[key] if isinstance(obj, dict) else obj


def unpack(inst):
    """把 instance 拆成驗證程式常用的一組別名。"""
    st = inst["sets"]
    return dict(
        I=st["I"], J=st["J"], H=st["H"], L=st["L"],
        Ltr=st["L_transfer"], T=st["T"], S=st["S"],
        p=inst["deterministic_parameters"],
        sd=inst["scenario_data"],
        cap_ij=inst["road_capacity"]["cap_ij"],
        cap_jh=inst["road_capacity"]["cap_jh"],
        cost_ij=inst["transport_cost"]["cost_ij"],
        cost_jh=inst["transport_cost"]["cost_jh"],
    )


def demand(sd, s, t, i, l):
    """ξ_ilts —— 與 extensive_form_core 中完全相同的取法。"""
    return sd["demand"][s][t][i].get(l, 0.0)


def cum_demand_area(sd, s, i, T, t_idx, L):
    """Σ_{l∈L} Σ_{r=1}^{t} ξ_ilrs —— 災區 i 到第 t 期為止的累積傷患（不分嚴重度）。"""
    return sum(demand(sd, s, T[r], i, l) for r in range(t_idx + 1) for l in L)


def first_stage_cost(inst, x):
    """C¹(x) = Σ f_j X_j + cv Σ V_j + ca Σ U_j + Σ cy_hj Y_hj。"""
    d = unpack(inst)
    p = d["p"]
    tot = sum(_ix(p["ccp_fixed_opening_cost"], j) * x["X"][j] for j in d["J"])
    tot += p["staff_unit_assignment_cost"] * sum(x["V"][j] for j in d["J"])
    tot += p["ccp_ambulance_unit_assignment_cost"] * sum(x["U"][j] for j in d["J"])
    tot += sum(p["supply_allocation_cost_from_hospital_to_ccp"][h][j] * x["Y"][(h, j)]
               for h in d["H"] for j in d["J"])
    return tot


def staff_ub_tightened(inst, j):
    """VI-4 的新係數 min{ v̄_j, ⌈Σ_l k_jl/α_l⌉ }。"""
    d = unpack(inst)
    p = d["p"]
    need = sum(_ix(p["ccp_physical_capacity_by_severity"], l)
               / p["staff_treatment_rate_by_severity"][l] for l in d["L"])
    return min(_ix(p["ccp_staff_upper_bound"], j), math.ceil(need - 1e-9))


def x_bar(inst):
    """x̄ —— 第一階段變數的逐分量上界向量（VI-6 用）。整數變數一律下取整。"""
    d = unpack(inst)
    p = d["p"]
    X = {j: 1 for j in d["J"]}
    V = {j: int(math.floor(_ix(p["ccp_staff_upper_bound"], j))) for j in d["J"]}
    U = {j: int(math.floor(_ix(p["ccp_ambulance_upper_bound"], j))) for j in d["J"]}
    Y = {(h, j): int(math.floor(min(_ix(p["hospital_supply_upper_bound"], h),
                                    _ix(p["ccp_supply_upper_bound"], j))))
         for h in d["H"] for j in d["J"]}
    return {"X": X, "V": V, "U": U, "Y": Y}


# ===================================================================== #
# VI-1 ~ VI-5：就地套用到已建好的 extensive form                          #
# ===================================================================== #
def apply_vi1(model, v, inst):
    """(11) → (11′)：把 X_j 的係數由 c_ij·u_ijts 收緊為 min{ c_ij·u_ijts, 累積需求 }。"""
    d = unpack(inst); sd = d["sd"]; X = v["X"]
    model.update()
    n = 0
    for s in d["S"]:
        for i in d["I"]:
            for t_idx, t in enumerate(d["T"]):
                cum = cum_demand_area(sd, s, i, d["T"], t_idx, d["L"])
                for j in d["J"]:
                    c = model.getConstrByName(f"RoadCap_IJ_{s}_{i}_{j}_{t}")
                    if c is None:
                        raise KeyError(f"找不到限制式 RoadCap_IJ_{s}_{i}_{j}_{t}")
                    old = d["cap_ij"][i][j] * sd["road_availability_ij"][s][i][j][t]
                    new = min(old, cum) * _sab("vi1_scale")
                    if new < old - 1e-12:
                        model.chgCoeff(c, X[j], -new)
                        n += 1
    model.update()
    return dict(changed=n, added=0, removed=0)


def apply_vi2(model, v, inst):
    """(12) → (12′)：把 X_j 的係數收緊為 min{ c_jh·w_jhts, Σ_{l∈L^Amb} k_jl }。"""
    d = unpack(inst); sd = d["sd"]; X = v["X"]; p = d["p"]
    model.update()
    n = 0
    for j in d["J"]:
        kcap = sum(_ix(p["ccp_physical_capacity_by_severity"], l) for l in d["Ltr"])
        for s in d["S"]:
            for h in d["H"]:
                for t in d["T"]:
                    c = model.getConstrByName(f"RoadCap_JH_{s}_{j}_{h}_{t}")
                    if c is None:
                        raise KeyError(f"找不到限制式 RoadCap_JH_{s}_{j}_{h}_{t}")
                    old = d["cap_jh"][j][h] * sd["road_availability_jh"][s][j][h][t]
                    new = min(old, kcap) * _sab("vi2_scale")
                    if new < old - 1e-12:
                        model.chgCoeff(c, X[j], -new)
                        n += 1
    model.update()
    return dict(changed=n, added=0, removed=0)


def apply_vi3(model, v, inst):
    """(14) 與 (26) 合併為一條：RHS 取 min，並刪掉 (26)。"""
    d = unpack(inst); sd = d["sd"]; p = d["p"]
    model.update()
    n = 0
    removed = 0
    for s in d["S"]:
        for h in d["H"]:
            eta_b = (p["hospital_ambulance_casualty_capacity"]
                     * _ix(p["hospital_ambulance_fleet"], h))
            for t in d["T"]:
                c14 = model.getConstrByName(f"Hosp_AmbCap_{s}_{h}_{t}")
                c26 = model.getConstrByName(f"Hosp_ReceiveCap_{s}_{h}_{t}")
                if c14 is None or c26 is None:
                    raise KeyError(f"找不到 Hosp_AmbCap / Hosp_ReceiveCap {s}_{h}_{t}")
                hcap = sd["hospital_receiving_capacity"][s][h][t]
                new = min(eta_b, hcap) * _sab("vi3_scale")
                # 只有右手邊真的變小才算「數學上有作用」；刪掉 (26) 另外計數，
                # 因為在 min 從未綁到的 instance 上，(26) 本來就是冗餘的。
                if new < eta_b - 1e-12:
                    n += 1
                c14.RHS = new
                model.remove(c26)
                removed += 1
    model.update()
    return dict(changed=n, added=0, removed=removed)


def apply_vi4(model, v, inst):
    """(5) → (5′)：把 Logic_V_j 中 X_j 的係數由 v̄_j 收緊為 min{ v̄_j, ⌈Σ k/α⌉ }。"""
    d = unpack(inst); X = v["X"]
    model.update()
    n = 0
    for j in d["J"]:
        c = model.getConstrByName(f"Logic_V_{j}")
        if c is None:
            raise KeyError(f"找不到限制式 Logic_V_{j}")
        old = _ix(d["p"]["ccp_staff_upper_bound"], j)
        new = SABOTAGE.get("vi4_bound", staff_ub_tightened(inst, j))
        if new < old - 1e-12:
            model.chgCoeff(c, X[j], -float(new))
            n += 1
    model.update()
    return dict(changed=n, added=0, removed=0)


def apply_vi5(model, v, inst):
    """新增 X_j ≤ V_j 與 X_j ≤ Σ_h Y_hj。"""
    d = unpack(inst); X, V, Y = v["X"], v["V"], v["Y"]
    # 反向對照用：把倍率乘到「大於整個醫護資源池」，任何 CCP 都開不起來，
    # 保證切掉最佳解。倍率若只設 2，在最佳解本來就有 V_j ≥ 2 的 instance 上
    # 根本咬不到，反向對照會變成無效的測試。
    m = (SABOTAGE["vi5_mult"] * d["p"]["total_available_staff"] + 1
         if "vi5_mult" in SABOTAGE else 1.0)
    n = 0
    for j in d["J"]:
        model.addConstr(m * X[j] <= V[j], f"VI5_staff_{j}")
        model.addConstr(m * X[j] <= gp.quicksum(Y[h, j] for h in d["H"]),
                        f"VI5_supply_{j}")
        n += 2
    model.update()
    return dict(changed=0, added=n, removed=0)


APPLY = {"VI-1": apply_vi1, "VI-2": apply_vi2, "VI-3": apply_vi3,
         "VI-4": apply_vi4, "VI-5": apply_vi5}


def build_extensive(inst, vis=(), time_limit=600.0, mip_gap=0.0, env=None,
                    name="validate"):
    """建 extensive form 並套用指定的 VI（vis 為 VI 編號的序列）。"""
    d = unpack(inst)
    model, v = model_core.build_gurobi_model(
        d["I"], d["J"], d["H"], d["L"], d["Ltr"], d["T"], d["S"],
        d["p"], d["sd"], d["sd"]["probability"],
        d["cap_ij"], d["cap_jh"], d["cost_ij"], d["cost_jh"],
        model_name=name, time_limit=time_limit, mip_gap=mip_gap, env=env,
    )
    model.setParam("OutputFlag", 0)
    touched = dict(changed=0, added=0, removed=0)
    for vid in vis:
        if vid not in APPLY:
            raise ValueError(f"{vid} 不是可套用到 extensive form 的 VI")
        got = APPLY[vid](model, v, inst)
        for k in touched:
            touched[k] += got[k]
    model.update()
    return model, v, touched


# ===================================================================== #
# 真實的第二階段成本 Q(x; ω^s)                                            #
# ===================================================================== #
_FIRST_STAGE_ROW_PREFIXES = ("Total_Staff", "Total_CCP_Ambulances",
                             "Hosp_Supply_", "Logic_V_", "Logic_U_", "Logic_Y_")


def true_Q(inst, x, s, env=None, relax_first_stage=False, time_limit=300.0,
           return_flows=False):
    """Q(x; ω^s)：把第一階段固定成 x，只留情境 s，解出真實的第二階段成本。

    relax_first_stage=True 時暫時把一階限制式的右手邊放寬至 +∞。
    這是 VI-6 計算 q̲_s = Q(x̄; ω^s) 時必須的 —— x̄ 是逐分量上界，
    本來就不滿足資源池限制式 (2)(3)(4)；而 Q(·) 的定義只把 x 當作
    第二階段的右手邊參數，並不要求 x 屬於第一階段可行域。
    """
    d = unpack(inst)
    sub_sd = {k: {s: d["sd"][k][s]} for k in
              ("demand", "road_availability_ij", "road_availability_jh",
               "hospital_receiving_capacity")}
    model, v = model_core.build_gurobi_model(
        d["I"], d["J"], d["H"], d["L"], d["Ltr"], d["T"], [s],
        d["p"], sub_sd, {s: 1.0},
        d["cap_ij"], d["cap_jh"], d["cost_ij"], d["cost_jh"],
        model_name=f"Q_{s}", time_limit=time_limit, mip_gap=0.0,
        fixed_first_stage=x, env=env,
    )
    model.setParam("OutputFlag", 0)
    if relax_first_stage:
        model.update()
        for c in model.getConstrs():
            if c.ConstrName.startswith(_FIRST_STAGE_ROW_PREFIXES):
                c.RHS = GRB.INFINITY
        model.update()
    model.optimize()
    if model.status != GRB.OPTIMAL:
        st = model.status
        model.dispose()
        raise SolveFailed(f"Q(x; {s}) 未達最佳，status={st}"
                          f"（relax_first_stage={relax_first_stage}）", st)
    q = model.ObjVal - first_stage_cost(inst, x)
    flows = None
    if return_flows:
        flows = {"FI": {k: var.X for k, var in v["FI"].items()},
                 "FO": {k: var.X for k, var in v["FO"].items()}}
    model.dispose()
    return (q, flows) if return_flows else q


# ===================================================================== #
# VI-6 / VI-7：θ_s 的下界與上界                                           #
# ===================================================================== #
def bound_vi6(inst, s, env=None, time_limit=300.0):
    """q̲_s := Q(x̄; ω^s)。需解一個 LP（每情境一次，之後為常數）。"""
    return true_Q(inst, x_bar(inst), s, env=env, relax_first_stage=True,
                  time_limit=time_limit) * _sab("vi6_scale")


def bound_vi7(inst, s):
    """q̄_s := Q(0; ω^s) = Σ_i Σ_l Σ_t ρ_l ( Σ_{r=1}^{t} ξ_ilrs )　—— 閉式，不需求解。"""
    d = unpack(inst); sd = d["sd"]
    rho = d["p"]["disaster_area_remaining_penalty_by_severity"]
    tot = 0.0
    for i in d["I"]:
        for l in d["L"]:
            cum = 0.0
            for t in d["T"]:
                cum += demand(sd, s, t, i, l)
                tot += rho[l] * cum
    return tot * _sab("vi7_scale")


# ===================================================================== #
# VI-8：每情境彙總鬆弛                                                    #
# ===================================================================== #
def bound_vi8(inst, x, s, env=None, time_limit=300.0):
    """解彙總鬆弛 LP，回傳它給 θ_s 的下界（即連結式的右手邊最佳值）。

    變數（皆為對空間索引加總後的總量，與規格書 2.8 節一一對應）：
        fi[l][t]  = Σ_{i∈I} Σ_{j∈J} FI_ijlt(s)        l ∈ L
        rm[l][t]  = Σ_{i∈I} RM_ilt(s)                 l ∈ L
        fo[l][t]  = Σ_{j∈J} Σ_{h∈H} FO_jhlt(s)        l ∈ L^Amb
        wat[l][t] = Σ_{j∈J} WAT_jlt(s)                l ∈ L^Amb
    """
    d = unpack(inst); p = d["p"]; sd = d["sd"]
    L, Ltr, T, I, Jset, H = d["L"], d["Ltr"], d["T"], d["I"], d["J"], d["H"]
    nT = len(T)

    tau = {l: int(p["treatment_duration_by_severity"][l]) for l in L}
    alpha = p["staff_treatment_rate_by_severity"]
    beta = p["supply_consumption_by_severity"]
    rho = p["disaster_area_remaining_penalty_by_severity"]
    delta = p["ccp_waiting_penalty_by_severity"]
    kap = p["ccp_ambulance_casualty_capacity"]
    eta = p["hospital_ambulance_casualty_capacity"]
    kcap = {l: _ix(p["ccp_physical_capacity_by_severity"], l) for l in L}

    sumX = sum(x["X"][j] for j in Jset)
    sumV = sum(x["V"][j] for j in Jset)
    sumU = sum(x["U"][j] for j in Jset)
    sumY = sum(x["Y"][(h, j)] for h in H for j in Jset)

    m = gp.Model(f"agg_{s}", env=env) if env is not None else gp.Model(f"agg_{s}")
    m.setParam("OutputFlag", 0)
    m.setParam("TimeLimit", time_limit)
    fi = {(l, r): m.addVar(lb=0.0, name=f"fi_{l}_{r}") for l in L for r in range(nT)}
    rm = {(l, r): m.addVar(lb=0.0, name=f"rm_{l}_{r}") for l in L for r in range(nT)}
    fo = {(l, r): m.addVar(lb=0.0, name=f"fo_{l}_{r}") for l in Ltr for r in range(nT)}
    wat = {(l, r): m.addVar(lb=0.0, name=f"wat_{l}_{r}") for l in Ltr for r in range(nT)}

    def win(l, ti):
        """(18) 的滾動窗 r = max(1, t−τ_l+1) … t，以 0-based 索引表示。"""
        return range(max(0, ti - tau[l] + 1), ti + 1)

    # (8.1) 災區人數守恆（(15)(16) 對 i 加總）
    for l in L:
        for ti, t in enumerate(T):
            arrive = sum(demand(sd, s, t, i, l) for i in I)
            prev = rm[(l, ti - 1)] if ti > 0 else 0.0
            m.addConstr(rm[(l, ti)] == prev + arrive - fi[(l, ti)], f"a81_{l}_{ti}")

    # (8.2) CCP 等待區人數守恆（(17)(19)(20)(21) 對 j 加總）
    for l in Ltr:
        for ti in range(nT):
            prev = wat[(l, ti - 1)] if ti > 0 else 0.0
            done = fi[(l, ti - tau[l])] if ti - tau[l] >= 0 else 0.0
            m.addConstr(wat[(l, ti)] == prev + done - fo[(l, ti)], f"a82_{l}_{ti}")

    # (8.3)(8.4) 實體容量（(17)(18)(22)(23) 對 j 加總）
    for ti in range(nT):
        for l in Ltr:
            m.addConstr(gp.quicksum(fi[(l, r)] for r in win(l, ti)) + wat[(l, ti)]
                        <= kcap[l] * sumX, f"a83_{l}_{ti}")
        for l in [x_ for x_ in L if x_ not in Ltr]:
            m.addConstr(gp.quicksum(fi[(l, r)] for r in win(l, ti))
                        <= kcap[l] * sumX, f"a84_{l}_{ti}")

    # (8.5) 醫護（(17)(18)(24) 對 j 加總）
    for ti in range(nT):
        m.addConstr(gp.quicksum((1.0 / alpha[l]) * gp.quicksum(fi[(l, r)] for r in win(l, ti))
                                for l in L) <= sumV, f"a85_{ti}")

    # (8.6) CCP 救護車（(13) 對 j 加總）
    for ti in range(nT):
        m.addConstr(gp.quicksum(fi[(l, ti)] for l in Ltr) <= kap * sumU, f"a86_{ti}")

    # (8.7) 物資（(17)(25) 對 j 加總）
    m.addConstr(gp.quicksum(beta[l] * fi[(l, ti)] for l in L for ti in range(nT))
                <= sumY, "a87")

    # (8.8) 醫院收治（VI-3 對 h 加總）
    for ti, t in enumerate(T):
        rhs = sum(min(eta * _ix(p["hospital_ambulance_fleet"], h),
                      sd["hospital_receiving_capacity"][s][h][t]) for h in H)
        m.addConstr(gp.quicksum(fo[(l, ti)] for l in Ltr) <= rhs, f"a88_{ti}")

    # (8.9) 入口道路（VI-1 對 i, j 加總）
    for ti, t in enumerate(T):
        rhs = 0.0
        for j in Jset:
            if not x["X"][j]:
                continue
            rhs += sum(min(d["cap_ij"][i][j] * sd["road_availability_ij"][s][i][j][t],
                           cum_demand_area(sd, s, i, T, ti, L)) for i in I)
        m.addConstr(gp.quicksum(fi[(l, ti)] for l in L) <= rhs, f"a89_{ti}")

    # (8.10) 出口道路（VI-2 對 j, h 加總）
    kcap_tr = sum(kcap[l] for l in Ltr)
    for ti, t in enumerate(T):
        rhs = 0.0
        for j in Jset:
            if not x["X"][j]:
                continue
            rhs += sum(min(d["cap_jh"][j][h] * sd["road_availability_jh"][s][j][h][t],
                           kcap_tr) for h in H)
        m.addConstr(gp.quicksum(fo[(l, ti)] for l in Ltr) <= rhs, f"a810_{ti}")

    # 連結式的右手邊 = 目標式
    min_tij = min(d["cost_ij"][i][j] for i in I for j in Jset)
    min_tjh = min(d["cost_jh"][j][h] for j in Jset for h in H)
    m.setObjective(
        gp.quicksum(rho[l] * rm[(l, ti)] for l in L for ti in range(nT))
        + gp.quicksum(delta[l] * wat[(l, ti)] for l in Ltr for ti in range(nT))
        + min_tij * gp.quicksum(fi[(l, ti)] for l in L for ti in range(nT))
        + min_tjh * gp.quicksum(fo[(l, ti)] for l in Ltr for ti in range(nT)),
        GRB.MINIMIZE)
    m.optimize()
    if m.status != GRB.OPTIMAL:
        st = m.status
        m.dispose()
        raise SolveFailed(f"VI-8 彙總 LP 未達最佳，status={st}", st)
    val = m.ObjVal * _sab("vi8_scale")
    nvars, ncons = m.NumVars, m.NumConstrs
    m.dispose()
    return val, nvars, ncons


# ===================================================================== #
# OPT 型的式子在給定解上是否被違反                                        #
# ===================================================================== #
def check_vi4_on(inst, x):
    """VI-4：V_j ≤ min{ v̄_j, ⌈Σ_l k_jl/α_l⌉ }。回傳違反清單。"""
    out = []
    for j in unpack(inst)["J"]:
        ub = staff_ub_tightened(inst, j) * x["X"][j]
        if x["V"][j] > ub + 1e-6:
            out.append((f"j={j}", x["V"][j] - ub))
    return out


def check_vi5_on(inst, x):
    """VI-5：X_j ≤ V_j 且 X_j ≤ Σ_h Y_hj。回傳違反清單。"""
    d = unpack(inst); out = []
    for j in d["J"]:
        if x["X"][j] > x["V"][j] + 1e-6:
            out.append((f"X_{j}≤V_{j}", x["X"][j] - x["V"][j]))
        sy = sum(x["Y"][(h, j)] for h in d["H"])
        if x["X"][j] > sy + 1e-6:
            out.append((f"X_{j}≤ΣY_h{j}", x["X"][j] - sy))
    return out


def check_vi1_on(inst, x, flows, scenarios=None):
    """VI-1：Σ_l FI_ijlt ≤ min{ c_ij u_ijts, 累積需求 } X_j。回傳違反清單。"""
    d = unpack(inst); sd = d["sd"]; out = []; slack = float("inf")
    for s in (scenarios or d["S"]):
        for i in d["I"]:
            for ti, t in enumerate(d["T"]):
                cum = cum_demand_area(sd, s, i, d["T"], ti, d["L"])
                for j in d["J"]:
                    lhs = sum(flows["FI"].get((s, i, j, l, t), 0.0) for l in d["L"])
                    rhs = min(d["cap_ij"][i][j] * sd["road_availability_ij"][s][i][j][t],
                              cum) * x["X"][j]
                    if x["X"][j]:          # X_j=0 的列恆為 0≤0，計入會讓鬆弛永遠是 0
                        slack = min(slack, rhs - lhs)
                    if lhs > rhs + 1e-6:
                        out.append((f"{s}/{i}/{j}/{t}", lhs - rhs))
    return out, slack


def check_vi2_on(inst, x, flows, scenarios=None):
    """VI-2：Σ_{l∈L^Amb} FO_jhlt ≤ min{ c_jh w_jhts, Σ_l k_jl } X_j。"""
    d = unpack(inst); sd = d["sd"]; p = d["p"]; out = []
    kcap = sum(_ix(p["ccp_physical_capacity_by_severity"], l) for l in d["Ltr"])
    slack = float("inf")
    for s in (scenarios or d["S"]):
        for j in d["J"]:
            for h in d["H"]:
                for t in d["T"]:
                    lhs = sum(flows["FO"].get((s, j, h, l, t), 0.0) for l in d["Ltr"])
                    rhs = min(d["cap_jh"][j][h] * sd["road_availability_jh"][s][j][h][t],
                              kcap) * x["X"][j]
                    if x["X"][j]:
                        slack = min(slack, rhs - lhs)
                    if lhs > rhs + 1e-6:
                        out.append((f"{s}/{j}/{h}/{t}", lhs - rhs))
    return out, slack


def check_vi3_on(inst, x, flows, scenarios=None):
    """VI-3：Σ_j Σ_l FO_jhlt ≤ min{ η b_h, h_hts }。"""
    d = unpack(inst); sd = d["sd"]; p = d["p"]; out = []; slack = float("inf")
    for s in (scenarios or d["S"]):
        for h in d["H"]:
            eta_b = (p["hospital_ambulance_casualty_capacity"]
                     * _ix(p["hospital_ambulance_fleet"], h))
            for t in d["T"]:
                lhs = sum(flows["FO"].get((s, j, h, l, t), 0.0)
                          for j in d["J"] for l in d["Ltr"])
                rhs = min(eta_b, sd["hospital_receiving_capacity"][s][h][t])
                slack = min(slack, rhs - lhs)
                if lhs > rhs + 1e-6:
                    out.append((f"{s}/{h}/{t}", lhs - rhs))
    return out, slack
