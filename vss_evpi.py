"""
vss_evpi.py  —  VSS and EVPI computation for the two-stage SP model.

Definitions (cost minimisation):
    RP   = SP extensive-form objective  (solved externally, passed in)
    EV   = deterministic model using probability-weighted average of random params
    EEV  = fix EV's first-stage solution, evaluate expected recourse over scenarios
    WS   = sum_s p_s * (optimal obj for scenario s as a deterministic problem)

    VSS  = EEV - RP          (value of the stochastic solution)
    EVPI = RP  - WS          (expected value of perfect information)

Theoretical ordering: WS <= RP <= EEV
"""
from __future__ import annotations

import time
from typing import Any

import gurobipy as gp
from gurobipy import GRB

import model_core


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #

def _make_callback():
    """Return a callback function that prints progress on new best or every 10 s."""
    class _State:
        last_print = time.time()
        best_ub = float("inf")

    state = _State()

    def _cb(model, where):
        if where != GRB.Callback.MIP:
            return
        now = time.time()
        obj_bst = model.cbGet(GRB.Callback.MIP_OBJBST)
        obj_bnd = model.cbGet(GRB.Callback.MIP_OBJBND)
        if obj_bst < GRB.INFINITY and abs(obj_bst) > 1e-9:
            gap = abs(obj_bst - obj_bnd) / abs(obj_bst) * 100
        else:
            gap = float("inf")
        found_new = obj_bst < state.best_ub
        if found_new or (now - state.last_print) >= 10.0:
            rt = model.cbGet(GRB.Callback.RUNTIME)
            print(
                f"  [Time: {rt:.1f}s] LB: {obj_bnd:12.2f} | "
                f"UB: {obj_bst:12.2f} | Gap: {gap:.2f}%"
            )
            state.last_print = now
            if found_new:
                state.best_ub = obj_bst

    return _cb


def _weighted_average(nested: dict, S: list[str], norm_probs: dict[str, float]) -> Any:
    """Recursively compute probability-weighted average over scenarios S."""
    first = nested[S[0]]
    if isinstance(first, dict):
        return {
            k: _weighted_average({s: nested[s][k] for s in S}, S, norm_probs)
            for k in first
        }
    return sum(norm_probs[s] * float(nested[s]) for s in S)


def _solve_sub(
    label: str,
    I, J, H, L, L_transfer, T, S,
    params, scenario_data, probabilities,
    cap_ij, cap_jh, cost_ij, cost_jh,
    time_limit: float,
    mip_gap: float,
    fixed_first_stage=None,
):
    """Build, solve, and return (best_lb, best_ub, gap, model, vars_dict)."""
    m, v = model_core.build_gurobi_model(
        I, J, H, L, L_transfer, T, S,
        params, scenario_data, probabilities,
        cap_ij, cap_jh, cost_ij, cost_jh,
        model_name=label,
        time_limit=time_limit,
        mip_gap=mip_gap,
        fixed_first_stage=fixed_first_stage,
    )
    m.optimize()

    feasible = m.SolCount > 0 and m.status in (GRB.OPTIMAL, GRB.TIME_LIMIT)
    if not feasible:
        return None, None, None, m, v

    best_ub = m.ObjVal
    best_lb = m.ObjBound
    gap     = m.MIPGap * 100
    return best_lb, best_ub, gap, m, v


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

