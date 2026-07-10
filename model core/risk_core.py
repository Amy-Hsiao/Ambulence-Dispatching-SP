"""
risk_core.py — MCVaR / DRO 風險層（掛在 Benders master 上）。

設計原則（見 plan/08、plan/09）：
* 風險只改 master 的目標式與輔助變數；ScenarioOracle 與 cut 邏輯一律不動。
  數學依據：cuts 是 θ_s ≥ Q_s(x) 的下界近似，而 MCVaR / WMCVaR 目標對每個
  Q_s 單調不減（ambiguity set 內所有機率 ≥ 0），故以 θ_s 代 Q_s 後 master
  仍是有效鬆弛，master.ObjBound 是原風險問題的合法 LB。
* risk_cfg=None（或 type="sp"）時所有函式退化為期望值，行為與舊版完全相同。
* 模型切換：risk_cfg["type"] ∈ {"sp","mcvar","dro_box","dro_ellipsoidal",
  "dro_polyhedral"}；SP / SP+MCVaR / SP+MCVaR+DRO 隨時可切，互不影響。

公式對應（Thesis_Draft 3.4–3.5 節與 Appendix A）：
    (1)(1a)(1b)(1e)  MCVaR：obj = C1 + (1−λ)Σp·θ + λ(φ + 1/(1−α)Σp·ℓ)
    (32)+(35)/Thm A.1  DRO-B（box, MILP）：
        γ·e + ζ − ϖ = θ；obj 加 ε̄_B(eᵀζ + eᵀϖ)（mean 與 CVaR 兩組對偶）
    (33)+(36)/Thm A.2  DRO-E（ellipsoidal, MISOCP）：
        ‖A_Eᵀ(θ + Δ + π·e)‖₂ ≤ ν；obj 加 p0ᵀΔ + ν（A_E = a_E·I）
    (34)+(37)/Thm A.3  DRO-P（polyhedral, MILP）：
        |a_P(θ_s + Γ_s + χ)| ≤ ψ ∀s；obj 加 p0ᵀΓ + ψ（A_P = a_P·I）
"""
from __future__ import annotations

from typing import Any

import gurobipy as gp
from gurobipy import GRB

import config

RISK_TYPES = ("sp", "mcvar", "dro_box", "dro_ellipsoidal", "dro_polyhedral")
DRO_TYPES = ("dro_box", "dro_ellipsoidal", "dro_polyhedral")

_QUIET_ENV: gp.Env | None = None


def _quiet_env() -> gp.Env:
    """小型評估模型共用的靜音 Gurobi 環境（lazy 建立）。"""
    global _QUIET_ENV
    if _QUIET_ENV is None:
        env = gp.Env(empty=True)
        env.setParam("OutputFlag", 0)
        env.start()
        _QUIET_ENV = env
    return _QUIET_ENV


# ====================================================================== #
# risk_cfg 建構與驗證                                                     #
# ====================================================================== #

def make_risk_cfg(
    risk_type: str | None = None,
    alpha: float | None = None,
    lam: float | None = None,
    epsilon_box: float | None = None,
    a_e: float | None = None,
    a_p: float | None = None,
) -> dict[str, Any] | None:
    """組出 risk_cfg dict；type 為 None/"sp" 時回傳 None（= 原 SP 路徑）。

    參數為 None 時讀 config 預設值（RISK_ALPHA / RISK_LAMBDA / DRO_*）。
    """
    if risk_type is None or risk_type == "sp":
        return None
    if risk_type not in RISK_TYPES:
        raise ValueError(f"Unknown risk_type {risk_type!r}; expected one of {RISK_TYPES}.")

    alpha = float(getattr(config, "RISK_ALPHA", 0.9) if alpha is None else alpha)
    lam = float(getattr(config, "RISK_LAMBDA", 0.5) if lam is None else lam)
    if not (0.0 <= alpha < 1.0):
        raise ValueError(f"alpha must satisfy 0 <= alpha < 1 (got {alpha}).")
    if not (0.0 <= lam <= 1.0):
        raise ValueError(f"lambda must satisfy 0 <= lambda <= 1 (got {lam}).")

    cfg: dict[str, Any] = {"type": risk_type, "alpha": alpha, "lambda": lam}

    if risk_type == "dro_box":
        cfg["epsilon_box"] = float(
            getattr(config, "DRO_EPSILON_BOX", 0.01) if epsilon_box is None else epsilon_box
        )
        if cfg["epsilon_box"] < 0:
            raise ValueError("epsilon_box must be >= 0.")
    elif risk_type == "dro_ellipsoidal":
        cfg["a_e"] = float(getattr(config, "DRO_A_E", 0.0005) if a_e is None else a_e)
        if cfg["a_e"] < 0:
            raise ValueError("a_e must be >= 0.")
    elif risk_type == "dro_polyhedral":
        cfg["a_p"] = float(getattr(config, "DRO_A_P", 0.001) if a_p is None else a_p)
        if cfg["a_p"] < 0:
            raise ValueError("a_p must be >= 0.")
    return cfg


