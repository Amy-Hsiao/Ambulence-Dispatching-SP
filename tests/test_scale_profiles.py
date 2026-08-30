"""規模 profile 與資源縮放的回歸測試。

2026-08 更新：資料集由「東區」改為「台北市全區」，規模改為
small = I70 / medium = I100 / large = I130，三者 |J| = 50、|H| = 18。
資源縮放的分母固定為 PARAMETERS 的校準規模 (I=129, J=10, H=16)。
"""
import importlib
import math
import sys
import unittest
from pathlib import Path


MODEL_CORE = Path(__file__).resolve().parents[1] / "model core"
if str(MODEL_CORE) not in sys.path:
    sys.path.insert(0, str(MODEL_CORE))

config = importlib.import_module("config")


class ScaleProfileTests(unittest.TestCase):
    # (I, J, H),
    # (staff, ccp_amb, ccp_staff_ub, ccp_amb_ub, ccp_supply_ub, hosp_supply_ub, hosp_fleet),
    # (physical minor, moderate, severe)
    EXPECTED = {
        "small":  ((70, 20, 18),  (299,  72, 57, 10, 1086, 290,  9), (78, 24,  8)),
        "medium": ((100, 20, 18), (427, 103, 81, 14, 1551, 414, 13), (111, 34, 11)),
        "large":  ((130, 20, 18), (555, 134, 105, 19, 2016, 538, 17), (145, 44, 15)),
    }

    @classmethod
    def setUpClass(cls):
        cls.instances = {scale: config.generate_data(scale=scale) for scale in cls.EXPECTED}

    def test_counts_and_scaled_resources(self):
        for scale, (counts, resources, physical) in self.EXPECTED.items():
            with self.subTest(scale=scale):
                instance = self.instances[scale]
                sets = instance["sets"]
                params = instance["deterministic_parameters"]
                actual_counts = (len(sets["I"]), len(sets["J"]), len(sets["H"]))
                self.assertEqual(actual_counts, counts)
                actual_resources = (
                    params["total_available_staff"],
                    params["total_available_ccp_ambulances"],
                    next(iter(params["ccp_staff_upper_bound"].values())),
                    next(iter(params["ccp_ambulance_upper_bound"].values())),
                    next(iter(params["ccp_supply_upper_bound"].values())),
                    next(iter(params["hospital_supply_upper_bound"].values())),
                    next(iter(params["hospital_ambulance_fleet"].values())),
                )
                self.assertEqual(actual_resources, resources)
                self.assertEqual(
                    tuple(params["ccp_physical_capacity_by_severity"][s]
                          for s in config.SEVERITY_LEVELS),
                    physical,
                )

    def test_scaling_drivers_use_calibration_basis(self):
        """縮放分母必須是 PARAMETERS 的校準規模，不是資料檔筆數。"""
        for scale in self.EXPECTED:
            with self.subTest(scale=scale):
                resolved = config.resolve_scale(scale)
                expected_sd = resolved["n_disaster"] / config.PARAM_CALIB_N_DISASTER
                expected_sh = expected_sd * (
                    config.PARAM_CALIB_N_HOSPITAL / resolved["n_hospital"]
                )
                self.assertAlmostEqual(resolved["demand_scale"], expected_sd)
                self.assertAlmostEqual(resolved["hospital_scale"], expected_sh)
                # 預設 demand_only：per-CCP 上限不因候選點數變多而稀釋
                self.assertEqual(config.CCP_UPPER_BOUND_SCALING, "demand_only")
                self.assertAlmostEqual(resolved["ccp_scale"], expected_sd)

    def test_per_ccp_load_mode_preserves_pool_ratio(self):
        """切到 per_ccp_load 時，Σ per-CCP 上限 / 全域池 應與校準情境一致。"""
        original = config.CCP_UPPER_BOUND_SCALING
        try:
            config.CCP_UPPER_BOUND_SCALING = "per_ccp_load"
            resolved = config.resolve_scale("large")
            expected = resolved["demand_scale"] * (
                config.PARAM_CALIB_N_CCP / resolved["n_ccp"]
            )
            self.assertAlmostEqual(resolved["ccp_scale"], expected)
        finally:
            config.CCP_UPPER_BOUND_SCALING = original

    def test_nested_and_reproducible_sampling(self):
        small, medium, large = (self.instances[s] for s in ("small", "medium", "large"))
        for set_name in ("I", "H"):
            self.assertLessEqual(set(small["sets"][set_name]), set(medium["sets"][set_name]))
            self.assertLessEqual(set(medium["sets"][set_name]), set(large["sets"][set_name]))
        repeated = config.generate_data(scale="medium")
        self.assertEqual(repeated["sets"]["I"], medium["sets"]["I"])
        self.assertEqual(repeated["sets"]["H"], medium["sets"]["H"])

    def test_all_scales_share_the_same_ccp_candidates(self):
        """|J| = 20 對三個規模都相同，跨規模的一階決策空間一致。"""
        reference = self.instances["small"]["sets"]["J"]
        for scale in ("medium", "large"):
            self.assertEqual(self.instances[scale]["sets"]["J"], reference)
        self.assertEqual(len(reference), 20)

    def test_global_pool_remains_binding(self):
        """全域醫護池 < Σ per-CCP 上限 → 全域池是綁定約束（跨規模結構一致）。"""
        for scale, instance in self.instances.items():
            params = instance["deterministic_parameters"]
            total_per_ccp_staff = sum(params["ccp_staff_upper_bound"].values())
            self.assertLess(params["total_available_staff"], total_per_ccp_staff, scale)

    def test_opening_count_is_comparable_across_scales(self):
        """全域池 / per-CCP 上限 ≈ 可實際開設的 CCP 數，三規模應相近（約 5~6）。"""
        ratios = []
        for instance in self.instances.values():
            params = instance["deterministic_parameters"]
            per_ccp = next(iter(params["ccp_staff_upper_bound"].values()))
            ratios.append(params["total_available_staff"] / per_ccp)
        self.assertLess(max(ratios) - min(ratios), 1.0, ratios)
        for ratio in ratios:
            self.assertTrue(3.0 <= ratio <= 10.0, ratios)

    def test_demand_grows_with_disaster_count(self):
        """總需求應與 |I| 成正比（per-災區需求分布不隨規模改變）。"""
        per_area = {}
        for scale, instance in self.instances.items():
            demand = instance["scenario_data"]["demand"]
            total = sum(
                sum(sev.values())
                for per_period in demand.values()
                for per_area_map in per_period.values()
                for sev in per_area_map.values()
            )
            per_area[scale] = total / len(demand) / len(instance["sets"]["I"])
        values = list(per_area.values())
        self.assertLess(max(values) - min(values), 0.15 * max(values), per_area)

    def test_intensive_parameters_do_not_scale(self):
        keys = (
            "staff_unit_assignment_cost",
            "ccp_ambulance_unit_assignment_cost",
            "ccp_ambulance_casualty_capacity",
            "hospital_ambulance_casualty_capacity",
            "treatment_duration_by_severity",
            "staff_treatment_rate_by_severity",
            "supply_consumption_by_severity",
            "disaster_area_remaining_penalty_by_severity",
            "ccp_waiting_penalty_by_severity",
        )
        baseline = self.instances["small"]["deterministic_parameters"]
        for scale in ("medium", "large"):
            params = self.instances[scale]["deterministic_parameters"]
            for key in keys:
                self.assertEqual(params[key], baseline[key], f"{scale}: {key}")

    def test_default_profile_and_legacy_ratio_branch(self):
        default_instance = config.generate_data()
        self.assertEqual(default_instance["metadata"]["scale"], config.EXPERIMENT_SCALE)
        legacy = config.generate_data(sample_ratio=1.0)
        self.assertEqual(legacy["metadata"]["sampling_mode"], "legacy_ratio")
        self.assertEqual(
            (len(legacy["sets"]["I"]), len(legacy["sets"]["H"])),
            (config.N_DISASTER_FULL, config.N_HOSPITAL_FULL),
        )

    def test_profiles_fit_within_available_data(self):
        for scale, profile in config.SCALE_PROFILES.items():
            with self.subTest(scale=scale):
                self.assertLessEqual(profile["n_disaster"], config.N_DISASTER_FULL)
                self.assertLessEqual(profile["n_ccp"], config.N_CCP_FULL)
                self.assertLessEqual(profile["n_hospital"], config.N_HOSPITAL_FULL)
                self.assertLessEqual(profile["spatial_clusters"], profile["n_disaster"])


if __name__ == "__main__":
    unittest.main()
