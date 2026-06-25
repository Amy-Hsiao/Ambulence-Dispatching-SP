# SP model deterministic parameters 與 random variables 生成方式

本文說明 `SP model.pdf` 中兩階段 stochastic programming extensive form 所需資料的建議產生方式。文件分成兩層資料設定：

- **Tiny synthetic tier**：用於 tiny deterministic/unit tests，重點是可重現、數值小、容易檢查 mass balance 與 capacity constraints。
- **Scalable case-calibrated tier**：用於後續擴充到較接近真實案例的實驗，例如 Bhopal、Van、Yushu 類案例。若沒有真實 GIS、人口、醫院與道路資料，本文只提供生成規則，不宣稱是真實案例資料。

除非特別註明，所有隨機資料都應由固定 random seed 產生，並輸出 scenario table，使 extensive form 可完全重現。

## 1. 文獻依據與標註規則

本文使用以下來源標註：

- **Alizadeh et al. (2019)**：`A robust stochastic Casualty Collection Points location problem`。可參考 CCP candidate site、CCP capacity、minor/intermediate/immediate 傷患分類、Bhopal case、casualty scenarios、transportation capacity scenarios。
- **Farghadani-Chaharsooghi et al. (2025)**：`Stochastic casualty response planning with multiple classes of patients`。可參考 stochastic casualty demand、hospital treatment capacity、equal scenario probability、uniform distribution、high/low priority penalty hierarchy。
- **Zhang et al. (2026)**：`Humanitarian relief logistics network design considering facility location, inventory pre-positioning and evacuation planning`。可參考 post-disaster road capacity ratio in `[0,1]`、link capacity multiplier、evacuee/road uncertainty、distance-based transportation cost。
- **Jin et al. (2024)**：`A risk-averse distributionally robust optimisation approach for drone-supported relief facility location problem`。可參考 equal scenario probability、random demand in discrete scenarios、distance-based delivery cost。
- **Shehadeh and Tucker (2022)**：`Stochastic optimization models for location and inventory prepositioning of disaster relief supplies`。可作為 relief supply、arc capacity、scenario-based SP/DRO uncertainty 背景補充。
- **自訂假設**：模型需要但上述文獻未直接給定，或文獻概念需轉換成本文 minor/moderate/severe、multi-period casualty arrival、time-dependent restoration 的設定。

## 2. 集合設定

| 符號 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|
| `I` disaster areas | 2 個災區，例如 `I={i1,i2}` | 使用行政區、里/ward/neighborhood 或災害熱區；Bhopal case 可用 affected wards，Van case 可用 demand neighborhoods | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025) |
| `J` candidate CCP locations | 2 個候選 CCP，例如 `J={j1,j2}` | 選學校、公園、體育場、大型空地、社區中心等可設 CCP 的地點 | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025) |
| `H` hospitals | 1 或 2 間醫院，例如 `H={h1}` | 使用真實醫院或 medical care centers | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025) |
| `L` casualty severity levels | 固定為 `{minor, moderate, severe}` | 同 tiny，對應 minor/intermediate/immediate 或 low/high priority 類別 | Alizadeh et al. (2019), 自訂映射 |
| `L_Amb` ambulance-required severities | 固定為 `{moderate, severe}` | 同 tiny；minor 在 CCP 完成處置，不建立 hospital transfer variables | Alizadeh et al. (2019), SP model |
| `T` time periods | 3 期，例如 `T={1,2,3}` | 依研究設計可用 7 天或 72 小時內的離散 periods | Alizadeh et al. (2019), Zhang et al. (2026), 自訂 |
| `S` scenarios | 2 到 5 個 scenarios | 10、50、100 或更多 scenarios；若用 SAA，可提高 sample size | Farghadani-Chaharsooghi et al. (2025), Zhang et al. (2026), Jin et al. (2024) |

Scenario probability 建議設定為：

```text
p_s = 1 / |S|, for all s in S
```

這是 tiny 與 scalable tier 的預設。Farghadani-Chaharsooghi et al. (2025) 與 Jin et al. (2024) 都使用 equal scenario probability 的設定。若未來有歷史事件頻率或災害 hazard model，可以改用非均等機率。

## 3. 空間資料與距離矩陣

所有與距離有關的參數建議先建立三類座標：

