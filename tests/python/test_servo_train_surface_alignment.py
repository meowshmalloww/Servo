from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location(
    "servo_train_surface_alignment", TRAINER_PATH
)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


class DrivingSurfaceAlignmentLossTests(unittest.TestCase):
    def test_aligned_planar_road_has_zero_loss(self) -> None:
        features = torch.tensor(
            [[[[0.0, 1.0, 0.0, 0.10], [0.0, 1.0, 0.0, 0.10]]]],
            requires_grad=True,
        )
        depth_normals = torch.tensor(
            [[[[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]]]]
        )
        alpha = torch.ones((1, 1, 2, 1))
        semantic = torch.ones((1, 1, 2, 1), dtype=torch.int64)
        confidence = torch.ones_like(alpha)

        normal, planar, normal_count, planar_count = (
            servo_train.driving_surface_alignment_loss(
                features, depth_normals, alpha, semantic, confidence
            )
        )

        torch.testing.assert_close(normal, torch.tensor(0.0))
        torch.testing.assert_close(planar, torch.tensor(0.0))
        self.assertEqual(normal_count, 2)
        self.assertEqual(planar_count, 2)

    def test_sign_is_not_regularized_by_the_road_only_loss(self) -> None:
        features = torch.tensor([[[[1.0, 0.0, 0.0, 0.90]]]])
        depth_normals = torch.tensor([[[[0.0, 1.0, 0.0]]]])
        alpha = torch.ones((1, 1, 1, 1))
        semantic = torch.full((1, 1, 1, 1), 12, dtype=torch.int64)
        confidence = torch.ones_like(alpha)

        normal, planar, normal_count, planar_count = (
            servo_train.driving_surface_alignment_loss(
                features, depth_normals, alpha, semantic, confidence
            )
        )

        torch.testing.assert_close(normal, torch.tensor(0.0))
        torch.testing.assert_close(planar, torch.tensor(0.0))
        self.assertEqual(normal_count, 0)
        self.assertEqual(planar_count, 0)

    def test_sky_is_excluded_from_both_losses(self) -> None:
        features = torch.tensor([[[[1.0, 0.0, 0.0, 1.0]]]])
        depth_normals = torch.tensor([[[[0.0, 1.0, 0.0]]]])
        alpha = torch.ones((1, 1, 1, 1))
        semantic = torch.full((1, 1, 1, 1), 17, dtype=torch.int64)
        confidence = torch.ones_like(alpha)

        normal, planar, normal_count, planar_count = (
            servo_train.driving_surface_alignment_loss(
                features, depth_normals, alpha, semantic, confidence
            )
        )

        torch.testing.assert_close(normal, torch.tensor(0.0))
        torch.testing.assert_close(planar, torch.tensor(0.0))
        self.assertEqual(normal_count, 0)
        self.assertEqual(planar_count, 0)


if __name__ == "__main__":
    unittest.main()