def compute_vss_evpi(
    instance: dict[str, Any],
    S_selected: list[str],
    rp_best_lb: float,
    rp_best_ub: float,
    rp_gap: float,
    time_limit: float = 3600.0,
    mip_gap: float = 0.01,
) -> dict[str, Any]:
    """Compute EV, EEV, WS and derive VSS / EVPI.

    Parameters
    ----------
    instance      : output of config.generate_data()
    S_selected    : subset of scenario IDs used in the RP solve
    rp_best_lb/ub : already-solved RP bounds (BestBound / ObjVal)
    rp_gap        : RP MIPGap * 100
    """
    sets    = instance["sets"]
    I       = sets["I"]
    J       = sets["J"]
    H       = sets["H"]
    L       = sets["L"]
    L_tr    = sets["L_transfer"]
    T       = sets["T"]

    params     = instance["deterministic_parameters"]
    cap_ij     = instance["road_capacity"]["cap_ij"]
    cap_jh     = instance["road_capacity"]["cap_jh"]
    cost_ij    = instance["transport_cost"]["cost_ij"]
    cost_jh    = instance["transport_cost"]["cost_jh"]
    sd_full    = instance["scenario_data"]   # original full scenario data

    # ---- Normalize probabilities over S_selected --------------------- #
    raw_probs  = {s: sd_full["probability"][s] for s in S_selected}
    total_prob = sum(raw_probs.values())
    norm_probs = {s: p / total_prob for s, p in raw_probs.items()}

    # ------------------------------------------------------------------ #
    # EV — deterministic model using probability-weighted average data    #
    # ------------------------------------------------------------------ #
    ev_demand   = _weighted_average(sd_full["demand"],   S_selected, norm_probs)
    ev_road_ij  = _weighted_average(sd_full["road_availability_ij"],  S_selected, norm_probs)
    ev_road_jh  = _weighted_average(sd_full["road_availability_jh"],  S_selected, norm_probs)
    ev_hosp_cap = _weighted_average(sd_full["hospital_receiving_capacity"], S_selected, norm_probs)

    ev_det = {
        "demand":                      ev_demand,
        "road_availability_ij":        ev_road_ij,
        "road_availability_jh":        ev_road_jh,
        "hospital_receiving_capacity": ev_hosp_cap,
    }
    ev_sd    = model_core.wrap_det_scenario(ev_det, "EV")
    ev_probs = {"EV": 1.0}
    ev_S     = ["EV"]

    ev_lb, ev_ub, ev_gap, ev_m, ev_v = _solve_sub(
        "EV", I, J, H, L, L_tr, T, ev_S,
        params, ev_sd, ev_probs,
        cap_ij, cap_jh, cost_ij, cost_jh,
        time_limit, mip_gap,
    )

    # Extract EV first-stage solution
    ev_first_stage = None
    if ev_lb is not None:
        X_ev = ev_v["X"]
        V_ev = ev_v["V"]
        U_ev = ev_v["U"]
        Y_ev = ev_v["Y"]
        ev_first_stage = {
            "X": {j: round(X_ev[j].X) for j in J},
            "V": {j: round(V_ev[j].X) for j in J},
            "U": {j: round(U_ev[j].X) for j in J},
            "Y": {(h, j): round(Y_ev[h, j].X) for h in H for j in J},
        }

    # ------------------------------------------------------------------ #
    # EEV — fix EV first-stage, evaluate recourse over original scenarios #
    # ------------------------------------------------------------------ #
    eev_lb = eev_ub = eev_gap = None
    if ev_first_stage is not None:
        eev_sd = {
            "demand":                      {s: sd_full["demand"][s]                      for s in S_selected},
            "road_availability_ij":        {s: sd_full["road_availability_ij"][s]        for s in S_selected},
            "road_availability_jh":        {s: sd_full["road_availability_jh"][s]        for s in S_selected},
            "hospital_receiving_capacity": {s: sd_full["hospital_receiving_capacity"][s] for s in S_selected},
        }
        eev_lb, eev_ub, eev_gap, _, _ = _solve_sub(
            "EEV", I, J, H, L, L_tr, T, S_selected,
            params, eev_sd, norm_probs,
            cap_ij, cap_jh, cost_ij, cost_jh,
            time_limit, mip_gap,
            fixed_first_stage=ev_first_stage,
        )
    else:
        pass

    # ------------------------------------------------------------------ #
    # WS — per-scenario deterministic, probability-weighted average       #
    # ------------------------------------------------------------------ #
    ws_scenario_results: dict[str, dict] = {}
    ws_ub_weighted = 0.0
    ws_feasible    = True

    for s in S_selected:
        ws_s_det = {
            "demand":                      sd_full["demand"][s],
            "road_availability_ij":        sd_full["road_availability_ij"][s],
            "road_availability_jh":        sd_full["road_availability_jh"][s],
            "hospital_receiving_capacity": sd_full["hospital_receiving_capacity"][s],
        }
        ws_sd    = model_core.wrap_det_scenario(ws_s_det, s)
        ws_probs = {s: 1.0}
        ws_S     = [s]

        lb_s, ub_s, gap_s, _, _ = _solve_sub(
            f"WS[{s}]", I, J, H, L, L_tr, T, ws_S,
            params, ws_sd, ws_probs,
            cap_ij, cap_jh, cost_ij, cost_jh,
            time_limit, mip_gap,
        )

        ws_scenario_results[s] = {
            "best_lb": lb_s,
            "best_ub": ub_s,
            "gap":     gap_s,
            "prob":    norm_probs[s],
        }
        if ub_s is not None:
            ws_ub_weighted += norm_probs[s] * ub_s
        else:
            ws_feasible = False

    ws_ub_total = ws_ub_weighted if ws_feasible else None

    # ------------------------------------------------------------------ #
    # Derive VSS / EVPI                                                   #
    # ------------------------------------------------------------------ #
    warnings: list[str] = []

    def _pct(numerator, denominator, label):
        if denominator is None or abs(denominator) < 1e-9:
            warnings.append(f"{label}(%): RP_used is 0 or None — percentage undefined")
            return None
        return numerator / abs(denominator) * 100

    rp_used  = rp_best_ub
    eev_used = eev_ub
    ws_used  = ws_ub_total

    vss  = (eev_used - rp_used)     if (eev_used is not None) else None
    evpi = (rp_used  - ws_used)     if (ws_used  is not None) else None
    vss_pct  = _pct(vss,  rp_used, "VSS")  if vss  is not None else None
    evpi_pct = _pct(evpi, rp_used, "EVPI") if evpi is not None else None

    # Logic check: WS <= RP <= EEV
    if ws_used is not None and rp_used is not None and ws_used > rp_used + 1e-4:
        msg = (f"LOGIC WARNING: WS_used ({ws_used:.2f}) > RP_used ({rp_used:.2f}) — "
               "may be caused by MIP gap or time limit")
        warnings.append(msg)
    if eev_used is not None and rp_used is not None and eev_used < rp_used - 1e-4:
        msg = (f"LOGIC WARNING: EEV_used ({eev_used:.2f}) < RP_used ({rp_used:.2f}) — "
               "may be caused by MIP gap or time limit")
        warnings.append(msg)

    summary = {
        "RP":  {"best_lb": rp_best_lb,  "best_ub": rp_best_ub,  "gap": rp_gap},
        "EV":  {"best_lb": ev_lb,        "best_ub": ev_ub,        "gap": ev_gap,
                "first_stage": ev_first_stage},
        "EEV": {"best_lb": eev_lb,       "best_ub": eev_ub,       "gap": eev_gap},
        "WS":  {"best_ub_weighted": ws_ub_total,
                "scenarios": ws_scenario_results},
        "VSS":      vss,
        "EVPI":     evpi,
        "VSS_pct":  vss_pct,
        "EVPI_pct": evpi_pct,
        "used_bound": "BestUB",
        "warnings": warnings,
    }
    return summary