- `coord_i`：災區 `i` 的座標。
- `coord_j`：候選 CCP `j` 的座標。
- `coord_h`：醫院 `h` 的座標。

Tiny synthetic tier 可在小型平面上手動設定座標，例如：

| 節點 | 座標 |
|---|---|
| `i1` | `(0, 0)` |
| `i2` | `(4, 0)` |
| `j1` | `(1, 1)` |
| `j2` | `(3, 1)` |
| `h1` | `(2, 4)` |

Scalable case-calibrated tier 可使用真實 latitude/longitude，透過 GIS road network 或 Distance Matrix API 取得 travel distance/time。Zhang et al. (2026) 使用 Google Distance Matrix API 取得 node distance；Jin et al. (2024) 則在小例子中使用 Euclidean distance 並令 delivery cost 與距離成比例。

若沒有真實 road distance，先用 Euclidean distance：

```text
d_ab = sqrt((x_a - x_b)^2 + (y_a - y_b)^2)
```

若要避免 0 距離導致成本為 0，可設：

```text
d_ab = max(epsilon_distance, EuclideanDistance(a,b))
```

此 epsilon rule 是自訂假設，主要用於 tiny tests。

## 4. 第一階 deterministic parameters

| 符號 | 意義 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|---|
| `f_j` | 開啟 CCP `j` 固定成本 | 依容量給小整數，例如 `f_j = 100 + 5 * total_capacity_j` | 與 CCP 面積、容量或 facility size 成比例；可用 `f_j = base_open_cost + area_cost * area_j` | Farghadani-Chaharsooghi et al. (2025), 自訂映射 |
| `cv` | 每位醫療人員配置成本 | 固定小值，例如 `cv=10` | 用人員每日薪資、津貼、調度成本或 normalized cost | 自訂假設 |
| `ca` | 每台 CCP ambulance 配置成本 | 固定小值，例如 `ca=30` | 用 ambulance deployment cost、fuel、crew、standby cost | 自訂假設 |
| `cy_hj` | 醫院 `h` 到 CCP `j` 的每單位物資調度成本 | `cy_hj = supply_unit_cost * d_hj`，例如 `supply_unit_cost=1` | distance-based cost；可用每公里運輸成本乘上 road distance | Zhang et al. (2026), Jin et al. (2024) |
| `nv` | 可用醫療人員總數 | 小整數，例如 4 到 8 | 由 emergency response staff roster 或醫療隊規模設定 | 自訂假設 |
| `na` | 可用 CCP ambulance 總數 | 小整數，例如 1 到 3 | 由 EMS/消防/醫院支援車隊規模設定 | 自訂假設 |
| `sbar_h` | 醫院 `h` 可提供最大醫療物資量 | 小整數，例如 20 到 60 | 可令 `sbar_h` 與 hospital nominal capacity 成比例 | Farghadani-Chaharsooghi et al. (2025), Sun et al. via Farghadani-Chaharsooghi et al. (2025), 自訂映射 |
| `vbar_j` | CCP `j` 可配置最大醫療人員數 | 2 到 5 | 與 CCP 面積、可用空間、facility level 成比例 | Alizadeh et al. (2019), 自訂映射 |
| `ubar_j` | CCP `j` 可配置最大 ambulance 數 | 1 到 3 | 與 CCP 停車空間、道路可達性或 facility level 成比例 | 自訂假設 |
| `ybar_j` | CCP `j` 可接收最大醫療物資量 | 10 到 50 | 與 CCP storage area 或 capacity 成比例 | Farghadani-Chaharsooghi et al. (2025), 自訂映射 |

建議 tiny tier 先讓 total resources 足以處理部分但不是全部最壞需求，避免模型因完全不足而只靠 penalty，又避免所有限制都不 binding。

## 5. 第二階 deterministic parameters

### 5.1 Road normal capacities 與 transportation cost

