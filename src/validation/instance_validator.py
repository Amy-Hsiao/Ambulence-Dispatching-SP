"""Pre-solve validation for SP instances."""

from __future__ import annotations

from typing import Any

from src.data.schema import MINOR, REQUIRED_SETS, hosp_cap, periods, ss, u, w, xi


def _is_int_value(value: float, tol: float = 1e-9) -> bool:
    return abs(float(value) - round(float(value))) <= tol


def validate_instance(instance: dict[str, Any], tol: float = 1e-9) -> dict[str, Any]:
    errors: list[str] = []
    sets = instance.get("sets", {})
    for name in REQUIRED_SETS:
        if name not in sets or not sets[name]:
            errors.append(f"missing or empty set {name}")
    if errors:
        return {"passed": False, "errors": errors}

    I, J, H, L, L_Amb, S = sets["I"], sets["J"], sets["H"], sets["L"], sets["L_Amb"], sets["S"]
    T = periods(instance)
    if set(L_Amb) - set(L):
        errors.append("L_Amb must be a subset of L")
    if MINOR in set(L_Amb):
        errors.append("minor must not be in L_Amb")

    p_s = instance.get("p_s", {})
    if set(p_s) != set(S):
        errors.append("p_s keys must match S")
    if abs(sum(float(p_s.get(s, 0)) for s in S) - 1.0) > tol:
        errors.append("sum_s p_s must equal 1")
    for s in S:
        if float(p_s.get(s, -1)) < -tol:
            errors.append(f"p_s[{s}] must be nonnegative")

    sec = instance.get("second_stage", {})
    for i in I:
        for j in J:
            if sec["c_ij"][i][j] < -tol:
                errors.append(f"c_ij[{i},{j}] must be nonnegative")
            for t in T:
                for s in S:
                    val = u(instance, i, j, t, s)
                    if val < -tol or val > 1 + tol:
                        errors.append(f"u_ijts[{i},{j},{t},{s}] must be in [0,1]")
    for j in J:
        for h in H:
            if sec["c_jh"][j][h] < -tol:
                errors.append(f"c_jh[{j},{h}] must be nonnegative")
            for t in T:
                for s in S:
                    val = w(instance, j, h, t, s)
                    if val < -tol or val > 1 + tol:
                        errors.append(f"w_jhts[{j},{h},{t},{s}] must be in [0,1]")

    for i in I:
        for l in L:
            for t in T:
                for s in S:
                    val = xi(instance, i, l, t, s)
                    if val < -tol:
                        errors.append(f"xi_ilts[{i},{l},{t},{s}] must be nonnegative")
                    if not _is_int_value(val):
                        errors.append(f"xi_ilts[{i},{l},{t},{s}] must be integer data")
    for h in H:
        for t in T:
            for s in S:
                val = hosp_cap(instance, h, t, s)
                if val < -tol:
                    errors.append(f"h_hts[{h},{t},{s}] must be nonnegative")
                if not _is_int_value(val):
                    errors.append(f"h_hts[{h},{t},{s}] must be integer data")

    for j in J:
        for l in L:
            if sec["k_jl"][j][l] <= 0:
                errors.append(f"k_jl[{j},{l}] must be positive")
    for l in L:
        for name in ("alpha_l", "beta_l", "tau_l"):
            if sec[name][l] <= 0:
                errors.append(f"{name}[{l}] must be positive")
        if sec["rho_l"][l] < -tol:
            errors.append(f"rho_l[{l}] must be nonnegative")
    for l in L_Amb:
        if sec["delta_l"][l] < -tol:
            errors.append(f"delta_l[{l}] must be nonnegative")

    return {"passed": not errors, "errors": errors}
