# 15 — 規模 Profile 設計：small / medium / large case（config 統一選擇機制）

本計畫定義如何把「東區全資料」抽樣成 small / medium / large 三種規模的
實驗案例，並在 `config.py` 建立**單一開關**：實驗程式只要指定
`EXPERIMENT_SCALE = "small" | "medium" | "large"`，config 就會自動調出對應
的路網規模與所有隨規模縮放的參數。本文件為設計 + 實作規格；先確認設計，
再進實作。

---

## 0. 背景與現況分析

### 0.1 現有資料規模（東區全量）

| 集合 | 檔案 | 全量筆數 |
|---|---|---|
| 災區 I | `east_district_disaster.csv` | **129** |
| CCP J | `east_district_ccp.csv` | **10** |
| 醫院 H | `east_district_hospital.csv` | **16** |

情境 `SCENARIOS=5`、期數 `TIME_PERIODS=8`（與規模正交，見 §7）。

### 0.2 現況機制與問題

- `generate_data(sample_ratio, ccp_sample_size)` 目前用**單一 `SAMPLE_RATIO`**
  同時抽樣 I 與 H（同比例），CCP 另用 `CCP_SAMPLE_SIZE` 抽。
- 資源縮放 `ccp_resource_scale = actual_ccp_count / full_ccp_count`
  （config.py L556-560）。**只綁 CCP 數**。
- **問題**：本計畫要求 **CCP 固定 10（= 全部）**，於是
  `ccp_resource_scale ≡ 10/10 = 1.0` → 不論路網縮多小，
  `total_available_staff`、`total_available_ccp_ambulances` **都不會變小**。
  這正是「路網變小、可派遣醫生上限卻沒變少」的破口。
- 另外，`ccp_staff_upper_bound`、`ccp_ambulance_upper_bound`、
  `ccp_supply_upper_bound`、`ccp_physical_capacity_by_severity`、
  醫院端上限**目前完全不隨規模縮放**（`_build_deterministic_parameters`
  只縮兩個 total pool）。

### 0.3 修正核心思路

CCP 數固定 → 不能再用 CCP 數當縮放驅動。**改以災區數 |I| 當需求驅動**：
每個災區每期產生 `U[1,5]` 需求，總需求 ∝ |I|，因此系統資源池與 per-CCP
容量都應以 `|I| / 129` 縮放；醫院端上限以「per-醫院負載」縮放（見 §5）。

---

## 1. 三個 case 的網路規模（結論先講）

CCP 一律 = 10（全部 CCP 都是候選點；符合需求）。I、H 由東區資料抽樣，
large 明顯小於全量 129。

| Case | 災區 I | CCP J | 醫院 H | 佔全量 I 比例 `s_I=I/129` |
|---|---|---|---|---|
| **small** | **20** | **10** | **6** | 15.5% |
| **medium** | **40** | **10** | **10** | 31.0% |
| **large** | **70** | **10** | **14** | 54.3% |
| （full 參考） | 129 | 10 | 16 | 100% |

規模大致等比成長（I：20→40→70），large ≈ 全量的一半，符合「比全用還小」。
三者 |I| 皆 ≥ 3×群集數，K-means 空間異質性成立（見 §6）。

---

## 2. 選擇機制設計（config 單一開關）

### 2.1 新增模組級設定

在 `config.py` 參數區新增：

```python
# ── 規模 Profile（small/medium/large/full；實驗程式只改這一個開關）──
EXPERIMENT_SCALE = "medium"   # "small" | "medium" | "large" | "full"

N_DISASTER_FULL = 129   # 東區全量（= CSV 筆數，供縮放基準）
N_HOSPITAL_FULL = 16
N_CCP_FULL      = 10

SCALE_PROFILES = {
    "small":  {"n_disaster": 20,  "n_hospital": 6,  "n_ccp": 10, "spatial_clusters": 3},
    "medium": {"n_disaster": 40,  "n_hospital": 10, "n_ccp": 10, "spatial_clusters": 3},
    "large":  {"n_disaster": 70,  "n_hospital": 14, "n_ccp": 10, "spatial_clusters": 3},
    "full":   {"n_disaster": 129, "n_hospital": 16, "n_ccp": 10, "spatial_clusters": 3},
}
```

