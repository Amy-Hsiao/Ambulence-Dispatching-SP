# 08 — SP + MCVaR（Branch-and-Benders-Cut 版）

[CRITICAL REQUIREMENT: 只改 master，不改 oracle]
MCVaR 只影響 master problem 的目標式與輔助變數。`ScenarioOracle`、cut 生成邏輯
（ordinary cut、Papadakos/Pareto cut、core point、root seeding、user cuts、
parallel oracles、EV warm start）一律沿用，**一行都不能改動其數學邏輯**。
理由：cuts 是 θ_s ≥ Q_s(X,V,U,Y) 的下界近似；MCVaR 的目標式對每個 Q_s 單調不減，
所以既有 cut 對新目標式仍然有效（thesis 式 (1)-(1e)）。

## 對應公式（Thesis_Draft 3.4 節）

- 目標式 (1)：min C1 + MCVaR_α(Q)
- (1a)：MCVaR_α(Q) = (1−λ)·E_p[Q] + λ·CVaR_α(Q)
- (1b)+(1e) 線性化：CVaR_α = min_φ { φ + 1/(1−α)·Σ_s p_s·ℓ_s }，ℓ_s ≥ Q_s − φ，ℓ_s ≥ 0
- λ = 0 時退化為原本 SP；λ = 1 時為純 CVaR。

## 新增/修改檔案

1. `model core/risk_core.py`（新增）
   - `RISK_TYPES = ("sp", "mcvar", "dro_box", "dro_ellipsoidal", "dro_polyhedral")`
   - `make_risk_cfg(...)`：由 config 讀 α、λ 等值組成 risk_cfg dict。
   - `attach_risk_to_master(m, mv, S_selected, p0, risk_cfg)`：
     在 `lshaped_core.build_master` 建好的 master 上加：
     - `phi`（free）、`ell[s] ≥ 0`
     - 限制式 `ell[s] ≥ theta[s] − phi` ∀s
     - 改 objective 為 `C1 + (1−λ)·Σ p0_s·theta[s] + λ·(phi + 1/(1−α)·Σ p0_s·ell[s])`
     - 回傳新增變數 dict（併入 mv）。
   - `evaluate_mcvar(Q: dict[s,float], p0, alpha, lam) -> (value, phi_star)`：
     給定 oracle 算出的 Q 向量，解析計算 MCVaR：φ* = 離散分佈的 VaR_α
     （累積機率 ≥ α 的最小 Q 值），再代入 (1a)(1b)。供 incumbent UB 使用。
2. `model core/lshaped_core.py`（小幅修改，預設行為零改動）
   - `build_master(..., risk_cfg=None)`：risk_cfg 為 None ⇒ 與現行完全相同；
     否則呼叫 `risk_core.attach_risk_to_master`。
   - `solve_bbc(..., risk_cfg=None)` / `solve_classic(..., risk_cfg=None)`：
     所有「以 Σ p_s·Q_s 計算 UB / incumbent / heuristic 評估」之處，抽成
     `_objective_from_Q(Q, p0, risk_cfg)`；risk_cfg=None 時 = 現行期望值，
     mcvar 時呼叫 `evaluate_mcvar`。
   - EV warm start：一階解照舊；θ start 照舊；另外設 φ start = VaR_α(Q_start)、
     ℓ_s start = max(Q_s − φ, 0)。
   - **強制 multi_cut=True**：risk_cfg 非 None 且 multi_cut=False 時直接 raise
     （single-cut 的聚合 θ 無法餵 ℓ_s）。
3. `model portal/mcvar bbc.py`（新增，可執行入口）
   - 介面與 `benders bbc.py` 完全相同：`run_mcvar_model(scenario_size=None,
     sample_ratio=None, time_limit=None, mip_gap=None, alpha=None, lam=None)
     -> (model, summary)`；`if __name__ == "__main__": run_mcvar_model()`。
   - log 檔名前綴 `MCVAR_BBC_`，檔名尾端加 `_a{alpha}_l{lam}`。
   - RESULT SUMMARY 與 benders bbc 同格式（欄位標籤相同，batch runner 正則
     照常解析），VSS/EVPI 欄位印 `NA`，之後加印 risk 區塊：
     `alpha, lambda, phi* (VaR), E[Q], CVaR_alpha, MCVaR, first-stage cost`。
4. `model core/config.py`（新增參數區塊，附中文註解）
   - `RISK_ALPHA = 0.9`、`RISK_LAMBDA = 0.5`
   - 情境機率照舊（等權重 1/S 正規化後即為 p0）。

## 重要限制

- 不寫 extensive form 版本；直接用 B&BC 與既有全部 enhancement。
- risk_cfg=None 的舊 SP 路徑必須 bit-for-bit 不變（回歸保證）。
- 固定隨機種子規則照舊：同 seed 同 S 下，MCVaR 與 SP 用同一組情境資料。
- Gurobi 靜音、自訂 log（Best LB / Best UB / Gap / time）規則照舊。

## 自訂求解 log

同 benders bbc：每次 incumbent 更新或每 10 秒印一行；此處 Best UB / LB 均指
「MCVaR 目標值」而非期望值。最終 summary 照舊格式。

## 驗收條件（必須全部通過才算完成）

1. 回歸：`benders bbc.py` 在本階段修改後重跑，objective 與修改前完全一致。
2. λ=0：`mcvar bbc.py` 的 objective 與 `benders bbc.py` 相同（同 seed、同 S、
   gap 容差內）。
3. λ=1、α=0：退化為期望值（CVaR_0 = E[Q]），objective ≈ SP。
4. 單調性：固定 α，λ 增加 ⇒ objective 不減；固定 λ，α 增加 ⇒ objective 不減
   （小 instance：S=5、T=8 驗證 3×3 組合）。
5. 一致性：incumbent UB（oracle Q 向量 + evaluate_mcvar）與 master 收斂後的
   objective 在 gap 容差內一致。
6. 驗證腳本 `run experiment/validate_risk_v1.py`：自動跑 1–5 並印 PASS/FAIL。

## 完成後停止

完成後停止，列出修改/新增檔案、執行方式、驗證結果，等待使用者確認後才進入
09（DRO）。
