"""Run the tiny instances in the required order."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.schema import write_instance
from src.data.tiny_generator import CASE_BUILDERS
from src.io.result_writer import write_results
from src.model.sp_model import build_model
from src.validation.instance_validator import validate_instance
from src.validation.solution_validator import validate_solution


TEST_ORDER = [
    "deterministic_baseline",
    "all_capacities_sufficient",
    "road_disruption",
    "hospital_capacity_bottleneck",
    "ambulance_bottleneck",
    "treatment_time_boundary",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-dir", default="data/generated")
    parser.add_argument("--result-dir", default="output/tiny_tests")
    args = parser.parse_args()

    failures = []
    for name in TEST_ORDER:
        instance = CASE_BUILDERS[name]()
        write_instance(instance, f"{args.instance_dir}/{name}.json")
        pre = validate_instance(instance)
        if not pre["passed"]:
            failures.append((name, "instance", pre))
            print(f"{name}: instance validation failed")
            continue
        model = build_model(instance)
        model.optimize()
        post = validate_solution(model)
        write_results(model, args.result_dir, name)
        print(f"{name}: objective={model.ObjVal:.6g}, validator_passed={post['passed']}")
        if not post["passed"]:
            failures.append((name, "solution", post))
    if failures:
        raise SystemExit(f"Tiny tests failed: {failures}")


if __name__ == "__main__":
    main()
