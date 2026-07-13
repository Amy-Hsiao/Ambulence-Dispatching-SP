"""Run the small/medium/large S=30 B&BC stress test requested for 2026-07-13."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_RUNNER_PATH = ROOT_DIR / "run experiment" / "batch_stress_test.py"
OUTPUT_DIR = ROOT_DIR / "experiment result"
RESULT_BASENAME = "Stress Test_Different Scale_B&BC_20260713"
SNAPSHOT_PATH = ROOT_DIR / "run experiment" / "stress_scale_rows.json"
BUILDER_PATH = ROOT_DIR / "run experiment" / "build_stress_scale_xlsx.mjs"
PREVIEW_PATH = ROOT_DIR / "run experiment" / "stress_scale_preview.png"
DEFAULT_NODE = Path(
    r"C:\Users\Amy\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
)

# Allow the bundled Python packages to make this file runnable directly from a
# clean terminal, without the former supervisor wrapper.
PYTHON_PACKAGES = ROOT_DIR / ".codex_spreadsheet" / "python_packages"
if PYTHON_PACKAGES.exists() and str(PYTHON_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PYTHON_PACKAGES))


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
    """Persist an atomic snapshot; the same script builds Excel on exit."""
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_dir = ROOT_DIR / "run experiment"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    temp_path = SNAPSHOT_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, SNAPSHOT_PATH)
    print(f"[xlsx] result snapshot updated ({len(rows)} row(s))")


def _find_node() -> Path | None:
    """Find the bundled Node runtime, or a node executable on PATH."""
    env_node = os.environ.get("CODEX_NODE")
    candidates = [Path(env_node)] if env_node else []
    candidates.extend([DEFAULT_NODE, Path(shutil.which("node"))] if shutil.which("node") else [DEFAULT_NODE])
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None


def build_final_excel() -> None:
    """Build the final workbook from the latest snapshot in this same process."""
    if not SNAPSHOT_PATH.exists():
        print(f"[xlsx] no snapshot found; Excel was not built: {SNAPSHOT_PATH}")
        return
    if not BUILDER_PATH.exists():
        print(f"[xlsx] builder not found; Excel was not built: {BUILDER_PATH}")
        return
    node = _find_node()
    if node is None:
        print("[xlsx] Node.js not found; set CODEX_NODE or add node to PATH")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{RESULT_BASENAME}.xlsx"
    command = [str(node), str(BUILDER_PATH), str(SNAPSHOT_PATH), str(output_path), str(PREVIEW_PATH)]
    try:
        result = subprocess.run(command, cwd=ROOT_DIR, check=False)
    except OSError as exc:
        print(f"[xlsx] failed to launch Node builder: {exc}")
        return
    print(f"[xlsx] builder exit code: {result.returncode}")
    if result.returncode == 0:
        print(f"[xlsx] final workbook: {output_path}")


runner.export_xlsx = export_xlsx


if __name__ == "__main__":
    print("B&BC enhancements: multi-cut, root seeding, user/root cuts, EV warm start, ")
    print("Pareto cuts, branch priority, and parallel oracles are all enabled.")
    try:
        runner.main()
    finally:
        # This also preserves a partial workbook if the runner exits after a
        # case-level error or is interrupted after a snapshot was written.
        build_final_excel()
