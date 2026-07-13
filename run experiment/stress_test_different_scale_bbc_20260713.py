"""Run the small/medium/large S=30 B&BC stress test requested for 2026-07-13."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_RUNNER_PATH = ROOT_DIR / "run experiment" / "batch_stress_test.py"
OUTPUT_DIR = ROOT_DIR / "experiment result"
RESULT_BASENAME = "Stress Test_Different Scale_B&BC_20260713"


def _load_base_runner():
    spec = importlib.util.spec_from_file_location("scale_stress_base", BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load base runner: {BASE_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_base_runner()

# Experiment design.
runner.EXPERIMENT_AXIS = "scale"
runner.EXPERIMENT_VALUES = ["small", "medium", "large"]
runner.BASE_SCENARIOS = 30
runner.BASE_TIME_PERIODS = 8
runner.TIME_LIMIT = 3600.0
runner.MIP_GAP = 0.01
runner.STOP_ON_ERROR = False  # Always attempt all three scales.
runner.RESULT_BASENAME = RESULT_BASENAME
runner.RESULT_DIR = OUTPUT_DIR
runner.LOG_SUBDIR_NAME = RESULT_BASENAME
runner.LOG_SUBDIR = runner.LOG_DIR / RESULT_BASENAME

# Explicitly enable every B&BC enhancement represented by the ablation design.
runner.cfg.SOLVER_ENGINE = "lshaped"
runner.cfg.BENDERS_MULTI_CUT = True
runner.cfg.BENDERS_ROOT_SEED_ADAPTIVE = True
runner.cfg.BENDERS_ROOT_SEED_ITERS = max(1, int(runner.cfg.BENDERS_ROOT_SEED_ITERS))
runner.cfg.BENDERS_USE_USER_CUTS = True
runner.cfg.BENDERS_ROOT_CUT_ROUNDS = max(1, int(runner.cfg.BENDERS_ROOT_CUT_ROUNDS))
runner.cfg.BENDERS_EV_WARM_START = True
runner.cfg.BENDERS_PARETO_ENABLED = True
runner.cfg.BENDERS_X_BRANCH_PRIORITY_ENABLED = True
runner.cfg.BENDERS_PARALLEL_ORACLES = max(1, int(runner.cfg.BENDERS_PARALLEL_ORACLES))


def export_xlsx(rows, xlsx_path: Path) -> None:
    """Persist an atomic result snapshot; the detached supervisor builds Excel."""
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_dir = ROOT_DIR / "run experiment"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    json_path = scratch_dir / "stress_scale_rows.json"
    temp_path = json_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, json_path)
    print(f"[xlsx] result snapshot updated ({len(rows)} row(s)); final workbook is built after all cases")


runner.export_xlsx = export_xlsx


if __name__ == "__main__":
    print("B&BC enhancements: multi-cut, root seeding, user/root cuts, EV warm start, ")
    print("Pareto cuts, branch priority, and parallel oracles are all enabled.")
    runner.main()
