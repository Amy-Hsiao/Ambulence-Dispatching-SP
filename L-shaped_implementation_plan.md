# L-shaped (Benders) 演算法實作計畫

適用模型:兩階段 SP(`model_core.py` 之 extensive form)
基礎設定:Both = 全局 omega [0.8,1.2] + 空間 U[0.5,1.5](正規化)、S=5 起步、T=8、seed 42
目標:讓 RP 在 S = 20~100+ 可解;同一套框架日後延伸至 MCVaR 與 DRO。

---

## 1. 為什麼你的模型是 L-shaped 的標準案例

檢視 `model_core.py` 後確認三個關鍵性質:

**(a) 階段結構乾淨。** 一階變數 X(二元)、V、U、Y(整數)只出現在一階成本與一階資源限制式;二階變數 FI、FO、RM、REG、TRT、WAT **全部是連續變數**,依情境 s 完全可分——情境之間沒有任何耦合限制式。

**(b) 耦合只透過六類限制式的右手邊。** 固定一階解後,情境 s 的子問題是一個純 LP:

| 限制式 | 耦合的一階變數 |
|---|---|
| RoadCap_IJ / RoadCap_JH | X[j](容量 × X) |
| CCP_AmbCap | U[j] |
| CCP_PhysicalCap | X[j] |
| StaffCap | V[j] |
| SupplyCap | Σ_h Y[h,j] |
| Hosp_AmbCap / Hosp_ReceiveCap / 各流量守恆 | (無耦合) |

**(c) Relatively complete recourse 成立。** 對任何滿足一階限制式的 (X,V,U,Y),取 FI=FO=0,讓 RM 逐期吸收全部需求、WAT=0,即為可行解(以懲罰成本計價)。因此**不需要 feasibility cut,只需要 optimality cut**——這是 L-shaped 最簡單的形式。

另外,子問題目標值恆 ≥ 0,所以 θ_s ≥ 0 是合法的初始下界。

---

## 2. 分解設計

### 2.1 Master problem(MIP)

```
min  一階成本(X,V,U,Y) + Σ_s p_s · θ_s
s.t. Total_Staff, Total_CCP_Ambulances, Hosp_Supply_h,
     Logic_V_j, Logic_U_j, Logic_Y_j        (照抄 model_core 的一階限制式)
     θ_s ≥ 0                                 ∀s
     θ_s ≥ optimality cuts                   (迭代中加入)
     X 二元;V, U, Y 整數
```

規模:|J|=10 → 3×10 + 16×10 + S 個 θ ≈ 200 個變數,極小。

### 2.2 Subproblem(每情境一個 LP)

固定 (X̄,V̄,Ū,Ȳ) 後,情境 s 的二階 LP:

```
Q_s(x̄) = min  懲罰成本(RM,WAT) + 運輸成本(FI,FO)
         s.t. model_core 中所有含 s 的限制式,一階值代入
```

**實作技巧(讓 model_core 零改動):** 直接呼叫
`build_gurobi_model(..., S=[s], fixed_first_stage=x̄)` 建出單情境模型,
再把 X/V/U/Y 四組變數的 `vtype` 改成 `GRB.CONTINUOUS`(值已被 lb=ub 固定,
改型別不影響解,但模型變成純 LP → Gurobi 才會給對偶資訊)。

### 2.3 Optimality cut(reduced-cost / 敏感度形式)

一階變數以 lb=ub 固定在 LP 中,其 **reduced cost 即為 Q_s 對該變數的次梯度**。
解完子問題後直接讀取:

```
cut:  θ_s ≥ Q_s(x̄) + Σ_j  RC_X[j]·(X[j]−X̄[j]) + Σ_j RC_V[j]·(V[j]−V̄[j])
                    + Σ_j  RC_U[j]·(U[j]−Ū[j]) + Σ_{h,j} RC_Y[h,j]·(Y[h,j]−Ȳ[h,j])
```

由 LP 值函數對 bound 的凸性,此 cut 對所有 x 有效(標準 Benders cut 的等價形式)。
好處:不必手動整理六類耦合限制式的對偶乘子與 T 矩陣,新增限制式時也不會漏。
(教科書的對偶形式列為備選,兩者數學上等價。)

### 2.4 Multi-cut vs single-cut

採 **multi-cut**(每情境一條 θ_s、每輪最多加 S 條 cut)。理由:master 極小,
多變數無負擔;multi-cut 迭代次數顯著少於 single-cut;S ≤ 100 時 cut 總量無虞。
若未來 S > 500 再考慮聚合。

### 2.5 主迴圈:Branch-and-cut(lazy constraint)

不採「每輪把 master MIP 解到底」的古典迭代(慢),採現代作法:

```
1. 建 master 一次,設 LazyConstraints=1
2. model.optimize(callback)
3. callback 在 MIPSOL(找到整數 incumbent x̄)時:
     對每個 s:更新子問題 LP 的一階變數 bounds → 熱啟動 dual simplex 重解
     若 Q_s(x̄) > θ̄_s + tol:cbLazy 加入該情境的 cut
4. Gurobi 自己管理 branch-and-bound 與 cut pool,
   終止條件即原本的 MIPGap 1% / TimeLimit 3600s
```

**子問題模型重複使用**是效能關鍵:S 個 LP 在開始時各建一次,之後每個 incumbent
只改 60+160 個變數的 bounds 再熱啟動重解(單情境 LP 約 3 萬變數,dual simplex
重解預期 < 1 秒),絕不可每輪重建模型。

### 2.6 加速措施(依序啟用,先求對再求快)

