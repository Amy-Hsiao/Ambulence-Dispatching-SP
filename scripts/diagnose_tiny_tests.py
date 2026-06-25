"""Diagnose whether tiny test solutions exercise the intended model logic."""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_tiny_tests import TEST_ORDER
from src.data.schema import has_period, hosp_cap, instance_fingerprint, periods, prev_period, u, w, xi
from src.data.tiny_generator import CASE_BUILDERS

TOL = 1e-6


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _latest_result_path(result_dir: Path, case: str) -> Path | None:
    candidates = []
    standard_path = result_dir / case / "results.json"
    if standard_path.exists():
        candidates.append(standard_path)
    case_dir = result_dir / case
    if case_dir.exists():
        candidates.extend(case_dir.glob(f"{case}_results*.json"))
    candidates.extend(result_dir.glob(f"{case}_results*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def _result_value(results: dict[str, Any], group: str, *parts: Any) -> float:
    if group in results["first_stage_variables"]:
        return float(results["first_stage_variables"][group].get(_key(*parts), 0.0))
    return float(results["nonzero_second_stage_variables"][group].get(_key(*parts), 0.0))


def _total(results: dict[str, Any], group: str) -> float:
    if group in results["first_stage_variables"]:
        return sum(float(v) for v in results["first_stage_variables"][group].values())
    return sum(float(v) for v in results["nonzero_second_stage_variables"][group].values())


def _objective_components(instance: dict[str, Any], results: dict[str, Any]) -> dict[str, float]:
    sec = instance["second_stage"]
    sets = instance["sets"]
    I, J, H, L, L_Amb, S = sets["I"], sets["J"], sets["H"], sets["L"], sets["L_Amb"], sets["S"]
    T = periods(instance)
    p_s = instance["p_s"]
    rm = wat = fi = fo = 0.0
    for s in S:
        prob = float(p_s[s])
        rm += prob * sum(sec["rho_l"][l] * _result_value(results, "RM", i, l, t, s) for i in I for l in L for t in T)
        wat += prob * sum(sec["delta_l"][l] * _result_value(results, "WAT", j, l, t, s) for j in J for l in L_Amb for t in T)
        fi += prob * sum(sec["t_ij"][i][j] * _result_value(results, "FI", i, j, l, t, s) for i in I for j in J for l in L for t in T)
        fo += prob * sum(sec["t_jh"][j][h] * _result_value(results, "FO", j, h, l, t, s) for j in J for h in H for l in L_Amb for t in T)
    return {"RM_penalty": rm, "WAT_penalty": wat, "FI_transport": fi, "FO_transport": fo}


class BindingCollector:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def le(self, family: str, index: tuple[Any, ...], lhs: float, rhs: float) -> None:
        slack = rhs - lhs
        self.rows[family].append({"index": index, "lhs": lhs, "rhs": rhs, "slack": slack, "violation": max(0.0, -slack)})

    def eq(self, family: str, index: tuple[Any, ...], lhs: float, rhs: float) -> None:
        residual = lhs - rhs
        self.rows[family].append({"index": index, "lhs": lhs, "rhs": rhs, "slack": abs(residual), "violation": abs(residual)})

    def summary(self) -> dict[str, dict[str, Any]]:
        out = {}
        for family, rows in self.rows.items():
            slacks = [r["slack"] for r in rows]
            binding = [r for r in rows if abs(r["slack"]) <= TOL]
            out[family] = {
                "max_slack": max(slacks) if slacks else 0.0,
                "min_slack": min(slacks) if slacks else 0.0,
                "max_violation": max((r["violation"] for r in rows), default=0.0),
                "num_binding_constraints": len(binding),
                "binding_examples": [list(r["index"]) for r in binding[:5]],
            }
        return out


def binding_summary(instance: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    sets = instance["sets"]
    I, J, H, L, L_Amb, S = sets["I"], sets["J"], sets["H"], sets["L"], sets["L_Amb"], sets["S"]
    T = periods(instance)
    L_non_amb = [l for l in L if l not in set(L_Amb)]
    sec = instance["second_stage"]
    b = BindingCollector()

    for i in I:
        for j in J:
            for t in T:
                for s in S:
                    b.le(
                        "road_i_to_j_capacity",
                        (i, j, t, s),
                        sum(_result_value(results, "FI", i, j, l, t, s) for l in L),
                        sec["c_ij"][i][j] * u(instance, i, j, t, s) * _result_value(results, "X", j),
                    )
    for j in J:
        for h in H:
            for t in T:
                for s in S:
                    b.le(
                        "road_j_to_h_capacity",
                        (j, h, t, s),
                        sum(_result_value(results, "FO", j, h, l, t, s) for l in L_Amb),
                        sec["c_jh"][j][h] * w(instance, j, h, t, s) * _result_value(results, "X", j),
                    )
    for j in J:
        for t in T:
            for s in S:
                b.le(
                    "ccp_ambulance_capacity",
                    (j, t, s),
                    sum(_result_value(results, "FI", i, j, l, t, s) for i in I for l in L_Amb),
                    sec["kappa"] * _result_value(results, "U", j),
                )
    for h in H:
        for t in T:
            for s in S:
                lhs = sum(_result_value(results, "FO", j, h, l, t, s) for j in J for l in L_Amb)
                b.le("hospital_ambulance_capacity", (h, t, s), lhs, sec["eta"] * sec["b_h"][h])
                b.le("hospital_receiving_capacity", (h, t, s), lhs, hosp_cap(instance, h, t, s))
    for j in J:
        for t in T:
            for s in S:
                for l in L_Amb:
                    b.le(
                        "ccp_physical_capacity",
                        (j, l, t, s),
                        _result_value(results, "TRT", j, l, t, s) + _result_value(results, "WAT", j, l, t, s),
                        sec["k_jl"][j][l] * _result_value(results, "X", j),
                    )
                for l in L_non_amb:
                    b.le(
                        "ccp_physical_capacity",
                        (j, l, t, s),
                        _result_value(results, "TRT", j, l, t, s),
                        sec["k_jl"][j][l] * _result_value(results, "X", j),
                    )
                b.le(
                    "staff_workload",
                    (j, t, s),
                    sum(_result_value(results, "TRT", j, l, t, s) / sec["alpha_l"][l] for l in L),
                    _result_value(results, "V", j),
                )
    for j in J:
        for s in S:
            b.le(
                "supply_consumption",
                (j, s),
                sum(sec["beta_l"][l] * _result_value(results, "REG", j, l, t, s) for l in L for t in T),
                sum(_result_value(results, "Y", h, j) for h in H),
            )

    for i in I:
        for l in L:
            for t in T:
                for s in S:
                    prev = prev_period(instance, t)
                    rhs = (0.0 if prev is None else _result_value(results, "RM", i, l, prev, s)) + xi(instance, i, l, t, s)
                    rhs -= sum(_result_value(results, "FI", i, j, l, t, s) for j in J)
                    b.eq("RM_balance", (i, l, t, s), _result_value(results, "RM", i, l, t, s), rhs)
    for j in J:
        for l in L:
            for t in T:
                for s in S:
                    b.eq("REG_definition", (j, l, t, s), _result_value(results, "REG", j, l, t, s), sum(_result_value(results, "FI", i, j, l, t, s) for i in I))
                    tau = int(sec["tau_l"][l])
                    start = t - tau + 1
                    b.eq("TRT_rolling_sum", (j, l, t, s), _result_value(results, "TRT", j, l, t, s), sum(_result_value(results, "REG", j, l, r, s) for r in T if start <= r <= t))
    for j in J:
        for l in L_Amb:
            tau = int(sec["tau_l"][l])
            for t in T:
                for s in S:
                    prev = prev_period(instance, t)
                    completed_t = t - tau
                    completed = _result_value(results, "REG", j, l, completed_t, s) if has_period(instance, completed_t) else 0.0
                    rhs = (0.0 if prev is None else _result_value(results, "WAT", j, l, prev, s)) + completed
                    rhs -= sum(_result_value(results, "FO", j, h, l, t, s) for h in H)
                    b.eq("WAT_balance", (j, l, t, s), _result_value(results, "WAT", j, l, t, s), rhs)
    return b.summary()


def case_checks(case: str, instance: dict[str, Any], results: dict[str, Any], baseline: dict[str, Any] | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    sets = instance["sets"]
    I, J, H, L_Amb, S = sets["I"], sets["J"], sets["H"], sets["L_Amb"], sets["S"]
    T = periods(instance)
    baseline_obj = None if baseline is None else float(baseline["objective_value"])

    add("validator_passed", bool(results.get("validator_summary", {}).get("passed")), "")
    if "instance_fingerprint" in results:
        current_fp = instance_fingerprint(instance)
        add(
            "result_matches_current_instance",
            results["instance_fingerprint"] == current_fp,
            f"result={results['instance_fingerprint'][:12]}, current={current_fp[:12]}",
        )
    else:
        add(
            "result_has_instance_fingerprint",
            False,
            "結果檔由舊版 result_writer 寫出；請重新執行 scripts/run_tiny_tests.py",
        )
    if "gurobi_status" in results:
        add("gurobi_status_optimal", int(results["gurobi_status"]) == 2, f"status={results['gurobi_status']}")
    else:
        add("gurobi_status_recorded", False, "結果檔由舊版 result_writer 寫出；請重新執行 scripts/run_tiny_tests.py")
    if case == "deterministic_baseline":
        add("minor_has_no_FO", all("|minor|" not in k for k in results["nonzero_second_stage_variables"]["FO"]))
        add("minor_has_no_WAT", all("|minor|" not in k for k in results["nonzero_second_stage_variables"]["WAT"]))
        add("RM_zero_total", _total(results, "RM") <= TOL, f"RM total={_total(results, 'RM')}")
    elif case == "all_capacities_sufficient":
        add("RM_zero_total", _total(results, "RM") <= TOL, f"RM total={_total(results, 'RM')}")
        add("WAT_zero_total", _total(results, "WAT") <= TOL, f"WAT total={_total(results, 'WAT')}")
        if baseline_obj is not None:
            add("objective_matches_baseline", abs(float(results["objective_value"]) - baseline_obj) <= TOL)
    elif case == "road_disruption":
        meta = instance["case_metadata"]["intended_binding"]
        i, j, t, s = meta["i"], meta["j"], meta["time"], meta["scenario"]
        flow = sum(_result_value(results, "FI", i, j, l, t, s) for l in instance["sets"]["L"])
        add("disrupted_u_is_zero", abs(u(instance, i, j, t, s)) <= TOL)
        add("FI_on_disrupted_link_is_zero", flow <= TOL, f"FI={flow}")
        add("RM_positive_in_disrupted_period", sum(_result_value(results, "RM", i, l, t, s) for l in instance["sets"]["L"]) > TOL)
        if baseline_obj is not None:
            add("objective_above_baseline", float(results["objective_value"]) > baseline_obj + TOL)
    elif case == "hospital_capacity_bottleneck":
        meta = instance["case_metadata"]["intended_binding"]
        h, t, s = meta["hospital"], meta["time"], meta["scenario"]
        fo = sum(_result_value(results, "FO", j, h, l, t, s) for j in J for l in L_Amb)
        add("intended_hospital_capacity_is_zero", hosp_cap(instance, h, t, s) <= TOL)
        add("FO_at_bottleneck_is_zero", fo <= TOL, f"FO={fo}")
        add("WAT_positive", _total(results, "WAT") > TOL, f"WAT total={_total(results, 'WAT')}")
        if baseline_obj is not None:
            add("objective_above_baseline", float(results["objective_value"]) > baseline_obj + TOL)
    elif case == "ambulance_bottleneck":
        binds = binding_summary(instance, results)["ccp_ambulance_capacity"]["num_binding_constraints"]
        add("ccp_ambulance_capacity_binds", binds > 0, f"binding count={binds}")
        add("RM_positive", _total(results, "RM") > TOL, f"RM total={_total(results, 'RM')}")
        if baseline_obj is not None:
            add("objective_above_baseline", float(results["objective_value"]) > baseline_obj + TOL)
    elif case == "treatment_time_boundary":
        add("moderate_no_FO_before_completion", sum(_result_value(results, "FO", j, h, "moderate", 1, s) for j in J for h in H for s in S) <= TOL)
        add("severe_no_FO_before_completion", sum(_result_value(results, "FO", j, h, "severe", t, s) for j in J for h in H for t in (1, 2) for s in S if t in T) <= TOL)
        add("TRT_total_exceeds_REG_total_due_to_rolling", _total(results, "TRT") > _total(results, "REG") + TOL, f"TRT={_total(results, 'TRT')}, REG={_total(results, 'REG')}")
    return checks


def diagnose(result_dir: Path = Path("outputs/tiny_tests"), output_dir: Path = Path("outputs/tiny_diagnostics")) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = {}
    baseline_results = None
    baseline_path = _latest_result_path(result_dir, "deterministic_baseline")
    if baseline_path is not None:
        baseline_results = _load_json(baseline_path)

    for case in TEST_ORDER:
        instance = CASE_BUILDERS[case]()
        result_path = _latest_result_path(result_dir, case)
        if result_path is None:
            cases[case] = {"missing_results": str(result_dir / case / "results.json")}
            continue
        results = _load_json(result_path)
        cases[case] = {
            "result_file": str(result_path),
            "objective": {
                "objective_value": results["objective_value"],
                "first_stage_cost": results["first_stage_cost"],
                "expected_second_stage_cost": results["expected_second_stage_cost"],
                "components": _objective_components(instance, results),
            },
            "case_metadata": instance.get("case_metadata", {}),
            "variable_totals": {g: _total(results, g) for g in ("FI", "FO", "RM", "REG", "TRT", "WAT")},
            "constraint_binding_summary": binding_summary(instance, results),
            "case_checks": case_checks(case, instance, results, baseline_results),
        }

    report = {
        "note": "此診斷只檢查 tiny case 是否觸發預期模型邏輯；未使用 Benders、decomposition、cuts、heuristics 或 warm starts。",
        "tolerance": TOL,
        "cases": cases,
    }
    json_path = output_dir / "tiny_test_diagnostic_report.json"
    md_path = output_dir / "tiny_test_diagnostic_report.md"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Tiny Case 診斷報告", "", report["note"], "", f"容許誤差：`{report['tolerance']}`", ""]
    for case, data in report["cases"].items():
        lines += [f"## {case}", ""]
        if "missing_results" in data:
            lines += [f"找不到結果檔：`{data['missing_results']}`", ""]
            continue
        obj = data["objective"]
        lines += [
            f"- 目標值：`{obj['objective_value']}`",
            f"- 第一階成本：`{obj['first_stage_cost']}`",
            f"- 期望第二階成本：`{obj['expected_second_stage_cost']}`",
            f"- 成本組成：`{obj['components']}`",
            f"- 變數總量：`{data['variable_totals']}`",
            "",
            "### 案例檢查",
        ]
        for check in data["case_checks"]:
            status = "通過" if check["passed"] else "未通過"
            detail = f" - {check['detail']}" if check.get("detail") else ""
            lines.append(f"- {status}: {check['name']}{detail}")
        lines += ["", "### Binding 摘要", ""]
        lines.append("| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |")
        lines.append("|---|---:|---:|---:|---|")
        for family, summary in data["constraint_binding_summary"].items():
            lines.append(
                f"| {family} | {summary['max_slack']:.6g} | {summary['min_slack']:.6g} | "
                f"{summary['num_binding_constraints']} | `{summary['binding_examples']}` |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    diagnose()
    print("Tiny case 診斷完成")
    print("- Markdown 報告：outputs/tiny_diagnostics/tiny_test_diagnostic_report.md")
    print("- JSON 報告：outputs/tiny_diagnostics/tiny_test_diagnostic_report.json")


if __name__ == "__main__":
    main()