### 2.2 縮放因子（兩個驅動）

```python
def resolve_scale(scale: str) -> dict:
    p = SCALE_PROFILES[scale]
    s_I = p["n_disaster"] / N_DISASTER_FULL          # 需求驅動：total pool + per-CCP
    s_H = s_I / (p["n_hospital"] / N_HOSPITAL_FULL)  # per-醫院負載驅動：per-醫院上限
    return {**p, "demand_scale": s_I, "hospital_scale": s_H}
```

- `s_I = |I| / 129`：驅動全域資源池與 per-CCP 上限（因為 CCP 數固定，
  per-CCP 負載 ∝ 總需求/|J| ∝ |I|）。
- `s_H = s_I / (|H|/16)`：驅動 per-醫院上限。醫院數本身已縮，per-醫院負載
  ∝ 總轉送量/|H| ∝ |I|/|H|，故用此因子維持 per-醫院鬆緊度與全量一致。

### 2.3 實驗程式端用法（目標體驗）

實驗 runner 只要在參數區設定：

```python
cfg.EXPERIMENT_SCALE = "small"   # 或 "medium" / "large"
```

其餘沿用現有 `patched_generate_data()` 覆寫慣例；`generate_data()`
預設 `scale = EXPERIMENT_SCALE`，自動抽出對應規模與參數。

---

## 3. 哪些參數「隨規模縮放」、哪些「不縮放」（研究結論）

分類原則：**外延量（extensive，與系統規模成正比）縮放；內涵量
（intensive，單位速率/機率/單價）不縮放。**

### 3.1 隨 |I| 縮放（× `s_I`，`ceil` 進位，沿用現有 rounding）

| 參數 | 意義 | 為何縮 |
|---|---|---|
| `total_available_staff` | 全系統可派遣醫護總量 | 需求 ∝ |I| |
| `total_available_ccp_ambulances` | 全系統 CCP 救護車總量 | 需求 ∝ |I| |
| `ccp_staff_upper_bound` | 單 CCP 醫護上限 | per-CCP 負載 ∝ |I|/|J|，|J| 固定 |
| `ccp_ambulance_upper_bound` | 單 CCP 救護車上限 | 同上 |
| `ccp_supply_upper_bound` | 單 CCP 物資上限 | 物資消耗 ∝ 需求 |
| `ccp_physical_capacity_by_severity` | 單 CCP 各傷級收治量 | 收治量 ∝ 需求 |

> 「可派遣醫生上限變少」= `total_available_staff` +
> `ccp_staff_upper_bound` 兩層，本設計兩層一起縮，維持
> 「全域池 < Σ per-CCP 上限」的綁定關係（見 §5.2 驗算）。

### 3.2 隨 per-醫院負載縮放（× `s_H`）

| 參數 | 意義 |
|---|---|
| `hospital_supply_upper_bound` | 單醫院物資上限 |
| `hospital_ambulance_fleet` | 單醫院救護車隊 |

> 醫院總容量 = per-醫院上限 × |H|。|H| 已隨 profile 縮，再乘 `s_H`
> 使 per-醫院鬆緊度對齊全量，避免小 case 醫院端過鬆或過緊。

### 3.3 **不縮放**（內涵量 / 單價 / 速率 / 機率）

| 類別 | 參數 | 為何不縮 |
|---|---|---|
| 單價/成本 | `ccp_fixed_opening_cost`、`staff_unit_assignment_cost`、`ccp_ambulance_unit_assignment_cost`、`supply_allocation_cost_unit` | 單位成本，縮了目標值不可比 |
| 罰金 | `disaster_area_remaining_penalty_by_severity`、`ccp_waiting_penalty_by_severity` | 單位懲罰，需跨規模可比 |
| 速率/時長 | `treatment_duration_by_severity`、`staff_treatment_rate_by_severity`、`supply_consumption_by_severity` | 物理速率，與規模無關 |
| 單車運能 | `ccp_ambulance_casualty_capacity`、`hospital_ambulance_casualty_capacity` | 每車固定 2 人 |
| 機率 | `SEVERITY_PROBABILITY` | 傷級分布，與規模無關 |
| 速度/期長 | `ASSUMED_SPEED_MPS`、`PERIOD_DURATION_SEC` | 物理常數 |

