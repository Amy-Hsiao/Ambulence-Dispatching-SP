"""Run the deterministic tiny baseline with organized output names."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ambulance_sp.data_generation.tiny_case_generator import deterministic_baseline
from src.ambulance_sp.optimization.extensive_form_sp_model import build_model
from src.ambulance_sp.reporting.chinese_report_writer import write_case_summary_zh
from src.ambulance_sp.reporting.result_writer import write_results
from src.ambulance_sp.schemas.instance_schema import write_instance
from src.ambulance_sp.validation.input_data_validator import validate_instance
from src.ambulance_sp.validation.solution_validator import validate_solution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-out", default="data/tiny/instances/deterministic_baseline.json")
    parser.add_argument("--result-dir", default="outputs/tiny_baseline")
    args = parser.parse_args()

    instance = deterministic_baseline()
    write_instance(instance, args.instance_out)
    pre = validate_instance(instance)
    if not pre["passed"]:
        raise SystemExit(f"Instance validation failed: {pre['errors']}")

    model = build_model(instance)
    model.Params.OutputFlag = 0
    model.optimize()
    post = validate_solution(model)
    paths = write_results(model, args.result_dir, instance["name"], standard_names=True)
    write_case_summary_zh(paths["json"], Path(args.result_dir) / "summary_zh.md")

    print("============================================================")
    print("Tiny Case Validation Summary")
    print("============================================================")
    print(f"Case: deterministic_baseline")
    print(f"Gurobi status: {model.Status}")
    print(f"Objective: {model.ObjVal}")
    print(f"Validator passed: {post['passed']}")
    if not post["passed"]:
        raise SystemExit(f"Solution validation failed: {post}")


if __name__ == "__main__":
    main()

