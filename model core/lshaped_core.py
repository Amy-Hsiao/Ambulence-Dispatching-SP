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

import time
from typing import Any

import gurobipy as gp
from gurobipy import GRB

import config
import extensive_form_core as model_core


# ====================================================================== #
# Phase 1 — ScenarioOracle                                               #
# ====================================================================== #

class ScenarioOracle:
    """單一情境 s 的二階 LP oracle。整個求解過程只建一次模型，
    之後每次 evaluate() 僅更新一階變數的 bounds 並以 dual simplex 熱啟動重解。
    """

    def __init__(self, instance: dict[str, Any], s: str,
                 time_limit: float = 300.0, threads: int = 1,
                 env: gp.Env | None = None):
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

def build_master(instance: dict[str, Any], S_selected: list[str],
                 norm_probs: dict[str, float],
                 time_limit: float = 3600.0, mip_gap: float = 0.01,
                 multi_cut: bool = True):
    """建 Benders master：一階變數 + 一階限制式 + θ 變數。

    Returns (model, vars_dict)；vars_dict 含 X/V/U/Y 與 theta（{s: var} 或 {"__agg__": var}）。
    """
    sets   = instance["sets"]
    J      = sets["J"]
    H      = sets["H"]
    params = instance["deterministic_parameters"]

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
        m.addConstr(V[j] <= params["ccp_staff_upper_bound"][j]     * X[j], f"Logic_V_{j}")
        m.addConstr(U[j] <= params["ccp_ambulance_upper_bound"][j] * X[j], f"Logic_U_{j}")
        m.addConstr(
            gp.quicksum(Y[h, j] for h in H) <= params["ccp_supply_upper_bound"][j] * X[j],
            f"Logic_Y_{j}",
        )

    return m, {"X": X, "V": V, "U": U, "Y": Y, "theta": theta,
               "first_stage_cost_expr": first_stage_cost}


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