def print_vss_evpi_summary(summary: dict[str, Any]) -> None:
    """Pretty-print the VSS/EVPI summary dict."""
    print("\n" + "=" * 60)
    print("  VSS / EVPI SUMMARY")
    print("=" * 60)

    def _fmt(v, decimals=2):
        if v is None:
            return "NA"
        return f"{v:.{decimals}f}"

    rp  = summary["RP"]
    ev  = summary["EV"]
    eev = summary["EEV"]
    ws  = summary["WS"]

    print(f"  RP   BestLB={_fmt(rp['best_lb'])}  BestUB={_fmt(rp['best_ub'])}  Gap={_fmt(rp['gap'], 4)}%")
    print(f"  EV   BestLB={_fmt(ev['best_lb'])}  BestUB={_fmt(ev['best_ub'])}  Gap={_fmt(ev['gap'], 4)}%")
    print(f"  EEV  BestLB={_fmt(eev['best_lb'])}  BestUB={_fmt(eev['best_ub'])}  Gap={_fmt(eev['gap'], 4)}%")
    ws_total = ws.get("best_ub_weighted")
    print(f"  WS   Weighted_BestUB={_fmt(ws_total)}")
    print(f"  Per-scenario WS:")
    for s, res in ws["scenarios"].items():
        print(f"    {s}: LB={_fmt(res['best_lb'])}  UB={_fmt(res['best_ub'])}  "
              f"Gap={_fmt(res['gap'], 4)}%  p={res['prob']:.4f}")
    print("-" * 60)
    print(f"  VSS       = EEV - RP = {_fmt(summary['VSS'])}")
    print(f"  EVPI      = RP  - WS = {_fmt(summary['EVPI'])}")
    vss_pct  = summary["VSS_pct"]
    evpi_pct = summary["EVPI_pct"]
    print(f"  VSS(%)    = {_fmt(vss_pct, 4) if vss_pct  is not None else 'NA'} %")
    print(f"  EVPI(%)   = {_fmt(evpi_pct, 4) if evpi_pct is not None else 'NA'} %")
    print(f"  used_bound = {summary['used_bound']}")
    if summary["warnings"]:
        print("  WARNINGS:")
        for w in summary["warnings"]:
            print(f"    ! {w}")
    print("=" * 60)
