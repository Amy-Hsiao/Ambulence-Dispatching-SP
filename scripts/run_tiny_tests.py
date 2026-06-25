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

EXPECTED_OBJECTIVES = {
    "deterministic_baseline": 208.0,
    "all_capacities_sufficient": 208.0,
    "road_disruption": 526.0,
    "hospital_capacity_bottleneck": 336.0,
    "ambulance_bottleneck": 287.0,
    "treatment_time_boundary": 205.0,
}
TOL = 1e-6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-dir", default="data/tiny/instances")
    parser.add_argument("--result-dir", default="outputs/tiny_tests")
    args = parser.parse_args()

    failures = []
    print("開始執行 tiny case regression tests")
    for name in TEST_ORDER:
        instance = CASE_BUILDERS[name]()
        write_instance(instance, f"{args.instance_dir}/{name}.json")
        pre = validate_instance(instance)
        if not pre["passed"]:
            failures.append((name, "instance", pre))
            print(f"- {name}: instance validation 未通過")
            continue
        model = build_model(instance)
        model.optimize()
        expected = EXPECTED_OBJECTIVES[name]
        if abs(float(model.ObjVal) - expected) > TOL:
            raise SystemExit(f"{name} objective changed: expected={expected}, actual={model.ObjVal}")
        post = validate_solution(model)
        case_dir = Path(args.result_dir) / name
        write_results(model, case_dir, name, standard_names=True)
        print(f"- {name}: 目標值={model.ObjVal:.6g}, 預期={expected:.6g}, 驗證通過={'是' if post['passed'] else '否'}")
        if not post["passed"]:
            failures.append((name, "solution", post))
    if failures:
        raise SystemExit(f"Tiny tests failed: {failures}")
    print("tiny case regression tests 全部通過")


if __name__ == "__main__":
    main()
