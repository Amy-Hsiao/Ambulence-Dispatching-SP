"""Generate, validate, solve, and write the deterministic tiny baseline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.schema import write_instance
from src.data.tiny_generator import deterministic_baseline
from src.io.result_writer import write_results
from src.model.sp_model import build_model
from src.validation.instance_validator import validate_instance
from src.validation.solution_validator import validate_solution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-out", default="data/generated/deterministic_baseline.json")
    parser.add_argument("--result-dir", default="output/tiny_baseline")
    args = parser.parse_args()

    instance = deterministic_baseline()
    write_instance(instance, args.instance_out)
    pre = validate_instance(instance)
    if not pre["passed"]:
        raise SystemExit(f"Instance validation failed: {pre['errors']}")

    model = build_model(instance)
    model.optimize()
    post = validate_solution(model)
    paths = write_results(model, args.result_dir, instance["name"])
    print(f"objective={model.ObjVal}")
    print(f"validator_passed={post['passed']}")
    for label, path in paths.items():
        print(f"{label}={Path(path)}")
    if not post["passed"]:
        raise SystemExit(f"Solution validation failed: {post}")


if __name__ == "__main__":
    main()
