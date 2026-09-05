"""check_vi_master.py — VI-6/7/8 在 Benders master 上的回歸測試。

tests/validate_vi.py 驗的是 extensive form（那裡沒有 θ_s，驗不到 VI-6/7/8）。
本程式補上 master 這一側，檢查三件事：

  1. master 根節點 LP 下界：開 VI 後必須「不低於」關 VI（VI 只會收緊鬆弛）。
     本模型具 relatively complete recourse，關 VI 時這個值應該是 0。
  2. 完整 BBC 求解的最佳目標值：開 VI 與關 VI 必須相同（VI 不改變最佳值）。
     SP 與 MCVaR 各驗一次。
  3. VI-6 的 q̲_s 與 VI-7 的 q̄_s 必須滿足 q̲_s ≤ 真實 Q ≤ q̄_s。
     （真實 Q 由求解結果的 scenario_q 取得。）

執行：python "tests/check_vi_master.py"
       python "tests/check_vi_master.py" --instance small --time-limit 300
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "model core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gurobipy as gp
from gurobipy import GRB

import config
import lshaped_core
import risk_core
import validate_vi as vv          # 借用它的 tiny_instance / real_instance

ALL_OFF = {"all": False}
REL_TOL = 1e-7


def _norm_probs(inst, S):
    sd = inst["scenario_data"]
    raw = {s: sd["probability"][s] for s in S}
    tot = sum(raw.values())
    return {s: p / tot for s, p in raw.items()}


def root_lp_bound(inst, S, vi_cfg, risk_cfg, lbf):
    """master 的根節點 LP 下界（整數變數全部鬆弛）。"""
    m, mv = lshaped_core.build_master(
        inst, S, _norm_probs(inst, S), time_limit=300.0, mip_gap=0.0,
        multi_cut=True, risk_cfg=risk_cfg, lbf_enabled=lbf, vi_cfg=vi_cfg)
    m.setParam("OutputFlag", 0)
    m.update()
    r = m.relax()
    r.setParam("OutputFlag", 0)
    r.optimize()
    val = r.ObjVal if r.status == GRB.OPTIMAL else float("nan")
    nv, nc = m.NumVars, m.NumConstrs
    lb = dict(mv.get("vi_theta_lb", {}))
    ub = dict(mv.get("vi_theta_ub", {}))
    r.dispose(); m.dispose()
    return val, nv, nc, lb, ub


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="tiny",
                    choices=["tiny", "small", "medium", "large", "full"])
    ap.add_argument("--scenarios", type=int, default=None)
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    inst = (vv.tiny_instance(n_s=a.scenarios or 2, seed=a.seed)
            if a.instance == "tiny" else vv.real_instance(a.instance, a.scenarios))
    S = inst["sets"]["S"]
    print("=" * 92)
    print(" VI-6/7/8 master 端回歸測試")
    print("=" * 92)
    print(f" instance : {inst['_label']}")
    print(f" 時限     : {a.time_limit:g}s")

    fails = []

    # ---------------- 1. 根節點 LP 下界 ----------------
    print("\n" + "-" * 92)
    print(" 1 · master 根節點 LP 下界（VI 只會收緊鬆弛，開了不可能變低）")
    print("-" * 92)
    print(f"  {'風險設定':<10}{'LBF':<6}{'VI':<6}{'根節點 LP':>20}{'vars':>9}{'constrs':>9}")
    lp_rows = {}
    for rname, rcfg in (("SP", None), ("MCVaR", risk_core.make_risk_cfg("mcvar"))):
        for lbf in (False, True):
            for vname, vcfg in (("off", ALL_OFF), ("on", None)):
                try:
                    val, nv, nc, qlo, qhi = root_lp_bound(inst, S, vcfg, rcfg, lbf)
                except gp.GurobiError as exc:
                    print(f"  {rname:<10}{str(lbf):<6}{vname:<6}  Gurobi 錯誤：{exc}")
                    return 2
                lp_rows[(rname, lbf, vname)] = val
                print(f"  {rname:<10}{str(lbf):<6}{vname:<6}{val:>20,.2f}{nv:>9}{nc:>9}")
            off = lp_rows[(rname, lbf, "off")]
            on = lp_rows[(rname, lbf, "on")]
            if on < off - abs(off) * 1e-9 - 1e-6:
                fails.append(f"根節點 LP 變低：{rname}/LBF={lbf}　{off:,.2f} → {on:,.2f}")
    print("\n  註：關 VI 且關 LBF 時根節點 LP 應為 0（relatively complete recourse），")
    print("  這正是 VI-6 與 VI-8 要解決的問題。")

    # ---------------- 2. 最佳值不變 ----------------
    print("\n" + "-" * 92)
    print(" 2 · 完整 BBC 求解的最佳目標值（VI 不得改變最佳值）")
    print("-" * 92)
    print(f"  {'風險設定':<10}{'VI':<6}{'UB':>20}{'LB':>20}{'Gap%':>8}{'nodes':>10}{'秒':>8}  狀態")
    for rname, rcfg in (("SP", None), ("MCVaR", risk_core.make_risk_cfg("mcvar"))):
        objs = {}
        for vname, vcfg in (("off", ALL_OFF), ("on", None)):
            t0 = time.time()
            # tiny instance 是合成的，沒有 EV 資料，關掉暖啟動（與 VI 無關）
            res = lshaped_core.solve_bbc(
                inst, S, time_limit=a.time_limit, mip_gap=0.0,
                risk_cfg=rcfg, vi_cfg=vcfg, verbose=False,
                ev_warm_start=("deterministic_data" in inst))
            objs[vname] = res
            print(f"  {rname:<10}{vname:<6}{(res['best_ub'] or float('nan')):>20,.6f}"
                  f"{res['best_lb']:>20,.6f}{(res['gap_pct'] or 0):>8.3f}"
                  f"{res['nodes']:>10,.0f}{time.time() - t0:>8.1f}  {res['status']}")
        u0, u1 = objs["off"]["best_ub"], objs["on"]["best_ub"]
        if u0 is None or u1 is None:
            fails.append(f"{rname}：其中一組沒有取得可行解")
        else:
            rel = abs(u1 - u0) / max(1.0, abs(u0))
            if rel > REL_TOL:
                fails.append(f"{rname} 最佳值改變：{u0:,.6f} → {u1:,.6f}（相對 {rel:.2e}）")
            # 3. q̲_s ≤ Q_s ≤ q̄_s
            res_on = objs["on"]
            qlo, qhi = res_on.get("vi_theta_lb", {}), res_on.get("vi_theta_ub", {})
            for s, q in (res_on.get("scenario_q") or {}).items():
                if s in qlo and q < qlo[s] - 1e-6 - 1e-9 * abs(q):
                    fails.append(f"{rname}/{s}：Q={q:,.2f} < q̲={qlo[s]:,.2f}")
                if s in qhi and q > qhi[s] + 1e-6 + 1e-9 * abs(q):
                    fails.append(f"{rname}/{s}：Q={q:,.2f} > q̄={qhi[s]:,.2f}")

    print("\n" + "-" * 92)
    print(" 3 · θ_s 的界包住真實 Q_s（由上一步的 scenario_q 檢查，違反會列在下方）")

    print("\n" + "=" * 92)
    if fails:
        print(f" 失敗 {len(fails)} 項：")
        for f in fails:
            print(f"   · {f}")
        print("=" * 92)
        return 1
    print(" 全部通過：VI 未改變任何最佳值，且根節點 LP 下界不降。")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
