# Tiny Case 中文診斷報告

此報告只整理 diagnostics 結果，不改變模型或求解結果。

## all_capacities_sufficient

- Objective：208.0
- First-stage cost：202.0
- Expected second-stage cost：6.0
- Variable totals：`{'FI': 4.0, 'FO': 2.0, 'REG': 4.0, 'RM': 0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks

- 通過: `validator_passed`
- 通過: `result_matches_current_instance`；result=b82f0150ed47, current=b82f0150ed47
- 通過: `gurobi_status_optimal`；status=2
- 通過: `RM_zero_total`；RM total=0
- 通過: `WAT_zero_total`；WAT total=0
- 通過: `objective_matches_baseline`

### Binding Constraints

- `REG_definition`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `RM_balance`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `TRT_rolling_sum`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `WAT_balance`：binding 數量 4, min_slack=0.0, max_slack=0.0
- `ccp_ambulance_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `ccp_physical_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `hospital_ambulance_capacity`：binding 數量 0, min_slack=998.0, max_slack=1000.0
- `hospital_receiving_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `road_i_to_j_capacity`：binding 數量 0, min_slack=96.0, max_slack=100.0
- `road_j_to_h_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `staff_workload`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `supply_consumption`：binding 數量 1, min_slack=0.0, max_slack=0.0

## ambulance_bottleneck

- Objective：287.0
- First-stage cost：202.0
- Expected second-stage cost：85.0
- Variable totals：`{'FI': 4.0, 'FO': 1.0, 'REG': 4.0, 'RM': 1.0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks

- 通過: `validator_passed`
- 通過: `result_matches_current_instance`；result=4466ad2d2d23, current=4466ad2d2d23
- 通過: `gurobi_status_optimal`；status=2
- 通過: `ccp_ambulance_capacity_binds`；binding count=2
- 通過: `RM_positive`；RM total=1.0
- 通過: `objective_above_baseline`

### Binding Constraints

- `REG_definition`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `RM_balance`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `TRT_rolling_sum`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `WAT_balance`：binding 數量 4, min_slack=0.0, max_slack=0.0
- `ccp_ambulance_capacity`：binding 數量 2, min_slack=0.0, max_slack=0.0
- `ccp_physical_capacity`：binding 數量 0, min_slack=1.0, max_slack=4.0
- `hospital_ambulance_capacity`：binding 數量 0, min_slack=1.0, max_slack=2.0
- `hospital_receiving_capacity`：binding 數量 0, min_slack=2.0, max_slack=3.0
- `road_i_to_j_capacity`：binding 數量 0, min_slack=7.0, max_slack=9.0
- `road_j_to_h_capacity`：binding 數量 0, min_slack=9.0, max_slack=10.0
- `staff_workload`：binding 數量 0, min_slack=0.5, max_slack=1.5
- `supply_consumption`：binding 數量 1, min_slack=0.0, max_slack=0.0

## deterministic_baseline

- Objective：208.0
- First-stage cost：202.0
- Expected second-stage cost：6.0
- Variable totals：`{'FI': 4.0, 'FO': 2.0, 'REG': 4.0, 'RM': 0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks

- 通過: `validator_passed`
- 通過: `result_matches_current_instance`；result=442aebc4d709, current=442aebc4d709
- 通過: `gurobi_status_optimal`；status=2
- 通過: `minor_has_no_FO`
- 通過: `minor_has_no_WAT`
- 通過: `RM_zero_total`；RM total=0

### Binding Constraints

- `REG_definition`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `RM_balance`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `TRT_rolling_sum`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `WAT_balance`：binding 數量 4, min_slack=0.0, max_slack=0.0
- `ccp_ambulance_capacity`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `ccp_physical_capacity`：binding 數量 0, min_slack=1.0, max_slack=4.0
- `hospital_ambulance_capacity`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `hospital_receiving_capacity`：binding 數量 0, min_slack=1.0, max_slack=3.0
- `road_i_to_j_capacity`：binding 數量 0, min_slack=6.0, max_slack=10.0
- `road_j_to_h_capacity`：binding 數量 0, min_slack=8.0, max_slack=10.0
- `staff_workload`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `supply_consumption`：binding 數量 1, min_slack=0.0, max_slack=0.0

## hospital_capacity_bottleneck

- Objective：336.0
- First-stage cost：202.0
- Expected second-stage cost：134.0
- Variable totals：`{'FI': 4.0, 'FO': 0, 'REG': 4.0, 'RM': 0, 'TRT': 4.0, 'WAT': 2.0}`

### Case Checks

- 通過: `validator_passed`
- 通過: `result_matches_current_instance`；result=01837ea2be07, current=01837ea2be07
- 通過: `gurobi_status_optimal`；status=2
- 通過: `intended_hospital_capacity_is_zero`
- 通過: `FO_at_bottleneck_is_zero`；FO=0.0
- 通過: `WAT_positive`；WAT total=2.0
- 通過: `objective_above_baseline`

### Binding Constraints

- `REG_definition`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `RM_balance`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `TRT_rolling_sum`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `WAT_balance`：binding 數量 4, min_slack=0.0, max_slack=0.0
- `ccp_ambulance_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `ccp_physical_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `hospital_ambulance_capacity`：binding 數量 0, min_slack=1000.0, max_slack=1000.0
- `hospital_receiving_capacity`：binding 數量 1, min_slack=0.0, max_slack=100.0
- `road_i_to_j_capacity`：binding 數量 0, min_slack=96.0, max_slack=100.0
- `road_j_to_h_capacity`：binding 數量 0, min_slack=100.0, max_slack=100.0
- `staff_workload`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `supply_consumption`：binding 數量 1, min_slack=0.0, max_slack=0.0

## road_disruption

- Objective：526.0
- First-stage cost：202.0
- Expected second-stage cost：324.0
- Variable totals：`{'FI': 4.0, 'FO': 0, 'REG': 4.0, 'RM': 4.0, 'TRT': 4.0, 'WAT': 0}`

### Case Checks

- 通過: `validator_passed`
- 通過: `result_matches_current_instance`；result=98db68ae3b20, current=98db68ae3b20
- 通過: `gurobi_status_optimal`；status=2
- 通過: `disrupted_u_is_zero`
- 通過: `FI_on_disrupted_link_is_zero`；FI=0.0
- 通過: `RM_positive_in_disrupted_period`
- 通過: `objective_above_baseline`

### Binding Constraints

- `REG_definition`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `RM_balance`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `TRT_rolling_sum`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `WAT_balance`：binding 數量 4, min_slack=0.0, max_slack=0.0
- `ccp_ambulance_capacity`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `ccp_physical_capacity`：binding 數量 0, min_slack=1.0, max_slack=4.0
- `hospital_ambulance_capacity`：binding 數量 0, min_slack=2.0, max_slack=2.0
- `hospital_receiving_capacity`：binding 數量 0, min_slack=3.0, max_slack=3.0
- `road_i_to_j_capacity`：binding 數量 1, min_slack=0.0, max_slack=6.0
- `road_j_to_h_capacity`：binding 數量 0, min_slack=10.0, max_slack=10.0
- `staff_workload`：binding 數量 1, min_slack=0.0, max_slack=2.0
- `supply_consumption`：binding 數量 1, min_slack=0.0, max_slack=0.0

## treatment_time_boundary

- Objective：205.0
- First-stage cost：201.0
- Expected second-stage cost：4.0
- Variable totals：`{'FI': 3.0, 'FO': 1.0, 'REG': 3.0, 'RM': 0, 'TRT': 6.0, 'WAT': 0}`

### Case Checks

- 通過: `validator_passed`
- 通過: `result_matches_current_instance`；result=30208f6dd360, current=30208f6dd360
- 通過: `gurobi_status_optimal`；status=2
- 通過: `moderate_no_FO_before_completion`
- 通過: `severe_no_FO_before_completion`
- 通過: `TRT_total_exceeds_REG_total_due_to_rolling`；TRT=6.0, REG=3.0

### Binding Constraints

- `REG_definition`：binding 數量 9, min_slack=0.0, max_slack=0.0
- `RM_balance`：binding 數量 9, min_slack=0.0, max_slack=0.0
- `TRT_rolling_sum`：binding 數量 9, min_slack=0.0, max_slack=0.0
- `WAT_balance`：binding 數量 6, min_slack=0.0, max_slack=0.0
- `ccp_ambulance_capacity`：binding 數量 0, min_slack=98.0, max_slack=100.0
- `ccp_physical_capacity`：binding 數量 0, min_slack=99.0, max_slack=100.0
- `hospital_ambulance_capacity`：binding 數量 0, min_slack=999.0, max_slack=1000.0
- `hospital_receiving_capacity`：binding 數量 0, min_slack=99.0, max_slack=100.0
- `road_i_to_j_capacity`：binding 數量 0, min_slack=97.0, max_slack=100.0
- `road_j_to_h_capacity`：binding 數量 0, min_slack=99.0, max_slack=100.0
- `staff_workload`：binding 數量 0, min_slack=0.25, max_slack=1.0
- `supply_consumption`：binding 數量 1, min_slack=0.0, max_slack=0.0
