from __future__ import annotations

import importlib.util

import pytest

from src.data.tiny_generator import deterministic_baseline
from src.model.sp_model import build_model
from src.validation.instance_validator import validate_instance
from src.validation.solution_validator import validate_solution


pytestmark = pytest.mark.skipif(importlib.util.find_spec("gurobipy") is None, reason="gurobipy is not installed")


def test_deterministic_baseline_solves_and_validates():
    instance = deterministic_baseline()
    assert validate_instance(instance)["passed"]
    model = build_model(instance)
    model.Params.OutputFlag = 0
    model.optimize()
    assert validate_solution(model)["passed"]