| 符號 | 意義 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|---|
| `c_ij` | 災區 `i` 到 CCP `j` 正常每期最大運輸容量 | 依距離反比設定，例如 `ceil(base_cap / (1 + d_ij))`，下限 2 | 可用道路等級、車道數、歷史通行量或救護/車輛 throughput 估計 | Zhang et al. (2026), Shehadeh and Tucker (2022), 自訂映射 |
| `c_jh` | CCP `j` 到醫院 `h` 正常每期最大運輸容量 | 同 `c_ij`，通常可略高或略低 | 同上，依 road segment 或 OD pair 容量設定 | Zhang et al. (2026), Shehadeh and Tucker (2022), 自訂映射 |
| `t_ij` | 災區 `i` 到 CCP `j` 每名傷患運輸成本/時間懲罰 | `t_ij = cost_per_km_in * d_ij` | distance-based 或 travel-time-based cost | Zhang et al. (2026), Jin et al. (2024) |
| `t_jh` | CCP `j` 到醫院 `h` 每名傷患轉送成本/時間懲罰 | `t_jh = cost_per_km_out * d_jh` | distance-based 或 travel-time-based cost | Zhang et al. (2026), Jin et al. (2024) |

若希望 ambulance transfer 比一般送到 CCP 更昂貴，可設定：

```text
cost_per_km_out >= cost_per_km_in
```

這是自訂假設，用於反映中重症轉院更耗資源。

### 5.2 Ambulance capacities 與 hospital ambulance fleet

| 符號 | 意義 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|---|
| `kappa` | 每台 CCP ambulance 每期可運送需 ambulance 傷患數 | 2 到 4 | 依每期長度、平均 round-trip time、每車可載人數估計 | 自訂假設 |
| `eta` | 每台 hospital ambulance 每期可轉送傷患數 | 2 到 4 | 同上；若醫院車隊效率較高可設更高 | 自訂假設 |
| `b_h` | 醫院 `h` 自有 ambulance 數 | 1 到 3 | 由醫院 EMS fleet 或公開資料設定 | Farghadani-Chaharsooghi et al. (2025) 有 hospital vehicle/resource 設定概念；數值自訂 |

### 5.3 CCP physical capacity

| 符號 | 意義 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|---|
| `k_jl` | CCP `j` 對 severity `l` 的 physical capacity | 小整數，例如 `minor:8, moderate:5, severe:3` | 先估總容量 `floor(area_j / 7)`，再依 severity allocation ratio 分配 | Alizadeh et al. (2019), 自訂 severity allocation |

Alizadeh et al. (2019) 以 CCP 可用總面積除以每人治療所需空間估算 CCP capacity，文中採 `7 m²/person`。套用到本文可寫成：

```text
total_ccp_capacity_j = floor(available_area_j / 7)
k_j,minor    = floor(0.50 * total_ccp_capacity_j)
k_j,moderate = floor(0.30 * total_ccp_capacity_j)
k_j,severe   = total_ccp_capacity_j - k_j,minor - k_j,moderate
```

上述 severity allocation ratio 是自訂假設；若有 triage/傷型資料，應改用實際比例。

### 5.4 Treatment time, staff productivity, supplies

| 符號 | 意義 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|---|
| `tau_l` | severity `l` 在 CCP 需治療期數 | `minor=1, moderate=2, severe=2 or 3` | 依 triage/treatment protocol 或平均處置時間離散化 | Farghadani-Chaharsooghi et al. (2025) treatment duration 概念；映射自訂 |
| `alpha_l` | 每位醫療人員每期可處理 severity `l` 傷患數 | `minor=4, moderate=2, severe=1` | 依醫護生產率與治療時間估計，例如 `period_length / treatment_time_l` | 自訂假設 |
| `beta_l` | 每名 severity `l` 傷患消耗醫療物資量 | `minor=1, moderate=2, severe=3` | 依 medical kit、drug kit、surgical kit 消耗量設定 | Farghadani-Chaharsooghi et al. (2025), WHO kit 概念經文獻引用；映射自訂 |

這三組參數必須維持 severity hierarchy：

```text
tau_minor <= tau_moderate <= tau_severe
alpha_minor >= alpha_moderate >= alpha_severe
beta_minor <= beta_moderate <= beta_severe
```

### 5.5 Penalty costs

| 符號 | 意義 | Tiny synthetic tier | Scalable case-calibrated tier | 來源 |
|---|---|---|---|---|
| `rho_l` | 傷患留在災區一期間的 penalty | `minor=20, moderate=80, severe=200` | 依 severity risk 設高低；中重症 penalty 明顯較高 | Farghadani-Chaharsooghi et al. (2025), 自訂映射 |
| `delta_l` | 已治療但仍等待轉院的 penalty，僅 `l in L_Amb` | `moderate=30, severe=100` | 低於或接近 `rho_l`，但 severe waiting penalty 應高於 moderate | Farghadani-Chaharsooghi et al. (2025), 自訂映射 |

