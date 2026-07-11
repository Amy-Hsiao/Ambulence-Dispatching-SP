"""
benders bbc.py — Multi-cut Branch-and-Benders-Cut 入口（Phase 5：正式引擎）。

介面與 `extensive form.py` 完全相同：run_sp_model(...) -> (model, summary)，
回傳的 model 為 Benders master（runner 讀取 NumVars/NodeCount/IterCount 與
X/V/U/Y 變數值），summary 為 vss_evpi 的結果 dict（另附 summary["bbc_stats"]）。

輸出契約：
* console/log 的 RESULT SUMMARY 與 extensive form 同格式（含相同的欄位標籤，
  讓 batch runner 的 log 正則照常解析），之後加印一段 B&BC 演算法統計。
* log 檔名以 BBC_ 開頭，寫入專案根 logs/（runner 會再移入子資料夾）。
* num_vars / num_constrs / Nodes / Iteration 為 master 的數值（extensive form
  的對應值是完整模型；兩引擎的這幾欄語意不同，論文表格中需註明）。

注意：summary 的一階解以 result["first_stage"]（oracle 重評後的最佳解）為準；
master 最終 incumbent 理論上可能與其不同（機率極低，差異在 gap 容差內）。
"""
import sys
import time
from pathlib import Path

# ── bootstrap：讓 model core/ 內的模組可被 import ─────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MODEL_CORE_DIR = str(PROJECT_ROOT / "model core")
if _MODEL_CORE_DIR not in sys.path:
    sys.path.insert(0, _MODEL_CORE_DIR)

import gurobipy as gp  # noqa: E402
from gurobipy import GRB  # noqa: E402

import config  # noqa: E402
import logging_utils  # noqa: E402
import extensive_form_core as model_core  # noqa: E402
import vss_evpi  # noqa: E402
import lshaped_core  # noqa: E402


def _build_bbc_log_path(scenario_size, sample_ratio, time_limit, mip_gap) -> Path:
    """與 build_sp_log_path 相同命名規則，前綴改 BBC_（沿用 logging_utils 工具）。"""
    used = "ALL" if scenario_size is None else scenario_size
    base_name = (
        f"BBC_seed{config.MASTER_SEED}"
        f"_scen{config.SCENARIOS}"
        f"_used{used}"
        f"_period{config.TIME_PERIODS}"
        f"_sample{logging_utils._format_value(sample_ratio)}"
        f"_D{logging_utils._format_value(config.DEMAND_MULTIPLIER)}"
        f"_R{logging_utils._format_value(config.ROAD_CAPACITY_MULTIPLIER)}"
        f"_H{logging_utils._format_value(config.HOSPITAL_CAPACITY_MULTIPLIER)}"
        f"_tl{logging_utils._format_value(time_limit)}"
        f"_gap{logging_utils._format_value(mip_gap)}"
    )
    return logging_utils._unique_log_path(base_name)


