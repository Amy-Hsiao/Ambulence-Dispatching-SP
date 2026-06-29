import time

import gurobipy as gp
from gurobipy import GRB

import config
import logging_utils
import model_core
import vss_evpi


def sp_callback(model, where):
    """Print progress on new best UB or every 10 seconds."""
    if where == GRB.Callback.MIP:
        current_time = time.time()
        if not hasattr(model._cb_data, "last_print_time"):
            model._cb_data.last_print_time = current_time
            model._cb_data.best_ub = float("inf")

        obj_bst = model.cbGet(GRB.Callback.MIP_OBJBST)
        obj_bnd = model.cbGet(GRB.Callback.MIP_OBJBND)

        if obj_bst < GRB.INFINITY and abs(obj_bst) > 1e-6:
            gap = abs(obj_bst - obj_bnd) / abs(obj_bst) * 100
        else:
            gap = float("inf")

        found_new_best = obj_bst < model._cb_data.best_ub
        time_elapsed = current_time - model._cb_data.last_print_time

        if found_new_best or time_elapsed >= config.SP_PROGRESS_INTERVAL_SEC:
            runtime = model.cbGet(GRB.Callback.RUNTIME)
            print(
                f"[Time: {runtime:.1f}s] Best LB: {obj_bnd:12.2f} | "
                f"Best UB: {obj_bst:12.2f} | Gap: {gap:6.2f}%"
            )
            model._cb_data.last_print_time = current_time
            if found_new_best:
                model._cb_data.best_ub = obj_bst


def run_sp_model(scenario_size=None, sample_ratio=None, time_limit=None, mip_gap=None):
    scenario_size = config.SP_SCENARIO_SIZE if scenario_size is None else scenario_size
    sample_ratio = config.SP_SAMPLE_RATIO if sample_ratio is None else sample_ratio
    time_limit = config.SP_TIME_LIMIT if time_limit is None else time_limit
    mip_gap = config.SP_MIP_GAP if mip_gap is None else mip_gap

    log_path = logging_utils.build_sp_log_path(scenario_size, sample_ratio, time_limit, mip_gap)
    with logging_utils.tee_output(log_path):
        return _run_sp_model(scenario_size, sample_ratio, time_limit, mip_gap)


