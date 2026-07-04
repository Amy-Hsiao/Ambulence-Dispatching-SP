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
DISASTER_CSV = "east_district_disaster.csv"
CCP_CSV = "east_district_ccp.csv"
HOSPITAL_CSV = "east_district_hospital.csv"

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
SAMPLE_RATIO = 1.0           # East District 直接用全部 I 和 H
CCP_SAMPLE_SIZE = None       # East District 全部 10 個 CCP 都是候選點
SCALE_CCP_TOTAL_RESOURCES = True
CCP_RESOURCE_SCALE_ROUNDING = "ceil"

SP_SCENARIO_SIZE = None
SP_SAMPLE_RATIO = SAMPLE_RATIO
SP_TIME_LIMIT = 3600.0
SP_MIP_GAP = 0.01
SP_PROGRESS_INTERVAL_SEC = 10.0

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
BENDERS_ROOT_CUT_ROUNDS  = 15      # root 節點分數解 user cut 輪數（0 = 關閉 root cuts）
BENDERS_USE_USER_CUTS    = True    # True: root 節點分數解 user cut
BENDERS_CUT_VIOL_REL_TOL = 1e-6    # cut 違反判定：Q_s > θ_s + tol·max(1,|Q_s|)
BENDERS_PARALLEL_ORACLES = 1       # 子問題平行數（1 = 循序；Phase 4 才調大）
BENDERS_EV_WARM_START    = True    # 用 EV 一階解當 master 初始 incumbent

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


