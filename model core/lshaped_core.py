"""
lshaped_core.py — Multi-cut L-shaped / Branch-and-Benders-Cut 演算法核心。

Phase 0：模組骨架 + build_master
Phase 1：ScenarioOracle（單情境 LP、reduced-cost cut）  ← 本版已實作
Phase 2：solve_classic（古典迭代迴圈）                   ← 本版已實作
Phase 3：solve_bbc（lazy callback B&BC）                 ← 本版已實作

數學設計見 L-shaped_implementation_plan.md 與 BBC_multicut_execution_plan.md。
不修改 extensive_form_core 的任何邏輯——子問題直接重用 build_gurobi_model。

Cut 推導（reduced-cost / 敏感度形式）
------------------------------------
子問題含全部一階變數（以 lb=ub 固定），其 LP 目標 = F(x̄) + Q_s(x̄)。
對固定變數 v：∂(total)/∂v = v.RC，而 ∂F/∂v = v.Obj（目標係數），
故 ∂Q_s/∂v = v.RC − v.Obj。optimality cut：

    θ_s ≥ Q_s(x̄) + Σ_v (v.RC − v.Obj)·(v − v̄)

由 LP 值函數對變數 bound 的凸性，此 cut 全域有效，且在 x̄ 處取等式。
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import gurobipy as gp
from gurobipy import GRB

import config
import extensive_form_core as model_core
import risk_core


# ====================================================================== #
# LBF — Lower Bounding Functional (Jensen-based average-scenario LP)      #
# ====================================================================== #

def _compute_average_scenario_data(
    instance: dict[str, Any],
    S_selected: list[str],
    norm_probs: dict[str, float],
) -> dict[str, Any]:
    """Compute probability-weighted average of scenario data across S_selected.

    Returns a flat (non-scenario-indexed) dict with keys:
        "demand"                    : {t: {i: {l: val}}}
        "road_availability_ij"      : {i: {j: {t: val}}}
        "road_availability_jh"      : {j: {h: {t: val}}}
        "hospital_receiving_capacity": {h: {t: val}}
    """
    sd = instance["scenario_data"]
    sets = instance["sets"]
    I, J, H = sets["I"], sets["J"], sets["H"]
    L = sets["L"]
    T = sets["T"]

    # demand[s][t][i][l] → avg_demand[t][i][l]
    avg_demand: dict[str, dict[str, dict[str, float]]] = {}
    for t in T:
        avg_demand[t] = {}
        for i in I:
            avg_demand[t][i] = {}
            # Collect all severity levels across scenarios
            all_l: set[str] = set()
            for s in S_selected:
                all_l.update(sd["demand"][s][t][i].keys())
            for l in all_l:
                avg_demand[t][i][l] = sum(
                    norm_probs[s] * sd["demand"][s][t][i].get(l, 0)
                    for s in S_selected
                )

    # road_availability_ij[s][i][j][t] → avg[i][j][t]
    avg_road_ij: dict[str, dict[str, dict[str, float]]] = {}
    for i in I:
        avg_road_ij[i] = {}
        for j in J:
            avg_road_ij[i][j] = {}
            for t in T:
                avg_road_ij[i][j][t] = sum(
                    norm_probs[s] * sd["road_availability_ij"][s][i][j][t]
                    for s in S_selected
                )

    # road_availability_jh[s][j][h][t] → avg[j][h][t]
    avg_road_jh: dict[str, dict[str, dict[str, float]]] = {}
    for j in J:
        avg_road_jh[j] = {}
        for h in H:
            avg_road_jh[j][h] = {}
            for t in T:
                avg_road_jh[j][h][t] = sum(
                    norm_probs[s] * sd["road_availability_jh"][s][j][h][t]
                    for s in S_selected
                )

    # hospital_receiving_capacity[s][h][t] → avg[h][t]
    avg_hosp_cap: dict[str, dict[str, float]] = {}
    for h in H:
        avg_hosp_cap[h] = {}
        for t in T:
            avg_hosp_cap[h][t] = sum(
                norm_probs[s] * sd["hospital_receiving_capacity"][s][h][t]
                for s in S_selected
            )

    return {
        "demand": avg_demand,
        "road_availability_ij": avg_road_ij,
        "road_availability_jh": avg_road_jh,
        "hospital_receiving_capacity": avg_hosp_cap,
    }


def _embed_lbf_in_master(
    m: gp.Model,
    mv: dict[str, Any],
    instance: dict[str, Any],
    S_selected: list[str],
    norm_probs: dict[str, float],
) -> None:
    """Embed the average-scenario second-stage LP into the master as an LBF.

    By Jensen's inequality, Q̄(x) = Σ p_s Q_s(x) ≥ Q(x; ξ̄) where ξ̄ is the
    probability-weighted average scenario.  This provides a structural lower
    bound on the weighted θ sum from the first iteration.

    Adds continuous second-stage variables (FI_avg, FO_avg, etc.) and all
    second-stage constraints using average scenario data.  Then adds a
    linking constraint:  Σ p_s θ_s ≥ (second-stage cost of avg scenario).
    """
    sets = instance["sets"]
    I, J, H = sets["I"], sets["J"], sets["H"]
    L = sets["L"]
    L_transfer = sets["L_transfer"]
    T = sets["T"]
    params = instance["deterministic_parameters"]
    cap_ij = instance["road_capacity"]["cap_ij"]
    cap_jh = instance["road_capacity"]["cap_jh"]
    cost_ij = instance["transport_cost"]["cost_ij"]
    cost_jh = instance["transport_cost"]["cost_jh"]

    avg = _compute_average_scenario_data(instance, S_selected, norm_probs)

    # LBF 區塊複製了整組二階限制式，VI-1/2/3 同樣適用（都是 EXACT，只收緊
    # big-M，不影響 Jensen 下界的合法性）。以平均情境資料計算收緊係數。
    _vi_lbf = (model_core.vi_flags(None)
               if getattr(config, "VI_APPLY_TO_LBF", False)
               else {k: False for k in model_core.VI_KEYS})
    _lbf_cum = {}
    if _vi_lbf["VI-1"]:
        for i in I:
            run = 0.0
            for t in T:
                run += sum(avg["demand"][t][i].get(l, 0.0) for l in L)
                _lbf_cum[(i, t)] = run
    _lbf_tr_cap = (model_core.vi_ccp_transfer_capacity(params, L_transfer)
                   if _vi_lbf["VI-2"] else 0.0)

    X, V, U, Y = mv["X"], mv["V"], mv["U"], mv["Y"]

    # ----- average-scenario second-stage continuous variables ----- #
    FI_a  = m.addVars(I, J, L,          T, vtype=GRB.CONTINUOUS, lb=0, name="FI_avg")
    FO_a  = m.addVars(J, H, L_transfer, T, vtype=GRB.CONTINUOUS, lb=0, name="FO_avg")
    RM_a  = m.addVars(I, L,             T, vtype=GRB.CONTINUOUS, lb=0, name="RM_avg")
    REG_a = m.addVars(J, L,             T, vtype=GRB.CONTINUOUS, lb=0, name="REG_avg")
    TRT_a = m.addVars(J, L,             T, vtype=GRB.CONTINUOUS, lb=0, name="TRT_avg")
    WAT_a = m.addVars(J, L_transfer,    T, vtype=GRB.CONTINUOUS, lb=0, name="WAT_avg")

    # ----- second-stage cost expression for the average scenario ----- #
    avg_second_cost = (
        gp.quicksum(
            params["disaster_area_remaining_penalty_by_severity"][l] * RM_a[i, l, t]
            for i in I for l in L for t in T
        )
        + gp.quicksum(
            params["ccp_waiting_penalty_by_severity"][l] * WAT_a[j, l, t]
            for j in J for l in L_transfer for t in T
        )
        + gp.quicksum(
            cost_ij[i][j] * FI_a[i, j, l, t]
            for i in I for j in J for l in L for t in T
        )
        + gp.quicksum(
            cost_jh[j][h] * FO_a[j, h, l, t]
            for j in J for h in H for l in L_transfer for t in T
        )
    )

    # ----- Jensen bounding constraint: Σ p_s θ_s ≥ avg second-stage cost ----- #
    theta = mv["theta"]
    if "__agg__" in theta:
        # single-cut: the aggregate θ already represents Σ p_s θ_s
        theta_sum = theta["__agg__"]
    else:
        theta_sum = gp.quicksum(norm_probs[s] * theta[s] for s in S_selected)
    m.addConstr(theta_sum >= avg_second_cost, "LBF_Jensen")

    # ----- replicate all second-stage constraints with average data ----- #
    for t_idx, t in enumerate(T):
        prev_t = T[t_idx - 1] if t_idx > 0 else None

        # Road capacity i→j
        for i in I:
            for j in J:
                _c = cap_ij[i][j] * avg["road_availability_ij"][i][j][t]
                if _vi_lbf["VI-1"]:
                    _c = min(_c, _lbf_cum[(i, t)])
                m.addConstr(
                    gp.quicksum(FI_a[i, j, l, t] for l in L) <= _c * X[j],
                    f"LBF_RoadCap_IJ_{i}_{j}_{t}",
                )

        # Road capacity j→h
        for j in J:
            for h in H:
                _c = cap_jh[j][h] * avg["road_availability_jh"][j][h][t]
                if _vi_lbf["VI-2"]:
                    _c = min(_c, _lbf_tr_cap)
                m.addConstr(
                    gp.quicksum(FO_a[j, h, l, t] for l in L_transfer) <= _c * X[j],
                    f"LBF_RoadCap_JH_{j}_{h}_{t}",
                )

        # CCP ambulance capacity
        for j in J:
            m.addConstr(
                gp.quicksum(FI_a[i, j, l, t] for i in I for l in L_transfer)
                <= params["ccp_ambulance_casualty_capacity"] * U[j],
                f"LBF_CCP_AmbCap_{j}_{t}",
            )

        # Hospital receiving capacity
        for h in H:
            _eta_b = (params["hospital_ambulance_casualty_capacity"]
                      * params["hospital_ambulance_fleet"][h])
            _hc = avg["hospital_receiving_capacity"][h][t]
            _o = gp.quicksum(FO_a[j, h, l, t] for j in J for l in L_transfer)
            if _vi_lbf["VI-3"]:
                m.addConstr(_o <= min(_eta_b, _hc), f"LBF_Hosp_AmbCap_{h}_{t}")
            else:
                m.addConstr(_o <= _eta_b, f"LBF_Hosp_AmbCap_{h}_{t}")
                m.addConstr(_o <= _hc, f"LBF_Hosp_ReceiveCap_{h}_{t}")

        # Remaining patients at disaster area
        for i in I:
            for l in L:
                prev_rm = RM_a[i, l, prev_t] if prev_t else 0
                demand_val = avg["demand"][t][i].get(l, 0)
                m.addConstr(
                    RM_a[i, l, t]
                    == prev_rm - gp.quicksum(FI_a[i, j, l, t] for j in J) + demand_val,
                    f"LBF_Flow_RM_{i}_{l}_{t}",
                )

        for j in J:
            # REG and TRT
            for l in L:
                m.addConstr(
                    REG_a[j, l, t] == gp.quicksum(FI_a[i, j, l, t] for i in I),
                    f"LBF_Flow_REG_{j}_{l}_{t}",
                )
                tau = int(params["treatment_duration_by_severity"][l])
                start_idx = max(0, t_idx - tau + 1)
                rolling = T[start_idx: t_idx + 1]
                m.addConstr(
                    TRT_a[j, l, t] == gp.quicksum(REG_a[j, l, r] for r in rolling),
                    f"LBF_Flow_TRT_{j}_{l}_{t}",
                )

            # WAT (ambulance-severity only)
            for l in L_transfer:
                tau = int(params["treatment_duration_by_severity"][l])
                prev_wat = WAT_a[j, l, prev_t] if prev_t else 0
                completed = REG_a[j, l, T[t_idx - tau]] if (t_idx - tau) >= 0 else 0
                m.addConstr(
                    WAT_a[j, l, t]
                    == prev_wat + completed - gp.quicksum(FO_a[j, h, l, t] for h in H),
                    f"LBF_Flow_WAT_{j}_{l}_{t}",
                )

            # Physical capacity (TRT + WAT for ambulance severities)
            for l in L_transfer:
                m.addConstr(
                    TRT_a[j, l, t] + WAT_a[j, l, t]
                    <= params["ccp_physical_capacity_by_severity"][l] * X[j],
                    f"LBF_CCP_PhysicalCap_{j}_{l}_{t}",
                )
            for l in [sev for sev in L if sev not in L_transfer]:
                m.addConstr(
                    TRT_a[j, l, t]
                    <= params["ccp_physical_capacity_by_severity"][l] * X[j],
                    f"LBF_CCP_PhysicalCap_{j}_{l}_{t}",
                )

            # Staff capacity
            m.addConstr(
                gp.quicksum(
                    TRT_a[j, l, t] / params["staff_treatment_rate_by_severity"][l]
                    for l in L
                ) <= V[j],
                f"LBF_StaffCap_{j}_{t}",
            )

    # Supply consumption (outside t loop)
    for j in J:
        m.addConstr(
            gp.quicksum(
                params["supply_consumption_by_severity"][l] * REG_a[j, l, t]
                for l in L for t in T
            ) <= gp.quicksum(Y[h, j] for h in H),
            f"LBF_SupplyCap_{j}",
        )

    m.update()


# ====================================================================== #
# Phase 1 — ScenarioOracle                                               #
# ====================================================================== #

class ScenarioOracle:
    """單一情境 s 的二階 LP oracle。整個求解過程只建一次模型，
    之後每次 evaluate() 僅更新一階變數的 bounds 並以 dual simplex 熱啟動重解。
    """

    def __init__(self, instance: dict[str, Any], s: str,
                 time_limit: float = 300.0, threads: int = 1,
                 env: gp.Env | None = None,
                 vi_cfg: dict[str, Any] | None = None):
        sets = instance["sets"]
        self.s   = s
        self.I   = sets["I"]
        self.J   = sets["J"]
        self.H   = sets["H"]
        L        = sets["L"]
        L_tr     = sets["L_transfer"]
        T        = sets["T"]
        params   = instance["deterministic_parameters"]
        sd_full  = instance["scenario_data"]

        sub_sd = {
            "demand":                      {s: sd_full["demand"][s]},
            "road_availability_ij":        {s: sd_full["road_availability_ij"][s]},
            "road_availability_jh":        {s: sd_full["road_availability_jh"][s]},
            "hospital_receiving_capacity": {s: sd_full["hospital_receiving_capacity"][s]},
        }

        # 先以零解固定一階（零解必滿足一階資源限制式），建好後再逐次改 bounds
        zero_fs = {
            "X": {j: 0 for j in self.J},
            "V": {j: 0 for j in self.J},
            "U": {j: 0 for j in self.J},
            "Y": {(h, j): 0 for h in self.H for j in self.J},
        }
        m, v = model_core.build_gurobi_model(
            self.I, self.J, self.H, L, L_tr, T, [s],
            params, sub_sd, {s: 1.0},
            instance["road_capacity"]["cap_ij"],
            instance["road_capacity"]["cap_jh"],
            instance["transport_cost"]["cost_ij"],
            instance["transport_cost"]["cost_jh"],
            model_name=f"Oracle[{s}]",
            time_limit=time_limit,
            mip_gap=1e-9,          # LP：gap 參數無作用，設小值以防萬一
            fixed_first_stage=zero_fs,
            vi_cfg=vi_cfg,
            env=env,
        )
        # 一階變數鬆弛為連續（值仍被 lb=ub 固定）→ 模型成為純 LP → 才有 RC/對偶
        self.X, self.V, self.U, self.Y = v["X"], v["V"], v["U"], v["Y"]
        for j in self.J:
            self.X[j].vtype = GRB.CONTINUOUS
            self.V[j].vtype = GRB.CONTINUOUS
            self.U[j].vtype = GRB.CONTINUOUS
        for h in self.H:
            for j in self.J:
                self.Y[h, j].vtype = GRB.CONTINUOUS

        m.setParam("OutputFlag", 0)
        m.setParam("Method", 1)        # dual simplex：bounds 更新後熱啟動重解最快
        m.setParam("Threads", threads)
        m.setParam("NumericFocus", 1)
        self.model = m
        self.n_solves = 0

    # ------------------------------------------------------------------ #
    def _set_first_stage(self, fs: dict[str, Any]) -> None:
        for j in self.J:
            xv = float(fs["X"][j]); self.X[j].lb = xv; self.X[j].ub = xv
            vv = float(fs["V"][j]); self.V[j].lb = vv; self.V[j].ub = vv
            uv = float(fs["U"][j]); self.U[j].lb = uv; self.U[j].ub = uv
        for h in self.H:
            for j in self.J:
                yv = float(fs["Y"].get((h, j), 0.0))
                self.Y[h, j].lb = yv; self.Y[h, j].ub = yv

    # ------------------------------------------------------------------ #
    def evaluate(self, fs: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """固定一階解 fs 後求解情境 LP。

        Returns
        -------
        Q_s : float
            純二階成本（LP 目標值 − 一階成本 F(fs)）。
        cut : dict
            {"const": Q_s, "at": fs 的複本,
             "gX": {j: g}, "gV": {j: g}, "gU": {j: g}, "gY": {(h,j): g}}
            代表 θ_s ≥ const + Σ g·(var − var̄)。
        """
        self._set_first_stage(fs)
        self.model.optimize()
        self.n_solves += 1
        if self.model.status != GRB.OPTIMAL:
            raise RuntimeError(
                f"Oracle[{self.s}] LP not optimal (status={self.model.status}). "
                "Relatively complete recourse 應保證可行，請檢查一階解是否違反一階資源限制式。"
            )

        total = self.model.ObjVal
        first_stage_cost = sum(
            var.Obj * var.X
            for group in (self.X, self.V, self.U, self.Y)
            for var in group.values()
        )
        q_s = total - first_stage_cost

        def _g(var):
            return var.RC - var.Obj    # ∂Q_s/∂v（見模組 docstring）

        cut = {
            "const": q_s,
            "at": {
                "X": {j: float(fs["X"][j]) for j in self.J},
                "V": {j: float(fs["V"][j]) for j in self.J},
                "U": {j: float(fs["U"][j]) for j in self.J},
                "Y": {(h, j): float(fs["Y"].get((h, j), 0.0))
                      for h in self.H for j in self.J},
            },
            "gX": {j: _g(self.X[j]) for j in self.J},
            "gV": {j: _g(self.V[j]) for j in self.J},
            "gU": {j: _g(self.U[j]) for j in self.J},
            "gY": {(h, j): _g(self.Y[h, j]) for h in self.H for j in self.J},
        }
        return q_s, cut

    # ------------------------------------------------------------------ #
    def cut_value_at(self, cut: dict[str, Any], fs: dict[str, Any]) -> float:
        """計算 cut 右手邊在任意一階解 fs 的取值（除錯 / 驗證用）。"""
        val = cut["const"]
        at = cut["at"]
        val += sum(cut["gX"][j] * (float(fs["X"][j]) - at["X"][j]) for j in self.J)
        val += sum(cut["gV"][j] * (float(fs["V"][j]) - at["V"][j]) for j in self.J)
        val += sum(cut["gU"][j] * (float(fs["U"][j]) - at["U"][j]) for j in self.J)
        val += sum(
            cut["gY"][(h, j)] * (float(fs["Y"].get((h, j), 0.0)) - at["Y"][(h, j)])
            for h in self.H for j in self.J
        )
        return val


# ====================================================================== #
# Phase 0 — Master builder（一階限制式照 extensive_form_core 抄寫）        #
# ====================================================================== #

# ====================================================================== #
# 有效不等式 VI-6 / VI-7 / VI-8（只在 Benders master 出現）               #
#                                                                        #
# 編號與 docs/有效不等式_實作規格.docx 一致；驗證程式 tests/validate_vi.py。#
# VI-1 ~ VI-5 作用於模型本身，實作於 extensive_form_core.py（master 的     #
# 一階限制式與 oracle 都會經過那裡）。                                     #
# ====================================================================== #

def _vi_theta_upper(instance: dict[str, Any], s: str) -> float:
    """VI-7：q̄_s = Q(0; ω^s) = Σ_i Σ_l Σ_t ρ_l ( Σ_{r=1}^{t} ξ_ilrs )。

    第一階段全為 0 時 (11)(12) 逼得 FI = FO = 0，一路推下去只剩 (10) 的第一項，
    故有閉式解，不需求解任何 LP。
    """
    sets = instance["sets"]
    rho = instance["deterministic_parameters"]["disaster_area_remaining_penalty_by_severity"]
    dem = instance["scenario_data"]["demand"][s]
    tot = 0.0
    for i in sets["I"]:
        for l in sets["L"]:
            cum = 0.0
            for t in sets["T"]:
                cum += dem[t][i].get(l, 0.0)
                tot += rho[l] * cum
    return tot


def _vi_theta_lower(instance: dict[str, Any], s: str, time_limit: float) -> float | None:
    """VI-6：q̲_s = Q(x̄; ω^s)，x̄ 為第一階段變數的逐分量上界向量。

    Q(·; ω^s) 對 x 逐分量非增（一階變數在二階限制式中只以非負係數出現在右手邊），
    故 Q(x̄) 是所有第一階段可行解的下界。x̄ 本身違反資源池限制式 (2)(3)(4)，
    計算時把一階限制式的右手邊放寬至 +∞ —— Q 的定義只把 x 當右手邊參數，
    並不要求 x 屬於第一階段可行域。

    求解失敗（超時等）時回傳 None，呼叫端跳過該情境的下界。
    """
    sets = instance["sets"]
    J, H = sets["J"], sets["H"]
    params = instance["deterministic_parameters"]
    sd_full = instance["scenario_data"]
    x_bar = {
        "X": {j: 1 for j in J},
        "V": {j: int(math.floor(params["ccp_staff_upper_bound"][j])) for j in J},
        "U": {j: int(math.floor(params["ccp_ambulance_upper_bound"][j])) for j in J},
        "Y": {(h, j): int(math.floor(min(params["hospital_supply_upper_bound"][h],
                                         params["ccp_supply_upper_bound"][j])))
              for h in H for j in J},
    }
    sub_sd = {k: {s: sd_full[k][s]} for k in
              ("demand", "road_availability_ij", "road_availability_jh",
               "hospital_receiving_capacity")}
    m = None
    try:
        m, _v = model_core.build_gurobi_model(
            sets["I"], J, H, sets["L"], sets["L_transfer"], sets["T"], [s],
            params, sub_sd, {s: 1.0},
            instance["road_capacity"]["cap_ij"], instance["road_capacity"]["cap_jh"],
            instance["transport_cost"]["cost_ij"], instance["transport_cost"]["cost_jh"],
            model_name=f"VI6_lb[{s}]", time_limit=time_limit, mip_gap=0.0,
            fixed_first_stage=x_bar,
        )
        m.setParam("OutputFlag", 0)
        m.update()
        for c in m.getConstrs():
            if c.ConstrName.startswith(("Total_Staff", "Total_CCP_Ambulances",
                                        "Hosp_Supply_", "Logic_V_", "Logic_U_",
                                        "Logic_Y_")):
                c.RHS = GRB.INFINITY
        m.optimize()
        if m.status != GRB.OPTIMAL:
            return None
        first_stage_cost = (
            sum(params["ccp_fixed_opening_cost"][j] * x_bar["X"][j] for j in J)
            + params["staff_unit_assignment_cost"] * sum(x_bar["V"].values())
            + params["ccp_ambulance_unit_assignment_cost"] * sum(x_bar["U"].values())
            + sum(params["supply_allocation_cost_from_hospital_to_ccp"][h][j]
                  * x_bar["Y"][(h, j)] for h in H for j in J)
        )
        return m.ObjVal - first_stage_cost
    except gp.GurobiError:
        return None
    finally:
        if m is not None:
            m.dispose()


def _embed_vi8_in_master(m: gp.Model, mv: dict[str, Any], instance: dict[str, Any],
                         S_selected: list[str], norm_probs: dict[str, float],
                         multi_cut: bool) -> int:
    """VI-8：把第二階段限制式對空間索引 i, j, h 加總後的投影塞進 master。

    每情境只需 (2|L| + 2|L^Amb|)·|T| 個連續變數 —— 文件中寫成
    Σ_{i∈I} Σ_{j∈J} FI_ijlt(s) 的求和式，程式中就是這裡的一個變數。
    式子編號 (8.1)–(8.10) 與規格書 2.8 節一一對應。

    回傳新增的限制式條數。
    """
    sets = instance["sets"]
    I, J, H = sets["I"], sets["J"], sets["H"]
    L, Ltr, T = sets["L"], sets["L_transfer"], sets["T"]
    params = instance["deterministic_parameters"]
    sd = instance["scenario_data"]
    cap_ij = instance["road_capacity"]["cap_ij"]
    cap_jh = instance["road_capacity"]["cap_jh"]
    cost_ij = instance["transport_cost"]["cost_ij"]
    cost_jh = instance["transport_cost"]["cost_jh"]
    X, V, U, Y = mv["X"], mv["V"], mv["U"], mv["Y"]
    theta = mv["theta"]

    tau = {l: int(params["treatment_duration_by_severity"][l]) for l in L}
    alpha = params["staff_treatment_rate_by_severity"]
    beta = params["supply_consumption_by_severity"]
    rho = params["disaster_area_remaining_penalty_by_severity"]
    delta = params["ccp_waiting_penalty_by_severity"]
    kap = params["ccp_ambulance_casualty_capacity"]
    eta = params["hospital_ambulance_casualty_capacity"]
    kcap = {l: params["ccp_physical_capacity_by_severity"][l] for l in L}
    kcap_tr = sum(kcap[l] for l in Ltr)
    nT = len(T)

    sumX = gp.quicksum(X[j] for j in J)
    sumV = gp.quicksum(V[j] for j in J)
    sumU = gp.quicksum(U[j] for j in J)
    sumY = gp.quicksum(Y[h, j] for h in H for j in J)
    min_tij = min(cost_ij[i][j] for i in I for j in J)
    min_tjh = min(cost_jh[j][h] for j in J for h in H)

    def window(l, ti):
        """(18) 的滾動窗 r = max(1, t−τ_l+1) … t，以 0-based 索引表示。"""
        return range(max(0, ti - tau[l] + 1), ti + 1)

    n_added = 0
    link_terms = {}
    for s in S_selected:
        fi = m.addVars(L, range(nT), lb=0.0, name=f"vi8_fi[{s}]")
        rm = m.addVars(L, range(nT), lb=0.0, name=f"vi8_rm[{s}]")
        fo = m.addVars(Ltr, range(nT), lb=0.0, name=f"vi8_fo[{s}]")
        wat = m.addVars(Ltr, range(nT), lb=0.0, name=f"vi8_wat[{s}]")

        # 各期各災區的累積傷患（(8.9) 的係數要用）
        cum = {}
        for i in I:
            run = 0.0
            for ti, t in enumerate(T):
                run += sum(sd["demand"][s][t][i].get(l, 0.0) for l in L)
                cum[(i, ti)] = run

        # (8.1) 災區人數守恆（(15)(16) 對 i 加總）
        for l in L:
            for ti, t in enumerate(T):
                arrive = sum(sd["demand"][s][t][i].get(l, 0.0) for i in I)
                prev = rm[l, ti - 1] if ti > 0 else 0.0
                m.addConstr(rm[l, ti] == prev + arrive - fi[l, ti],
                            f"VI8_1[{s},{l},{ti}]"); n_added += 1

        # (8.2) CCP 等待區人數守恆（(17)(19)(20)(21) 對 j 加總）
        for l in Ltr:
            for ti in range(nT):
                prev = wat[l, ti - 1] if ti > 0 else 0.0
                done = fi[l, ti - tau[l]] if ti - tau[l] >= 0 else 0.0
                m.addConstr(wat[l, ti] == prev + done - fo[l, ti],
                            f"VI8_2[{s},{l},{ti}]"); n_added += 1

        for ti, t in enumerate(T):
            # (8.3)(8.4) 實體容量（(17)(18)(22)(23) 對 j 加總）
            for l in Ltr:
                m.addConstr(gp.quicksum(fi[l, r] for r in window(l, ti)) + wat[l, ti]
                            <= kcap[l] * sumX, f"VI8_3[{s},{l},{ti}]"); n_added += 1
            for l in [x for x in L if x not in Ltr]:
                m.addConstr(gp.quicksum(fi[l, r] for r in window(l, ti))
                            <= kcap[l] * sumX, f"VI8_4[{s},{l},{ti}]"); n_added += 1
            # (8.5) 醫護（(17)(18)(24) 對 j 加總）
            m.addConstr(gp.quicksum((1.0 / alpha[l])
                                    * gp.quicksum(fi[l, r] for r in window(l, ti))
                                    for l in L) <= sumV,
                        f"VI8_5[{s},{ti}]"); n_added += 1
            # (8.6) CCP 救護車（(13) 對 j 加總）
            m.addConstr(gp.quicksum(fi[l, ti] for l in Ltr) <= kap * sumU,
                        f"VI8_6[{s},{ti}]"); n_added += 1
            # (8.8) 醫院收治（VI-3 對 h 加總）
            rhs8 = sum(min(eta * params["hospital_ambulance_fleet"][h],
                           sd["hospital_receiving_capacity"][s][h][t]) for h in H)
            m.addConstr(gp.quicksum(fo[l, ti] for l in Ltr) <= rhs8,
                        f"VI8_8[{s},{ti}]"); n_added += 1
            # (8.9) 入口道路（VI-1 對 i, j 加總）
            coef_in = {j: sum(min(cap_ij[i][j] * sd["road_availability_ij"][s][i][j][t],
                                  cum[(i, ti)]) for i in I) for j in J}
            m.addConstr(gp.quicksum(fi[l, ti] for l in L)
                        <= gp.quicksum(coef_in[j] * X[j] for j in J),
                        f"VI8_9[{s},{ti}]"); n_added += 1
            # (8.10) 出口道路（VI-2 對 j, h 加總）
            coef_out = {j: sum(min(cap_jh[j][h] * sd["road_availability_jh"][s][j][h][t],
                                   kcap_tr) for h in H) for j in J}
            m.addConstr(gp.quicksum(fo[l, ti] for l in Ltr)
                        <= gp.quicksum(coef_out[j] * X[j] for j in J),
                        f"VI8_10[{s},{ti}]"); n_added += 1

        # (8.7) 物資（(17)(25) 對 j 加總；整個規劃期間一條）
        m.addConstr(gp.quicksum(beta[l] * fi[l, ti] for l in L for ti in range(nT))
                    <= sumY, f"VI8_7[{s}]"); n_added += 1

        # 連結式的右手邊：前兩項與 (10) 的前兩項逐項相同，後兩項是運送成本，
        # 彙總後已無法分辨路徑，故以最小單價取下界。
        link_terms[s] = (
            gp.quicksum(rho[l] * rm[l, ti] for l in L for ti in range(nT))
            + gp.quicksum(delta[l] * wat[l, ti] for l in Ltr for ti in range(nT))
            + min_tij * gp.quicksum(fi[l, ti] for l in L for ti in range(nT))
            + min_tjh * gp.quicksum(fo[l, ti] for l in Ltr for ti in range(nT))
        )

    if multi_cut:
        for s in S_selected:
            m.addConstr(theta[s] >= link_terms[s], f"VI8_link[{s}]"); n_added += 1
    else:
        # single-cut：聚合 θ 代表 Σ p_s θ_s，故下界也要用同一組權重加總
        m.addConstr(theta["__agg__"]
                    >= gp.quicksum(norm_probs[s] * link_terms[s] for s in S_selected),
                    "VI8_link_agg"); n_added += 1
    return n_added


def build_master(instance: dict[str, Any], S_selected: list[str],
                 norm_probs: dict[str, float],
                 time_limit: float = 3600.0, mip_gap: float = 0.01,
                 multi_cut: bool = True,
                 risk_cfg: dict[str, Any] | None = None,
                 lbf_enabled: bool = False,
                 vi_cfg: dict[str, Any] | None = None):
    """建 Benders master：一階變數 + 一階限制式 + θ 變數。

    Returns (model, vars_dict)；vars_dict 含 X/V/U/Y 與 theta（{s: var} 或 {"__agg__": var}）。

    risk_cfg（plan/08）：None = 原 SP 期望值目標（行為與舊版完全相同）；
    否則由 risk_core.attach_risk_to_master 加上 φ/ℓ 風險層並改寫目標式，
    cut 仍全部掛在 θ_s 上，一階限制式不變。
    """
    sets   = instance["sets"]
    J      = sets["J"]
    H      = sets["H"]
    params = instance["deterministic_parameters"]

    _vi = model_core.vi_flags(vi_cfg)

    m = gp.Model("Benders_Master")
    m.setParam("OutputFlag", 0)
    m.setParam("TimeLimit", time_limit)
    m.setParam("MIPGap", mip_gap)

    X = m.addVars(J, vtype=GRB.BINARY,        name="X")
    V = m.addVars(J, vtype=GRB.INTEGER, lb=0, name="V")
    U = m.addVars(J, vtype=GRB.INTEGER, lb=0, name="U")
    Y = m.addVars(H, J, vtype=GRB.INTEGER, lb=0, name="Y")

    # θ：二階期望成本的代理變數（Q_s ≥ 0 ⇒ θ ≥ 0 合法）
    if multi_cut:
        theta = {s: m.addVar(lb=0.0, name=f"theta[{s}]") for s in S_selected}
        theta_expr = gp.quicksum(norm_probs[s] * theta[s] for s in S_selected)
    else:
        agg = m.addVar(lb=0.0, name="Theta")
        theta = {"__agg__": agg}
        theta_expr = agg

    first_stage_cost = (
        gp.quicksum(params["ccp_fixed_opening_cost"][j] * X[j] for j in J)
        + params["staff_unit_assignment_cost"] * gp.quicksum(V[j] for j in J)
        + params["ccp_ambulance_unit_assignment_cost"] * gp.quicksum(U[j] for j in J)
        + gp.quicksum(
            params["supply_allocation_cost_from_hospital_to_ccp"][h][j] * Y[h, j]
            for h in H for j in J
        )
    )
    m.setObjective(first_stage_cost + theta_expr, GRB.MINIMIZE)

    # 一階資源限制式（與 extensive_form_core 完全相同）
    m.addConstr(gp.quicksum(V[j] for j in J) <= params["total_available_staff"],
                "Total_Staff")
    m.addConstr(gp.quicksum(U[j] for j in J) <= params["total_available_ccp_ambulances"],
                "Total_CCP_Ambulances")
    for h in H:
        m.addConstr(
            gp.quicksum(Y[h, j] for j in J) <= params["hospital_supply_upper_bound"][h],
            f"Hosp_Supply_{h}",
        )
    for j in J:
        # VI-4：(5) → (5′)。master 是第一階段真正做決策的地方，這兩條要加在這裡。
        _v_ub = (model_core.vi_staff_ub(params, j, sets["L"]) if _vi["VI-4"]
                 else params["ccp_staff_upper_bound"][j])
        m.addConstr(V[j] <= _v_ub * X[j], f"Logic_V_{j}")
        m.addConstr(U[j] <= params["ccp_ambulance_upper_bound"][j] * X[j], f"Logic_U_{j}")
        m.addConstr(
            gp.quicksum(Y[h, j] for h in H) <= params["ccp_supply_upper_bound"][j] * X[j],
            f"Logic_Y_{j}",
        )
        if _vi["VI-5"]:
            # VI-5：開了站就必須配置醫護與物資
            m.addConstr(X[j] <= V[j], f"VI5_staff_{j}")
            m.addConstr(X[j] <= gp.quicksum(Y[h, j] for h in H), f"VI5_supply_{j}")

    mv = {"X": X, "V": V, "U": U, "Y": Y, "theta": theta,
          "first_stage_cost_expr": first_stage_cost}

    # ---- VI-6 / VI-7：θ_s 的下界與上界 ----
    # 本模型具 relatively complete recourse，未加切割時 master 的 LP 鬆弛最佳值
    # 恰為 0；VI-6 給 θ_s 一個立即可用的非零下界，是成本最低的一條。
    vi_theta_lb = {}
    vi_theta_ub = {}
    if _vi["VI-6"] or _vi["VI-7"]:
        # 剛 addVar 出來的變數要先 update 才能讀寫屬性
        m.update()
        lb_tl = float(getattr(config, "VI_THETA_LB_TIME_LIMIT", 120.0))
        for s in S_selected:
            if _vi["VI-7"]:
                vi_theta_ub[s] = _vi_theta_upper(instance, s)
            if _vi["VI-6"]:
                q_lo = _vi_theta_lower(instance, s, lb_tl)
                if q_lo is not None and q_lo > 0.0:
                    vi_theta_lb[s] = q_lo
        if multi_cut:
            for s in S_selected:
                if s in vi_theta_lb:
                    theta[s].lb = max(theta[s].lb, vi_theta_lb[s])
                if s in vi_theta_ub:
                    theta[s].ub = vi_theta_ub[s]
        else:
            agg = theta["__agg__"]
            if len(vi_theta_lb) == len(S_selected):
                agg.lb = max(agg.lb,
                             sum(norm_probs[s] * vi_theta_lb[s] for s in S_selected))
            if len(vi_theta_ub) == len(S_selected):
                agg.ub = sum(norm_probs[s] * vi_theta_ub[s] for s in S_selected)
    mv["vi_theta_lb"] = vi_theta_lb
    mv["vi_theta_ub"] = vi_theta_ub

    if risk_cfg is not None:
        risk_core.attach_risk_to_master(m, mv, S_selected, norm_probs, risk_cfg)
    if lbf_enabled:
        _embed_lbf_in_master(m, mv, instance, S_selected, norm_probs)

    # ---- VI-8：每情境彙總鬆弛 ----
    # 必須排在 risk 層之後 —— 它掛的是 θ_s，而 risk 層只改目標式不動 θ_s，
    # 故兩者互不干擾；排在 LBF 之後則是為了讓 master 的變數編號穩定、好對照。
    vi8_rows = 0
    if _vi["VI-8"]:
        vi8_rows = _embed_vi8_in_master(m, mv, instance, S_selected,
                                        norm_probs, multi_cut)
    mv["vi_flags"] = _vi
    mv["vi8_rows"] = vi8_rows
    return m, mv


def cut_expr(cut: dict[str, Any], mv: dict[str, Any], J: list[str], H: list[str]):
    """把 oracle 回傳的 cut dict 轉成 master 變數的線性表達式（cut 右手邊）。"""
    at = cut["at"]
    expr = gp.LinExpr(cut["const"])
    for j in J:
        expr += cut["gX"][j] * (mv["X"][j] - at["X"][j])
        expr += cut["gV"][j] * (mv["V"][j] - at["V"][j])
        expr += cut["gU"][j] * (mv["U"][j] - at["U"][j])
    for h in H:
        for j in J:
            expr += cut["gY"][(h, j)] * (mv["Y"][h, j] - at["Y"][(h, j)])
    return expr


# ====================================================================== #
# Phase 2 classic loop / Phase 3 B&BC                                      #
# ====================================================================== #

def _normalize_probabilities(instance: dict[str, Any], S_selected: list[str]) -> dict[str, float]:
    sd = instance["scenario_data"]
    raw_probs = {s: float(sd["probability"][s]) for s in S_selected}
    total_prob = sum(raw_probs.values())
    if total_prob <= 0:
        raise ValueError("Selected scenario probabilities must sum to a positive value.")
    return {s: p / total_prob for s, p in raw_probs.items()}


def _extract_first_stage(
    mv: dict[str, Any],
    J: list[str],
    H: list[str],
    round_values: bool = True,
    from_callback: Any | None = None,
) -> dict[str, Any]:
    def _val(var):
        value = from_callback(var) if from_callback is not None else var.X
        return int(round(value)) if round_values else float(value)

    return {
        "X": {j: _val(mv["X"][j]) for j in J},
        "V": {j: _val(mv["V"][j]) for j in J},
        "U": {j: _val(mv["U"][j]) for j in J},
        "Y": {(h, j): _val(mv["Y"][h, j]) for h in H for j in J},
    }


def _theta_values(mv: dict[str, Any], S_selected: list[str], multi_cut: bool) -> dict[str, float]:
    theta = mv["theta"]
    if multi_cut:
        return {s: float(theta[s].X) for s in S_selected}
    agg = float(theta["__agg__"].X)
    return {s: agg for s in S_selected}


def _first_stage_cost(instance: dict[str, Any], fs: dict[str, Any]) -> float:
    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    params = instance["deterministic_parameters"]
    return float(
        sum(params["ccp_fixed_opening_cost"][j] * fs["X"][j] for j in J)
        + params["staff_unit_assignment_cost"] * sum(fs["V"][j] for j in J)
        + params["ccp_ambulance_unit_assignment_cost"] * sum(fs["U"][j] for j in J)
        + sum(
            params["supply_allocation_cost_from_hospital_to_ccp"][h][j]
            * fs["Y"].get((h, j), 0)
            for h in H for j in J
        )
    )


def _selected_scenario_data(instance: dict[str, Any], S_selected: list[str]) -> dict[str, Any]:
    sd = instance["scenario_data"]
    return {
        "demand": {s: sd["demand"][s] for s in S_selected},
        "road_availability_ij": {s: sd["road_availability_ij"][s] for s in S_selected},
        "road_availability_jh": {s: sd["road_availability_jh"][s] for s in S_selected},
        "hospital_receiving_capacity": {
            s: sd["hospital_receiving_capacity"][s] for s in S_selected
        },
    }


def _solve_ev_first_stage(
    instance: dict[str, Any],
    time_limit: float,
    mip_gap: float,
) -> dict[str, Any] | None:
    sets = instance["sets"]
    ev_data = instance["deterministic_data"]["expected_value"]
    ev_sd = model_core.wrap_det_scenario(ev_data, "EV")
    m, v = model_core.build_gurobi_model(
        sets["I"],
        sets["J"],
        sets["H"],
        sets["L"],
        sets["L_transfer"],
        sets["T"],
        ["EV"],
        instance["deterministic_parameters"],
        ev_sd,
        {"EV": 1.0},
        instance["road_capacity"]["cap_ij"],
        instance["road_capacity"]["cap_jh"],
        instance["transport_cost"]["cost_ij"],
        instance["transport_cost"]["cost_jh"],
        model_name="EV_Warm_Start",
        time_limit=time_limit,
        mip_gap=mip_gap,
    )
    m.optimize()
    if m.SolCount == 0:
        return None
    return _extract_first_stage(v, sets["J"], sets["H"], round_values=True)


def _apply_first_stage_start(mv: dict[str, Any], fs: dict[str, Any], J: list[str], H: list[str]) -> None:
    for j in J:
        mv["X"][j].Start = fs["X"][j]
        mv["V"][j].Start = fs["V"][j]
        mv["U"][j].Start = fs["U"][j]
    for h in H:
        for j in J:
            mv["Y"][h, j].Start = fs["Y"].get((h, j), 0)


def _apply_theta_start(
    mv: dict[str, Any],
    S_selected: list[str],
    q_by_s: dict[str, float],
    norm_probs: dict[str, float],
    multi_cut: bool,
) -> None:
    if multi_cut:
        for s in S_selected:
            mv["theta"][s].Start = q_by_s[s]
    else:
        mv["theta"]["__agg__"].Start = sum(norm_probs[s] * q_by_s[s] for s in S_selected)


def _relative_gap(best_ub: float, best_lb: float) -> float:
    if best_ub == float("inf") or best_lb == -float("inf"):
        return float("inf")
    return max(0.0, (best_ub - best_lb) / max(1.0, abs(best_ub)))


def _cut_signature(s: str, cut: dict[str, Any], ndigits: int = 8) -> tuple[Any, ...]:
    at = cut["at"]
    return (
        s,
        tuple(sorted((k, round(v, ndigits)) for k, v in at["X"].items())),
        tuple(sorted((k, round(v, ndigits)) for k, v in at["V"].items())),
        tuple(sorted((k, round(v, ndigits)) for k, v in at["U"].items())),
        tuple(sorted((k, round(v, ndigits)) for k, v in at["Y"].items())),
    )


def _first_stage_cache_key(fs: dict[str, Any], ndigits: int = 8) -> tuple[Any, ...]:
    return (
        tuple(sorted((k, round(float(v), ndigits)) for k, v in fs["X"].items())),
        tuple(sorted((k, round(float(v), ndigits)) for k, v in fs["V"].items())),
        tuple(sorted((k, round(float(v), ndigits)) for k, v in fs["U"].items())),
        tuple(sorted((k, round(float(v), ndigits)) for k, v in fs["Y"].items())),
    )


def _empty_first_stage(J: list[str], H: list[str]) -> dict[str, Any]:
    return {
        "X": {j: 0.0 for j in J},
        "V": {j: 0.0 for j in J},
        "U": {j: 0.0 for j in J},
        "Y": {(h, j): 0.0 for h in H for j in J},
    }


def _clip_first_stage_to_relaxed_domain(
    instance: dict[str, Any],
    fs: dict[str, Any],
) -> dict[str, Any]:
    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    params = instance["deterministic_parameters"]

    clipped = _empty_first_stage(J, H)

    for j in J:
        clipped["X"][j] = min(1.0, max(0.0, float(fs["X"].get(j, 0.0))))

    for j in J:
        x_j = clipped["X"][j]
        clipped["V"][j] = min(
            float(params["ccp_staff_upper_bound"][j]) * x_j,
            max(0.0, float(fs["V"].get(j, 0.0))),
        )
        clipped["U"][j] = min(
            float(params["ccp_ambulance_upper_bound"][j]) * x_j,
            max(0.0, float(fs["U"].get(j, 0.0))),
        )

    total_staff = float(params["total_available_staff"])
    staff_sum = sum(clipped["V"].values())
    if staff_sum > total_staff and staff_sum > 1e-9:
        scale = total_staff / staff_sum
        for j in J:
            clipped["V"][j] *= scale

    total_ambulances = float(params["total_available_ccp_ambulances"])
    ambulance_sum = sum(clipped["U"].values())
    if ambulance_sum > total_ambulances and ambulance_sum > 1e-9:
        scale = total_ambulances / ambulance_sum
        for j in J:
            clipped["U"][j] *= scale

    for h in H:
        for j in J:
            if clipped["X"][j] <= 1e-9:
                clipped["Y"][(h, j)] = 0.0
            else:
                clipped["Y"][(h, j)] = max(0.0, float(fs["Y"].get((h, j), 0.0)))

    # Alternate row/column scaling to keep the core point inside the relaxed
    # first-stage feasible region without solving another projection problem.
    for _ in range(3):
        for h in H:
            row_cap = float(params["hospital_supply_upper_bound"][h])
            row_sum = sum(clipped["Y"][(h, j)] for j in J)
            if row_sum > row_cap and row_sum > 1e-9:
                scale = row_cap / row_sum
                for j in J:
                    clipped["Y"][(h, j)] *= scale

        for j in J:
            col_cap = float(params["ccp_supply_upper_bound"][j]) * clipped["X"][j]
            col_sum = sum(clipped["Y"][(h, j)] for h in H)
            if col_sum > col_cap and col_sum > 1e-9:
                scale = col_cap / col_sum
                for h in H:
                    clipped["Y"][(h, j)] *= scale

    return clipped


def _build_initial_core_point(instance: dict[str, Any]) -> dict[str, Any]:
    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    params = instance["deterministic_parameters"]

    staff_per_j = 0.7 * float(params["total_available_staff"]) / max(1, len(J))
    ambulance_per_j = 0.7 * float(params["total_available_ccp_ambulances"]) / max(1, len(J))
    total_y_cap = min(
        sum(float(params["hospital_supply_upper_bound"][h]) for h in H),
        sum(float(params["ccp_supply_upper_bound"][j]) for j in J),
    )
    y_per_hj = 0.7 * total_y_cap / max(1, len(H) * len(J))

    core_point = {
        "X": {j: 1.0 for j in J},
        "V": {j: staff_per_j for j in J},
        "U": {j: ambulance_per_j for j in J},
        "Y": {(h, j): y_per_hj for h in H for j in J},
    }
    return _clip_first_stage_to_relaxed_domain(instance, core_point)


def _blend_core_point(
    instance: dict[str, Any],
    core_point: dict[str, Any],
    master_fs: dict[str, Any],
    blend: float = 0.5,
) -> dict[str, Any]:
    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    keep = min(1.0, max(0.0, float(blend)))
    take = 1.0 - keep

    blended = {
        "X": {j: keep * float(core_point["X"][j]) + take * float(master_fs["X"][j]) for j in J},
        "V": {j: keep * float(core_point["V"][j]) + take * float(master_fs["V"][j]) for j in J},
        "U": {j: keep * float(core_point["U"][j]) + take * float(master_fs["U"][j]) for j in J},
        "Y": {
            (h, j): keep * float(core_point["Y"][(h, j)]) + take * float(master_fs["Y"][(h, j)])
            for h in H for j in J
        },
    }
    return _clip_first_stage_to_relaxed_domain(instance, blended)


def _rounded_first_stage_heuristic(
    instance: dict[str, Any],
    master_fs: dict[str, Any],
) -> dict[str, Any]:
    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    params = instance["deterministic_parameters"]

    rounded = _empty_first_stage(J, H)
    for j in J:
        rounded["X"][j] = 1.0 if float(master_fs["X"][j]) >= 0.5 else 0.0
        if rounded["X"][j] > 0.5:
            rounded["V"][j] = max(0.0, float(master_fs["V"][j]))
            rounded["U"][j] = max(0.0, float(master_fs["U"][j]))
            for h in H:
                rounded["Y"][(h, j)] = max(0.0, float(master_fs["Y"][(h, j)]))

    rounded = _clip_first_stage_to_relaxed_domain(instance, rounded)

    x_int = {j: int(round(rounded["X"][j])) for j in J}
    v_int = {j: int(math.floor(rounded["V"][j] + 1e-9)) for j in J}
    u_int = {j: int(math.floor(rounded["U"][j] + 1e-9)) for j in J}
    y_int = {(h, j): int(math.floor(rounded["Y"][(h, j)] + 1e-9)) for h in H for j in J}

    def _greedy_fill(values_int: dict[str, int], values_float: dict[str, float], total_cap: float, ub: dict[str, float]) -> None:
        total_cap_int = int(math.floor(total_cap + 1e-9))
        current = sum(values_int.values())
        order = sorted(J, key=lambda j: values_float[j] - values_int[j], reverse=True)
        while current < total_cap_int:
            progressed = False
            for j in order:
                if values_float[j] <= values_int[j] + 1e-9:
                    continue
                if values_int[j] + 1 > int(math.floor(ub[j] + 1e-9)):
                    continue
                values_int[j] += 1
                current += 1
                progressed = True
                if current >= total_cap_int:
                    break
            if not progressed:
                break

    _greedy_fill(
        v_int,
        rounded["V"],
        float(params["total_available_staff"]),
        {j: float(params["ccp_staff_upper_bound"][j]) * x_int[j] for j in J},
    )
    _greedy_fill(
        u_int,
        rounded["U"],
        float(params["total_available_ccp_ambulances"]),
        {j: float(params["ccp_ambulance_upper_bound"][j]) * x_int[j] for j in J},
    )

    row_used = {h: sum(y_int[(h, j)] for j in J) for h in H}
    col_used = {j: sum(y_int[(h, j)] for h in H) for j in J}
    y_order = sorted(
        [(h, j) for h in H for j in J],
        key=lambda idx: rounded["Y"][idx] - y_int[idx],
        reverse=True,
    )
    for h, j in y_order:
        if rounded["Y"][(h, j)] <= y_int[(h, j)] + 1e-9:
            continue
        if row_used[h] + 1 > int(math.floor(float(params["hospital_supply_upper_bound"][h]) + 1e-9)):
            continue
        if col_used[j] + 1 > int(math.floor(float(params["ccp_supply_upper_bound"][j]) * x_int[j] + 1e-9)):
            continue
        y_int[(h, j)] += 1
        row_used[h] += 1
        col_used[j] += 1

    return {
        "X": x_int,
        "V": v_int,
        "U": u_int,
        "Y": y_int,
    }


def solve_classic(
    instance: dict[str, Any],
    S_selected: list[str],
    time_limit: float | None = None,
    mip_gap: float | None = None,
    multi_cut: bool = True,
    max_iterations: int | None = None,
    verbose: bool = True,
    risk_cfg: dict[str, Any] | None = None,
    vi_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Solve the RP with the classic multi-cut L-shaped loop.

    This is the Phase 2 correctness baseline.  The UB is always recomputed by
    evaluating the incumbent first-stage solution with every scenario oracle.

    risk_cfg=None 時行為與舊版完全相同；風險模型（mcvar/dro）強制 multi-cut。
    """
    if not S_selected:
        raise ValueError("S_selected must contain at least one scenario.")
    if risk_cfg is not None and not multi_cut:
        raise ValueError(
            "Risk-averse solve (mcvar/dro) requires multi_cut=True；"
            "single-cut 聚合 θ 無法定義 per-scenario ℓ_s。"
        )

    time_limit = config.SP_TIME_LIMIT if time_limit is None else float(time_limit)
    mip_gap = config.SP_MIP_GAP if mip_gap is None else float(mip_gap)
    max_iterations = 10_000 if max_iterations is None else int(max_iterations)

    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    norm_probs = _normalize_probabilities(instance, S_selected)

    start_time = time.time()
    master, mv = build_master(
        instance,
        S_selected,
        norm_probs,
        time_limit=time_limit,
        mip_gap=mip_gap,
        multi_cut=multi_cut,
        risk_cfg=risk_cfg,
        vi_cfg=vi_cfg,
    )
    master.setParam("NumericFocus", 1)

    oracles = {
        s: ScenarioOracle(instance, s, time_limit=time_limit, threads=1,
                          vi_cfg=vi_cfg)
        for s in S_selected
    }

    best_ub = float("inf")
    best_lb = -float("inf")
    best_fs = None
    best_q = None
    cuts_added = 0
    cut_signatures: set[tuple[Any, ...]] = set()
    history: list[dict[str, Any]] = []
    status = "ITERATION_LIMIT"

    if verbose:
        print("=" * 70)
        print("CLASSIC MULTI-CUT L-SHAPED")
        print("=" * 70)
        print(" iter |           LB |           UB |   gap % | cuts | oracle")

    for iteration in range(1, max_iterations + 1):
        elapsed = time.time() - start_time
        remaining = time_limit - elapsed
        if remaining <= 0:
            status = "TIME_LIMIT"
            break

        master.setParam("TimeLimit", max(1.0, remaining))
        master.optimize()

        if master.SolCount == 0:
            status = f"MASTER_NO_SOLUTION_{master.Status}"
            break
        if master.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL):
            status = f"MASTER_STATUS_{master.Status}"
            break

        raw_lb = float(master.ObjBound)
        best_lb = max(best_lb, raw_lb)
        fs = _extract_first_stage(mv, J, H)
        theta_vals = _theta_values(mv, S_selected, multi_cut)

        q_by_s: dict[str, float] = {}
        cuts_this_iter = 0
        weighted_q = 0.0
        aggregate_cut_expr = gp.LinExpr()
        aggregate_q = 0.0
        aggregate_theta = float(mv["theta"]["__agg__"].X) if not multi_cut else 0.0

        for s in S_selected:
            q_s, cut = oracles[s].evaluate(fs)
            q_by_s[s] = q_s
            weighted_q += norm_probs[s] * q_s
            tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(q_s))

            if multi_cut:
                violated = q_s > theta_vals[s] + tol
                sig = _cut_signature(s, cut)
                if violated and sig not in cut_signatures:
                    master.addConstr(mv["theta"][s] >= cut_expr(cut, mv, J, H),
                                     name=f"benders_{s}_{cuts_added + 1}")
                    cut_signatures.add(sig)
                    cuts_added += 1
                    cuts_this_iter += 1
            else:
                aggregate_q += norm_probs[s] * q_s
                aggregate_cut_expr += norm_probs[s] * cut_expr(cut, mv, J, H)

        if not multi_cut:
            tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(aggregate_q))
            if aggregate_q > aggregate_theta + tol:
                master.addConstr(mv["theta"]["__agg__"] >= aggregate_cut_expr,
                                 name=f"benders_agg_{cuts_added + 1}")
                cuts_added += 1
                cuts_this_iter += 1

        # risk_cfg=None → Σ p_s·Q_s（同舊版）；否則以風險目標評估 true UB
        true_ub = _first_stage_cost(instance, fs) + (
            weighted_q
            if risk_cfg is None
            else risk_core.second_stage_objective_from_Q(q_by_s, norm_probs, risk_cfg)
        )
        if true_ub < best_ub:
            best_ub = true_ub
            best_fs = fs
            best_q = q_by_s

        gap = _relative_gap(best_ub, best_lb)
        oracle_solves = sum(oracle.n_solves for oracle in oracles.values())
        row = {
            "iteration": iteration,
            "lb": best_lb,
            "raw_lb": raw_lb,
            "ub": best_ub,
            "gap": gap,
            "gap_pct": gap * 100.0,
            "cuts_added": cuts_added,
            "cuts_this_iter": cuts_this_iter,
            "oracle_solves": oracle_solves,
            "runtime": time.time() - start_time,
        }
        history.append(row)

        if verbose:
            print(
                f"{iteration:5d} | {best_lb:12.2f} | {best_ub:12.2f} | "
                f"{gap * 100.0:7.3f} | {cuts_this_iter:4d} | {oracle_solves:6d}"
            )

        if gap <= mip_gap:
            status = "OPTIMAL" if cuts_this_iter == 0 else "GAP_REACHED"
            break

        if cuts_this_iter == 0 and master.Status == GRB.OPTIMAL:
            status = "OPTIMAL"
            break

    runtime = time.time() - start_time
    oracle_solves = sum(oracle.n_solves for oracle in oracles.values())
    gap = _relative_gap(best_ub, best_lb)

    return {
        "obj_value": best_ub if best_ub < float("inf") else None,
        "best_ub": best_ub if best_ub < float("inf") else None,
        "best_lb": best_lb if best_lb > -float("inf") else None,
        "gap_pct": None if gap == float("inf") else gap * 100.0,
        "runtime": runtime,
        "iterations": len(history),
        "cuts_added": cuts_added,
        "oracle_solves": oracle_solves,
        "first_stage": best_fs,
        "scenario_q": best_q,
        "status": status,
        "history": history,
        "master": master,
        "vars": mv,
    }


