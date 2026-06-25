"""Validate real-data CSV headers without solving the optimization model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_loading.real_data_loader import build_real_instance_skeleton


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/real/raw")
    parser.add_argument("--output-path", default="data/real/processed/real_instance_skeleton.json")
    parser.add_argument("--report-path", default="outputs/real_data_validation/validation_report.json")
    args = parser.parse_args()

    payload = build_real_instance_skeleton(args.raw_dir, args.output_path)
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    validation = payload["validation"]
    print("Real data CSV header 檢查完成")
    print(f"- 通過：{'是' if validation['passed'] else '否'}")
    print(f"- 錯誤數：{len(validation['errors'])}")
    print(f"- 警告數：{len(validation['warnings'])}")
    print(f"- skeleton 輸出：{args.output_path}")
    print(f"- validation report：{report_path}")
    if validation["errors"]:
        raise SystemExit(validation["errors"])


if __name__ == "__main__":
    main()
