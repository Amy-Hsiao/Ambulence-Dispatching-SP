# Real Data Preparation Guide

目前 real-data workflow 是 skeleton。它只建立 CSV templates、檢查 raw CSV headers，尚未把真實資料轉成可求解 instance。

## 建立空白 Templates

```powershell
python scripts/build_real_data_templates.py
```

輸出：

```text
data/real/templates/
```

這些 CSV 只有欄位列，沒有真實資料。

## 放入 Raw Data

將 templates 複製到：

```text
data/real/raw/
```

填入真實資料後執行：

```powershell
python scripts/validate_real_data_only.py
```

輸出：

```text
data/real/processed/real_instance_skeleton.json
outputs/real_data_validation/validation_report.json
```

## Template List

| Template | 用途 |
|---|---|
| `nodes_template.csv` | 節點總表。 |
| `disaster_areas_template.csv` | `I` 災區集合與座標。 |
| `candidate_ccps_template.csv` | `J` CCP 候選點與第一階上限。 |
| `hospitals_template.csv` | `H` 醫院資料、供應與 ambulance fleet。 |
| `road_links_i_to_j_template.csv` | `c_ij` 與 `t_ij`。 |
| `road_links_j_to_h_template.csv` | `c_jh` 與 `t_jh`。 |
| `casualty_arrivals_template.csv` | `xi_ilts`。 |
| `road_availability_i_to_j_template.csv` | `u_ijts`。 |
| `road_availability_j_to_h_template.csv` | `w_jhts`。 |
| `hospital_capacity_template.csv` | `h_hts`。 |
| `scenario_probabilities_template.csv` | `p_s`。 |
| `first_stage_parameters_template.csv` | scalar 或 indexed first-stage parameters。 |
| `severity_parameters_template.csv` | `tau_l, alpha_l, beta_l, rho_l, delta_l`。 |

## Limitations

- `src/data_loading/real_data_loader.py` 目前只做 header validation。
- 它不會自動補缺失資料。
- 它不會宣稱真實資料已存在。
- 完整 real-data transformation 必須明確把 CSV rows 轉成 `docs/data_schema.md` 的 JSON schema。
