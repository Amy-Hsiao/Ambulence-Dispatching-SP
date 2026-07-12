# 14 — Ellipsoidal 無法執行：診斷結論與修復計畫

## 診斷結論（證據鏈）

1. 失敗點：`risk_core.evaluate_wmcvar`（incumbent UB 評估用的小型 SOCP）
   回傳 **Gurobi status 12 = NUMERIC（數值困難）**，raise 後整場求解中斷。
   證據：`logs/ellipsoidal diagnostics/ellipsoidal_diagnostic_20260711_175036.log`
   的 traceback（T1/T2 FAIL）。
2. 觸發條件：全規模 instance 的 Q 向量量級 ~4×10⁷，搭配 a_E=0.0005 的
   SOC 係數，該版 Gurobi 的 barrier 在這種尺度組合下數值失敗。
   **這不是模型公式錯誤**——同一模型在小 instance（validate_risk_v2）與
   本機另一版 Gurobi（沙盒重現 50 組同量級隨機 Q）全部正常解到 OPTIMAL，
   代表問題是「特定 Gurobi 版本 × 大尺度 Q」的數值敏感性。
3. 前一輪修正（fractional 評估跳過 WMCVaR、只算 Q 和 cuts）已解決
   root seeding 階段的崩潰（診斷 T0–T4 PASS），但**整數 incumbent 的
   UB 評估仍必須呼叫 evaluate_wmcvar**，所以完整實驗仍會在 B&C 階段
   第一次整數解時中斷。診斷腳本停在 root seeding 後，測不到這段。
4. `engine="classic"` 無法繞過：classic 迴圈同樣經由
   `second_stage_objective_from_Q` 呼叫 evaluate_wmcvar。

## 修復方案（依建議順序）

### 方案 A（建議）：evaluate_wmcvar 數值前處理（純縮放，不動數學）

依據：WMCVaR 對 Q 是**正齊次**——WMCVaR(c·Q) = c·WMCVaR(Q)（c>0）。
（證明一行：目標與所有限制式對 (Q, φ, ℓ, 對偶變數) 均為線性齊次，
ambiguity set 只約束機率向量、與 Q 無關；φ*、ℓ*、ψ、ν 等皆隨 c 等比。）
沙盒已驗證：縮放前後解值相對差 ~1e-6（barrier 容差內）。

改動內容（僅 `risk_core.evaluate_wmcvar` 內部，約 15 行，數學零改動）：

1. 進場先算 `c = 1 / max(1.0, max(|Q_s|))`，以 `Q' = c·Q` 建模求解，
   回傳時 `value / c`、`phi_star / c`、`ell_star / c`。
   （worst_case_distribution 的 weights 用原尺度 Q 與換算回的 ℓ*，不受影響。）
2. 若仍非 OPTIMAL，依序 retry：`NumericFocus=3` → 再加 `BarHomogeneous=1`。
3. retry 全失敗才 raise（訊息附上 Q 量級與 scope，方便日後診斷）。

限制式邏輯、對偶重構、master、oracle 一律不動。

### 方案 B（環境層，可並行）：升級 Gurobi

`pip install --upgrade gurobipy`（確認學術授權相容新版）。沙盒版本
不會觸發 status 12，升級可能直接消失；但版本不受控，方案 A 仍應做，
才不會換台機器又壞。

### 方案 C（備援）：若修完 A 後 master 的 MISOCP 在 B&C 階段另出數值問題

改用 `run_dro_model(ambiguity_set="ellipsoidal", engine="classic")`
（portal 既有參數，不改程式）；classic 迴圈的 master 為獨立重解，
無 callback 相依。只在觀察到新失敗點時啟用。

## 驗收條件（方案 A 實作後，缺一不可）

1. `validate_risk_v2.py` 7/7 PASS（D1 對偶=原始暴力法、D6 引擎交叉
   一致——確保縮放沒有改變任何數學結果）。
2. 新增單元測試（併入 validate_risk_v2 或獨立腳本）：隨機 Q 量級掃
   1e0 ~ 1e8 × 三個 set，evaluate_wmcvar 與 worst_case_distribution
   原始解一致、且齊次性 |WMCVaR(cQ)/c − WMCVaR(Q)| 相對差 < 1e-5。
3. 使用者機器重跑 `run experiment/diagnose_ellipsoidal_failure.py`
   全 PASS，且其中至少一測完整跑到整數 incumbent 之後（不早停）。
4. 使用者機器跑一場完整 ellipsoidal case（S=30、α=0.9、λ=0.3、
   a_E=0.0005、gap=1%、tl=600）到正常結束（OPTIMAL 或 TIME_LIMIT，
   不得 exception）。
5. box / polyhedral / mcvar / 純 SP 回歸：objective 與修改前一致
   （縮放只在 evaluate_wmcvar 內，其他路徑理論上零影響，仍須實測）。

## 完成後停止

方案 A 為 `model core/risk_core.py` 的數值層修改（非模型邏輯），
**須使用者明確同意後才實作**；實作完成後停止回報驗收結果。
