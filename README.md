# 救護車調度與損壞道路修復決策：Two-Stage SP Tiny Case

本專案實作一個 **純 two-stage stochastic programming extensive-form model**，用 `gurobipy` 求解災後傷患疏散、CCP 配置、醫療人員/救護車/物資配置，以及情境式道路與醫院容量不確定性。

## V1 範圍

目前只做：

- plain two-stage stochastic programming extensive form
- `gurobipy` 直接建模與求解
- tiny deterministic / validation cases
- real-data CSV template 與 loader skeleton

目前不做：

- DRO
- Benders / L-shaped method
- heuristics
- warm-start
- 自訂演算法或 decomposition

數學模型核心在：

```text
src/model/sp_model.py
```

整理資料夾時不得修改這個檔案中的 objective、constraints、variables，也不得修改 tiny case 參數來硬修結果。

## 為什麼資料夾和程式不用中文命名？

本專案採用「英文路徑 + 繁體中文說明」：

- Python import/package 對英文路徑最穩定。
- Windows terminal、pytest、Gurobi、pip、Git 對中文檔名有時會遇到編碼或路徑問題。
- 使用英文檔名能降低工具鏈風險；用中文 README、docs、terminal/report 文字補足可讀性。

## 資料夾說明

```text
configs/      YAML 設定檔。保留 tiny baseline/tests 與 real-data template 的預設路徑。
data/         輸入資料與 templates。
docs/         中文文件：專案結構、資料格式、tiny 驗證、真實資料準備。
outputs/      所有求解結果與診斷報告。專案只保留這一個輸出根目錄。
papers/       參考文獻 PDF。
scripts/      使用者主要執行入口。
src/          Python 原始碼。
tests/        pytest 測試。
archive/      cleanup 歸檔區；不是目前執行流程的一部分。
```

`output/` 舊資料夾已歸檔到：

```text
archive/cleanup_20260626/output_legacy/
```

## 程式入口

### 1. 跑 deterministic baseline

```powershell
python scripts/run_tiny_baseline.py
```

用途：

- 產生 `deterministic_baseline` tiny instance
- 建立並求解 SP model
- 驗證解
- 輸出結果到 `outputs/tiny_baseline/deterministic_baseline/`

### 2. 跑全部 tiny regression cases

```powershell
python scripts/run_tiny_tests.py
```

用途：

- 依固定順序跑 6 個 tiny cases
- 檢查每個 objective 是否等於 regression target
- 每個 case 輸出到 `outputs/tiny_tests/<case>/`

### 3. 產生 tiny diagnostic report

```powershell
python scripts/diagnose_tiny_tests.py
```

用途：

- 讀取 `outputs/tiny_tests/<case>/results.json`
- 檢查每個 tiny case 是否真的觸發預期模型邏輯
- 輸出到 `outputs/tiny_diagnostics/`

### 4. 建立 real-data CSV templates

```powershell
python scripts/build_real_data_templates.py
```

用途：

- 建立空白 CSV templates 到 `data/real/templates/`
- 只產生欄位，不代表真實資料已存在

### 5. 檢查 real-data CSV headers

```powershell
python scripts/validate_real_data_only.py
```

用途：

- 檢查 `data/real/raw/` 裡 CSV 是否符合 templates 欄位
- 產生 skeleton validation summary
- 不求解模型，也不自動補真實資料

## Tiny Case Regression Targets

| Case | Objective |
|---|---:|
| `deterministic_baseline` | 208 |
| `all_capacities_sufficient` | 208 |
| `road_disruption` | 526 |
| `hospital_capacity_bottleneck` | 336 |
| `ambulance_bottleneck` | 287 |
| `treatment_time_boundary` | 205 |

如果任一 objective 改變，請停止整理並回報原因，不要調參數硬修。

## 輸出結構

每個 case 都有自己的資料夾：

```text
outputs/tiny_tests/road_disruption/
├─ results.json
├─ nonzero_variables.csv
├─ constraint_violations.csv
└─ summary.md
```

標準檔案說明：

- `results.json`：完整求解結果、objective decomposition、變數值、validator summary
- `nonzero_variables.csv`：第一階變數與非零 second-stage variables
- `constraint_violations.csv`：各 constraint family 最大違反量
- `summary.md`：繁體中文求解摘要

## 原始碼結構

```text
src/data/          tiny case schema helper 與 tiny case generator
src/data_loading/  real-data CSV template builder 與 loader skeleton
src/io/            result writer，輸出 JSON/CSV/Markdown
src/model/         gurobipy extensive-form SP model
src/validation/    instance validator 與 solution validator
```

`src/model/sp_model.py` 是模型核心。其他資料夾負責資料、輸出與驗證。

## 重要文件

- `docs/project_structure.md`
- `docs/data_schema.md`
- `docs/tiny_case_validation_guide.md`
- `docs/real_data_preparation_guide.md`

過時文件與重複腳本已移到：

```text
archive/cleanup_20260626/
```
