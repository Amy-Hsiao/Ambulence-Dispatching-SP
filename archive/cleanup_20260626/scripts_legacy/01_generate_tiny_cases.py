"""Generate tiny case JSON files into the organized data folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ambulance_sp.data_generation.tiny_case_generator import write_all


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/tiny/instances")
    args = parser.parse_args()
    for path in write_all(args.output_dir):
        print(path)


if __name__ == "__main__":
    main()

