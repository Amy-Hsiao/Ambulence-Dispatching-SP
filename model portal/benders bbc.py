"""
benders bbc.py — Multi-cut Branch-and-Benders-Cut 入口。

Phase 0 狀態：PASSTHROUGH——直接轉呼叫 extensive form 的 run_sp_model()，
輸出與 `model portal/extensive form.py` 逐字一致（Phase 0 驗收用）。
Phase 3 完成後，此檔改為呼叫 lshaped_core.solve()，輸出契約不變。
"""
import importlib.util
import sys
from pathlib import Path

# ── bootstrap：讓 model core/ 內的模組可被 import ─────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MODEL_CORE_DIR = str(PROJECT_ROOT / "model core")
if _MODEL_CORE_DIR not in sys.path:
    sys.path.insert(0, _MODEL_CORE_DIR)

import config  # noqa: E402


def _load_extensive_form():
    path = PROJECT_ROOT / "model portal" / "extensive form.py"
    spec = importlib.util.spec_from_file_location("extensive_form_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_sp_model(scenario_size=None, sample_ratio=None, time_limit=None, mip_gap=None):
    """與 extensive form 相同的介面；runner 可無縫替換。"""
    engine_ready = False   # Phase 3 完成後改為讀 lshaped_core.solve
    if not engine_ready:
        print("[benders bbc] Phase 0 passthrough：目前轉呼叫 extensive form 引擎。")
        ef = _load_extensive_form()
        return ef.run_sp_model(
            scenario_size=scenario_size,
            sample_ratio=sample_ratio,
            time_limit=time_limit,
            mip_gap=mip_gap,
        )


if __name__ == "__main__":
    run_sp_model()