Farghadani-Chaharsooghi et al. (2025) 使用 high-priority penalty 大於 low-priority penalty，且曾設定 high penalty 為 low penalty 的 2 倍。本文模型有三種 severity，建議使用：

```text
rho_minor < rho_moderate < rho_severe
delta_moderate < delta_severe
delta_l <= rho_l
```

`delta_l <= rho_l` 是自訂假設，表示已完成 CCP 治療但等待轉院通常比仍留在災區的風險低；若研究假設 hospital delay 對 severe 特別致命，也可令 `delta_severe` 接近或高於 `rho_severe`，但需在實驗中說明。

## 6. Random variables 生成方式

所有 random variables 都要先生成 scenario realizations，再帶入 extensive form：

```text
omega_s = {
  xi_ilts,
  u_ijts,
  w_jhts,
  h_hts
}
```

### 6.1 新增傷患數 `xi_ilts`

`xi_ilts` 是災區 `i`、severity `l`、period `t`、scenario `s` 下新生成傷患數。

Tiny synthetic tier：

1. 對每個 `i,s` 產生 total casualties：

```text
total_i_s ~ DiscreteUniform(low_i, high_i)
```

建議 tiny 值：

```text
low_i = 4, high_i = 12
```

2. 依 severity ratio 分配：

```text
r_minor = 0.55
r_moderate = 0.30
r_severe = 0.15
```

3. 依 time profile 分配到各期：

```text
T = {1,2,3}
time_weight = {0.60, 0.30, 0.10}
```

4. 取整數時使用 largest remainder method，確保：

```text
sum_l sum_t xi_ilts = total_i_s
```

Scalable case-calibrated tier：

- Alizadeh et al. (2019) 在 Bhopal case 中依 ward population 與 Singh and Ghosh (1987) casualty simulation procedure 生成 casualty scenarios，並設定 3 個 injury severity levels 與 7 天 planning period。
- Farghadani-Chaharsooghi et al. (2025) 在一般 CRP instances 中用 `U[50,200]` 產生 demand location 的 patient demand，並說明在缺乏精準分布資訊時 uniform distribution 是合理的 maximum-entropy choice。

建議 scalable 公式：

```text
base_demand_i_s ~ DiscreteUniform(50, 200)
severity_count_i_l_s = round_by_ratio(base_demand_i_s, severity_ratio_l)
xi_i_l_t_s = round_by_time_profile(severity_count_i_l_s, time_weight_t)
```

若有真實人口與災害強度資料，可改成：

```text
base_demand_i_s = round(population_i * damage_rate_i_s * casualty_rate_i_s)
```

其中 `damage_rate_i_s` 可由地震烈度、距離 fault line、淹水深度或災害暴露程度估計。這種人口乘災損比例的概念與 Farghadani-Chaharsooghi et al. (2025) Van case 中依 population、damage intensity、damage state 與總傷患數決定 base demand 的描述一致。

多期 time profile 是自訂假設，因目前資料夾內文獻沒有直接給本文 `xi_ilts` 的逐期 arrival 公式。建議預設早期高、後期遞減：

```text
time_weight_t = exp(-lambda_arrival * (t-1)) / sum_r exp(-lambda_arrival * (r-1))
```

Tiny 可用 `lambda_arrival = 0.8`；scalable 可做 sensitivity analysis。

### 6.2 災區到 CCP road availability `u_ijts`

`u_ijts` 是災區 `i` 到 CCP `j` 在 period `t`、scenario `s` 的可用容量比例，範圍 `[0,1]`。實際容量為：

```text
effective_capacity_ijts = c_ij * u_ijts
```

Tiny synthetic tier：

```text
u_ij1s ~ Uniform(0.5, 0.9)
repair_rate_ijs ~ Uniform(0.0, 0.2)
u_ijts = min(1.0, u_ij1s + repair_rate_ijs * (t - 1))
```

Scalable case-calibrated tier：

- Zhang et al. (2026) 將 road capacity uncertainty 表示為 `[0,1]` 的 link capacity multiplier，並在 Yushu case 中用 `U(0.3,0.5)` 產生 post-disaster link capacity。
- Alizadeh et al. (2019) 使用 available transportation capacity scenarios，high set 為 `{85%,90%,95%}`，low set 為 `{70%,75%,80%}`。