def risk_scope(risk_cfg: dict[str, Any]) -> float | None:
    """回傳 ambiguity set 的 scope 參數值（mcvar/sp 回傳 None）。"""
    if risk_cfg is None:
        return None
    return {
        "dro_box": risk_cfg.get("epsilon_box"),
        "dro_ellipsoidal": risk_cfg.get("a_e"),
        "dro_polyhedral": risk_cfg.get("a_p"),
    }.get(risk_cfg["type"])


def validate_risk_cfg_for_probs(risk_cfg: dict[str, Any] | None,
                                p0: dict[str, float]) -> None:
    """機率相關的有效性檢查（box set 的 p ≥ 0 條件，見 plan/09）。

    box 定義 (32) 不含 p ≥ 0，故要求 ε̄_B ≤ min_s p0_s；否則 worst-case
    機率可能為負 → 目標對 Q_s 不再單調 → Benders cut 下界失效。
    ellipsoidal (33) / polyhedral (34) 已內含 p0 + A·ε ≥ 0，天然滿足。
    """
    if risk_cfg is None:
        return
    if risk_cfg["type"] == "dro_box":
        min_p = min(p0.values())
        eps = risk_cfg["epsilon_box"]
        if eps > min_p + 1e-12:
            raise ValueError(
                f"Box ambiguity set requires epsilon_box <= min_s p0_s "
                f"(epsilon_box={eps}, min p0={min_p:.6f})，否則 worst-case 機率"
                f"可能為負、Benders cut 下界失效。請調小 DRO_EPSILON_BOX。"
            )


# ====================================================================== #
# DRO 對偶區塊（master 與小型評估模型共用同一份建構邏輯）                    #
# ====================================================================== #

