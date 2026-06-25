"""Generate reproducible tiny instances for the extensive-form SP model."""

from __future__ import annotations

import argparse
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.data.schema import write_instance


def _zeros_xi(I: list[str], L: list[str], T: list[int], S: list[str]) -> dict[str, Any]:
    return {i: {l: {str(t): {s: 0 for s in S} for t in T} for l in L} for i in I}


def _full_u(I: list[str], J: list[str], T: list[int], S: list[str], value: float = 1.0) -> dict[str, Any]:
    return {i: {j: {str(t): {s: value for s in S} for t in T} for j in J} for i in I}


def _full_w(J: list[str], H: list[str], T: list[int], S: list[str], value: float = 1.0) -> dict[str, Any]:
    return {j: {h: {str(t): {s: value for s in S} for t in T} for h in H} for j in J}


def _h_caps(H: list[str], T: list[int], S: list[str], value: int) -> dict[str, Any]:
    return {h: {str(t): {s: value for s in S} for t in T} for h in H}


def deterministic_baseline() -> dict[str, Any]:
    I, J, H = ["i1"], ["j1"], ["h1"]
    L, L_Amb, T, S = ["minor", "moderate", "severe"], ["moderate", "severe"], [1, 2], ["s1"]
    xi = _zeros_xi(I, L, T, S)
    xi["i1"]["minor"]["1"]["s1"] = 2
    xi["i1"]["moderate"]["1"]["s1"] = 1
    xi["i1"]["severe"]["1"]["s1"] = 1
    return {
        "name": "deterministic_baseline",
        "case_metadata": {
            "purpose": "Baseline sanity case for flow balances, first-stage linking, and L_Amb-only FO/WAT variables.",
        },
        "sets": {"I": I, "J": J, "H": H, "L": L, "L_Amb": L_Amb, "T": T, "S": S},
        "p_s": {"s1": 1.0},
        "first_stage": {
            "f_j": {"j1": 145},
            "cv": 10,
            "ca": 30,
            "cy_hj": {"h1": {"j1": 1}},
            "nv": 4,
            "na": 1,
            "sbar_h": {"h1": 20},
            "vbar_j": {"j1": 4},
            "ubar_j": {"j1": 1},
            "ybar_j": {"j1": 20},
        },
        "second_stage": {
            "c_ij": {"i1": {"j1": 10}},
            "c_jh": {"j1": {"h1": 10}},
            "kappa": 2,
            "eta": 2,
            "b_h": {"h1": 1},
            "k_jl": {"j1": {"minor": 4, "moderate": 3, "severe": 2}},
            "tau_l": {"minor": 1, "moderate": 1, "severe": 1},
            "alpha_l": {"minor": 4, "moderate": 2, "severe": 1},
            "beta_l": {"minor": 1, "moderate": 2, "severe": 3},
            "rho_l": {"minor": 20, "moderate": 80, "severe": 200},
            "delta_l": {"moderate": 30, "severe": 100},
            "t_ij": {"i1": {"j1": 1}},
            "t_jh": {"j1": {"h1": 1}},
        },
        "random_variables": {
            "xi_ilts": xi,
            "u_ijts": _full_u(I, J, T, S),
            "w_jhts": _full_w(J, H, T, S),
            "h_hts": _h_caps(H, T, S, 3),
        },
    }


def all_capacities_sufficient() -> dict[str, Any]:
    inst = deterministic_baseline()
    inst["name"] = "all_capacities_sufficient"
    inst["case_metadata"] = {
        "purpose": "All major capacities are loose; RM and WAT should stay at zero.",
    }
    inst["first_stage"]["nv"] = 10
    inst["first_stage"]["na"] = 4
    inst["first_stage"]["sbar_h"]["h1"] = 100
    inst["first_stage"]["vbar_j"]["j1"] = 10
    inst["first_stage"]["ubar_j"]["j1"] = 4
    inst["first_stage"]["ybar_j"]["j1"] = 100
    inst["second_stage"]["c_ij"]["i1"]["j1"] = 100
    inst["second_stage"]["c_jh"]["j1"]["h1"] = 100
    inst["second_stage"]["k_jl"]["j1"] = {"minor": 100, "moderate": 100, "severe": 100}
    inst["second_stage"]["kappa"] = 100
    inst["second_stage"]["eta"] = 100
    inst["second_stage"]["b_h"]["h1"] = 10
    inst["random_variables"]["h_hts"] = _h_caps(["h1"], [1, 2], ["s1"], 100)
    return inst


