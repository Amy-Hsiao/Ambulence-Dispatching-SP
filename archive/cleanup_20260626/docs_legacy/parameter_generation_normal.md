# Normal / Scalable Parameter Generation

本文件是 `parameter_generation.md` 拆分後的 **normal generation** 版本，也就是原文件中的 **scalable case-calibrated tier**。此版本用於產生較接近真實案例的 two-stage stochastic programming extensive-form instances，例如 Bhopal、Van、Yushu 類案例。若沒有真實 GIS、人口、醫院與道路資料，本文件提供的是生成規則與可校準的 baseline，不宣稱是真實案例資料。

## 1. 適用範圍

Normal generation 用於：

- 產生 small、medium、large、stress-test instances。
- 測試 extensive-form SP model 在不同 `|I|, |J|, |H|, |T|, |S|` 下的可解規模。
- 做 sensitivity analysis 與 out-of-sample evaluation 的資料基礎。
- 未來銜接 real GIS、population、hospital capacity、road network data。

Normal generation 不用於：

- 取代真實案例校準。
- 宣稱某特定城市的實際災害結果。
- 直接支撐政策結論，除非已補齊真實資料與校準依據。

## 2. Literature-based source labels

本文使用以下來源標註：

- **Alizadeh et al. (2019)**：可參考 CCP candidate site、CCP capacity、minor/intermediate/immediate 傷患分類、Bhopal case、casualty scenarios、transportation capacity scenarios。
- **Farghadani-Chaharsooghi et al. (2025)**：可參考 stochastic casualty demand、hospital treatment capacity、equal scenario probability、uniform distribution、high/low priority penalty hierarchy。
- **Zhang et al. (2026)**：可參考 post-disaster road capacity ratio in `[0,1]`、link capacity multiplier、evacuee/road uncertainty、distance-based transportation cost。
- **Jin et al. (2024)**：可參考 equal scenario probability、random demand in discrete scenarios、distance-based delivery cost。
- **Shehadeh and Tucker (2022)**：可作為 relief supply、arc capacity、scenario-based SP/DRO uncertainty 背景補充。
- **自訂假設**：模型需要但上述文獻未直接給定，或文獻概念需轉換成本文 minor/moderate/severe、multi-period casualty arrival、time-dependent restoration 的設定。

## 3. 模型資料覆蓋範圍

本文件涵蓋 SP model 所需的：

- sets：`I, J, H, L, L_Amb, T, S`
- first-stage deterministic parameters：`f_j, cv, ca, cy_hj, nv, na, sbar_h, vbar_j, ubar_j, ybar_j`
- second-stage deterministic parameters：`c_ij, c_jh, kappa, eta, b_h, k_jl, tau_l, alpha_l, beta_l, rho_l, delta_l, t_ij, t_jh`
- random variable realizations：`xi_ilts, u_ijts, w_jhts, h_hts`
- scenario probability：`p_s`

注意：`X_j, V_j, U_j, Y_hj, FI, FO, RM, REG, TRT, WAT` 是 optimization decision variables，不應由 data generator 產生。

## 4. Sets

| Symbol | Normal generation rule | Source / note |
|---|---|---|
| `I` | 使用行政區、里、ward、neighborhood 或災害熱區 | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025) |
| `J` | 選學校、公園、體育場、大型空地、社區中心等可設 CCP 的地點 | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025) |
| `H` | 使用真實醫院或 medical care centers | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025) |
| `L` | `{minor, moderate, severe}` | 對應 minor/intermediate/immediate 或 low/high priority 類別 |
| `L_Amb` | `{moderate, severe}` | minor 不建立 hospital transfer variables |
| `T` | 可用 7 天、72 小時內的離散 periods，或依研究設計設定 | 自訂 period discretization |
| `S` | 10、50、100 或更多 scenarios；若用 SAA，可提高 sample size | Farghadani-Chaharsooghi et al. (2025), Zhang et al. (2026), Jin et al. (2024) |

Scenario probability default：

```text
p_s = 1 / |S|, for all s in S
```

若有歷史事件頻率、hazard model 或 scenario tree，可以改用非均等機率。

## 5. Recommended instance sizes

| Instance | `|I|` | `|J|` | `|H|` | `|L|` | `|T|` | `|S|` | Purpose |
|---|---:|---:|---:|---:|---:|---:|---|
| small | 3 | 2 | 1 | 3 | 4 | 5 | initial stochastic debugging |
| medium | 5 | 3 | 2 | 3 | 6 | 20 | baseline computational test |
| large | 10 | 5 | 3 | 3 | 8 | 50 | extensive-form scalability test |
| stress | 20 | 8 | 5 | 3 | 12 | 100 | identify computational bottleneck |

