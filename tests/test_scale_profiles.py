import importlib
import sys
import unittest
from pathlib import Path


MODEL_CORE = Path(__file__).resolve().parents[1] / "model core"
if str(MODEL_CORE) not in sys.path:
    sys.path.insert(0, str(MODEL_CORE))

config = importlib.import_module("config")


class ScaleProfileTests(unittest.TestCase):
    EXPECTED = {
        "small":  ((20, 10, 6), (86, 21, 17, 3, 311, 249, 8), (23, 7, 3)),
        "medium": ((40, 10, 10), (171, 41, 33, 6, 621, 298, 9), (45, 14, 5)),
        "large":  ((70, 10, 14), (299, 72, 57, 10, 1086, 373, 12), (78, 24, 8)),
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

    def test_nested_and_reproducible_sampling(self):
        small, medium, large = (self.instances[s] for s in ("small", "medium", "large"))
        for set_name in ("I", "H"):
            self.assertLessEqual(set(small["sets"][set_name]), set(medium["sets"][set_name]))
            self.assertLessEqual(set(medium["sets"][set_name]), set(large["sets"][set_name]))
        repeated = config.generate_data(scale="medium")
        self.assertEqual(repeated["sets"]["I"], medium["sets"]["I"])
        self.assertEqual(repeated["sets"]["H"], medium["sets"]["H"])

    def test_global_pool_remains_binding(self):
        for scale, instance in self.instances.items():
            params = instance["deterministic_parameters"]
            total_per_ccp_staff = sum(params["ccp_staff_upper_bound"].values())
            self.assertLess(params["total_available_staff"], total_per_ccp_staff, scale)

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
        self.assertEqual((len(legacy["sets"]["I"]), len(legacy["sets"]["H"])), (129, 16))


if __name__ == "__main__":
    unittest.main()
