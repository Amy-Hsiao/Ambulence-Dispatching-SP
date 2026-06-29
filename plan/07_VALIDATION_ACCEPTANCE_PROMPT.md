# Prompt 07：完成驗證、回歸測試與最終交付檢查

請補齊 validation、tests 與最終 acceptance checklist。此階段不新增大型功能，只做穩定性、正確性與可重現性確認。

## 需要驗證的項目

### Data validation

- CSV 索引唯一。
- I/J/H/L/T/S 維度一致。
- scenario probability 加總為 1。
- 所有需求、容量、成本非負。
- road availability 在 [0, 1]。
- hospital capacity 非負。
- fixed seed 重跑結果一致。
- S/T prefix stability 通過。

### Model validation

- first-stage variables 不含 scenario index。
- SP objective 使用 scenario probability。
- deterministic expected value 使用同一批 scenarios 的平均。
- WS 每個 scenario 解一次 deterministic model。
- EEV 固定 EV 的 first-stage variables。
- 所有 variables 均有輸出。

### Solution validation

檢查主要限制式 violation，例如：

- staff total limit
- CCP ambulance total limit
- hospital supply limit
- CCP supply limit
- road_in_capacity
- road_out_capacity
- hospital_receiving_capacity
- staff treatment capacity
- CCP capacity
- hospital ambulance capacity
- RM balance
- REG/TRT/WAT balance

### Output validation

- summary 欄位完整。
- first_stage_variables.csv 欄位完整。
- second_stage_variables.csv 欄位完整。
- solve_log.csv 欄位完整。
- factor_scaling 欄位完整。
- bottleneck_summary 欄位完整。
- Excel 與 CSV 數字一致。

## Tiny baseline / regression tests

保留既有 tiny baseline 測試。若既有腳本有 expected objective，例如 208.0，必須在修改後仍通過，除非明確記錄是因模型定義修正而改變。

建議測試：

1. tiny deterministic baseline。
2. tiny SP with S=2, T=2。
3. reproducibility test。
4. prefix stability test。
5. VSS/EVPI smoke test。
6. output schema test。
7. no Gurobi native log test。

## 最終 acceptance checklist

請建立 `docs/acceptance_checklist.md`，包含：

- 如何從 raw CSV 生成 instance。
- 如何跑 deterministic。
- 如何跑 SP。
- 如何跑 VSS/EVPI。
- 如何跑 stress tests。
- 每個輸出檔案的位置與欄位。
- 常見錯誤排查。
- 哪些數字使用 Best UB。
- 如何確認隨機資料可重現。

## 完成後停止

完成本階段後，回報所有測試是否通過。若有失敗，列出失敗原因與建議修正，但不要自行進入新功能開發。