def _evaluate_kpis(instance, S_selected, norm_probs, best_fs, time_limit=300.0):
    """以固定一階解逐情境重解 recourse LP，計算與 extensive form 相同的 KPI。

    回傳 dict；任何情境解不出來時回傳 None（KPI 區塊將略過，不影響主結果）。
    """
    sets = instance["sets"]
    I, J, H = sets["I"], sets["J"], sets["H"]
    L, L_tr, T = sets["L"], sets["L_transfer"], sets["T"]
    params = instance["deterministic_parameters"]
    cap_ij = instance["road_capacity"]["cap_ij"]
    cap_jh = instance["road_capacity"]["cap_jh"]
    sd_full = instance["scenario_data"]

    def safe_div(num, den):
        return (num / den * 100) if den > 1e-6 else 0.0

    tot = {"FI": 0.0, "FO": 0.0, "RM": 0.0, "WAT": 0.0}
    mx = {k: 0.0 for k in
          ("ccp", "hosp", "road_ij", "road_jh", "staff", "ccp_amb", "hosp_amb")}

    for s in S_selected:
        sub_sd = {
            "demand":                      {s: sd_full["demand"][s]},
            "road_availability_ij":        {s: sd_full["road_availability_ij"][s]},
            "road_availability_jh":        {s: sd_full["road_availability_jh"][s]},
            "hospital_receiving_capacity": {s: sd_full["hospital_receiving_capacity"][s]},
        }
        m, v = model_core.build_gurobi_model(
            I, J, H, L, L_tr, T, [s],
            params, sub_sd, {s: 1.0},
            cap_ij, cap_jh,
            instance["transport_cost"]["cost_ij"],
            instance["transport_cost"]["cost_jh"],
            model_name=f"KPI[{s}]",
            time_limit=time_limit,
            mip_gap=1e-6,
            fixed_first_stage=best_fs,
        )
        m.setParam("OutputFlag", 0)
        m.optimize()
        if m.SolCount == 0:
            return None
        FI, FO, RM, TRT, WAT = v["FI"], v["FO"], v["RM"], v["TRT"], v["WAT"]
        p = norm_probs[s]

        tot["FI"]  += p * sum(FI[s, i, j, l, t].X for i in I for j in J for l in L for t in T)
        tot["FO"]  += p * sum(FO[s, j, h, l, t].X for j in J for h in H for l in L_tr for t in T)
        tot["RM"]  += p * sum(RM[s, i, l, t].X for i in I for l in L for t in T)
        tot["WAT"] += p * sum(WAT[s, j, l, t].X for j in J for l in L_tr for t in T)

        for j in J:
            for l in L:
                cap = params["ccp_physical_capacity_by_severity"][l] * best_fs["X"][j]
                for t in T:
                    used = TRT[s, j, l, t].X + (WAT[s, j, l, t].X if l in L_tr else 0)
                    mx["ccp"] = max(mx["ccp"], safe_div(used, cap))
        for h in H:
            for t in T:
                cap = sd_full["hospital_receiving_capacity"][s][h][t]
                used = sum(FO[s, j, h, l, t].X for j in J for l in L_tr)
                mx["hosp"] = max(mx["hosp"], safe_div(used, cap))
        for i in I:
            for j in J:
                for t in T:
                    cap = cap_ij[i][j] * sd_full["road_availability_ij"][s][i][j][t] * best_fs["X"][j]
                    used = sum(FI[s, i, j, l, t].X for l in L)
                    mx["road_ij"] = max(mx["road_ij"], safe_div(used, cap))
        for j in J:
            for h in H:
                for t in T:
                    cap = cap_jh[j][h] * sd_full["road_availability_jh"][s][j][h][t] * best_fs["X"][j]
                    used = sum(FO[s, j, h, l, t].X for l in L_tr)
                    mx["road_jh"] = max(mx["road_jh"], safe_div(used, cap))
        for j in J:
            capV = best_fs["V"][j]
            capU = params["ccp_ambulance_casualty_capacity"] * best_fs["U"][j]
            for t in T:
                usedV = sum(TRT[s, j, l, t].X / params["staff_treatment_rate_by_severity"][l] for l in L)
                usedU = sum(FI[s, i, j, l, t].X for i in I for l in L_tr)
                mx["staff"]   = max(mx["staff"],   safe_div(usedV, capV))
                mx["ccp_amb"] = max(mx["ccp_amb"], safe_div(usedU, capU))
        for h in H:
            cap = params["hospital_ambulance_casualty_capacity"] * params["hospital_ambulance_fleet"][h]
            for t in T:
                used = sum(FO[s, j, h, l, t].X for j in J for l in L_tr)
                mx["hosp_amb"] = max(mx["hosp_amb"], safe_div(used, cap))

        m.dispose()

    return {"tot": tot, "mx": mx}


def run_sp_model(scenario_size=None, sample_ratio=None, time_limit=None, mip_gap=None,
                 compute_kpis=True, compute_vss_evpi=True):
    scenario_size = config.SP_SCENARIO_SIZE if scenario_size is None else scenario_size
    sample_ratio = config.SP_SAMPLE_RATIO if sample_ratio is None else sample_ratio
    time_limit = config.SP_TIME_LIMIT if time_limit is None else time_limit
    mip_gap = config.SP_MIP_GAP if mip_gap is None else mip_gap

    log_path = _build_bbc_log_path(scenario_size, sample_ratio, time_limit, mip_gap)
    with logging_utils.tee_output(log_path):
        return _run(scenario_size, sample_ratio, time_limit, mip_gap,
                    compute_kpis, compute_vss_evpi)


