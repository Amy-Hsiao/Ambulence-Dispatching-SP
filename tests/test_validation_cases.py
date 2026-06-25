from __future__ import annotations

import importlib.util
import json

import pytest

from scripts.diagnose_tiny_tests import case_checks
from scripts.run_tiny_tests import TEST_ORDER
from src.data.tiny_generator import CASE_BUILDERS
from src.io.result_writer import write_results
from src.model.sp_model import build_model
from src.validation.instance_validator import validate_instance
from src.validation.solution_validator import validate_solution


pytestmark = pytest.mark.skipif(importlib.util.find_spec("gurobipy") is None, reason="gurobipy is not installed")


@pytest.fixture(scope="module")
def solved_results(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("tiny_results")
    solved = {}
    for case_name in TEST_ORDER:
        instance = CASE_BUILDERS[case_name]()
        pre = validate_instance(instance)
        assert pre["passed"], pre
        model = build_model(instance)
        model.Params.OutputFlag = 0
        model.optimize()
        post = validate_solution(model)
        assert post["passed"], post
        paths = write_results(model, out_dir, case_name)
        with open(paths["json"], encoding="utf-8") as f:
            solved[case_name] = {"instance": instance, "results": json.load(f)}
    return solved


@pytest.mark.parametrize("case_name", TEST_ORDER)
def test_tiny_case_validates_after_solve(case_name, solved_results):
    assert solved_results[case_name]["results"]["validator_summary"]["passed"]


@pytest.mark.parametrize("case_name", TEST_ORDER)
def test_tiny_case_exercises_intended_logic(case_name, solved_results):
    baseline = solved_results["deterministic_baseline"]["results"]
    instance = solved_results[case_name]["instance"]
    results = solved_results[case_name]["results"]
    checks = case_checks(case_name, instance, results, baseline)
    failed = [check for check in checks if not check["passed"]]
    assert not failed, failed