def _add_dro_dual_blocks(
    m: gp.Model,
    q_expr: dict[str, Any],
    ell_expr: dict[str, Any],
    S: list[str],
    p0: dict[str, float],
    risk_cfg: dict[str, Any],
) -> tuple[Any, Any]:
    """加入兩組 worst-case expectation 的對偶變數/限制式。

    q_expr / ell_expr：{s: gurobi var 或常數}，分別代表 Q_s（master 中為
    θ_s）與 ℓ_s。回傳 (mean_term, cvar_term) 兩個目標式片段：
        mean_term ≥ sup_{p∈P} Qᵀp    cvar_term ≥ sup_{p∈P} ℓᵀp
    （對偶最小化下取等式；Thesis Thm A.1–A.3。）
    """
    rtype = risk_cfg["type"]
    nominal_q = gp.quicksum(p0[s] * q_expr[s] for s in S)
    nominal_l = gp.quicksum(p0[s] * ell_expr[s] for s in S)

    if rtype == "dro_box":
        eps = risk_cfg["epsilon_box"]
        gamma = m.addVar(lb=-GRB.INFINITY, name="dro_gamma")
        zeta = {s: m.addVar(lb=0.0, name=f"dro_zeta[{s}]") for s in S}
        varpi = {s: m.addVar(lb=0.0, name=f"dro_varpi[{s}]") for s in S}
        gamma_h = m.addVar(lb=-GRB.INFINITY, name="dro_gamma_hat")
        zeta_h = {s: m.addVar(lb=0.0, name=f"dro_zeta_hat[{s}]") for s in S}
        varpi_h = {s: m.addVar(lb=0.0, name=f"dro_varpi_hat[{s}]") for s in S}
        for s in S:
            m.addConstr(gamma + zeta[s] - varpi[s] == q_expr[s],
                        name=f"dro_box_mean_{s}")
            m.addConstr(gamma_h + zeta_h[s] - varpi_h[s] == ell_expr[s],
                        name=f"dro_box_cvar_{s}")
        mean_term = nominal_q + eps * (
            gp.quicksum(zeta[s] for s in S) + gp.quicksum(varpi[s] for s in S)
        )
        cvar_term = nominal_l + eps * (
            gp.quicksum(zeta_h[s] for s in S) + gp.quicksum(varpi_h[s] for s in S)
        )
        return mean_term, cvar_term

    if rtype == "dro_ellipsoidal":
        a_e = risk_cfg["a_e"]
        delta = {s: m.addVar(lb=0.0, name=f"dro_delta[{s}]") for s in S}
        nu = m.addVar(lb=0.0, name="dro_nu")
        pi = m.addVar(lb=-GRB.INFINITY, name="dro_pi")
        delta_h = {s: m.addVar(lb=0.0, name=f"dro_delta_hat[{s}]") for s in S}
        nu_h = m.addVar(lb=0.0, name="dro_nu_hat")
        pi_h = m.addVar(lb=-GRB.INFINITY, name="dro_pi_hat")
        # t_s = a_E·(θ_s + Δ_s + π)；‖t‖₂ ≤ ν（SOC，ν ≥ 0）
        t = {s: m.addVar(lb=-GRB.INFINITY, name=f"dro_t[{s}]") for s in S}
        t_h = {s: m.addVar(lb=-GRB.INFINITY, name=f"dro_t_hat[{s}]") for s in S}
        for s in S:
            m.addConstr(t[s] == a_e * (q_expr[s] + delta[s] + pi),
                        name=f"dro_ell_t_{s}")
            m.addConstr(t_h[s] == a_e * (ell_expr[s] + delta_h[s] + pi_h),
                        name=f"dro_ell_t_hat_{s}")
        m.addQConstr(
            gp.quicksum(t[s] * t[s] for s in S) <= nu * nu, name="dro_ell_soc_mean"
        )
        m.addQConstr(
            gp.quicksum(t_h[s] * t_h[s] for s in S) <= nu_h * nu_h,
            name="dro_ell_soc_cvar",
        )
        mean_term = nominal_q + gp.quicksum(p0[s] * delta[s] for s in S) + nu
        cvar_term = nominal_l + gp.quicksum(p0[s] * delta_h[s] for s in S) + nu_h
        return mean_term, cvar_term

    if rtype == "dro_polyhedral":
        a_p = risk_cfg["a_p"]
        gam = {s: m.addVar(lb=0.0, name=f"dro_Gamma[{s}]") for s in S}
        psi = m.addVar(lb=0.0, name="dro_psi")
        chi = m.addVar(lb=-GRB.INFINITY, name="dro_chi")
        gam_h = {s: m.addVar(lb=0.0, name=f"dro_Gamma_hat[{s}]") for s in S}
        psi_h = m.addVar(lb=0.0, name="dro_psi_hat")
        chi_h = m.addVar(lb=-GRB.INFINITY, name="dro_chi_hat")
        # ∞-norm 線性化：−ψ ≤ a_P(θ_s + Γ_s + χ) ≤ ψ ∀s（hat 同理）
        for s in S:
            m.addConstr(a_p * (q_expr[s] + gam[s] + chi) <= psi,
                        name=f"dro_poly_ub_{s}")
            m.addConstr(a_p * (q_expr[s] + gam[s] + chi) >= -psi,
                        name=f"dro_poly_lb_{s}")
            m.addConstr(a_p * (ell_expr[s] + gam_h[s] + chi_h) <= psi_h,
                        name=f"dro_poly_ub_hat_{s}")
            m.addConstr(a_p * (ell_expr[s] + gam_h[s] + chi_h) >= -psi_h,
                        name=f"dro_poly_lb_hat_{s}")
        mean_term = nominal_q + gp.quicksum(p0[s] * gam[s] for s in S) + psi
        cvar_term = nominal_l + gp.quicksum(p0[s] * gam_h[s] for s in S) + psi_h
        return mean_term, cvar_term

    raise ValueError(f"Unsupported DRO type {rtype!r}.")


# ====================================================================== #
# master 風險層（φ, ℓ_s + 目標式改寫）                                     #
# ====================================================================== #

