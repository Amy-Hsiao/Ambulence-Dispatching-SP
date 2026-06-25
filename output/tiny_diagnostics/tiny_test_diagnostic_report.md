# Tiny Test Diagnostic Report

Diagnostics only; this does not use Benders, decomposition, cuts, heuristics, or warm starts.

Tolerance: `1e-06`

## deterministic_baseline

- Objective: `208.0`
- First-stage cost: `202.0`
- Expected second-stage cost: `6.0`
- Cost components: `{'RM_penalty': 0.0, 'WAT_penalty': 0.0, 'FI_transport': 4.0, 'FO_transport': 2.0}`
- Variable totals: `{'FI': 4.0, 'FO': 2.0, 'RM': 0, 'REG': 4.0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks
- PASS: validator_passed
- PASS: result_matches_current_instance - result=442aebc4d709, current=442aebc4d709
- PASS: gurobi_status_optimal - status=2
- PASS: minor_has_no_FO
- PASS: minor_has_no_WAT
- PASS: RM_zero_total - RM total=0

### Binding Summary

| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |
|---|---:|---:|---:|---|
| road_i_to_j_capacity | 10 | 6 | 0 | `[]` |
| road_j_to_h_capacity | 10 | 8 | 0 | `[]` |
| ccp_ambulance_capacity | 2 | 0 | 1 | `[['j1', 1, 's1']]` |
| hospital_ambulance_capacity | 2 | 0 | 1 | `[['h1', 2, 's1']]` |
| hospital_receiving_capacity | 3 | 1 | 0 | `[]` |
| ccp_physical_capacity | 4 | 1 | 0 | `[]` |
| staff_workload | 2 | 0 | 1 | `[['j1', 1, 's1']]` |
| supply_consumption | 0 | 0 | 1 | `[['j1', 's1']]` |
| RM_balance | 0 | 0 | 6 | `[['i1', 'minor', 1, 's1'], ['i1', 'minor', 2, 's1'], ['i1', 'moderate', 1, 's1'], ['i1', 'moderate', 2, 's1'], ['i1', 'severe', 1, 's1']]` |
| REG_definition | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| TRT_rolling_sum | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| WAT_balance | 0 | 0 | 4 | `[['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1'], ['j1', 'severe', 2, 's1']]` |

## all_capacities_sufficient

- Objective: `208.0`
- First-stage cost: `202.0`
- Expected second-stage cost: `6.0`
- Cost components: `{'RM_penalty': 0.0, 'WAT_penalty': 0.0, 'FI_transport': 4.0, 'FO_transport': 2.0}`
- Variable totals: `{'FI': 4.0, 'FO': 2.0, 'RM': 0, 'REG': 4.0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks
- PASS: validator_passed
- PASS: result_matches_current_instance - result=b82f0150ed47, current=b82f0150ed47
- PASS: gurobi_status_optimal - status=2
- PASS: RM_zero_total - RM total=0
- PASS: WAT_zero_total - WAT total=0
- PASS: objective_matches_baseline

### Binding Summary

| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |
|---|---:|---:|---:|---|
| road_i_to_j_capacity | 100 | 96 | 0 | `[]` |
| road_j_to_h_capacity | 100 | 98 | 0 | `[]` |
| ccp_ambulance_capacity | 100 | 98 | 0 | `[]` |
| hospital_ambulance_capacity | 1000 | 998 | 0 | `[]` |
| hospital_receiving_capacity | 100 | 98 | 0 | `[]` |
| ccp_physical_capacity | 100 | 98 | 0 | `[]` |
| staff_workload | 2 | 0 | 1 | `[['j1', 1, 's1']]` |
| supply_consumption | 0 | 0 | 1 | `[['j1', 's1']]` |
| RM_balance | 0 | 0 | 6 | `[['i1', 'minor', 1, 's1'], ['i1', 'minor', 2, 's1'], ['i1', 'moderate', 1, 's1'], ['i1', 'moderate', 2, 's1'], ['i1', 'severe', 1, 's1']]` |
| REG_definition | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| TRT_rolling_sum | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| WAT_balance | 0 | 0 | 4 | `[['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1'], ['j1', 'severe', 2, 's1']]` |

## road_disruption

- Objective: `526.0`
- First-stage cost: `202.0`
- Expected second-stage cost: `324.0`
- Cost components: `{'RM_penalty': 320.0, 'WAT_penalty': 0.0, 'FI_transport': 4.0, 'FO_transport': 0.0}`
- Variable totals: `{'FI': 4.0, 'FO': 0, 'RM': 4.0, 'REG': 4.0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks
- PASS: validator_passed
- PASS: result_matches_current_instance - result=98db68ae3b20, current=98db68ae3b20
- PASS: gurobi_status_optimal - status=2
- PASS: disrupted_u_is_zero
- PASS: FI_on_disrupted_link_is_zero - FI=0.0
- PASS: RM_positive_in_disrupted_period
- PASS: objective_above_baseline

### Binding Summary

| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |
|---|---:|---:|---:|---|
| road_i_to_j_capacity | 6 | 0 | 1 | `[['i1', 'j1', 1, 's1']]` |
| road_j_to_h_capacity | 10 | 10 | 0 | `[]` |
| ccp_ambulance_capacity | 2 | 0 | 1 | `[['j1', 2, 's1']]` |
| hospital_ambulance_capacity | 2 | 2 | 0 | `[]` |
| hospital_receiving_capacity | 3 | 3 | 0 | `[]` |
| ccp_physical_capacity | 4 | 1 | 0 | `[]` |
| staff_workload | 2 | 0 | 1 | `[['j1', 2, 's1']]` |
| supply_consumption | 0 | 0 | 1 | `[['j1', 's1']]` |
| RM_balance | 0 | 0 | 6 | `[['i1', 'minor', 1, 's1'], ['i1', 'minor', 2, 's1'], ['i1', 'moderate', 1, 's1'], ['i1', 'moderate', 2, 's1'], ['i1', 'severe', 1, 's1']]` |
| REG_definition | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| TRT_rolling_sum | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| WAT_balance | 0 | 0 | 4 | `[['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1'], ['j1', 'severe', 2, 's1']]` |

## hospital_capacity_bottleneck

- Objective: `336.0`
- First-stage cost: `202.0`
- Expected second-stage cost: `134.0`
- Cost components: `{'RM_penalty': 0.0, 'WAT_penalty': 130.0, 'FI_transport': 4.0, 'FO_transport': 0.0}`
- Variable totals: `{'FI': 4.0, 'FO': 0, 'RM': 0, 'REG': 4.0, 'TRT': 4.0, 'WAT': 2.0}`

### Case Checks
- PASS: validator_passed
- PASS: result_matches_current_instance - result=01837ea2be07, current=01837ea2be07
- PASS: gurobi_status_optimal - status=2
- PASS: intended_hospital_capacity_is_zero
- PASS: FO_at_bottleneck_is_zero - FO=0.0
- PASS: WAT_positive - WAT total=2.0
- PASS: objective_above_baseline

### Binding Summary

| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |
|---|---:|---:|---:|---|
| road_i_to_j_capacity | 100 | 96 | 0 | `[]` |
| road_j_to_h_capacity | 100 | 100 | 0 | `[]` |
| ccp_ambulance_capacity | 100 | 98 | 0 | `[]` |
| hospital_ambulance_capacity | 1000 | 1000 | 0 | `[]` |
| hospital_receiving_capacity | 100 | 0 | 1 | `[['h1', 2, 's1']]` |
| ccp_physical_capacity | 100 | 98 | 0 | `[]` |
| staff_workload | 2 | 0 | 1 | `[['j1', 1, 's1']]` |
| supply_consumption | 0 | 0 | 1 | `[['j1', 's1']]` |
| RM_balance | 0 | 0 | 6 | `[['i1', 'minor', 1, 's1'], ['i1', 'minor', 2, 's1'], ['i1', 'moderate', 1, 's1'], ['i1', 'moderate', 2, 's1'], ['i1', 'severe', 1, 's1']]` |
| REG_definition | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| TRT_rolling_sum | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| WAT_balance | 0 | 0 | 4 | `[['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1'], ['j1', 'severe', 2, 's1']]` |

## ambulance_bottleneck

- Objective: `287.0`
- First-stage cost: `202.0`
- Expected second-stage cost: `85.0`
- Cost components: `{'RM_penalty': 80.0, 'WAT_penalty': 0.0, 'FI_transport': 4.0, 'FO_transport': 1.0}`
- Variable totals: `{'FI': 4.0, 'FO': 1.0, 'RM': 1.0, 'REG': 4.0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks
- PASS: validator_passed
- PASS: result_matches_current_instance - result=4466ad2d2d23, current=4466ad2d2d23
- PASS: gurobi_status_optimal - status=2
- PASS: ccp_ambulance_capacity_binds - binding count=2
- PASS: RM_positive - RM total=1.0
- PASS: objective_above_baseline

### Binding Summary

| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |
|---|---:|---:|---:|---|
| road_i_to_j_capacity | 9 | 7 | 0 | `[]` |
| road_j_to_h_capacity | 10 | 9 | 0 | `[]` |
| ccp_ambulance_capacity | 0 | 0 | 2 | `[['j1', 1, 's1'], ['j1', 2, 's1']]` |
| hospital_ambulance_capacity | 2 | 1 | 0 | `[]` |
| hospital_receiving_capacity | 3 | 2 | 0 | `[]` |
| ccp_physical_capacity | 4 | 1 | 0 | `[]` |
| staff_workload | 1.5 | 0.5 | 0 | `[]` |
| supply_consumption | 0 | 0 | 1 | `[['j1', 's1']]` |
| RM_balance | 0 | 0 | 6 | `[['i1', 'minor', 1, 's1'], ['i1', 'minor', 2, 's1'], ['i1', 'moderate', 1, 's1'], ['i1', 'moderate', 2, 's1'], ['i1', 'severe', 1, 's1']]` |
| REG_definition | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| TRT_rolling_sum | 0 | 0 | 6 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1']]` |
| WAT_balance | 0 | 0 | 4 | `[['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'severe', 1, 's1'], ['j1', 'severe', 2, 's1']]` |

## treatment_time_boundary

- Objective: `205.0`
- First-stage cost: `201.0`
- Expected second-stage cost: `4.0`
- Cost components: `{'RM_penalty': 0.0, 'WAT_penalty': 0.0, 'FI_transport': 3.0, 'FO_transport': 1.0}`
- Variable totals: `{'FI': 3.0, 'FO': 1.0, 'RM': 0, 'REG': 3.0, 'TRT': 6.0, 'WAT': 0}`

### Case Checks
- PASS: validator_passed
- PASS: result_matches_current_instance - result=30208f6dd360, current=30208f6dd360
- PASS: gurobi_status_optimal - status=2
- PASS: moderate_no_FO_before_completion
- PASS: severe_no_FO_before_completion
- PASS: TRT_total_exceeds_REG_total_due_to_rolling - TRT=6.0, REG=3.0

### Binding Summary

| constraint_family | max_slack | min_slack | num_binding_constraints | binding_examples |
|---|---:|---:|---:|---|
| road_i_to_j_capacity | 100 | 97 | 0 | `[]` |
| road_j_to_h_capacity | 100 | 99 | 0 | `[]` |
| ccp_ambulance_capacity | 100 | 98 | 0 | `[]` |
| hospital_ambulance_capacity | 1000 | 999 | 0 | `[]` |
| hospital_receiving_capacity | 100 | 99 | 0 | `[]` |
| ccp_physical_capacity | 100 | 99 | 0 | `[]` |
| staff_workload | 1 | 0.25 | 0 | `[]` |
| supply_consumption | 0 | 0 | 1 | `[['j1', 's1']]` |
| RM_balance | 0 | 0 | 9 | `[['i1', 'minor', 1, 's1'], ['i1', 'minor', 2, 's1'], ['i1', 'minor', 3, 's1'], ['i1', 'moderate', 1, 's1'], ['i1', 'moderate', 2, 's1']]` |
| REG_definition | 0 | 0 | 9 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'minor', 3, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1']]` |
| TRT_rolling_sum | 0 | 0 | 9 | `[['j1', 'minor', 1, 's1'], ['j1', 'minor', 2, 's1'], ['j1', 'minor', 3, 's1'], ['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1']]` |
| WAT_balance | 0 | 0 | 6 | `[['j1', 'moderate', 1, 's1'], ['j1', 'moderate', 2, 's1'], ['j1', 'moderate', 3, 's1'], ['j1', 'severe', 1, 's1'], ['j1', 'severe', 2, 's1']]` |
