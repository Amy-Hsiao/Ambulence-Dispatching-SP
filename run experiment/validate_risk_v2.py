#!/usr/bin/env python3
"""
Plan/09 validation — SP + MCVaR + DRO (box / ellipsoidal / polyhedral, B&BC).

Default smoke test uses a reduced instance so it also runs under the
size-limited Gurobi license:
    python "run experiment/validate_risk_v2.py"

Checks:
    D1  evaluate_wmcvar (dual reformulation) matches primal brute force
        (phi swept over breakpoints, sup_p solved as primal LP/QCP) for all
        three ambiguity sets on random cases.
    D2  scope -> 0: DRO objective degenerates to MCVaR (solver level, box).
    D3  Conservativeness: DRO obj >= MCVaR obj for all three sets (solver
        level); WMCVaR nondecreasing in scope (unit level).
    D4  Box validity guard: epsilon_box > min p0 is rejected.
    D5  Incumbent UB consistency: best_ub == C1 + WMCVaR(Q) recomputed.
    D6  DRO-E engine cross-check: B&BC (MISOCP master + lazy cuts) matches
        classic L-shaped loop within combined gap.
    D7  Worst-case p stays inside the ambiguity set and sums to 1.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT / "model core"), str(PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config
import lshaped_core
import risk_core

SAMPLE_RATIO = 0.05      # 小 instance：I≈7, J=6, H=1（受限授權也能跑）
CCP_SAMPLE_SIZE = 6
TIME_LIMIT = 300.0
MIP_GAP = 0.01
ALPHA, LAM = 0.9, 0.5
BBC_KWARGS = dict(
    time_limit=TIME_LIMIT,
    mip_gap=MIP_GAP,
    root_seed_iters=5,
    root_cut_rounds=5,
    parallel_oracles=5,
    use_user_cuts=True,
    ev_warm_start=True,
    verbose=False,
)


def within_combined_gap(left_ub, left_gap_pct, right_ub, right_gap_pct):
    diff = abs(left_ub - right_ub)
    allowance = (
        abs(left_ub) * (left_gap_pct or 0.0) / 100.0
        + abs(right_ub) * (right_gap_pct or 0.0) / 100.0
        + 1e-4
    )
    return diff <= allowance, diff, allowance


def primal_wmcvar(q, p0, risk_cfg):
    """暴力法：φ 掃過 {q_s} 斷點；sup_p 以原始 LP/QCP（worst_case_distribution）解。"""
    alpha, lam = risk_cfg["alpha"], risk_cfg["lambda"]
    sup_mean = sum(
        risk_core.worst_case_distribution(q, p0, risk_cfg)[s] * q[s] for s in q
    )
    best = float("inf")
    for phi in set(q.values()):
        ell = {s: max(q[s] - phi, 0.0) for s in q}
        wp = risk_core.worst_case_distribution(ell, p0, risk_cfg)
        sup_tail = sum(wp[s] * ell[s] for s in q)
        val = lam * phi + (1 - lam) * sup_mean + lam / (1 - alpha) * sup_tail
        best = min(best, val)
    return best


def check_d1():
    rng = random.Random(909)
    for trial in range(30):
        n = rng.randint(3, 8)
        labels = [f"s{k}" for k in range(n)]
        raw = [rng.random() + 0.05 for _ in labels]
        tot = sum(raw)
        p0 = {s: w / tot for s, w in zip(labels, raw)}
        q = {s: rng.uniform(0, 1e6) for s in labels}
        alpha = rng.choice([0.0, 0.5, 0.8, 0.9])
        lam = rng.choice([0.0, 0.3, 0.5, 1.0])
        min_p = min(p0.values())
        cases = [
            ("dro_box", {"epsilon_box": rng.uniform(0.0, min_p)}),
            ("dro_ellipsoidal", {"a_e": rng.uniform(0.0, 0.2)}),
            ("dro_polyhedral", {"a_p": rng.uniform(0.0, 0.2)}),
        ]
        for rtype, kw in cases:
            cfg = risk_core.make_risk_cfg(rtype, alpha=alpha, lam=lam, **kw)
            got, _ = risk_core.evaluate_wmcvar(q, p0, cfg)
            want = primal_wmcvar(q, p0, cfg)
            if abs(got - want) > 1e-4 * max(1.0, abs(want)):
                return False, (
                    f"trial={trial} {rtype} alpha={alpha} lambda={lam} "
                    f"dual={got:.4f} primal={want:.4f}"
                )
    return True, "30 random cases x 3 sets: dual reformulation matches primal brute force"


def check_d4():
    p0 = {f"s{i}": 0.2 for i in range(5)}
    cfg = risk_core.make_risk_cfg("dro_box", alpha=0.9, lam=0.5, epsilon_box=0.5)
    try:
        risk_core.validate_risk_cfg_for_probs(cfg, p0)
        return False, "epsilon_box=0.5 > min p0=0.2 not rejected"
    except ValueError:
        return True, "epsilon_box > min p0 rejected as expected"


def check_d7(q, p0, risk_cfg, worst_p):
    tol = 1e-6
    if abs(sum(worst_p.values()) - 1.0) > tol:
        return False, f"worst_p sums to {sum(worst_p.values()):.8f}"
    if min(worst_p.values()) < -tol:
        return False, f"worst_p has negative entry {min(worst_p.values()):.2e}"
    rtype = risk_cfg["type"]
    if rtype == "dro_box":
        dev = max(abs(worst_p[s] - p0[s]) for s in p0)
        if dev > risk_cfg["epsilon_box"] + tol:
            return False, f"box dev {dev:.6f} > eps {risk_cfg['epsilon_box']}"
    elif rtype == "dro_ellipsoidal":
        a = risk_cfg["a_e"]
        norm2 = sum(((worst_p[s] - p0[s]) / a) ** 2 for s in p0) ** 0.5 if a > 0 else 0.0
        if norm2 > 1.0 + 1e-4:
            return False, f"ellipsoidal ||eps||2 = {norm2:.6f} > 1"
    elif rtype == "dro_polyhedral":
        a = risk_cfg["a_p"]
        norm1 = sum(abs(worst_p[s] - p0[s]) / a for s in p0) if a > 0 else 0.0
        if norm1 > 1.0 + 1e-4:
            return False, f"polyhedral ||eps||1 = {norm1:.6f} > 1"
    return True, "worst_p feasible (sum=1, p>=0, inside ambiguity set)"


def run_bbc(instance, S, risk_cfg, **overrides):
    kwargs = dict(BBC_KWARGS)
    kwargs.update(overrides)
    return lshaped_core.solve_bbc(instance, S, risk_cfg=risk_cfg, **kwargs)


def main():
    print("=" * 70)
    print("PLAN/09 VALIDATION - SP + MCVaR + DRO (B&BC)")
    print("=" * 70)
    print(f"sample_ratio={SAMPLE_RATIO} ccp={CCP_SAMPLE_SIZE} "
          f"time_limit={TIME_LIMIT} mip_gap={MIP_GAP} alpha={ALPHA} lambda={LAM}")

    results = []

    ok, detail = check_d1()
    results.append(("D1 dual reformulation == primal brute force (3 sets)", ok, detail))

    ok, detail = check_d4()
    results.append(("D4 box epsilon guard", ok, detail))

    instance = config.generate_data(
        sample_ratio=SAMPLE_RATIO, ccp_sample_size=CCP_SAMPLE_SIZE
    )
    S = instance["sets"]["S"][:5]
    p0 = lshaped_core._normalize_probabilities(instance, S)

    print("-" * 70)
    print("solving: MCVaR baseline (0.9, 0.5)")
    mc = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=ALPHA, lam=LAM))

    print("solving: DRO box eps=1e-9 (degeneracy check)")
    box0 = run_bbc(instance, S, risk_core.make_risk_cfg(
        "dro_box", alpha=ALPHA, lam=LAM, epsilon_box=1e-9))
    ok, diff, allowance = within_combined_gap(
        box0["best_ub"], box0["gap_pct"], mc["best_ub"], mc["gap_pct"]
    )
    results.append((
        "D2 scope->0 degenerates to MCVaR (solver level)",
        ok,
        f"DRO-B(eps=1e-9)={box0['best_ub']:.4f} MCVaR={mc['best_ub']:.4f} "
        f"diff={diff:.4f} allowance={allowance:.4f}",
    ))

    print("solving: DRO box / ellipsoidal / polyhedral (default scopes)")
    dro_runs = {}
    for rtype, kw in [
        ("dro_box", {"epsilon_box": 0.05}),
        ("dro_ellipsoidal", {"a_e": 0.05}),
        ("dro_polyhedral", {"a_p": 0.10}),
    ]:
        cfg = risk_core.make_risk_cfg(rtype, alpha=ALPHA, lam=LAM, **kw)
        dro_runs[rtype] = (cfg, run_bbc(instance, S, cfg))

    ok_all, msgs = True, []
    for rtype, (cfg, res) in dro_runs.items():
        allowance = (
            abs(res["best_ub"]) * (res["gap_pct"] or 0.0) / 100.0
            + abs(mc["best_ub"]) * (mc["gap_pct"] or 0.0) / 100.0 + 1e-4
        )
        ok = res["best_ub"] >= mc["best_ub"] - allowance
        ok_all = ok_all and ok
        msgs.append(f"{rtype}={res['best_ub']:.2f}")
    # 單調性（unit level，固定 Q 向量）
    q_fix = dro_runs["dro_box"][1]["scenario_q"]
    small = risk_core.evaluate_wmcvar(
        q_fix, p0, risk_core.make_risk_cfg("dro_box", alpha=ALPHA, lam=LAM,
                                           epsilon_box=0.01))[0]
    large = risk_core.evaluate_wmcvar(
        q_fix, p0, risk_core.make_risk_cfg("dro_box", alpha=ALPHA, lam=LAM,
                                           epsilon_box=0.05))[0]
    ok_mono = small <= large + 1e-6
    results.append((
        "D3 DRO >= MCVaR and WMCVaR nondecreasing in scope",
        ok_all and ok_mono,
        f"MCVaR={mc['best_ub']:.2f}; " + "; ".join(msgs)
        + f"; box WMCVaR(0.01)={small:.2f} <= WMCVaR(0.05)={large:.2f}",
    ))

    ok_all, msgs = True, []
    for rtype, (cfg, res) in dro_runs.items():
        recomputed = (
            lshaped_core._first_stage_cost(instance, res["first_stage"])
            + risk_core.second_stage_objective_from_Q(res["scenario_q"], p0, cfg)
        )
        diff = abs(recomputed - res["best_ub"])
        ok = diff <= 1e-6 * max(1.0, abs(res["best_ub"]))
        ok_all = ok_all and ok
        msgs.append(f"{rtype} diff={diff:.2e}")
    results.append((
        "D5 incumbent UB == C1 + WMCVaR(Q) recomputed (3 sets)",
        ok_all, "; ".join(msgs),
    ))

    print("solving: DRO ellipsoidal via classic loop (engine cross-check)")
    cfg_e = dro_runs["dro_ellipsoidal"][0]
    ell_classic = lshaped_core.solve_classic(
        instance, S, time_limit=TIME_LIMIT, mip_gap=MIP_GAP,
        max_iterations=2000, verbose=False, risk_cfg=cfg_e,
    )
    ell_bbc = dro_runs["dro_ellipsoidal"][1]
    ok, diff, allowance = within_combined_gap(
        ell_bbc["best_ub"], ell_bbc["gap_pct"],
        ell_classic["best_ub"], ell_classic["gap_pct"],
    )
    results.append((
        "D6 DRO-E: B&BC (MISOCP master) matches classic L-shaped",
        ok,
        f"BBC={ell_bbc['best_ub']:.4f} classic={ell_classic['best_ub']:.4f} "
        f"diff={diff:.4f} allowance={allowance:.4f}",
    ))

    ok_all, msgs = True, []
    for rtype, (cfg, res) in dro_runs.items():
        _, detail = risk_core.evaluate_wmcvar(res["scenario_q"], p0, cfg)
        ok, msg = check_d7(res["scenario_q"], p0, cfg, detail["worst_p"])
        ok_all = ok_all and ok
        msgs.append(f"{rtype}: {msg}")
    results.append(("D7 worst-case p feasibility (3 sets)", ok_all, "; ".join(msgs)))

    print("-" * 70)
    passed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"       {detail}")
        passed += int(ok)
    print("-" * 70)
    print(
        f"{passed}/{len(results)} checks passed."
        + ("  Plan/09 validation passed." if passed == len(results)
           else "  Plan/09 validation FAILED.")
    )
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
