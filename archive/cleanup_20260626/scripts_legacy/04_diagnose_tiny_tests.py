"""Run tiny diagnostics and write English and Chinese Markdown reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.diagnose_tiny_tests import diagnose
from src.ambulance_sp.reporting.chinese_report_writer import write_diagnostic_summary_zh


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default="outputs/tiny_tests")
    parser.add_argument("--output-dir", default="outputs/tiny_diagnostics")
    args = parser.parse_args()
    diagnose(Path(args.result_dir), Path(args.output_dir))
    write_diagnostic_summary_zh(
        Path(args.output_dir) / "tiny_test_diagnostic_report.json",
        Path(args.output_dir) / "tiny_test_diagnostic_report_zh.md",
    )
    print(f"Wrote {Path(args.output_dir) / 'tiny_test_diagnostic_report.md'}")
    print(f"Wrote {Path(args.output_dir) / 'tiny_test_diagnostic_report.json'}")
    print(f"Wrote {Path(args.output_dir) / 'tiny_test_diagnostic_report_zh.md'}")


if __name__ == "__main__":
    main()

