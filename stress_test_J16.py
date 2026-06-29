#!/usr/bin/env python3
"""
stress_test_J16.py
==================
Stress Test：J=16 固定（全部 CCP 候選點），只縮放 I 和 H
  S = 5    (固定)
  T = 8    (固定)
  sample_ratio: 10% → 25% → 50% → 75% → 100%

早停條件：某一個規模的最終 Gap > 10%，後續更大的規模不再執行。
每跑完一個規模立即寫入 CSV，確保中途中斷也不會遺失結果。
"""

import csv
import datetime
import math
import os
import sys
import time

# ── 確保從腳本所在目錄執行 ───────────────────────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

# ── 實驗固定參數 ─────────────────────────────────────────────
TARGET_SCENARIOS  = 5
TARGET_PERIODS    = 8
SAMPLE_RATIOS     = [0.10, 0.25, 0.50, 0.75, 1.00]
GAP_STOP_PCT      = 10.0    # Gap 超過這個值就停
TIME_LIMIT        = 3600.0  # 每個規模最多 1 小時
MIP_GAP           = 0.01    # Gurobi 收斂門檻 1%

# ── import config 並驗證設定 ─────────────────────────────────
import config as cfg

if cfg.SCENARIOS != TARGET_SCENARIOS:
    print(f"[WARNING] config.SCENARIOS={cfg.SCENARIOS}，本腳本需要 {TARGET_SCENARIOS}，已強制覆寫。")
    cfg.SCENARIOS = TARGET_SCENARIOS

if cfg.TIME_PERIODS != TARGET_PERIODS:
    print(f"[WARNING] config.TIME_PERIODS={cfg.TIME_PERIODS}，本腳本需要 {TARGET_PERIODS}，已強制覆寫。")
    cfg.TIME_PERIODS = TARGET_PERIODS

import sp_model as sp

# ── 取得全集合大小 ───────────────────────────────────────────
def _csv_row_count(filepath):
    with open(filepath, encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in f) - 1  # 扣掉 header

full_I = _csv_row_count(f"data/{cfg.DISASTER_CSV}")
full_H = _csv_row_count(f"data/{cfg.HOSPITAL_CSV}")
full_J = _csv_row_count(f"data/{cfg.CCP_CSV}")   # 固定，不抽樣

# ── 輸出 CSV 路徑 ────────────────────────────────────────────
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path  = f"stress_test_J16_{timestamp}.csv"
FIELDNAMES = [
    "test_id", "sample_ratio_pct",
    "I", "J", "H", "S", "T",
    "obj_value", "best_lb", "best_ub",
    "cpu_s", "gap_pct",
    "vss_pct", "evpi_pct",
    "note",
]

results = []

def save_csv():
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)


# ── 開始執行 ─────────────────────────────────────────────────
print("=" * 65)
print("STRESS TEST  ─  J=16 固定，只縮放 I 和 H")
print(f"Start : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
print(f"Config: S={cfg.SCENARIOS}, T={cfg.TIME_PERIODS}, "
      f"time_limit={TIME_LIMIT:.0f}s, mip_gap={MIP_GAP*100:.0f}%")
print(f"Full scale: I={full_I}, J={full_J}, H={full_H}")
print(f"Early-stop: Gap > {GAP_STOP_PCT}%")
print("=" * 65)

for run_idx, ratio in enumerate(SAMPLE_RATIOS, start=1):
    I_n     = max(1, math.ceil(full_I * ratio))
    H_n     = max(1, math.ceil(full_H * ratio))
    pct_str = f"{ratio * 100:.0f}%"
    test_id = f"ST{int(ratio * 100):03d}"

    print(f"\n[{run_idx}/{len(SAMPLE_RATIOS)}]  {test_id}  ratio={pct_str}  "
          f"I={I_n}, J={full_J}, H={H_n}  "
          f"─  {datetime.datetime.now():%H:%M:%S}")

    row = {k: "—" for k in FIELDNAMES}
    row.update({
        "test_id":          test_id,
        "sample_ratio_pct": pct_str,
        "I": I_n, "J": full_J, "H": H_n,
        "S": cfg.SCENARIOS, "T": cfg.TIME_PERIODS,
        "note": "",
    })

    t0 = time.time()
    try:
        model, summary = sp.run_sp_model(
            scenario_size=cfg.SCENARIOS,
            sample_ratio=ratio,
            time_limit=TIME_LIMIT,
            mip_gap=MIP_GAP,
        )
    except Exception as exc:
        row["cpu_s"] = f"{time.time() - t0:.1f}"
        row["note"]  = f"ERROR: {exc}"
        results.append(row)
        save_csv()
        print(f"  ✗ ERROR: {exc}  →  stopping.")
        break

    cpu = time.time() - t0
    row["cpu_s"] = f"{cpu:.1f}"

    # ── 無可行解 ────────────────────────────────────────────
    if model is None:
        row["note"] = "INFEASIBLE / no solution"
        results.append(row)
        save_csv()
        print("  ✗ INFEASIBLE – stopping.")
        break

    # ── 讀取求解結果 ─────────────────────────────────────────
    gap_pct = model.MIPGap * 100
    row["gap_pct"]   = f"{gap_pct:.4f}"
    row["best_ub"]   = f"{model.ObjVal:.2f}"
    row["best_lb"]   = f"{model.ObjBound:.2f}"
    row["obj_value"] = row["best_ub"]

    if summary is not None:
        vss  = summary.get("VSS_pct")
        evpi = summary.get("EVPI_pct")
        row["vss_pct"]  = f"{vss:.4f}"  if vss  is not None else "—"
        row["evpi_pct"] = f"{evpi:.4f}" if evpi is not None else "—"

    stop = gap_pct > GAP_STOP_PCT
    if stop:
        row["note"] = f"STOP – gap {gap_pct:.2f}% > {GAP_STOP_PCT:.0f}%"

    results.append(row)
    save_csv()

    status_mark = "✗ GAP TOO LARGE" if stop else "✓"
    print(f"  {status_mark}  CPU={cpu:.1f}s  "
          f"Gap={gap_pct:.2f}%  UB={model.ObjVal:.2f}  "
          f"VSS={row['vss_pct']}%  EVPI={row['evpi_pct']}%")

    if stop:
        remaining = [f"{r*100:.0f}%" for r in SAMPLE_RATIOS[run_idx:]]
        if remaining:
            print(f"  → Skipping: {', '.join(remaining)}")
        break


# ── 最終摘要 ─────────────────────────────────────────────────
print("\n" + "=" * 65)
print("SUMMARY")
hdr = f"{'ID':>7} | {'Ratio':>5} | {'I':>4} {'H':>3} | {'CPU(s)':>7} | {'Gap%':>7} | {'VSS%':>7} | {'EVPI%':>7} | Note"
print(hdr)
print("-" * len(hdr))
for r in results:
    print(f"{r['test_id']:>7} | {r['sample_ratio_pct']:>5} | "
          f"{str(r['I']):>4} {str(r['H']):>3} | "
          f"{r['cpu_s']:>7} | {r['gap_pct']:>7} | "
          f"{r['vss_pct']:>7} | {r['evpi_pct']:>7} | {r['note']}")

print("=" * 65)
print(f"Results → {csv_path}")
print(f"End   : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
