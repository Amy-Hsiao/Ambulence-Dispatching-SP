# 11 — 實驗二：Price of Distributional Robustness（PDR）

對應 Jin et al. (2024) 式 (41) 與 Table 6；論文 6.3 節。

## 定義

PDR = (DRO* − MCVaR*) / MCVaR*，其中 MCVaR* 是**同 α、λ** 的
SP+MCVaR（RA-TSSP）最佳值，DRO* 是各 ambiguity set 在指定 scope 下的
SP+MCVaR+DRO 最佳值。固定 α = λ = 0.9（可調）。

## 求解需求

MCVaR baseline 解 1 次 + 每個 set × 每個 scope 各解 1 次
（預設 1 + 3×5 = 16 次）。

⚠ Gap 紀律：Table 6 的 PDR 均 < 1%，mip_gap 必須遠小於 PDR 訊號
（預設 0.001，正式跑建議 0.0005 以下），baseline 與 DRO 用同一 gap、
同 seed、同情境資料，否則 PDR 是雜訊。PDR 為負且超出 gap 容差時
console 要警告。

## scope 掃描值（box 上限 = 1/S；S=30 時 ≈ 0.033，不能照抄 Jin 的 0.15/0.2）

- box ε̄_B：{0.001, 0.005, 0.01, 0.02, 0.03}
- ellipsoidal a_E：{0.00005, 0.0001, 0.0005, 0.001, 0.01}
- polyhedral a_P：{0.0005, 0.005, 0.01, 0.05, 0.5}

## 入口

`run experiment/batch_pdr_experiment.py`（慣例同 batch_risk_experiment.py：
頂端參數區、逐 case 重寫輸出、FAIL 續跑、log 移子資料夾、一階解存 json）。

## 輸出：Excel 四分頁 + raw CSV

1. `box` / `ellipsoidal` / `polyhedral`：明細表（欄位同 stress test：
   factor | |I| | |J| | |H| | |S| | |T| | obj_value | First Stage Decision |
   Best LB | Best UB | CPU Time(s) | num_vars | num_constrs | Nodes |
   Iteration | Final Gap(%)，不含 VSS/EVPI），第一列為 MCVaR baseline，
   之後每列一個 scope，尾端附 scope、PDR(%)、WMCVaR 等 risk 欄。
2. `PDR_table`：論文格式（Jin Table 6）——三組並排欄
   （ω|PDR、a_E|PDR、a_P|PDR），可直接貼論文。

## 驗收條件

1. 16 case 全跑完或 FAIL 有記錄；四分頁齊全。
2. 每個 set 的 PDR 隨 scope 單調不減（gap 容差內），scope 最小值 PDR ≈ 0。
3. PDR 負值超容差 → console 警告並提示調緊 gap。
4. 同 seed 重跑結果一致。

## 完成後停止

跑完回報 PDR 表，經使用者確認後再計畫實驗三（out-of-sample）。