建議兩種生成模式：

**模式 A：嚴重災損/山區道路**

```text
u_ij1s ~ Uniform(0.3, 0.5)
repair_rate_ijs ~ Uniform(0.03, 0.15)
u_ijts = min(1.0, u_ij1s + repair_rate_ijs * (t - 1))
```

**模式 B：交通容量情境集**

```text
capacity_set_high = {0.85, 0.90, 0.95}
capacity_set_low  = {0.70, 0.75, 0.80}
u_ijts = sampled_capacity_level_s
```

若要符合本文 time-dependent assumption，可在模式 B 上加修復：

```text
u_ijts = min(1.0, sampled_capacity_level_s + repair_rate_ijs * (t - 1))
```

多期修復公式是自訂假設，用於符合 `SP model.pdf` 中 scenario-dependent and time-dependent road availability。

### 6.3 CCP 到醫院 road availability `w_jhts`

`w_jhts` 是 CCP `j` 到醫院 `h` 在 period `t`、scenario `s` 的可用容量比例，範圍 `[0,1]`。實際容量為：

```text
effective_capacity_jhts = c_jh * w_jhts
```

生成方式與 `u_ijts` 相同，但可視情況讓主幹道路恢復較快：

Tiny synthetic tier：

```text
w_jh1s ~ Uniform(0.6, 1.0)
repair_rate_jhs ~ Uniform(0.0, 0.2)
w_jhts = min(1.0, w_jh1s + repair_rate_jhs * (t - 1))
```

Scalable case-calibrated tier：

```text
w_jh1s ~ Uniform(0.3, 0.5)       # 若假設醫院周邊道路也嚴重受損
w_jh1s ~ Uniform(0.5, 0.8)       # 若假設醫院主幹道較可通行
w_jhts = min(1.0, w_jh1s + repair_rate_jhs * (t - 1))
```

`w_jhts` 的 `[0,1]` link capacity multiplier 來自 Zhang et al. (2026)；若採 high/low transportation capacity scenario，可引用 Alizadeh et al. (2019)。醫院路段是否恢復較快是自訂假設。

### 6.4 醫院接收能力 `h_hts`

`h_hts` 是醫院 `h` 在 period `t`、scenario `s` 最大可接收傷患數。

Tiny synthetic tier：

```text
nominal_hospital_cap_h = small integer, e.g. 4 to 10 per period
damage_factor_hs ~ Uniform(0.5, 1.0)
restoration_rate_hs ~ Uniform(0.0, 0.2)
h_hts = floor(nominal_hospital_cap_h * min(1.0, damage_factor_hs + restoration_rate_hs * (t - 1)))
```

Scalable case-calibrated tier：

Farghadani-Chaharsooghi et al. (2025) 將 hospital treatment capacity 視為 scenario-dependent uncertain parameter，並在 instance generation 中設定：

```text
hospital_capacity_hs ~ Uniform(1000, 2000)
```

對本文 multi-period 模型，可改成：

```text
nominal_hospital_cap_h ~ Uniform(1000, 2000)
damage_factor_hs ~ Uniform(0.5, 1.0)
restoration_rate_hs ~ Uniform(0.02, 0.15)
h_hts = floor(nominal_hospital_cap_h * min(1.0, damage_factor_hs + restoration_rate_hs * (t - 1)))
```

`Uniform(1000,2000)` 來自 Farghadani-Chaharsooghi et al. (2025)。damage/restoration factor 是自訂假設，用來符合本文 time-dependent hospital receiving capacity assumption。若模型 period 很短，應將 annual/daily capacity 縮放成每 period capacity。

## 7. 建議 tiny deterministic baseline

第一個 unit test 建議完全 deterministic，只設一個 scenario：

```text
I = {i1}
J = {j1}
H = {h1}
L = {minor, moderate, severe}
L_Amb = {moderate, severe}
T = {1, 2}
S = {s1}
p_s1 = 1
```

建議資料：

