# 13 — 規模 pilot → PDR 校準 scope → 重跑實驗一（交接執行計畫）

本計畫給執行模型照步驟操作。背景：2026-07-10 的實驗一結果顯示 S=30 全規模
下所有 case 跑滿 3600 秒仍有 0.2%–4.3% gap，α×λ 矩陣出現單調性違反
（gap 雜訊），且 polyhedral 的 scope（a_P=0.001）太小、穩健溢價被雜訊淹沒。
因此依序做：A. 找出能收斂的情境數 S* → B. 在 S* 下跑 PDR 並選定各 set 的
scope → C. 用選定 scope 與 S* 重跑實驗一。

## 鐵律（違反任何一條就停止並回報）

1. **不可修改** `model core/`、`model portal/` 下的任何檔案。
2. 只能修改 `run experiment/batch_risk_experiment.py` 與
   `run experiment/batch_pdr_experiment.py` **頂端 Parameter setting area
   的常數值**；不可改動這兩支檔案的函式邏輯。
3. 一次只跑一個 runner（兩個同時跑會互搶 log 搬移，資料會錯亂）。
4. `experiment result/` 內既有檔案一律不可刪除或覆蓋；每步的
   `RESULT_PREFIX` 都要照本計畫改名。
5. 每個 Step 結束必須停止，用文末的回報格式回報，等使用者確認才進下一步。
6. 若遇到 Python 例外、FAIL case、或判讀條件不成立，停止並回報，不要自行
   發明修法。

## Step A — 規模 pilot（找 S*）

目的：找出「gap=1e-4 能在 3600 秒內收斂」的最大情境數 S*。

操作：編輯 `run experiment/batch_risk_experiment.py` 的參數區，設：

```python
AMBIGUITY_SETS = ["box"]
ALPHA_VALUES   = [0.9]
LAMBDA_VALUES  = [0.5]
SCOPES         = {"box": 0.01, "ellipsoidal": 0.0005, "polyhedral": 0.001}
BASE_SCENARIOS = 10          # 第一輪
TIME_LIMIT     = 3600.0
MIP_GAP        = 1e-4
RESULT_PREFIX  = "PILOT_scale_S10"
```

（其他 BASE_* 不動。若檔案目前處於 ellipsoidal-only 模式，仍只改上列常數；
若有 `REQUIRE_FIRST_CASE_SUCCESS` 之類旗標，維持原值。）

執行 `python "run experiment/batch_risk_experiment.py"`，跑完記錄 raw CSV
裡該 case 的 `cpu_s`、`gap_pct`、`solver_status`。

然後依序把 `BASE_SCENARIOS` 改成 15、20、25（`RESULT_PREFIX` 同步改
S15/S20/S25），重複執行。**升到某個 S 出現「solver_status ≠ OPTIMAL 或
cpu_s > 3000」就停**，不用再往上。

判讀：S* = 「solver_status=OPTIMAL 且 cpu_s ≤ 3000」的最大 S。
若 S=10 都不滿足 → 停止回報（本計畫終止，由使用者決策）。
完成後回報各 S 的 (cpu_s, gap_pct, status) 與選定的 S*。

## Step B — PDR 掃描並選定 scope（需使用者確認 S* 後執行）

操作：編輯 `run experiment/batch_pdr_experiment.py` 參數區，設：

```python
RISK_ALPHA_FIXED  = 0.9
RISK_LAMBDA_FIXED = 0.9
SCOPE_VALUES = {
    "box":         [0.001, 0.005, 0.01, 0.02, 0.03],   # 全部須 ≤ 1/S*
    "ellipsoidal": [0.00005, 0.0001, 0.0005, 0.001, 0.01],
    "polyhedral":  [0.001, 0.01, 0.05, 0.1, 0.3],      # 比舊值大，重點修正
}
AMBIGUITY_SETS = ["box", "polyhedral"]   # ellipsoidal 若已可解才加回
BASE_SCENARIOS = <S*>
TIME_LIMIT     = 3600.0
MIP_GAP        = 1e-4
RESULT_PREFIX  = "DRO_PDR_S<S*>"
```

box scope 檢查：若 0.03 > 1/S*（例 S*=25 時 1/25=0.04 沒問題；S*=40 時要
刪掉超標值），把超過 1/S* 的值從清單移除。

執行後判讀（每個 set 分開）：

1. PDR 必須全部 ≥ 0 且隨 scope 單調不減；出現負值或大幅非單調 → 停止回報。
2. 選 scope：取「PDR 落在 0.1%–0.5% 區間」的 scope 當正式值；若整條曲線
   都 < 0.1%，取合法範圍內最大的 scope；若都 > 0.5%，取最小的。
3. 回報 PDR 表與選定的 ω*、a_P*（、a_E*），等使用者確認。

## Step C — 重跑實驗一（α×λ 網格，需使用者確認 scope 後執行）

操作：編輯 `run experiment/batch_risk_experiment.py` 參數區，設：

```python
AMBIGUITY_SETS = ["box", "polyhedral"]   # ellipsoidal 可解才加回
ALPHA_VALUES   = [0.5, 0.6, 0.7, 0.8, 0.9]
LAMBDA_VALUES  = [0.3, 0.5, 0.7, 0.9]
SCOPES         = {"box": <ω*>, "ellipsoidal": <a_E* 或原值>, "polyhedral": <a_P*>}
BASE_SCENARIOS = <S*>
TIME_LIMIT     = 3600.0
MIP_GAP        = 1e-4
RESULT_PREFIX  = "DRO_alpha_lambda_S<S*>_final"
```

case 數 = 2 sets × 20 組合 = 40（加 ellipsoidal 則 60）。逐 case 重寫輸出，
可中途檢視。

完成判讀：console 的單調性檢查必須「趨勢檢查通過」；若有 [WARN]（obj 未隨
α/λ 遞增超出容差），列出違反的格子回報，不要自行重跑。

## Step D — B&BC ablation（本計畫範圍外）

實驗一重跑確認後，ablation 依 `plan/12_ABLATION_EXPERIMENT_PROMPT.md`
執行；其中 `BENDERS_PARETO_ENABLED` 開關需要動 `model core/lshaped_core.py`，
**不屬於本計畫的權限範圍**，須由使用者另行安排。

## 每步回報格式

```text
階段完成：Step <A/B/C>

1. 修改的參數（檔案 + 常數 + 新值）
2. 執行結果檔案（CSV / xlsx / log 路徑）
3. 關鍵數字（依該步的判讀項目）
4. 判讀結論（S* / 選定 scope / 單調性是否通過）
5. 異常與未處理事項

我已停止，等待使用者確認後再進入下一步。
```
