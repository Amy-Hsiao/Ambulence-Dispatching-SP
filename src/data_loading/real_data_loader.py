"""Skeleton loader for real-data CSVs.

This module is intentionally validation-oriented. It prepares the path from real CSVs to
the existing instance schema without changing the SP model or tiny cases.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.data_loading.real_data_template_builder import TEMPLATES


RAW_TO_TEMPLATE = {name.replace("_template", ""): header for name, header in TEMPLATES.items()}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate_real_csv_folder(raw_dir: str | Path = "data/real/raw") -> dict[str, Any]:
    raw_dir = Path(raw_dir)
    errors: list[str] = []
    warnings: list[str] = []
    file_summaries: dict[str, Any] = {}

    if not raw_dir.exists():
        errors.append(f"raw data directory does not exist: {raw_dir}")
        return {"passed": False, "errors": errors, "warnings": warnings, "files": file_summaries}

    for filename, required_header in RAW_TO_TEMPLATE.items():
        path = raw_dir / filename
        if not path.exists():
            warnings.append(f"missing optional/raw CSV: {path}")
            continue
        rows = _read_rows(path)
        actual = list(rows[0].keys()) if rows else []
        missing = [col for col in required_header if col not in actual]
        if missing:
            errors.append(f"{path} missing columns: {missing}")
        file_summaries[filename] = {"rows": len(rows), "columns": actual}

    return {"passed": not errors, "errors": errors, "warnings": warnings, "files": file_summaries}


def build_real_instance_skeleton(
    raw_dir: str | Path = "data/real/raw",
    output_path: str | Path = "data/real/processed/real_instance.json",
) -> dict[str, Any]:
    """Validate CSV presence and write a placeholder processed JSON.

    Full real-data transformation should map the raw CSV rows into the same schema used by
    tiny instances. This skeleton deliberately does not infer model parameters silently.
    """
    validation = validate_real_csv_folder(raw_dir)
    payload = {
        "status": "template_only",
        "message": "Real-data loader skeleton validated CSV headers but did not infer a model instance.",
        "validation": validation,
        "next_step": "Fill raw CSVs and implement explicit field mapping to the existing instance schema.",
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    return payload
