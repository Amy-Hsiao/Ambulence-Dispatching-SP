[CRITICAL REQUIREMENT: UNIVERSAL MODEL FUNCTION]
絕對不可以分開寫 Deterministic Model 和 SP Model。請撰寫唯一一個共用的建模函數：
`def build_gurobi_model(param_dict, scenarios_data):`

程式邏輯必須遵守以下規則：
1. 當 `len(scenarios_data) == 1` 時：代表這是 Deterministic Model 或單一情境的 WS 模型。程式不需生成 Non-anticipativity constraints，直接以單一情境建立模型並回傳。
2. 當 `len(scenarios_data) > 1` 時：代表這是 Extensive Form SP 模型。程式必須自動展開所有情境的第二階段決策變數，並嚴格加入 Non-anticipativity constraints（第一階段決策在各情境下必須一致）。
3. 所有的變數命名規則與限制式（資源容量、流動平衡）在兩種狀況下必須完全共用同一套邏輯。

請完成正常 SP 模型。此階段只做 RP 求解，不要實作 VSS / EVPI 的完整流程。

## 重要限制

- 使用 extensive form。
- 不使用 Benders decomposition。
- 不使用 Pareto cut、core point、decomposition enhancement。
- First-stage variables 在所有 scenarios 共用。
- Second-stage variables 依 scenario 分開。

## 模型結構

### First-stage variables

- `X_j`
- `v_j`
- `theta_j`
- `y_hj`

這些變數不能有 scenario index。

### Second-stage variables

每個 scenario s 都有一份：

- `FI_i-j-l-t-s`
- `FO_j-h-l-t-s`
- `RM_i-l-t-s`
- `REG_j-l-t-s`
- `TRT_j-l-t-s`
- `WAT_j-l-t-s`

全部為 nonnegative continuous。

## 目標函數

最小化：

```text
first-stage cost + sum_s p_s * second-stage-cost_s
```

scenario probability 預設等權重 `1/S`，但要允許從 config 讀取。

## 限制式

沿用 deterministic model 的限制式，但所有包含隨機參數與 second-stage variables 的限制式都要加 scenario index。

First-stage resource 限制不能重複乘上 scenario。

## 自訂求解 log

- 關閉 Gurobi 原生 log。
- 每個iteration印出一行：
  - `Iter`
  - `Time(s)`
  - `Best LB`
  - `Best UB`
  - `Gap(%)`
- 最終 summary 必須清楚列出 Best LB、Best UB、Final Gap、CPU Time(s)、Nodes、Iteration。

## 輸出

必須輸出：

1. `summary.csv/json`
2. `first_stage_variables.csv`
3. `second_stage_variables.csv`
4. `variables_all.csv`
5. `solve_log.csv`
6. `scenario_summary.csv`

`scenario_summary.csv` 至少包含：

- scenario
- probability
- second_stage_cost
- total_demand
- total_transported_to_ccp
- total_transferred_to_hospital
- total_remaining_disaster_area
- total_waiting_at_ccp

## 驗收條件

1. SP 模型中的 first-stage variables 只有一份，不能被複製成每個 scenario 一份。
2. second-stage variables 數量會隨 S 成比例增加。
3. objective 要使用 scenario probability。
4. 小型 instance 可以求解成功。
5. 輸出包含所有一階與二階決策變數。
6. console 不出現 Gurobi 原生大量資訊。

## 完成後停止

完成 SP 後停止，提供執行方式、輸出範例與驗證結果。不要開始寫 VSS / EVPI。
