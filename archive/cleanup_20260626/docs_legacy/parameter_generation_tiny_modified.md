# Tiny Case Parameter Generation

本文件是 `parameter_generation.md` 拆分後的 **tiny synthetic tier** 版本，目的不是模擬真實災害，而是建立可手算、可重現、適合 unit tests 與 debugging 的小型資料。此資料層級應優先用來檢查 extensive-form two-stage SP model 的 indexing、mass balance、capacity constraints、treatment-time boundary conditions，以及 minor/moderate/severe 與 `L_Amb` 的邏輯。

## 1. 適用範圍

Tiny case 用於：

- 測試 Gurobi model 是否能正確建模與求解。
- 測試 `RM`、`REG`、`TRT`、`WAT` 等狀態變數是否符合 flow balance。
- 測試 `t-1`、`t - tau_l`、`L_Amb` 的邊界條件。
- 建立 deterministic baseline，讓結果可以人工檢查。

Tiny case 不用於：

- 解釋真實災害情境。
- 進行政策建議。
- 評估大規模 computational performance。

## 2. 模型資料覆蓋範圍

本文件涵蓋 SP model 所需的：

- sets：`I, J, H, L, L_Amb, T, S`
- first-stage deterministic parameters：`f_j, cv, ca, cy_hj, nv, na, sbar_h, vbar_j, ubar_j, ybar_j`
- second-stage deterministic parameters：`c_ij, c_jh, kappa, eta, b_h, k_jl, tau_l, alpha_l, beta_l, rho_l, delta_l, t_ij, t_jh`
- random variable realizations：`xi_ilts, u_ijts, w_jhts, h_hts`
- scenario probability：`p_s`

注意：`X_j, V_j, U_j, Y_hj, FI, FO, RM, REG, TRT, WAT` 是 optimization decision variables，不應由 data generator 產生。

決策變數型態設定：

- First-stage decision variables：`X_j` 為 binary；`V_j, U_j, Y_hj` 若沿用原 SP model，設定為 nonnegative integer。
- Second-stage decision variables：`FI, FO, RM, REG, TRT, WAT` 全部設定為 **nonnegative continuous variables**，允許小數值，不需設定為 integer。
- 在 Gurobi 中，`FI, FO, RM, REG, TRT, WAT` 應使用 `vtype=GRB.CONTINUOUS` 且 `lb=0`；result validator 不應檢查這些二階變數是否為整數，而應使用 numerical tolerance 檢查 flow balance 與 capacity constraints。

## 3. Tiny case 設計原則

Tiny case 的設計原則如下：

1. 數值小，方便手算。
2. 使用固定 random seed，或直接使用 deterministic values。
3. 至少有一個完全 deterministic baseline。
4. 至少有一個 capacity binding 或 bottleneck case。
5. 至少有一個 road disruption case。
6. 至少有一個 hospital capacity bottleneck case。
7. 對 `tau_l > 1` 的 case，要能測試 `t - tau_l < 1` 時不產生 treatment completion。

## 4. Sets

建議 tiny default sets：

```text
I = {i1, i2}
J = {j1, j2}
H = {h1}
L = {minor, moderate, severe}
L_Amb = {moderate, severe}
T = {1, 2, 3}
S = {s1, s2}
p_s = 1 / |S|, for all s in S
```

第一個 deterministic baseline 可再縮小為：

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

## 5. Coordinates and distance matrices

Tiny case 可使用人工座標：

| Node | Coordinate |
|---|---:|
| `i1` | `(0, 0)` |
| `i2` | `(4, 0)` |
| `j1` | `(1, 1)` |
| `j2` | `(3, 1)` |
| `h1` | `(2, 4)` |

距離使用 Euclidean distance：

```text
d_ab = sqrt((x_a - x_b)^2 + (y_a - y_b)^2)
```

為了避免 0 distance 造成運輸成本為 0，可設定：

```text
d_ab = max(epsilon_distance, EuclideanDistance(a,b))
epsilon_distance = 0.1
```

## 6. First-stage deterministic parameters

### 6.1 Default generation rules

| Parameter | Tiny generation rule |
|---|---|
| `f_j` | `f_j = 100 + 5 * sum_l k_jl` |
| `cv` | `cv = 10` |
| `ca` | `ca = 30` |
| `cy_hj` | `cy_hj = supply_unit_cost * d_hj`, with `supply_unit_cost = 1` |
| `nv` | integer in `[4, 8]`; deterministic baseline use `nv = 4` |
| `na` | integer in `[1, 3]`; deterministic baseline use `na = 1` |
| `sbar_h` | integer in `[20, 60]`; deterministic baseline use `sbar_h1 = 20` |
| `vbar_j` | integer in `[2, 5]`; deterministic baseline use `vbar_j1 = 4` |
| `ubar_j` | integer in `[1, 3]`; deterministic baseline use `ubar_j1 = 1` |
| `ybar_j` | integer in `[10, 50]`; deterministic baseline use `ybar_j1 = 20` |

