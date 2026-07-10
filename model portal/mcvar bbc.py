"""
mcvar bbc.py — SP + MCVaR 的 Branch-and-Benders-Cut 入口（plan/08）。

介面與 `benders bbc.py` 相同：run_mcvar_model(...) -> (model, summary)。
與 SP 的差異只在 master 目標式（風險層由 risk_core 掛上）；oracle、cut、
root seeding、EV warm start、parallel oracles 等 enhancement 全部沿用。

輸出契約：
* RESULT SUMMARY 欄位標籤與 benders bbc 完全一致（batch runner 正則照常解析）；
  VSS/EVPI 對風險模型不適用，一律印 NA；之後加印 RISK MEASURE 區塊與
  B&BC 統計區塊。
* log 檔名以 MCVAR_BBC_ 開頭，尾端含 _a{alpha}_l{lambda}。
"""
import importlib.util
import sys
import time
from pathlib import Path

# ── bootstrap：讓 model core/ 內的模組可被 import ─────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MODEL_CORE_DIR = str(PROJECT_ROOT / "model core")
if _MODEL_CORE_DIR not in sys.path:
    sys.path.insert(0, _MODEL_CORE_DIR)

import config  # noqa: E402
import logging_utils  # noqa: E402
import lshaped_core  # noqa: E402
import risk_core  # noqa: E402


def _load_bbc_portal():
    """載入 benders bbc.py（檔名含空白，需用 importlib），重用其 KPI 評估。"""
    path = PROJECT_ROOT / "model portal" / "benders bbc.py"
    spec = importlib.util.spec_from_file_location("benders_bbc_portal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_mcvar_log_path(scenario_size, sample_ratio, time_limit, mip_gap,
                          alpha, lam) -> Path:
    used = "ALL" if scenario_size is None else scenario_size
    base_name = (
        f"MCVAR_BBC_seed{config.MASTER_SEED}"
        f"_scen{config.SCENARIOS}"
        f"_used{used}"
        f"_period{config.TIME_PERIODS}"
        f"_sample{logging_utils._format_value(sample_ratio)}"
        f"_D{logging_utils._format_value(config.DEMAND_MULTIPLIER)}"
        f"_R{logging_utils._format_value(config.ROAD_CAPACITY_MULTIPLIER)}"
        f"_H{logging_utils._format_value(config.HOSPITAL_CAPACITY_MULTIPLIER)}"
        f"_tl{logging_utils._format_value(time_limit)}"
        f"_gap{logging_utils._format_value(mip_gap)}"
        f"_a{logging_utils._format_value(alpha)}"
        f"_l{logging_utils._format_value(lam)}"
    )
    return logging_utils._unique_log_path(base_name)


def run_mcvar_model(scenario_size=None, sample_ratio=None, time_limit=None,
                    mip_gap=None, alpha=None, lam=None, compute_kpis=True):
    scenario_size = config.SP_SCENARIO_SIZE if scenario_size is None else scenario_size
    sample_ratio = config.SP_SAMPLE_RATIO if sample_ratio is None else sample_ratio
    time_limit = config.SP_TIME_LIMIT if time_limit is None else time_limit
    mip_gap = config.SP_MIP_GAP if mip_gap is None else mip_gap
    risk_cfg = risk_core.make_risk_cfg("mcvar", alpha=alpha, lam=lam)

    log_path = _build_mcvar_log_path(
        scenario_size, sample_ratio, time_limit, mip_gap,
        risk_cfg["alpha"], risk_cfg["lambda"],
    )
    with logging_utils.tee_output(log_path):
        return _run(scenario_size, sample_ratio, time_limit, mip_gap,
                    risk_cfg, compute_kpis)


