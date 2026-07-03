from __future__ import annotations

import re
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Iterable

import config


# Phase R 重構：logging_utils.py 移入 model core/，LOG_DIR 改以檔案位置定位專案根
# （原 Path("logs") 相對 cwd）；log 仍寫到專案根的 logs/
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _format_value(value: Any) -> str:
    if value is None:
        return "ALL"
    text = str(value)
    text = text.replace(".", "p")
    text = text.replace("-", "m")
    return text


def _safe_filename_part(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\s]+', "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "run"


def _unique_log_path(base_name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename_part(base_name)
    path = LOG_DIR / f"{safe_name}.log"
    if not path.exists():
        return path

    run_idx = 2
    while True:
        candidate = LOG_DIR / f"{safe_name}_r{run_idx:02d}.log"
        if not candidate.exists():
            return candidate
        run_idx += 1


def build_sp_log_path(scenario_size, sample_ratio, time_limit, mip_gap) -> Path:
    used = "ALL" if scenario_size is None else scenario_size
    base_name = (
        f"SP_seed{config.MASTER_SEED}"
        f"_scen{config.SCENARIOS}"
        f"_used{used}"
        f"_period{config.TIME_PERIODS}"
        f"_sample{_format_value(sample_ratio)}"
        f"_D{_format_value(config.DEMAND_MULTIPLIER)}"
        f"_R{_format_value(config.ROAD_CAPACITY_MULTIPLIER)}"
        f"_H{_format_value(config.HOSPITAL_CAPACITY_MULTIPLIER)}"
        f"_tl{_format_value(time_limit)}"
        f"_gap{_format_value(mip_gap)}"
    )
    return _unique_log_path(base_name)


def build_det_log_path(sample_ratio, time_limit=3600.0, mip_gap=0.01) -> Path:
    base_name = (
        f"DET_seed{config.MASTER_SEED}"
        "_scenB00"
        f"_period{config.TIME_PERIODS}"
        f"_sample{_format_value(sample_ratio)}"
        "_D1_R1_H1"
        f"_tl{_format_value(time_limit)}"
        f"_gap{_format_value(mip_gap)}"
    )
    return _unique_log_path(base_name)


def print_run_metadata(
    model_type: str,
    instance: dict[str, Any],
    settings: Iterable[tuple[str, Any]],
    multipliers_override: dict[str, Any] | None = None,
) -> None:
    metadata = instance["metadata"]
    counts = metadata["sampled_counts"]
    multipliers = multipliers_override or metadata["multipliers"]

    print("=" * 50)
    print("RUN METADATA")
    print("=" * 50)
    print(f"- model_type: {model_type}")
    for key, value in settings:
        print(f"- {key}: {value}")
    print(f"- master_seed: {metadata['master_seed']}")
    print(f"- num_scenarios_config: {metadata['num_scenarios']}")
    print(f"- num_periods: {metadata['num_periods']}")
    print(f"- sample_ratio: {metadata['sample_ratio']}")
    print(f"- sampled_disaster_areas: {counts['disaster_areas']}")
    print(f"- sampled_ccps: {counts['ccps']}")
    print(f"- sampled_hospitals: {counts['hospitals']}")
    print(f"- demand_multiplier: {multipliers['demand_multiplier']}")
    print(f"- road_capacity_multiplier: {multipliers['road_capacity_multiplier']}")
    print(f"- hospital_capacity_multiplier: {multipliers['hospital_capacity_multiplier']}")
    print("=" * 50)


@contextmanager
def tee_output(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as log_file:
        tee_stdout = TeeStream(sys.stdout, log_file)
        tee_stderr = TeeStream(sys.stderr, log_file)
        with redirect_stdout(tee_stdout), redirect_stderr(tee_stderr):
            print(f"Log file: {log_path}")
            yield
