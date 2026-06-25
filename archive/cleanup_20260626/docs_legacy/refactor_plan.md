# Refactor Plan

## Boundary

This cleanup is limited to project organization, documentation, import wrappers, reporting, and real-data preparation skeletons.

It must not change:

- SP model formulation.
- Objective function.
- Constraint logic.
- Tiny case parameter values.
- Tiny case definitions.
- Existing solved result values.
- Domain of second-stage variables.
- The no-Benders / no-decomposition / no-cuts policy.

## Current State

The working model is currently implemented in:

- `src/model/sp_model.py`
- `src/data/tiny_generator.py`
- `src/data/schema.py`
- `src/validation/instance_validator.py`
- `src/validation/solution_validator.py`
- `src/io/result_writer.py`

Legacy scripts are:

- `scripts/run_tiny_baseline.py`
- `scripts/run_tiny_tests.py`
- `scripts/diagnose_tiny_tests.py`

Existing solved outputs are in `output/`.

## Target Structure

The organized package namespace is:

```text
src/ambulance_sp/
  data_generation/
  data_loading/
  schemas/
  optimization/
  validation/
  reporting/
  utils/
```

The current core implementation is kept intact and exposed through compatibility wrappers. This avoids accidental mathematical changes while improving import paths.

## File Mapping

| Current file | Organized wrapper |
|---|---|
| `src/model/sp_model.py` | `src/ambulance_sp/optimization/extensive_form_sp_model.py` |
| `src/data/tiny_generator.py` | `src/ambulance_sp/data_generation/tiny_case_generator.py` |
| `src/data/schema.py` | `src/ambulance_sp/schemas/instance_schema.py` |
| `src/validation/instance_validator.py` | `src/ambulance_sp/validation/input_data_validator.py` |
| `src/validation/solution_validator.py` | `src/ambulance_sp/validation/solution_validator.py` |
| `src/io/result_writer.py` | `src/ambulance_sp/reporting/result_writer.py` |
| `scripts/run_tiny_tests.py` | `scripts/03_run_all_tiny_tests.py` |
| `scripts/diagnose_tiny_tests.py` | `scripts/04_diagnose_tiny_tests.py` |

## Import Strategy

Existing imports remain valid. New imports can use the organized namespace, for example:

```python
from ambulance_sp.optimization.extensive_form_sp_model import build_model
from ambulance_sp.data_generation.tiny_case_generator import CASE_BUILDERS
```

The legacy `src.*` imports are not removed in this cleanup.

## Testing Strategy

Regression commands:

```powershell
python scripts\02_run_tiny_baseline.py
python scripts\03_run_all_tiny_tests.py
python scripts\04_diagnose_tiny_tests.py
```

Regression targets:

| Case | Objective | Validator |
|---|---:|---|
| `deterministic_baseline` | 208 | passed |
| `all_capacities_sufficient` | 208 | passed |
| `road_disruption` | 526 | passed |
| `hospital_capacity_bottleneck` | 336 | passed |
| `ambulance_bottleneck` | 287 | passed |
| `treatment_time_boundary` | 205 | passed |

## Next Steps

1. Keep the mathematical model in `sp_model.py` unchanged.
2. Add organized wrappers under `src/ambulance_sp`.
3. Add numbered scripts for a clearer workflow.
4. Add real-data CSV templates and validation-only loader skeletons.
5. Keep tiny case regression results unchanged.
