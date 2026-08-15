# 16 — 台北全區放大規模：參數重新縮放與 ablation 重跑（2026-08）

老師的兩點意見：(1) 規模太小；(2) 實驗後 B&BC 的加速效果不夠明顯。
本文件記錄放大規模的資料選擇、參數縮放依據，以及重跑 ablation 的設定。

---

## 0. 資料來源改變

| 集合 | 舊（東區） | 新（台北全區） | 檔案 |
|---|---|---|---|
| 災區 I | 129 | **229** | `data/disaster_Taipei.csv` |
| CCP J | 10 | **50** | `data/ccp_Taipei_50.csv` |
| 醫院 H | 16 | **20** | `data/hospital_Taipei.csv` |

### 0.1 CCP 候選點為什麼是 50 個

老師要求 |J| = 50，但 `data/ccp_Taipei.csv` 只有 **16** 個真實 CCP。
因此以 `run experiment/build_ccp_candidates_taipei.py` 補足到 50 個
**候選設置點**（完全確定性、固定 seed、可重現）：

1. 對 229 個真實災區節點做 K-means（k = 50，k-means++ 初始、20 次重啟取
   inertia 最小），得到 50 個空間分散的質心。質心 = 需求節點的幾何中心，
   是設施選址文獻中標準的候選點生成啟發式。
2. 把 16 個真實 CCP 貪婪指派到離它最近、尚未被占用的質心，用真實座標取代。
3. 修補與災區節點重合的質心（單點群集的質心會落在該節點上，造成
   `distance_ij = 0` 退化）：改取「該節點與其最近鄰居的中點」。

結果：**16 個真實 CCP + 34 個由真實災區地理衍生的候選點**。
候選點兩兩最小距離 549 m、候選點與災區最小距離 109 m，無退化。

> ⚠️ 論文寫作時要明確說明：34 個是「候選設置點」，不是既有設施。
> 若日後拿到真正的 50 筆 CCP 資料，直接覆蓋 `data/ccp_Taipei_50.csv`
> （欄位 `,X,Y`），`config.py` 不需改動。

### 0.2 為什麼 |J| 變大有助於凸顯 B&BC

B&BC 的優勢在於「把巨大的第二階段丟給 oracle，master 只留一階變數」。

| | 一階 0-1 變數 | 第二階段變數（估計） |
|---|---|---|
| 舊（J=10, I=129, S=30, T=8） | 10 | ~40 萬 |
| 新 large（J=50, I=130, S=30, T=8） | **50** | **~192 萬** |

Extensive form 要一次吞下 190 萬個變數；B&BC 的 master 只有 50 + 30 = 80 個
變數。規模差距拉開後，加速比才會明顯。

---

## 1. 三個 case 的網路規模

老師指定：災區 70~130 取三組、CCP 50、醫院 18。

| Case | 災區 I | CCP J | 醫院 H |
|---|---|---|---|
| **small** | **70** | 50 | 18 |
| **medium** | **100** | 50 | 18 |
| **large** | **130** | 50 | 18 |
| （full 參考） | 229 | 50 | 20 |

抽樣沿用 `SCALE_SAMPLING_MODE = "nested"`：small ⊂ medium ⊂ large ⊂ full，
固定 seed shuffle 後取前綴，三個規模是「同一張圖的放大/縮小」，跨規模比較乾淨。
|J| = 50 三規模完全相同 → 一階決策空間一致，時間差異純粹來自規模。

---

## 2. 參數縮放：核心觀念（本次最重要的修正）

### 2.1 分母必須是「校準規模」，不是「資料檔筆數」

`PARAMETERS` 區的數值（`total_available_staff = 550` 等）是在**東區全量
（I=129, J=10, H=16）** 上校準出來的。舊版 `resolve_scale()` 用
`N_DISASTER_FULL`（= 資料檔筆數）當分母，換資料集後會出錯：

> 若把 `N_DISASTER_FULL` 改成 229，則 large (I=130) 的 s_D = 130/229 = 0.57，
> 醫護池只剩 550×0.57 = 314 人 —— 但 I=130 的實際需求跟東區全量 (129) 幾乎
> 一樣。資源憑空少了 43%，解出來會被大量未服務罰金主導，非常奇怪。

因此新增三個**校準基準常數**，縮放一律以此為分母：

```python
PARAM_CALIB_N_DISASTER = 129   # PARAMETERS 校準時的 |I|
PARAM_CALIB_N_CCP      = 10    # 校準時的 |J|
PARAM_CALIB_N_HOSPITAL = 16    # 校準時的 |H|
```

