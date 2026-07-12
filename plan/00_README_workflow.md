# Codex 專案執行總流程：救護車道路受損派送

本工作包的目的不是一次把所有程式寫完，而是讓 Codex 分階段完成大型最佳化專案。每個階段都必須停下來，讓使用者檢查模型、輸出與測試結果，再進入下一階段。

## 執行原則

1. 不要一次完成全部功能。
2. 每個階段只處理該階段指定範圍。
3. 每個階段完成後，必須列出：
   - 新增/修改檔案
   - 主要設計決策
   - 如何執行
   - 驗證結果
   - 尚未處理的事項
4. 不要印出 Gurobi 內建大量求解資訊，必須設定靜音，改用自訂 log 顯示 Best LB、Best UB、Gap、solve time。
5. 所有隨機種子必須固定，且要做到：增加 S 不改變前面 scenario；增加 T 不改變前面 period 的已生成資料。
6. 正常 SP 先用 extensive form，不使用 Benders、Pareto cut、core point、decomposition 或其他加速法，除非使用者之後明確要求。
7. 所有輸出要清楚、可讀、可追溯，且包含所有一階與二階決策變數。

## 建議執行順序

1. `01_PROJECT_RULES.md`：先建立專案規範與不可違反條件。
2. `02_DATA_CONFIG_PROMPT.md`：完成 config.py 與資料生成/讀檔流程。
3. `03_DETERMINISTIC_MODEL_PROMPT.md`：完成 deterministic / expected value / scenario-specific deterministic model。
4. `04_SP_MODEL_PROMPT.md`：完成正常 two-stage stochastic programming extensive form。
5. `05_VSS_EVPI_PROMPT.md`：完成 RP、EV、EEV、WS、VSS、EVPI 計算流程。
6. `06_OUTPUTS_STRESS_TESTS_PROMPT.md`：完成結果輸出、stress test 表格與 bottleneck summary。
7. `07_VALIDATION_ACCEPTANCE_PROMPT.md`：補完整驗證、tiny baseline、回歸測試與最終交付檢查。
8. `08_MCVAR_BBC_PROMPT.md`：SP + MCVaR（直接 B&BC + 既有 enhancement，不寫 extensive form）。
9. `09_DRO_BBC_PROMPT.md`：SP + MCVaR + DRO（box / ellipsoidal / polyhedral 對偶重構，B&BC）。
10. `10_RISK_EXPERIMENTS_PROMPT.md`：實驗一（DRO 三種 ambiguity set 的 α×λ 網格，輸出 Excel 六分頁）與批次調參入口 `run experiment/batch_risk_experiment.py`。
11. `11_PDR_EXPERIMENT_PROMPT.md`：實驗二（PDR = (DRO*−MCVaR*)/MCVaR*，scope 掃描，輸出 Excel 四分頁含論文格式 PDR 表）與入口 `run experiment/batch_pdr_experiment.py`。
12. `12_ABLATION_EXPERIMENT_PROMPT.md`：實驗三（B&BC 加速策略 ablation：BBC→+WS→+RS→+UC→Full 五配置，Excel 六分頁）；計畫已定，待使用者確認後實作 `run experiment/batch_ablation_experiment.py`。
13. `13_SCALE_PILOT_AND_RERUN_PROMPT.md`：交接執行計畫（給執行模型）——A. 規模 pilot 找 S* → B. PDR 校準各 set 的 scope → C. 以 S* 與選定 scope 重跑實驗一；只改 runner 參數區、每步停止回報。

註：階段 8–11 例外於原則 6（風險模型直接用 Benders B&BC，經使用者明確要求）。

## 每階段完成後的停止規則

Codex 每完成一份 prompt 的任務後，必須停止，不能自行進入下一份 prompt。回覆格式如下：

```text
階段完成：<階段名稱>

1. 修改/新增檔案
- ...

2. 核心設計
- ...

3. 執行方式
- ...

4. 驗證結果
- ...

5. 需要使用者檢查的地方
- ...

我已停止，等待你確認後再進入下一階段。
```
