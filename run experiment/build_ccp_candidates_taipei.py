#!/usr/bin/env python3
"""產生 Taipei 的 50 個 CCP 候選點（data/ccp_Taipei_50.csv）。

背景
----
`data/ccp_Taipei.csv` 只有 16 個真實 CCP 點位，但實驗需要 |J| = 50 個
「候選」設置點，才能讓一階 0-1 決策空間夠大、B&BC 的加速效果顯現。

作法（完全確定性，固定 seed，可重現）
-----------------------------------
1. 對 229 個真實災區節點做 K-means（k = 50），取得 50 個空間分散的質心。
   質心 = 需求節點的幾何中心，是設施選址文獻中標準的候選點生成啟發式。
2. 把 16 個「真實」CCP 依序貪婪指派到離它最近、尚未被占用的質心，並用
   真實座標取代該質心。
   → 最終 50 點 = 16 個真實 CCP + 34 個由真實災區地理衍生的候選點，
     且彼此空間分散、不會與既有 CCP 重疊。
3. 檢查：兩兩最小距離、與災區節點的最小距離（避免距離 0 造成退化）。

若日後拿到真正的 50 筆 CCP 資料，直接覆蓋 data/ccp_Taipei_50.csv
（欄位 `,X,Y`）即可，config.py 不需改動。

用法
----
    python "run experiment/build_ccp_candidates_taipei.py"
"""
from __future__ import annotations

import csv
import math
import random
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"

DISASTER_CSV = DATA_DIR / "disaster_Taipei.csv"
REAL_CCP_CSV = DATA_DIR / "ccp_Taipei.csv"
OUTPUT_CSV = DATA_DIR / "ccp_Taipei_50.csv"

TARGET_N_CCP = 50
SEED = 42
KMEANS_MAX_ITER = 300
KMEANS_RESTARTS = 20
MIN_SEPARATION_M = 150.0   # 候選點之間 / 候選點與災區節點的最小距離（僅警告）