### 6.2 Unit-test advice

- 若要測試 opening logic，讓 `f_j` 不要太低，避免所有 CCP 都被打開。
- 若要測試 resource bottleneck，降低 `nv`、`na` 或 `sbar_h`。
- 若要測試 supply constraint，降低 `ybar_j` 或提高 `beta_l`。

## 7. Second-stage deterministic parameters

### 7.1 Road normal capacities and transportation costs

| Parameter | Tiny generation rule |
|---|---|
| `c_ij` | `ceil(base_cap_in / (1 + d_ij))`, lower bound `2`; use `base_cap_in = 20` |
| `c_jh` | `ceil(base_cap_out / (1 + d_jh))`, lower bound `2`; use `base_cap_out = 20` |
| `t_ij` | `t_ij = cost_per_km_in * d_ij`; use `cost_per_km_in = 1` |
| `t_jh` | `t_jh = cost_per_km_out * d_jh`; use `cost_per_km_out = 1.5` |

可設定：

```text
cost_per_km_out >= cost_per_km_in
```

表示 CCP 到醫院的 ambulance transfer 通常比災區到 CCP 的初步運送更昂貴。

### 7.2 Ambulance capacities and hospital ambulance fleet

| Parameter | Tiny generation rule |
|---|---|
| `kappa` | integer in `[2, 4]`; deterministic baseline use `kappa = 2` |
| `eta` | integer in `[2, 4]`; deterministic baseline use `eta = 2` |
| `b_h` | integer in `[1, 3]`; deterministic baseline use `b_h1 = 1` |

### 7.3 CCP physical capacity

| Severity | Tiny default `k_jl` |
|---|---:|
| `minor` | 8 |
| `moderate` | 5 |
| `severe` | 3 |

Deterministic baseline 可使用較小值：

| Severity | Baseline `k_j1,l` |
|---|---:|
| `minor` | 4 |
| `moderate` | 3 |
| `severe` | 2 |

### 7.4 Treatment time, staff productivity, and supplies

| Parameter | Tiny default |
|---|---|
| `tau_minor` | `1` |
| `tau_moderate` | `2` for boundary test; `1` for simplest deterministic baseline |
| `tau_severe` | `2` or `3` for boundary test; `1` for simplest deterministic baseline |
| `alpha_minor` | `4` |
| `alpha_moderate` | `2` |
| `alpha_severe` | `1` |
| `beta_minor` | `1` |
| `beta_moderate` | `2` |
| `beta_severe` | `3` |

Severity hierarchy must hold:

```text
tau_minor <= tau_moderate <= tau_severe
alpha_minor >= alpha_moderate >= alpha_severe
beta_minor <= beta_moderate <= beta_severe
```

### 7.5 Penalty costs

| Parameter | Tiny default |
|---|---:|
| `rho_minor` | 20 |
| `rho_moderate` | 80 |
| `rho_severe` | 200 |
| `delta_moderate` | 30 |
| `delta_severe` | 100 |

Recommended hierarchy:

```text
rho_minor < rho_moderate < rho_severe
delta_moderate < delta_severe
delta_l <= rho_l
```

## 8. Random variable realizations

All random variables are generated as scenario realizations:

```text
omega_s = {
  xi_ilts,
  u_ijts,
  w_jhts,
  h_hts
}
```

### 8.1 Casualty arrival `xi_ilts`

Tiny stochastic generation:

```text
total_i_s ~ DiscreteUniform(4, 12)
severity_ratio = {minor: 0.55, moderate: 0.30, severe: 0.15}
time_weight = {1: 0.60, 2: 0.30, 3: 0.10}
```

Use largest remainder method to guarantee:

```text
sum_l sum_t xi_ilts = total_i_s
```

### 8.2 Disaster-area-to-CCP road availability `u_ijts`

Tiny stochastic generation:

```text
u_ij1s ~ Uniform(0.5, 0.9)
repair_rate_ijs ~ Uniform(0.0, 0.2)
u_ijts = min(1.0, u_ij1s + repair_rate_ijs * (t - 1))
```

For deterministic baseline:

```text
u_ijts = 1 for all i,j,t,s
```

For road-disruption unit test:

```text
u_ijts = 0 for selected i,j,t,s
```

### 8.3 CCP-to-hospital road availability `w_jhts`

Tiny stochastic generation:

```text
w_jh1s ~ Uniform(0.6, 1.0)
repair_rate_jhs ~ Uniform(0.0, 0.2)
w_jhts = min(1.0, w_jh1s + repair_rate_jhs * (t - 1))
```