`N_DISASTER_FULL / N_CCP_FULL / N_HOSPITAL_FULL`（229/50/20）改為只表示
「CSV 實際筆數」，供 `full` profile 與上限驗證使用。

### 2.2 三個縮放驅動因子

| 因子 | 公式 | 驅動哪些參數 | 依據 |
|---|---|---|---|
| `demand_scale` s_D | `\|I\| / 129` | 全域資源池 | 每災區每期產生 U[1,5] 需求 → 系統總需求 ∝ \|I\| |
| `ccp_scale` s_J | `s_D`（預設） | per-CCP 上限 | 見 §2.3 |
| `hospital_scale` s_H | `s_D × (16 / \|H\|)` | per-醫院上限 | per-醫院負載 ∝ 總轉送量/\|H\| ∝ \|I\|/\|H\| |

### 2.3 per-CCP 上限：為什麼不隨 |J| 稀釋（`demand_only`）

新增開關 `CCP_UPPER_BOUND_SCALING`，預設 `"demand_only"`：

* **`demand_only`（預設，採用）**：per-CCP 上限只隨總需求縮放，不因候選點
  從 10 個變成 50 個而變小。
  **理由**：單一 CCP 的收治量／人力上限是「設施的物理屬性」，不會因為
  規劃時多列了幾個候選地點就縮水。此時**全域資源池仍是綁定約束**
  （555 醫護 ÷ 每 CCP 上限 105 ≈ 5.3），實際開設數量由全域池與固定開設成本
  （150 萬/座）自然限制 → 一階決策變成「從 50 個候選點挑約 5~6 個」的
  典型選址問題，組合數 C(50,6) ≈ 1,590 萬，對 B&BC 非常有利。
* **`per_ccp_load`（備選）**：per-CCP 上限額外乘 `10/|J|` = 0.2，維持
  「Σ per-CCP 上限 / 全域池」比值與校準情境完全相同。此時會開出約 26 座
  CCP，目標值被固定開設成本（26 × 150 萬 = 3,900 萬）主導，且物理上難解釋。

> 兩種模式都保留在 config，切換只改一個字串，不動任何求解邏輯。

### 2.4 不縮放的參數（沿用 plan/15 §3.3）

單價／成本、罰金、治療速率、單車運能、傷級機率、速度／期長 —— 全部維持
不變。跨規模的目標值才可比。

---

## 3. 縮放後的實際數值（`ceil` 進位，已驗算）

| 參數 | 校準值 | small (I=70) | medium (I=100) | large (I=130) |
|---|---|---|---|---|
| s_D | 1.000 | 0.543 | 0.775 | 1.008 |
| s_J | 1.000 | 0.543 | 0.775 | 1.008 |
| s_H | 1.000 | 0.482 | 0.689 | 0.896 |
| `total_available_staff` | 550 | **299** | **427** | **555** |
| `total_available_ccp_ambulances` | 132 | **72** | **103** | **134** |
| `ccp_staff_upper_bound` | 104 | **57** | **81** | **105** |
| `ccp_ambulance_upper_bound` | 18 | **10** | **14** | **19** |
| `ccp_supply_upper_bound` | 2000 | **1086** | **1551** | **2016** |
| `ccp_physical_capacity` minor | 143 | **78** | **111** | **145** |
| `ccp_physical_capacity` moderate | 43 | **24** | **34** | **44** |
| `ccp_physical_capacity` severe | 14 | **8** | **11** | **15** |
| `hospital_supply_upper_bound` | 600 | **290** | **414** | **538** |
| `hospital_ambulance_fleet` | 18 | **9** | **13** | **17** |

### 3.1 結構一致性驗算

| 檢查 | small | medium | large | 結論 |
|---|---|---|---|---|
| 全域醫護池 < Σ per-CCP 上限 | 299 < 2850 | 427 < 4050 | 555 < 5250 | ✅ 全域池為綁定約束 |
| 全域池 ÷ per-CCP 上限（≈ 可開設數） | 5.2 | 5.3 | 5.3 | ✅ 三規模一致 |
| 每情境總需求 | 1872 | 2680 | 3489 | ✅ 與 \|I\| 成正比 |
| 每期需求 | 234 | 335 | 436 | |
| 每期轉送需求（mod+sev） | 94 | 134 | 174 | |
| 每期醫院收治容量 | 509 | 509 | 509 | ✅ 醫院端不會過緊 |

