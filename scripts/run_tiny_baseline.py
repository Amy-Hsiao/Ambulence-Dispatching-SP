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


EXPECTED_OBJECTIVE = 208.0
TOL = 1e-6


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
    model.optimize()
    if abs(float(model.ObjVal) - EXPECTED_OBJECTIVE) > TOL:
        raise SystemExit(
            "deterministic_baseline objective changed: "
            f"expected={EXPECTED_OBJECTIVE}, actual={model.ObjVal}"
        )
    post = validate_solution(model)
    case_dir = Path(args.result_dir) / instance["name"]
    paths = write_results(model, case_dir, instance["name"], standard_names=True)
    print("Tiny baseline 求解完成")
    print(f"- 案例：{instance['name']}")
    print(f"- 目標值：{model.ObjVal:.6g}")
    print(f"- 驗證通過：{'是' if post['passed'] else '否'}")
    print("- 輸出檔案：")
    for label, path in paths.items():
        print(f"  - {label}: {Path(path)}")
    if not post["passed"]:
        raise SystemExit(f"Solution validation failed: {post}")


if __name__ == "__main__":
    main()
