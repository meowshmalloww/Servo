from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location(
    "servo_train_coverage_densification", TRAINER_PATH
)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


class CoverageDensificationTests(unittest.TestCase):
    def accumulate(
        self,
        gradients: list[float],
        footprints: list[float],
        depths: list[float],
        gaussian_ids: list[int] | None = None,
    ) -> dict:
        ids = gaussian_ids or [0] * len(gradients)
        gaussian_count = max(ids) + 1
        params = {"means": torch.zeros((gaussian_count, 3))}
        projected = torch.zeros((len(gradients), 2), requires_grad=True)
        projected.grad = torch.tensor([[value, 0.0] for value in gradients])
        information = {
            "width": 2,
            "height": 2,
            "n_cameras": 1,
            "radii": torch.tensor([[2.0, 1.0]] * len(gradients)),
            "gaussian_ids": torch.tensor(ids, dtype=torch.long),
            "depths": torch.tensor(depths),
            "tiles_per_gauss": torch.tensor(footprints),
            "tile_width": 100,
            "tile_height": 100,
            "means2d": projected,
        }
        state = {"grad2d": None, "count": None, "radii": None}
        servo_train.update_coverage_densification_state(
            params,
            state,
            information,
            key_for_gradient="means2d",
            absgrad=False,
            scene_scale=1.0,
            maximum_footprint_fraction=0.02,
            footprint_power=1.0,
            depth_scale_fraction=0.37,
            depth_power=2.0,
        )
        return state

    def test_broad_observation_dominates_mixed_footprint_score(self) -> None:
        state = self.accumulate([0.001, 0.00005], [64, 1], [1.0, 1.0])
        score = state["grad2d"] / state["count"]
        self.assertAlmostEqual(float(score[0]), 0.0009853846, places=9)
        default = state["coverageDensificationDiagnostics"]
        default_score = default["defaultGrad2d"] / default["defaultCount"]
        self.assertAlmostEqual(float(default_score[0]), 0.000525, places=9)

    def test_equal_small_footprints_match_default_score(self) -> None:
        state = self.accumulate([0.001, 0.00005], [1, 1], [1.0, 1.0])
        score = state["grad2d"] / state["count"]
        self.assertAlmostEqual(float(score[0]), 0.000525, places=9)

    def test_depth_scaling_suppresses_near_camera_floater(self) -> None:
        state = self.accumulate([0.001], [64], [0.1])
        score = state["grad2d"] / state["count"]
        expected = 0.001 * (0.1 / 0.37) ** 2
        self.assertAlmostEqual(float(score[0]), expected, places=9)

    def test_footprint_is_capped_and_radius_matches_default_normalization(self) -> None:
        state = self.accumulate([0.001], [10_000], [1.0])
        diagnostics = state["coverageDensificationDiagnostics"]
        self.assertEqual(diagnostics["maximumFootprint"], 200.0)
        self.assertAlmostEqual(float(state["radii"][0]), 1.0)

    def test_nonfinite_metadata_fails_closed(self) -> None:
        with self.assertRaisesRegex(servo_train.TrainingError, "nonfinite"):
            self.accumulate([0.001], [1], [float("nan")])

    def test_contract_is_diagnostic_only(self) -> None:
        treatment = {
            "schema": "servo.diagnostic-coverage-densification/v1",
            "method": "gsplat-1.5.3-tile-footprint-depth-scaled-v1",
            "footprintSource": "tiles-per-gaussian",
            "maximumFootprintFraction": 0.02,
            "footprintPower": 1.0,
            "depthSource": "camera-space-z",
            "depthScaleFraction": 0.37,
            "depthPower": 2.0,
            "packedRequired": True,
            "surfelAllowed": False,
            "dualOpacityAllowed": False,
            "revisedOpacity": False,
            "lossesChanged": False,
            "opacityPolicyChanged": False,
            "pruningPolicyChanged": False,
        }
        publishable = {}
        diagnostic = {
            "diagnosticProvenance": {
                "schema": "servo.diagnostic-training-provenance/v1",
                "nonPublishable": True,
            }
        }
        self.assertFalse(
            servo_train.supported_coverage_densification_contract(
                publishable, treatment
            )
        )
        self.assertTrue(
            servo_train.supported_coverage_densification_contract(
                diagnostic, treatment
            )
        )


if __name__ == "__main__":
    unittest.main()