## 6. Spatial data and distance matrices

Normal generation should first create or load three node sets:

- `coord_i`：災區 `i` 的 latitude/longitude 或 projected coordinates。
- `coord_j`：candidate CCP `j` 的 coordinates。
- `coord_h`：hospital `h` 的 coordinates。

Preferred data source：

```text
road-network travel time/distance from GIS, OSM, or Distance Matrix API
```

Fallback rule：

```text
d_ab = sqrt((x_a - x_b)^2 + (y_a - y_b)^2)
d_ab = max(epsilon_distance, d_ab)
```

Transportation and supply costs may be distance-based:

```text
t_ij = cost_per_km_in * d_ij
t_jh = cost_per_km_out * d_jh
cy_hj = supply_unit_cost * d_hj
```

Recommended hierarchy:

```text
cost_per_km_out >= cost_per_km_in
```

## 7. First-stage deterministic parameters

| Parameter | Normal generation rule | Source / note |
|---|---|---|
| `f_j` | `f_j = base_open_cost + area_cost * area_j` or proportional to CCP capacity | Farghadani-Chaharsooghi et al. (2025), custom mapping |
| `cv` | staff daily wage, allowance, deployment cost, or normalized cost | custom assumption |
| `ca` | ambulance deployment, fuel, crew, standby cost, or normalized cost | custom assumption |
| `cy_hj` | `supply_unit_cost * d_hj` | Zhang et al. (2026), Jin et al. (2024) |
| `nv` | total available emergency medical staff | emergency response roster or scenario setting |
| `na` | total available CCP ambulances | EMS/fire department/temporary fleet |
| `sbar_h` | proportional to hospital nominal capacity or available emergency supply | Farghadani-Chaharsooghi et al. (2025), custom mapping |
| `vbar_j` | proportional to CCP area, facility level, or usable space | Alizadeh et al. (2019), custom mapping |
| `ubar_j` | proportional to CCP parking space and road accessibility | custom assumption |
| `ybar_j` | proportional to CCP storage area or physical capacity | Farghadani-Chaharsooghi et al. (2025), custom mapping |

Suggested scalable defaults when no real data are available:

```text
base_open_cost = 500
area_cost = 0.5
cv = 50
ca = 150
supply_unit_cost = 1
nv = round(0.8 * sum_j vbar_j)
na = round(0.6 * sum_j ubar_j)
sbar_h = round(0.3 * nominal_hospital_cap_h) for each h
```

These are normalized defaults and should be replaced after calibration.

## 8. Second-stage deterministic parameters

### 8.1 Road normal capacities and transportation costs

| Parameter | Normal generation rule | Source / note |
|---|---|---|
| `c_ij` | estimated from road class, number of lanes, historical traffic, or vehicle throughput | Zhang et al. (2026), Shehadeh and Tucker (2022), custom mapping |
| `c_jh` | same as `c_ij`, using CCP-to-hospital OD pair | Zhang et al. (2026), Shehadeh and Tucker (2022), custom mapping |
| `t_ij` | `cost_per_km_in * d_ij` or travel-time-based penalty | Zhang et al. (2026), Jin et al. (2024) |
| `t_jh` | `cost_per_km_out * d_jh` or travel-time-based penalty | Zhang et al. (2026), Jin et al. (2024) |

Fallback if road capacity data are unavailable:

```text
c_ij = ceil(base_cap_in / (1 + distance_penalty * d_ij))
c_jh = ceil(base_cap_out / (1 + distance_penalty * d_jh))
```

Example normalized defaults:

```text
base_cap_in = 200
base_cap_out = 200
distance_penalty = 0.05
lower_bound_capacity = 10
```

### 8.2 Ambulance capacities and hospital ambulance fleet

| Parameter | Normal generation rule | Source / note |
|---|---|---|
| `kappa` | estimated from period length, average round-trip time, and vehicle capacity | custom assumption |
| `eta` | same logic for hospital ambulance transfer | custom assumption |
| `b_h` | hospital EMS fleet or public hospital resource data | Farghadani-Chaharsooghi et al. (2025) has hospital vehicle/resource concept; numeric value must be calibrated |

A practical approximation:

```text
kappa = floor(period_length / avg_round_trip_time_area_to_ccp)
eta = floor(period_length / avg_round_trip_time_ccp_to_hospital)
```

If one ambulance can carry more than one casualty per trip, multiply by vehicle loading capacity.

### 8.3 CCP physical capacity `k_jl`