def attach_risk_to_master(
    m: gp.Model,
    mv: dict[str, Any],
    S_selected: list[str],
    p0: dict[str, float],
    risk_cfg: dict[str, Any],
) -> None:
    """在 build_master 建好的 master 上加風險層並改寫目標式。

    需求：multi-cut master（theta = {s: var}）。mv 會被就地加入
    "phi"、"ell"（DRO 對偶變數留在 model 內，不需外部存取）。
    """
    theta = mv["theta"]
    if "__agg__" in theta:
        raise ValueError(
            "Risk-averse master requires multi-cut theta（single-cut 聚合 θ 無法"
            "定義 per-scenario ℓ_s）。請以 BENDERS_MULTI_CUT=True 執行。"
        )
    validate_risk_cfg_for_probs(risk_cfg, p0)

    alpha = risk_cfg["alpha"]
    lam = risk_cfg["lambda"]
    rtype = risk_cfg["type"]
    C1 = mv["first_stage_cost_expr"]

    # 共通：φ（free）與 ℓ_s ≥ θ_s − φ（式 1b/1e，Q_s 以 θ_s 代）
    phi = m.addVar(lb=-GRB.INFINITY, name="phi_var")
    ell = {s: m.addVar(lb=0.0, name=f"ell[{s}]") for s in S_selected}
    for s in S_selected:
        m.addConstr(ell[s] >= theta[s] - phi, name=f"CVaR_ell_{s}")
    mv["phi"] = phi
    mv["ell"] = ell

    if rtype == "mcvar":
        # obj = C1 + (1−λ)Σp0θ + λ(φ + 1/(1−α)Σp0ℓ)   —— 式 (1)+(1a)+(1b)
        mean_term = gp.quicksum(p0[s] * theta[s] for s in S_selected)
        cvar_tail = gp.quicksum(p0[s] * ell[s] for s in S_selected)
    elif rtype in DRO_TYPES:
        # obj = C1 + λφ + (1−λ)·sup_p Qᵀp + λ/(1−α)·sup_p ℓᵀp —— 式 (31)+(35)–(37)
        theta_expr = {s: theta[s] for s in S_selected}
        ell_expr = {s: ell[s] for s in S_selected}
        mean_term, cvar_tail = _add_dro_dual_blocks(
            m, theta_expr, ell_expr, S_selected, p0, risk_cfg
        )
    else:  # pragma: no cover
        raise ValueError(f"Unsupported risk type {rtype!r} in attach_risk_to_master.")

    obj = (
        C1
        + (1.0 - lam) * mean_term
        + lam * (phi + (1.0 / (1.0 - alpha)) * cvar_tail)
    )
    m.setObjective(obj, GRB.MINIMIZE)
    m.update()


# ====================================================================== #
# 給定 Q 向量的目標值評估（incumbent UB / warm start 用）                   #
# ====================================================================== #

def evaluate_mcvar(
    q_by_s: dict[str, float],
    p0: dict[str, float],
    alpha: float,
    lam: float,
) -> tuple[float, float]:
    """給定情境成本向量 Q 與機率 p0，解析計算 MCVaR 與最佳 φ*。

    離散分佈下 CVaR 最小化式 (1b) 的最佳 φ* 是 α-分位數：
    將 Q 由小到大排序，φ* = 累積機率首次 ≥ α 的 Q 值（Rockafellar–Uryasev）。
    α=0 時 CVaR_0 = E[Q]（φ* = min Q，(Q−φ*)^+ 全取正部）。

    Returns (mcvar_value, phi_star)。
    """
    if not q_by_s:
        raise ValueError("q_by_s must not be empty.")
    exp_q = sum(p0[s] * q_by_s[s] for s in q_by_s)
    phi_star = _discrete_var_quantile(q_by_s, p0, alpha)
    if lam == 0.0:
        return exp_q, phi_star
    tail = sum(p0[s] * max(q_by_s[s] - phi_star, 0.0) for s in q_by_s)
    cvar = phi_star + tail / (1.0 - alpha)
    return (1.0 - lam) * exp_q + lam * cvar, phi_star


def _discrete_var_quantile(q_by_s, p0, alpha) -> float:
    """離散分佈的 α-分位數（VaR_α）：排序後累積機率首次 ≥ α 的 Q 值。"""
    items = sorted(q_by_s.items(), key=lambda kv: kv[1])
    cum = 0.0
    for s, q in items:
        cum += p0[s]
        if cum >= alpha - 1e-12:
            return q
    return items[-1][1]  # 數值誤差保護（機率總和略 < α 時取最大值）


