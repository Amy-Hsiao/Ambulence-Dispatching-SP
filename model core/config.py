import csv
import math
import hashlib
import random
import warnings
from collections.abc import Mapping
from typing import Any
from pathlib import Path

# ==========================================
# 參數設定區
# ==========================================
# Phase R 重構：config.py 移入 model core/，DATA_DIR 改以檔案位置定位專案根（原 Path("data") 相對 cwd）
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
# 2026-08 放大規模：資料來源由「東區」改為「台北市全區」。
#   disaster_Taipei.csv  : 229 個災區節點
#   ccp_Taipei_50.csv    : 50 個 CCP 候選點（16 個真實 CCP + 34 個由災區節點
#                          K-means 質心衍生的候選點；見
#                          run experiment/build_ccp_candidates_taipei.py）
#   hospital_Taipei.csv  : 20 家醫院
DISASTER_CSV = "disaster_Taipei.csv"
CCP_CSV = "ccp_Taipei_50.csv"
HOSPITAL_CSV = "hospital_Taipei.csv"

MASTER_SEED = 42
SCENARIOS = 5
TIME_PERIODS = 8
COORDINATE_SYSTEM = "euclidean_m"
DEMAND_MULTIPLIER = 1.0
DEMAND_UNIFORM_LOW = 1.0
DEMAND_UNIFORM_HIGH = 5.0
# ── 基礎設定（定案）：Both = 全局 omega [0.8,1.2] + 空間乘數 U[0.5,1.5]（正規化）──
# 依 sensitivity_uncertainty_results：VSS≈13%、EVPI≈2.9%，結果對空間範圍不敏感（±0.2~±0.7 間 VSS 僅差 2pp）
SCENARIO_OMEGA_LOW  = 0.8   # 全局情境乘數 下界（災害整體規模 ±20%）
SCENARIO_OMEGA_HIGH = 1.2   # 全局情境乘數 上界
SCENARIO_SPATIAL_CLUSTERS   = 3     # 地理群集數（K-means）
SCENARIO_SPATIAL_OMEGA_LOW  = 0.5   # 群集需求乘數 下界（原 [0.5,2.0]，2026-07 定案改為 [0.5,1.5]）
SCENARIO_SPATIAL_OMEGA_HIGH = 1.5   # 群集需求乘數 上界
NORMALIZE_SPATIAL_OMEGA = True  # True: 空間乘數依群集規模加權正規化(每情境加權平均=1，純重分配不改總量)
USE_SCENARIO_OMEGA  = True   # [Ablation 開關] True: 每情境抽全局 omega；False: 固定 1.0
USE_SPATIAL_KMEANS  = True   # [Ablation 開關] True: K-means 空間異質性；False: 不分群
ROAD_CAPACITY_MULTIPLIER = 1.0
HOSPITAL_CAPACITY_MULTIPLIER = 1.0
SAMPLE_RATIO = 1.0           # East District 直接用全部 I 和 H（legacy 路徑）
CCP_SAMPLE_SIZE = None       # East District 全部 10 個 CCP 都是候選點
SCALE_CCP_TOTAL_RESOURCES = True
CCP_RESOURCE_SCALE_ROUNDING = "ceil"

# ── 規模 Profile（plan/15）：實驗程式只要設 EXPERIMENT_SCALE 就切換規模 ──
# 當 generate_data 未帶 sample_ratio 時，依 EXPERIMENT_SCALE 抽出 (I,J,H) 與
# 縮放後參數。"full" = 全量（等同 legacy 全用）。傳 sample_ratio 則走 legacy 路徑。
EXPERIMENT_SCALE = "full"    # "small" | "medium" | "large" | "full"

# ── 校準基準（PARAMETERS 區的數值是在「東區全量」這個規模上校準出來的）──
# 縮放一律以此為分母，才不會因為換資料集（東區 → 台北）而讓資源憑空放大/縮小。
# ⚠️ 這三個常數綁定 PARAMETERS 的校準情境，除非重新校準 PARAMETERS，否則不要改。
PARAM_CALIB_N_DISASTER = 129   # 校準時的 |I|
PARAM_CALIB_N_CCP      = 10    # 校準時的 |J|
PARAM_CALIB_N_HOSPITAL = 16    # 校準時的 |H|

# ── 台北全量（= CSV 實際筆數，供 "full" profile 與上限驗證用）──
N_DISASTER_FULL = 229
N_CCP_FULL = 50
N_HOSPITAL_FULL = 20

# 2026-08 放大規模（老師要求）：災區 70/100/130、CCP 50、醫院 18。
SCALE_PROFILES = {
    "small":  {"n_disaster": 70,  "n_hospital": 18, "n_ccp": 50, "spatial_clusters": 3},
    "medium": {"n_disaster": 100, "n_hospital": 18, "n_ccp": 50, "spatial_clusters": 3},
    "large":  {"n_disaster": 130, "n_hospital": 18, "n_ccp": 50, "spatial_clusters": 3},
    "full":   {"n_disaster": 229, "n_hospital": 20, "n_ccp": 50, "spatial_clusters": 3},
}
# 抽樣模式："nested" = small ⊂ medium ⊂ large（固定 shuffle 取前綴）。
SCALE_SAMPLING_MODE = "nested"

# ── per-CCP 上限的縮放語意 ──
# "demand_only"  ：per-CCP 上限只隨總需求 (|I|) 縮放，不隨候選點數 |J| 稀釋。
#                  理由：單一 CCP 的收治量/人力上限是「設施的物理屬性」，
#                  不會因為候選地點變多就變小。此時全域資源池
#                  (total_available_staff) 仍是綁定約束，會限制實際開設數量，
#                  一階決策變成「從 50 個候選點挑約 5~6 個」的選址問題。
# "per_ccp_load" ：per-CCP 上限額外乘 (PARAM_CALIB_N_CCP / |J|)，維持
#                  「Σ per-CCP 上限 / 全域池」比值與校準情境完全相同。
#                  此時會開出約 26 個 CCP，目標值被固定開設成本主導。
CCP_UPPER_BOUND_SCALING = "demand_only"   # "demand_only" | "per_ccp_load"