For deterministic baseline:

```text
w_jhts = 1 for all j,h,t,s
```

### 8.4 Hospital receiving capacity `h_hts`

Tiny stochastic generation:

```text
nominal_hospital_cap_h = integer in [4, 10]
damage_factor_hs ~ Uniform(0.5, 1.0)
restoration_rate_hs ~ Uniform(0.0, 0.2)
h_hts = floor(nominal_hospital_cap_h * min(1.0, damage_factor_hs + restoration_rate_hs * (t - 1)))
```

For deterministic baseline:

```text
h_h1,t,s1 = 3 for all t
```

## 9. Fully deterministic baseline instance

This is the first unit-test instance. It should be solved before any stochastic scenario test.

### 9.1 Sets

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

### 9.2 Random variable realizations

| Parameter | Value |
|---|---:|
| `xi_i1,minor,1,s1` | 2 |
| `xi_i1,moderate,1,s1` | 1 |
| `xi_i1,severe,1,s1` | 1 |
| `xi_i1,l,2,s1` | 0 for all `l` |
| `u_i1,j1,t,s1` | 1 for all `t` |
| `w_j1,h1,t,s1` | 1 for all `t` |
| `h_h1,t,s1` | 3 for all `t` |

### 9.3 Deterministic parameters

| Parameter | Value |
|---|---:|
| `f_j1` | 145 |
| `cv` | 10 |
| `ca` | 30 |
| `cy_h1,j1` | 1 |
| `nv` | 4 |
| `na` | 1 |
| `sbar_h1` | 20 |
| `vbar_j1` | 4 |
| `ubar_j1` | 1 |
| `ybar_j1` | 20 |
| `c_i1,j1` | 10 |
| `c_j1,h1` | 10 |
| `kappa` | 2 |
| `eta` | 2 |
| `b_h1` | 1 |
| `k_j1,minor` | 4 |
| `k_j1,moderate` | 3 |
| `k_j1,severe` | 2 |
| `tau_minor` | 1 |
| `tau_moderate` | 1 |
| `tau_severe` | 1 |
| `alpha_minor` | 4 |
| `alpha_moderate` | 2 |
| `alpha_severe` | 1 |
| `beta_minor` | 1 |
| `beta_moderate` | 2 |
| `beta_severe` | 3 |
| `rho_minor` | 20 |
| `rho_moderate` | 80 |
| `rho_severe` | 200 |
| `delta_moderate` | 30 |
| `delta_severe` | 100 |
| `t_i1,j1` | 1 |
| `t_j1,h1` | 1 |

### 9.4 Expected behavior

The expected qualitative behavior is:

- Minor casualties should not have hospital transfer variables.
- If the first-stage solution opens `j1` and allocates enough resources, most or all casualties should be transported out of the disaster area.
- `RM` should follow the equation `RM_t = RM_{t-1} + xi_t - sum_j FI_t`.
- `REG_jlt` should equal total incoming `FI` to CCP `j`.
- With `tau_l = 1`, treatment completion can occur in the same period under the current model convention.
- `WAT` for `moderate` and `severe` should only exist for `L_Amb`.

## 10. Additional unit-test cases

### Case A: all capacities sufficient

```text
u_ijts = 1
w_jhts = 1
h_hts = large
c_ij = large
c_jh = large
nv, na, sbar_h, k_jl = large enough
```

Expected: low or zero `RM` and low or zero `WAT`.

### Case B: road disruption

```text
u_ijts = 0 for selected i,j,t,s
```

Expected: corresponding `FI_ijlts = 0`; casualties remain in disaster area and `RM` increases.

### Case C: hospital capacity bottleneck

```text
h_hts = 0 for selected h,t,s
```

Expected: `FO_jhlts = 0` for the affected period; treated `L_Amb` casualties may accumulate in `WAT`.

### Case D: ambulance bottleneck

```text
kappa * U_j < total ambulance-required incoming demand
```

Expected: `FI` for `moderate` and `severe` is limited by CCP ambulance capacity.

### Case E: treatment-time boundary

```text
tau_moderate = 2
tau_severe = 3
T = {1, 2, 3}
```

Expected: when `t - tau_l < 1`, treatment completion term should be zero.

## 11. Required validation checks

Every generated tiny instance must pass:

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

After solve, the result validator should check:

Before checking constraints, use a numerical tolerance such as `1e-6`. Since `FI, FO, RM, REG, TRT, WAT` are continuous recourse variables, the validator should allow decimal values and should not require integer-valued second-stage solutions.

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
```

## 12. Known limitations

- Tiny case values are for debugging only.
- Tiny case should not be used for managerial interpretation.
- Some deterministic values are intentionally simple to make hand-checking easy.
- Once the deterministic baseline passes, stochastic tiny scenarios should be added gradually.