def road_disruption() -> dict[str, Any]:
    inst = deterministic_baseline()
    inst["name"] = "road_disruption"
    inst["random_variables"]["u_ijts"]["i1"]["j1"]["1"]["s1"] = 0.0
    inst["case_metadata"] = {
        "purpose": "The only disaster-area-to-CCP link is unavailable in period 1.",
        "intended_binding": {
            "constraint_family": "road_i_to_j_capacity",
            "i": "i1",
            "j": "j1",
            "time": 1,
            "scenario": "s1",
        },
    }
    return inst


def hospital_capacity_bottleneck() -> dict[str, Any]:
    inst = all_capacities_sufficient()
    inst["name"] = "hospital_capacity_bottleneck"
    # In the baseline tau=1 convention, period-1 registrations complete and become transferable in period 2.
    # Therefore the bottleneck must be placed at t=2 to test the hospital receiving constraint.
    inst["random_variables"]["h_hts"]["h1"]["2"]["s1"] = 0
    inst["case_metadata"] = {
        "purpose": "Hospital receiving capacity is zero exactly when baseline hospital transfer would occur.",
        "intended_binding": {
            "constraint_family": "hospital_receiving_capacity",
            "hospital": "h1",
            "time": 2,
            "scenario": "s1",
        },
    }
    return inst


def ambulance_bottleneck() -> dict[str, Any]:
    inst = deterministic_baseline()
    inst["name"] = "ambulance_bottleneck"
    inst["second_stage"]["kappa"] = 1
    inst["first_stage"]["na"] = 1
    inst["first_stage"]["ubar_j"]["j1"] = 1
    inst["case_metadata"] = {
        "purpose": "CCP ambulance capacity limits period-level ambulance-required FI.",
        "intended_binding": {
            "constraint_family": "ccp_ambulance_capacity",
            "j": "j1",
            "scenario": "s1",
        },
    }
    return inst


def treatment_time_boundary() -> dict[str, Any]:
    inst = all_capacities_sufficient()
    inst["name"] = "treatment_time_boundary"
    inst["sets"]["T"] = [1, 2, 3]
    I, J, H = inst["sets"]["I"], inst["sets"]["J"], inst["sets"]["H"]
    L, S = inst["sets"]["L"], inst["sets"]["S"]
    xi = _zeros_xi(I, L, [1, 2, 3], S)
    xi["i1"]["minor"]["1"]["s1"] = 1
    xi["i1"]["moderate"]["1"]["s1"] = 1
    xi["i1"]["severe"]["1"]["s1"] = 1
    inst["random_variables"]["xi_ilts"] = xi
    inst["random_variables"]["u_ijts"] = _full_u(I, J, [1, 2, 3], S)
    inst["random_variables"]["w_jhts"] = _full_w(J, H, [1, 2, 3], S)
    inst["random_variables"]["h_hts"] = _h_caps(H, [1, 2, 3], S, 100)
    inst["second_stage"]["tau_l"] = {"minor": 1, "moderate": 2, "severe": 3}
    inst["case_metadata"] = {
        "purpose": "Checks treatment completion boundary t - tau_l < 1 and TRT rolling sums.",
        "intended_boundary_checks": [
            {"l": "moderate", "time": 1, "completion_period": -1},
            {"l": "severe", "time": 1, "completion_period": -2},
            {"l": "severe", "time": 2, "completion_period": -1},
        ],
    }
    return inst


