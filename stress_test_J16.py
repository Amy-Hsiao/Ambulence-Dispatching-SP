#!/usr/bin/env python3
"""
Batch SP experiment runner.

This script is only a runner. It temporarily changes values in the imported
config module while it runs each experiment case, then restores them. It does
not rewrite config.py and does not change the model core logic.
"""

from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import math
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


# =============================================================================
# Parameter setting area
# =============================================================================
# Choose exactly one experiment axis:
#   "scenario"                     -> run different scenario counts, e.g. [5, 10, 20]
#   "ccp"                          -> run different CCP counts, e.g. [6, 8, 10]
#   "sample_ratio"                 -> run different I/H sample ratios, e.g. [0.1, 0.25, 0.5, 1.0]
#   "time_period"                  -> run different time periods, e.g. [4, 8, 12, 16]
#   "demand_multiplier"            -> run different demand multipliers, e.g. [1.0, 1.2, 1.5]
#   "road_capacity_multiplier"     -> run different road capacity multipliers, e.g. [0.8, 1.0, 1.2]
#   "hospital_capacity_multiplier" -> run different hospital capacity multipliers, e.g. [0.8, 1.0, 1.2]
EXPERIMENT_AXIS = "scenario"
EXPERIMENT_VALUES = [5, 10, 20]

# Fixed base settings. The chosen EXPERIMENT_AXIS overrides one of these values
# for each case; all other values stay fixed.
BASE_SCENARIOS = 5
BASE_CCP_SAMPLE_SIZE = 8       # None = use all CCPs; positive int = sample N CCPs
BASE_SAMPLE_RATIO = 0.25       # 0 < ratio <= 1.0; samples disaster areas and hospitals
BASE_TIME_PERIODS = 8
BASE_DEMAND_MULTIPLIER = 1.0
BASE_ROAD_CAPACITY_MULTIPLIER = 1.0
BASE_HOSPITAL_CAPACITY_MULTIPLIER = 1.0

# Solver and early-stop settings.
TIME_LIMIT = 3600.0
MIP_GAP = 0.01
GAP_STOP_PCT = 10.0
CPU_STOP_SEC = 10000.0

# Output settings.
RESULT_PREFIX = "stress_test_batch"
STOP_ON_ERROR = True


ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "logs"
SP_MODEL_PATH = ROOT_DIR / "sp model.py"

os.chdir(ROOT_DIR)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config as cfg  # noqa: E402


FIELDNAMES = [
    "test_id",
    "axis",
    "axis_value",
    "sample_ratio",
    "I",
    "J",
    "H",
    "S",
    "T",
    "demand_multiplier",
    "road_capacity_multiplier",
    "hospital_capacity_multiplier",
    "obj_value",
    "best_lb",
    "best_ub",
    "cpu_s",
    "wall_s",
    "gap_pct",
    "vss_pct",
    "evpi_pct",
    "log_path",
    "status",
    "note",
]


AXIS_TO_SETTING = {
    "scenario": "scenarios",
    "ccp": "ccp_sample_size",
    "sample_ratio": "sample_ratio",
    "time_period": "time_periods",
    "demand_multiplier": "demand_multiplier",
    "road_capacity_multiplier": "road_capacity_multiplier",
    "hospital_capacity_multiplier": "hospital_capacity_multiplier",
}


