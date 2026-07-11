#!/usr/bin/env python3
"""B&BC acceleration ablation runner（實驗三，plan/12）。

固定同一個隨機 instance，依序比較 BBC、BBC+WS、BBC+RS、BBC+UC、BBC-Full，
模型為純 SP 與 SP+MCVaR+DRO(box)。每個 case 後即重寫 raw CSV 與六分頁 Excel；
單一 case 失敗會留下 FAIL 記錄並繼續。
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import math
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


# =============================================================================
# Parameter setting area
# =============================================================================

BASE_SCENARIOS = 30
BASE_CCP_SAMPLE_SIZE = None
BASE_SAMPLE_RATIO = 1.0
BASE_TIME_PERIODS = 8
BASE_DEMAND_MULTIPLIER = 1.0
BASE_ROAD_CAPACITY_MULTIPLIER = 1.0
BASE_HOSPITAL_CAPACITY_MULTIPLIER = 1.0

RISK_ALPHA = 0.9
RISK_LAMBDA = 0.5
DRO_BOX_SCOPE = 0.01

TIME_LIMIT = 3600.0
MIP_GAP = 1e-4
COMPUTE_KPIS = False
STOP_ON_ERROR = False

RESULT_PREFIX = "BBC_ablation"
LOG_SUBDIR_NAME = "bbc ablation"


# =============================================================================
# Setup
# =============================================================================

ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "logs"
LOG_SUBDIR = LOG_DIR / LOG_SUBDIR_NAME
RESULT_DIR = ROOT_DIR / "experiment result"

os.chdir(ROOT_DIR)
for _p in (str(ROOT_DIR / "model core"), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as cfg  # noqa: E402

SP_MODEL_PATH = ROOT_DIR / "model portal" / "benders bbc.py"
DRO_MODEL_PATH = ROOT_DIR / "model portal" / "dro bbc.py"

DEFAULT_ROOT_SEED_ITERS = int(cfg.BENDERS_ROOT_SEED_ITERS)
DEFAULT_ROOT_CUT_ROUNDS = int(cfg.BENDERS_ROOT_CUT_ROUNDS)

CONFIGS = [
    {"name": "BBC",      "ev": False, "seed": 0,                       "rounds": 0,                       "user": False, "pareto": False},
    {"name": "BBC+WS",   "ev": True,  "seed": 0,                       "rounds": 0,                       "user": False, "pareto": False},
    {"name": "BBC+RS",   "ev": True,  "seed": DEFAULT_ROOT_SEED_ITERS, "rounds": 0,                       "user": False, "pareto": False},
    {"name": "BBC+UC",   "ev": True,  "seed": DEFAULT_ROOT_SEED_ITERS, "rounds": DEFAULT_ROOT_CUT_ROUNDS, "user": True,  "pareto": False},
    {"name": "BBC-Full", "ev": True,  "seed": DEFAULT_ROOT_SEED_ITERS, "rounds": DEFAULT_ROOT_CUT_ROUNDS, "user": True,  "pareto": True},
]
MODELS = ["SP", "DRO-box"]

FIELDNAMES = [
    "test_id", "model", "config", "I", "J", "H", "S", "T",
    "obj_value", "first_stage_decision", "best_lb", "best_ub", "cpu_s",
    "wall_s", "num_vars", "num_constrs", "nodes", "iterations", "gap_pct",
    "total_cuts", "seed_cuts", "lazy_cuts", "user_cuts", "root_seed_lb",
    "root_seed_iters_done", "root_cut_rounds_done", "ev_warm_start",
    "root_seed_iters", "root_cut_rounds", "use_user_cuts", "pareto_enabled",
    "multi_cut", "parallel_oracles", "oracle_solves", "incumbent_evals",
    "callback_time_s", "solver_status", "log_path", "status", "note",
]

DETAIL_COLUMNS = [
    ("|I| Disaster", "I"), ("|J| CCP", "J"), ("|H| Hosp", "H"),
    ("|S| Scen", "S"), ("|T| Per", "T"), ("obj_value", "obj_value"),
    ("First Stage Decision", "first_stage_decision"), ("Best LB", "best_lb"),
    ("Best UB", "best_ub"), ("CPU Time(s)", "cpu_s"),
    ("num_vars", "num_vars"), ("num_constrs", "num_constrs"),
    ("Nodes", "nodes"), ("Iteration", "iterations"),
    ("Final Gap(%)", "gap_pct"), ("Total Cuts", "total_cuts"),
    ("Seed Cuts", "seed_cuts"), ("Lazy Cuts", "lazy_cuts"),
    ("User Cuts", "user_cuts"), ("Seeded LB(root)", "root_seed_lb"),
    ("model", "model"), ("config", "config"), ("status", "status"),
]
TEXT_KEYS = {"first_stage_decision", "model", "config", "status"}


def blank_row() -> dict[str, Any]:
    return {key: "NA" for key in FIELDNAMES}


def load_portal(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load portal: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return max(0, sum(1 for row in csv.reader(f) if any(row)) - 1)


def estimate_counts() -> dict[str, int]:
    full_i = csv_row_count(ROOT_DIR / "data" / cfg.DISASTER_CSV)
    full_j = csv_row_count(ROOT_DIR / "data" / cfg.CCP_CSV)
    full_h = csv_row_count(ROOT_DIR / "data" / cfg.HOSPITAL_CSV)
    ratio = float(BASE_SAMPLE_RATIO)
    return {
        "I": full_i if ratio >= 1.0 else max(1, math.ceil(full_i * ratio)),
        "J": full_j if BASE_CCP_SAMPLE_SIZE is None else min(BASE_CCP_SAMPLE_SIZE, full_j),
        "H": full_h if ratio >= 1.0 else max(1, math.ceil(full_h * ratio)),
    }


def first_stage_string(fs: dict[str, Any] | None) -> str:
    if not fs:
        return "NA"
    supply: dict[str, float] = {}
    for (h, j), value in fs["Y"].items():
        supply[j] = supply.get(j, 0.0) + float(value)
    lines = []
    for j in sorted(fs["X"]):
        if float(fs["X"][j]) > 0.5:
            lines.append(
                f"CCP {j:4s} -> X: 1, Staff(V): {float(fs['V'][j]):.0f}, "
                f"Amb(U): {float(fs['U'][j]):.0f}, MedicalSupply(Y): {supply.get(j, 0.0):.2f}"
            )
    return "\n".join(lines) if lines else "none opened"


def snapshot_logs() -> set[Path]:
    return {p.resolve() for p in LOG_DIR.glob("*.log")} if LOG_DIR.exists() else set()


def move_newest_log(before: set[Path]) -> Path | None:
    created = [p for p in LOG_DIR.glob("*.log") if p.resolve() not in before]
    if not created:
        return None
    source = max(created, key=lambda p: p.stat().st_mtime)
    LOG_SUBDIR.mkdir(parents=True, exist_ok=True)
    dest = LOG_SUBDIR / source.name
    shutil.move(str(source), str(dest))
    return dest


@contextmanager
def temporary_config(case: dict[str, Any]):
    values = {
        "SCENARIOS": BASE_SCENARIOS,
        "TIME_PERIODS": BASE_TIME_PERIODS,
        "SAMPLE_RATIO": BASE_SAMPLE_RATIO,
        "SP_SAMPLE_RATIO": BASE_SAMPLE_RATIO,
        "DEMAND_MULTIPLIER": BASE_DEMAND_MULTIPLIER,
        "ROAD_CAPACITY_MULTIPLIER": BASE_ROAD_CAPACITY_MULTIPLIER,
        "HOSPITAL_CAPACITY_MULTIPLIER": BASE_HOSPITAL_CAPACITY_MULTIPLIER,
        "SP_TIME_LIMIT": TIME_LIMIT,
        "SP_MIP_GAP": MIP_GAP,
        "BENDERS_MULTI_CUT": True,
        "BENDERS_EV_WARM_START": case["ev"],
        "BENDERS_ROOT_SEED_ITERS": case["seed"],
        "BENDERS_ROOT_CUT_ROUNDS": case["rounds"],
        "BENDERS_USE_USER_CUTS": case["user"],
        "BENDERS_PARETO_ENABLED": case["pareto"],
    }
    if hasattr(cfg, "CCP_SAMPLE_SIZE"):
        values["CCP_SAMPLE_SIZE"] = BASE_CCP_SAMPLE_SIZE
    original = {key: getattr(cfg, key) for key in values}
    try:
        for key, value in values.items():
            setattr(cfg, key, value)
        yield
    finally:
        for key, value in original.items():
            setattr(cfg, key, value)


@contextmanager
def cached_instance_generation():
    """讓全部 10 cases 共用同一個由 MASTER_SEED 產生的 instance。"""
    original = cfg.generate_data
    cache: dict[tuple[Any, ...], Any] = {}

    def _cached(*args, **kwargs):
        kwargs.setdefault("ccp_sample_size", BASE_CCP_SAMPLE_SIZE)
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = original(*args, **kwargs)
        return cache[key]

    cfg.generate_data = _cached
    try:
        yield
    finally:
        cfg.generate_data = original


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def excel_value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key, "NA")
    if key in TEXT_KEYS:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def export_xlsx(rows: list[dict[str, Any]], path: Path) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        print("  [xlsx] openpyxl 未安裝，略過 Excel 匯出")
        return

    try:
        wb = Workbook()
        wb.remove(wb.active)
        fill = PatternFill("solid", fgColor="2E74B5")
        font = Font(bold=True, color="FFFFFF")

        for case in CONFIGS:
            ws = wb.create_sheet(case["name"])
            for col, (title, _key) in enumerate(DETAIL_COLUMNS, 1):
                cell = ws.cell(1, col, title)
                cell.fill, cell.font = fill, font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            out_row = 2
            for row in rows:
                if row.get("config") != case["name"]:
                    continue
                for col, (_title, key) in enumerate(DETAIL_COLUMNS, 1):
                    cell = ws.cell(out_row, col, excel_value(row, key))
                    if key == "first_stage_decision":
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                out_row += 1
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = f"A1:W{max(1, out_row - 1)}"
            ws.row_dimensions[1].height = 34
            for col in range(1, len(DETAIL_COLUMNS) + 1):
                ws.column_dimensions[ws.cell(1, col).column_letter].width = 14
            ws.column_dimensions["G"].width = 62
            ws.column_dimensions["U"].width = 14
            ws.column_dimensions["V"].width = 14
            for data_row in range(2, out_row):
                for col, (_title, key) in enumerate(DETAIL_COLUMNS, 1):
                    cell = ws.cell(data_row, col)
                    if key in {"obj_value", "best_lb", "best_ub"}:
                        cell.number_format = "#,##0.0000"
                    elif key in {"cpu_s", "gap_pct"}:
                        cell.number_format = "#,##0.0000"
                    elif key not in TEXT_KEYS:
                        cell.number_format = "#,##0"

        ws = wb.create_sheet("ablation_table")
        ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
        ws.cell(1, 1, "model")
        for idx, case in enumerate(CONFIGS):
            start = 2 + idx * 3
            ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=start + 2)
            ws.cell(1, start, case["name"])
            for offset, title in enumerate(("Time", "Gap(%)", "Nodes")):
                ws.cell(2, start + offset, title)
        for row_idx, model_name in enumerate(MODELS, 3):
            ws.cell(row_idx, 1, model_name)
            for idx, case in enumerate(CONFIGS):
                match = next((r for r in rows if r.get("model") == model_name
                              and r.get("config") == case["name"]), None)
                start = 2 + idx * 3
                if match is None:
                    values = ("NA", "NA", "NA")
                elif match.get("status") != "OK":
                    values = ("FAIL", "FAIL", "FAIL")
                else:
                    values = tuple(excel_value(match, key) for key in ("cpu_s", "gap_pct", "nodes"))
                for offset, value in enumerate(values):
                    ws.cell(row_idx, start + offset, value)

        for row in ws.iter_rows(min_row=1, max_row=2):
            for cell in row:
                cell.fill, cell.font = fill, font
                cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions["A"].width = 14
        for col in range(2, 2 + len(CONFIGS) * 3):
            ws.column_dimensions[ws.cell(2, col).column_letter].width = 13
        ws.freeze_panes = "B3"
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
    except Exception as exc:  # noqa: BLE001
        print(f"  [xlsx] Excel 匯出失敗（不影響 CSV）: {exc}")


def run_one_case(portal: Any, model_name: str, case: dict[str, Any],
                 counts: dict[str, int], run_idx: int, total: int) -> dict[str, Any]:
    test_id = f"{model_name}_{case['name']}".replace("+", "_plus_")
    row = blank_row()
    row.update({
        "test_id": test_id, "model": model_name, "config": case["name"],
        "I": counts["I"], "J": counts["J"], "H": counts["H"],
        "S": BASE_SCENARIOS, "T": BASE_TIME_PERIODS,
        "ev_warm_start": case["ev"], "root_seed_iters": case["seed"],
        "root_cut_rounds": case["rounds"], "use_user_cuts": case["user"],
        "pareto_enabled": case["pareto"], "multi_cut": True,
        "status": "RUNNING", "note": "",
    })
    print(f"\n[{run_idx}/{total}] model={model_name} config={case['name']}")
    before = snapshot_logs()
    wall_start = time.time()
    model = summary = None
    try:
        try:
            with temporary_config(case):
                if model_name == "SP":
                    model, summary = portal.run_sp_model(
                        scenario_size=BASE_SCENARIOS, sample_ratio=BASE_SAMPLE_RATIO,
                        time_limit=TIME_LIMIT, mip_gap=MIP_GAP,
                        compute_kpis=COMPUTE_KPIS, compute_vss_evpi=False,
                    )
                else:
                    model, summary = portal.run_dro_model(
                        ambiguity_set="box", scenario_size=BASE_SCENARIOS,
                        sample_ratio=BASE_SAMPLE_RATIO, time_limit=TIME_LIMIT,
                        mip_gap=MIP_GAP, alpha=RISK_ALPHA, lam=RISK_LAMBDA,
                        scope=DRO_BOX_SCOPE, compute_kpis=COMPUTE_KPIS,
                    )
        finally:
            row["wall_s"] = f"{time.time() - wall_start:.2f}"
            log_path = move_newest_log(before)
            row["log_path"] = str(log_path) if log_path else "NA"
    except Exception as exc:  # noqa: BLE001
        row["status"] = "FAIL"
        row["note"] = f"{type(exc).__name__}: {exc}"
        print(f"  -> FAIL: {row['note']}")
        if STOP_ON_ERROR:
            raise
        return row

    if model is None or summary is None:
        row["status"], row["note"] = "FAIL", "no feasible solution (see log)"
        return row

    st = summary.get("bbc_stats", {})
    fs = summary.get("first_stage")
    objective = float(summary["objective"])
    row.update({
        "obj_value": f"{objective:.6f}",
        "first_stage_decision": first_stage_string(fs),
        "best_lb": f"{float(summary['best_lb']):.6f}",
        "best_ub": f"{objective:.6f}",
        "cpu_s": f"{float(st.get('runtime', float('nan'))):.2f}",
        "num_vars": getattr(model, "NumVars", "NA"),
        "num_constrs": getattr(model, "NumConstrs", "NA"),
        "nodes": f"{float(getattr(model, 'NodeCount', float('nan'))):.0f}",
        "iterations": f"{float(getattr(model, 'IterCount', float('nan'))):.0f}",
        "gap_pct": f"{float(summary['gap_pct']):.6f}",
        "total_cuts": st.get("cuts_added", "NA"),
        "seed_cuts": st.get("seed_cuts_added", "NA"),
        "lazy_cuts": st.get("lazy_cuts_added", "NA"),
        "user_cuts": st.get("user_cuts_added", "NA"),
        "root_seed_lb": st.get("root_seed_lb", "NA"),
        "root_seed_iters_done": st.get("root_seed_iters_done", "NA"),
        "root_cut_rounds_done": st.get("root_cut_rounds_done", "NA"),
        "parallel_oracles": st.get("parallel_oracles", getattr(cfg, "BENDERS_PARALLEL_ORACLES", "NA")),
        "oracle_solves": st.get("oracle_solves", "NA"),
        "incumbent_evals": st.get("incumbent_evals", "NA"),
        "callback_time_s": st.get("callback_time", "NA"),
        "solver_status": st.get("solver_status", "NA"),
        "status": "OK",
    })
    try:
        model.dispose()
    except Exception:  # noqa: BLE001
        pass
    print(f"  -> OK obj={row['obj_value']} time={row['cpu_s']}s gap={row['gap_pct']}%")
    return row


def objective_warnings(rows: list[dict[str, Any]]) -> list[str]:
    warnings = []
    for model_name in MODELS:
        successful = [r for r in rows if r.get("model") == model_name and r.get("status") == "OK"]
        if len(successful) < 2:
            continue
        reference = successful[0]
        ref_obj = float(reference["obj_value"])
        ref_gap = float(reference["gap_pct"]) / 100.0
        for row in successful[1:]:
            obj = float(row["obj_value"])
            gap = float(row["gap_pct"]) / 100.0
            tolerance = abs(ref_obj) * ref_gap + abs(obj) * gap + 1e-6
            if abs(obj - ref_obj) > tolerance:
                warnings.append(
                    f"{model_name}: {reference['config']} vs {row['config']} objective "
                    f"不一致 ({ref_obj:.6f} vs {obj:.6f}, tol={tolerance:.6f})"
                )
    return warnings


def main() -> None:
    if DRO_BOX_SCOPE > 1.0 / BASE_SCENARIOS + 1e-12:
        raise ValueError(
            f"DRO_BOX_SCOPE={DRO_BOX_SCOPE} > 1/S={1.0 / BASE_SCENARIOS:.6f}"
        )

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULT_DIR / f"{RESULT_PREFIX}_raw_{timestamp}.csv"
    xlsx_path = RESULT_DIR / f"{RESULT_PREFIX}_{timestamp}.xlsx"
    counts = estimate_counts()
    expected = {"I": 129, "J": 10, "H": 16}
    if counts != expected:
        print(f"[WARN] 目前資料規模 {counts} 與 plan/12 指定 {expected} 不同。")

    print("=" * 72)
    print("B&BC ABLATION EXPERIMENT (實驗三)")
    print("=" * 72)
    print(f"configs={[case['name'] for case in CONFIGS]}")
    print(f"models={MODELS} S={BASE_SCENARIOS} T={BASE_TIME_PERIODS}")
    print(f"mip_gap={MIP_GAP} time_limit={TIME_LIMIT} cases={len(CONFIGS) * len(MODELS)}")
    print(f"CSV   : {csv_path}\nExcel : {xlsx_path}")

    sp_portal = load_portal(SP_MODEL_PATH, "ablation_sp_portal")
    dro_portal = load_portal(DRO_MODEL_PATH, "ablation_dro_portal")
    portals = {"SP": sp_portal, "DRO-box": dro_portal}
    rows: list[dict[str, Any]] = []
    total = len(CONFIGS) * len(MODELS)

    # 依規格：同一模型的五個配置連續跑；所有 cases 共用同一 cached instance。
    with cached_instance_generation():
        run_idx = 0
        for model_name in MODELS:
            for case in CONFIGS:
                run_idx += 1
                row = run_one_case(portals[model_name], model_name, case, counts, run_idx, total)
                rows.append(row)
                write_results(csv_path, rows)
                export_xlsx(rows, xlsx_path)

    warnings = objective_warnings(rows)
    print("\n" + "=" * 72)
    print(f"Done: {sum(r['status'] == 'OK' for r in rows)}/{len(rows)} cases OK")
    for warning in warnings:
        print(f"[WARN] {warning}")
    print(f"CSV   : {csv_path}\nExcel : {xlsx_path}")


if __name__ == "__main__":
    main()
