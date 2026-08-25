from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tools.reconstruction import servo_prepare_r31_initial_scale as prepare_r31
from tools.reconstruction import servo_train


class FakePose:
    def __init__(self, matrix: np.ndarray) -> None:
        self._matrix = matrix

    def matrix(self) -> np.ndarray:
        return self._matrix


def reconstruction_for_depths(depths: list[float], focals: list[float] | None = None):
    focals = focals or [100.0] * len(depths)
    images = {}
    cameras = {}
    elements = []
    for index, (depth, focal) in enumerate(zip(depths, focals), start=1):
        matrix = np.asarray(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, depth - 10.0]],
            dtype=np.float64,
        )
        cameras[index] = SimpleNamespace(
            model_name="PINHOLE",
            width=200,
            height=100,
            calibration_matrix=lambda focal=focal: np.asarray(
                [[focal, 0.0, 100.0], [0.0, focal, 50.0], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            ),
        )
        images[index] = SimpleNamespace(
            has_pose=True,
            camera_id=index,
            points2D=[SimpleNamespace(xy=np.asarray([100.0, 50.0]))],
            cam_from_world=lambda matrix=matrix: FakePose(matrix),
        )
        elements.append(SimpleNamespace(image_id=index, point2D_idx=0))
    point = SimpleNamespace(
        xyz=np.asarray([0.0, 0.0, 10.0]),
        track=SimpleNamespace(elements=elements),
    )
    return SimpleNamespace(points3D={7: point}, images=images, cameras=cameras)


class InitialScaleTests(unittest.TestCase):
    def test_projected_track_cap_matches_pinhole_radius(self) -> None:
        caps, stats = servo_train.projected_track_scale_caps(
            reconstruction_for_depths([10.0, 10.0, 10.0]),
            np.asarray([7]),
            normalization_scale=0.5,
            training_factor=1,
            target_radius_pixels=1.75,
            minimum_valid_observations=3,
        )
        self.assertAlmostEqual(float(caps[0]), 5.0 / 100.0 * 1.75, places=6)
        self.assertEqual(stats["eligibleSparsePoints"], 1)
        self.assertFalse(stats["metric"])

    def test_track_median_rejects_single_depth_outlier(self) -> None:
        reconstruction = reconstruction_for_depths(
            [10.0] * 9 + [1_000.0], [100.0] * 10
        )
        caps, _ = servo_train.projected_track_scale_caps(
            reconstruction,
            np.asarray([7]),
            normalization_scale=1.0,
            training_factor=1,
            target_radius_pixels=1.75,
            minimum_valid_observations=3,
        )
        self.assertAlmostEqual(float(caps[0]), 0.175, places=6)

    def test_fewer_than_three_observations_falls_back(self) -> None:
        caps, stats = servo_train.projected_track_scale_caps(
            reconstruction_for_depths([10.0, 10.0]),
            np.asarray([7]),
            normalization_scale=1.0,
            training_factor=1,
            target_radius_pixels=1.75,
            minimum_valid_observations=3,
        )
        self.assertTrue(math.isnan(float(caps[0])))
        self.assertEqual(stats["eligibleSparsePoints"], 0)

    def test_create_parameters_caps_isotropically(self) -> None:
        dataset = SimpleNamespace(
            points=np.asarray(
                [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                dtype=np.float32,
            ),
            colors=np.full((3, 3), 0.5, dtype=np.float32),
            initial_scale_caps=np.asarray([0.1, np.nan, np.nan], dtype=np.float32),
        )
        parameters = servo_train.create_parameters(dataset, 0, "cpu")
        scale = np.exp(parameters["scales"].detach().numpy())
        np.testing.assert_allclose(scale[0], [0.1, 0.1, 0.1], rtol=1e-6)
        np.testing.assert_allclose(scale[1, 0], scale[1], rtol=1e-6)

    def test_r31_generator_is_matched_except_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            base.write_text(
                '{"configurationHash":"sha256:parent","pipelineCodeHash":"sha256:old"}',
                encoding="utf-8",
            )
            control = prepare_r31.build_config(
                base=base,
                treatment="control",
                calibration_quantile=0.90,
                steps=900,
                seed=42,
                output=root / "control",
            )
            treatment = prepare_r31.build_config(
                base=base,
                treatment="projected-footprint",
                calibration_quantile=0.90,
                steps=900,
                seed=42,
                output=root / "treatment",
            )
            self.assertNotIn("initialScalePolicy", control)
            self.assertEqual(
                treatment["initialScalePolicy"]["calibrationQuantile"], 0.90
            )
            self.assertEqual(control["finalFitSteps"], 373)
            self.assertEqual(control["refineScale2dStopIter"], 527)


if __name__ == "__main__":
    unittest.main()
