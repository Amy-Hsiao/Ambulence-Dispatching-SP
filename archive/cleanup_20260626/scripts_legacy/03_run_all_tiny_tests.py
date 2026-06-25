"""Run all tiny tests in the required order with organized output folders."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_tiny_tests import TEST_ORDER
from src.ambulance_sp.data_generation.tiny_case_generator import CASE_BUILDERS
from src.ambulance_sp.optimization.extensive_form_sp_model import build_model
from src.ambulance_sp.reporting.chinese_report_writer import CASE_PURPOSE_ZH, write_case_summary_zh
from src.ambulance_sp.reporting.result_writer import write_results
from src.ambulance_sp.schemas.instance_schema import write_instance
from src.ambulance_sp.validation.input_data_validator import validate_instance
from src.ambulance_sp.validation.solution_validator import validate_solution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-dir", default="data/tiny/instances")
    parser.add_argument("--result-dir", default="outputs/tiny_tests")
    args = parser.parse_args()

    failures = []
    print("============================================================")
    print("Tiny Case Validation Summary")
    print("============================================================")
    print()
    for idx, name in enumerate(TEST_ORDER, start=1):
        instance = CASE_BUILDERS[name]()
        write_instance(instance, f"{args.instance_dir}/{name}.json")
        pre = validate_instance(instance)
        if not pre["passed"]:
            failures.append((name, "instance", pre))
            print(f"Case {idx}: {name}")
            print("  Instance validation failed")
            continue
        model = build_model(instance)
        model.Params.OutputFlag = 0
        model.optimize()
        post = validate_solution(model)
        case_dir = Path(args.result_dir) / name
        paths = write_results(model, case_dir, name, standard_names=True)
        write_case_summary_zh(paths["json"], case_dir / "summary_zh.md")
        print(f"Case {idx}: {name}")
        print(f"  Purpose: {CASE_PURPOSE_ZH.get(name, '')}")
        print(f"  Gurobi status: {model.Status}")
        print(f"  Objective: {model.ObjVal}")
        print(f"  Validator passed: {post['passed']}")
        print()
        if not post["passed"]:
            failures.append((name, "solution", post))
    if failures:
        raise SystemExit(f"Tiny tests failed: {failures}")
    print("All tiny cases passed validation.")


if __name__ == "__main__":
    main()

