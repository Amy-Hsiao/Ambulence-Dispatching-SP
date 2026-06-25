"""Build empty CSV templates for preparing real-data instances."""

from __future__ import annotations

import csv
from pathlib import Path


TEMPLATES: dict[str, list[str]] = {
    "nodes_template.csv": ["node_id", "node_type", "name", "latitude", "longitude", "notes"],
    "disaster_areas_template.csv": ["i", "name", "latitude", "longitude"],
    "candidate_ccps_template.csv": ["j", "name", "latitude", "longitude", "fixed_cost", "vbar_j", "ubar_j", "ybar_j"],
    "hospitals_template.csv": ["h", "name", "latitude", "longitude", "sbar_h", "b_h"],
    "road_links_i_to_j_template.csv": ["i", "j", "c_ij", "t_ij"],
    "road_links_j_to_h_template.csv": ["j", "h", "c_jh", "t_jh"],
    "casualty_arrivals_template.csv": ["i", "l", "t", "s", "xi_ilts"],
    "road_availability_i_to_j_template.csv": ["i", "j", "t", "s", "u_ijts"],
    "road_availability_j_to_h_template.csv": ["j", "h", "t", "s", "w_jhts"],
    "hospital_capacity_template.csv": ["h", "t", "s", "h_hts"],
    "scenario_probabilities_template.csv": ["s", "p_s"],
    "first_stage_parameters_template.csv": ["parameter", "h", "j", "value"],
    "severity_parameters_template.csv": ["l", "in_L_Amb", "tau_l", "alpha_l", "beta_l", "rho_l", "delta_l"],
}


def build_templates(output_dir: str | Path = "data/real/templates") -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, header in TEMPLATES.items():
        path = output_dir / filename
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
        paths.append(path)
    return paths