def solve_classic(
    instance: dict[str, Any],
    S_selected: list[str],
    time_limit: float | None = None,
    mip_gap: float | None = None,
    multi_cut: bool = True,
    max_iterations: int | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Solve the RP with the classic multi-cut L-shaped loop.

    This is the Phase 2 correctness baseline.  The UB is always recomputed by
    evaluating the incumbent first-stage solution with every scenario oracle.
    """
    if not S_selected:
        raise ValueError("S_selected must contain at least one scenario.")

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
    )
    master.setParam("NumericFocus", 1)

    oracles = {
        s: ScenarioOracle(instance, s, time_limit=time_limit, threads=1)
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

        true_ub = _first_stage_cost(instance, fs) + weighted_q
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
    use_user_cuts: bool | None = None,
    ev_warm_start: bool | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Solve the RP with Branch-and-Benders-Cut lazy constraints.

    Lazy cuts are generated at integer incumbents.  Optional root user cuts are
    generated at the root node LP relaxation and are limited by root_cut_rounds.
    """
    if not S_selected:
        raise ValueError("S_selected must contain at least one scenario.")

    time_limit = config.SP_TIME_LIMIT if time_limit is None else float(time_limit)
    mip_gap = config.SP_MIP_GAP if mip_gap is None else float(mip_gap)
    multi_cut = config.BENDERS_MULTI_CUT if multi_cut is None else bool(multi_cut)
    if root_cut_rounds is None:
        root_cut_rounds = root_seed_iters
    if root_cut_rounds is None:
        root_cut_rounds = getattr(
            config,
            "BENDERS_ROOT_CUT_ROUNDS",
            getattr(config, "BENDERS_ROOT_SEED_ITERS", 0),
        )
    root_cut_rounds = int(root_cut_rounds)
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
    )
    master.setParam("LazyConstraints", 1)
    master.setParam("PreCrush", 1)
    master.setParam("MIPFocus", 1)
    master.setParam("NumericFocus", 1)

    oracles = {
        s: ScenarioOracle(instance, s, time_limit=time_limit, threads=1)
        for s in S_selected
    }

    best_ub = float("inf")
    best_fs = None
    best_q = None
    cuts_added = 0
    lazy_cuts_added = 0
    user_cuts_added = 0
    incumbent_evals = 0
    root_cut_rounds_done = 0
    callback_time = 0.0
    user_cut_signatures: set[tuple[Any, ...]] = set()
    event_log: list[dict[str, Any]] = []

    def evaluate_first_stage(fs: dict[str, Any]) -> tuple[float, dict[str, float], dict[str, Any]]:
        q_by_s: dict[str, float] = {}
        cut_by_s: dict[str, Any] = {}
        weighted_q = 0.0
        for s in S_selected:
            q_s, cut = oracles[s].evaluate(fs)
            q_by_s[s] = q_s
            cut_by_s[s] = cut
            weighted_q += norm_probs[s] * q_s
        return _first_stage_cost(instance, fs) + weighted_q, q_by_s, cut_by_s

    if ev_warm_start:
        ev_limit = min(time_limit, getattr(config, "VSS_EVPI_EV_TIME_LIMIT", time_limit))
        ev_fs = _solve_ev_first_stage(instance, ev_limit, mip_gap)
        if ev_fs is not None:
            ev_ub, ev_q, _ = evaluate_first_stage(ev_fs)
            _apply_first_stage_start(mv, ev_fs, J, H)
            _apply_theta_start(mv, S_selected, ev_q, norm_probs, multi_cut)
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

    if verbose:
        print("=" * 70)
        print("BRANCH-AND-BENDERS-CUT")
        if use_user_cuts and root_cut_rounds > 0:
            print(f"Root user cuts enabled: rootCutRounds={root_cut_rounds}")
        print("=" * 70)

    def bbc_callback(model, where):
        nonlocal best_ub, best_fs, best_q
        nonlocal cuts_added, lazy_cuts_added, user_cuts_added
        nonlocal incumbent_evals, root_cut_rounds_done, callback_time

        if where == GRB.Callback.MIPNODE:
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
            _, q_by_s, cut_by_s = evaluate_first_stage(fs)
            root_cut_rounds_done += 1
            cuts_this_node = 0

            if multi_cut:
                for s in S_selected:
                    theta_val = model.cbGetNodeRel(mv["theta"][s])
                    q_s = q_by_s[s]
                    cut = cut_by_s[s]
                    tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(q_s))
                    sig = _cut_signature(s, cut)
                    if q_s > theta_val + tol and sig not in user_cut_signatures:
                        model.cbCut(mv["theta"][s] >= cut_expr(cut, mv, J, H))
                        user_cut_signatures.add(sig)
                        user_cuts_added += 1
                        cuts_added += 1
                        cuts_this_node += 1
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
                "runtime": time.time() - start_time,
            })
            return

        if where == GRB.Callback.MIPSOL:
            cb_start = time.time()
            incumbent_evals += 1
            fs = _extract_first_stage(
                mv,
                J,
                H,
                round_values=True,
                from_callback=model.cbGetSolution,
            )

            true_ub, q_by_s, cut_by_s = evaluate_first_stage(fs)
            if true_ub < best_ub:
                best_ub = true_ub
                best_fs = fs
                best_q = q_by_s

            cuts_this_sol = 0
            if multi_cut:
                for s in S_selected:
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
                aggregate_q = sum(norm_probs[s] * q_by_s[s] for s in S_selected)
                tol = config.BENDERS_CUT_VIOL_REL_TOL * max(1.0, abs(aggregate_q))
                if aggregate_q > theta_val + tol:
                    expr = gp.LinExpr()
                    for s in S_selected:
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
                "runtime": time.time() - start_time,
            })

    remaining = time_limit - (time.time() - start_time)
    master.setParam("TimeLimit", max(1.0, remaining))
    master.optimize(bbc_callback)

    runtime = time.time() - start_time
    best_lb = float(master.ObjBound) if master.SolCount > 0 or master.Status in (
        GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL
    ) else None
    if best_ub == float("inf") and master.SolCount > 0:
        fs = _extract_first_stage(mv, J, H, round_values=True)
        best_ub, best_q, _ = evaluate_first_stage(fs)
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

    if verbose:
        print("-" * 70)
        print(
            f"B&BC done | status={status} | LB={best_lb if best_lb is not None else 'NA'} | "
            f"UB={best_ub if best_ub < float('inf') else 'NA'} | "
            f"gap={gap if gap is not None else 'NA'}%"
        )
        print(
            f"cuts_added={cuts_added} user_cuts={user_cuts_added} "
            f"lazy_cuts={lazy_cuts_added} rootCutRounds={root_cut_rounds_done}/"
            f"{root_cut_rounds} oracle_solves={oracle_solves} callback_time={callback_time:.2f}s"
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
        "user_cuts_added": user_cuts_added,
        "lazy_cuts_added": lazy_cuts_added,
        "root_cut_rounds": root_cut_rounds,
        "root_cut_rounds_done": root_cut_rounds_done,
        "use_user_cuts": use_user_cuts,
        "oracle_solves": oracle_solves,
        "incumbent_evals": incumbent_evals,
        "callback_time": callback_time,
        "first_stage": best_fs,
        "scenario_q": best_q,
        "status": status,
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