def stochastic_tiny(seed: int = 7) -> dict[str, Any]:
    import random

    rng = random.Random(seed)
    I, J, H = ["i1", "i2"], ["j1", "j2"], ["h1"]
    L, L_Amb, T, S = ["minor", "moderate", "severe"], ["moderate", "severe"], [1, 2, 3], ["s1", "s2"]
    coords = {"i1": (0, 0), "i2": (4, 0), "j1": (1, 1), "j2": (3, 1), "h1": (2, 4)}

    def dist(a: str, b: str) -> float:
        ax, ay = coords[a]
        bx, by = coords[b]
        return max(0.1, math.hypot(ax - bx, ay - by))

    k_jl = {j: {"minor": 8, "moderate": 5, "severe": 3} for j in J}
    inst = deepcopy(deterministic_baseline())
    inst["name"] = "stochastic_tiny"
    inst["sets"] = {"I": I, "J": J, "H": H, "L": L, "L_Amb": L_Amb, "T": T, "S": S}
    inst["p_s"] = {s: 1 / len(S) for s in S}
    inst["first_stage"] = {
        "f_j": {j: 100 + 5 * sum(k_jl[j].values()) for j in J},
        "cv": 10,
        "ca": 30,
        "cy_hj": {h: {j: dist(h, j) for j in J} for h in H},
        "nv": 8,
        "na": 3,
        "sbar_h": {"h1": 60},
        "vbar_j": {j: 5 for j in J},
        "ubar_j": {j: 3 for j in J},
        "ybar_j": {j: 50 for j in J},
    }
    inst["second_stage"] = {
        "c_ij": {i: {j: max(2, math.ceil(20 / (1 + dist(i, j)))) for j in J} for i in I},
        "c_jh": {j: {h: max(2, math.ceil(20 / (1 + dist(j, h)))) for h in H} for j in J},
        "kappa": 3,
        "eta": 3,
        "b_h": {"h1": 2},
        "k_jl": k_jl,
        "tau_l": {"minor": 1, "moderate": 2, "severe": 2},
        "alpha_l": {"minor": 4, "moderate": 2, "severe": 1},
        "beta_l": {"minor": 1, "moderate": 2, "severe": 3},
        "rho_l": {"minor": 20, "moderate": 80, "severe": 200},
        "delta_l": {"moderate": 30, "severe": 100},
        "t_ij": {i: {j: dist(i, j) for j in J} for i in I},
        "t_jh": {j: {h: 1.5 * dist(j, h) for h in H} for j in J},
    }
    xi = _zeros_xi(I, L, T, S)
    ratios = {"minor": 0.55, "moderate": 0.30, "severe": 0.15}
    weights = {1: 0.60, 2: 0.30, 3: 0.10}
    for s in S:
        for i in I:
            total = rng.randint(4, 12)
            cells = [(l, t, total * ratios[l] * weights[t]) for l in L for t in T]
            floors = [(l, t, math.floor(v), v - math.floor(v)) for l, t, v in cells]
            remainder = total - sum(v for _, _, v, _ in floors)
            for l, t, v, _ in floors:
                xi[i][l][str(t)][s] = v
            for l, t, _, _ in sorted(floors, key=lambda x: x[3], reverse=True)[:remainder]:
                xi[i][l][str(t)][s] += 1
    u = _full_u(I, J, T, S)
    for i in I:
        for j in J:
            for s in S:
                base, rate = rng.uniform(0.5, 0.9), rng.uniform(0, 0.2)
                for t in T:
                    u[i][j][str(t)][s] = min(1.0, base + rate * (t - 1))
    w = _full_w(J, H, T, S)
    for j in J:
        for h in H:
            for s in S:
                base, rate = rng.uniform(0.6, 1.0), rng.uniform(0, 0.2)
                for t in T:
                    w[j][h][str(t)][s] = min(1.0, base + rate * (t - 1))
    hcaps = _h_caps(H, T, S, 0)
    for h in H:
        nominal = rng.randint(4, 10)
        for s in S:
            damage, restore = rng.uniform(0.5, 1.0), rng.uniform(0, 0.2)
            for t in T:
                hcaps[h][str(t)][s] = math.floor(nominal * min(1.0, damage + restore * (t - 1)))
    inst["random_variables"] = {"xi_ilts": xi, "u_ijts": u, "w_jhts": w, "h_hts": hcaps}
    return inst


CASE_BUILDERS = {
    "deterministic_baseline": deterministic_baseline,
    "all_capacities_sufficient": all_capacities_sufficient,
    "road_disruption": road_disruption,
    "hospital_capacity_bottleneck": hospital_capacity_bottleneck,
    "ambulance_bottleneck": ambulance_bottleneck,
    "treatment_time_boundary": treatment_time_boundary,
    "stochastic_tiny": stochastic_tiny,
}


def write_all(output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    paths = []
    for name, builder in CASE_BUILDERS.items():
        inst = builder()
        path = output_dir / f"{name}.json"
        write_instance(inst, path)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/generated")
    args = parser.parse_args()
    for path in write_all(args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