---

## 4. 縮放後參數數值（三個 case，已用 `ceil` 驗算）

### 4.1 全域資源池 + per-CCP（× `s_I`）

| 參數 | 全量 | small (20) | medium (40) | large (70) |
|---|---|---|---|---|
| `total_available_staff` | 550 | **86** | **171** | **299** |
| `total_available_ccp_ambulances` | 132 | **21** | **41** | **72** |
| `ccp_staff_upper_bound` | 104 | **17** | **33** | **57** |
| `ccp_ambulance_upper_bound` | 18 | **3** | **6** | **10** |
| `ccp_supply_upper_bound` | 2000 | **311** | **621** | **1086** |
| `ccp_physical_capacity` minor | 143 | **23** | **45** | **78** |
| `ccp_physical_capacity` moderate | 43 | **7** | **14** | **24** |
| `ccp_physical_capacity` severe | 14 | **3** | **5** | **8** |

### 4.2 per-醫院（× `s_H`）

| 參數 | 全量 | small (H=6) | medium (H=10) | large (H=14) |
|---|---|---|---|---|
| `hospital_supply_upper_bound` | 600 | **249** | **298** | **373** |
| `hospital_ambulance_fleet` | 18 | **8** | **9** | **12** |

`s_I` = 0.155 / 0.310 / 0.543；`s_H` = 0.413 / 0.496 / 0.620。

---

## 5. Random Variable 範圍是否隨規模改變（研究結論）

**核心結論：per-entity（每災區 / 每路段 / 每醫院）的隨機範圍不隨規模改變。**
總量的縮放是透過 entity「數量」（|I|、|H|）達成，不是靠改每單位的範圍。

| 隨機變數（`generate_scenarios`） | 範圍 | 是否隨規模改？ | 理由 |
|---|---|---|---|
| 需求 `DEMAND_UNIFORM` | U[1,5] / 災區·期 | **否** | 每災區的需求分布固定；總量靠 |I| 數量縮放 |
| 全域情境乘數 `SCENARIO_OMEGA` | [0.8,1.2] | **否** | 系統性 ±20%，與規模無關 |
| 空間乘數 `SCENARIO_SPATIAL_OMEGA` | [0.5,1.5] | **否** | 已正規化（加權平均=1），純重分配 |
| 路況 `road_ij/jh` 初值 | U[0,0.4] | **否** | 每路段物理屬性 |
| 路況恢復率 | U[0.05,0.08] | **否** | 同上 |
| 醫院容量 `hospital_capacity` | U[30,50] / 醫院·期 | **否** | 每醫院物理容量；總量靠 |H| 縮放 |
| **空間群集數** `SCENARIO_SPATIAL_CLUSTERS` | 3 | **是（結構性）** | K-means 需 k ≤ |I|，且 k ≪ |I| 才有意義 |

實作防呆：`n_clusters = min(profile["spatial_clusters"], n_disaster)`。
三個選定規模（20/40/70）皆遠大於 3，維持 clusters = 3 即可。

**附註（不需改參數，但要知道）**：災區數變少時，總需求的**相對變異
（CV）會變大**（獨立抽樣平均效應減弱）→ small case 情境間波動天生較大。
這是合理且有利的性質（小網路本就較「lumpy」），有助於凸顯 SP / MCVaR /
DRO 的穩健性差異，無須額外調整。

---

## 6. 空間群集與抽樣一致性

- **群集**：`SCENARIO_SPATIAL_CLUSTERS = 3` 對三規模皆適用（防呆見 §5）。
- **抽樣建議（nested）**：建議 small ⊂ medium ⊂ large ⊂ full，用固定
  seed 先抽最大集合再取前綴，讓不同規模是「同一張圖的放大/縮小」，
  跨規模比較更乾淨。若沿用現有「各規模獨立 seeded 抽樣」亦可，但
  需在 metadata 記錄以利複現。（此為設計選項，實作時二選一並記錄。）

---