`tests/test_scale_profiles.py` 已把上述數值與結構不變量寫成 11 條回歸測試。

---

## 4. 隨機變數範圍：一律不改（沿用 plan/15 §5）

per-entity（每災區／每路段／每醫院）的隨機範圍不隨規模改變；總量的縮放
透過 entity「數量」達成。需求 U[1,5]、全域 omega [0.8,1.2]、空間乘數
[0.5,1.5]、路況 U[0,0.4]、醫院容量 U[30,50] —— 全部維持原值。
空間群集數維持 3（70/100/130 皆遠大於 3）。

---

## 5. Ablation 實驗重跑設定

`run experiment/batch_ablation_experiment.py`

### 5.1 實驗矩陣：3 × 4 × 6 = **72 個 case**

| 維度 | 內容 |
|---|---|
| Scale (3) | small / medium / large |
| Model (4) | `SP+MCVaR`、`DRO-box`、`DRO-ellipsoidal`、`DRO-polyhedral` |
| Config (6) | Extensive、BBC、BBC+WS、BBC+WS+RS、BBC+WS+RS+UC、BBC+WS+RS+UC+Pareto |

Ambiguity set scope：box `ε̄_B = 0.01`（須 ≤ min_s p0_s = 1/30 ≈ 0.0333 ✅）、
ellipsoidal `a_E = 0.0005`、polyhedral `a_P = 0.001`。
風險參數 α = 0.9、λ = 0.5。S = 30、T = 8。

### 5.2 求解時間與提早結束

```python
TIME_LIMIT = 7200.0     # 每個 case 上限 2 小時
MIP_GAP    = 0.01       # relative MIP gap ≤ 1% 立即停止
```

Gurobi 的 `MIPGap` 本身就是提早終止條件：一旦 `(UB−LB)/|UB| ≤ 1%` 就回傳
`OPTIMAL` 並停止，不會跑滿 2 小時。**六種 config 共用同一門檻**，時間比較
才公平（同收斂精度下比時間）。跑不到 1% 的 case 才會用滿 `TIME_LIMIT`，
此時 `gap_pct` 欄位會記錄實際殘餘 gap。

子程序硬超時緩衝由 900 s 加大到 **1800 s**（規模放大後建模與寫回較久，
避免跑滿時限的 case 在寫回結果前被誤砍成 FAIL）。

> 最壞情況總時間 = 72 × 2 hr = 144 小時。實務上多數 case 會提早收斂，
> 但仍建議先跑 §6 的 pilot，再排長時間執行。

### 5.3 Excel 輸出

分頁：`raw_results`、`run_settings`、`small`、`medium`、`large`、`summary_table`。

**`summary_table` 依老師要求新增 objective value**：每個 config 的子欄位由
原本 3 欄改為 4 欄 —— **`Obj Value`** / `A.Time` / `A.Gap(%)` / `Nodes`。
表格結構：列 = Scale × Model（3 × 4 = 12 列），欄 = 5 + 6 × 4 = 29 欄。

`run_settings` 另外新增資料檔名、校準基準、`ccp_upper_bound_scaling`、
以及三個規模的 s_D / s_J / s_H，確保實驗設定可完整追溯。

### 5.4 中斷續跑

raw CSV 在**每個 case 結束後**就原子性重寫一次，已完成的 case 絕不會白跑。

* Ctrl+C 中斷 → 程式攔截 `KeyboardInterrupt`，保存結果並直接印出要貼的檔名。
* 正常結束但有 case 未完成 → 同樣會印出續跑指令。
* 續跑：把最新的 `..._raw_YYYYmmdd_HHMMSS.csv` 檔名貼進參數區
  `RESUME_FROM_CSV`，重新執行即可。只補跑「缺少或非 OK」的 case，
  並把上次已完成的併進本次新輸出，得到完整一份。

### 5.5 模型規模與硬超時（放大後的重要影響）

Extensive form 一次建出所有情境，變數量由 `FI = S·|I|·|J|·|L|·|T|` 主導：

| | 上一版（東區 J=10） | 本版（台北 J=50） | 倍數 |
|---|---|---|---|
| small | 206,490 | **3,099,450** | 15× |
| medium | 384,130 | **4,201,050** | 11× |
| large | 640,970 | **5,302,650** | 8× |

B&BC 則完全不受影響：master 永遠只有 **50 個 0-1 + 30 個 θ = 80 個變數**，
每個情境 oracle 約 10~18 萬變數且逐一求解。**這就是加速效果會變明顯的原因。**

