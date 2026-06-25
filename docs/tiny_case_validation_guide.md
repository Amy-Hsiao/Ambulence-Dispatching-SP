# Tiny Case Validation Guide

Tiny cases 是整理與重構時的 regression targets。任何資料夾整理、命名調整、輸出改路徑，都不得改變 objective。

## Required Commands

依序執行：

```powershell
python scripts/run_tiny_baseline.py
python scripts/run_tiny_tests.py
python scripts/diagnose_tiny_tests.py
```

## Expected Objectives

| Case | Objective | 主要檢查 |
|---|---:|---|
| `deterministic_baseline` | 208 | baseline mass balance、first-stage linking、minor 無 `FO/WAT` |
| `all_capacities_sufficient` | 208 | 容量足夠時 `RM=0` 且 `WAT=0` |
| `road_disruption` | 526 | inbound road `u=0` 時該 link 的 `FI=0` 且 `RM` 增加 |
| `hospital_capacity_bottleneck` | 336 | hospital receiving capacity 阻擋 `FO`，`WAT` 增加 |
| `ambulance_bottleneck` | 287 | CCP ambulance capacity binding |
| `treatment_time_boundary` | 205 | `t - tau_l < 1` 時 completion term 為 0 |

`scripts/run_tiny_tests.py` 會直接比對 objective；若任一 case 改變，script 會停止。

## Output Layout

```text
outputs/tiny_tests/<case>/
├─ results.json
├─ nonzero_variables.csv
├─ constraint_violations.csv
└─ summary.md
```

Baseline：

```text
outputs/tiny_baseline/deterministic_baseline/
```

Diagnostics：

```text
outputs/tiny_diagnostics/tiny_test_diagnostic_report.md
outputs/tiny_diagnostics/tiny_test_diagnostic_report.json
```

## 整理時注意事項

- 不修改 `src/model/sp_model.py`。
- 不修改 `src/data/tiny_generator.py` 裡的 tiny case 參數來硬修 objective。
- 若結果改變，先回報原因，不要調整參數。