## 7. 與 S / T 的關係（正交，不納入 profile）

`SCENARIOS (S)` 與 `TIME_PERIODS (T)` 是**隨機維度與時間維度**，非「路網
規模」，且對可解性影響巨大（見 `plan/13`：S* 由 pilot 決定）。因此：

- 預設 **不** 由 `EXPERIMENT_SCALE` 控制，維持獨立調參。
- 如需便利，可在各 profile 另加選填 `suggested_scenarios`，但預設 runner
  仍以自身 `BASE_SCENARIOS` 為準，避免覆寫既有實驗流程。

---

## 8. 實作步驟（需先確認本設計再執行）

> ⚠️ **權限提醒**：本機制要修改 `model core/config.py`（屬 `model core/`）。
> `plan/13` 等交接文件的「不可改 model core/」鐵律是針對該批次實驗；
> 本計畫是使用者主動授權的 config 重構，實作時**僅新增規模機制**，
> 不動求解引擎（`lshaped_core` / `extensive_form_core` / `risk_core`）。

1. **新增設定**（§2.1）：`EXPERIMENT_SCALE`、`N_*_FULL`、`SCALE_PROFILES`。
2. **新增 `resolve_scale()`**（§2.2）：回傳 counts + `demand_scale` + `hospital_scale`。
3. **改 `generate_data()` 簽章**：
   - 新增參數 `scale: str | None = None`，預設取 `EXPERIMENT_SCALE`。
   - 依 `resolve_scale` 得 `n_disaster / n_hospital / n_ccp`，改用**明確筆數**
     抽樣 I、H（取代單一 `SAMPLE_RATIO`）；CCP 固定取全部 10。
   - 保留 legacy `sample_ratio / ccp_sample_size` 分支以相容舊 runner
     （`scale=None` 且給 ratio 時走舊路徑）。
4. **改 `_build_deterministic_parameters()`**：
   - 新增 `demand_scale`、`hospital_scale` 參數。
   - 全域池與 per-CCP 上限 × `demand_scale`（新增 per-CCP 四項縮放）。
   - per-醫院上限 × `hospital_scale`（`hospital_supply_upper_bound`、
     `hospital_ambulance_fleet`）。
   - 成本 / 罰金 / 速率 / 機率**維持不縮**（§3.3）。
5. **群集防呆**：`n_clusters = min(spatial_clusters, n_disaster)`。
6. **metadata 補記**：`scale`、`demand_scale`、`hospital_scale`、
   抽樣模式（nested / independent）、實際 I/J/H 筆數。
7. **實驗 runner**：把各 batch 檔頂端的 `BASE_SAMPLE_RATIO / BASE_CCP_SAMPLE_SIZE`
   改為一行 `cfg.EXPERIMENT_SCALE = "..."`（或保留兩者、以 scale 優先）。

---

## 9. 驗證步驟（實作後必做）

1. **數值檢查**：對 small/medium/large 各跑 `generate_data`，印
   `instance["metadata"]["resource_scaling"]` 與 `sampled_counts`，比對 §1、§4 表。
2. **綁定一致性**：確認每規模「全域 staff 池 < Σ per-CCP staff 上限」
   （驗算：86<170、171<330、299<570，與全量 550<1040 同向）→ 全域池為
   綁定約束，跨規模結構一致。
3. **Feasibility pilot**：三規模各跑一次 SP（小 S、寬 gap、短 time limit）
   確認皆有可行解、無 `validate_instance` 警訊；特別檢查 small case 醫院端
   （`s_H` 最小）不因過緊而不可行。
4. **複現性**：固定 seed 重抽兩次，確認 I/H 抽樣集合一致。
5. **不縮項回歸**：確認成本 / 罰金 / 速率在三規模數值完全相同。

---

## 10. 一句話總結

新增 `EXPERIMENT_SCALE` 一個開關 → config 依 `SCALE_PROFILES` 調出
(I,J,H) 與縮放後參數；縮放驅動由「CCP 數」改為「災區數 |I|」，
per-醫院另用 per-醫院負載因子；隨機變數的 per-entity 範圍一律不動，
規模效果全由 entity 數量與資源上限承載。