SP_SCENARIO_SIZE = None
SP_SAMPLE_RATIO = SAMPLE_RATIO
SP_TIME_LIMIT = 3600.0
SP_MIP_GAP = 0.01
SP_PROGRESS_INTERVAL_SEC = 10.0

# ── 風險模型設定（plan/08-09；只影響 mcvar/dro 入口，SP 路徑完全不受影響）──
RISK_ALPHA  = 0.9    # CVaR 信心水準 α ∈ [0,1)（越大越保守）
RISK_LAMBDA = 0.5    # mean 與 CVaR 的權重 λ ∈ [0,1]（0 = 純期望值 = SP；1 = 純 CVaR）
# DRO ambiguity set 參數（plan/09；預設值取 Jin et al. 2024 小算例設定）
DRO_AMBIGUITY_SET = "box"   # "box" | "ellipsoidal" | "polyhedral"
DRO_EPSILON_BOX   = 0.01    # box：|p_s − p0_s| ≤ ε̄_B；必須 ≤ min_s p0_s（等權重時 = 1/S）
DRO_A_E           = 0.0005  # ellipsoidal：A_E = a_E · I
DRO_A_P           = 0.001   # polyhedral：A_P = a_P · I

# VSS/EVPI 子問題時間預算（定義不變，只限制求解時間與精度）
# 最壞情況總時間 ≈ SP 3600 + EV 180 + EEV 180 + WS 5×120 = 76 分鐘
VSS_EVPI_EV_TIME_LIMIT  = 180.0   # EV：單情境確定性模型
VSS_EVPI_EEV_TIME_LIMIT = 180.0   # EEV：一階固定後近似 LP，通常數秒
VSS_EVPI_WS_TIME_LIMIT  = 120.0   # WS：每個情境（原 1200）
VSS_EVPI_WS_MIP_GAP     = 0.01    # WS gap 與 RP 一致（原 0.0001；gap 不一致會使 EVPI 有偏）
# 大 S 加速（定義不變）：EEV 依情境分解成單情境 LP（數學等價）；WS/EEV 情境平行求解
VSS_EVPI_DECOMPOSE_EEV     = True  # True: EEV = Σ p_s·(固定x_EV的單情境目標)，逐情境計算
VSS_EVPI_PARALLEL_WORKERS  = 6     # WS/EEV 同時求解的情境數（1 = 循序，行為同舊版）

# ── Benders / B&BC 設定（Phase 0；只影響 lshaped 引擎，extensive form 完全不受影響）──
SOLVER_ENGINE            = "lshaped"     # "extensive" | "lshaped"（runner 依此分派求解引擎）
BENDERS_MULTI_CUT        = True    # False = single-cut（僅供實驗比較，預設恆 True）
# ── Root seeding（2026-08-16 依 plan/17 診斷結果調整）──
# 問題：上一輪 small case 的 seeding 在第 151/300 輪、LB=10,029,725 就停止，
#       但 Extensive 的根節點 LP 下界是 17,865,909 —— Benders 收斂後理論上
#       應該等於這個值，卻只拿到 56%。停止當下每輪還在漲 0.038%，且只花了
#       367 秒（總預算的 5%）。這是典型的 Benders tailing-off 被 5e-4 的
#       停滯門檻誤判成收斂，直接導致 BBC 的 LB 反而輸給 Extensive。
# 對策：把停滯門檻收緊 10 倍、停滯輪數放寬 4 倍。
#
# ⚠️ ITERS 為什麼是 600 而不是更大：
#    (1) 上一輪是被「停滯判定」在第 151 輪停掉的，300 輪的上限根本沒用到
#        → 真正該修的是 REL_TOL / STALL_ROUNDS，ITERS 只是保險絲。
#    (2) lshaped_core 的 seeding 只有「總時限用完」一個時間保護，所以 ITERS
#        就是實質時間上限。實測 151 輪 = 366.56s（2.43 s/輪）。若每輪成本固定，
#        600 輪 ≈ 1,460s（總預算 20%）；即使每輪成本隨切割線性變貴，也還有
#        時限保護會接手，最壞情況只是退化成「只做 seeding」而不會崩潰。
#    (3) 每輪成本主要來自 50 個情境 oracle（各約 10~18 萬變數），master 只有
#        100 個變數（50 X + 50 θ），所以成本接近固定而非二次成長。
#    先用 600 跑診斷實驗量到真實的 s/輪，再決定正式實驗要不要調高。
BENDERS_ROOT_SEED_ITERS  = 600     # 正式 B&C 前，LP 鬆弛 master 的 ordinary cut 墊切輪數上限（原 300）
BENDERS_ROOT_SEED_ADAPTIVE = True  # 保留相容欄位；實際以相對 LB 改善門檻控制停止
BENDERS_ROOT_SEED_STALL_ROUNDS = 40 # seeded LB 連 40 輪改善不足門檻即停止（原 10）
BENDERS_ROOT_SEED_LB_ABS_TOL = 1e-3   # 保留相容欄位；Papadakos seeding 不再使用絕對門檻
BENDERS_ROOT_SEED_LB_REL_TOL = 5e-5   # seeded LB 單輪相對改善 < 0.005% 才視為停滯（原 5e-4）
BENDERS_ROOT_SEED_ROUND_HEUR_FREQ = 10
BENDERS_PAPADAKOS_BLEND   = 0.5
BENDERS_PARETO_ENABLED    = True    # False = seeding/user cuts 僅加 standard cut，不建 core point
BENDERS_PROGRESS_BOUND_FLOOR = -1e50
BENDERS_ROOT_CUT_ROUNDS  = 15      # root 節點 callback 分數解 user cut 輪數（0 = 關閉 root cuts）
BENDERS_USE_USER_CUTS    = True    # True: root 節點分數解 user cut
BENDERS_CUT_VIOL_REL_TOL = 1e-6    # cut 違反判定：Q_s > θ_s + tol·max(1,|Q_s|)
# 情境 oracle 平行數（1 = 循序）。oracle 是單執行緒 LP（ScenarioOracle threads=1），
# 所以平行度 ≈ 佔用的實體核心數。實測 callback 佔 BBC 總時間 28%~67%，
# 情境數又從 30 提高到 50，故由 5 提高到 10（機器為 12 實體核心 / 24 邏輯執行緒，
# 留 2 核給 master 與作業系統）。若換到核心數較少的機器，請調回 5。
BENDERS_PARALLEL_ORACLES = 10
BENDERS_EV_WARM_START    = True    # 用 EV 一階解當 master 初始 incumbent
BENDERS_MIPFOCUS         = 3       # 3 = 強化 bound；None = 不覆寫 Gurobi 預設
BENDERS_HEURISTICS       = 0.05    # 啟發式時間比例；None = 不覆寫 Gurobi 預設
BENDERS_NUMERIC_FOCUS    = 1       # None = 不覆寫 Gurobi 預設
BENDERS_X_BRANCH_PRIORITY_ENABLED = True
BENDERS_X_BRANCH_PRIORITY = 10     # 只給 X[j] 設 branching priority；0 = 無優先權