1. **EV warm start**:master 用 EV 一階解 + 對應 θ_s = Q_s(x_EV) 當初始解(現成程式:`vss_evpi.py` 已會算 EV)。
2. **Root seeding(可選)**:正式 B&C 前,先在 LP 鬆弛 master 上跑 10~20 輪古典迭代,把 cut pool 墊高再開始分枝,通常大幅減少節點數。
3. **平行子問題(可選)**:S 大時,callback 內以多執行緒同時解 S 個 LP(每個子問題各自的 Gurobi environment)。
4. **數值設定**:懲罰係數達 1e5,建議 master 與子問題皆設 `NumericFocus=1`;cut 違反容差取相對值(如 1e-6 × |Q_s|)。

---

## 3. 與現有程式的介面

新增單一檔案 `lshaped.py`,**不動** `model_core.py`、`config.py`、`vss_evpi.py`:

```
lshaped.py
├── build_master(instance, S_selected, norm_probs) -> (master, vars, thetas)
│     一階限制式邏輯照 model_core §一階段落抄寫(唯一的重複程式碼,約 30 行)
│
├── class ScenarioOracle:
│     __init__(instance, s):  用 build_gurobi_model(S=[s], fixed_first_stage=零解)
│                             建 LP、鬆弛一階 vtype、關 OutputFlag
│     evaluate(first_stage) -> (Q_s, cut_coeffs):
│                             更新 bounds → optimize → 讀 ObjVal 與 RC
│
└── solve_lshaped(instance, S_selected, time_limit, mip_gap, ...) -> result
      result 包含:obj(=UB)、best_lb(master ObjBound)、gap、runtime、
      cuts_added、first_stage dict(格式同 vss_evpi 的 ev_first_stage)
```

**下游全部即插即用**:`compute_vss_evpi()` 只吃 `rp_best_lb / rp_best_ub / rp_gap`
三個數字,與求解引擎無關,一行都不用改;EV/EEV/WS 維持 extensive form(EV 單情境、
EEV 固定一階後是 LP、WS 單情境,都不是瓶頸;若 EEV 在大 S 變慢,可直接用
ScenarioOracle 逐情境評估後加權——數學上完全等價)。批次 runner 只需把
`sp_module.run_sp_model(...)` 換成 `lshaped.solve_lshaped(...)`,CSV/Excel 欄位
(num_vars 等改報 master+子問題合計或 master 值,註明即可)照舊。

新增 runner:`run_sp_lshaped.py`(比照 `sp model.py` 的輸出格式與 log 慣例,
log 同樣進 `logs\east district stress test`)。

---

## 4. 驗證流程(先於任何 S 放大實驗)

| # | 測試 | 通過標準 |
|---|---|---|
| V1 | S=1(B00 基準情境):L-shaped vs 直接解 extensive form | 目標值相對誤差 < 1e-4 |
| V2 | S=5,Both [0.8,1.2]:對照已收斂的 extensive 解 25,426,150.72(gap 0.016%) | 兩者 UB 差 < 兩邊 gap 之和 |
| V3 | S=5,Both [0.5,1.5]:先用 extensive form 放寬時限(過夜 8h)磨出緊參考值 | 同上 |
| V4 | 每次執行檢查 LB 單調不減、WS ≤ RP ≤ EEV | 邏輯警告零觸發 |
| V5 | 一階解比對:L-shaped 與 extensive 的開設 CCP 集合 | 一致(或目標值等價的替代解) |

V1–V5 全過之後才開始 S = 5, 10, 20, 30, 50 的放大實驗;屆時 extensive form
與 L-shaped 並列跑到 extensive 解不動為止,那張「兩種方法 CPU 對照表」就是
論文演算法章節的主表。

---

## 5. 里程碑與風險

| 里程碑 | 內容 | 估時 |
|---|---|---|
| M1 | ScenarioOracle + master,通過 V1 | 2–3 天 |
| M2 | Lazy callback 主迴圈,通過 V2–V5 | 2–3 天 |
| M3 | 效能:bounds 熱啟動、EV warm start、root seeding | 3–5 天 |
| M4 | runner / log / CSV / Excel 整合 + S 放大實驗 | 1–2 天 |

主要風險與對策:**(1) 退化導致重複 cut**——設 cut 違反容差、跳過與既有 cut 相同者;
**(2) tailing-off(LB 爬不動)**——目標本來就只要 1% gap,通常不會觸發;若發生,
再加 in-out / level 穩定化(留為備案,不先做);**(3) 大懲罰係數的數值問題**——
NumericFocus、必要時對目標做 1e-3 縮放,回報時還原;**(4) Gurobi lazy cut 細節**——
`LazyConstraints=1` 必設,且 MIPSOL 拿到的 x̄ 要用 `cbGetSolution`。

---

## 6. 對 MCVaR / DRO 的延伸(留欄位,不現在做)

- **Mean-CVaR**:目標加 λ·CVaR_α 項後,標準作法引入 η 與每情境超額變數 z_s ≥(情境成本)− η,結構仍是「一階 + 依情境可分的凸二階」,同一套 oracle 直接沿用,只有 master 的 θ 聚合方式改變。
- **DRO**(moment-based 或 Wasserstein):對偶化後為有限支撐上的 worst-case 加權,主流解法 column-and-constraint generation 與本框架共用子問題 oracle;Wasserstein 球半徑掃描時 ScenarioOracle 完全不變。

這是把 L-shaped 寫成獨立模組(而非塞進 sp model.py)的根本理由:同一個
ScenarioOracle 服務三個模型,演算法章節一次寫好、三章共用。
