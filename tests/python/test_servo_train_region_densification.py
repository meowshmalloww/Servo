from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
SPEC = importlib.util.spec_from_file_location("servo_train_region_density", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_train = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_train
SPEC.loader.exec_module(servo_train)


def treatment() -> dict[str, object]:
    return {
        "schema": "servo.diagnostic-region-aware-densification/v1",
        "method": "gsplat-1.5.3-absgrad-tile-footprint-semantic-detail-v1",
        "maximumFootprintFraction": 0.02,
        "depthScaleFraction": 0.37,
        "depthPower": 2.0,
        "minimumStaticConfidence": 0.50,
        "minimumStaticFootprintFraction": 0.50,
        "minimumObservedViewsForBoost": 3,
        "semanticWeights": {
            "unknown": 0.0,
            "sky": 0.0,
            "dynamic": 0.0,
            "vegetation": 0.5,
            "water": 0.5,
            "rigidStatic": 1.0,
            "road": 1.15,
            "boundary": 1.75,
            "roadMarking": 2.5,
            "sign": 3.0,
        },
        "edgeBase": 0.5,
        "edgeScale": 0.08,
        "edgeMaximum": 1.5,
        "residualBase": 0.5,
        "residualScale": 0.15,
        "residualMaximum": 1.5,
        "priorityMinimum": 0.75,
        "priorityMaximum": 3.0,
        "lossesChanged": False,
        "opacityPolicyChanged": False,
        "pruningPolicyChanged": False,
        "generatedViewsUsed": False,
    }


class GradientSource:
    def __init__(self, value: torch.Tensor) -> None:
        self.absgrad = value


class RegionDensificationTests(unittest.TestCase):
    def test_contract_is_sealed_to_nonpublishable_exact_values(self) -> None:
        config = {
            "diagnosticProvenance": {
                "schema": "servo.diagnostic-training-provenance/v1",
                "nonPublishable": True,
            }
        }
        self.assertTrue(
            servo_train.supported_region_densification_contract(
                config, treatment()
            )
        )
        unsafe = treatment()
        unsafe["generatedViewsUsed"] = True
        self.assertFalse(
            servo_train.supported_region_densification_contract(config, unsafe)
        )

    def test_priority_excludes_sky_and_dynamic_and_prioritizes_markings(self) -> None:
        rendered = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
        target = torch.zeros_like(rendered)
        target[:, :, 4:, :] = 1.0
        semantic = torch.ones((1, 8, 8, 1), dtype=torch.int64)
        semantic[:, 0, :, 0] = 17
        semantic[:, 1, :, 0] = 18
        semantic[:, 2, :, 0] = 2
        semantic[:, 3, :, 0] = 12
        confidence = torch.ones((1, 8, 8, 1), dtype=torch.float32)

        priority, static, classes = servo_train.build_region_density_priority(
            rendered, target, semantic, confidence
        )
        self.assertTrue(torch.equal(priority[:, :2], torch.zeros_like(priority[:, :2])))
        self.assertTrue(torch.equal(static[:, :2], torch.zeros_like(static[:, :2])))
        self.assertGreater(float(priority[:, 2].mean()), float(priority[:, 4].mean()))
        self.assertGreater(float(priority[:, 3].mean()), float(priority[:, 2].mean()))
        self.assertTrue(torch.equal(classes[:, 0], torch.zeros_like(classes[:, 0])))

    def test_sampling_uses_pixel_means_and_adaptive_footprints(self) -> None:
        priority = torch.zeros((1, 21, 21, 1), dtype=torch.float32)
        priority[:, 10, 14, 0] = 4.0
        static = torch.ones_like(priority)
        classes = torch.full_like(priority, 2, dtype=torch.int64)
        info = {
            "means2d": torch.tensor([[10.0, 10.0], [10.0, 10.0]]),
            "radii": torch.tensor([[1.0, 1.0], [9.0, 9.0]]),
            "camera_ids": torch.tensor([0, 0]),
            "gaussian_ids": torch.tensor([0, 1]),
            "width": 21,
            "height": 21,
            "n_cameras": 1,
        }
        sampled, valid, sampled_classes = (
            servo_train.sample_region_priority_for_gaussians(
                priority, static, classes, info
            )
        )
        self.assertEqual(float(sampled[0]), 0.0)
        self.assertGreater(float(sampled[1]), 0.0)
        self.assertTrue(torch.all(valid > 0.0))
        self.assertTrue(torch.equal(sampled_classes, torch.tensor([2, 2])))

    def test_state_requires_three_distinct_frames_for_region_evidence(self) -> None:
        params = {"means": torch.zeros((1, 3), dtype=torch.float32)}
        state = {"grad2d": None, "count": None, "radii": None}
        info = {
            "width": 64,
            "height": 48,
            "n_cameras": 1,
            "radii": torch.tensor([[4.0, 4.0]]),
            "gaussian_ids": torch.tensor([0]),
            "depths": torch.tensor([1.0]),
            "tiles_per_gauss": torch.tensor([2.0]),
            "tile_width": 4,
            "tile_height": 3,
            "means2d": GradientSource(torch.tensor([[0.01, 0.01]])),
        }
        for frame in (7, 7, 8, 9):
            servo_train.update_coverage_densification_state(
                params,
                state,
                info,
                key_for_gradient="means2d",
                absgrad=True,
                scene_scale=1.0,
                maximum_footprint_fraction=0.02,
                footprint_power=1.0,
                depth_scale_fraction=0.37,
                depth_power=2.0,
                region_priority=torch.tensor([2.0]),
                region_static_fraction=torch.tensor([1.0]),
                region_classes=torch.tensor([5]),
                frame_index=frame,
            )
        diagnostics = state["coverageDensificationDiagnostics"]
        self.assertEqual(
            [int(diagnostics[key][0]) for key in ("regionView0", "regionView1", "regionView2")],
            [7, 8, 9],
        )
        self.assertEqual(int(diagnostics["regionPeakClass"][0]), 5)


if __name__ == "__main__":
    unittest.main()
