"""Run the stress test, then isolate final Excel authoring from the solver process."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run experiment" / "stress_test_different_scale_bbc_20260713.py"
LOG_DIR = ROOT / "logs" / "Stress Test_Different Scale_B&BC_20260713"
JSON_PATH = ROOT / "run experiment" / "stress_scale_rows.json"
BUILDER = ROOT / "run experiment" / "build_stress_scale_xlsx.mjs"
NODE = Path(r"C:\Users\Amy\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
OUTPUT = ROOT / "experiment result" / "Stress Test_Different Scale_B&BC_20260713.xlsx"
PREVIEW = ROOT / "run experiment" / "stress_scale_preview.png"
PYTHON_PACKAGES = ROOT / ".codex_spreadsheet" / "python_packages"

LOG_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH.unlink(missing_ok=True)
child_env = os.environ.copy()
child_env["PYTHONPATH"] = str(PYTHON_PACKAGES) + os.pathsep + child_env.get("PYTHONPATH", "")
with (LOG_DIR / "runner_stdout.log").open("w", encoding="utf-8", buffering=1) as stdout, (
    LOG_DIR / "runner_stderr.log"
).open("w", encoding="utf-8", buffering=1) as stderr:
    solve = subprocess.run(
        [sys.executable, "-u", str(RUNNER)],
        cwd=ROOT,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        env=child_env,
        check=False,
    )
    stdout.write(f"\n[supervisor] solver runner exit code: {solve.returncode}\n")
    stdout.flush()
    if JSON_PATH.exists():
        excel = subprocess.run(
            [str(NODE), str(BUILDER), str(JSON_PATH), str(OUTPUT), str(PREVIEW)],
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        stdout.write(f"\n[supervisor] Excel builder exit code: {excel.returncode}\n")
        stdout.flush()
    else:
        stderr.write("[supervisor] No result snapshot was produced; Excel was not rebuilt.\n")