PERIOD_DURATION_SEC = 1800.0
ASSUMED_SPEED_MPS = 11.11

PARAMETERS = {
    "ccp_fixed_opening_cost": 1500000.0,
    "staff_unit_assignment_cost": 10000.0,
    "ccp_ambulance_unit_assignment_cost": 8000.0,
    "supply_allocation_cost_unit": 1800.0,
    "total_available_staff": 550.0,
    "total_available_ccp_ambulances": 132.0,
    "hospital_supply_upper_bound": 600.0,
    "ccp_staff_upper_bound": 104.0,
    "ccp_ambulance_upper_bound": 18.0,
    "ccp_supply_upper_bound": 2000.0,
    "hospital_ambulance_fleet": 18.0,
    "ccp_ambulance_casualty_capacity": 2.0,
    "hospital_ambulance_casualty_capacity": 2.0,
    "ccp_physical_capacity_by_severity": {
        "minor": 143.0,
        "moderate": 43.0,
        "severe": 14.0
    },
    "treatment_duration_by_severity": {
        "minor": 1.0,
        "moderate": 2.0,
        "severe": 1.0
    },
    "staff_treatment_rate_by_severity": {
        "minor": 3.0,
        "moderate": 2.0,
        "severe": 1.0
    },
    "supply_consumption_by_severity": {
        "minor": 1.0,
        "moderate": 2.0,
        "severe": 4.0
    },
    "disaster_area_remaining_penalty_by_severity": {
        "minor": 2000.0,
        "moderate": 50000.0,
        "severe": 100000.0
    },
    "ccp_waiting_penalty_by_severity": {
        "minor": 0.0,
        "moderate": 25000.0,
        "severe": 50000.0
    }
}

SEVERITY_LEVELS = ("minor", "moderate", "severe")
TRANSFER_SEVERITY_LEVELS = ("moderate", "severe")
SEVERITY_PROBABILITY = {
    "minor": 0.6,
    "moderate": 0.3,
    "severe": 0.1,
}


class CoordinateRecord:
    def __init__(self, id: str, x: float, y: float, name: str | None = None):
        self.id = id
        self.x = x
        self.y = y
        self.name = name

    def asdict(self):
        return {"id": self.id, "x": self.x, "y": self.y, "name": self.name}


def read_coordinate_csv(path: Path) -> list[CoordinateRecord]:
    if not path.exists():
        records = []
        prefix = path.stem.split("_")[0]
        count = 10 if prefix == "disaster" else (5 if prefix == "ccp" else 4)
        for i in range(count):
            records.append(CoordinateRecord(id=f"{prefix[0].upper()}{i+1:02d}", x=i*100.0, y=i*100.0, name=f"{prefix}_{i}"))
        return records
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        records = []
        for row in reader:
            index_field = "" if "" in row else (reader.fieldnames or [""])[0]
            records.append(
                CoordinateRecord(
                    id=str(row[index_field]),
                    x=float(row["X"]),
                    y=float(row["Y"]),
                    name=row.get("name") or None,
                )
            )
    return records


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _distance_m(a: CoordinateRecord, b: CoordinateRecord, coordinate_system: str) -> float:
    coordinate_system = coordinate_system.lower()
    if coordinate_system in {"latlon", "lat_lon", "haversine"}:
        return _haversine_m(a.y, a.x, b.y, b.x)
    if coordinate_system in {"euclidean", "euclidean_m", "twd97", "meter", "meters"}:
        return math.hypot(a.x - b.x, a.y - b.y)
    raise ValueError("coordinate_system must be euclidean_m/twd97/meters or latlon/haversine")


def _matrix(origins, destinations, coordinate_system):
    return {
        o.id: {d.id: _distance_m(o, d, coordinate_system) for d in destinations}
        for o in origins
    }


def _transport_cost(matrix):
    return {
        oid: {did: 100.0 + 150.0 * dist / 1000.0 for did, dist in dests.items()}
        for oid, dests in matrix.items()
    }


def _indexed_scalar(value: float, ids: list[str]) -> dict[str, float]:
    return {item_id: float(value) for item_id in ids}


def resolve_scale(scale: str) -> dict[str, Any]:
    """Resolve a named network scale and its resource-scaling drivers.

    三個驅動因子（分母一律是 PARAM_CALIB_*，即 PARAMETERS 的校準規模）：

    * ``demand_scale``   s_D = |I| / I_calib
      驅動「外延總量」：total_available_staff、total_available_ccp_ambulances。
      每個災區每期產生 U[1,5] 需求，故系統總需求 ∝ |I|。

    * ``ccp_scale``      s_J = s_D                      (demand_only)
                         s_D · (J_calib / |J|)          (per_ccp_load)
      驅動 per-CCP 上限。預設 demand_only：單一 CCP 的容量是設施物理屬性，
      不因候選點數量而改變；開設數量由全域資源池與固定開設成本自然限制。

    * ``hospital_scale`` s_H = s_D · (H_calib / |H|)
      驅動 per-醫院上限。醫院總轉送量 ∝ |I|，per-醫院負載 ∝ |I| / |H|，
      故以此因子維持 per-醫院鬆緊度與校準情境一致。
    """
    normalized = str(scale).strip().lower()
    if normalized not in SCALE_PROFILES:
        valid = ", ".join(SCALE_PROFILES)
        raise ValueError(f"Unknown experiment scale {scale!r}; expected one of: {valid}")
    profile = SCALE_PROFILES[normalized]

    demand_scale = profile["n_disaster"] / PARAM_CALIB_N_DISASTER

    mode = str(CCP_UPPER_BOUND_SCALING).strip().lower()
    if mode == "demand_only":
        ccp_scale = demand_scale
    elif mode == "per_ccp_load":
        ccp_scale = demand_scale * (PARAM_CALIB_N_CCP / profile["n_ccp"])
    else:
        raise ValueError(
            f"Unsupported CCP_UPPER_BOUND_SCALING: {CCP_UPPER_BOUND_SCALING!r}; "
            "expected 'demand_only' or 'per_ccp_load'"
        )

    hospital_scale = demand_scale * (PARAM_CALIB_N_HOSPITAL / profile["n_hospital"])

    return {
        **profile,
        "scale": normalized,
        "demand_scale": demand_scale,
        "ccp_scale": ccp_scale,
        "hospital_scale": hospital_scale,
        "ccp_upper_bound_scaling": mode,
    }