def solve_bbc(
    instance: dict[str, Any],
    S_selected: list[str],
    time_limit: float | None = None,
    mip_gap: float | None = None,
    multi_cut: bool | None = None,
    root_cut_rounds: int | None = None,
    root_seed_iters: int | None = None,
    parallel_oracles: int | None = None,
    use_user_cuts: bool | None = None,
    ev_warm_start: bool | None = None,
    pareto_enabled: bool | None = None,
    lbf_enabled: bool | None = None,
    diagnostic_stop_after_root_seeding: bool = False,
    diagnostic_stop_after_first_incumbent: bool = False,
    verbose: bool = True,
    risk_cfg: dict[str, Any] | None = None,
    vi_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Solve the RP with Branch-and-Benders-Cut lazy constraints.

    LP root seeding adds ordinary Benders cuts before branch-and-cut starts.
    Lazy cuts are generated at integer incumbents. Optional root user cuts are
    generated inside the root-node LP callback and limited by root_cut_rounds.

    risk_cfg（plan/08）：None = 原 SP（行為與舊版完全相同）；"mcvar"/"dro_*"
    時 master 目標式含風險層，所有 UB / incumbent / heuristic 評估一律以
    risk_core.second_stage_objective_from_Q 計算，cut 邏輯與 oracle 不變。

    pareto_enabled 預設讀 config.BENDERS_PARETO_ENABLED（預設 True）；False
    時 root seeding 與 root user cuts 只建立 standard cuts。
    """
    if not S_selected:
        raise ValueError("S_selected must contain at least one scenario.")

    time_limit = config.SP_TIME_LIMIT if time_limit is None else float(time_limit)
    mip_gap = config.SP_MIP_GAP if mip_gap is None else float(mip_gap)
    multi_cut = config.BENDERS_MULTI_CUT if multi_cut is None else bool(multi_cut)
    if risk_cfg is not None and not multi_cut:
        raise ValueError(
            "Risk-averse solve (mcvar/dro) requires multi_cut=True；"
            "single-cut 聚合 θ 無法定義 per-scenario ℓ_s。"
        )
    if root_seed_iters is None:
        root_seed_iters = getattr(config, "BENDERS_ROOT_SEED_ITERS", 0)
    if root_cut_rounds is None:
        root_cut_rounds = getattr(config, "BENDERS_ROOT_CUT_ROUNDS", 0)
    root_seed_iters = int(root_seed_iters)
    root_cut_rounds = int(root_cut_rounds)
    parallel_oracles = (
        getattr(config, "BENDERS_PARALLEL_ORACLES", 1)
        if parallel_oracles is None
        else parallel_oracles
    )
    parallel_oracles = max(1, min(int(parallel_oracles), len(S_selected)))
    use_user_cuts = (
        getattr(config, "BENDERS_USE_USER_CUTS", False)
        if use_user_cuts is None
        else bool(use_user_cuts)
    )
    ev_warm_start = (
        config.BENDERS_EV_WARM_START
        if ev_warm_start is None
        else bool(ev_warm_start)
    )
    pareto_enabled = (
        getattr(config, "BENDERS_PARETO_ENABLED", True)
        if pareto_enabled is None
        else bool(pareto_enabled)
    )
    lbf_enabled = (
        getattr(config, "BENDERS_LBF_ENABLED", False)
        if lbf_enabled is None
        else bool(lbf_enabled)
    )
    incumbent_early_term = bool(
        getattr(config, "BENDERS_INCUMBENT_EARLY_TERMINATION", True)
    )
    papadakos_blend = float(getattr(config, "BENDERS_PAPADAKOS_BLEND", 0.5))
    rounding_heur_freq = max(1, int(getattr(config, "BENDERS_ROOT_SEED_ROUND_HEUR_FREQ", 10)))
    progress_bound_floor = float(getattr(config, "BENDERS_PROGRESS_BOUND_FLOOR", -1e50))

    sets = instance["sets"]
    J = sets["J"]
    H = sets["H"]
    norm_probs = _normalize_probabilities(instance, S_selected)
    start_time = time.time()

    master, mv = build_master(
        instance,
        S_selected,
        norm_probs,
        time_limit=time_limit,
        mip_gap=mip_gap,
        multi_cut=multi_cut,
        risk_cfg=risk_cfg,
        lbf_enabled=lbf_enabled,
        vi_cfg=vi_cfg,
    )
    master.setParam("LazyConstraints", 1)
    master.setParam("PreCrush", 1)
    # ── 確保 master MIP log 印到終端機（含 LB/UB/Gap/Time） ──
    master.setParam("OutputFlag", 1)
    master.setParam("LogToConsole", 1)
    display_interval = int(getattr(config, "BENDERS_DISPLAY_INTERVAL", 30))
    master.setParam("DisplayInterval", display_interval)
    mip_focus = getattr(config, "BENDERS_MIPFOCUS", None)
    if mip_focus is not None:
        master.setParam("MIPFocus", int(mip_focus))
    heuristics = getattr(config, "BENDERS_HEURISTICS", None)
    if heuristics is not None:
        master.setParam("Heuristics", float(heuristics))
    numeric_focus = getattr(config, "BENDERS_NUMERIC_FOCUS", None)
    if numeric_focus is not None:
        master.setParam("NumericFocus", int(numeric_focus))

    x_branch_priority = int(getattr(config, "BENDERS_X_BRANCH_PRIORITY", 0))
    if getattr(config, "BENDERS_X_BRANCH_PRIORITY_ENABLED", False) and x_branch_priority > 0:
        for var in mv["X"].values():
            var.BranchPriority = x_branch_priority

    oracle_envs: dict[str, gp.Env] = {}
    if parallel_oracles > 1:
        for s in S_selected:
            env = gp.Env(empty=True)
            env.setParam("OutputFlag", 0)
            env.start()
            oracle_envs[s] = env
    oracles = {
        s: ScenarioOracle(
            instance,
            s,
            time_limit=time_limit,
            threads=1,
            env=oracle_envs.get(s),
            vi_cfg=vi_cfg,
        )
        for s in S_selected
    }
    oracle_executor = (
        ThreadPoolExecutor(max_workers=parallel_oracles)
        if parallel_oracles > 1
        else None
    )

    best_ub = float("inf")
    best_fs = None
    best_q = None
    cuts_added = 0
    seed_cuts_added = 0
    lazy_cuts_added = 0
    user_cuts_added = 0
    incumbent_evals = 0
    root_seed_iters_done = 0
    root_cut_rounds_done = 0
    callback_time = 0.0
    root_seed_time = 0.0
    root_seed_lb = None
    root_seed_stop_reason = "not_run"
    cache_hits = 0
    cache_misses = 0
    last_progress_print = start_time
    # Pareto 關閉時不要建 core point，也不要做額外的 Pareto oracle 求解。
    core_point = _build_initial_core_point(instance) if pareto_enabled else None
    evaluation_cache: dict[
        tuple[Any, ...],
        tuple[float | None, dict[str, float], dict[str, Any]],
    ] = {}
    seed_cut_signatures: set[tuple[Any, ...]] = set()
    user_cut_signatures: set[tuple[Any, ...]] = set()
    event_log: list[dict[str, Any]] = []
    cleanup_done = False
    diagnostic_first_incumbent_reached = False

    def cleanup_oracle_resources() -> None:
        nonlocal cleanup_done
        if cleanup_done:
            return
        if oracle_executor is not None:
            oracle_executor.shutdown(wait=True)
        for oracle in oracles.values():
            oracle.model.dispose()
        for env in oracle_envs.values():
            env.dispose()
        cleanup_done = True

    def evaluate_first_stage(
        fs: dict[str, Any],
        compute_objective: bool = True,
    ) -> tuple[float | None, dict[str, float], dict[str, Any], bool]:
        """Evaluate recourse oracles and optionally aggregate the risk objective.

        Fractional root/core-point evaluations only need Q_s and dual cuts.  They
        are not feasible incumbents of the integer problem, so computing a true
        UB is both unnecessary and, for extreme ellipsoidal Q vectors, can make
        the auxiliary WMCVaR SOCP numerically fail.  Integer EV/heuristic/MIPSOL
        calls keep the default compute_objective=True behavior.
        """
        nonlocal cache_hits, cache_misses

        def objective_from_q(q_by_s: dict[str, float]) -> float:
            weighted_q = sum(norm_probs[s] * q_by_s[s] for s in S_selected)
            return _first_stage_cost(instance, fs) + (
                weighted_q
                if risk_cfg is None
                else risk_core.second_stage_objective_from_Q(q_by_s, norm_probs, risk_cfg)
            )

        key = _first_stage_cache_key(fs)
        cached = evaluation_cache.get(key)
        if cached is not None:
            cache_hits += 1
            true_ub, q_by_s, cut_by_s = cached
            # A fractional call may have cached only Q/cuts.  If the same point
            # later becomes an integer incumbent, complete (and cache) its UB.
            if compute_objective and true_ub is None:
                true_ub = objective_from_q(q_by_s)
                evaluation_cache[key] = (true_ub, q_by_s, cut_by_s)
            return true_ub, q_by_s, cut_by_s, True

        q_by_s: dict[str, float] = {}
        cut_by_s: dict[str, Any] = {}

        # --- Incumbent early termination ---
        # When evaluating an integer incumbent (compute_objective=True) and
        # early termination is enabled, evaluate scenarios one-by-one (or in
        # small batches with parallel executor).  If partial weighted Q +
        # first_stage_cost already exceeds best_ub, skip remaining scenarios.
        # This is safe because Q_s ≥ 0 for all s.
        early_terminated = False
        if incumbent_early_term and compute_objective and risk_cfg is None:
            fs_cost = _first_stage_cost(instance, fs)
            # Sort scenarios by descending probability to detect fathoming faster
            sorted_s = sorted(S_selected, key=lambda s: -norm_probs[s])
            partial_wq = 0.0

            if oracle_executor is None:
                # Sequential evaluation with early exit
                for s in sorted_s:
                    q_s, cut = oracles[s].evaluate(fs)
                    q_by_s[s] = q_s
                    cut_by_s[s] = cut
                    partial_wq += norm_probs[s] * q_s
                    if fs_cost + partial_wq > best_ub:
                        early_terminated = True
                        break
            else:
                # With parallel oracles: submit in batches of parallel_oracles
                for batch_start in range(0, len(sorted_s), parallel_oracles):
                    batch = sorted_s[batch_start:batch_start + parallel_oracles]
                    futures = {
                        s: oracle_executor.submit(oracles[s].evaluate, fs)
                        for s in batch
                    }
                    for s in batch:
                        q_s, cut = futures[s].result()
                        q_by_s[s] = q_s
                        cut_by_s[s] = cut
                        partial_wq += norm_probs[s] * q_s
                    if fs_cost + partial_wq > best_ub:
                        early_terminated = True
                        break

            if early_terminated:
                # Don't cache partial evaluations; return inf UB
                # but still return the cuts we obtained for lazy cut generation
                cache_misses += 1
                return float("inf"), q_by_s, cut_by_s, False
            else:
                true_ub = fs_cost + partial_wq
                evaluation_cache[key] = (true_ub, q_by_s, cut_by_s)
                cache_misses += 1
                return true_ub, q_by_s, cut_by_s, False
        else:
            # Original path: evaluate all scenarios (fractional / risk-averse)
            if oracle_executor is None:
                results = [(s, *oracles[s].evaluate(fs)) for s in S_selected]
            else:
                futures = {
                    s: oracle_executor.submit(oracles[s].evaluate, fs)
                    for s in S_selected
                }
                results = [(s, *future.result()) for s, future in futures.items()]

            for s, q_s, cut in results:
                q_by_s[s] = q_s
                cut_by_s[s] = cut
            true_ub = objective_from_q(q_by_s) if compute_objective else None
            evaluation_cache[key] = (true_ub, q_by_s, cut_by_s)
            cache_misses += 1
            return true_ub, q_by_s, cut_by_s, False

    def maybe_print_progress(model: gp.Model, where: int) -> None:
        nonlocal last_progress_print
        if not verbose or time.time() - last_progress_print < 10.0:
            return
        lb = None
        try:
            if where == GRB.Callback.MIP:
                lb = float(model.cbGet(GRB.Callback.MIP_OBJBND))
            elif where == GRB.Callback.MIPSOL:
                lb = float(model.cbGet(GRB.Callback.MIPSOL_OBJBND))
            elif where == GRB.Callback.MIPNODE:
                lb = float(model.cbGet(GRB.Callback.MIPNODE_OBJBND))
        except Exception:
            lb = None
        if lb is not None and (not math.isfinite(lb) or lb < progress_bound_floor):
            return
        gap_txt = "NA"
        if lb is not None and best_ub < float("inf"):
            gap_txt = f"{_relative_gap(best_ub, lb) * 100.0:.2f}%"
        lb_txt = f"{lb:.2f}" if lb is not None else "NA"
        ub_txt = f"{best_ub:.2f}" if best_ub < float("inf") else "NA"
        print(
            f"[BBC t={time.time() - start_time:.1f}s] "
            f"UB={ub_txt} LB={lb_txt} gap={gap_txt}"
        )
        last_progress_print = time.time()

    def add_dual_track_cuts(
        theta_values: dict[str, float],
        eval_fs: dict[str, Any],
        standard_q_by_s: dict[str, float],
        standard_cut_by_s: dict[str, Any],
        pareto_cut_by_s: dict[str, Any] | None,
        signature_store: set[tuple[Any, ...]],
        add_cut: Any,
        name_prefix: str,
        iteration_label: Any,
    ) -> int:
        cuts_this_round = 0
        for s in S_selected:
            standard_cut = standard_cut_by_s[s]
            standard_rhs = standard_q_by_s[s]
            standard_tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(standard_rhs))
            standard_sig = _cut_signature(s, standard_cut)
            if standard_rhs > theta_values[s] + standard_tol and standard_sig not in signature_store:
                add_cut(
                    s,
                    standard_cut,
                    f"{name_prefix}_{iteration_label}_{s}_std",
                )
                signature_store.add(standard_sig)
                cuts_this_round += 1

            if pareto_cut_by_s is not None:
                pareto_cut = pareto_cut_by_s[s]
                pareto_rhs = oracles[s].cut_value_at(pareto_cut, eval_fs)
                pareto_tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(pareto_rhs))
                pareto_sig = _cut_signature(s, pareto_cut)
                if pareto_rhs > theta_values[s] + pareto_tol and pareto_sig not in signature_store:
                    add_cut(
                        s,
                        pareto_cut,
                        f"{name_prefix}_{iteration_label}_{s}_pareto",
                    )
                    signature_store.add(pareto_sig)
                    cuts_this_round += 1
        return cuts_this_round

    if ev_warm_start:
        try:
            ev_limit = min(time_limit, getattr(config, "VSS_EVPI_EV_TIME_LIMIT", time_limit))
            ev_fs = _solve_ev_first_stage(instance, ev_limit, mip_gap)
            if ev_fs is not None:
                ev_ub, ev_q, _, _ = evaluate_first_stage(ev_fs)
                _apply_first_stage_start(mv, ev_fs, J, H)
                _apply_theta_start(mv, S_selected, ev_q, norm_probs, multi_cut)
                risk_core.apply_risk_start(mv, S_selected, ev_q, norm_probs, risk_cfg)
                best_ub = ev_ub
                best_fs = ev_fs
                best_q = ev_q
                event_log.append({
                    "event": "ev_warm_start",
                    "ub": ev_ub,
                    "runtime": time.time() - start_time,
                })
                if verbose:
                    print(f"[B&BC] EV warm start UB: {ev_ub:.2f}")
        except Exception:
            cleanup_oracle_resources()
            raise

    def run_root_seeding() -> None:
        nonlocal best_ub, best_fs, best_q, core_point
        nonlocal cuts_added, seed_cuts_added, root_seed_iters_done, root_seed_time
        nonlocal root_seed_lb, root_seed_stop_reason
        if root_seed_iters <= 0:
            root_seed_stop_reason = "disabled"
            return

        seed_start = time.time()
        stall_limit = max(1, int(getattr(config, "BENDERS_ROOT_SEED_STALL_ROUNDS", 5)))
        lb_rel_tol = float(getattr(config, "BENDERS_ROOT_SEED_LB_REL_TOL", 5e-4))
        best_seed_lb = -float("inf")
        prev_seed_lb = None
        stall_rounds = 0
        cuts_added_after_last_lp = False
        original_vtypes: list[tuple[gp.Var, str]] = []
        for j in J:
            original_vtypes.append((mv["X"][j], GRB.BINARY))
            original_vtypes.append((mv["V"][j], GRB.INTEGER))
            original_vtypes.append((mv["U"][j], GRB.INTEGER))
        for h in H:
            for j in J:
                original_vtypes.append((mv["Y"][h, j], GRB.INTEGER))

        try:
            for var, _ in original_vtypes:
                var.vtype = GRB.CONTINUOUS
            master.update()

            if verbose:
                print("=" * 70)
                print(
                    "B&BC ROOT SEEDING "
                    f"({'Papadakos dual-track' if pareto_enabled else 'standard cuts'}, "
                    f"max {root_seed_iters} LP iterations, "
                    f"stop after {stall_limit} rounds with LB improvement < {lb_rel_tol * 100:.4f}%)"
                )
                print("=" * 70)

            for iter_no in range(1, root_seed_iters + 1):
                remaining = time_limit - (time.time() - start_time)
                if remaining <= 1.0:
                    root_seed_stop_reason = "time_limit"
                    break
                master.setParam("TimeLimit", max(1.0, remaining))
                master.optimize()
                if master.SolCount == 0:
                    root_seed_stop_reason = "no_lp_solution"
                    break
                if master.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL):
                    root_seed_stop_reason = f"lp_status_{master.Status}"
                    break

                root_seed_lb = float(master.ObjVal)
                if prev_seed_lb is not None:
                    rel_improvement = (root_seed_lb - prev_seed_lb) / max(1.0, abs(prev_seed_lb))
                    if rel_improvement < lb_rel_tol:
                        stall_rounds += 1
                    else:
                        stall_rounds = 0
                    if stall_rounds >= stall_limit:
                        root_seed_stop_reason = (
                            f"lb_rel_improve_below_{lb_rel_tol:.6f}_for_{stall_rounds}_rounds"
                        )
                        event_log.append({
                            "event": "root_seed_stop",
                            "iteration": iter_no,
                            "seeded_lb": root_seed_lb,
                            "prev_seeded_lb": prev_seed_lb,
                            "stall_rounds": stall_rounds,
                            "rel_improvement_pct": rel_improvement * 100.0,
                            "runtime": time.time() - start_time,
                        })
                        if verbose:
                            print(
                                f"[root seed stop] seeded_LB={root_seed_lb:.2f} "
                                f"prev_LB={prev_seed_lb:.2f} "
                                f"rel_improve={rel_improvement * 100.0:.4f}% "
                                f"stall_rounds={stall_rounds}/{stall_limit}"
                            )
                        break
                prev_seed_lb = root_seed_lb
                if root_seed_lb > best_seed_lb:
                    best_seed_lb = root_seed_lb

                fs = _extract_first_stage(mv, J, H, round_values=False)
                _, q_by_s, cut_by_s, cache_hit = evaluate_first_stage(
                    fs, compute_objective=False,
                )
                pareto_cut_by_s = None
                pareto_cache_hit = False
                if pareto_enabled:
                    core_point = _blend_core_point(instance, core_point, fs, blend=papadakos_blend)
                    _, _, pareto_cut_by_s, pareto_cache_hit = evaluate_first_stage(
                        core_point, compute_objective=False,
                    )
                root_seed_iters_done += 1
                cuts_this_iter = 0

                if multi_cut:
                    theta_vals = _theta_values(mv, S_selected, multi_cut=True)
                    cuts_this_iter = add_dual_track_cuts(
                        theta_vals,
                        fs,
                        q_by_s,
                        cut_by_s,
                        pareto_cut_by_s,
                        seed_cut_signatures,
                        lambda s, cut, name: master.addConstr(
                            mv["theta"][s] >= cut_expr(cut, mv, J, H),
                            name=name,
                        ),
                        "RootSeedCut",
                        iter_no,
                    )
                    if cuts_this_iter > 0:
                        seed_cuts_added += cuts_this_iter
                        cuts_added += cuts_this_iter
                        cuts_added_after_last_lp = True
                else:
                    theta_val = float(mv["theta"]["__agg__"].X)
                    aggregate_q = sum(norm_probs[s] * q_by_s[s] for s in S_selected)
                    tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(aggregate_q))
                    if aggregate_q > theta_val + tol:
                        expr = gp.LinExpr()
                        for s in S_selected:
                            expr += norm_probs[s] * cut_expr(cut_by_s[s], mv, J, H)
                        master.addConstr(
                            mv["theta"]["__agg__"] >= expr,
                            name=f"RootSeedCut_{iter_no}",
                        )
                        seed_cuts_added += 1
                        cuts_added += 1
                        cuts_this_iter += 1
                        cuts_added_after_last_lp = True

                master.update()
                if iter_no % rounding_heur_freq == 0:
                    rounded_fs = _rounded_first_stage_heuristic(instance, fs)
                    rounded_ub, rounded_q, _, rounded_cache_hit = evaluate_first_stage(rounded_fs)
                    event_log.append({
                        "event": "root_seed_rounding_heuristic",
                        "iteration": iter_no,
                        "ub": rounded_ub,
                        "improved_best_ub": rounded_ub < best_ub,
                        "cache_hit": rounded_cache_hit,
                        "runtime": time.time() - start_time,
                    })
                    if rounded_ub < best_ub:
                        best_ub = rounded_ub
                        best_fs = rounded_fs
                        best_q = rounded_q
                        _apply_first_stage_start(mv, rounded_fs, J, H)
                        _apply_theta_start(mv, S_selected, rounded_q, norm_probs, multi_cut)
                        risk_core.apply_risk_start(mv, S_selected, rounded_q, norm_probs, risk_cfg)
                        if verbose:
                            print(f"[root heuristic {iter_no}] improved UB={rounded_ub:.2f}")
                event_log.append({
                    "event": "root_seed",
                    "iteration": iter_no,
                    "seeded_lb": root_seed_lb,
                    "cuts_this_iter": cuts_this_iter,
                    "seed_cuts_added": seed_cuts_added,
                    "stall_rounds": stall_rounds,
                    "cache_hit": cache_hit,
                    "pareto_cache_hit": pareto_cache_hit,
                    "runtime": time.time() - start_time,
                })
                if verbose:
                    print(
                        f"[root seed {iter_no}] LB={root_seed_lb:.2f} cuts={cuts_this_iter} "
                        f"total_seed_cuts={seed_cuts_added}"
                    )
                if cuts_this_iter == 0:
                    root_seed_stop_reason = "lp_converged"
                    break
            else:
                root_seed_stop_reason = "max_iters"

            if cuts_added_after_last_lp and time_limit - (time.time() - start_time) > 1.0:
                master.setParam("TimeLimit", max(1.0, time_limit - (time.time() - start_time)))
                master.optimize()
                if master.SolCount > 0:
                    root_seed_lb = float(master.ObjVal)
                    event_log.append({
                        "event": "root_seed_final_lp",
                        "seeded_lb": root_seed_lb,
                        "runtime": time.time() - start_time,
                    })
        finally:
            for var, vtype in original_vtypes:
                var.vtype = vtype
            master.update()
            root_seed_time += time.time() - seed_start
            if verbose:
                lb_text = f"{root_seed_lb:.2f}" if root_seed_lb is not None else "NA"
                print(
                    f"[root seed done] seeded_LB={lb_text} "
                    f"reason={root_seed_stop_reason} "
                    f"iters={root_seed_iters_done}/{root_seed_iters} "
                    f"seed_cuts={seed_cuts_added} time={root_seed_time:.2f}s"
                )

    try:
        run_root_seeding()
    except Exception:
        cleanup_oracle_resources()
        raise

    if diagnostic_stop_after_root_seeding:
        oracle_solves = sum(oracle.n_solves for oracle in oracles.values())
        cleanup_oracle_resources()
        if verbose:
            print(
                "[DIAGNOSTIC STOP] root seeding completed without exception | "
                f"iters={root_seed_iters_done}/{root_seed_iters} "
                f"seeded_LB={root_seed_lb} oracle_solves={oracle_solves}"
            )
        return {
            "obj_value": best_ub if best_ub < float("inf") else None,
            "best_ub": best_ub if best_ub < float("inf") else None,
            "best_lb": root_seed_lb,
            "gap_pct": None,
            "runtime": time.time() - start_time,
            "cuts_added": cuts_added,
            "seed_cuts_added": seed_cuts_added,
            "user_cuts_added": 0,
            "lazy_cuts_added": 0,
            "root_seed_iters": root_seed_iters,
            "root_seed_iters_done": root_seed_iters_done,
            "root_seed_lb": root_seed_lb,
            "root_seed_stop_reason": root_seed_stop_reason,
            "root_seed_time": root_seed_time,
            "root_cut_rounds": root_cut_rounds,
            "root_cut_rounds_done": 0,
            "use_user_cuts": use_user_cuts,
            "pareto_enabled": pareto_enabled,
            "parallel_oracles": parallel_oracles,
            "oracle_solves": oracle_solves,
            "incumbent_evals": 0,
            "callback_time": 0.0,
            "first_stage": best_fs,
            "scenario_q": best_q,
            "status": "DIAGNOSTIC_ROOT_SEED_OK",
            "diagnostic_stop": "after_root_seeding",
            "diagnostic_first_incumbent_reached": False,
            "history": event_log,
            "master": master,
            "vars": mv,
        }

    if verbose:
        print("=" * 70)
        print("BRANCH-AND-BENDERS-CUT")
        if root_seed_iters > 0:
            print(f"LP root seeding: {root_seed_iters_done}/{root_seed_iters} rounds")
        if use_user_cuts and root_cut_rounds > 0:
            print(f"Root user cuts enabled: rootCutRounds={root_cut_rounds}")
        if parallel_oracles > 1:
            print(f"Parallel oracle workers: {parallel_oracles}")
        print("=" * 70)

    def bbc_callback(model, where):
        nonlocal best_ub, best_fs, best_q, core_point
        nonlocal cuts_added, lazy_cuts_added, user_cuts_added
        nonlocal incumbent_evals, root_cut_rounds_done, callback_time
        nonlocal diagnostic_first_incumbent_reached

        if where == GRB.Callback.MIP:
            maybe_print_progress(model, where)
            return

        if where == GRB.Callback.MIPNODE:
            maybe_print_progress(model, where)
            if not use_user_cuts or root_cut_rounds <= 0:
                return
            if root_cut_rounds_done >= root_cut_rounds:
                return
            if int(model.cbGet(GRB.Callback.MIPNODE_NODCNT)) != 0:
                return
            if model.cbGet(GRB.Callback.MIPNODE_STATUS) != GRB.OPTIMAL:
                return

            cb_start = time.time()
            fs = _extract_first_stage(
                mv,
                J,
                H,
                round_values=False,
                from_callback=model.cbGetNodeRel,
            )
            _, q_by_s, cut_by_s, cache_hit = evaluate_first_stage(
                fs, compute_objective=False,
            )
            pareto_cut_by_s = None
            pareto_cache_hit = False
            if pareto_enabled:
                core_point = _blend_core_point(instance, core_point, fs, blend=papadakos_blend)
                _, _, pareto_cut_by_s, pareto_cache_hit = evaluate_first_stage(
                    core_point, compute_objective=False,
                )
            root_cut_rounds_done += 1
            cuts_this_node = 0

            if multi_cut:
                theta_vals = {
                    s: model.cbGetNodeRel(mv["theta"][s])
                    for s in S_selected
                }
                cuts_this_node = add_dual_track_cuts(
                    theta_vals,
                    fs,
                    q_by_s,
                    cut_by_s,
                    pareto_cut_by_s,
                    user_cut_signatures,
                    lambda s, cut, _name: model.cbCut(mv["theta"][s] >= cut_expr(cut, mv, J, H)),
                    "RootUserCut",
                    root_cut_rounds_done,
                )
                user_cuts_added += cuts_this_node
                cuts_added += cuts_this_node
            else:
                theta_val = model.cbGetNodeRel(mv["theta"]["__agg__"])
                aggregate_q = sum(norm_probs[s] * q_by_s[s] for s in S_selected)
                tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(aggregate_q))
                if aggregate_q > theta_val + tol:
                    expr = gp.LinExpr()
                    for s in S_selected:
                        expr += norm_probs[s] * cut_expr(cut_by_s[s], mv, J, H)
                    model.cbCut(mv["theta"]["__agg__"] >= expr)
                    user_cuts_added += 1
                    cuts_added += 1
                    cuts_this_node += 1

            callback_time += time.time() - cb_start
            event_log.append({
                "event": "root_user_cut",
                "round": root_cut_rounds_done,
                "cuts_this_node": cuts_this_node,
                "user_cuts_added": user_cuts_added,
                "cache_hit": cache_hit,
                "pareto_cache_hit": pareto_cache_hit,
                "runtime": time.time() - start_time,
            })
            return

        if where == GRB.Callback.MIPSOL:
            maybe_print_progress(model, where)
            cb_start = time.time()
            incumbent_evals += 1
            fs = _extract_first_stage(
                mv,
                J,
                H,
                round_values=True,
                from_callback=model.cbGetSolution,
            )

            true_ub, q_by_s, cut_by_s, cache_hit = evaluate_first_stage(fs)
            if true_ub < best_ub:
                best_ub = true_ub
                best_fs = fs
                best_q = q_by_s

            # q_by_s may be partial when incumbent early termination fired;
            # only add lazy cuts for scenarios actually evaluated.
            evaluated_scenarios = list(q_by_s.keys())

            cuts_this_sol = 0
            if multi_cut:
                for s in evaluated_scenarios:
                    theta_val = model.cbGetSolution(mv["theta"][s])
                    q_s = q_by_s[s]
                    tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(q_s))
                    if q_s > theta_val + tol:
                        model.cbLazy(mv["theta"][s] >= cut_expr(cut_by_s[s], mv, J, H))
                        lazy_cuts_added += 1
                        cuts_added += 1
                        cuts_this_sol += 1
            else:
                theta_val = model.cbGetSolution(mv["theta"]["__agg__"])
                aggregate_q = sum(norm_probs[s] * q_by_s.get(s, 0) for s in S_selected)
                tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(aggregate_q))
                if aggregate_q > theta_val + tol:
                    expr = gp.LinExpr()
                    for s in evaluated_scenarios:
                        expr += norm_probs[s] * cut_expr(cut_by_s[s], mv, J, H)
                    model.cbLazy(mv["theta"]["__agg__"] >= expr)
                    lazy_cuts_added += 1
                    cuts_added += 1
                    cuts_this_sol += 1

            callback_time += time.time() - cb_start
            event_log.append({
                "event": "mipsol",
                "incumbent_eval": incumbent_evals,
                "ub": true_ub,
                "cuts_this_sol": cuts_this_sol,
                "lazy_cuts_added": lazy_cuts_added,
                "cache_hit": cache_hit,
                "runtime": time.time() - start_time,
            })
            if diagnostic_stop_after_first_incumbent:
                diagnostic_first_incumbent_reached = True
                if verbose:
                    print(
                        "[DIAGNOSTIC STOP] first MIPSOL oracle evaluation completed | "
                        f"UB={true_ub:.2f} lazy_cuts={cuts_this_sol}"
                    )
                model.terminate()

    remaining = time_limit - (time.time() - start_time)
    master.setParam("TimeLimit", max(1.0, remaining))
    try:
        master.optimize(bbc_callback)

        runtime = time.time() - start_time
        best_lb = float(master.ObjBound) if master.SolCount > 0 or master.Status in (
            GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL
        ) else None
        if best_ub == float("inf") and master.SolCount > 0:
            fs = _extract_first_stage(mv, J, H, round_values=True)
            best_ub, best_q, _, _ = evaluate_first_stage(fs)
            best_fs = fs

        gap = None
        if best_lb is not None and best_ub < float("inf"):
            gap = _relative_gap(best_ub, best_lb) * 100.0

        oracle_solves = sum(oracle.n_solves for oracle in oracles.values())
        status_map = {
            GRB.OPTIMAL: "OPTIMAL",
            GRB.TIME_LIMIT: "TIME_LIMIT",
            GRB.INTERRUPTED: "INTERRUPTED",
            GRB.SUBOPTIMAL: "SUBOPTIMAL",
        }
        status = status_map.get(master.Status, f"STATUS_{master.Status}")
    finally:
        cleanup_oracle_resources()

    if verbose:
        print("-" * 70)
        print(
            f"B&BC done | status={status} | LB={best_lb if best_lb is not None else 'NA'} | "
            f"UB={best_ub if best_ub < float('inf') else 'NA'} | "
            f"gap={gap if gap is not None else 'NA'}%"
        )
        print(
            f"cuts_added={cuts_added} user_cuts={user_cuts_added} "
            f"lazy_cuts={lazy_cuts_added} seed_cuts={seed_cuts_added} "
            f"pareto_enabled={pareto_enabled} "
            f"rootSeedIters={root_seed_iters_done}/{root_seed_iters} "
            f"seeded_LB={root_seed_lb if root_seed_lb is not None else 'NA'} "
            f"rootSeedStop={root_seed_stop_reason} "
            f"rootCutRounds={root_cut_rounds_done}/{root_cut_rounds} "
            f"parallel_oracles={parallel_oracles} oracle_solves={oracle_solves} "
            f"cache_hits={cache_hits} cache_misses={cache_misses} "
            f"root_seed_time={root_seed_time:.2f}s callback_time={callback_time:.2f}s"
        )

    return {
        "obj_value": best_ub if best_ub < float("inf") else None,
        "best_ub": best_ub if best_ub < float("inf") else None,
        "best_lb": best_lb,
        "gap_pct": gap,
        "runtime": runtime,
        "iterations": int(master.IterCount) if master.SolCount > 0 else 0,
        "nodes": float(master.NodeCount) if master.SolCount > 0 else 0.0,
        "cuts_added": cuts_added,
        "seed_cuts_added": seed_cuts_added,
        "user_cuts_added": user_cuts_added,
        "lazy_cuts_added": lazy_cuts_added,
        "root_seed_iters": root_seed_iters,
        "root_seed_iters_done": root_seed_iters_done,
        "root_seed_lb": root_seed_lb,
        "root_seed_stop_reason": root_seed_stop_reason,
        "root_seed_time": root_seed_time,
        "root_cut_rounds": root_cut_rounds,
        "root_cut_rounds_done": root_cut_rounds_done,
        "use_user_cuts": use_user_cuts,
        "pareto_enabled": pareto_enabled,
        "lbf_enabled": lbf_enabled,
        "vi_flags": mv.get("vi_flags", {}),
        "vi8_rows": mv.get("vi8_rows", 0),
        "vi_theta_lb": mv.get("vi_theta_lb", {}),
        "vi_theta_ub": mv.get("vi_theta_ub", {}),
        "incumbent_early_termination": incumbent_early_term,
        "parallel_oracles": parallel_oracles,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "oracle_solves": oracle_solves,
        "incumbent_evals": incumbent_evals,
        "callback_time": callback_time,
        "first_stage": best_fs,
        "scenario_q": best_q,
        "status": status,
        "diagnostic_stop": (
            "after_first_incumbent"
            if diagnostic_first_incumbent_reached else None
        ),
        "diagnostic_first_incumbent_reached": diagnostic_first_incumbent_reached,
        "history": event_log,
        "master": master,
        "vars": mv,
    }


def solve(instance, S_selected, time_limit=None, mip_gap=None, **kwargs):
    """Public L-shaped entry point."""
    method = kwargs.pop("method", "classic")
    if method == "classic":
        return solve_classic(
            instance,
            S_selected,
            time_limit=time_limit,
            mip_gap=mip_gap,
            **kwargs,
        )
    if method == "bbc":
        return solve_bbc(
            instance,
            S_selected,
            time_limit=time_limit,
            mip_gap=mip_gap,
            **kwargs,
        )
    if method == "auto":
        return solve_bbc(
            instance,
            S_selected,
            time_limit=time_limit,
            mip_gap=mip_gap,
            **kwargs,
        )
    else:
        raise NotImplementedError(
            "Supported L-shaped methods are 'classic', 'bbc', and 'auto'."
        )
