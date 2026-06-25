# Cleanup 2026-06-26 Regression Targets

整理前必須維持的 tiny case objective：

| Case | Objective |
|---|---:|
| deterministic_baseline | 208 |
| all_capacities_sufficient | 208 |
| road_disruption | 526 |
| hospital_capacity_bottleneck | 336 |
| ambulance_bottleneck | 287 |
| treatment_time_boundary | 205 |

本次 cleanup 不允許修改 `src/model/sp_model.py` 的 objective、constraints、variables，也不允許修改 tiny case 參數來硬修結果。
