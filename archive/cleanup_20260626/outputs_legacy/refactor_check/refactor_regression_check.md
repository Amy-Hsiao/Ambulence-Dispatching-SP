# Refactor Regression Check

This cleanup did not intentionally change the mathematical model, tiny parameters, tiny case definitions, or solved result values.

## Commands

Use a Python environment with `gurobipy` and a valid Gurobi license:

```powershell
python scripts\02_run_tiny_baseline.py
python scripts\03_run_all_tiny_tests.py
python scripts\04_diagnose_tiny_tests.py
```

## Required Regression Targets

| Case | Expected objective | Expected validator |
|---|---:|---|
| `deterministic_baseline` | 208 | passed |
| `all_capacities_sufficient` | 208 | passed |
| `road_disruption` | 526 | passed |
| `hospital_capacity_bottleneck` | 336 | passed |
| `ambulance_bottleneck` | 287 | passed |
| `treatment_time_boundary` | 205 | passed |

## No Advanced Algorithm Check

The project remains a direct extensive-form Gurobi model. No Benders decomposition, cuts, column generation, progressive hedging, heuristics, warm starts, or other acceleration method was added.
