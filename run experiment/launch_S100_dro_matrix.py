"""launch_S100_dro_matrix.py — S=100 的 DRO 全矩陣總管（batch_dro_full_matrix 的外殼）

這支程式「不碰任何求解邏輯」，它只負責把 batch_dro_full_matrix.py 用正確的參數、
正確的順序、正確的容錯方式叫起來。所有模型、切割、加速階梯都原封不動，
跟 S=50 那一輪逐字相同，只有情境數從 50 換成 100 —— 兩份結果才能並排比較。

為什麼要多一層外殼
------------------
1. **一個規模開一個行程。**
   S=100 的 large instance 加上 Gurobi 的整體式模型，記憶體是 S=50 的兩倍以上。
   若三個規模在同一個 Python 行程裡連跑，前一個規模留下的模型、instance 快取、
   Gurobi 內部配置不一定會完全還給作業系統，等輪到 large 時可用記憶體已經被吃掉。
   每個規模獨立開行程、跑完就整個結束，記憶體一定乾淨。

2. **半夜掛掉會自己爬起來。**
   batch_dro_full_matrix.py 本身已經能續跑（每跑完一格立刻寫進度檔），但前提是
   有人回來按下執行。S=100 這一輪預估數天，電腦當機、Gurobi 段錯誤、Windows
   自動重開機都可能發生在沒人看著的時候。這支外殼會偵測到子行程異常結束，
   自動重新叫起來，已完成的格子會被跳過。

3. **完整的執行紀錄。**
   子行程的輸出同時印到畫面並寫進 experiment result/log/S100_<時間>.log。

執行
----
    # 標準用法：72 格全跑，2 小時時限，續跑
    python "run experiment/launch_S100_dro_matrix.py"

    # 先驗流程不求解（幾秒鐘跑完，確認參數、輸出檔名、續跑邏輯都對）
    python "run experiment/launch_S100_dro_matrix.py" --dry-run

    # 只跑某幾個規模
    python "run experiment/launch_S100_dro_matrix.py" --scales small,medium

    # 從頭重跑（舊進度檔會先備份，不會刪除）
    python "run experiment/launch_S100_dro_matrix.py" --fresh

輸出（experiment result/）
--------------------------
    DRO_full_matrix_raw_S100.csv    進度檔，每格跑完立刻更新
    DRO_full_matrix_S100.xlsx       Summary / Table_small / Table_medium /
                                    Table_large / Detail / Config
    log/S100_<時間>.log             本次完整主控台紀錄

中斷與續跑
----------
    Ctrl+C  → 外殼與子行程一起乾淨結束，已完成的格子都在進度檔裡。
    再執行一次同一道指令即可從中斷處接著跑（預設就是續跑，不必加任何參數）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
BATCH = ROOT_DIR / "run experiment" / "batch_dro_full_matrix.py"
LOG_DIR = ROOT_DIR / "experiment result" / "log"

# 這一輪的固定設定 —— 跟 S=50 那輪唯一的差別就是 SCENARIOS。
SCENARIOS = 100
TAG = "S100"
TIME_LIMIT = 7200.0          # 每格 2 小時，與 S=50 相同
DEFAULT_SCALES = ("small", "medium", "large")
DEFAULT_MODELS = "dro_box,dro_ellipsoidal,dro_polyhedral"
DEFAULT_METHODS = "1,2,3,4,5,6,7,8"

# 子行程的離開碼。3 = 偵測到另一個實例（鎖檔）；130 = 使用者 Ctrl+C。
# 這兩種都不該自動重試 —— 重試只會再撞一次鎖，或違背使用者停止的意圖。
EXIT_LOCKED = 3
EXIT_INTERRUPTED = 130


def fmt_hms(sec: float) -> str:
    sec = int(max(0.0, sec))
    return f"{sec // 3600:d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def build_cmd(scale: str, args) -> list[str]:
    cmd = [sys.executable, "-u", str(BATCH),
           "--scales", scale,
           "--models", args.models,
           "--methods", args.methods,
           "--scenarios", str(SCENARIOS),
           "--time-limit", str(args.time_limit),
           "--tag", TAG]
    if args.mip_gap is not None:
        cmd += ["--mip-gap", str(args.mip_gap)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.keep_failed:
        cmd.append("--keep-failed")
    # --fresh 只在「本次第一個規模」下，否則第二個規模會把第一個規模的結果備份走。
    return cmd


def run_once(cmd: list[str], log_fh) -> int:
    """跑一次子行程，輸出同時進畫面與 log 檔。回傳離開碼。"""
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1)
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_fh.write(line)
            log_fh.flush()
    finally:
        proc.stdout.close()
    return proc.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="S=100 DRO 全矩陣總管")
    ap.add_argument("--scales", default=",".join(DEFAULT_SCALES))
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--methods", default=DEFAULT_METHODS)
    ap.add_argument("--time-limit", type=float, default=TIME_LIMIT)
    ap.add_argument("--mip-gap", type=float, default=None,
                    help="不給就沿用 config.SP_MIP_GAP（S=50 那輪是 0.01）")
    ap.add_argument("--fresh", action="store_true",
                    help="從頭重跑；舊進度檔先備份不刪除")
    ap.add_argument("--keep-failed", action="store_true",
                    help="失敗的格子視為完成、續跑時不重試")
    ap.add_argument("--dry-run", action="store_true",
                    help="不求解，只驗流程與輸出版面")
    ap.add_argument("--max-restarts", type=int, default=5,
                    help="同一個規模異常結束後最多自動重啟幾次（預設 5）")
    args = ap.parse_args(argv)

    scales = [x.strip() for x in args.scales.split(",") if x.strip()]
    if not scales:
        ap.error("--scales 不能是空的")
    if not BATCH.exists():
        ap.error(f"找不到 {BATCH}")

    n_models = len([x for x in args.models.split(",") if x.strip()])
    n_methods = len([x for x in args.methods.split(",") if x.strip()])
    total_cells = len(scales) * n_models * n_methods

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"S100_{datetime.now():%Y%m%d_%H%M%S}.log"

    print("=" * 100)
    print(" S=100　DRO 全矩陣　總管")
    print("=" * 100)
    print(f" 情境數 |S| : {SCENARIOS}　（S=50 那輪的前 50 個情境就是這 100 個的子集）")
    print(f" 規模       : {', '.join(scales)}　（一個規模一個行程，跑完就釋放記憶體）")
    print(f" 模糊集     : {args.models}")
    print(f" 方法       : {args.methods}")
    print(f" 每格時限   : {args.time_limit:,.0f} 秒 = {args.time_limit / 3600:.2f} 小時")
    print(f" 總格數     : {total_cells}")
    print(f" 最壞耗時   : {total_cells * args.time_limit / 86400:.2f} 天"
          f"（實際會少很多，提早收斂的格子不會用滿時限）")
    print(f" 進度檔     : experiment result/DRO_full_matrix_raw_{TAG}.csv")
    print(f" Excel      : experiment result/DRO_full_matrix_{TAG}.xlsx")
    print(f" 本次紀錄   : {log_path}")
    if args.dry_run:
        print(" *** DRY RUN：不會真的求解 ***")
    print("=" * 100, flush=True)

    t0 = time.time()
    rc = 0
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"# launch_S100_dro_matrix　開始 {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        log_fh.write(f"# scales={scales} models={args.models} methods={args.methods}\n\n")
        for si, scale in enumerate(scales):
            cmd = build_cmd(scale, args)
            if args.fresh and si == 0:
                # 只有第一個規模帶 --fresh：進度檔是三個規模共用的一份，
                # 每個規模都帶的話第二、三個規模會把前面剛跑完的結果備份走。
                cmd.append("--fresh")

            for attempt in range(1, args.max_restarts + 2):
                banner = (f"\n{'#' * 100}\n"
                          f"# 規模 {scale}　（第 {si + 1}/{len(scales)} 個）"
                          f"　嘗試 {attempt}"
                          f"　已用 {fmt_hms(time.time() - t0)}"
                          f"　{datetime.now():%Y-%m-%d %H:%M:%S}\n"
                          f"{'#' * 100}\n")
                print(banner, flush=True)
                log_fh.write(banner)
                log_fh.flush()

                try:
                    code = run_once(cmd, log_fh)
                except KeyboardInterrupt:
                    print("\n 使用者中斷。已完成的格子都在進度檔裡，"
                          "重跑同一道指令即可續跑。", flush=True)
                    return EXIT_INTERRUPTED

                if code == 0:
                    break
                if code == EXIT_INTERRUPTED:
                    print("\n 子行程回報使用者中斷，全部停止。", flush=True)
                    return EXIT_INTERRUPTED
                if code == EXIT_LOCKED:
                    print("\n 偵測到另一個實例正在跑（鎖檔）。為避免兩邊互相覆蓋"
                          "進度檔，本次停止。", flush=True)
                    return EXIT_LOCKED
                if attempt > args.max_restarts:
                    print(f"\n [!] 規模 {scale} 連續失敗 {args.max_restarts + 1} 次"
                          f"（最後離開碼 {code}），跳過這個規模繼續往下。", flush=True)
                    rc = rc or code
                    break
                wait = 30
                print(f"\n [!] 子行程異常結束（離開碼 {code}）。{wait} 秒後自動重啟，"
                      f"已完成的格子會自動跳過。", flush=True)
                time.sleep(wait)

    used = time.time() - t0
    print("\n" + "=" * 100)
    print(f" 總管結束　實際耗時 {fmt_hms(used)}"
          f"　（{(datetime.now() - timedelta(seconds=used)):%m-%d %H:%M}"
          f" → {datetime.now():%m-%d %H:%M}）")
    print(f" Excel  : experiment result/DRO_full_matrix_{TAG}.xlsx")
    print(f" 進度檔 : experiment result/DRO_full_matrix_raw_{TAG}.csv")
    print(f" 紀錄   : {log_path}")
    print("=" * 100)
    return rc


if __name__ == "__main__":
    sys.exit(main())