def _build_deterministic_parameters(ccp_ids, hospital_ids, ccp_resource_scale=1.0):
    supply_allocation_cost = {
        h: {j: float(PARAMETERS["supply_allocation_cost_unit"]) for j in ccp_ids}
        for h in hospital_ids
    }
    return {
        "ccp_fixed_opening_cost": _indexed_scalar(PARAMETERS["ccp_fixed_opening_cost"], ccp_ids),
        "staff_unit_assignment_cost": float(PARAMETERS["staff_unit_assignment_cost"]),
        "ccp_ambulance_unit_assignment_cost": float(PARAMETERS["ccp_ambulance_unit_assignment_cost"]),
        "supply_allocation_cost_from_hospital_to_ccp": supply_allocation_cost,
        "total_available_staff": _scale_total_resource(PARAMETERS["total_available_staff"], ccp_resource_scale),
        "total_available_ccp_ambulances": _scale_total_resource(PARAMETERS["total_available_ccp_ambulances"], ccp_resource_scale),
        "hospital_supply_upper_bound": _indexed_scalar(PARAMETERS["hospital_supply_upper_bound"], hospital_ids),
        "ccp_staff_upper_bound": _indexed_scalar(PARAMETERS["ccp_staff_upper_bound"], ccp_ids),
        "ccp_ambulance_upper_bound": _indexed_scalar(PARAMETERS["ccp_ambulance_upper_bound"], ccp_ids),
        "ccp_supply_upper_bound": _indexed_scalar(PARAMETERS["ccp_supply_upper_bound"], ccp_ids),
        "hospital_ambulance_fleet": _indexed_scalar(PARAMETERS["hospital_ambulance_fleet"], hospital_ids),
        "ccp_ambulance_casualty_capacity": float(PARAMETERS["ccp_ambulance_casualty_capacity"]),
        "hospital_ambulance_casualty_capacity": float(PARAMETERS["hospital_ambulance_casualty_capacity"]),
        "ccp_physical_capacity_by_severity": PARAMETERS["ccp_physical_capacity_by_severity"],
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
    sample_ratio: float = SAMPLE_RATIO,
    ccp_sample_size: int | None = CCP_SAMPLE_SIZE,
) -> dict[str, Any]:
    if not (0 < sample_ratio <= 1.0):
        raise ValueError(f"sample_ratio must be in (0, 1.0], got {sample_ratio}")
    if ccp_sample_size is not None and (not isinstance(ccp_sample_size, int) or ccp_sample_size < 1):
        raise ValueError(f"ccp_sample_size must be a positive int or None, got {ccp_sample_size}")

    all_disaster_records = read_coordinate_csv(DATA_DIR / DISASTER_CSV)
    all_ccp_records      = read_coordinate_csv(DATA_DIR / CCP_CSV)
    all_hospital_records = read_coordinate_csv(DATA_DIR / HOSPITAL_CSV)

    full_n_disaster = len(all_disaster_records)
    full_n_ccp      = len(all_ccp_records)
    full_n_hospital = len(all_hospital_records)

    _n_ccp = (
        min(ccp_sample_size, full_n_ccp)
        if ccp_sample_size is not None
        else full_n_ccp
    )
    if _n_ccp < full_n_ccp:
        ccp_rng     = random.Random(stable_seed(MASTER_SEED, "ccp_selection", _n_ccp))
        sampled_ccp = ccp_rng.sample(all_ccp_records, _n_ccp)
        ccp_id_set  = {r.id for r in sampled_ccp}
        ccp_records = [r for r in all_ccp_records if r.id in ccp_id_set]
    else:
        ccp_records = all_ccp_records

    if sample_ratio < 1.0:
        sampling_rng = random.Random(MASTER_SEED)
        n_disaster = max(1, math.ceil(full_n_disaster * sample_ratio))
        n_hospital = max(1, math.ceil(full_n_hospital  * sample_ratio))
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
    ccp_resource_scale = (
        actual_ccp_count / full_n_ccp
        if SCALE_CCP_TOTAL_RESOURCES and full_n_ccp > 0
        else 1.0
    )

    scenario_ids = [f"S{idx + 1:03d}" for idx in range(SCENARIOS)]
    period_ids   = [f"T{idx + 1:03d}" for idx in range(TIME_PERIODS)]

    distance_ij_m = _matrix(disaster_records, ccp_records,      COORDINATE_SYSTEM)
    distance_jh_m = _matrix(ccp_records,      hospital_records, COORDINATE_SYSTEM)
    cap_ij  = {i: {j: 80.0 for j in ccp_ids}      for i in disaster_ids}
    cap_jh  = {j: {h: 80.0 for h in hospital_ids} for j in ccp_ids}
    cost_ij = _transport_cost(distance_ij_m)
    cost_jh = _transport_cost(distance_jh_m)

    deterministic_parameters = _build_deterministic_parameters(
        ccp_ids, hospital_ids, ccp_resource_scale=ccp_resource_scale,
    )
    resource_scaling = {
        "ccp_total_resources_scaled": SCALE_CCP_TOTAL_RESOURCES,
        "base_ccp_count": full_n_ccp,
        "actual_ccp_count": actual_ccp_count,
        "ccp_resource_scale": ccp_resource_scale,
        "rounding": CCP_RESOURCE_SCALE_ROUNDING,
        "base_total_available_staff": float(PARAMETERS["total_available_staff"]),
        "scaled_total_available_staff": deterministic_parameters["total_available_staff"],
        "base_total_available_ccp_ambulances": float(PARAMETERS["total_available_ccp_ambulances"]),
        "scaled_total_available_ccp_ambulances": deterministic_parameters["total_available_ccp_ambulances"],
    }

    # 地理群集（受 USE_SPATIAL_KMEANS 開關控制）
    if USE_SPATIAL_KMEANS:
        cluster_assignments = _kmeans_cluster(
            disaster_records, SCENARIO_SPATIAL_CLUSTERS, seed=MASTER_SEED
        )
        disaster_cluster = {r.id: c for r, c in zip(disaster_records, cluster_assignments)}
        cluster_sizes = {ki: sum(1 for c in cluster_assignments if c == ki) for ki in range(SCENARIO_SPATIAL_CLUSTERS)}
    else:
        disaster_cluster = None
        cluster_sizes = {}

    # 隨機情境（apply_omega=True，含空間異質性）
    scenario_data, seed_audit = generate_scenarios(
        disaster_ids, ccp_ids, hospital_ids,
        disaster_cluster=disaster_cluster,
        n_clusters=SCENARIO_SPATIAL_CLUSTERS,
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
            "scenario_spatial_clusters": SCENARIO_SPATIAL_CLUSTERS,
            "scenario_spatial_omega_range": [SCENARIO_SPATIAL_OMEGA_LOW, SCENARIO_SPATIAL_OMEGA_HIGH],
            "normalize_spatial_omega": NORMALIZE_SPATIAL_OMEGA,
            "cluster_sizes": cluster_sizes,
            "sample_ratio": sample_ratio,
            "ccp_sample_size": ccp_sample_size,
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
            "scenario_spatial_clusters":    SCENARIO_SPATIAL_CLUSTERS,
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