def _scale_total_resource(value: float, scale: float) -> float:
    scaled = float(value) * float(scale)
    if CCP_RESOURCE_SCALE_ROUNDING == "ceil":
        return float(math.ceil(scaled))
    if CCP_RESOURCE_SCALE_ROUNDING == "round":
        return float(round(scaled))
    if CCP_RESOURCE_SCALE_ROUNDING == "floor":
        return float(math.floor(scaled))
    if CCP_RESOURCE_SCALE_ROUNDING == "none":
        return scaled
    raise ValueError(f"Unsupported CCP_RESOURCE_SCALE_ROUNDING: {CCP_RESOURCE_SCALE_ROUNDING}")


def _build_deterministic_parameters(
    ccp_ids,
    hospital_ids,
    ccp_resource_scale=1.0,
    demand_scale=None,
    hospital_scale=1.0,
    ccp_scale=None,
):
    # ccp_resource_scale is retained for legacy sample_ratio/ccp_sample_size runs.
    demand_scale = ccp_resource_scale if demand_scale is None else demand_scale
    # per-CCP 上限的縮放因子；未指定時退回 demand_scale（= 舊行為）。
    ccp_scale = demand_scale if ccp_scale is None else ccp_scale
    supply_allocation_cost = {
        h: {j: float(PARAMETERS["supply_allocation_cost_unit"]) for j in ccp_ids}
        for h in hospital_ids
    }
    return {
        "ccp_fixed_opening_cost": _indexed_scalar(PARAMETERS["ccp_fixed_opening_cost"], ccp_ids),
        "staff_unit_assignment_cost": float(PARAMETERS["staff_unit_assignment_cost"]),
        "ccp_ambulance_unit_assignment_cost": float(PARAMETERS["ccp_ambulance_unit_assignment_cost"]),
        "supply_allocation_cost_from_hospital_to_ccp": supply_allocation_cost,
        "total_available_staff": _scale_total_resource(PARAMETERS["total_available_staff"], demand_scale),
        "total_available_ccp_ambulances": _scale_total_resource(PARAMETERS["total_available_ccp_ambulances"], demand_scale),
        "hospital_supply_upper_bound": _indexed_scalar(
            _scale_total_resource(PARAMETERS["hospital_supply_upper_bound"], hospital_scale), hospital_ids
        ),
        "ccp_staff_upper_bound": _indexed_scalar(
            _scale_total_resource(PARAMETERS["ccp_staff_upper_bound"], ccp_scale), ccp_ids
        ),
        "ccp_ambulance_upper_bound": _indexed_scalar(
            _scale_total_resource(PARAMETERS["ccp_ambulance_upper_bound"], ccp_scale), ccp_ids
        ),
        "ccp_supply_upper_bound": _indexed_scalar(
            _scale_total_resource(PARAMETERS["ccp_supply_upper_bound"], ccp_scale), ccp_ids
        ),
        "hospital_ambulance_fleet": _indexed_scalar(
            _scale_total_resource(PARAMETERS["hospital_ambulance_fleet"], hospital_scale), hospital_ids
        ),
        "ccp_ambulance_casualty_capacity": float(PARAMETERS["ccp_ambulance_casualty_capacity"]),
        "hospital_ambulance_casualty_capacity": float(PARAMETERS["hospital_ambulance_casualty_capacity"]),
        "ccp_physical_capacity_by_severity": {
            severity: _scale_total_resource(value, ccp_scale)
            for severity, value in PARAMETERS["ccp_physical_capacity_by_severity"].items()
        },
        "treatment_duration_by_severity": PARAMETERS["treatment_duration_by_severity"],
        "staff_treatment_rate_by_severity": PARAMETERS["staff_treatment_rate_by_severity"],
        "supply_consumption_by_severity": PARAMETERS["supply_consumption_by_severity"],
        "disaster_area_remaining_penalty_by_severity": PARAMETERS["disaster_area_remaining_penalty_by_severity"],
        "ccp_waiting_penalty_by_severity": PARAMETERS["ccp_waiting_penalty_by_severity"],
    }


# ==========================================
# 地理群集（K-means）
# ==========================================
def _kmeans_cluster(
    records: list[CoordinateRecord],
    k: int,
    seed: int,
    max_iter: int = 50,
) -> list[int]:
    """
    對 CoordinateRecord 做簡易 K-means，回傳每筆 record 的群集編號（0..k-1）。
    使用純標準庫，無需 scipy/sklearn。
    """
    rng = random.Random(seed)
    # 隨機選 k 個初始中心點
    init_indices = rng.sample(range(len(records)), k)
    centroids = [(records[i].x, records[i].y) for i in init_indices]

    assignments = [0] * len(records)
    for _ in range(max_iter):
        # 分配步驟
        new_assignments = []
        for r in records:
            dists = [math.hypot(r.x - cx, r.y - cy) for cx, cy in centroids]
            new_assignments.append(dists.index(min(dists)))

        # 更新中心
        new_centroids = []
        for ki in range(k):
            members = [records[j] for j, a in enumerate(new_assignments) if a == ki]
            if members:
                cx = sum(m.x for m in members) / len(members)
                cy = sum(m.y for m in members) / len(members)
                new_centroids.append((cx, cy))
            else:
                new_centroids.append(centroids[ki])

        if new_assignments == assignments and new_centroids == centroids:
            break
        assignments = new_assignments
        centroids = new_centroids

    return assignments


