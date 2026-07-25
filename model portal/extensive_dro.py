"""
extensive_dro.py — 純 extensive form（monolithic，無任何加速）入口。

供實驗三的 "Extensive" 配置使用，介面與 benders bbc.py / dro bbc.py 相同
（run_sp_model / run_dro_model → (model, summary)）：
  * run_sp_model  → SP extensive form（objective = C1 + Σ p_s Q_s，直接丟 Gurobi）
  * run_dro_model → SP+MCVaR+DRO(box) extensive form：重用 extensive_form_core 的
                    完整 recourse，把每情境「實際 recourse 成本 Q_s」餵進 risk_core
                    的同一套 DRO 對偶區塊（與 B&BC 完全相同的風險重構），因此最佳
                    目標值會與 B&BC DRO 的收斂值相同（可作為交叉驗證）。

不修改任何既有 model core / portal 邏輯：只重用 build_gurobi_model 與
risk_core._add_dro_dual_blocks。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MODEL_CORE_DIR = str(PROJECT_ROOT / "model core")
if _MODEL_CORE_DIR not in sys.path:
    sys.path.insert(0, _MODEL_CORE_DIR)

import gurobipy as gp
from gurobipy import GRB

import config
import logging_utils
import extensive_form_core as model_core
import risk_core


_STATUS_MAP = {
    GRB.OPTIMAL: "OPTIMAL",
    GRB.TIME_LIMIT: "TIME_LIMIT",
    GRB.INFEASIBLE: "INFEASIBLE",
    GRB.INF_OR_UNBD: "INF_OR_UNBD",
    GRB.UNBOUNDED: "UNBOUNDED",
}


def _configure_cpu_parallel_only(model):
    """Extensive-form baseline solver settings（公平基準）。

    只設定 CPU 平行度（Threads=0 用滿所有核心、ConcurrentMIP=1），presolve /
    cuts / heuristics 等一律採 Gurobi 預設（全部開啟）。論文中「no acceleration」
    指的是「沒有分解、沒有 B&BC 那套加速技巧」，而非關掉 Gurobi 內建加速；
    關掉內建加速會讓單體 baseline 在中大規模連可行整數解都找不到、對比不公平。
    """
    settings = {
        "Threads": 0,
        "ConcurrentMIP": 1,
    }
    for name, value in settings.items():
        model.setParam(name, value)
    return settings


def _select_and_build(scenario_size, sample_ratio, time_limit, mip_gap):
    """產生 instance、選情境、建 extensive-form 模型（回傳共用資料）。"""
    instance = config.generate_data(sample_ratio=sample_ratio)
    sets = instance["sets"]
    I, J, H = sets["I"], sets["J"], sets["H"]
    L, L_transfer, T = sets["L"], sets["L_transfer"], sets["T"]
    S_all = sets["S"]
    S_selected = S_all if scenario_size is None else S_all[:scenario_size]

    params = instance["deterministic_parameters"]
    sd = instance["scenario_data"]
    raw_probs = {s: sd["probability"][s] for s in S_selected}
    total_prob = sum(raw_probs.values())
    norm_probs = {s: p / total_prob for s, p in raw_probs.items()}

    rp_sd = {
        "demand":                      {s: sd["demand"][s]                      for s in S_selected},
        "road_availability_ij":        {s: sd["road_availability_ij"][s]        for s in S_selected},
        "road_availability_jh":        {s: sd["road_availability_jh"][s]        for s in S_selected},
        "hospital_receiving_capacity": {s: sd["hospital_receiving_capacity"][s] for s in S_selected},
    }

    model, v = model_core.build_gurobi_model(
        I, J, H, L, L_transfer, T, S_selected,
        params, rp_sd, norm_probs,
        instance["road_capacity"]["cap_ij"], instance["road_capacity"]["cap_jh"],
        instance["transport_cost"]["cost_ij"], instance["transport_cost"]["cost_jh"],
        model_name="Extensive_Model", time_limit=time_limit, mip_gap=mip_gap,
    )
    return instance, model, v, S_selected, norm_probs


def _first_stage(v, J, H):
    X, V, U, Y = v["X"], v["V"], v["U"], v["Y"]
    return {
        "X": {j: X[j].X for j in J},
        "V": {j: V[j].X for j in J},
        "U": {j: U[j].X for j in J},
        "Y": {(h, j): Y[h, j].X for h in H for j in J},
    }


def _summarize(model, v, sets):
    if model.SolCount <= 0 or model.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        return None
    obj = float(model.ObjVal)
    return {
        "objective": obj,
        "best_lb": float(model.ObjBound),
        "best_ub": obj,
        "gap_pct": float(model.MIPGap) * 100.0,
        "first_stage": _first_stage(v, sets["J"], sets["H"]),
        "bbc_stats": {
            "runtime": float(model.Runtime),
            "solver_status": _STATUS_MAP.get(model.status, str(model.status)),
        },
    }


def _apply_risk_objective(model, v, S_sel, p0, risk_cfg):
    """把「實際 recourse 成本 Q_s」餵進 risk_core 的風險重構（與 B&BC master 同一套）。

    mcvar：obj = C1 + (1-λ)Σp0·Q + λ(φ + 1/(1-α)Σp0·ℓ)，ℓ_s ≥ Q_s − φ。
    dro_*：mean/cvar 兩段用 risk_core._add_dro_dual_blocks 的對偶展開（box/ellipsoidal/polyhedral）。
    """
    C1 = v["first_stage_cost_expr"]
    Q = {s: v["scenario_cost_expr"][s] for s in S_sel}
    phi = model.addVar(lb=-GRB.INFINITY, name="phi_var")
    ell = {s: model.addVar(lb=0.0, name=f"ell[{s}]") for s in S_sel}
    for s in S_sel:
        model.addConstr(ell[s] >= Q[s] - phi, name=f"CVaR_ell_{s}")
    if risk_cfg["type"] == "mcvar":
        mean_term = gp.quicksum(p0[s] * Q[s] for s in S_sel)
        cvar_tail = gp.quicksum(p0[s] * ell[s] for s in S_sel)
    else:
        mean_term, cvar_tail = risk_core._add_dro_dual_blocks(model, Q, ell, S_sel, p0, risk_cfg)
    a = risk_cfg["alpha"]
    lm = risk_cfg["lambda"]
    model.setObjective(
        C1 + (1.0 - lm) * mean_term + lm * (phi + (1.0 / (1.0 - a)) * cvar_tail),
        GRB.MINIMIZE,
    )
    model.update()


def run_sp_model(scenario_size=None, sample_ratio=None, time_limit=None, mip_gap=None,
                 compute_kpis=False, compute_vss_evpi=False):
    scenario_size = config.SP_SCENARIO_SIZE if scenario_size is None else scenario_size
    sample_ratio = config.SP_SAMPLE_RATIO if sample_ratio is None else sample_ratio
    time_limit = config.SP_TIME_LIMIT if time_limit is None else time_limit
    mip_gap = config.SP_MIP_GAP if mip_gap is None else mip_gap

    log_path = logging_utils.build_sp_log_path(scenario_size, sample_ratio, time_limit, mip_gap)
    with logging_utils.tee_output(log_path):
        instance, model, v, S_sel, _p0 = _select_and_build(
            scenario_size, sample_ratio, time_limit, mip_gap
        )
        cpu_only_settings = _configure_cpu_parallel_only(model)
        model.setParam("OutputFlag", 1)
        logging_utils.print_run_metadata(
            "Extensive-SP",
            instance,
            (
                ("scenario_size_used", len(S_sel)),
                ("time_limit", time_limit),
                ("mip_gap", mip_gap),
                *tuple((f"gurobi_{key}", value) for key, value in cpu_only_settings.items()),
            ),
        )
        print("\nOptimizing Extensive SP Model (monolithic, no acceleration)...\n")
        model.optimize()
        summary = _summarize(model, v, instance["sets"])
    return model, summary


def run_dro_model(ambiguity_set="box", scenario_size=None, sample_ratio=None,
                  time_limit=None, mip_gap=None, alpha=None, lam=None, scope=None,
                  compute_kpis=False):
    scenario_size = config.SP_SCENARIO_SIZE if scenario_size is None else scenario_size
    sample_ratio = config.SP_SAMPLE_RATIO if sample_ratio is None else sample_ratio
    time_limit = config.SP_TIME_LIMIT if time_limit is None else time_limit
    mip_gap = config.SP_MIP_GAP if mip_gap is None else mip_gap
    rtype = {
        "box": "dro_box", "ellipsoidal": "dro_ellipsoidal", "polyhedral": "dro_polyhedral",
    }.get(ambiguity_set)
    if rtype is None:
        raise ValueError(f"未知 ambiguity_set={ambiguity_set!r}（box/ellipsoidal/polyhedral）。")
    scope_kw = {"dro_box": "epsilon_box", "dro_ellipsoidal": "a_e", "dro_polyhedral": "a_p"}[rtype]
    risk_cfg = risk_core.make_risk_cfg(
        rtype, alpha=alpha, lam=lam, **({scope_kw: scope} if scope is not None else {})
    )

    log_path = logging_utils.build_sp_log_path(scenario_size, sample_ratio, time_limit, mip_gap)
    with logging_utils.tee_output(log_path):
        instance, model, v, S_sel, p0 = _select_and_build(
            scenario_size, sample_ratio, time_limit, mip_gap
        )
        cpu_only_settings = _configure_cpu_parallel_only(model)
        risk_core.validate_risk_cfg_for_probs(risk_cfg, p0)
        _apply_risk_objective(model, v, S_sel, p0, risk_cfg)
        model.setParam("OutputFlag", 1)
        logging_utils.print_run_metadata(
            f"Extensive-DRO({ambiguity_set})",
            instance,
            (
                ("scenario_size_used", len(S_sel)),
                ("time_limit", time_limit),
                ("mip_gap", mip_gap),
                ("risk_alpha", risk_cfg["alpha"]),
                ("risk_lambda", risk_cfg["lambda"]),
                ("ambiguity_scope", risk_core.risk_scope(risk_cfg)),
                *tuple((f"gurobi_{key}", value) for key, value in cpu_only_settings.items()),
            ),
        )
        print(f"\nOptimizing Extensive SP+MCVaR+DRO({ambiguity_set}) Model "
              f"(monolithic, no acceleration)...\n")
        model.optimize()
        summary = _summarize(model, v, instance["sets"])
    return model, summary


def run_mcvar_model(scenario_size=None, sample_ratio=None, time_limit=None,
                    mip_gap=None, alpha=None, lam=None, compute_kpis=False):
    scenario_size = config.SP_SCENARIO_SIZE if scenario_size is None else scenario_size
    sample_ratio = config.SP_SAMPLE_RATIO if sample_ratio is None else sample_ratio
    time_limit = config.SP_TIME_LIMIT if time_limit is None else time_limit
    mip_gap = config.SP_MIP_GAP if mip_gap is None else mip_gap
    risk_cfg = risk_core.make_risk_cfg("mcvar", alpha=alpha, lam=lam)

    log_path = logging_utils.build_sp_log_path(scenario_size, sample_ratio, time_limit, mip_gap)
    with logging_utils.tee_output(log_path):
        instance, model, v, S_sel, p0 = _select_and_build(
            scenario_size, sample_ratio, time_limit, mip_gap
        )
        cpu_only_settings = _configure_cpu_parallel_only(model)
        _apply_risk_objective(model, v, S_sel, p0, risk_cfg)
        model.setParam("OutputFlag", 1)
        logging_utils.print_run_metadata(
            "Extensive-MCVaR",
            instance,
            (
                ("scenario_size_used", len(S_sel)),
                ("time_limit", time_limit),
                ("mip_gap", mip_gap),
                ("risk_alpha", risk_cfg["alpha"]),
                ("risk_lambda", risk_cfg["lambda"]),
                *tuple((f"gurobi_{key}", value) for key, value in cpu_only_settings.items()),
            ),
        )
        print("\nOptimizing Extensive SP+MCVaR Model (monolithic, no acceleration)...\n")
        model.optimize()
        summary = _summarize(model, v, instance["sets"])
    return model, summary
