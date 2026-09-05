"""validate_vi.py — 有效不等式正確性驗證：一支程式逐條驗證全部八條 VI。

執行方式
--------
    python "tests/validate_vi.py"                       # 預設：tiny instance，三關全跑
    python "tests/validate_vi.py" --self-test           # 附反向對照（建議至少跑一次）
    python "tests/validate_vi.py" --instance small --gates 2 --scenarios 3
    python "tests/validate_vi.py" --gates 2 --samples 80

三道關卡（對應規格書第 3 節）
---------------------------
關卡一　最佳值一致
    在 extensive form 上比較「無 VI」與「逐條加入 VI」的最佳目標值，必須逐位相同。
    另外單獨跑一次「五條全開」，抓 VI 之間互相干擾才會出現的錯誤。
    涵蓋 VI-1 ~ VI-5。

關卡二　隨機解逐條檢查
    隨機抽第一階段可行解 x（含全零解與 x̄），對每個情境求出真實的 Q(x; ω^s)，檢查：
      · VI-1/2/3（EXACT）：收緊後的限制式在該情境的第二階段最佳解上不被違反
      · VI-6（RELAX）：q̲_s ≤ Q(x; ω^s)
      · VI-7（OPT）  ：Q(x; ω^s) ≤ q̄_s
      · VI-8（RELAX）：彙總鬆弛 LP 的最佳值 ≤ Q(x; ω^s)

關卡三　最佳解代回
    取關卡一的最佳解，把所有 VI 代回去檢查。注意 OPT 型只保證「存在一個最佳解
    滿足」，所以只有在成本係數嚴格為正（可證明「每一個」最佳解都滿足）時，
    違反才判 FAIL；否則僅列為參考。

判定狀態
--------
    PASS          通過
    FAIL          違反，必須修正
    VACUOUS       跑完了，但該 VI 在這個 instance 上完全沒作用，通過沒有意義
    INCONCLUSIVE  求解器未達最佳（超時等），無法判定
    NO DATA       該關卡沒有取得任何有效樣本
    SKIP / —      本次未跑 / 該關卡不適用於這條

輸出
----
    · 主控台印出各關的表 + 一張八條 × 三關的總判定表
    · 同一份內容寫到 --report（預設 tests/vi_validation_report.txt）
    · 機器可讀的 JSON（同名 .json；若 --report 本身是 .json 則寫成 .meta.json）
    · exit code：0 全部通過；1 有 FAIL 或未完整驗證；2 Gurobi 授權容量不足

注意
----
    --instance tiny 用受限版 Gurobi 授權（pip 安裝內附的那個）就跑得完；
    真實 instance（small / medium / large / full）遠超過受限授權的上限，
    必須在有完整授權的機器上跑。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import math
import random
import sys
import time
from pathlib import Path

# 主控台若不是 UTF-8（Windows 中文版預設 cp950），θ、x̄、q̲ 這些字會直接讓
# print 丟 UnicodeEncodeError，整份報告在寫檔前就死掉。先把輸出串流轉成 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "model core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gurobipy as gp
from gurobipy import GRB

import config
import vi_reference as vir
from vi_reference import SolveFailed


REL_TOL_GATE1 = 1e-7    # 關卡一：最佳值的相對容差
COST_TOL_ABS = 1e-6     # 關卡二：成本量綱（VI-6/7/8）的絕對容差
COST_TOL_REL = 1e-9     # 關卡二：成本量綱的相對容差
FLOW_TOL = 1e-6         # 關卡二／三：人數量綱（VI-1/2/3）的絕對容差
                        # 不可與成本共用容差 —— Q 動輒 1e10，相對容差會把
                        # 好幾十個人的違反當成雜訊放過去。

# 這些狀態代表「這個模型沒有可行解／解爆了」，對 EXACT/OPT 而言是決定性的錯誤
FATAL_STATUS = {GRB.INFEASIBLE, GRB.INF_OR_UNBD, GRB.UNBOUNDED}
STATUS_NAME = {2: "OPTIMAL", 3: "INFEASIBLE", 4: "INF_OR_UNBD", 5: "UNBOUNDED",
               9: "TIME_LIMIT", 11: "INTERRUPTED", 12: "NUMERIC", 13: "SUBOPTIMAL"}


def sname(st):
    return STATUS_NAME.get(st, f"STATUS_{st}")


def violated(viol, tol):
    """NaN 安全的違反判定。

    直接寫 `viol > tol` 時，viol 是 NaN 會得到 False，於是「算不出來」會被
    當成「沒有違反」而判 PASS —— 這是最危險的失效方向。改用 not(<=)，
    NaN 就會落在違反那一側。
    """
    return not (viol <= tol)


# ===================================================================== #
# 輸出                                                                   #
# ===================================================================== #
class Tee:
    def __init__(self, echo=True):
        self.buf = io.StringIO()
        self.echo = echo

    def __call__(self, line=""):
        if self.echo:
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("utf-8", "replace").decode("utf-8", "replace"))
        self.buf.write(line + "\n")

    def text(self):
        return self.buf.getvalue()


class Quiet(Tee):
    """反向對照期間只留結論，吞掉破壞版的細節表。"""

    def __init__(self):
        super().__init__(echo=False)


# ===================================================================== #
# instance                                                              #
# ===================================================================== #
def tiny_instance(n_i=4, n_j=3, n_h=2, n_t=3, n_s=2, seed=7):
    """自足的小型 instance（不讀 CSV），結構與 config.generate_data 的輸出相同。

    容量刻意調得偏緊，讓 VI-3、VI-4、VI-5 與各條道路限制式都真的會綁到，
    否則驗證會在「反正沒作用」的情況下輕鬆通過，等於沒驗到。
    """
    rng = random.Random(seed)
    I = [f"I{k}" for k in range(n_i)]
    J = [f"J{k}" for k in range(n_j)]
    H = [f"H{k}" for k in range(n_h)]
    T = [f"T{k + 1}" for k in range(n_t)]
    S = [f"S{k + 1}" for k in range(n_s)]
    L = list(config.SEVERITY_LEVELS)
    L_tr = list(config.TRANSFER_SEVERITY_LEVELS)
    P = config.PARAMETERS

    params = {
        "ccp_fixed_opening_cost": {j: 150000.0 for j in J},
        "staff_unit_assignment_cost": P["staff_unit_assignment_cost"],
        "ccp_ambulance_unit_assignment_cost": P["ccp_ambulance_unit_assignment_cost"],
        "supply_allocation_cost_from_hospital_to_ccp": {h: {j: 1800.0 for j in J} for h in H},
        "total_available_staff": 30.0,
        "total_available_ccp_ambulances": 8.0,
        "hospital_supply_upper_bound": {h: 120.0 for h in H},
        "ccp_staff_upper_bound": {j: 14.0 for j in J},
        "ccp_ambulance_upper_bound": {j: 4.0 for j in J},
        "ccp_supply_upper_bound": {j: 150.0 for j in J},
        "hospital_ambulance_fleet": {h: 3.0 for h in H},
        "ccp_ambulance_casualty_capacity": P["ccp_ambulance_casualty_capacity"],
        "hospital_ambulance_casualty_capacity": P["hospital_ambulance_casualty_capacity"],
        "ccp_physical_capacity_by_severity": {"minor": 8.0, "moderate": 3.0, "severe": 2.0},
        "treatment_duration_by_severity": P["treatment_duration_by_severity"],
        "staff_treatment_rate_by_severity": P["staff_treatment_rate_by_severity"],
        "supply_consumption_by_severity": P["supply_consumption_by_severity"],
        "disaster_area_remaining_penalty_by_severity":
            P["disaster_area_remaining_penalty_by_severity"],
        "ccp_waiting_penalty_by_severity": P["ccp_waiting_penalty_by_severity"],
    }
    demand, r_ij, r_jh, hcap = {}, {}, {}, {}
    for s in S:
        demand[s] = {t: {i: {l: rng.uniform(1, 5) * config.SEVERITY_PROBABILITY[l]
                             for l in L} for i in I} for t in T}
        r_ij[s] = {i: {j: {t: min(1.0, rng.uniform(0, .4) + .07 * k)
                           for k, t in enumerate(T)} for j in J} for i in I}
        r_jh[s] = {j: {h: {t: min(1.0, rng.uniform(0, .4) + .07 * k)
                           for k, t in enumerate(T)} for h in H} for j in J}
        # 醫院收治量刻意壓到 η·b_h = 6 附近，讓 VI-3 的 min 真的會綁到；
        # 否則該條在此 instance 上數學無效，只是刪掉冗餘的 (26)。
        hcap[s] = {h: {t: rng.uniform(3.0, 7.0) * (0.9 ** k) for k, t in enumerate(T)}
                   for h in H}
    return {
        "sets": {"I": I, "J": J, "H": H, "L": L, "L_transfer": L_tr, "T": T, "S": S},
        "deterministic_parameters": params,
        "scenario_data": {"probability": {s: 1.0 / len(S) for s in S},
                          "demand": demand, "road_availability_ij": r_ij,
                          "road_availability_jh": r_jh,
                          "hospital_receiving_capacity": hcap},
        "road_capacity": {"cap_ij": {i: {j: 80.0 for j in J} for i in I},
                          "cap_jh": {j: {h: 80.0 for h in H} for j in J}},
        "transport_cost": {"cost_ij": {i: {j: 100.0 + rng.uniform(0, 400) for j in J}
                                       for i in I},
                           "cost_jh": {j: {h: 100.0 + rng.uniform(0, 400) for h in H}
                                       for j in J}},
        "_label": f"tiny (|I|={n_i} |J|={n_j} |H|={n_h} |T|={n_t} |S|={n_s})",
    }


def real_instance(scale, n_scen=None):
    """真實台北 instance（讀 data/ 下的 CSV），可只取前 n_scen 個情境。"""
    inst = config.generate_data(scale=scale)
    st = inst["sets"]
    if n_scen is not None and n_scen < len(st["S"]):
        keep = st["S"][:n_scen]
        st["S"] = keep
        sd = inst["scenario_data"]
        for key in ("demand", "road_availability_ij", "road_availability_jh",
                    "hospital_receiving_capacity"):
            sd[key] = {s: sd[key][s] for s in keep}
        raw = {s: sd["probability"][s] for s in keep}
        tot = sum(raw.values())
        sd["probability"] = {s: p / tot for s, p in raw.items()}
    inst["_label"] = (f"{scale} (|I|={len(st['I'])} |J|={len(st['J'])} "
                      f"|H|={len(st['H'])} |T|={len(st['T'])} |S|={len(st['S'])})")
    return inst


# ===================================================================== #
# 隨機第一階段可行解                                                      #
# ===================================================================== #
def random_feasible_fs(inst, rng):
    """隨機抽一個滿足式 (2)–(9) 的 (X, V, U, Y)。"""
    d = vir.unpack(inst)
    J, H = d["J"], d["H"]
    p = d["p"]
    X = {j: (1 if rng.random() < 0.6 else 0) for j in J}
    if not any(X.values()):
        X[rng.choice(J)] = 1

    def alloc(pool, ub_key):
        left = int(pool)
        out = {}
        for j in J:
            cap = int(vir._ix(p[ub_key], j)) * X[j]
            out[j] = rng.randint(0, min(cap, left)) if (cap and left > 0) else 0
            left -= out[j]
        return out

    V = alloc(p["total_available_staff"], "ccp_staff_upper_bound")
    U = alloc(p["total_available_ccp_ambulances"], "ccp_ambulance_upper_bound")
    Y = {(h, j): 0 for h in H for j in J}
    for h in H:
        left = int(vir._ix(p["hospital_supply_upper_bound"], h))
        for j in J:
            if not X[j]:
                continue
            room = int(vir._ix(p["ccp_supply_upper_bound"], j)) - sum(Y[(hh, j)] for hh in H)
            take = rng.randint(0, max(0, min(room, left)))
            Y[(h, j)] = take
            left -= take
    return {"X": X, "V": V, "U": U, "Y": Y}


def zero_fs(inst):
    d = vir.unpack(inst)
    return {"X": {j: 0 for j in d["J"]}, "V": {j: 0 for j in d["J"]},
            "U": {j: 0 for j in d["J"]},
            "Y": {(h, j): 0 for h in d["H"] for j in d["J"]}}


# ===================================================================== #
# 關卡一                                                                 #
# ===================================================================== #
def gate1(inst, out, time_limit, env):
    out("")
    out("-" * 100)
    out(" 關卡一 · 最佳值一致（extensive form；抓 EXACT 與 OPT 切掉最佳解的錯誤）")
    out("-" * 100)

    def solve(vis, label, use_project_vi=False):
        t0 = time.time()
        m = None
        try:
            m, v, touched = vir.build_extensive(
                inst, vis, time_limit=time_limit, mip_gap=0.0, env=env,
                name=label, use_project_vi=use_project_vi)
            m.optimize()
            st = m.status
            has = m.SolCount > 0
            obj = m.ObjVal if has else float("nan")
            d = vir.unpack(inst)
            fs = flows = None
            # 只有真正達到最佳的解才拿去做關卡三 —— 超時的 incumbent 不是最佳解，
            # 拿它去檢查 OPT 型的式子會得到毫無意義的 PASS 或冤枉的 FAIL。
            if has and st == GRB.OPTIMAL:
                fs = {"X": {j: round(v["X"][j].X) for j in d["J"]},
                      "V": {j: round(v["V"][j].X) for j in d["J"]},
                      "U": {j: round(v["U"][j].X) for j in d["J"]},
                      "Y": {(h, j): round(v["Y"][h, j].X) for h in d["H"] for j in d["J"]}}
                flows = {"FI": {k: var.X for k, var in v["FI"].items()},
                         "FO": {k: var.X for k, var in v["FO"].items()}}
            return dict(obj=obj, nv=m.NumVars, nc=m.NumConstrs, status=st,
                        touched=touched, secs=time.time() - t0, fs=fs, flows=flows)
        finally:
            if m is not None:
                m.dispose()

    base = solve((), "base")
    if base["status"] != GRB.OPTIMAL:
        out(f"  基準解未達最佳（status={sname(base['status'])}）。")
        if base["status"] in FATAL_STATUS:
            out("  原始模型本身就無解 —— 這不是 VI 的問題，請先檢查 instance 與參數。")
        else:
            out("  請放寬 --time-limit，或改用較小的 instance。")
        return {vid: "INCONCLUSIVE" for vid in vir.MODEL_VIS}, base, {}, None, None

    out(f"  {'配置':<24}{'ObjVal':>20}{'|Δ|':>12}{'相對Δ':>11}"
        f"{'vars':>8}{'constrs':>9}{'收緊':>6}{'新增':>6}{'刪除':>6}{'秒':>7}  判定")
    out(f"  {'無 VI（基準）':<22}{base['obj']:>20,.6f}{'—':>12}{'—':>11}"
        f"{base['nv']:>8}{base['nc']:>9}{'—':>6}{'—':>6}{'—':>6}{base['secs']:>7.1f}  —")

    verdict, detail = {}, {}
    combo = project = None
    cases = [((vid,), vid, False) for vid in vir.MODEL_VIS]
    cases.append((tuple(vir.MODEL_VIS), "VI-1..VI-5 全開", False))
    # 最後一列改由 model core 依 config.VI_* 自己加 VI，本模組一條都不套。
    # 這一列比對的是「參考實作」與「專案實作」是否等價 —— 兩份獨立寫成的
    # 程式若給出同一個最佳值與同一組限制式數，才算真的實作對了。
    cases.append(((), "config 實作（專案程式）", True))
    for vis, label, use_proj in cases:
        r = solve(vis, label.replace(" ", "_"), use_project_vi=use_proj)
        tc = r["touched"]
        effective = tc["changed"] + tc["added"]
        if r["status"] in FATAL_STATUS:
            # 加了 VI 之後模型無解 —— 這條把可行解全切光了，是決定性的錯誤，
            # 絕不能當成「求解器沒跑完」放過去。
            mark, res = f"**FAIL**({sname(r['status'])})", "FAIL"
            dab = drel = float("nan")
        elif r["status"] != GRB.OPTIMAL:
            mark, res = f"INCONCLUSIVE({sname(r['status'])})", "INCONCLUSIVE"
            dab = drel = float("nan")
        else:
            dab = abs(r["obj"] - base["obj"])
            drel = dab / max(1.0, abs(base["obj"]))
            if violated(drel, REL_TOL_GATE1):
                mark, res = "**FAIL**", "FAIL"
            elif effective == 0 and not use_proj:
                # 目標值一樣，但這條在本 instance 上一條限制式都沒收緊／沒新增，
                # 等於什麼都沒驗到。報 PASS 會給人錯誤的安全感。
                mark, res = "VACUOUS", "VACUOUS"
            else:
                mark, res = "PASS", "PASS"
        out(f"  {label:<24}{r['obj']:>20,.6f}{dab:>12.2e}{drel:>11.2e}"
            f"{r['nv']:>8}{r['nc']:>9}{tc['changed']:>6}{tc['added']:>6}"
            f"{tc['removed']:>6}{r['secs']:>7.1f}  {mark}")
        rec = dict(obj=r["obj"], abs_delta=dab, rel_delta=drel, touched=tc,
                   vars=r["nv"], constrs=r["nc"], status=sname(r["status"]), result=res)
        if use_proj:
            # 專案實作自己加 VI，touched 一律為 0，VACUOUS 的判定不適用
            res = "FAIL" if res == "FAIL" else ("PASS" if r["status"] == GRB.OPTIMAL
                                                else "INCONCLUSIVE")
            project = res
            detail["PROJECT"] = rec
        elif len(vis) == 1:
            verdict[vis[0]] = res
            detail[vis[0]] = rec
        else:
            combo = res
            detail["COMBO"] = rec
    out("")
    out("  「收緊／新增／刪除」＝該 VI 實際改動的限制式條數。收緊＋新增為 0 時判 VACUOUS：")
    out("  目標值雖然一樣，但這條在本 instance 上根本沒作用，通過與否沒有資訊。")
    out("  「五條全開」用來抓 VI 之間互相干擾才出現的錯誤，它失敗會讓整份驗證失敗。")
    out("  最後一列「config 實作」是 model core 依 config.VI_* 自己加的 VI（本驗證程式")
    out("  一條都沒套）。它與「五條全開」的目標值必須一致 —— 兩份獨立實作互相對照。")
    return verdict, base, detail, combo, project


# ===================================================================== #
# 關卡二                                                                 #
# ===================================================================== #
def gate2(inst, out, n_samples, seed, env, sub_time_limit):
    out("")
    out("-" * 100)
    out(" 關卡二 · 隨機解逐條檢查（RELAX 的下界、OPT 的上界、EXACT 的收緊式）")
    out("-" * 100)

    d = vir.unpack(inst)
    rng = random.Random(seed)
    samples = [("全零解", zero_fs(inst)), ("x̄（逐分量上界）", vir.x_bar(inst))]
    samples += [(f"隨機 #{k + 1}", random_feasible_fs(inst, rng)) for k in range(n_samples)]

    keys = ["VI-1", "VI-2", "VI-3", "VI-6", "VI-7", "VI-8"]
    stat = {k: dict(n=0, bad=0, maxv=0.0, minslack=float("inf"), where="", agg=None)
            for k in keys}

    # 兩個常數界，求解前算一次
    try:
        q_lo = {s: vir.bound_vi6(inst, s, env=env, time_limit=sub_time_limit)
                for s in d["S"]}
    except SolveFailed as exc:
        out(f"  無法計算 q̲_s（VI-6）：{exc}")
        out("  本關無法進行。請放寬 --sub-time-limit，或改用較小的 instance。")
        return {k: "NO DATA" for k in keys}, {}
    q_hi = {s: vir.bound_vi7(inst, s) for s in d["S"]}
    if any(math.isnan(q_lo[s]) or math.isnan(q_hi[s]) for s in d["S"]):
        out("  q̲_s 或 q̄_s 算出 NaN —— instance 資料中可能有缺值，本關無法判定。")
        return {k: "NO DATA" for k in keys}, {}
    out("  q̲_s（VI-6）= " + ", ".join(f"{s}:{q_lo[s]:,.2f}" for s in d["S"]))
    out("  q̄_s（VI-7）= " + ", ".join(f"{s}:{q_hi[s]:,.2f}" for s in d["S"]))
    out("")

    n_skip_Q = n_skip_agg = 0
    skip_reasons = {}

    def note(key, viol, tol, slack, where):
        st = stat[key]
        st["n"] += 1
        if violated(viol, tol):
            st["bad"] += 1
            if not (viol <= st["maxv"]):          # NaN 安全
                st["maxv"], st["where"] = viol, where
        if slack is not None and slack < st["minslack"]:
            st["minslack"] = slack

    for name, x in samples:
        relax = name.startswith("x̄")
        for s in d["S"]:
            try:
                q, flows = vir.true_Q(inst, x, s, env=env, relax_first_stage=relax,
                                      return_flows=True, time_limit=sub_time_limit)
            except SolveFailed as exc:
                n_skip_Q += 1
                key = sname(exc.status)
                skip_reasons[key] = skip_reasons.get(key, 0) + 1
                continue

            ctol = COST_TOL_ABS + COST_TOL_REL * max(1.0, abs(q))

            # ---- EXACT 三條：在真實的第二階段最佳解上檢查收緊後的限制式 ----
            for key, fn in (("VI-1", vir.check_vi1_on), ("VI-2", vir.check_vi2_on),
                            ("VI-3", vir.check_vi3_on)):
                bad, sl = fn(inst, x, flows, scenarios=[s])
                if bad:
                    worst_row = max(bad, key=lambda b: b[1])
                    note(key, worst_row[1], FLOW_TOL, None, f"{name}/{worst_row[0]}")
                else:
                    note(key, 0.0, FLOW_TOL, sl if sl != float("inf") else None, "")

            # ---- VI-6：q̲_s ≤ Q(x; ω^s)　---- VI-7：Q(x; ω^s) ≤ q̄_s ----
            note("VI-6", q_lo[s] - q, ctol, q - q_lo[s], f"{name}/{s}")
            note("VI-7", q - q_hi[s], ctol, q_hi[s] - q, f"{name}/{s}")

            # ---- VI-8：彙總鬆弛 LP 的最佳值 ≤ Q(x; ω^s) ----
            try:
                val, nv, nc = vir.bound_vi8(inst, x, s, env=env,
                                            time_limit=sub_time_limit)
            except SolveFailed:
                n_skip_agg += 1
                continue
            stat["VI-8"]["agg"] = (nv, nc)
            note("VI-8", val - q, ctol, q - val, f"{name}/{s}")

    planned = len(samples) * len(d["S"])
    out(f"  樣本：{len(samples)} 個一階解 × {len(d['S'])} 情境 = {planned} 組"
        f"（其中 2 個為指定解：全零解與 x̄）")
    if n_skip_Q or n_skip_agg:
        txt = "、".join(f"{k}×{v}" for k, v in skip_reasons.items()) or "—"
        out(f"  略過：子問題 {n_skip_Q} 組（狀態 {txt}）、彙總 LP {n_skip_agg} 組。")
    out("")
    out(f"  {'編號':<7}{'名稱':<22}{'檢查數':>7}{'違反數':>7}{'最大違反':>12}"
        f"{'最小鬆弛':>14}  判定")
    verdict, detail = {}, {}
    for k in keys:
        st = stat[k]
        meta = next(m for m in vir.VI_META if m["id"] == k)
        if st["n"] == 0:
            res, mark = "NO DATA", "NO DATA"
        elif st["bad"]:
            res, mark = "FAIL", "**FAIL**"
        elif st["n"] < planned * 0.5:
            # 一半以上的樣本都沒跑成，剩下的通過不足以背書
            res, mark = "INCONCLUSIVE", "INCONCLUSIVE"
        else:
            res, mark = "PASS", "PASS"
        ms = "—" if st["minslack"] == float("inf") else f"{st['minslack']:,.4g}"
        out(f"  {k:<7}{meta['name']:<22}{st['n']:>7}{st['bad']:>7}"
            f"{st['maxv']:>12.2e}{ms:>14}  {mark}")
        if st["bad"]:
            out(f"          最大違反出現在：{st['where']}")
        verdict[k] = res
        detail[k] = dict(checks=st["n"], planned=planned, violations=st["bad"],
                         max_violation=st["maxv"],
                         min_slack=None if st["minslack"] == float("inf") else st["minslack"],
                         worst_at=st["where"], result=res)
    if stat["VI-8"]["agg"]:
        nv, nc = stat["VI-8"]["agg"]
        out("")
        out(f"  VI-8 彙總 LP 的規模：每情境 {nv} 個變數 / {nc} 條限制式"
            f"（原第二階段的 FI 單獨就有 "
            f"{len(d['I']) * len(d['J']) * len(d['L']) * len(d['T'])} 個變數）")
    out("")
    out("  「最小鬆弛」＝所有樣本中「右手邊 − 左手邊」的最小值（已排除 X_j = 0 的恆零列）。")
    out("  接近 0 表示這條在某個樣本上真的綁到了；數值很大表示它從未接近綁定，")
    out("  通過的資訊量有限。負值需在容差內，僅為浮點誤差。")
    out("  注意 VI-6 在 x̄、VI-7 與 VI-8 在全零解上本來就相等，那幾個 0 是設計使然。")
    return verdict, detail


# ===================================================================== #
# 關卡三                                                                 #
# ===================================================================== #
def gate3(inst, out, base, env, sub_time_limit):
    out("")
    out("-" * 100)
    out(" 關卡三 · 最佳解代回（把關卡一的最佳解代進所有 VI）")
    out("-" * 100)
    if base is None or base.get("fs") is None:
        out("  關卡一未取得「已證明為最佳」的解（超時的 incumbent 不算），本關略過。")
        return {}, {}

    x, flows = base["fs"], base["flows"]
    d = vir.unpack(inst)
    p = d["p"]

    # OPT 型只保證「存在一個最佳解滿足此式」。只有在成本係數嚴格為正時，
    # 交換論證才強到「每一個最佳解都滿足」，違反才構成 FAIL；否則求解器
    # 回傳另一個等值最佳解就會冤枉一條正確的式子。
    cv_pos = p["staff_unit_assignment_cost"] > 0
    f_pos = min(vir._ix(p["ccp_fixed_opening_cost"], j) for j in d["J"]) > 0

    rows = [
        ("VI-1", vir.check_vi1_on(inst, x, flows)[0], True, ""),
        ("VI-2", vir.check_vi2_on(inst, x, flows)[0], True, ""),
        ("VI-3", vir.check_vi3_on(inst, x, flows)[0], True, ""),
        ("VI-4", vir.check_vi4_on(inst, x), cv_pos, "" if cv_pos else "cv = 0，僅供參考"),
        ("VI-5", vir.check_vi5_on(inst, x), f_pos, "" if f_pos else "f_j = 0，僅供參考"),
    ]
    try:
        bad7 = []
        for s in d["S"]:
            q = vir.true_Q(inst, x, s, env=env, time_limit=sub_time_limit)
            hi = vir.bound_vi7(inst, s)
            if violated(q - hi, COST_TOL_ABS + COST_TOL_REL * max(1.0, abs(q))):
                bad7.append((s, q - hi))
        rows.append(("VI-7", bad7, True, ""))
    except SolveFailed as exc:
        out(f"  VI-7 的 Q(x*; ω^s) 求解失敗（{exc}），該條本關不判定。")

    out(f"  最佳解：ΣX={sum(x['X'].values())}　ΣV={sum(x['V'].values())}"
        f"　ΣU={sum(x['U'].values())}　ΣY={sum(x['Y'].values())}")
    out("")
    out(f"  {'編號':<7}{'名稱':<22}{'違反數':>7}{'最大違反':>12}  判定")
    verdict, detail = {}, {}
    for k, bad, hard, note_txt in rows:
        meta = next(m for m in vir.VI_META if m["id"] == k)
        worst = max((b[1] for b in bad), default=0.0)
        if not bad:
            res, mark = "PASS", "PASS"
        elif hard:
            res, mark = "FAIL", "**FAIL**"
        else:
            res, mark = "INCONCLUSIVE", f"參考（{note_txt}）"
        out(f"  {k:<7}{meta['name']:<22}{len(bad):>7}{worst:>12.2e}  {mark}")
        if bad:
            for w in bad[:3]:
                out(f"          {w[0]}　超出 {w[1]:.6g}")
        verdict[k] = res
        detail[k] = dict(violations=len(bad), max_violation=worst,
                         hard=hard, note=note_txt, result=res)
    out("")
    out("  OPT 型（VI-4、VI-5）只保證「存在一個最佳解滿足此式」。本關把它當硬性判定，")
    out(f"  前提是相關成本係數嚴格為正（cv > 0：{cv_pos}；f_j > 0：{f_pos}），")
    out("  此時交換論證強到「每一個最佳解都滿足」。前提不成立時只列為參考、不判 FAIL。")
    return verdict, detail


# ===================================================================== #
# 反向對照                                                               #
# ===================================================================== #
def self_test(inst, out, env, time_limit, sub_time_limit, seed):
    """把每一條 VI 各故意寫錯一次，確認驗證程式真的會判 FAIL。

    驗證程式全綠有一個致命的可能 —— 它根本沒在檢查任何東西。唯一能排除這點的
    辦法，是先讓它去驗一個已知是錯的版本。八條都要測：只測其中三條，等於只
    證明了那三條的檢查路徑有效。
    """
    out("")
    out("=" * 100)
    out(" 反向對照（negative control）· 每條各故意寫錯一次，確認驗證程式抓得到")
    out("=" * 100)
    out(f" {'編號':<7}{'故意寫錯的內容':<40}{'應由哪一關抓到':<12}{'實際':<22}判定")
    caught = 0
    rows = {}
    for vid, (sab, gate, desc) in vir.SABOTAGE_CASES.items():
        vir.SABOTAGE = dict(sab)
        try:
            if gate == 1:
                v, _b, _d, _c, _p = gate1(inst, Quiet(), time_limit, env)
            else:
                v, _d = gate2(inst, Quiet(), 4, seed, env, sub_time_limit)
            got = v.get(vid, "NO DATA")
        except Exception as exc:
            got = f"ERROR({type(exc).__name__})"
        finally:
            vir.SABOTAGE = {}
        # 只有明確判成 FAIL 才算抓到。ERROR、INCONCLUSIVE、VACUOUS 都是
        # 「驗證程式沒能給出判定」，不能拿來證明它有效。
        ok = (got == "FAIL")
        caught += ok
        rows[vid] = dict(sabotage=desc, gate=gate, got=got, caught=bool(ok))
        out(f" {vid:<7}{desc:<40}{'關卡' + str(gate):<12}{got:<22}"
            f"{'抓到' if ok else '**沒抓到**'}")
    out("-" * 100)
    n = len(vir.SABOTAGE_CASES)
    if caught == n:
        out(f" {caught}/{n} 條的故意錯誤都被判成 FAIL —— 八條的檢查路徑都有效，")
        out(" 正式結果的全綠不是因為驗證程式什麼都沒檢查。")
    else:
        miss = [k for k, r in rows.items() if not r["caught"]]
        out(f" 只抓到 {caught}/{n} —— {'、'.join(miss)} 的檢查有盲點，"
            f"這幾條的正式結果不可採信。")
    return caught == n, rows


# ===================================================================== #
# main                                                                  #
# ===================================================================== #
def _sanitize(obj):
    """把 NaN / inf 換成 None，否則寫出來的 JSON 嚴格解析器讀不了。"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _write_report(args, inst, out, gates, summary, d1, d2, d3, st_rows, code):
    """報告一定要落地。寫檔失敗不能反過來炸掉整份已經跑完的驗證。"""
    try:
        rep = Path(args.report) if args.report else (
            Path(__file__).resolve().parent / "vi_validation_report.txt")
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(out.text(), encoding="utf-8")
        # --report x.json 時 with_suffix(".json") 會蓋掉剛寫好的文字報告
        js = (rep.with_suffix(".meta.json") if rep.suffix.lower() == ".json"
              else rep.with_suffix(".json"))
        js.write_text(json.dumps(_sanitize(
            {"timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
             "instance": inst["_label"], "seed": args.seed,
             "gates_run": sorted(gates), "samples": args.samples,
             "exit_code": code, "summary": summary,
             "gate1": d1, "gate2": d2, "gate3": d3, "self_test": st_rows}),
            ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"\n報告已寫入：\n  {rep}\n  {js}")
    except (OSError, ValueError) as exc:
        print(f"\n[警告] 報告寫檔失敗（{exc}）。驗證結果如上，exit code = {code}。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="有效不等式正確性驗證（八條、三關）")
    ap.add_argument("--instance", default="tiny",
                    choices=["tiny", "small", "medium", "large", "full"],
                    help="tiny＝自足小例（預設，最快）；其餘為真實台北 instance")
    ap.add_argument("--gates", default="1,2,3", help="要跑的關卡，如 --gates 2 或 1,3")
    ap.add_argument("--samples", type=int, default=40, help="關卡二的隨機解個數（≥ 0）")
    ap.add_argument("--scenarios", type=int, default=None, help="只取前 N 個情境（≥ 1）")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--time-limit", type=float, default=600.0,
                    help="關卡一每次 MIP 求解的時限（秒）")
    ap.add_argument("--sub-time-limit", type=float, default=300.0,
                    help="關卡二／三每次子問題與彙總 LP 的時限（秒）")
    ap.add_argument("--report", default=None, help="報告檔路徑（預設寫進 tests/）")
    ap.add_argument("--self-test", action="store_true",
                    help="附帶跑反向對照：八條各故意寫錯一次，確認驗證程式抓得到")
    args = ap.parse_args(argv)

    # ---- 參數檢查：荒謬的輸入要當場擋掉，不能默默跑出一個空模型然後全部 PASS ----
    try:
        gates = {int(g) for g in args.gates.replace(" ", "").split(",") if g}
    except ValueError:
        ap.error(f"--gates 只能是以逗號分隔的整數，收到 {args.gates!r}")
    if not gates:
        ap.error("--gates 不能是空的")
    unknown = sorted(gates - {1, 2, 3})
    if unknown:
        ap.error(f"--gates 只有 1、2、3，收到 {unknown}")
    if args.samples < 0:
        ap.error(f"--samples 不能是負數，收到 {args.samples}")
    if args.scenarios is not None and args.scenarios < 1:
        ap.error(f"--scenarios 至少要 1，收到 {args.scenarios}")
    if args.time_limit <= 0 or args.sub_time_limit <= 0:
        ap.error("時限必須大於 0")

    out = Tee()
    if args.instance == "tiny":
        inst = tiny_instance(n_s=args.scenarios or 2, seed=args.seed)
    else:
        inst = real_instance(args.instance, args.scenarios)
    if not vir.unpack(inst)["S"]:
        ap.error("這個 instance 沒有任何情境，無法驗證")

    # Seed 固定，讓交替最佳解的選擇在同一台機器上可重現
    env = gp.Env(params={"OutputFlag": 0, "Seed": args.seed})
    try:
        return _run(args, inst, out, gates, env)
    finally:
        try:
            env.dispose()
        except Exception:
            pass


def _run(args, inst, out, gates, env):
    d = vir.unpack(inst)
    n2 = (len(d["I"]) * len(d["J"]) * len(d["L"]) * len(d["T"])
          + len(d["J"]) * len(d["H"]) * len(d["Ltr"]) * len(d["T"]))
    out("=" * 100)
    out(" 有效不等式正確性驗證　VI Validation")
    out("=" * 100)
    out(f" 時間      : {_dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    out(f" instance  : {inst['_label']}")
    out(f" gurobi    : {'.'.join(str(v) for v in gp.gurobi.version())}")
    out(f" seed      : {args.seed}　　關卡：{sorted(gates)}　　關卡二樣本數：{args.samples}")
    out(f" 時限      : 關卡一 {args.time_limit:g}s／次；關卡二、三 {args.sub_time_limit:g}s／次")
    out(f" 容差      : 關卡一 相對 {REL_TOL_GATE1:.0e}；成本量綱 {COST_TOL_ABS:.0e}"
        f"＋相對 {COST_TOL_REL:.0e}；人數量綱 {FLOW_TOL:.0e}")
    out(f" 模型規模  : 單情境第二階段主要變數約 {n2:,} 個")
    out(f" 規格書    : docs/有效不等式_實作規格.docx（編號與本程式一致）")
    if args.instance != "tiny" and 1 in gates:
        out(" 注意      : 真實 instance 的關卡一需把 MIP 解到 0% gap，可能很久；"
            "超時會判 INCONCLUSIVE。")

    t0 = time.time()
    v1 = v2 = v3 = {}
    d1 = d2 = d3 = {}
    base = combo = project = None
    gate1_ran = False
    st_ok, st_rows = None, {}
    try:
        if 1 in gates:
            v1, base, d1, combo, project = gate1(inst, out, args.time_limit, env)
            gate1_ran = True
        if 2 in gates:
            v2, d2 = gate2(inst, out, args.samples, args.seed, env, args.sub_time_limit)
        if 3 in gates:
            if base is None:
                out("")
                out(" 關卡三需要關卡一的最佳解，先補跑一次基準求解……")
                # 補跑的判定一併採納。之前把它丟掉，導致補跑印出的 FAIL 不會
                # 進入總判定，整份報告會在畫面上有 FAIL 的情況下說「全部通過」。
                v1, base, d1, combo, project = gate1(inst, out, args.time_limit, env)
                gate1_ran = True
                gates = gates | {1}
            v3, d3 = gate3(inst, out, base, env, args.sub_time_limit)
        if args.self_test:
            st_ok, st_rows = self_test(inst, out, env, args.time_limit,
                                       args.sub_time_limit, args.seed)
    except gp.GurobiError as exc:
        msg = str(exc)
        if "size-limited" in msg.lower() or "too large" in msg.lower():
            out("")
            out("!" * 100)
            out(" Gurobi 授權容量不足，本次無法完成驗證。")
            out(f" 訊息：{msg}")
            out("")
            out(" 這個 instance 的模型超過受限版授權（pip 安裝內附）能處理的大小。解法二選一：")
            out("   1. 改用 --instance tiny（預設值）—— 受限授權即可跑完整三關。")
            out("   2. 在有完整 Gurobi 授權的機器上跑真實 instance。")
            out("!" * 100)
            _write_report(args, inst, out, gates, {}, d1, d2, d3, st_rows, 2)
            return 2
        raise
    except SolveFailed as exc:
        out("")
        out("!" * 100)
        out(f" 子問題求解失敗，驗證中止：{exc}")
        out(" 請放寬 --sub-time-limit，或改用較小的 instance。")
        out("!" * 100)
        _write_report(args, inst, out, gates, {}, d1, d2, d3, st_rows, 1)
        return 1

    # ---------------- 總判定表 ----------------
    out("")
    out("=" * 100)
    out(" 總判定　（—＝該關卡不適用於這條；SKIP＝本次未跑）")
    out("=" * 100)
    out(f" {'編號':<7}{'名稱':<24}{'型別':<7}{'位置':<14}"
        f"{'關卡一':>16}{'關卡二':>14}{'關卡三':>14}   總判定")
    counts, summary = {}, {}
    for meta in vir.VI_META:
        k = meta["id"]
        cells = []
        for gi, vmap in ((1, v1), (2, v2), (3, v3)):
            if gi not in meta["gates"]:
                cells.append("—")
            elif gi not in gates:
                cells.append("SKIP")
            else:
                cells.append(vmap.get(k, "NO DATA"))
        run = [c for c in cells if c not in ("—", "SKIP")]
        if not run:
            overall = "未驗證"
        elif "FAIL" in run:
            overall = "**FAIL**"
        elif all(c == "PASS" for c in run):
            overall = "PASS"
        elif all(c in ("PASS", "VACUOUS") for c in run):
            overall = "VACUOUS"
        else:
            overall = "INCONCLUSIVE"
        counts[overall] = counts.get(overall, 0) + 1
        out(f" {k:<7}{meta['name']:<24}{meta['kind']:<7}{meta['stage']:<14}"
            f"{cells[0]:>16}{cells[1]:>14}{cells[2]:>14}   {overall}")
        summary[k] = dict(name=meta["name"], kind=meta["kind"], stage=meta["stage"],
                          gate1=cells[0], gate2=cells[1], gate3=cells[2],
                          overall=overall)
    if gate1_ran:
        cm = combo or "NO DATA"
        out(f" {'合併':<7}{'VI-1..VI-5 五條同時開啟':<24}{'—':<7}{'extensive':<14}"
            f"{cm:>16}{'—':>14}{'—':>14}   {'**FAIL**' if cm == 'FAIL' else cm}")
        summary["COMBO"] = dict(name="VI-1..VI-5 五條同時開啟", gate1=cm, overall=cm)
        pm = project or "NO DATA"
        out(f" {'實作':<7}{'config 實作（專案程式）':<24}{'—':<7}{'extensive':<14}"
            f"{pm:>16}{'—':>14}{'—':>14}   {'**FAIL**' if pm == 'FAIL' else pm}")
        summary["PROJECT"] = dict(name="config 實作（專案程式）", gate1=pm, overall=pm)
    out("-" * 100)
    total = len(vir.VI_META)
    n_pass = counts.get("PASS", 0)
    n_fail_vi = counts.get("**FAIL**", 0)
    n_fail = n_fail_vi + (1 if combo == "FAIL" else 0) + (1 if project == "FAIL" else 0)
    other = total - n_pass - n_fail_vi
    line = f" 通過 {n_pass} / {total} 條"
    if n_fail:
        line += f"　　失敗 {n_fail}"
    if other:
        line += f"　　未完整驗證 {other}"
    out(line + f"　　耗時 {time.time() - t0:.1f} 秒")
    out("=" * 100)

    all_green = (n_fail == 0 and n_pass == total)
    if st_ok is False:
        out(" 反向對照未全數抓到 —— 請先修好驗證程式，本次結果不可採信。")
    elif n_fail:
        out(" 有條目未通過 —— 該條在進入實作前必須先修正推導或實作。")
    elif all_green:
        out(" 全部通過，可以進入實作階段。" + ("（反向對照亦通過）" if st_ok else ""))
    else:
        out(" 尚有條目未完整驗證（SKIP / VACUOUS / INCONCLUSIVE），"
            "請補跑對應關卡或換一個會綁到的 instance。")

    code = 0 if (all_green and st_ok is not False) else 1
    _write_report(args, inst, out, gates, summary, d1, d2, d3, st_rows, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