因此硬超時改為依引擎分開設定：

```python
HARD_TIMEOUT_BUFFER_SEC           = 1800.0   # B&BC 類 → 每 case 上限 150 分鐘
HARD_TIMEOUT_BUFFER_SEC_EXTENSIVE = 5400.0   # Extensive → 每 case 上限 210 分鐘
```

> ⚠️ **Extensive form 在 medium / large 有可能因記憶體不足被系統終止**
> （530 萬變數的 MIP 可能需要數十 GB RAM）。這種情況會被記成 `FAIL` 並
> **繼續跑下一個 case**，不會中斷整批；`note` 欄位會註明疑似 OOM。
> 對 ablation 而言「Extensive 在此規模已無法求解」本身就是有意義的結果。

### 5.6 Excel 依賴

需要 **`openpyxl`**（不是 openxml）。程式在跑任何求解前就會先 preflight
檢查，缺套件會立刻失敗而不是白跑好幾小時。安裝：

```
python -m pip install openpyxl
```

---

## 6. 執行順序

```
1. python "run experiment/build_ccp_candidates_taipei.py"   # 產生 50 個 CCP 候選點（已跑過，檔案已在）
2. python -m unittest tests.test_scale_profiles tests.test_batch_ablation_experiment
3. python tests/dry_run_ablation.py                         # 全流程 dry run（不需 Gurobi，約 1 分鐘）
4. python "run experiment/pilot_scale_feasibility.py"       # 快速可行性檢查（S=5, gap=5%, 300s）
5. python "run experiment/batch_ablation_experiment.py"     # 正式 72 case
```

第 4 步的 pilot 會檢查：三規模都求得可行解、開設的 CCP 數量落在合理區間
（不是 0 個也不是 50 個全開）。**通過再跑第 5 步**，避免長時間白跑。

### 6.1 不會讓整批實驗中止的保護

| 狀況 | 行為 |
|---|---|
| 單一 case 求解例外 / Gurobi 報錯 | 記 `FAIL` + `note`，繼續下一個 case |
| Extensive 記憶體不足被系統砍掉 | 子程序 exit code 非 0 → 記 `FAIL`（註明疑似 OOM），繼續 |
| 單一 case 卡住超過硬超時 | 子程序被強制終止 → 記 `FAIL`（Hard timeout），繼續 |
| **輸出 Excel/CSV 正被 Excel 開著** | 重試 5 次；Excel 途中匯出失敗只警告，CSV 另存 rescue 檔，**不中止** |
| Ctrl+C 中斷 | 攔截、保存結果、印出續跑用的檔名 |
| 缺 openpyxl / gurobipy | 在跑任何求解**之前**就 preflight 失敗，不會白跑 |

`tests/dry_run_ablation.py` 用假求解器涵蓋以上情境，共 34 項檢查全數通過。

---

## 7. 求解核心零改動（重要）

本次修改僅涉及：

| 檔案 | 改動 |
|---|---|
| `model core/config.py` | 資料檔常數、`SCALE_PROFILES`、校準基準、`resolve_scale()`、`_build_deterministic_parameters()` 的 `ccp_scale` 參數、metadata |
| `run experiment/batch_ablation_experiment.py` | 實驗矩陣、時限/gap、summary 欄位、續跑提示 |
| `tests/test_scale_profiles.py`、`tests/test_batch_ablation_experiment.py` | 回歸測試更新 |
| `run experiment/build_ccp_candidates_taipei.py`、`pilot_scale_feasibility.py` | 新增工具 |

**以下檔案完全未動**（`git diff --ignore-cr-at-eol` 確認為零）：

```
model core/lshaped_core.py          model portal/benders bbc.py
model core/extensive_form_core.py   model portal/dro bbc.py
model core/risk_core.py             model portal/mcvar bbc.py
model core/vss_evpi.py              model portal/extensive_dro.py
                                    model portal/extensive form.py
                                    model portal/deterministic form.py
```

---

## 8. 一句話總結

資料換成台北全區、CCP 候選點補到 50、災區取 70/100/130；資源縮放的分母
從「資料檔筆數」改回「PARAMETERS 的校準規模 (129/10/16)」，per-CCP 上限
不因候選點變多而稀釋，使三個規模都維持「全域池綁定、約開 5~6 座 CCP」的
一致結構；ablation 擴成 3×4×6 = 72 個 case，每案 2 小時上限、gap ≤ 1% 提早
結束，summary 分頁加上 objective value，中斷可續跑。求解核心一行未改。