def _run(scenario_size, sample_ratio, time_limit, mip_gap, risk_cfg, compute_kpis):
    wall_start = time.time()
    instance = config.generate_data(sample_ratio=sample_ratio)
    sets = instance["sets"]
    I, J, H, T = sets["I"], sets["J"], sets["H"], sets["T"]
    S_selected = sets["S"] if scenario_size is None else sets["S"][:scenario_size]

    logging_utils.print_run_metadata(
        "MCVAR-BBC (mean-CVaR, multi-cut Branch-and-Benders-Cut)",
        instance,
        (
            ("scenario_size_used", len(S_selected)),
            ("time_limit", time_limit),
            ("mip_gap", mip_gap),
            ("risk_alpha", risk_cfg["alpha"]),
            ("risk_lambda", risk_cfg["lambda"]),
            ("multi_cut", config.BENDERS_MULTI_CUT),
            ("root_seed_iters", getattr(config, "BENDERS_ROOT_SEED_ITERS", 0)),
            ("root_cut_rounds", getattr(config, "BENDERS_ROOT_CUT_ROUNDS", 0)),
            ("use_user_cuts", getattr(config, "BENDERS_USE_USER_CUTS", False)),
            ("ev_warm_start", getattr(config, "BENDERS_EV_WARM_START", True)),
        ),
    )

    print("=" * 50)
    print(f"\nOptimizing SP+MCVaR Model (alpha={risk_cfg['alpha']}, "
          f"lambda={risk_cfg['lambda']}) — B&BC engine...\n")
    result = lshaped_core.solve(
        instance, S_selected,
        time_limit=time_limit, mip_gap=mip_gap,
        method="bbc",
        risk_cfg=risk_cfg,
    )

    if result.get("best_ub") is None or result.get("first_stage") is None:
        print(f"B&BC did not produce a feasible solution (status={result.get('status')}).")
        return None, None

    master = result["master"]
    rp_best_ub = float(result["best_ub"])
    rp_best_lb = float(result["best_lb"]) if result.get("best_lb") is not None else float("-inf")
    rp_gap = float(result["gap_pct"]) if result.get("gap_pct") is not None else float("nan")
    best_fs = result["first_stage"]
    best_q = result["scenario_q"]

    sd = instance["scenario_data"]
    raw_probs = {s: sd["probability"][s] for s in S_selected}
    total_prob = sum(raw_probs.values())
    norm_probs = {s: p / total_prob for s, p in raw_probs.items()}

    # ---- risk 摘要（E[Q]、VaR、CVaR、MCVaR；由 oracle 的 Q 向量計算）--------
    risk_stats = risk_core.risk_summary_from_Q(best_q, norm_probs, risk_cfg)
    first_stage_cost = lshaped_core._first_stage_cost(instance, best_fs)

    # ---- summary dict（形狀比照 vss_evpi 輸出；VSS/EVPI 不適用風險模型）----
    summary = {
        "VSS_pct": None,
        "EVPI_pct": None,
        "objective": rp_best_ub,
        "best_lb": rp_best_lb,
        "gap_pct": rp_gap,
        "first_stage": best_fs,
        "first_stage_cost": first_stage_cost,
        "risk": dict(risk_stats),
        "risk_cfg": dict(risk_cfg),
        "bbc_stats": {
            "engine":               "bbc",
            "risk_type":            risk_cfg["type"],
            "multi_cut":            config.BENDERS_MULTI_CUT,
            "cuts_added":           result.get("cuts_added"),
            "lazy_cuts_added":      result.get("lazy_cuts_added"),
            "user_cuts_added":      result.get("user_cuts_added"),
            "seed_cuts_added":      result.get("seed_cuts_added"),
            "root_seed_iters_done": result.get("root_seed_iters_done"),
            "root_seed_iters":      result.get("root_seed_iters"),
            "root_seed_lb":         result.get("root_seed_lb"),
            "root_seed_stop_reason": result.get("root_seed_stop_reason"),
            "root_seed_time":       result.get("root_seed_time"),
            "root_cut_rounds_done": result.get("root_cut_rounds_done"),
            "root_cut_rounds":      result.get("root_cut_rounds"),
            "use_user_cuts":        result.get("use_user_cuts"),
            "oracle_solves":        result.get("oracle_solves"),
            "incumbent_evals":      result.get("incumbent_evals"),
            "callback_time":        result.get("callback_time"),
            "solver_status":        result.get("status"),
            "runtime":              result.get("runtime"),
        },
    }

    # ---- KPI（重用 benders bbc 的 _evaluate_kpis；固定 best_fs 逐情境重解）--
    kpis = None
    bbc_portal = None
    if compute_kpis:
        bbc_portal = _load_bbc_portal()
        kpis = bbc_portal._evaluate_kpis(instance, S_selected, norm_probs, best_fs)

    total_demand = sum(
        norm_probs[s] * sd["demand"][s][t][i].get(l, 0)
        for s in S_selected for t in T for i in I for l in sets["L"]
    )

    # ---- RESULT SUMMARY（欄位標籤與 benders bbc 完全一致）------------------
    print("\n" + "=" * 50)
    print("SP MODEL (RP) RESULT SUMMARY")
    print(" ")
    print(f" - Engine: multi-cut Branch-and-Benders-Cut (MCVaR)")
    print(f" - Disaster Areas: {len(I)}")
    print(f" - Candidate CCPs: {len(J)}")
    print(f" - Hospitals: {len(H)}")
    print(f" - Scenarios: {len(S_selected)}")
    print(f" - Time Period: {len(T)}")
    print(f" - Objective Value:     {rp_best_ub:.2f}")
    print(f" - CPU Time:            {result['runtime']:.2f} s")
    print(f" - num_vars:            {master.NumVars:d}")
    print(f" - num_constrs:         {master.NumConstrs:d}")
    print(f" - Nodes:               {master.NodeCount:.0f}")
    print(f" - Iteration:           {master.IterCount:.0f} (Simplex iterations)")
    print(f" - Best UB (Objective): {rp_best_ub:.2f}")
    print(f" - Best LB (Bound):     {rp_best_lb:.2f}")
    print(f" - Final Gap:           {rp_gap:.4f}%")
    print(f" - VSS(%)    = NA")
    print(f" - EVPI(%)   = NA")
    print("-" * 50)
    print(" - RISK MEASURE (mean-CVaR of second-stage cost):")
    print(f" - alpha:               {risk_cfg['alpha']}")
    print(f" - lambda:              {risk_cfg['lambda']}")
    print(f" - first_stage_cost:    {first_stage_cost:.2f}")
    print(f" - expected_Q:          {risk_stats['expected_Q']:.2f}")
    print(f" - VaR (phi*):          {risk_stats['phi_star_VaR']:.2f}")
    print(f" - CVaR_alpha:          {risk_stats['CVaR']:.2f}")
    print(f" - MCVaR:               {risk_stats['MCVaR']:.2f}")
    print("-" * 50)
    print(" - First-stage decisions (Here and Now):")
    for j in J:
        if best_fs["X"][j] > 0.5:
            supply = sum(best_fs["Y"].get((h, j), 0) for h in H)
            print(
                f"   CCP {j:4s} -> X: 1, Staff(V): {best_fs['V'][j]:2.0f}, "
                f"Amb(U): {best_fs['U'][j]:2.0f}, MedicalSupply(Y): {supply:.2f}"
            )
    if kpis is not None:
        print("-" * 50)
        print(" - Expected KPIs (probability-weighted across scenarios):")
        print(" - total_demand:                  {:.2f}".format(total_demand))
        print(" - total_transported_to_ccp (FI): {:.2f}".format(kpis["tot"]["FI"]))
        print(" - total_transferred_to_hospital (FO): {:.2f}".format(kpis["tot"]["FO"]))
        print(" - total_remaining_disaster_area (RM): {:.2f} (all periods summed)".format(kpis["tot"]["RM"]))
        print(" - total_waiting_at_ccp (WAT):         {:.2f} (all periods summed)".format(kpis["tot"]["WAT"]))
        print("-" * 50)
        print(" - max_ccp_utilization_%:                {:6.2f} %".format(kpis["mx"]["ccp"]))
        print(" - max_hospital_utilization_%:           {:6.2f} %".format(kpis["mx"]["hosp"]))
        print(" - max_road_ij_utilization_%:            {:6.2f} %".format(kpis["mx"]["road_ij"]))
        print(" - max_road_jh_utilization_%:            {:6.2f} %".format(kpis["mx"]["road_jh"]))
        print(" - max_staff_utilization_%:              {:6.2f} %".format(kpis["mx"]["staff"]))
        print(" - max_ccp_ambulance_utilization_%:      {:6.2f} %".format(kpis["mx"]["ccp_amb"]))
        print(" - max_hospital_ambulance_utilization_%: {:6.2f} %".format(kpis["mx"]["hosp_amb"]))
    # ---- B&BC 演算法統計 ---------------------------------------------------
    st = summary["bbc_stats"]
    print("-" * 50)
    print(" - B&BC ALGORITHM STATISTICS:")
    print(f" - solver_status:        {st['solver_status']}")
    print(f" - multi_cut:            {st['multi_cut']}")
    print(f" - total_cuts:           {st['cuts_added']}")
    print(f" - seed_cuts:            {st['seed_cuts_added']} (root seed {st['root_seed_iters_done']}/{st['root_seed_iters']})")
    print(f" - seeded_LB:            {st['root_seed_lb']}")
    print(f" - root_seed_stop:       {st['root_seed_stop_reason']} ({st['root_seed_time']:.2f} s)")
    print(f" - lazy_cuts:            {st['lazy_cuts_added']}")
    print(f" - user_cuts:            {st['user_cuts_added']} (root rounds {st['root_cut_rounds_done']}/{st['root_cut_rounds']})")
    print(f" - oracle_solves:        {st['oracle_solves']}")
    print(f" - incumbent_evals:      {st['incumbent_evals']}")
    print(f" - callback_time:        {st['callback_time']:.2f} s")
    print(f" - master_nodes:         {master.NodeCount:.0f}")
    print(f" - wall_time_total:      {time.time() - wall_start:.2f} s")
    print("=" * 50)

    return master, summary


if __name__ == "__main__":
    run_mcvar_model()
