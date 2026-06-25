# Instance Data Schema

模型輸入是一個 JSON instance dictionary。Tiny cases 與未來 real-data loader 都必須轉成同一份 schema。

## Top-Level Keys

```text
name
case_metadata
sets
p_s
first_stage
second_stage
random_variables
```

`case_metadata` 可選，用來描述案例目的與 intended binding constraints。

## Sets

```text
sets = {
  "I": [...],
  "J": [...],
  "H": [...],
  "L": ["minor", "moderate", "severe"],
  "L_Amb": ["moderate", "severe"],
  "T": [1, 2, ...],
  "S": [...]
}
```

規則：

- `L_Amb` 必須是 `L` 的子集合。
- `minor` 不放入 `L_Amb`。
- 巢狀 random variables 的 period key 在 JSON 中用字串，例如 `"1"`。

## Scenario Probabilities

```text
p_s = {"s1": 1.0}
```

必須滿足：

```text
sum_s p_s[s] = 1
p_s[s] >= 0
```

## First-Stage Parameters

```text
first_stage = {
  "f_j": {"j1": ...},
  "cv": ...,
  "ca": ...,
  "cy_hj": {"h1": {"j1": ...}},
  "nv": ...,
  "na": ...,
  "sbar_h": {"h1": ...},
  "vbar_j": {"j1": ...},
  "ubar_j": {"j1": ...},
  "ybar_j": {"j1": ...}
}
```

## Second-Stage Deterministic Parameters

```text
second_stage = {
  "c_ij": {"i1": {"j1": ...}},
  "c_jh": {"j1": {"h1": ...}},
  "kappa": ...,
  "eta": ...,
  "b_h": {"h1": ...},
  "k_jl": {"j1": {"minor": ..., "moderate": ..., "severe": ...}},
  "tau_l": {"minor": ..., "moderate": ..., "severe": ...},
  "alpha_l": {"minor": ..., "moderate": ..., "severe": ...},
  "beta_l": {"minor": ..., "moderate": ..., "severe": ...},
  "rho_l": {"minor": ..., "moderate": ..., "severe": ...},
  "delta_l": {"moderate": ..., "severe": ...},
  "t_ij": {"i1": {"j1": ...}},
  "t_jh": {"j1": {"h1": ...}}
}
```

## Random Variable Realizations

```text
random_variables = {
  "xi_ilts": {"i": {"l": {"t": {"s": value}}}},
  "u_ijts": {"i": {"j": {"t": {"s": value}}}},
  "w_jhts": {"j": {"h": {"t": {"s": value}}}},
  "h_hts": {"h": {"t": {"s": value}}}
}
```

Validation rules：

- `xi_ilts >= 0`
- `0 <= u_ijts <= 1`
- `0 <= w_jhts <= 1`
- `h_hts >= 0`
- 所有 index 必須對應到 declared sets。

## Helper Modules

主要 schema helper 在：

```text
src/data/schema.py
```

real-data CSV skeleton 在：

```text
src/data_loading/
```
