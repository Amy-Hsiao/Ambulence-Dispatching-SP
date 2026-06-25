"""Build empty CSV templates for real-data preparation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_loading.real_data_template_builder import build_templates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/real/templates")
    args = parser.parse_args()

    paths = build_templates(args.output_dir)
    print("Real data CSV templates 已建立")
    for path in paths:
        print(f"- {path}")


if __name__ == "__main__":
    main()
