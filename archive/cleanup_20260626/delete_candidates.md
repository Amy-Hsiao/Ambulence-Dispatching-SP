# Cleanup 2026-06-26 可刪候選清單

本輪採用「先歸檔再刪」策略，因此以下檔案目前只移到 `archive/cleanup_20260626/`，尚未永久刪除。

## 可考慮刪除的歸檔內容

- `output_legacy/`：舊 `output/` 根目錄。新版統一使用 `outputs/`。
- `scripts_legacy/`：重複 numbered scripts `01_...` 到 `07_...`。新版保留 `scripts/run_tiny_baseline.py`、`scripts/run_tiny_tests.py`、`scripts/diagnose_tiny_tests.py`、`scripts/build_real_data_templates.py`、`scripts/validate_real_data_only.py`。
- `src_wrapper_legacy/ambulance_sp/`：整理前的 wrapper package。核心程式已保留在 `src/data/`、`src/model/`、`src/io/`、`src/validation/`，real-data skeleton 已移到 `src/data_loading/`。
- `outputs_legacy/`：舊命名結果檔，例如 `<case>_results.json`、`summary_zh.md`、timestamp fallback CSV、舊 run logs。
- `data_legacy/generated/`：舊 tiny generated JSON。新版 tiny instances 放在 `data/tiny/instances/`。
- `docs_legacy/`：過時 refactor/parameter generation 文件與舊 `.docx` 規則文件。

## 刪除前必須確認

1. `python scripts/run_tiny_baseline.py` 通過。
2. `python scripts/run_tiny_tests.py` 通過，且 objective 完全維持 regression targets。
3. `python scripts/diagnose_tiny_tests.py` 通過。
4. `rg "ambulance_sp|01_generate|02_run|03_run|04_diagnose|05_build|06_validate|07_run|output/" scripts src tests docs README.md configs` 沒有主流程引用。

未完成以上確認前，不建議永久刪除 archive。