def load_sp_module():
    """Load 'sp model.py' even though the filename contains a space."""
    if not SP_MODEL_PATH.exists():
        raise FileNotFoundError(f"Cannot find SP model file: {SP_MODEL_PATH}")

    spec = importlib.util.spec_from_file_location("sp_model_runner", SP_MODEL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {SP_MODEL_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def csv_row_count(filepath: Path) -> int:
    with filepath.open(encoding="utf-8-sig", newline="") as file:
        return max(0, sum(1 for _ in file) - 1)


def fmt_value(value: Any) -> str:
    if value is None:
        return "ALL"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def blank_row() -> dict[str, Any]:
    return {key: "NA" for key in FIELDNAMES}


def write_results(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def snapshot_logs() -> set[Path]:
    if not LOG_DIR.exists():
        return set()
    return {path.resolve() for path in LOG_DIR.glob("*.log")}


def newest_created_log(before: set[Path]) -> Path | None:
    if not LOG_DIR.exists():
        return None
    created = [path for path in LOG_DIR.glob("*.log") if path.resolve() not in before]
    if not created:
        return None
    return max(created, key=lambda path: path.stat().st_mtime)


def parse_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    return float(match.group(0)) if match else None


def parse_log_summary(log_path: Path | None) -> dict[str, float]:
    if log_path is None or not log_path.exists():
        return {}

    patterns = {
        "obj_value": re.compile(r"Objective Value:\s*([-+]?\d+(?:\.\d+)?)"),
        "cpu_s": re.compile(r"CPU Time:\s*([-+]?\d+(?:\.\d+)?)\s*s"),
        "best_ub": re.compile(r"Best UB \(Objective\):\s*([-+]?\d+(?:\.\d+)?)"),
        "best_lb": re.compile(r"Best LB \(Bound\):\s*([-+]?\d+(?:\.\d+)?)"),
        "gap_pct": re.compile(r"Final Gap:\s*([-+]?\d+(?:\.\d+)?)\s*%"),
    }

    values: dict[str, float] = {}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    for key, pattern in patterns.items():
        matches = pattern.findall(text)
        if matches:
            values[key] = float(matches[-1])
    return values


def safe_model_attr(model: Any, attr: str) -> float | None:
    try:
        return float(getattr(model, attr))
    except Exception:
        return None


def model_fallback_summary(model: Any) -> dict[str, float]:
    if model is None:
        return {}

    values: dict[str, float] = {}
    runtime = safe_model_attr(model, "Runtime")
    gap = safe_model_attr(model, "MIPGap")
    obj = safe_model_attr(model, "ObjVal")
    bound = safe_model_attr(model, "ObjBound")

    if runtime is not None:
        values["cpu_s"] = runtime
    if gap is not None:
        values["gap_pct"] = gap * 100.0
    if obj is not None:
        values["obj_value"] = obj
        values["best_ub"] = obj
    if bound is not None:
        values["best_lb"] = bound
    return values


def format_float(value: Any, digits: int = 4) -> str:
    if value is None or value == "NA":
        return "NA"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "NA"


def base_case_settings() -> dict[str, Any]:
    return {
        "scenarios": BASE_SCENARIOS,
        "ccp_sample_size": BASE_CCP_SAMPLE_SIZE,
        "sample_ratio": BASE_SAMPLE_RATIO,
        "time_periods": BASE_TIME_PERIODS,
        "demand_multiplier": BASE_DEMAND_MULTIPLIER,
        "road_capacity_multiplier": BASE_ROAD_CAPACITY_MULTIPLIER,
        "hospital_capacity_multiplier": BASE_HOSPITAL_CAPACITY_MULTIPLIER,
    }


def build_case(axis_value: Any) -> dict[str, Any]:
    if EXPERIMENT_AXIS not in AXIS_TO_SETTING:
        valid = ", ".join(sorted(AXIS_TO_SETTING))
        raise ValueError(f"Unknown EXPERIMENT_AXIS={EXPERIMENT_AXIS!r}; choose one of: {valid}")

    settings = base_case_settings()
    settings[AXIS_TO_SETTING[EXPERIMENT_AXIS]] = axis_value
    return settings


def validate_case(settings: dict[str, Any]) -> None:
    if not isinstance(settings["scenarios"], int) or settings["scenarios"] < 1:
        raise ValueError("scenarios must be a positive integer")
    if not isinstance(settings["time_periods"], int) or settings["time_periods"] < 1:
        raise ValueError("time_periods must be a positive integer")
    if not (0 < float(settings["sample_ratio"]) <= 1.0):
        raise ValueError("sample_ratio must be in (0, 1.0]")
    ccp_size = settings["ccp_sample_size"]
    if ccp_size is not None and (not isinstance(ccp_size, int) or ccp_size < 1):
        raise ValueError("ccp_sample_size must be None or a positive integer")


@contextmanager
def temporary_config(settings: dict[str, Any]):
    keys = {
        "SCENARIOS": settings["scenarios"],
        "TIME_PERIODS": settings["time_periods"],
        "SAMPLE_RATIO": settings["sample_ratio"],
        "SP_SAMPLE_RATIO": settings["sample_ratio"],
        "DEMAND_MULTIPLIER": settings["demand_multiplier"],
        "ROAD_CAPACITY_MULTIPLIER": settings["road_capacity_multiplier"],
        "HOSPITAL_CAPACITY_MULTIPLIER": settings["hospital_capacity_multiplier"],
        "SP_TIME_LIMIT": TIME_LIMIT,
        "SP_MIP_GAP": MIP_GAP,
    }
    if hasattr(cfg, "CCP_SAMPLE_SIZE"):
        keys["CCP_SAMPLE_SIZE"] = settings["ccp_sample_size"]

    original = {key: getattr(cfg, key) for key in keys}
    try:
        for key, value in keys.items():
            setattr(cfg, key, value)
        yield
    finally:
        for key, value in original.items():
            setattr(cfg, key, value)


@contextmanager
def patched_generate_data(ccp_sample_size: int | None):
    original_generate_data = cfg.generate_data

    def generate_data_with_ccp(*args, **kwargs):
        kwargs["ccp_sample_size"] = ccp_sample_size
        return original_generate_data(*args, **kwargs)

    cfg.generate_data = generate_data_with_ccp
    try:
        yield
    finally:
        cfg.generate_data = original_generate_data


@contextmanager
def patched_generate_scenarios(settings: dict[str, Any]):
    original_generate_scenarios = cfg.generate_scenarios

    def generate_scenarios_with_settings(*args, **kwargs):
        kwargs.setdefault("demand_multiplier", settings["demand_multiplier"])
        kwargs.setdefault("road_capacity_multiplier", settings["road_capacity_multiplier"])
        kwargs.setdefault("hospital_capacity_multiplier", settings["hospital_capacity_multiplier"])
        kwargs.setdefault("num_periods", settings["time_periods"])
        return original_generate_scenarios(*args, **kwargs)

    cfg.generate_scenarios = generate_scenarios_with_settings
    try:
        yield
    finally:
        cfg.generate_scenarios = original_generate_scenarios


def estimate_counts(settings: dict[str, Any]) -> dict[str, int]:
    full_i = csv_row_count(ROOT_DIR / "data" / cfg.DISASTER_CSV)
    full_j = csv_row_count(ROOT_DIR / "data" / cfg.CCP_CSV)
    full_h = csv_row_count(ROOT_DIR / "data" / cfg.HOSPITAL_CSV)
    ratio = float(settings["sample_ratio"])
    ccp_size = settings["ccp_sample_size"]
    return {
        "I": max(1, math.ceil(full_i * ratio)) if ratio < 1.0 else full_i,
        "J": min(ccp_size, full_j) if ccp_size is not None else full_j,
        "H": max(1, math.ceil(full_h * ratio)) if ratio < 1.0 else full_h,
    }


def run_one_case(sp_module: Any, run_idx: int, total_runs: int, axis_value: Any) -> dict[str, Any]:
    settings = build_case(axis_value)
    validate_case(settings)
    counts = estimate_counts(settings)
    test_id = f"{EXPERIMENT_AXIS}_{fmt_value(axis_value)}".replace(".", "p")

    row = blank_row()
    row.update(
        {
            "test_id": test_id,
            "axis": EXPERIMENT_AXIS,
            "axis_value": fmt_value(axis_value),
            "sample_ratio": fmt_value(settings["sample_ratio"]),
            "I": counts["I"],
            "J": counts["J"],
            "H": counts["H"],
            "S": settings["scenarios"],
            "T": settings["time_periods"],
            "demand_multiplier": fmt_value(settings["demand_multiplier"]),
            "road_capacity_multiplier": fmt_value(settings["road_capacity_multiplier"]),
            "hospital_capacity_multiplier": fmt_value(settings["hospital_capacity_multiplier"]),
            "status": "RUNNING",
            "note": "",
        }
    )

    print(
        f"\n[{run_idx}/{total_runs}] {test_id} | "
        f"I={counts['I']}, J={counts['J']}, H={counts['H']}, "
        f"S={settings['scenarios']}, T={settings['time_periods']}"
    )

    logs_before = snapshot_logs()
    wall_start = time.time()
    model = None
    summary = None
    log_path = None

    try:
        with (
            temporary_config(settings),
            patched_generate_data(settings["ccp_sample_size"]),
            patched_generate_scenarios(settings),
        ):
            model, summary = sp_module.run_sp_model(
                scenario_size=settings["scenarios"],
                sample_ratio=settings["sample_ratio"],
                time_limit=TIME_LIMIT,
                mip_gap=MIP_GAP,
            )
    finally:
        log_path = newest_created_log(logs_before)

    wall_s = time.time() - wall_start
    row["wall_s"] = format_float(wall_s, digits=1)
    row["log_path"] = str(log_path) if log_path is not None else "NA"

    if model is None:
        row["status"] = "STOP"
        row["note"] = "INFEASIBLE / no solution / no model returned"
        return row

    parsed = model_fallback_summary(model)
    parsed.update(parse_log_summary(log_path))

    row["cpu_s"] = format_float(parsed.get("cpu_s"), digits=2)
    row["gap_pct"] = format_float(parsed.get("gap_pct"), digits=4)
    row["obj_value"] = format_float(parsed.get("obj_value"), digits=2)
    row["best_ub"] = format_float(parsed.get("best_ub"), digits=2)
    row["best_lb"] = format_float(parsed.get("best_lb"), digits=2)

    if summary is not None:
        row["vss_pct"] = format_float(summary.get("VSS_pct"), digits=4)
        row["evpi_pct"] = format_float(summary.get("EVPI_pct"), digits=4)

    gap_pct = parsed.get("gap_pct")
    cpu_s = parsed.get("cpu_s")
    stop_reasons = []
    if gap_pct is not None and gap_pct > GAP_STOP_PCT:
        stop_reasons.append(f"Final Gap {gap_pct:.2f}% > {GAP_STOP_PCT:.2f}%")
    if cpu_s is not None and cpu_s > CPU_STOP_SEC:
        stop_reasons.append(f"CPU Time {cpu_s:.2f}s > {CPU_STOP_SEC:.2f}s")

    if stop_reasons:
        row["status"] = "STOP"
        row["note"] = "; ".join(stop_reasons)
    else:
        row["status"] = "OK"

    print(
        f"  status={row['status']} | CPU={row['cpu_s']}s | "
        f"Gap={row['gap_pct']}% | UB={row['best_ub']} | "
        f"VSS={row['vss_pct']}% | EVPI={row['evpi_pct']}%"
    )
    if row["note"]:
        print(f"  note: {row['note']}")

    return row


def print_header(csv_path: Path) -> None:
    base = base_case_settings()
    print("=" * 80)
    print("SP BATCH EXPERIMENT RUNNER")
    print(f"Start: {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Axis: {EXPERIMENT_AXIS} = {EXPERIMENT_VALUES}")
    print(
        "Base: "
        f"S={base['scenarios']}, J={fmt_value(base['ccp_sample_size'])}, "
        f"sample={base['sample_ratio']}, T={base['time_periods']}, "
        f"D={base['demand_multiplier']}, R={base['road_capacity_multiplier']}, "
        f"H={base['hospital_capacity_multiplier']}"
    )
    print(
        f"Solver: time_limit={TIME_LIMIT:.0f}s, mip_gap={MIP_GAP:g}; "
        f"stop if gap>{GAP_STOP_PCT:g}% or CPU>{CPU_STOP_SEC:g}s"
    )
    print(f"Output CSV: {csv_path}")
    print("=" * 80)


def print_summary(rows: list[dict[str, Any]], csv_path: Path) -> None:
    print("\n" + "=" * 80)
    print("SUMMARY")
    header = (
        f"{'ID':>20} | {'I':>4} {'J':>4} {'H':>4} | {'S':>3} {'T':>3} | "
        f"{'CPU(s)':>9} | {'Gap%':>9} | {'Status':>6} | Note"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['test_id']:>20} | {str(row['I']):>4} {str(row['J']):>4} {str(row['H']):>4} | "
            f"{str(row['S']):>3} {str(row['T']):>3} | {str(row['cpu_s']):>9} | "
            f"{str(row['gap_pct']):>9} | {str(row['status']):>6} | {row['note']}"
        )
    print("=" * 80)
    print(f"Results: {csv_path}")
    print(f"End: {dt.datetime.now():%Y-%m-%d %H:%M:%S}")


def main() -> None:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = ROOT_DIR / f"{RESULT_PREFIX}_{EXPERIMENT_AXIS}_{timestamp}.csv"
    rows: list[dict[str, Any]] = []

    sp_module = load_sp_module()
    print_header(csv_path)

    for run_idx, axis_value in enumerate(EXPERIMENT_VALUES, start=1):
        try:
            row = run_one_case(sp_module, run_idx, len(EXPERIMENT_VALUES), axis_value)
        except Exception as exc:
            row = blank_row()
            row.update(
                {
                    "test_id": f"{EXPERIMENT_AXIS}_{fmt_value(axis_value)}",
                    "axis": EXPERIMENT_AXIS,
                    "axis_value": fmt_value(axis_value),
                    "status": "STOP",
                    "note": f"ERROR: {exc}",
                }
            )
            print(f"  ERROR: {exc}")

        rows.append(row)
        write_results(csv_path, rows)

        if row["status"] == "STOP":
            remaining = [fmt_value(value) for value in EXPERIMENT_VALUES[run_idx:]]
            if remaining:
                print(f"  Skipping remaining cases: {', '.join(remaining)}")
            if STOP_ON_ERROR:
                break

    print_summary(rows, csv_path)


if __name__ == "__main__":
    main()