If CCP area is available:

```text
total_ccp_capacity_j = floor(available_area_j / 7)
k_j,minor    = floor(0.50 * total_ccp_capacity_j)
k_j,moderate = floor(0.30 * total_ccp_capacity_j)
k_j,severe   = total_ccp_capacity_j - k_j,minor - k_j,moderate
```

The `7 m²/person` rule follows the CCP capacity logic cited in Alizadeh et al. (2019). The severity allocation ratio is a custom assumption and should be replaced if triage data are available.

### 8.4 Treatment time, staff productivity, and supplies

| Parameter | Normal generation rule | Source / note |
|---|---|---|
| `tau_l` | discretized treatment duration by severity | Farghadani-Chaharsooghi et al. (2025) treatment duration concept; custom mapping |
| `alpha_l` | `period_length / treatment_time_l`, rounded or calibrated | custom assumption |
| `beta_l` | medical kits or resource units consumed per casualty by severity | Farghadani-Chaharsooghi et al. (2025), WHO kit concept through literature mapping |

Recommended hierarchy:

```text
tau_minor <= tau_moderate <= tau_severe
alpha_minor >= alpha_moderate >= alpha_severe
beta_minor <= beta_moderate <= beta_severe
```

Suggested normalized defaults:

```text
tau = {minor: 1, moderate: 2, severe: 3}
alpha = {minor: 8, moderate: 4, severe: 2}
beta = {minor: 1, moderate: 3, severe: 6}
```

### 8.5 Penalty costs

| Parameter | Normal generation rule | Source / note |
|---|---|---|
| `rho_l` | severity-based penalty for remaining in disaster area | Farghadani-Chaharsooghi et al. (2025), custom severity mapping |
| `delta_l` | penalty for treated `L_Amb` casualty waiting for hospital transfer | Farghadani-Chaharsooghi et al. (2025), custom severity mapping |

Recommended hierarchy:

```text
rho_minor < rho_moderate < rho_severe
delta_moderate < delta_severe
delta_l <= rho_l
```

Suggested normalized defaults:

```text
rho = {minor: 100, moderate: 400, severe: 1000}
delta = {moderate: 200, severe: 700}
```

If the research assumption is that severe post-treatment hospital delay is extremely dangerous, `delta_severe` can be set close to or above `rho_severe`, but this must be justified and tested.

## 9. Random variable generation

All random variables must be generated first as scenario realizations and then passed to the extensive form:

```text
omega_s = {
  xi_ilts,
  u_ijts,
  w_jhts,
  h_hts
}
```

### 9.1 Casualty arrival `xi_ilts`

Baseline scalable generation:

```text
base_demand_i_s ~ DiscreteUniform(50, 200)
severity_count_i_l_s = round_by_ratio(base_demand_i_s, severity_ratio_l)
xi_i_l_t_s = round_by_time_profile(severity_count_i_l_s, time_weight_t)
```

Default severity ratio:

```text
severity_ratio = {minor: 0.55, moderate: 0.30, severe: 0.15}
```

If real exposure data are available:

```text
base_demand_i_s = round(population_i * damage_rate_i_s * casualty_rate_i_s)
```

Where `damage_rate_i_s` can be estimated from earthquake intensity, distance to fault line, flood depth, building damage state, or other exposure indicators.

Multi-period arrival profile:

```text
time_weight_t = exp(-lambda_arrival * (t - 1)) / sum_r exp(-lambda_arrival * (r - 1))
```

Recommended default:

```text
lambda_arrival = 0.8
```

Use largest remainder method to preserve totals:

```text
sum_t xi_i_l_t_s = severity_count_i_l_s
sum_l sum_t xi_i_l_t_s = base_demand_i_s
```

### 9.2 Disaster-area-to-CCP road availability `u_ijts`

`u_ijts` is a capacity multiplier in `[0,1]`:

```text
effective_capacity_ijts = c_ij * u_ijts
```

Mode A: severe road disruption / mountainous area

```text
u_ij1s ~ Uniform(0.3, 0.5)
repair_rate_ijs ~ Uniform(0.03, 0.15)
u_ijts = min(1.0, u_ij1s + repair_rate_ijs * (t - 1))
```

Mode B: transportation capacity scenario set

```text
capacity_set_high = {0.85, 0.90, 0.95}
capacity_set_low  = {0.70, 0.75, 0.80}
u_ijts = sampled_capacity_level_s
```

To preserve time-dependent restoration:

```text
u_ijts = min(1.0, sampled_capacity_level_s + repair_rate_ijs * (t - 1))
```

### 9.3 CCP-to-hospital road availability `w_jhts`