def read_xy(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            keys = {k.strip().upper(): k for k in row if k}
            points.append((float(row[keys["X"]]), float(row[keys["Y"]])))
    return points


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _kmeans_plus_plus_init(points, k, rng):
    centers = [rng.choice(points)]
    while len(centers) < k:
        d2 = [min(_dist(p, c) ** 2 for c in centers) for p in points]
        total = sum(d2)
        if total <= 0.0:
            centers.append(rng.choice(points))
            continue
        threshold = rng.random() * total
        running = 0.0
        for point, weight in zip(points, d2):
            running += weight
            if running >= threshold:
                centers.append(point)
                break
    return centers


def kmeans(points, k, seed, max_iter=KMEANS_MAX_ITER):
    """回傳 (centroids, inertia)。純標準庫實作，確定性。"""
    rng = random.Random(seed)
    centers = _kmeans_plus_plus_init(points, k, rng)
    for _ in range(max_iter):
        buckets: list[list[tuple[float, float]]] = [[] for _ in range(k)]
        for point in points:
            best = min(range(k), key=lambda idx: _dist(point, centers[idx]))
            buckets[best].append(point)
        new_centers = []
        for idx, bucket in enumerate(buckets):
            if bucket:
                new_centers.append(
                    (sum(p[0] for p in bucket) / len(bucket),
                     sum(p[1] for p in bucket) / len(bucket))
                )
            else:
                # 空群：改指派到離所有中心最遠的點，避免中心塌陷
                far = max(points, key=lambda p: min(_dist(p, c) for c in centers))
                new_centers.append(far)
        shift = max(_dist(a, b) for a, b in zip(centers, new_centers))
        centers = new_centers
        if shift < 1e-6:
            break
    inertia = sum(min(_dist(p, c) ** 2 for c in centers) for p in points)
    return centers, inertia


def _repair_coincident(point, disaster, region_centroid):
    """把與災區節點過近的「合成」候選點移開（確定性，仍以真實地理衍生）。

    K-means 的單點群集其質心會剛好落在該災區節點上，造成 distance_ij = 0，
    使該 CCP 對該災區的運送時間退化為 0。修補方式：改取「該災區節點與其最近
    鄰居的中點」；若仍過近，再沿「區域重心 → 該點」方向推開至最小間隔。
    """
    nearest = min(disaster, key=lambda d: _dist(point, d))
    if _dist(point, nearest) >= MIN_SEPARATION_M:
        return point
    neighbour = min(
        (d for d in disaster if d != nearest),
        key=lambda d: _dist(nearest, d),
    )
    moved = ((nearest[0] + neighbour[0]) / 2.0, (nearest[1] + neighbour[1]) / 2.0)
    if min(_dist(moved, d) for d in disaster) >= MIN_SEPARATION_M:
        return moved
    dx, dy = moved[0] - region_centroid[0], moved[1] - region_centroid[1]
    norm = math.hypot(dx, dy) or 1.0
    return (moved[0] + MIN_SEPARATION_M * dx / norm,
            moved[1] + MIN_SEPARATION_M * dy / norm)


def build_candidates() -> list[tuple[float, float]]:
    disaster = read_xy(DISASTER_CSV)
    real_ccp = read_xy(REAL_CCP_CSV)
    if len(disaster) < TARGET_N_CCP:
        raise RuntimeError(
            f"災區節點只有 {len(disaster)} 個，無法產生 {TARGET_N_CCP} 個 K-means 候選點"
        )

    # 多次重啟取 inertia 最小者（確定性：seed 由固定序列衍生）
    best_centers, best_inertia = None, float("inf")
    for restart in range(KMEANS_RESTARTS):
        centers, inertia = kmeans(disaster, TARGET_N_CCP, SEED + restart)
        if inertia < best_inertia:
            best_centers, best_inertia = centers, inertia
    centers = sorted(best_centers, key=lambda p: (p[0], p[1]))

    # 貪婪：每個真實 CCP 取代離它最近、尚未被占用的質心
    taken: set[int] = set()
    pairs = sorted(
        ((_dist(ccp, centers[ci]), ri, ci)
         for ri, ccp in enumerate(real_ccp)
         for ci in range(len(centers))),
        key=lambda t: (t[0], t[1], t[2]),
    )
    assigned: dict[int, int] = {}
    for _, ri, ci in pairs:
        if ri in assigned or ci in taken:
            continue
        assigned[ri] = ci
        taken.add(ci)
        if len(assigned) == len(real_ccp):
            break

    # 先修補「與災區節點重合」的合成質心（真實 CCP 座標一律不動）
    region_centroid = (
        sum(p[0] for p in disaster) / len(disaster),
        sum(p[1] for p in disaster) / len(disaster),
    )
    candidates = [
        _repair_coincident(c, disaster, region_centroid) for c in centers
    ]
    for ri, ci in assigned.items():
        candidates[ci] = real_ccp[ri]

    candidates.sort(key=lambda p: (p[0], p[1]))
    return candidates


def report(candidates, disaster) -> None:
    min_pair = min(
        _dist(candidates[a], candidates[b])
        for a in range(len(candidates))
        for b in range(a + 1, len(candidates))
    )
    min_to_disaster = min(
        min(_dist(c, d) for d in disaster) for c in candidates
    )
    xs = [c[0] for c in candidates]
    ys = [c[1] for c in candidates]
    print(f"  候選點數            : {len(candidates)}")
    print(f"  候選點兩兩最小距離  : {min_pair:,.1f} m")
    print(f"  候選點-災區最小距離 : {min_to_disaster:,.1f} m")
    print(f"  X 範圍              : {min(xs):,.0f} ~ {max(xs):,.0f}")
    print(f"  Y 範圍              : {min(ys):,.0f} ~ {max(ys):,.0f}")
    if min_pair < MIN_SEPARATION_M:
        print(f"  [WARN] 有候選點距離 < {MIN_SEPARATION_M} m")
    if min_to_disaster < 1.0:
        print("  [WARN] 有候選點與災區節點重合（距離 0），會造成運送時間退化")


def main() -> int:
    print("=" * 66)
    print("建立 Taipei CCP 候選點（50 個）")
    print("=" * 66)
    disaster = read_xy(DISASTER_CSV)
    real_ccp = read_xy(REAL_CCP_CSV)
    print(f"  來源：災區 {len(disaster)} 點、真實 CCP {len(real_ccp)} 點")

    candidates = build_candidates()
    report(candidates, disaster)

    real_set = {(round(x, 4), round(y, 4)) for x, y in real_ccp}
    kept = sum(1 for x, y in candidates if (round(x, 4), round(y, 4)) in real_set)
    print(f"  其中保留的真實 CCP  : {kept} / {len(real_ccp)}")

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["", "X", "Y"])
        for idx, (x, y) in enumerate(candidates):
            writer.writerow([idx, f"{x:.4f}", f"{y:.4f}"])
    print(f"\n  已輸出：{OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