def _run(scenario_size, sample_ratio, time_limit, mip_gap, compute_kpis,
         compute_vss_evpi):
    wall_start = time.time()
    instance = config.generate_data(sample_ratio=sample_ratio)
    sets = instance["sets"]
    I, J, H, T = sets["I"], sets["J"], sets["H"], sets["T"]
    S_selected = sets["S"] if scenario_size is None else sets["S"][:scenario_size]

    logging_utils.print_run_metadata(
        "SP-BBC (multi-cut Branch-and-Benders-Cut)",
        instance,
        (
            ("scenario_size_used", len(S_selected)),
            ("time_limit", time_limit),
            ("mip_gap", mip_gap),
            ("multi_cut", config.BENDERS_MULTI_CUT),
            ("root_seed_iters", getattr(config, "BENDERS_ROOT_SEED_ITERS", 0)),
            ("root_seed_adaptive", getattr(config, "BENDERS_ROOT_SEED_ADAPTIVE", True)),
            ("root_seed_stall_rounds", getattr(config, "BENDERS_ROOT_SEED_STALL_ROUNDS", "NA")),
            ("root_cut_rounds", getattr(config, "BENDERS_ROOT_CUT_ROUNDS", 0)),
            ("use_user_cuts", getattr(config, "BENDERS_USE_USER_CUTS", False)),
            ("ev_warm_start", getattr(config, "BENDERS_EV_WARM_START", True)),
            ("pareto_enabled", getattr(config, "BENDERS_PARETO_ENABLED", True)),
            ("mip_focus", getattr(config, "BENDERS_MIPFOCUS", "default")),
            ("heuristics", getattr(config, "BENDERS_HEURISTICS", "default")),
            ("x_branch_priority_enabled", getattr(config, "BENDERS_X_BRANCH_PRIORITY_ENABLED", False)),
            ("x_branch_priority", getattr(config, "BENDERS_X_BRANCH_PRIORITY", 0)),
        ),
    )

    print("=" * 50)
    print("\nOptimizing SP Model (RP) — B&BC engine...\n")
    result = lshaped_core.solve(
        instance, S_selected,
        time_limit=time_limit, mip_gap=mip_gap,
        method="bbc",
    )

    if result.get("best_ub") is None or result.get("first_stage") is None:
        print(f"B&BC did not produce a feasible solution (status={result.get('status')}).")
        return None, None

    master = result["master"]
    rp_best_ub = float(result["best_ub"])
    rp_best_lb = float(result["best_lb"]) if result.get("best_lb") is not None else float("-inf")
    rp_gap = float(result["gap_pct"]) if result.get("gap_pct") is not None else float("nan")
    best_fs = result["first_stage"]

    sd = instance["scenario_data"]
    raw_probs = {s: sd["probability"][s] for s in S_selected}
    total_prob = sum(raw_probs.values())
    norm_probs = {s: p / total_prob for s, p in raw_probs.items()}

    # ---- VSS / EVPI（與 extensive form 完全相同的呼叫，引擎無關）----------
    if compute_vss_evpi:
        summary = vss_evpi.compute_vss_evpi(
            instance=instance, S_selected=S_selected,
            rp_best_lb=rp_best_lb, rp_best_ub=rp_best_ub, rp_gap=rp_gap,
            time_limit=time_limit, mip_gap=mip_gap,
        )
    else:
        summary = {
            "VSS_pct": None, "EVPI_pct": None,
            "objective": rp_best_ub, "best_lb": rp_best_lb,
            "gap_pct": rp_gap, "first_stage": best_fs,
        }
    summary["bbc_stats"] = {
        "engine":               "bbc",
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
        "pareto_enabled":       result.get("pareto_enabled"),
        "parallel_oracles":     result.get("parallel_oracles"),
        "oracle_solves":        result.get("oracle_solves"),
        "incumbent_evals":      result.get("incumbent_evals"),
        "callback_time":        result.get("callback_time"),
        "solver_status":        result.get("status"),
        "runtime":              result.get("runtime"),
    }

    # ---- KPI（同 extensive form 的期望 KPI；固定 best_fs 逐情境重解）------
    kpis = None
    if compute_kpis:
        kpis = _evaluate_kpis(instance, S_selected, norm_probs, best_fs)

    total_demand = sum(
        norm_probs[s] * sd["demand"][s][t][i].get(l, 0)
        for s in S_selected for t in T for i in I for l in sets["L"]
    )

    def fmt_pct(value):
        return "NA" if value is None else f"{value:.4f} %"

    # ---- RESULT SUMMARY（欄位標籤與 extensive form 完全一致）--------------
    print("\n" + "=" * 50)
    print("SP MODEL (RP) RESULT SUMMARY")
    print(" ")
    print(f" - Engine: multi-cut Branch-and-Benders-Cut")
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
    print(f" - VSS(%)    = {fmt_pct(summary['VSS_pct'])}")
    print(f" - EVPI(%)   = {fmt_pct(summary['EVPI_pct'])}")
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
    # ---- B&BC 演算法統計（B&BC 特有；論文演算法章節用）---------------------
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
    run_sp_model()