| 參數 | 值 |
|---|---|
| `xi_i1,minor,1,s1` | 2 |
| `xi_i1,moderate,1,s1` | 1 |
| `xi_i1,severe,1,s1` | 1 |
| `xi_i1,l,2,s1` | 0 for all `l` |
| `u_i1,j1,t,s1` | 1 for all `t` |
| `w_j1,h1,t,s1` | 1 for all `t` |
| `h_h1,t,s1` | 3 for all `t` |
| `c_i1,j1` | 10 |
| `c_j1,h1` | 10 |
| `kappa` | 2 |
| `eta` | 2 |
| `b_h1` | 1 |
| `k_j1,minor` | 4 |
| `k_j1,moderate` | 3 |
| `k_j1,severe` | 2 |
| `tau_minor, tau_moderate, tau_severe` | `1, 1, 1` |
| `alpha_minor, alpha_moderate, alpha_severe` | `4, 2, 1` |
| `beta_minor, beta_moderate, beta_severe` | `1, 2, 3` |
| `rho_minor, rho_moderate, rho_severe` | `20, 80, 200` |
| `delta_moderate, delta_severe` | `30, 100` |

此 baseline 的目的不是模擬真實災害，而是讓模型容易驗證：

- Minor casualties 不需要 hospital transfer variables。
- `t-1` 與 `t-tau_l` 邊界條件可人工追蹤。
- `TRT`、`WAT`、`RM` 的 mass balance 可手算。

## 8. 建議 scalable scenario generation pipeline

後續實作 data generator 時，建議依下列順序生成資料：

1. 固定 random seed。
2. 建立 sets：`I,J,H,L,L_Amb,T,S`。
3. 讀取或生成節點座標，計算 `d_ij,d_jh,d_hj`。
4. 生成 first-stage deterministic parameters：opening/resource/supply capacities and costs。
5. 生成 second-stage deterministic parameters：normal road capacities、treatment productivity、CCP capacities、penalties。
6. 對每個 scenario `s` 生成 disaster severity factor。
7. 生成 `xi_ilts`，並檢查所有值為非負整數。
8. 生成 `u_ijts,w_jhts`，並 clip 到 `[0,1]`。
9. 生成 `h_hts`，並轉成非負整數。
10. 設定 `p_s=1/|S|`。
11. 輸出 parameter dictionary 或 CSV/JSON，並保存 seed 與來源設定。

必要 validation checks：

```text
sum_s p_s = 1
xi_ilts >= 0 and integer
0 <= u_ijts <= 1
0 <= w_jhts <= 1
h_hts >= 0 and integer
c_ij, c_jh >= 0
k_jl, alpha_l, beta_l, tau_l > 0
rho_l, delta_l >= 0
```

## 9. 參數來源摘要表

| 類別 | 主要規則 | 來源 |
|---|---|---|
| Scenario probability | `p_s = 1/|S|` | Farghadani-Chaharsooghi et al. (2025), Jin et al. (2024) |
| Casualty demand | Tiny 用 small uniform；scalable 用 `U[50,200]` 或人口 × 災損比例 | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025), 自訂 time profile |
| Road availability | `[0,1]` capacity multiplier；可用 `U(0.3,0.5)` 或 capacity scenario sets | Zhang et al. (2026), Alizadeh et al. (2019), 自訂 restoration |
| Hospital receiving capacity | `U[1000,2000]` 再依 period 縮放/修復 | Farghadani-Chaharsooghi et al. (2025), 自訂 restoration |
| CCP capacity | `floor(area_j / 7)`，再分配到 severity | Alizadeh et al. (2019), 自訂 severity allocation |
| Transportation/supply costs | unit cost × distance | Zhang et al. (2026), Jin et al. (2024) |
| Penalty hierarchy | high severity/high priority penalty 較高 | Farghadani-Chaharsooghi et al. (2025), 自訂 minor/moderate/severe 映射 |
| Treatment/resource consumption | severity 越高，治療時間與物資消耗越高，人力 productivity 越低 | Farghadani-Chaharsooghi et al. (2025), 自訂映射 |

## 10. Known limitations

- 本文件提供資料生成設計，尚未實作 Python generator。
- 多期 casualty arrival profile、road restoration、hospital restoration 是自訂假設；文獻支持其方向，但未提供完全相同的 `xi_ilts/u_ijts/w_jhts/h_hts` 公式。
- 若使用真實案例，仍需補齊 GIS distance、人口、醫院 capacity、道路等級、CCP 面積與災害強度資料。
- Tiny synthetic tier 的數值只適合測試模型邏輯，不應用來解釋實務政策。
