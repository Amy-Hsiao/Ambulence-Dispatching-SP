# Prompt 06：完成輸出報表與 Stress Test 批次實驗

請完成結果輸出、Stress Test 批次執行與 bottleneck summary。此階段重點是讓輸出清楚好讀，且欄位符合實驗表格需求。

## Stress Test 表格 1：factor_scaling

輸出欄位必須包含：

- factor
- test_id
- level
- fixed_setting
- obj_value
- Best LB
- Best UB
- CPU Time(s)
- num_variables
- num_constraints
- Nodes
- Iteration
- Final Gap(%)
- VSS(%)
- EVPI(%)

建議情境列：

- Deterministic / B00
- Scenario：S = 5, 10, 20, 30
- Time Period：T = 8, 12, 24
- demand：D x 0.5, D x 2
- hospital capacity：H x 0.5, H x 2
- road capacity：C x 0.5, C x 2

## Stress Test 表格 2：bottleneck_summary

輸出欄位必須包含：

- factor
- test_id
- level
- fixed_setting
- total_demand
- total_transported_to_ccp
- total_transferred_to_hospital
- total_remaining_disaster_area RM
- total_waiting_at_ccp WAT
- max_ccp_utilization_%
- max_hospital_utilization_%
- max_road_ij_utilization_%
- max_road_jh_utilization_%
- max_staff_utilization_%
- max_ccp_ambulance_utilization_%
- max_hospital_ambulance_utilization_%
- suspected_bottleneck

## 決策變數輸出

每個 test case 都要輸出：

```text
outputs/<run_id>/<test_id>/
  summary.csv
  summary.json
  first_stage_variables.csv
  second_stage_variables.csv
  variables_all.csv
  variables_nonzero.csv
  solve_log.csv
  scenario_summary.csv
  bottleneck_summary.csv
```

### first_stage_variables.csv

建議欄位：

- run_id
- test_id
- model_type
- variable
- j
- h
- value

### second_stage_variables.csv

建議欄位：

- run_id
- test_id
- model_type
- scenario
- probability
- variable
- i
- j
- h
- l
- t
- value

`variables_all.csv` 必須包含 0 值。`variables_nonzero.csv` 可只保留大於 tolerance 的值，方便閱讀。

## Bottleneck 指標計算

至少計算：

1. total_demand
2. total_transported_to_ccp = sum FI
3. total_transferred_to_hospital = sum FO
4. total_remaining_disaster_area = sum RM at all periods or final period，請在欄位說明清楚
5. total_waiting_at_ccp = sum WAT at all periods or final period，請在欄位說明清楚
6. max_ccp_utilization_%
7. max_hospital_utilization_%
8. max_road_ij_utilization_%
9. max_road_jh_utilization_%
10. max_staff_utilization_%
11. max_ccp_ambulance_utilization_%
12. max_hospital_ambulance_utilization_%

`suspected_bottleneck` 可用最大 utilization 或最大 unmet/waiting contribution 判斷，但要把規則寫進文件。

## Excel / CSV 輸出

請同時輸出：

- `stress_test_results.xlsx`
- `factor_scaling.csv`
- `bottleneck_summary.csv`

Excel 至少兩個 sheets：

- `factor_scaling`
- `bottleneck_summary`

## Console 輸出

批次執行時，每個 test case 開始與結束都要清楚顯示：

```text
[START] test_id=S01 level=S=5
Iter | Time(s) | Best LB | Best UB | Gap(%)
...
[DONE] test_id=S01 status=... BestUB=... Gap=... Time=...
```

不可印出 Gurobi 原生大量資訊。

## 驗收條件

1. Stress Test 的兩張表欄位完整。
2. 每個 test case 都有完整變數輸出。
3. 每個 test case 都有 solve_log。
4. Excel 和 CSV 數字一致。
5. 即使某 test case infeasible 或 time limit，也要有 summary 並標記 status。

## 完成後停止

完成報表與 stress test 後停止，提供輸出檔案位置、欄位檢查與一個小型測試結果。