def _run_sp_model(scenario_size, sample_ratio, time_limit, mip_gap):
    instance = config.generate_data(sample_ratio=sample_ratio)
    sets = instance["sets"]
    I           = sets["I"]
    J           = sets["J"]
    H           = sets["H"]
    L           = sets["L"]
    L_transfer  = sets["L_transfer"]
    T           = sets["T"]
    S_selected  = sets["S"] if scenario_size is None else sets["S"][:scenario_size]

    logging_utils.print_run_metadata(
        "SP",
        instance,
        (
            ("scenario_size_used", len(S_selected)),
            ("scenario_size_request", "ALL" if scenario_size is None else scenario_size),
            ("time_limit", time_limit),
            ("mip_gap", mip_gap),
        ),
    )

    params      = instance["deterministic_parameters"]
    scenario_data = instance["scenario_data"]
    cap_ij      = instance["road_capacity"]["cap_ij"]
    cap_jh      = instance["road_capacity"]["cap_jh"]
    cost_ij     = instance["transport_cost"]["cost_ij"]
    cost_jh     = instance["transport_cost"]["cost_jh"]

    # Normalize probabilities for the selected subset
    raw_probs   = {s: scenario_data["probability"][s] for s in S_selected}
    total_prob  = sum(raw_probs.values())
    norm_probs  = {s: p / total_prob for s, p in raw_probs.items()}

    # Wrap selected scenario data for model_core
    rp_sd = {
        "demand":                      {s: scenario_data["demand"][s]                      for s in S_selected},
        "road_availability_ij":        {s: scenario_data["road_availability_ij"][s]        for s in S_selected},
        "road_availability_jh":        {s: scenario_data["road_availability_jh"][s]        for s in S_selected},
        "hospital_receiving_capacity": {s: scenario_data["hospital_receiving_capacity"][s] for s in S_selected},
    }

    # ------------------------------------------------------------------ #
    # RP — SP extensive form                                               #
    # ------------------------------------------------------------------ #
    model, v = model_core.build_gurobi_model(
        I, J, H, L, L_transfer, T, S_selected,
        params, rp_sd, norm_probs,
        cap_ij, cap_jh, cost_ij, cost_jh,
        model_name="SP_RP_Model",
        time_limit=time_limit,
        mip_gap=mip_gap,
    )
    X, V, U, Y = v["X"], v["V"], v["U"], v["Y"]
    FI, FO, RM, REG, TRT, WAT = (
        v["FI"], v["FO"], v["RM"], v["REG"], v["TRT"], v["WAT"],
    )

    class CallbackData:
        pass
    model._cb_data = CallbackData()

    print("=" * 50)
    print("\nOptimizing SP Model (RP)...\n")
    model.optimize(sp_callback)

    if (model.status == GRB.OPTIMAL or model.status == GRB.TIME_LIMIT) and model.SolCount > 0:
        rp_best_ub = model.ObjVal
        rp_best_lb = model.ObjBound
        rp_gap     = model.MIPGap * 100

        def safe_div(num, den):
            return (num / den * 100) if den > 1e-6 else 0.0

        total_demand = sum(
            norm_probs[s] * scenario_data["demand"][s][t][i].get(l, 0)
            for s in S_selected for t in T for i in I for l in L
        )
        tot_FI = sum(
            norm_probs[s] * FI[s, i, j, l, t].X
            for s in S_selected for i in I for j in J for l in L for t in T
        )
        tot_FO = sum(
            norm_probs[s] * FO[s, j, h, l, t].X
            for s in S_selected for j in J for h in H for l in L_transfer for t in T
        )
        tot_RM = sum(
            norm_probs[s] * RM[s, i, l, t].X
            for s in S_selected for i in I for l in L for t in T
        )
        tot_WAT = sum(
            norm_probs[s] * WAT[s, j, l, t].X
            for s in S_selected for j in J for l in L_transfer for t in T
        )

        max_ccp_util = 0.0
        for s in S_selected:
            for j in J:
                for l in L:
                    cap = params["ccp_physical_capacity_by_severity"][l] * X[j].X
                    for t in T:
                        used = TRT[s, j, l, t].X + (WAT[s, j, l, t].X if l in L_transfer else 0)
                        max_ccp_util = max(max_ccp_util, safe_div(used, cap))

        max_hosp_util = 0.0
        for s in S_selected:
            for h in H:
                for t in T:
                    cap  = scenario_data["hospital_receiving_capacity"][s][h][t]
                    used = sum(FO[s, j, h, l, t].X for j in J for l in L_transfer)
                    max_hosp_util = max(max_hosp_util, safe_div(used, cap))

        max_road_ij_util = 0.0
        for s in S_selected:
            for i in I:
                for j in J:
                    for t in T:
                        cap  = cap_ij[i][j] * scenario_data["road_availability_ij"][s][i][j][t] * X[j].X
                        used = sum(FI[s, i, j, l, t].X for l in L)
                        max_road_ij_util = max(max_road_ij_util, safe_div(used, cap))

        max_road_jh_util = 0.0
        for s in S_selected:
            for j in J:
                for h in H:
                    for t in T:
                        cap  = cap_jh[j][h] * scenario_data["road_availability_jh"][s][j][h][t] * X[j].X
                        used = sum(FO[s, j, h, l, t].X for l in L_transfer)
                        max_road_jh_util = max(max_road_jh_util, safe_div(used, cap))

        max_staff_util = 0.0
        for s in S_selected:
            for j in J:
                cap = V[j].X
                for t in T:
                    used = sum(
                        TRT[s, j, l, t].X / params["staff_treatment_rate_by_severity"][l]
                        for l in L
                    )
                    max_staff_util = max(max_staff_util, safe_div(used, cap))

        max_ccp_amb_util = 0.0
        for s in S_selected:
            for j in J:
                cap = params["ccp_ambulance_casualty_capacity"] * U[j].X
                for t in T:
                    used = sum(FI[s, i, j, l, t].X for i in I for l in L_transfer)
                    max_ccp_amb_util = max(max_ccp_amb_util, safe_div(used, cap))

        max_hosp_amb_util = 0.0
        for s in S_selected:
            for h in H:
                cap = params["hospital_ambulance_casualty_capacity"] * params["hospital_ambulance_fleet"][h]
                for t in T:
                    used = sum(FO[s, j, h, l, t].X for j in J for l in L_transfer)
                    max_hosp_amb_util = max(max_hosp_amb_util, safe_div(used, cap))

        summary = vss_evpi.compute_vss_evpi(
            instance     = instance,
            S_selected   = S_selected,
            rp_best_lb   = rp_best_lb,
            rp_best_ub   = rp_best_ub,
            rp_gap       = rp_gap,
            time_limit   = time_limit,
            mip_gap      = mip_gap,
        )

        def fmt_pct(value):
            return "NA" if value is None else f"{value:.4f} %"

        print("\n" + "=" * 50)
        print("SP MODEL (RP) RESULT SUMMARY")
        print(" ")
        print(f" - Disaster Areas: {len(I)}")
        print(f" - Candidate CCPs: {len(J)}")
        print(f" - Hospitals: {len(H)}")
        print(f" - Scenarios: {len(S_selected)}")
        print(f" - Time Period: {len(T)}")
        print(f" - Objective Value:     {rp_best_ub:.2f}")
        print(f" - CPU Time:            {model.Runtime:.2f} s")
        print(f" - num_vars:            {model.NumVars:d}")
        print(f" - num_constrs:         {model.NumConstrs:d}")
        print(f" - Nodes:               {model.NodeCount:.0f}")
        print(f" - Iteration:           {model.IterCount:.0f} (Simplex iterations)")
        print(f" - Best UB (Objective): {rp_best_ub:.2f}")
        print(f" - Best LB (Bound):     {rp_best_lb:.2f}")
        print(f" - Final Gap:           {rp_gap:.4f}%")
        print(f" - VSS(%)    = {fmt_pct(summary['VSS_pct'])}")
        print(f" - EVPI(%)   = {fmt_pct(summary['EVPI_pct'])}")
        print("-" * 50)
        print(" - First-stage decisions (Here and Now):")
        for j in J:
            if X[j].X > 0.5:
                supply = sum(Y[h, j].X for h in H)
                print(
                    f"   CCP {j:4s} -> X: 1, Staff(V): {V[j].X:2.0f}, "
                    f"Amb(U): {U[j].X:2.0f}, MedicalSupply(Y): {supply:.2f}"
                )
        print("-" * 50)
        print(" - Expected KPIs (probability-weighted across scenarios):")
        print(" - total_demand:                  {:.2f}".format(total_demand))
        print(" - total_transported_to_ccp (FI): {:.2f}".format(tot_FI))
        print(" - total_transferred_to_hospital (FO): {:.2f}".format(tot_FO))
        print(" - total_remaining_disaster_area (RM): {:.2f} (all periods summed)".format(tot_RM))
        print(" - total_waiting_at_ccp (WAT):         {:.2f} (all periods summed)".format(tot_WAT))
        print("-" * 50)
        print(" - max_ccp_utilization_%:                {:6.2f} %".format(max_ccp_util))
        print(" - max_hospital_utilization_%:           {:6.2f} %".format(max_hosp_util))
        print(" - max_road_ij_utilization_%:            {:6.2f} %".format(max_road_ij_util))
        print(" - max_road_jh_utilization_%:            {:6.2f} %".format(max_road_jh_util))
        print(" - max_staff_utilization_%:              {:6.2f} %".format(max_staff_util))
        print(" - max_ccp_ambulance_utilization_%:      {:6.2f} %".format(max_ccp_amb_util))
        print(" - max_hospital_ambulance_utilization_%: {:6.2f} %".format(max_hosp_amb_util))
        print("=" * 50)
        return model, summary

    if model.status == GRB.INFEASIBLE:
        print("MODEL IS INFEASIBLE.")
        return None, None

    print(f"Optimization ended with status {model.status}")
    return None, None


if __name__ == "__main__":
    run_sp_model()
