"""Launch the long-running scale stress test detached on Windows."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run experiment" / "stress_test_different_scale_bbc_20260713.py"
LOG_DIR = ROOT / "logs" / "Stress Test_Different Scale_B&BC_20260713"
LOG_DIR.mkdir(parents=True, exist_ok=True)

stdout = (LOG_DIR / "runner_stdout.log").open("w", encoding="utf-8", buffering=1)
stderr = (LOG_DIR / "runner_stderr.log").open("w", encoding="utf-8", buffering=1)
flags = (
    subprocess.DETACHED_PROCESS
    | subprocess.CREATE_NEW_PROCESS_GROUP
    | subprocess.CREATE_NO_WINDOW
)
process = subprocess.Popen(
    [sys.executable, "-u", str(SCRIPT)],
    cwd=ROOT,
    stdout=stdout,
    stderr=stderr,
    stdin=subprocess.DEVNULL,
    creationflags=flags,
    close_fds=True,
)
(LOG_DIR / "runner.pid").write_text(str(process.pid), encoding="ascii")
stdout.close()
stderr.close()
print(process.pid)
