"""Chinese Markdown summaries for tiny case outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CASE_PURPOSE_ZH = {
    "deterministic_baseline": "基準案例：檢查基本流量平衡、first-stage linking 與 L_Amb 限定變數。",
    "all_capacities_sufficient": "容量充足案例：確認外生容量寬鬆時 RM 與 WAT 維持低或為零。",
    "road_disruption": "道路中斷案例：確認中斷的災區到 CCP 道路上 FI 為零，RM 增加。",
    "hospital_capacity_bottleneck": "醫院容量瓶頸案例：確認醫院接收容量為零時 FO 被擋住，WAT 增加。",
    "ambulance_bottleneck": "救護車瓶頸案例：確認 CCP ambulance capacity 會限制 moderate/severe 的 FI。",
    "treatment_time_boundary": "治療時間邊界案例：確認 t - tau_l < 1 時 completion term 視為零。",
}


def _load(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_case_summary_zh(result_json: str | Path, output_path: str | Path) -> Path:
    result = _load(result_json)
    case = result.get("instance", Path(result_json).stem.replace("_results", ""))
    validator = result.get("validator_summary", {})
    lines = [
        f"# {case} 結果摘要",
        "",
        f"- 案例目的：{CASE_PURPOSE_ZH.get(case, ' tiny case validation ')}",
        f"- Gurobi status：{result.get('gurobi_status', '未記錄')}",
        f"- Objective：{result.get('objective_value')}",
        f"- First-stage cost：{result.get('first_stage_cost')}",
        f"- Expected second-stage cost：{result.get('expected_second_stage_cost')}",
        f"- Validator passed：{validator.get('passed')}",
        "",
        "## First-stage Variables",
        "",
    ]
    for group, values in result.get("first_stage_variables", {}).items():
        lines.append(f"- `{group}`：`{values}`")
    lines += ["", "## Constraint Max Violations", ""]
    for family, value in result.get("constraint_family_max_violation", {}).items():
        lines.append(f"- `{family}`：{value}")
    lines += [
        "",
        "## Note",
        "",
        "此摘要只整理既有求解結果，不改變模型、參數、case 定義或 objective。",
    ]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_diagnostic_summary_zh(diagnostic_json: str | Path, output_path: str | Path) -> Path:
    report = _load(diagnostic_json)
    lines = [
        "# Tiny Case 中文診斷報告",
        "",
        "此報告只整理 diagnostics 結果，不改變模型或求解結果。",
        "",
    ]
    for case, data in report.get("cases", {}).items():
        lines += [f"## {case}", ""]
        if "missing_results" in data:
            lines += [f"- 缺少結果檔：`{data['missing_results']}`", ""]
            continue
        objective = data.get("objective", {})
        lines += [
            f"- Objective：{objective.get('objective_value')}",
            f"- First-stage cost：{objective.get('first_stage_cost')}",
            f"- Expected second-stage cost：{objective.get('expected_second_stage_cost')}",
            f"- Variable totals：`{data.get('variable_totals')}`",
            "",
            "### Case Checks",
            "",
        ]
        for check in data.get("case_checks", []):
            status = "通過" if check.get("passed") else "未通過"
            detail = f"；{check.get('detail')}" if check.get("detail") else ""
            lines.append(f"- {status}: `{check.get('name')}`{detail}")
        lines += ["", "### Binding Constraints", ""]
        for family, summary in data.get("constraint_binding_summary", {}).items():
            lines.append(
                f"- `{family}`：binding 數量 {summary.get('num_binding_constraints')}, "
                f"min_slack={summary.get('min_slack')}, max_slack={summary.get('max_slack')}"
            )
        lines.append("")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path

