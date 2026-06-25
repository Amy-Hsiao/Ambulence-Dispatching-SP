"""Write solved model results for inspection."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.data.schema import instance_fingerprint
from src.validation.solution_validator import objective_decomposition, validate_solution


def _round_small(value: float, tol: float = 1e-9) -> float:
    return 0.0 if abs(value) <= tol else float(value)


def _tupledict_values(td: Any, tol: float = 1e-9) -> dict[str, float]:
    out = {}
    for key, var in td.items():
        if not isinstance(key, tuple):
            key = (key,)
        val = _round_small(float(var.X), tol)
        if abs(val) > tol:
            out["|".join(str(k) for k in key)] = val
    return out


def _all_tupledict_values(td: Any) -> dict[str, float]:
    out = {}
    for key, var in td.items():
        if not isinstance(key, tuple):
            key = (key,)
        out["|".join(str(k) for k in key)] = _round_small(float(var.X))
    return out


def _fallback_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def _write_json_with_fallback(path: Path, payload: dict[str, Any]) -> Path:
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        return path
    except PermissionError:
        fallback = _fallback_path(path)
        with fallback.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        print(f"Warning: {path} is locked; wrote {fallback} instead.")
        return fallback


def _write_csv_with_fallback(path: Path, rows: list[list[Any]]) -> Path:
    try:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        return path
    except PermissionError:
        fallback = _fallback_path(path)
        with fallback.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        print(f"Warning: {path} is locked; wrote {fallback} instead.")
        return fallback


def write_results(model: Any, output_dir: str | Path, name: str | None = None) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    instance = model._sp_instance
    name = name or instance.get("name", "sp_result")
    vars_ = model._sp_vars
    validator = validate_solution(model)
    decomp = objective_decomposition(model)

    payload = {
        "instance": instance.get("name", name),
        "instance_fingerprint": instance_fingerprint(instance),
        "instance_data": instance,
        "gurobi_status": int(model.Status),
        **decomp,
        "first_stage_variables": {
            "X": _all_tupledict_values(vars_["X"]),
            "V": _all_tupledict_values(vars_["V"]),
            "U": _all_tupledict_values(vars_["U"]),
            "Y": _all_tupledict_values(vars_["Y"]),
        },
        "nonzero_second_stage_variables": {
            "FI": _tupledict_values(vars_["FI"]),
            "FO": _tupledict_values(vars_["FO"]),
            "RM": _tupledict_values(vars_["RM"]),
            "REG": _tupledict_values(vars_["REG"]),
            "TRT": _tupledict_values(vars_["TRT"]),
            "WAT": _tupledict_values(vars_["WAT"]),
        },
        "constraint_family_max_violation": validator["max_violations"],
        "validator_summary": validator,
    }

    json_path = _write_json_with_fallback(output_dir / f"{name}_results.json", payload)

    variable_rows = [["group", "key", "value"]]
    for group in ("X", "V", "U", "Y"):
        for key, value in payload["first_stage_variables"][group].items():
            variable_rows.append([group, key, value])
    for group, values in payload["nonzero_second_stage_variables"].items():
        for key, value in values.items():
            variable_rows.append([group, key, value])
    csv_path = _write_csv_with_fallback(output_dir / f"{name}_nonzero_variables.csv", variable_rows)

    violation_rows = [["constraint_family", "max_violation"]]
    for family, value in validator["max_violations"].items():
        violation_rows.append([family, value])
    violations_path = _write_csv_with_fallback(output_dir / f"{name}_violations.csv", violation_rows)

    return {"json": json_path, "variables_csv": csv_path, "violations_csv": violations_path}
