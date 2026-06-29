# Prompt 05：完成 VSS 與 EVPI 計算流程

請完成 RP、EV、EEV、WS、VSS、EVPI 的整體計算流程。此階段重點是指標定義正確、使用 Best UB、輸出清楚。

## 成本最小化定義

本專案是成本最小化，因此使用以下定義：

```text
RP  = 正常 two-stage SP 的 objective
EV  = 將隨機參數取平均後，求解 deterministic model 得到的 objective
x_EV = EV model 得到的一階決策
EEV = 固定 x_EV 後，在原始 scenarios 上評估 expected cost
WS  = wait-and-see，每個 scenario 各自解一次 deterministic model，取機率加權平均
```

理論上若皆最優：

```text
WS <= RP <= EEV
VSS  = EEV - RP
EVPI = RP - WS
```

百分比：

```text
VSS(%)  = (EEV - RP) / abs(RP) * 100
EVPI(%) = (RP - WS) / abs(RP) * 100
```

若 RP 為 0，百分比應輸出 NA，避免除以 0。

## 使用 Best UB 的規則

若任一模型沒有收斂到 Gap = 0%，計算 VSS / EVPI 時不要使用 ObjVal 混算，統一使用 Best UB：

```text
RP_used  = RP_BestUB
EEV_used = EEV_BestUB
WS_used  = sum_s p_s * WS_s_BestUB

VSS_used  = EEV_used - RP_used
EVPI_used = RP_used - WS_used
VSS(%)    = VSS_used / abs(RP_used) * 100
EVPI(%)   = EVPI_used / abs(RP_used) * 100
```

所有 summary 仍需保留 Best LB、Best UB、Gap，讓使用者知道指標可信度。

## RP

呼叫 SP extensive form 求解。

輸出：

- RP summary
- RP variables
- RP solve log

## EV

1. 使用與 RP 同一批 scenarios。
2. 對隨機參數取 scenario average。
3. 解 deterministic expected-value model。
4. 保存 `x_EV = X_j, v_j, theta_j, y_hj`。

輸出：

- EV summary
- EV first-stage variables
- EV deterministic second-stage variables

## EEV

1. 建立 evaluation model。
2. 固定所有 first-stage variables 為 EV 解：
   - X_j
   - v_j
   - theta_j
   - y_hj
3. 在原始 scenarios 上解 recourse evaluation。
4. objective 必須包含 fixed first-stage cost + expected recourse cost。

輸出：

- EEV summary
- fixed first-stage variables
- scenario recourse variables
- EEV solve log

## WS

1. 對每個 scenario s：
   - 將該 scenario 的隨機參數視為確定值。
   - 解 deterministic model。
   - first-stage variables 可以隨 scenario 改變，因為 wait-and-see 代表完美資訊。
2. `WS = sum_s p_s * WS_s_BestUB`。

輸出：

- WS overall summary
- WS per-scenario summary
- WS per-scenario first-stage variables
- WS per-scenario second-stage variables

## 邏輯檢查

完成後要檢查：

- `WS <= RP <= EEV` 是否大致成立。
- 若不成立，標記 warning，不要硬改數字。
- 若因未收斂或 MIP gap 造成不等式不成立，要在 summary 中註明。

## 輸出 summary 欄位

至少包含：

- RP_BestLB, RP_BestUB, RP_Gap
- EV_BestLB, EV_BestUB, EV_Gap
- EEV_BestLB, EEV_BestUB, EEV_Gap
- WS_BestLB, WS_BestUB, WS_Gap 或 per-scenario gap summary
- VSS
- EVPI
- VSS(%)
- EVPI(%)
- used_bound = BestUB
- warning flags

## 驗收條件

1. WS 是每個 scenario 解一次 deterministic model 後加權平均。
2. EEV 是固定 EV 的一階決策後回到原 scenarios 評估。
3. VSS / EVPI 對成本最小化公式方向正確。
4. 未收斂時使用 Best UB 計算。
5. 所有中間模型都保留自己的 summary 與 log。

## 完成後停止

完成 VSS / EVPI 後停止，列出 RP、EV、EEV、WS 的數值與檢查結果。不要開始寫 stress test 批次輸出。