`w_jhts` is also a capacity multiplier in `[0,1]`:

```text
effective_capacity_jhts = c_jh * w_jhts
```

If hospital routes are also severely damaged:

```text
w_jh1s ~ Uniform(0.3, 0.5)
repair_rate_jhs ~ Uniform(0.03, 0.15)
w_jhts = min(1.0, w_jh1s + repair_rate_jhs * (t - 1))
```

If hospital routes are relatively more accessible:

```text
w_jh1s ~ Uniform(0.5, 0.8)
repair_rate_jhs ~ Uniform(0.03, 0.15)
w_jhts = min(1.0, w_jh1s + repair_rate_jhs * (t - 1))
```

### 9.4 Hospital receiving capacity `h_hts`

Baseline scalable generation:

```text
nominal_hospital_cap_h ~ Uniform(1000, 2000)
damage_factor_hs ~ Uniform(0.5, 1.0)
restoration_rate_hs ~ Uniform(0.02, 0.15)
h_hts = floor(nominal_hospital_cap_h * min(1.0, damage_factor_hs + restoration_rate_hs * (t - 1)))
```

Important scaling note:

```text
if nominal_hospital_cap_h is daily capacity and each period is 6 hours,
then per-period capacity = nominal_hospital_cap_h / 4
```

## 10. Scenario generation pipeline

Recommended pipeline:

1. Fix random seed.
2. Build sets: `I, J, H, L, L_Amb, T, S`.
3. Load or generate node coordinates.
4. Compute `d_ij, d_jh, d_hj`.
5. Generate first-stage deterministic parameters.
6. Generate second-stage deterministic parameters.
7. For each scenario `s`, generate a disaster severity factor.
8. Generate `xi_ilts`; validate nonnegative integer values.
9. Generate `u_ijts` and `w_jhts`; clip to `[0,1]`.
10. Generate `h_hts`; validate nonnegative integer values.
11. Set scenario probabilities `p_s`.
12. Export parameter dictionary, CSV, JSON, or YAML.
13. Save seed, generator configuration, and source assumptions.

## 11. Required validation checks

Before building the optimization model:

```text
sum_s p_s = 1
xi_ilts >= 0 and integer
0 <= u_ijts <= 1
0 <= w_jhts <= 1
h_hts >= 0 and integer
c_ij, c_jh >= 0
k_jl, alpha_l, beta_l, tau_l > 0
rho_l, delta_l >= 0
L_Amb subset of L
minor not in L_Amb
```

After solve:

```text
RM balance
REG = sum_i FI
TRT rolling-sum definition
WAT balance for L_Amb only
road capacity constraints
CCP ambulance capacity constraints
hospital ambulance capacity constraints
hospital receiving capacity constraints
staff workload constraint
supply consumption constraint
objective decomposition
```

## 12. Parameter source summary

| Category | Main rule | Source |
|---|---|---|
| Scenario probability | `p_s = 1/|S|` | Farghadani-Chaharsooghi et al. (2025), Jin et al. (2024) |
| Casualty demand | `U[50,200]` or population × damage/casualty rate | Alizadeh et al. (2019), Farghadani-Chaharsooghi et al. (2025), custom time profile |
| Road availability | `[0,1]` capacity multiplier; `U(0.3,0.5)` or transportation scenario sets | Zhang et al. (2026), Alizadeh et al. (2019), custom restoration |
| Hospital receiving capacity | `U[1000,2000]` adjusted by damage/restoration and period length | Farghadani-Chaharsooghi et al. (2025), custom restoration |
| CCP capacity | `floor(area_j / 7)`, then severity allocation | Alizadeh et al. (2019), custom severity allocation |
| Transportation/supply costs | unit cost × distance | Zhang et al. (2026), Jin et al. (2024) |
| Penalty hierarchy | higher severity gets higher penalty | Farghadani-Chaharsooghi et al. (2025), custom minor/moderate/severe mapping |
| Treatment/resource consumption | higher severity requires longer treatment and more resources | Farghadani-Chaharsooghi et al. (2025), custom mapping |

## 13. Known limitations

- This file provides parameter-generation rules, not final calibrated real-world data.
- Multi-period casualty arrival, road restoration, and hospital restoration formulas are custom assumptions designed to fit the model structure.
- For real case studies, GIS distance, population, hospital capacity, road class, CCP area, and disaster intensity data should be added.
- Uniform distributions are acceptable for preliminary experiments but should be replaced or justified when better empirical data are available.
- Normal generation should always be reported as synthetic or case-calibrated synthetic unless real data are used.