# ==========================================
# 隨機數生成與情境生成邏輯
# ==========================================
def stable_seed(master_seed: int, *parts: Any) -> int:
    material = "|".join([str(master_seed), *(str(p) for p in parts)])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % (2**32)


def _rng_with_audit(audit_rows, master_seed, random_object, *parts):
    seed = stable_seed(master_seed, random_object, *parts)
    audit_rows.append({
        "random_object": random_object,
        "parts": "|".join(str(p) for p in parts),
        "seed": seed,
    })
    return random.Random(seed)


def generate_scenarios(
    disaster_ids: list[str],
    ccp_ids: list[str],
    hospital_ids: list[str],
    scenario_ids: list[str] | None = None,
    demand_multiplier: float = DEMAND_MULTIPLIER,
    road_capacity_multiplier: float = ROAD_CAPACITY_MULTIPLIER,
    hospital_capacity_multiplier: float = HOSPITAL_CAPACITY_MULTIPLIER,
    num_periods: int = TIME_PERIODS,
    master_seed: int = MASTER_SEED,
    apply_omega: bool = True,
    disaster_cluster: dict[str, int] | None = None,
    n_clusters: int = SCENARIO_SPATIAL_CLUSTERS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    apply_omega=True  : 每個情境抽全局 omega 與空間 omega（隨機情境用）
    apply_omega=False : 所有 omega 固定為 1.0（B00 基準場景用）
    disaster_cluster  : {disaster_id: cluster_int}，None 時不套用空間異質性
    """
    audit_rows: list[dict[str, Any]] = []

    if scenario_ids is None:
        scenario_ids = [f"S{idx + 1:03d}" for idx in range(SCENARIOS)]

    period_ids = [f"T{idx + 1:03d}" for idx in range(num_periods)]
    scenario_probability = 1.0 / len(scenario_ids)

    demand: dict = {}
    road_ij: dict = {}
    road_jh: dict = {}
    hospital_capacity: dict = {}

    for scenario_id in scenario_ids:
        if apply_omega:
            # 全局乘數（整體規模；受 USE_SCENARIO_OMEGA 開關控制）
            if USE_SCENARIO_OMEGA:
                omega_demand   = _rng_with_audit(audit_rows, master_seed, "omega_demand",   scenario_id).uniform(SCENARIO_OMEGA_LOW, SCENARIO_OMEGA_HIGH)
                omega_road     = _rng_with_audit(audit_rows, master_seed, "omega_road",     scenario_id).uniform(SCENARIO_OMEGA_LOW, SCENARIO_OMEGA_HIGH)
                omega_hospital = _rng_with_audit(audit_rows, master_seed, "omega_hospital", scenario_id).uniform(SCENARIO_OMEGA_LOW, SCENARIO_OMEGA_HIGH)
            else:
                omega_demand = omega_road = omega_hospital = 1.0
            # 空間乘數（各群集的需求集中度）
            if disaster_cluster is not None:
                spatial_omega = {
                    ki: _rng_with_audit(audit_rows, master_seed, "omega_spatial", scenario_id, ki).uniform(
                        SCENARIO_SPATIAL_OMEGA_LOW, SCENARIO_SPATIAL_OMEGA_HIGH
                    )
                    for ki in range(n_clusters)
                }
                # 正規化：依群集內災區數加權，使加權平均 = 1
                # → 空間乘數只做「重分配」，期望總需求不變（總量由全局 omega 控制）
                if NORMALIZE_SPATIAL_OMEGA:
                    cluster_counts = {ki: 0 for ki in range(n_clusters)}
                    for cid in disaster_cluster.values():
                        cluster_counts[cid] = cluster_counts.get(cid, 0) + 1
                    total_areas = sum(cluster_counts.values())
                    weighted_mean = sum(
                        cluster_counts.get(ki, 0) * w for ki, w in spatial_omega.items()
                    ) / total_areas
                    if weighted_mean > 1e-12:
                        spatial_omega = {ki: w / weighted_mean for ki, w in spatial_omega.items()}
            else:
                spatial_omega = None
        else:
            omega_demand = omega_road = omega_hospital = 1.0
            spatial_omega = None

        demand[scenario_id] = {}
        for period_idx, period_id in enumerate(period_ids, start=1):
            demand[scenario_id][period_id] = {}
            for disaster_id in disaster_ids:
                rng = _rng_with_audit(audit_rows, master_seed, "demand", scenario_id, period_id, disaster_id)
                total_new = rng.uniform(DEMAND_UNIFORM_LOW, DEMAND_UNIFORM_HIGH) * demand_multiplier * omega_demand
                # 套用空間群集乘數
                if spatial_omega is not None:
                    ki = disaster_cluster.get(disaster_id, 0)
                    total_new *= spatial_omega[ki]
                demand[scenario_id][period_id][disaster_id] = {
                    sev: total_new * SEVERITY_PROBABILITY[sev]
                    for sev in SEVERITY_LEVELS
                }

        road_ij[scenario_id] = {}
        for disaster_id in disaster_ids:
            road_ij[scenario_id][disaster_id] = {}
            for ccp_id in ccp_ids:
                rng = _rng_with_audit(audit_rows, master_seed, "road_ij", scenario_id, disaster_id, ccp_id)
                first_avail = rng.uniform(0.0, 0.4) * omega_road
                rec_rng = _rng_with_audit(audit_rows, master_seed, "road_ij_recovery", scenario_id, disaster_id, ccp_id)
                recovery_rate = rec_rng.uniform(0.05, 0.08)
                road_ij[scenario_id][disaster_id][ccp_id] = {
                    period_id: min(first_avail * road_capacity_multiplier + recovery_rate * (pidx - 1), 1.0)
                    for pidx, period_id in enumerate(period_ids, start=1)
                }

        road_jh[scenario_id] = {}
        for ccp_id in ccp_ids:
            road_jh[scenario_id][ccp_id] = {}
            for hospital_id in hospital_ids:
                rng = _rng_with_audit(audit_rows, master_seed, "road_jh", scenario_id, ccp_id, hospital_id)
                first_avail = rng.uniform(0.0, 0.4) * omega_road
                rec_rng = _rng_with_audit(audit_rows, master_seed, "road_jh_recovery", scenario_id, ccp_id, hospital_id)
                recovery_rate = rec_rng.uniform(0.05, 0.08)
                road_jh[scenario_id][ccp_id][hospital_id] = {
                    period_id: min(first_avail * road_capacity_multiplier + recovery_rate * (pidx - 1), 1.0)
                    for pidx, period_id in enumerate(period_ids, start=1)
                }

        hospital_capacity[scenario_id] = {}
        for hospital_id in hospital_ids:
            rng = _rng_with_audit(audit_rows, master_seed, "hospital_capacity", scenario_id, hospital_id)
            first_cap = rng.uniform(30.0, 50.0) * hospital_capacity_multiplier * omega_hospital
            hospital_capacity[scenario_id][hospital_id] = {
                period_id: first_cap * (0.9 ** (pidx - 1))
                for pidx, period_id in enumerate(period_ids, start=1)
            }

    scenario_data = {
        "probability": {s: scenario_probability for s in scenario_ids},
        "demand": demand,
        "road_availability_ij": road_ij,
        "road_availability_jh": road_jh,
        "hospital_receiving_capacity": hospital_capacity,
    }
    return scenario_data, audit_rows


def _average_nested_by_scenario(scenario_values, scenario_ids):
    first = scenario_values[scenario_ids[0]]
    if isinstance(first, dict):
        return {
            k: _average_nested_by_scenario(
                {s: scenario_values[s][k] for s in scenario_ids}, scenario_ids
            )
            for k in first
        }
    return sum(float(scenario_values[s]) for s in scenario_ids) / len(scenario_ids)


def validate_instance(instance: dict[str, Any]) -> None:
    sets = instance["sets"]
    for set_name in ("I", "J", "H", "L", "L_transfer", "T", "S"):
        if len(sets[set_name]) != len(set(sets[set_name])):
            raise ValueError(f"Set {set_name} contains duplicated indices")

    probabilities = instance["scenario_data"]["probability"]
    probability_sum = sum(float(v) for v in probabilities.values())
    if abs(probability_sum - 1.0) > 1e-9:
        raise ValueError(f"Scenario probability must sum to 1, got {probability_sum}")

    dm = instance["distance_matrices"]
    max_dist_ij = max(max(d.values()) for d in dm["distance_ij_m"].values()) if dm["distance_ij_m"] else 0
    max_dist_jh = max(max(d.values()) for d in dm["distance_jh_m"].values()) if dm["distance_jh_m"] else 0
    estimated_max_travel_time = max(max_dist_ij, max_dist_jh) / ASSUMED_SPEED_MPS

    if estimated_max_travel_time > PERIOD_DURATION_SEC:
        warnings.warn(
            f"[模型假設警訊] 最大單程預估旅行時間 ({estimated_max_travel_time/60:.2f} 分鐘) "
            f"已超過設定之期長 ({PERIOD_DURATION_SEC/60:.2f} 分鐘)。"
        )

    def _reject_negative(value, path="instance"):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            if value < 0:
                raise ValueError(f"Negative value at {path}: {value}")
            return
        if isinstance(value, Mapping):
            for k, child in value.items():
                _reject_negative(child, f"{path}.{k}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                _reject_negative(child, f"{path}[{idx}]")

    _reject_negative(instance)


def generate_data(
    sample_ratio: float | None = None,
    ccp_sample_size: int | None = CCP_SAMPLE_SIZE,
    scale: str | None = None,
) -> dict[str, Any]:
    """Generate an instance from a named scale profile or the legacy ratio interface.

    With no arguments, ``EXPERIMENT_SCALE`` is used.  Passing ``sample_ratio``
    selects the backward-compatible ratio branch; passing ``scale`` explicitly
    always takes precedence over legacy sampling arguments.
    """
    profile = resolve_scale(EXPERIMENT_SCALE if scale is None else scale) if (
        scale is not None or sample_ratio is None
    ) else None
    if profile is None:
        if not (0 < float(sample_ratio) <= 1.0):
            raise ValueError(f"sample_ratio must be in (0, 1.0], got {sample_ratio}")
        if ccp_sample_size is not None and (not isinstance(ccp_sample_size, int) or ccp_sample_size < 1):
            raise ValueError(f"ccp_sample_size must be a positive int or None, got {ccp_sample_size}")

    all_disaster_records = read_coordinate_csv(DATA_DIR / DISASTER_CSV)
    all_ccp_records      = read_coordinate_csv(DATA_DIR / CCP_CSV)
    all_hospital_records = read_coordinate_csv(DATA_DIR / HOSPITAL_CSV)

    full_n_disaster = len(all_disaster_records)
    full_n_ccp      = len(all_ccp_records)
    full_n_hospital = len(all_hospital_records)

    if profile is not None:
        requested = {
            "n_disaster": profile["n_disaster"],
            "n_ccp": profile["n_ccp"],
            "n_hospital": profile["n_hospital"],
        }
        available = {
            "n_disaster": full_n_disaster,
            "n_ccp": full_n_ccp,
            "n_hospital": full_n_hospital,
        }
        for key, requested_count in requested.items():
            if requested_count > available[key]:
                raise ValueError(
                    f"Scale {profile['scale']!r} requests {key}={requested_count}, "
                    f"but only {available[key]} records are available"
                )
        _n_ccp = profile["n_ccp"]
    else:
        _n_ccp = (
            min(ccp_sample_size, full_n_ccp)
            if ccp_sample_size is not None
            else full_n_ccp
        )
    if _n_ccp < full_n_ccp:
        if SCALE_SAMPLING_MODE == "nested":
            # 巢狀抽樣：固定 seed 洗牌一次後取前綴，使
            # J=20 ⊂ J=30 ⊂ J=40 ⊂ J=50（與災區 / 醫院的作法一致）。
            # 這樣掃描 |J| 時，小的候選集合是大的子集合，最佳值隨 |J| 單調
            # 不增，求解難度的差異才能純粹歸因於候選點數量。
            ccp_order = list(all_ccp_records)
            random.Random(stable_seed(MASTER_SEED, "scale_nested", "ccp")).shuffle(ccp_order)
            ccp_id_set  = {r.id for r in ccp_order[:_n_ccp]}
        else:
            ccp_rng     = random.Random(stable_seed(MASTER_SEED, "ccp_selection", _n_ccp))
            sampled_ccp = ccp_rng.sample(all_ccp_records, _n_ccp)
            ccp_id_set  = {r.id for r in sampled_ccp}
        ccp_records = [r for r in all_ccp_records if r.id in ccp_id_set]
    else:
        ccp_records = all_ccp_records

    if profile is not None:
        # Nested deterministic sampling: small ⊂ medium ⊂ large ⊂ full.
        disaster_order = list(all_disaster_records)
        hospital_order = list(all_hospital_records)
        random.Random(stable_seed(MASTER_SEED, "scale_nested", "disaster")).shuffle(disaster_order)
        random.Random(stable_seed(MASTER_SEED, "scale_nested", "hospital")).shuffle(hospital_order)
        disaster_id_set = {r.id for r in disaster_order[:profile["n_disaster"]]}
        hospital_id_set = {r.id for r in hospital_order[:profile["n_hospital"]]}
        disaster_records = [r for r in all_disaster_records if r.id in disaster_id_set]
        hospital_records = [r for r in all_hospital_records if r.id in hospital_id_set]
    elif float(sample_ratio) < 1.0:
        sampling_rng = random.Random(MASTER_SEED)
        n_disaster = max(1, math.ceil(full_n_disaster * float(sample_ratio)))
        n_hospital = max(1, math.ceil(full_n_hospital * float(sample_ratio)))
        sampled_disaster = sampling_rng.sample(all_disaster_records, n_disaster)
        sampled_hospital = sampling_rng.sample(all_hospital_records,  n_hospital)
        disaster_id_set  = {r.id for r in sampled_disaster}
        hospital_id_set  = {r.id for r in sampled_hospital}
        disaster_records = [r for r in all_disaster_records if r.id in disaster_id_set]
        hospital_records = [r for r in all_hospital_records  if r.id in hospital_id_set]
    else:
        disaster_records = all_disaster_records
        hospital_records = all_hospital_records

    disaster_ids = [r.id for r in disaster_records]
    ccp_ids      = [r.id for r in ccp_records]
    hospital_ids = [r.id for r in hospital_records]

    actual_ccp_count = len(ccp_ids)
    if profile is not None:
        demand_scale = float(profile["demand_scale"])
        ccp_scale = float(profile["ccp_scale"])
        hospital_scale = float(profile["hospital_scale"])
        ccp_resource_scale = demand_scale
        sampling_mode = "nested_profile"
    else:
        ccp_resource_scale = (
            actual_ccp_count / full_n_ccp
            if SCALE_CCP_TOTAL_RESOURCES and full_n_ccp > 0
            else 1.0
        )
        demand_scale = ccp_resource_scale
        ccp_scale = ccp_resource_scale
        hospital_scale = 1.0
        sampling_mode = "legacy_ratio"

    scenario_ids = [f"S{idx + 1:03d}" for idx in range(SCENARIOS)]
    period_ids   = [f"T{idx + 1:03d}" for idx in range(TIME_PERIODS)]

    distance_ij_m = _matrix(disaster_records, ccp_records,      COORDINATE_SYSTEM)
    distance_jh_m = _matrix(ccp_records,      hospital_records, COORDINATE_SYSTEM)
    cap_ij  = {i: {j: 80.0 for j in ccp_ids}      for i in disaster_ids}
    cap_jh  = {j: {h: 80.0 for h in hospital_ids} for j in ccp_ids}
    cost_ij = _transport_cost(distance_ij_m)
    cost_jh = _transport_cost(distance_jh_m)

    deterministic_parameters = _build_deterministic_parameters(
        ccp_ids,
        hospital_ids,
        ccp_resource_scale=ccp_resource_scale,
        demand_scale=demand_scale,
        hospital_scale=hospital_scale,
        ccp_scale=ccp_scale,
    )
    resource_scaling = {
        "scale": profile["scale"] if profile is not None else None,
        "demand_scale": demand_scale,
        "ccp_scale": ccp_scale,
        "hospital_scale": hospital_scale,
        "ccp_upper_bound_scaling": (
            profile.get("ccp_upper_bound_scaling") if profile is not None else "legacy"
        ),
        "param_calibration_basis": {
            "n_disaster": PARAM_CALIB_N_DISASTER,
            "n_ccp": PARAM_CALIB_N_CCP,
            "n_hospital": PARAM_CALIB_N_HOSPITAL,
        },
        "ccp_total_resources_scaled": SCALE_CCP_TOTAL_RESOURCES,
        "base_ccp_count": full_n_ccp,
        "actual_ccp_count": actual_ccp_count,
        "ccp_resource_scale": ccp_resource_scale,
        "rounding": CCP_RESOURCE_SCALE_ROUNDING,
        "base_total_available_staff": float(PARAMETERS["total_available_staff"]),
        "scaled_total_available_staff": deterministic_parameters["total_available_staff"],
        "base_total_available_ccp_ambulances": float(PARAMETERS["total_available_ccp_ambulances"]),
        "scaled_total_available_ccp_ambulances": deterministic_parameters["total_available_ccp_ambulances"],
        "scaled_ccp_staff_upper_bound": next(iter(deterministic_parameters["ccp_staff_upper_bound"].values())),
        "scaled_ccp_ambulance_upper_bound": next(iter(deterministic_parameters["ccp_ambulance_upper_bound"].values())),
        "scaled_ccp_supply_upper_bound": next(iter(deterministic_parameters["ccp_supply_upper_bound"].values())),
        "scaled_ccp_physical_capacity_by_severity": deterministic_parameters["ccp_physical_capacity_by_severity"],
        "scaled_hospital_supply_upper_bound": next(iter(deterministic_parameters["hospital_supply_upper_bound"].values())),
        "scaled_hospital_ambulance_fleet": next(iter(deterministic_parameters["hospital_ambulance_fleet"].values())),
    }

    # 地理群集（受 USE_SPATIAL_KMEANS 開關控制）
    if USE_SPATIAL_KMEANS:
        n_clusters = min(
            profile["spatial_clusters"] if profile is not None else SCENARIO_SPATIAL_CLUSTERS,
            len(disaster_records),
        )
        cluster_assignments = _kmeans_cluster(
            disaster_records, n_clusters, seed=MASTER_SEED
        )
        disaster_cluster = {r.id: c for r, c in zip(disaster_records, cluster_assignments)}
        cluster_sizes = {ki: sum(1 for c in cluster_assignments if c == ki) for ki in range(n_clusters)}
    else:
        n_clusters = 0
        disaster_cluster = None
        cluster_sizes = {}

    # 隨機情境（apply_omega=True，含空間異質性）
    scenario_data, seed_audit = generate_scenarios(
        disaster_ids, ccp_ids, hospital_ids,
        disaster_cluster=disaster_cluster,
        n_clusters=n_clusters,
    )

    # 基準場景 B00（apply_omega=False，保持標準基準）
    baseline_scenario_data, baseline_seed_audit = generate_scenarios(
        disaster_ids, ccp_ids, hospital_ids,
        scenario_ids=["B00"],
        demand_multiplier=1.0,
        road_capacity_multiplier=1.0,
        hospital_capacity_multiplier=1.0,
        num_periods=TIME_PERIODS,
        master_seed=MASTER_SEED,
        apply_omega=False,
        disaster_cluster=None,
    )
    seed_audit.extend(baseline_seed_audit)

    deterministic_expected_value = {
        "demand":                      _average_nested_by_scenario(scenario_data["demand"],                      scenario_ids),
        "road_availability_ij":        _average_nested_by_scenario(scenario_data["road_availability_ij"],        scenario_ids),
        "road_availability_jh":        _average_nested_by_scenario(scenario_data["road_availability_jh"],        scenario_ids),
        "hospital_receiving_capacity": _average_nested_by_scenario(scenario_data["hospital_receiving_capacity"], scenario_ids),
    }

    deterministic_baseline = {
        "multipliers": {
            "demand_multiplier": 1.0,
            "road_capacity_multiplier": 1.0,
            "hospital_capacity_multiplier": 1.0,
        },
        "scenario_label": "B00",
        "demand":                      baseline_scenario_data["demand"]["B00"],
        "road_availability_ij":        baseline_scenario_data["road_availability_ij"]["B00"],
        "road_availability_jh":        baseline_scenario_data["road_availability_jh"]["B00"],
        "hospital_receiving_capacity": baseline_scenario_data["hospital_receiving_capacity"]["B00"],
    }

    instance = {
        "metadata": {
            "master_seed": MASTER_SEED,
            "coordinate_system": COORDINATE_SYSTEM,
            "num_scenarios": SCENARIOS,
            "num_periods": TIME_PERIODS,
            "multipliers": {
                "demand_multiplier": DEMAND_MULTIPLIER,
                "road_capacity_multiplier": ROAD_CAPACITY_MULTIPLIER,
                "hospital_capacity_multiplier": HOSPITAL_CAPACITY_MULTIPLIER,
            },
            "scenario_omega_range": [SCENARIO_OMEGA_LOW, SCENARIO_OMEGA_HIGH],
            "scenario_spatial_clusters": n_clusters,
            "scenario_spatial_omega_range": [SCENARIO_SPATIAL_OMEGA_LOW, SCENARIO_SPATIAL_OMEGA_HIGH],
            "normalize_spatial_omega": NORMALIZE_SPATIAL_OMEGA,
            "cluster_sizes": cluster_sizes,
            "scale": profile["scale"] if profile is not None else None,
            "sampling_mode": sampling_mode,
            "sample_ratio": sample_ratio if profile is None else None,
            "ccp_sample_size": ccp_sample_size if profile is None else profile["n_ccp"],
            "demand_scale": demand_scale,
            "hospital_scale": hospital_scale,
            "resource_scaling": resource_scaling,
            "sampled_counts": {
                "disaster_areas": len(disaster_ids),
                "ccps": len(ccp_ids),
                "hospitals": len(hospital_ids),
            },
        },
        "sets": {
            "I": disaster_ids,
            "J": ccp_ids,
            "H": hospital_ids,
            "L": list(SEVERITY_LEVELS),
            "L_transfer": list(TRANSFER_SEVERITY_LEVELS),
            "T": period_ids,
            "S": scenario_ids,
        },
        "coordinates": {
            "disaster_areas": [r.asdict() for r in disaster_records],
            "ccps":           [r.asdict() for r in ccp_records],
            "hospitals":      [r.asdict() for r in hospital_records],
        },
        "distance_matrices": {
            "distance_ij_m": distance_ij_m,
            "distance_jh_m": distance_jh_m,
        },
        "road_capacity": {
            "cap_ij": cap_ij,
            "cap_jh": cap_jh,
        },
        "transport_cost": {
            "cost_ij": cost_ij,
            "cost_jh": cost_jh,
        },
        "deterministic_parameters": deterministic_parameters,
        "scenario_data": scenario_data,
        "deterministic_data": {
            "baseline":       deterministic_baseline,
            "expected_value": deterministic_expected_value,
        },
        "random_seed_audit": seed_audit,
        "generation_assumptions": {
            "severity_probability":         SEVERITY_PROBABILITY,
            "demand_uniform_range":         [DEMAND_UNIFORM_LOW, DEMAND_UNIFORM_HIGH],
            "scenario_omega_range":         [SCENARIO_OMEGA_LOW, SCENARIO_OMEGA_HIGH],
            "scenario_spatial_clusters":    n_clusters,
            "scenario_spatial_omega_range": [SCENARIO_SPATIAL_OMEGA_LOW, SCENARIO_SPATIAL_OMEGA_HIGH],
            "normalize_spatial_omega":      NORMALIZE_SPATIAL_OMEGA,
            "road_capacity_formula":        "distance_m * 0.05",
            "transport_cost_formula":       "100 + 150 * distance_m / 1000",
            "hospital_capacity_decay":      "period_1_capacity * 0.9^(t - 1)",
        },
        "disaster_cluster": disaster_cluster,
    }

    validate_instance(instance)
    return instance


if __name__ == "__main__":
    print("Generating data...")
    data = generate_data()
    print("Data generated successfully.")
