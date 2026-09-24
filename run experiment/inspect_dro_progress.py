#!/usr/bin/env python3
"""檢查 batch_dro_full_matrix 的所有進度檔各自完成到哪裡（唯讀，不會改任何東西）。

為什麼需要這支
--------------
batch_dro_full_matrix.py 的進度檔名稱會跟著 --tag 改變：
    無 tag        → DRO_full_matrix_raw.csv
    --tag S50     → DRO_full_matrix_raw_S50.csv
    --dry-run     → DRO_full_matrix_raw_DRYRUN.csv
續跑時它只讀「跟本次 tag 相同」的那一份。若上次跑用了 --tag、這次忘了加，
就會去讀另一份進度檔，於是出現「表格裡 large 是空的，程式卻說只剩 2 格要跑」
這種看起來很矛盾的狀況。

這支會把 experiment result/ 底下每一份進度檔都列出來，
讓你一眼看出「哪一份才是你要續跑的那一份」。

用法
----
    python "run experiment/inspect_dro_progress.py"
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT_DIR / "experiment result"

SCALES = ["small", "medium", "large"]
MODELS = ["dro_box", "dro_ellipsoidal", "dro_polyhedral"]
MODEL_LABEL = {"dro_box": "DRO-box", "dro_ellipsoidal": "DRO-ellipsoidal",
               "dro_polyhedral": "DRO-polyhedral"}
N_METHODS = 8

# 與 batch_dro_full_matrix.py 一致：這些狀態會被視為「已完成」而永久跳過
SUCCESS_STATUS = {"OPTIMAL", "TIME_LIMIT", "SUBOPTIMAL", "INTERRUPTED",
                  "NODE_LIMIT", "SOLUTION_LIMIT", "ITERATION_LIMIT"}


def load(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError as exc:
        print(f"    [!] 無法讀取：{exc}")
    return rows


def describe(path: Path) -> None:
    rows = load(path)
    print("=" * 96)
    print(f" 進度檔：{path.name}")
    try:
        size_kb = path.stat().st_size / 1024
        import datetime as _dt
        mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime)
        print(f" 大小 {size_kb:,.0f} KB　最後修改 {mtime:%Y-%m-%d %H:%M:%S}")
    except OSError:
        pass
    print("=" * 96)
    if not rows:
        print("  （空檔或讀不到內容）\n")
        return

    # (scale, model) -> 已完成的 method_id 集合 / 狀態統計
    done = defaultdict(set)
    no_ub = defaultdict(set)
    status_count = defaultdict(int)
    by_cell = {}
    for r in rows:
        sc, md = r.get("scale"), r.get("model")
        try:
            mid = int(float(r.get("method_id")))
        except (TypeError, ValueError):
            continue
        st = (r.get("status") or "").strip()
        status_count[st or "(空白)"] += 1
        by_cell[(sc, md, mid)] = r
        if st in SUCCESS_STATUS:
            done[(sc, md)].add(mid)
            if not (r.get("UB") or "").strip():
                no_ub[(sc, md)].add(mid)

    total_done = sum(len(v) for v in done.values())
    print(f"  總列數 {len(rows)}　　被視為已完成（會跳過）{total_done} / "
          f"{len(SCALES) * len(MODELS) * N_METHODS}")
    print()
    # 第一段：完成數一覽（數字對齊，好掃）
    header = f"  {'scale':10}" + "".join(f"{MODEL_LABEL[m]:>18}" for m in MODELS)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for sc in SCALES:
        line = f"  {sc:10}"
        for md in MODELS:
            line += f"{f'{len(done[(sc, md)])}/{N_METHODS}':>18}"
        print(line)
    print()

    # 第二段：還缺哪些方法（獨立列出，避免擠在表格裡看不清楚）
    gaps = []
    for sc in SCALES:
        for md in MODELS:
            missing = sorted(set(range(1, N_METHODS + 1)) - done[(sc, md)])
            if missing:
                gaps.append((sc, md, missing))
    if gaps:
        print("  尚未完成的格子：")
        for sc, md, missing in gaps:
            print(f"    {sc:8} {MODEL_LABEL[md]:18} 缺方法 "
                  f"{','.join(map(str, missing))}　（{len(missing)} 格）")
    else:
        print("  ✅ 全部 72 格都已完成")
    print()

    # 已完成但沒有 UB 的格子（跑滿時限卻沒找到可行解）
    flagged = [(sc, md, sorted(v)) for (sc, md), v in no_ub.items() if v]
    if flagged:
        print("  已完成但「沒有找到可行解」的格子（表格裡 UB 欄會顯示狀態字串）：")
        for sc, md, mids in sorted(flagged):
            print(f"    {sc:8} {MODEL_LABEL[md]:18} 方法 {mids}")
        print()

    print("  狀態統計：", "　".join(f"{k}={v}" for k, v in sorted(status_count.items())))
    # INTERRUPTED 是陷阱：它算成功，會被永久跳過
    if status_count.get("INTERRUPTED"):
        print("  [!] 有 INTERRUPTED 狀態的格子。它被列在 SUCCESS_STATUS 裡，")
        print("      重跑時會被當成已完成而永久跳過。若那是你中途按 Ctrl+C 或")
        print("      當機造成的，請確認那格的數字是否可信。")
    print()


def main() -> int:
    if not RESULT_DIR.is_dir():
        print(f"找不到資料夾：{RESULT_DIR}")
        return 1
    files = sorted(RESULT_DIR.glob("DRO_full_matrix_raw*.csv"))
    files = [p for p in files if "_backup_" not in p.name]
    print()
    print("#" * 96)
    print(" batch_dro_full_matrix 進度檔總覽")
    print(f" 目錄：{RESULT_DIR}")
    print("#" * 96)
    if not files:
        print("\n  這個目錄底下沒有任何 DRO_full_matrix_raw*.csv 進度檔。")
        print("  → 你實際跑實驗的資料夾可能不是這一個，請確認路徑。\n")
        return 1
    print(f"\n 找到 {len(files)} 份進度檔：{', '.join(p.name for p in files)}\n")
    for p in files:
        describe(p)

    print("=" * 96)
    print(" 續跑提醒")
    print("=" * 96)
    print(" 進度檔名稱由 --tag 決定，續跑時 tag 必須跟上次完全一樣：")
    for p in files:
        stem = p.stem                      # DRO_full_matrix_raw[_TAG]
        tag = stem[len("DRO_full_matrix_raw"):].lstrip("_")
        cmd = 'python "run experiment/batch_dro_full_matrix.py"'
        if tag:
            cmd += f" --tag {tag}"
        print(f"   要續跑 {p.name}　→　{cmd}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
