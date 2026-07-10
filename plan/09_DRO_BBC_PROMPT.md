# 09 — SP + MCVaR + DRO（box / ellipsoidal / polyhedral，B&BC 版）

[CRITICAL REQUIREMENT: 沿用 08 的架構]
DRO 同樣只改 master：把 MCVaR 換成 worst-case MCVaR（WMCVaR）的對偶重構式。
oracle 與 cut 邏輯照舊不動。三個 ambiguity set 共用同一份程式骨架，只在
「對偶變數 + 對偶限制式 + objective」處分支。

## 對應公式（Thesis_Draft 3.5 節與 Appendix A）

- 模型 (28)-(31)：min C1 + λφ + (1−λ)·sup_p Qᵀp + λ/(1−α)·sup_p ℓᵀp
- Box (32)、Theorem 1 / (35)：MILP
- Ellipsoidal (33)、Theorem 2 / (36)：MISOCP
- Polyhedral (34)、Theorem 3 / (37)：MILP（∞-norm 拆成成對線性不等式）
- 名目機率 p0 = 正規化後的情境機率（等權重）；縮放矩陣取
  `A_E = a_E·I`、`A_P = a_P·I`（同 Jin et al. 2024 4.1.1 節設定）。

## Master 各 set 的新增內容（Q_s 一律以 theta[s] 代入）

共通（承接 08）：`phi` free、`ell[s] ≥ 0`、`ell[s] ≥ theta[s] − phi`。

1. `dro_box`（式 35）：
   - 新變數：`gamma` free、`zeta[s], varpi[s] ≥ 0`；hat 版本 `gamma_h, zeta_h[s], varpi_h[s]`
   - 限制式：`gamma + zeta[s] − varpi[s] = theta[s]` ∀s；
     `gamma_h + zeta_h[s] − varpi_h[s] = ell[s]` ∀s
   - objective：`C1 + λφ + (1−λ)[Σp0θ + ε̄_B(Σζ+Σϖ)] + λ/(1−α)[Σp0ℓ + ε̄_B(Σζ̂+Σϖ̂)]`
2. `dro_ellipsoidal`（式 36，A_E = a_E·I 可把 a_E 提出）：
   - 新變數：`Delta[s] ≥ 0, nu ≥ 0, pi` free（+ hat 版本）
   - SOC 限制式：`a_E·‖θ + Δ + π·e‖₂ ≤ ν`、`a_E·‖ℓ + Δ̂ + π̂·e‖₂ ≤ ν̂`
     （用 addGenConstrNorm 或 addQConstr 二擇一，master 變成 MISOCP）
   - objective：`C1 + λφ + (1−λ)[Σp0θ + p0ᵀΔ + ν] + λ/(1−α)[Σp0ℓ + p0ᵀΔ̂ + ν̂]`
3. `dro_polyhedral`（式 37，A_P = a_P·I）：
   - 新變數：`Gamma[s] ≥ 0, psi ≥ 0, chi` free（+ hat 版本）
   - ∞-norm 線性化：`−ψ ≤ a_P·(θ_s + Γ_s + χ) ≤ ψ` ∀s（hat 同理）
   - objective：`C1 + λφ + (1−λ)[Σp0θ + p0ᵀΓ + ψ] + λ/(1−α)[Σp0ℓ + p0ᵀΓ̂ + ψ̂]`

## ⚠ 數學有效性條件（必須寫進程式 assert）

Benders cut 以 θ_s 下界代 Q_s 之所以有效，是因為 sup_p 的目標對每個 Q_s 單調不減，
這要求 ambiguity set 內所有 p ≥ 0：
- ellipsoidal / polyhedral 定義 (33)(34) 已含 `p0 + A·ε ≥ 0`，天然滿足。
- **box (32) 沒有 p ≥ 0 條件**：必須 assert `ε̄_B ≤ min_s p0_s`（等權重時即
  `ε̄_B ≤ 1/|S|`），否則直接 raise 並提示調小 ε̄_B。論文參數設定也需遵守此界。

## 新增/修改檔案

1. `model core/risk_core.py`（擴充）
   - `attach_risk_to_master` 增加三個 dro 分支（上表）。
   - `evaluate_wmcvar(Q, p0, risk_cfg) -> (value, detail)`：incumbent UB 評估。
     給定 Q 向量解一個僅含 (φ, ℓ, 對偶變數) 的小型 LP/SOCP（|S| 維、毫秒級、
     獨立 gp.Env、靜音），回傳 worst-case MCVaR 值與 worst-case p 向量
     （worst-case p 由該小 LP 的對偶取得，實驗分析要用）。
   - `_objective_from_Q` 分派：sp→期望值、mcvar→evaluate_mcvar、dro_*→evaluate_wmcvar。
2. `model core/lshaped_core.py`：08 已留好 risk_cfg 接口，本階段只需確認
   dro 分支能走 `solve_bbc`。
   - **DRO-E 注意**：master 含 SOC 限制式時，Gurobi lazy constraint（cbLazy）
     需在 MISOCP 上運作。先以小 instance 驗證 callback 可用且 LB 正確；
     若不支援或數值不穩，DRO-E fallback 改走 `solve_classic` 迭代迴圈
     （cut 邏輯共用），並在 log 註明引擎。box / polyhedral 為純 MILP master，
     照走 B&BC。
3. `model portal/dro bbc.py`（新增，可執行入口）
   - `run_dro_model(ambiguity_set=None, alpha=None, lam=None, scope=None,
     scenario_size=None, sample_ratio=None, time_limit=None, mip_gap=None)
     -> (model, summary)`；檔案頂端 `AMBIGUITY_SET = "box"`（可改
     "ellipsoidal"/"polyhedral"），`__main__` 直接執行。
   - log 前綴 `DRO_{BOX|ELL|POLY}_BBC_`，檔名含 `_a{alpha}_l{lam}_e{scope}`。
   - RESULT SUMMARY 同格式；risk 區塊加印：ambiguity set、scope 參數、
     WMCVaR、對應的 in-sample MCVaR（名目 p0 下）、worst-case p 與 p0 的
     最大偏差、PDR%（若同場已知 SP 值則印，否則 NA）。
4. `model core/config.py`（新增）
   - `DRO_AMBIGUITY_SET = "box"`
   - `DRO_EPSILON_BOX = 0.01`、`DRO_A_E = 0.0005`、`DRO_A_P = 0.001`
     （預設值取 Jin et al. 2024 小算例設定，實驗時由 runner 覆寫）

## 驗收條件

1. 回歸：08 的 mcvar 與原 SP 路徑重跑結果不變。
2. 收斂一致性：scope → 0（ε̄_B=1e-8 / a_E=1e-8 / a_P=1e-8）時，三個 DRO 的
   objective 都收斂到同一 instance 的 MCVaR objective（gap 容差內）。
3. 保守性：DRO objective ≥ MCVaR objective（同 α, λ, seed）；PDR ≥ 0 且
   隨 scope 增加單調不減。
4. box assert：ε̄_B > 1/|S| 時必須 raise。
5. DRO-E：小 instance 上 B&BC 與 solve_classic 兩引擎 objective 一致
   （決定 DRO-E 正式引擎並記錄於 log）。
6. 驗證腳本 `run experiment/validate_risk_v2.py`：自動跑 1–5 印 PASS/FAIL
   （小 instance：S=5 與 S=10、T=8）。

## 完成後停止

完成後停止並回報，等待使用者確認後才進入 10（實驗）。
