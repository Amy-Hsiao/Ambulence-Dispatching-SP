# 專案資料夾結構

本文件說明 cleanup 後每個資料夾的用途。專案採用英文路徑，並以繁體中文文件與報告說明內容。

## 根目錄

```text
.
├─ configs/
├─ data/
├─ docs/
├─ outputs/
├─ papers/
├─ scripts/
├─ src/
├─ tests/
└─ archive/
```

## 資料夾用途

| 資料夾 | 用途 |
|---|---|
| `configs/` | YAML 設定檔，目前包含 tiny baseline/tests 與 real-data template 預設路徑。 |
| `data/` | 輸入資料、tiny instances、real-data templates。 |
| `docs/` | 中文文件，解釋專案結構、資料格式、tiny 驗證、真實資料準備。 |
| `outputs/` | 唯一正式輸出根目錄。所有求解結果與診斷報告都放這裡。 |
| `papers/` | 參考文獻 PDF。 |
| `scripts/` | 使用者主要執行入口。 |
| `src/` | Python 原始碼。 |
| `tests/` | pytest 測試。 |
| `archive/` | cleanup 歸檔區，保存舊檔與可刪候選，不參與目前執行流程。 |

## `data/`

```text
data/
├─ tiny/instances/       # tiny cases 的 JSON instance
└─ real/
   ├─ templates/         # 空 CSV templates
   ├─ raw/               # 使用者未來放真實 CSV 的位置
   └─ processed/         # real-data skeleton validation output
```

`data/generated/` 舊資料夾已歸檔，不再作為主要輸入位置。

## `outputs/`

```text
outputs/
├─ tiny_baseline/
│  └─ deterministic_baseline/
├─ tiny_tests/
│  └─ <case>/
├─ tiny_diagnostics/
└─ real_data_validation/
```

每個 case 的標準輸出檔：

```text
results.json
nonzero_variables.csv
constraint_violations.csv
summary.md
```

## `scripts/`

| Script | 用途 |
|---|---|
| `run_tiny_baseline.py` | 產生、求解、驗證 deterministic baseline。 |
| `run_tiny_tests.py` | 跑全部 tiny regression cases，並檢查 objective。 |
| `diagnose_tiny_tests.py` | 讀取 tiny outputs，產生診斷報告。 |
| `build_real_data_templates.py` | 建立 real-data CSV templates。 |
| `validate_real_data_only.py` | 只檢查 real-data CSV header，不求解模型。 |

## `src/`

| 模組 | 用途 |
|---|---|
| `src/data/` | instance schema helper 與 tiny generator。 |
| `src/data_loading/` | real-data template builder 與 loader skeleton。 |
| `src/io/` | result writer，輸出 JSON/CSV/Markdown。 |
| `src/model/` | gurobipy extensive-form SP model。 |
| `src/validation/` | instance 與 solution validation。 |

模型核心只在 `src/model/sp_model.py`。

## 歸檔區

本次整理歸檔到：

```text
archive/cleanup_20260626/
```

包含舊 `output/`、重複 numbered scripts、wrapper package、舊命名 outputs、過時 docs 與可刪候選清單。
