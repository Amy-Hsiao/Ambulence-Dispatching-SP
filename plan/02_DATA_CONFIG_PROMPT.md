# Prompt 02：完成 config.py 與資料生成流程

請根據專案規範完成 `config.py` 與必要的資料 schema / scenario generator。此階段只做資料層，不要實作最佳化模型。

## 輸入資料

讀取\data裡面的原始 CSV：
1. disaster_Daan_6.0.csv:災區 CSV：index 與座標。
2. ccp_Daan.csv: CCP CSV：index 與座標。
3. hospital_Daan.csv: 醫院 CSV：index 與座標。


## 必須生成的集合

- I：disaster areas。
- J：candidate CCPs。
- H：hospitals。
- L：severity levels = minor, moderate, severe。
- L_transfer：需要救護車與醫院轉送的 severity = moderate, severe。
- T：可自由調整 period 數量。
- S：可自由調整 scenario 數量。

## 必須生成的 deterministic parameters

依 parameter setting 建立：

- CCP fixed opening cost。
- staff unit assignment cost。
- CCP ambulance unit assignment cost。
- supply allocation cost from hospital h to CCP j。
- total available staff。
- total available CCP ambulances。
- hospital supply upper bound。
- CCP staff upper bound。
- CCP ambulance upper bound。
- CCP supply upper bound。
- hospital ambulance fleet。
- CCP physical capacity by severity。
- treatment duration by severity。
- staff treatment rate by severity。
- supply consumption by severity。
- disaster-area remaining penalty by severity。
- CCP waiting penalty by severity。

## 距離、容量與運輸成本

1. 讀取災區、CCP、醫院座標。
2. 計算 disaster area i 到 CCP j 的距離 `distance_ij_m`。
3. 計算 CCP j 到 hospital h 的距離 `distance_jh_m`。
4. 產生正常道路容量：
   - `cap_ij = distance_ij_m * 0.05`
   - `cap_jh = distance_jh_m * 0.05`
5. 產生運輸成本：
   - `cost_ij = 100 + 150 * distance_ij_m / 1000`
   - `cost_jh = 100 + 150 * distance_jh_m / 1000`
6. 座標單位要可設定：
   - 若 CSV 是 TWD97、平面座標或已是公尺，使用 Euclidean。
   - 若 CSV 是 lat/lon，使用 haversine。

## 隨機參數生成

所有隨機種子必須固定，且要使用 master seed 加上 scenario id / period id / link id 的穩定子種子，確保：

- S 從 5 改成 10 時，前 5 個 scenario 不變。
- T 從 4 改成 8 時，前 4 期資料不變。
- 重跑同一設定，所有資料完全相同。

### Demand

- demand multiplier(是一個可以手動調整的參數) 。
- baseline multiplier = 1。
- 每一期新傷患數 = U[0, 10] x demand multiplier。
- severity probability = minor 60%, moderate 30%, severe 10%。
- 支援 demand scale，例如 D x 0.5、D x 2。

### Road availability u_ijts / w_jhts

- road capacity mutiplier(是一個可以手動調整的參數)。
- baseline multiplier = 1。
- first-period availability ~ U[0, 0.4]。
- recovery rate ~ U[0.05, 0.08]。
- period t availability = min(first_availability x road capacity multiplier + recovery_rate * (t - 1), 1)。
- 支援 road capacity scale，例如 C x 0.5、C x 2。

### Hospital receiving capacity h_hts

- hospital capacity mutiplier(是一個可以手動調整的參數)。
- baseline multiplier = 1。
- period 1 capacity = U[25, 50] x hospital capacity mutiplier。
- period t capacity = period 1 capacity * 0.9^(t - 1)。
- 支援 hospital capacity scale，例如 H x 0.5、H x 2。

## deterministic 平均資料

需要支援兩種 deterministic data：

1. baseline deterministic：使用 baseline multiplier = 1，適合壓力測試 B00。
2. expected-value deterministic：使用同一批 scenarios 的 scenario average，適合 EV / VSS / EVPI。

注意：EV 計算應使用與 RP 相同的 scenarios 平均，不要用另一批 random draw。

## 輸出

資料層應能輸出：

- instance JSON。
- scenario data CSV 或 JSON。
- distance matrices。
- parameter summary。
- random seed audit table。

## 驗收條件

1. 同一 seed 重跑，輸出完全一致。
2. S 增加時，前面 scenarios 完全一致。
3. T 增加時，前面 periods 完全一致。
4. 所有距離、容量、成本矩陣維度正確。
5. `validate_instance` 能檢查：索引唯一、無負值、維度一致、scenario probability 加總為 1、所有必要參數存在。

## 完成後停止

完成本階段後請列出 config.py 的主要函數、輸入輸出格式與測試結果。不要開始寫 deterministic model。
