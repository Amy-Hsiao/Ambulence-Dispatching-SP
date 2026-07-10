#!/usr/bin/env python3
"""
Plan/08 validation — SP + MCVaR (B&BC).

Default smoke test uses a reduced instance so it also runs under the
size-limited Gurobi license:
    python "run experiment/validate_risk_v1.py"

Checks:
    R1  evaluate_mcvar matches brute-force CVaR minimization (unit test, no solver).
    R2  make_risk_cfg rejects invalid alpha / lambda; single-cut + risk raises.
    R3  MCVaR with lambda=0 matches plain SP B&BC (same instance/seed).
    R4  MCVaR with alpha=0, lambda=1 matches plain SP B&BC (CVaR_0 = E[Q]).
    R5  Objective is nondecreasing in lambda (alpha fixed) and in alpha (lambda fixed).
    R6  Incumbent UB consistency: best_ub == C1(fs*) + MCVaR(Q(fs*)) exactly.
    R7  Risk master carries phi/ell variables; SP master does not (regression).
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


def one_sided_allowance(low, low_gap_pct, high, high_gap_pct):
    """low ≤ high + allowance 的單邊容差（兩邊 gap 皆計入）。"""
    return (
        abs(low) * (low_gap_pct or 0.0) / 100.0
        + abs(high) * (high_gap_pct or 0.0) / 100.0
        + 1e-4
    )


def brute_force_mcvar(q, p, alpha, lam):
    """暴力法：φ 的最佳值必在 {q_s} 斷點上，逐一掃描取最小。"""
    exp_q = sum(p[s] * q[s] for s in q)
    best_cvar = min(
        phi + sum(p[s] * max(q[s] - phi, 0.0) for s in q) / (1.0 - alpha)
        for phi in q.values()
    )
    return (1.0 - lam) * exp_q + lam * best_cvar


def check_r1():
    rng = random.Random(2026)
    for trial in range(200):
        n = rng.randint(2, 12)
        labels = [f"s{k}" for k in range(n)]
        raw = [rng.random() + 1e-3 for _ in labels]
        tot = sum(raw)
        p = {s: w / tot for s, w in zip(labels, raw)}
        q = {s: rng.uniform(0, 1e6) for s in labels}
        alpha = rng.choice([0.0, 0.3, 0.5, 0.8, 0.9, 0.95])
        lam = rng.choice([0.0, 0.25, 0.5, 0.75, 1.0])
        got, _ = risk_core.evaluate_mcvar(q, p, alpha, lam)
        want = brute_force_mcvar(q, p, alpha, lam)
        if abs(got - want) > 1e-6 * max(1.0, abs(want)):
            return False, (
                f"trial={trial} alpha={alpha} lambda={lam} got={got:.6f} want={want:.6f}"
            )
    return True, "200 random (Q, p, alpha, lambda) cases match brute force"


def check_r2(instance, S):
    try:
        risk_core.make_risk_cfg("mcvar", alpha=1.0)
        return False, "alpha=1.0 not rejected"
    except ValueError:
        pass
    try:
        risk_core.make_risk_cfg("mcvar", lam=1.5)
        return False, "lambda=1.5 not rejected"
    except ValueError:
        pass
    try:
        lshaped_core.solve_bbc(
            instance, S, multi_cut=False,
            risk_cfg=risk_core.make_risk_cfg("mcvar"),
            **{k: v for k, v in BBC_KWARGS.items()},
        )
        return False, "single-cut + risk_cfg not rejected"
    except ValueError:
        pass
    return True, "invalid alpha / lambda / single-cut all rejected"


def run_bbc(instance, S, risk_cfg=None):
    return lshaped_core.solve_bbc(instance, S, risk_cfg=risk_cfg, **BBC_KWARGS)


def main():
    print("=" * 70)
    print("PLAN/08 VALIDATION - SP + MCVaR (B&BC)")
    print("=" * 70)
    print(f"sample_ratio={SAMPLE_RATIO} ccp={CCP_SAMPLE_SIZE} "
          f"time_limit={TIME_LIMIT} mip_gap={MIP_GAP}")

    results = []

    ok, detail = check_r1()
    results.append(("R1 evaluate_mcvar matches brute force", ok, detail))

    instance = config.generate_data(
        sample_ratio=SAMPLE_RATIO, ccp_sample_size=CCP_SAMPLE_SIZE
    )
    S = instance["sets"]["S"][:5]

    ok, detail = check_r2(instance, S)
    results.append(("R2 invalid configs rejected", ok, detail))

    print("-" * 70)
    print("solving: SP baseline (risk_cfg=None)")
    sp = run_bbc(instance, S, risk_cfg=None)

    print("solving: MCVaR lambda=0 (alpha=0.9)")
    m_l0 = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=0.9, lam=0.0))
    ok, diff, allowance = within_combined_gap(
        m_l0["best_ub"], m_l0["gap_pct"], sp["best_ub"], sp["gap_pct"]
    )
    results.append((
        "R3 lambda=0 reduces to SP",
        ok,
        f"MCVaR(l=0)={m_l0['best_ub']:.4f} SP={sp['best_ub']:.4f} "
        f"diff={diff:.4f} allowance={allowance:.4f}",
    ))

    print("solving: MCVaR alpha=0, lambda=1")
    m_a0l1 = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=0.0, lam=1.0))
    ok, diff, allowance = within_combined_gap(
        m_a0l1["best_ub"], m_a0l1["gap_pct"], sp["best_ub"], sp["gap_pct"]
    )
    results.append((
        "R4 alpha=0, lambda=1 reduces to SP (CVaR_0 = E[Q])",
        ok,
        f"MCVaR(a=0,l=1)={m_a0l1['best_ub']:.4f} SP={sp['best_ub']:.4f} "
        f"diff={diff:.4f} allowance={allowance:.4f}",
    ))

    print("solving: MCVaR (0.9, 0.3) / (0.9, 0.7) / (0.5, 0.5) / (0.9, 0.5)")
    m_93 = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=0.9, lam=0.3))
    m_97 = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=0.9, lam=0.7))
    m_55 = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=0.5, lam=0.5))
    m_95 = run_bbc(instance, S, risk_core.make_risk_cfg("mcvar", alpha=0.9, lam=0.5))

    allow_lam = one_sided_allowance(
        m_93["best_ub"], m_93["gap_pct"], m_97["best_ub"], m_97["gap_pct"]
    )
    ok_lam = m_93["best_ub"] <= m_97["best_ub"] + allow_lam
    allow_alp = one_sided_allowance(
        m_55["best_ub"], m_55["gap_pct"], m_95["best_ub"], m_95["gap_pct"]
    )
    ok_alp = m_55["best_ub"] <= m_95["best_ub"] + allow_alp
    results.append((
        "R5 objective nondecreasing in lambda and alpha",
        ok_lam and ok_alp,
        f"lam: {m_93['best_ub']:.4f} <= {m_97['best_ub']:.4f} (+{allow_lam:.4f})  "
        f"alpha: {m_55['best_ub']:.4f} <= {m_95['best_ub']:.4f} (+{allow_alp:.4f})",
    ))

    cfg_95 = risk_core.make_risk_cfg("mcvar", alpha=0.9, lam=0.5)
    recomputed = (
        lshaped_core._first_stage_cost(instance, m_95["first_stage"])
        + risk_core.second_stage_objective_from_Q(
            m_95["scenario_q"],
            lshaped_core._normalize_probabilities(instance, S),
            cfg_95,
        )
    )
    diff = abs(recomputed - m_95["best_ub"])
    ok = diff <= 1e-6 * max(1.0, abs(m_95["best_ub"]))
    results.append((
        "R6 incumbent UB == C1 + MCVaR(Q) recomputed",
        ok,
        f"best_ub={m_95['best_ub']:.6f} recomputed={recomputed:.6f} diff={diff:.2e}",
    ))

    risk_vars = [v.VarName for v in m_95["master"].getVars()
                 if v.VarName.startswith(("phi_var", "ell["))]
    sp_risk_vars = [v.VarName for v in sp["master"].getVars()
                    if v.VarName.startswith(("phi_var", "ell["))]
    ok = len(risk_vars) == 1 + len(S) and len(sp_risk_vars) == 0
    results.append((
        "R7 risk layer only present when risk_cfg is set",
        ok,
        f"risk master phi/ell vars={len(risk_vars)} (expected {1 + len(S)}); "
        f"SP master risk vars={len(sp_risk_vars)} (expected 0)",
    ))

    print("-" * 70)
    passed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"       {detail}")
        passed += int(ok)
    print("-" * 70)
    print(
        f"{passed}/{len(results)} checks passed."
        + ("  Plan/08 validation passed." if passed == len(results)
           else "  Plan/08 validation FAILED.")
    )
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
