"""Run a processed real-data instance with the same extensive-form model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ambulance_sp.optimization.extensive_form_sp_model import build_model
from src.ambulance_sp.reporting.result_writer import write_results
from src.ambulance_sp.schemas.instance_schema import load_instance
from src.ambulance_sp.validation.input_data_validator import validate_instance
from src.ambulance_sp.validation.solution_validator import validate_solution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="data/real/processed/real_instance.json")
    parser.add_argument("--result-dir", default="outputs/real_data_runs")
    args = parser.parse_args()

    instance = load_instance(args.instance)
    if instance.get("status") == "template_only":
        raise SystemExit("Real-data instance is template_only. Complete real-data mapping before solving.")
    pre = validate_instance(instance)
    if not pre["passed"]:
        raise SystemExit(f"Instance validation failed: {pre['errors']}")
    model = build_model(instance)
    model.optimize()
    post = validate_solution(model)
    write_results(model, args.result_dir, instance.get("name", "real_data_instance"))
    print(f"objective={model.ObjVal}")
    print(f"validator_passed={post['passed']}")


if __name__ == "__main__":
    main()

