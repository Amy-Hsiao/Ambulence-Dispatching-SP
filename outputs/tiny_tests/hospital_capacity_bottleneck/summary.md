# hospital_capacity_bottleneck 求解摘要

## 目標值

- 總目標值：`336.0`
- 第一階成本：`202.0`
- 期望第二階成本：`134.0`

## 驗證結果

- 驗證狀態：通過
- Gurobi status：`2`

## 輸出內容

- `results.json`：完整解與 objective decomposition
- `nonzero_variables.csv`：非零變數與第一階變數
- `constraint_violations.csv`：各 constraint family 最大違反量

## Constraint 最大違反量

| constraint_family | max_violation |
|---|---:|
| rm_balance | 0.0 |
| reg_definition | 0.0 |
| trt_definition | 0.0 |
| wat_balance | 0.0 |
| road_in_capacity | 0.0 |
| road_out_capacity | 0.0 |
| ccp_ambulance_capacity | 0.0 |
| hospital_ambulance_capacity | 0.0 |
| hospital_receiving_capacity | 0.0 |
| ccp_physical_capacity | 0.0 |
| staff_workload | 0.0 |
| supply_consumption | 0.0 |
| nonnegativity | 0.0 |
