# 10 — 實驗一：DRO 三種 ambiguity set 的 α × λ 網格掃描

實驗設計參考 Jin et al. (2024, TRE 103538) Tables 3–5（如論文 Table 4 的
呈現格式）。**目前只計畫實驗一；後續實驗（PDR、out-of-sample 等）等實驗一
完成並經使用者確認後再另行計畫。**

## 實驗內容

- 模型：`dro_box`、`dro_ellipsoidal`、`dro_polyhedral`（09 的 dro bbc）。
- 參數網格（同 Jin et al. Table 4）：
  - α ∈ {0.5, 0.6, 0.7, 0.8, 0.9}
  - λ ∈ {0.3, 0.5, 0.7, 0.9}
  - 共 5 × 4 × 3 = 60 個 case。
- scope 固定（runner 頂端可調）：ε̄_B = 0.01、a_E = 0.0005、a_P = 0.001
  （Jin et al. 4.1.2 設定；ε̄_B 需 ≤ 1/S，違反時 runner 直接報錯）。
- 基準 instance（runner 頂端可調）：Daan 資料、SAMPLE_RATIO=1.0、T=8、
  S=30、time_limit=3600、mip_gap=0.01、seed=MASTER_SEED。

## 批次調參入口

`run experiment/batch_risk_experiment.py`（新增，可直接 `python` 執行）

- 慣例完全比照 `batch_stress_test.py`：
  - 檔案頂端「Parameter setting area」：`ALPHA_VALUES`、`LAMBDA_VALUES`、
    `AMBIGUITY_SETS`、scope、instance 基準設定。
  - runner 只暫時 patch config 再還原，不改 model core。
  - 逐 case 呼叫 `dro bbc.py` 的 `run_dro_model(...)`，log 移入
    `experiment result/` 子資料夾。
  - **每完成一個 case 立即重寫輸出檔**（中斷可續看已完成部分）；
    單一 case 失敗記 FAIL 續跑，不中斷整批。
- 執行順序：box 全網格 → ellipsoidal → polyhedral；同 set 內依 α 再 λ 排序。

## 輸出（console + Excel）

1. console：每 case 結束印一行摘要
   `set | alpha | lambda | objective | Gap% | CPU(s)`；
   全部結束後把三個 set 的 α×λ objective 矩陣依 Table 4 格式印出。
2. Excel：`experiment result/DRO_alpha_lambda_<日期>.xlsx`，**六個分頁**：
   - `box` / `ellipsoidal` / `polyhedral`：明細表，欄位同 stress test 格式
     （factor | |I| Disaster | |J| CCP | |H| Hosp | |S| Scen | |T| Per |
     obj_value | First Stage Decision | Best LB | Best UB | CPU Time(s) |
     num_vars | num_constrs | Nodes | Iteration | Final Gap(%)），
     後接 risk 欄（α、λ、scope、開站數、ΣV/ΣU/ΣY、E[Q]、VaR、CVaR、
     MCVaR、WMCVaR、worst_p_max_dev）與 B&BC 統計欄。
   - `box_matrix` / `ellipsoidal_matrix` / `polyhedral_matrix`：
     列 = α（0.5–0.9）、欄 = λ（0.3–0.9）的 objective 矩陣
     （排版同 Jin et al. Table 4），下方附 `CPU Time(s)` 與
     `Final Gap(%)` 兩個同形狀矩陣。
3. 另存一份 raw CSV（`DRO_alpha_lambda_raw_<日期>.csv`）：每 case 一列，
   欄位 = set | alpha | lambda | scope | I/J/H/S/T | objective | E[Q] |
   CVaR | phi* | Best LB/UB | Gap% | CPU(s) | nodes | cuts | 開站清單 |
   ΣV | ΣU | ΣY | status(OK/FAIL) | log 檔名（可追溯）。
4. 一階解存 json（`experiment result/first_stage/`），供之後的實驗重用。

## 驗收條件

1. 60 case 全部跑完（或 FAIL 有記錄），Excel 三分頁齊全、矩陣無空格
   （FAIL 的格子填 "FAIL"）。
2. 趨勢檢查：固定 α 時 objective 隨 λ 遞增；固定 λ 時隨 α 遞增
   （同 Jin et al. Tables 3–5 的規律）；違反者在 console 標警告。
3. 同 seed 重跑任一 case，objective 與首次一致（可重現性）。
4. Excel 可直接開啟，格式乾淨可貼進論文。

## 完成後停止

實驗一跑完後停止，回報三個矩陣與異常 case，等使用者確認數字合理後，
再計畫後續實驗（PDR、out-of-sample、計算效率等）。
