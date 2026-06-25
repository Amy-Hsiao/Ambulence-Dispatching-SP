"""Small CSV writing helpers used by reporting scripts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def write_rows(path: str | Path, header: list[str], rows: list[list[Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path