def evaluate_wmcvar(
    q_by_s: dict[str, float],
    p0: dict[str, float],
    risk_cfg: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """給定 Q 向量，計算 worst-case MCVaR（DRO incumbent UB 評估）。

    解一個只含 (φ, ℓ, 對偶變數) 的小型 LP/SOCP（|S| 維、毫秒級、靜音），
    即 master 的 DRO 重構式把 θ_s 換成常數 Q_s。
    Returns (wmcvar_value, detail)；detail 含 phi_star 與 worst_p
    （在 φ* 下組合權重的 worst-case 機率向量，供報表分析）。
    """
    validate_risk_cfg_for_probs(risk_cfg, p0)
    S = list(q_by_s)
    alpha = risk_cfg["alpha"]
    lam = risk_cfg["lambda"]

    m = gp.Model("wmcvar_eval", env=_quiet_env())
    m.setParam("OutputFlag", 0)
    phi = m.addVar(lb=-GRB.INFINITY, name="phi_var")
    ell = {s: m.addVar(lb=0.0, name=f"ell[{s}]") for s in S}
    for s in S:
        m.addConstr(ell[s] >= q_by_s[s] - phi, name=f"CVaR_ell_{s}")
    q_expr = {s: float(q_by_s[s]) for s in S}
    mean_term, cvar_tail = _add_dro_dual_blocks(m, q_expr, ell, S, p0, risk_cfg)
    m.setObjective(
        (1.0 - lam) * mean_term
        + lam * (phi + (1.0 / (1.0 - alpha)) * cvar_tail),
        GRB.MINIMIZE,
    )
    m.optimize()
    if m.status != GRB.OPTIMAL:
        raise RuntimeError(f"evaluate_wmcvar: status={m.status} (expected OPTIMAL).")
    value = float(m.ObjVal)
    phi_star = float(phi.X)
    ell_star = {s: float(ell[s].X) for s in S}
    m.dispose()

    # worst-case p：在 φ* 固定下，最大化組合權重 (1−λ)Q + λ/(1−α)ℓ* 的機率向量
    weights = {
        s: (1.0 - lam) * q_by_s[s] + lam / (1.0 - alpha) * ell_star[s] for s in S
    }
    worst_p = worst_case_distribution(weights, p0, risk_cfg)
    return value, {"phi_star": phi_star, "ell_star": ell_star, "worst_p": worst_p}


def worst_case_distribution(
    weights: dict[str, float],
    p0: dict[str, float],
    risk_cfg: dict[str, Any],
) -> dict[str, float]:
    """解原始問題 max_{p∈P} weightsᵀp，回傳 worst-case 機率向量。

    直接照 ambiguity set 定義 (32)–(34) 建原始 LP/QCP（也用於驗證對偶重構）。
    """
    S = list(weights)
    rtype = risk_cfg["type"]
    m = gp.Model("worst_p", env=_quiet_env())
    m.setParam("OutputFlag", 0)
    epsv = {s: m.addVar(lb=-GRB.INFINITY, name=f"eps[{s}]") for s in S}
    m.addConstr(gp.quicksum(epsv[s] for s in S) == 0.0, name="sum_zero")

    if rtype == "dro_box":
        scale = 1.0
        bound = risk_cfg["epsilon_box"]
        for s in S:
            epsv[s].lb = -bound
            epsv[s].ub = bound
        # box 定義 (32) 不含 p ≥ 0；ε̄_B ≤ min p0 已由 validate 確保 p ≥ 0
    elif rtype == "dro_ellipsoidal":
        scale = risk_cfg["a_e"]
        m.addQConstr(
            gp.quicksum(epsv[s] * epsv[s] for s in S) <= 1.0, name="norm2"
        )
        for s in S:
            m.addConstr(p0[s] + scale * epsv[s] >= 0.0, name=f"p_nonneg_{s}")
    elif rtype == "dro_polyhedral":
        scale = risk_cfg["a_p"]
        u = {s: m.addVar(lb=0.0, name=f"abs[{s}]") for s in S}
        for s in S:
            m.addConstr(u[s] >= epsv[s])
            m.addConstr(u[s] >= -epsv[s])
        m.addConstr(gp.quicksum(u[s] for s in S) <= 1.0, name="norm1")
        for s in S:
            m.addConstr(p0[s] + scale * epsv[s] >= 0.0, name=f"p_nonneg_{s}")
    else:
        raise ValueError(f"worst_case_distribution: unsupported type {rtype!r}.")

    m.setObjective(
        gp.quicksum(weights[s] * (p0[s] + scale * epsv[s]) for s in S),
        GRB.MAXIMIZE,
    )
    m.optimize()
    if m.status != GRB.OPTIMAL:
        raise RuntimeError(f"worst_case_distribution: status={m.status}.")
    result = {s: float(p0[s] + scale * epsv[s].X) for s in S}
    m.dispose()
    return result


def second_stage_objective_from_Q(
    q_by_s: dict[str, float],
    p0: dict[str, float],
    risk_cfg: dict[str, Any] | None,
) -> float:
    """UB 評估的統一分派：回傳「二階部分」的目標值（不含 C1）。

    * None / "sp"  → Σ p0_s·Q_s（與舊版完全一致）
    * "mcvar"      → evaluate_mcvar
    * "dro_*"      → evaluate_wmcvar（worst-case MCVaR）
    """
    if risk_cfg is None or risk_cfg["type"] == "sp":
        return sum(p0[s] * q_by_s[s] for s in q_by_s)
    if risk_cfg["type"] == "mcvar":
        value, _ = evaluate_mcvar(q_by_s, p0, risk_cfg["alpha"], risk_cfg["lambda"])
        return value
    if risk_cfg["type"] in DRO_TYPES:
        return evaluate_wmcvar(q_by_s, p0, risk_cfg)[0]
    raise ValueError(f"Unsupported risk type {risk_cfg['type']!r}.")


# ====================================================================== #
# warm start（φ / ℓ 的 Start 值）                                          #
# ====================================================================== #

def apply_risk_start(
    mv: dict[str, Any],
    S_selected: list[str],
    q_by_s: dict[str, float],
    p0: dict[str, float],
    risk_cfg: dict[str, Any] | None,
) -> None:
    """在 _apply_theta_start 之後呼叫：給 φ / ℓ_s 設 MIP start。

    DRO 時 φ* 以名目分佈的分位數當起始值即可（Start 只是提示，Gurobi 會
    自行補全對偶變數）。risk_cfg=None 或 master 無風險層時不做任何事。
    """
    if risk_cfg is None or "phi" not in mv:
        return
    _, phi_star = evaluate_mcvar(
        q_by_s, p0, risk_cfg["alpha"], risk_cfg["lambda"]
    )
    mv["phi"].Start = phi_star
    for s in S_selected:
        mv["ell"][s].Start = max(q_by_s[s] - phi_star, 0.0)


# ====================================================================== #
# 報表輔助（portal RESULT SUMMARY 的 risk 區塊）                            #
# ====================================================================== #

def risk_summary_from_Q(
    q_by_s: dict[str, float],
    p0: dict[str, float],
    risk_cfg: dict[str, Any],
) -> dict[str, Any]:
    """回傳 risk 區塊要印的數字：E[Q]、VaR(φ*)、CVaR、MCVaR；
    DRO 時另含 WMCVaR、worst-case p 最大偏差與 scope。"""
    alpha = risk_cfg["alpha"]
    lam = risk_cfg["lambda"]
    exp_q = sum(p0[s] * q_by_s[s] for s in q_by_s)
    phi_star = _discrete_var_quantile(q_by_s, p0, alpha)
    tail = sum(p0[s] * max(q_by_s[s] - phi_star, 0.0) for s in q_by_s)
    cvar = phi_star + tail / (1.0 - alpha) if alpha < 1.0 else float("nan")
    mcvar = (1.0 - lam) * exp_q + lam * cvar
    out: dict[str, Any] = {
        "alpha": alpha,
        "lambda": lam,
        "expected_Q": exp_q,
        "phi_star_VaR": phi_star,
        "CVaR": cvar,
        "MCVaR": mcvar,
    }
    if risk_cfg["type"] in DRO_TYPES:
        wmcvar, detail = evaluate_wmcvar(q_by_s, p0, risk_cfg)
        out["WMCVaR"] = wmcvar
        out["phi_star_dro"] = detail["phi_star"]
        out["worst_p"] = detail["worst_p"]
        out["worst_p_max_dev"] = max(
            abs(detail["worst_p"][s] - p0[s]) for s in p0
        )
        out["scope"] = risk_scope(risk_cfg)
    return out
