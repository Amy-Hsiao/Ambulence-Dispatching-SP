# 12 — 實驗三：B&BC 加速策略 ablation（對應論文第 5 章演算法效率）

參考使用者提供的 BBD / BBD-IO / BBD-PO / BBD-Both 遞增式比較表。
**先計畫，經使用者確認後才實作。**

## 實驗設計

### 五個演算法配置（遞增階梯）

| 配置 | EV warm start | root seeding(+rounding heur.) | root user cuts | Pareto (Papadakos) |
|---|---|---|---|---|
| BBC        | – | – | – | – |
| BBC+WS     | ✓ | – | – | – |
| BBC+RS     | ✓ | ✓ | – | – |
| BBC+UC     | ✓ | ✓ | ✓ | – |
| BBC-Full   | ✓ | ✓ | ✓ | ✓ |

* Full − (BBC+UC) 的差即為 Pareto cuts 的貢獻，不需額外配置。
* 所有配置固定相同的 Gurobi 調參（MIPFocus、branch priority、heuristics、
  parallel oracles），只切換演算法元件，隔離貢獻來源。
* multi-cut 恆開（風險模型必要條件）。

### 需要的程式開關（實作階段才做）

* 新增 `BENDERS_PARETO_ENABLED`（config + solve_bbc 參數，預設 True 行為
  零改動）：False 時 root seeding 與 user cuts 的 dual-track 只加 standard
  cut、不建 core point、不解 Pareto oracle。
* 其餘配置用既有參數組合：`ev_warm_start`、`root_seed_iters=0`、
  `root_cut_rounds=0 / use_user_cuts=False`。

### 模型與規模

* 模型（2 個）：純 SP、SP+MCVaR+DRO(box)（α=0.9、λ=0.5、ε̄_B=0.01；
  只做 box——polyhedral master 同為 MILP 結構重複，ellipsoidal 擱置中，
  論文交代 box 為代表即可）。
* 網路固定：I=129 災區、J=10 CCP、H 16、T=8（不掃路網規模）。
* 規模：S = 30。
* 單 seed（MASTER_SEED）先跑；若之後需要 A.Time/NU 欄再擴 3 seeds。
* 總計 2 模型 × 5 配置 = 10 次求解。

### 停止條件（回應使用者的問題）

* `mip_gap = 1e-4`（= Gurobi 預設最優容差；文獻表格的 "Gap 0" 即此意，
  不設純 0% 以免數值誤差不收斂）、`time_limit = 3600`。
* 如此 Gap 欄僅在撞 time limit 時非零；S 的選擇以「Full 配置能在限內
  解到 optimal」為原則（pilot 先確認 S=100 可解，否則降級）。
* VSS/EVPI 不計算也不呈現（衡量建模價值而非演算法效率，且風險模型
  不適用）。

## 輸出：Excel 六分頁 + raw CSV

1–5. `BBC` / `BBC+WS` / `BBC+RS` / `BBC+UC` / `BBC-Full`：
   每分頁 = 一個配置的明細表，列 = {SP, DRO-box} ，
   欄位照使用者截圖（去掉 VSS/EVPI）：
   |I| Disaster | |J| CCP | |H| Hosp | |S| Scen | |T| Per | obj_value |
   First Stage Decision | Best LB | Best UB | CPU Time(s) | num_vars |
   num_constrs | Nodes | Iteration | Final Gap(%) | Total Cuts |
   Seed Cuts | Lazy Cuts | User Cuts | + Seeded LB(root)、model、config。
6. `ablation_table`：論文格式（仿參考表）——
   列群組 = model ，
   欄群組 = 五個配置並排，每配置三欄 Time | Gap(%) | Nodes。
   Obj 一致性不放此表（放明細分頁），但 runner 要自動檢查：同 model
   同 S 下五個配置的 obj 在容差內一致，不一致列警告。

## 入口

`run experiment/batch_ablation_experiment.py`（慣例同前兩個 runner：
頂端參數區、逐 case 重寫 CSV+xlsx、FAIL 續跑、log 移子資料夾）。
執行順序：五個配置連續跑（資料生成快取同一 instance），

## 驗收條件

1. `BENDERS_PARETO_ENABLED=True` 時所有既有驗證（validate_risk_v1/v2、
   benders bbc 回歸）結果不變。
2. 10 case 跑完或 FAIL 有記錄；六分頁齊全。
3. 同 model 同 S 的五個配置 obj 一致（容差 = 兩邊 gap 和）。
4. 趨勢預期：Time(BBC) ≥ Time(+WS) ≥ … ≥ Time(Full)（大體成立即可，
   不強制單調；反例在論文中討論）。

## 完成後停止

計畫經使用者確認後才實作；實作完成後停止回報。
