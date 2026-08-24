from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location(
    "servo_train_frame_oversampling", TRAINER_PATH
)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


def _diagnostic_config() -> dict:
    return {
        "diagnosticProvenance": {
            "schema": servo_train.DIAGNOSTIC_PROVENANCE_SCHEMA,
            "nonPublishable": True,
        }
    }


def _record(name: str, anchors: int) -> servo_train.ImageRecord:
    return servo_train.ImageRecord(
        name=name,
        path=Path("images") / name,
        camera_id=0,
        camera_model="PINHOLE",
        camera_to_world=[[1.0, 0.0, 0.0, float(len(name))],
                         [0.0, 1.0, 0.0, 0.0],
                         [0.0, 0.0, 1.0, 0.0],
                         [0.0, 0.0, 0.0, 1.0]],
        calibration=[[40.0, 0.0, 32.0], [0.0, 40.0, 24.0], [0.0, 0.0, 1.0]],
        width=64,
        height=48,
        sparse_pixels=[(0, 0)] * anchors,
        sparse_depths=[(0, 0, 1.0)] * anchors,
    )


def _records() -> list:
    # ImageRecord is a frozen dataclass; construct with the fields that exist.
    # The helper below tolerates field drift by building through __new__.
    return [_record(f"video-000/{index:08d}.png", anchors=1000 + index)
            for index in range(8)]


class FrameOversamplingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record_names = {
            f"video-000/{index:08d}.png": index for index in range(8)
        }

    def test_diagnostic_config_with_valid_frames_is_accepted(self) -> None:
        self.assertTrue(
            servo_train.supported_frame_oversampling_contract(
                _diagnostic_config(),
                schema=servo_train.FRAME_OVERSAMPLING_SCHEMA,
                method=servo_train.FRAME_OVERSAMPLING_METHOD,
                multiplier=3,
                frames=["video-000/00000002.png", "video-000/00000005.png"],
                record_names=self.record_names,
            )
        )

    def test_publishable_config_is_rejected(self) -> None:
        self.assertFalse(
            servo_train.supported_frame_oversampling_contract(
                {},
                schema=servo_train.FRAME_OVERSAMPLING_SCHEMA,
                method=servo_train.FRAME_OVERSAMPLING_METHOD,
                multiplier=3,
                frames=["video-000/00000002.png"],
                record_names=self.record_names,
            )
        )

    def test_multiplier_bounds_are_enforced(self) -> None:
        for multiplier in (1, 9):
            self.assertFalse(
                servo_train.supported_frame_oversampling_contract(
                    _diagnostic_config(),
                    schema=servo_train.FRAME_OVERSAMPLING_SCHEMA,
                    method=servo_train.FRAME_OVERSAMPLING_METHOD,
                    multiplier=multiplier,
                    frames=["video-000/00000002.png"],
                    record_names=self.record_names,
                )
            )

    def test_unknown_or_duplicate_frames_are_rejected(self) -> None:
        self.assertFalse(
            servo_train.supported_frame_oversampling_contract(
                _diagnostic_config(),
                schema=servo_train.FRAME_OVERSAMPLING_SCHEMA,
                method=servo_train.FRAME_OVERSAMPLING_METHOD,
                multiplier=3,
                frames=["video-000/99999999.png"],
                record_names=self.record_names,
            )
        )
        self.assertFalse(
            servo_train.supported_frame_oversampling_contract(
                _diagnostic_config(),
                schema=servo_train.FRAME_OVERSAMPLING_SCHEMA,
                method=servo_train.FRAME_OVERSAMPLING_METHOD,
                multiplier=3,
                frames=["video-000/00000002.png", "video-000/00000002.png"],
                record_names=self.record_names,
            )
        )

    def test_wrong_schema_or_method_is_rejected(self) -> None:
        self.assertFalse(
            servo_train.supported_frame_oversampling_contract(
                _diagnostic_config(),
                schema="other/v1",
                method=servo_train.FRAME_OVERSAMPLING_METHOD,
                multiplier=3,
                frames=["video-000/00000002.png"],
                record_names=self.record_names,
            )
        )


class FrameOversamplingPlanTests(unittest.TestCase):
    def test_multipliers_scale_only_listed_training_frames(self) -> None:
        records = _records()
        train_indices = [0, 1, 2, 3, 4, 5]
        groups = [list(range(8))]

        baseline = servo_train.build_training_sampling_plan(
            records, train_indices, groups
        )
        boosted = servo_train.build_training_sampling_plan(
            records,
            train_indices,
            groups,
            frame_multipliers={2: 4, 5: 2},
        )

        self.assertEqual(baseline.weights[2] * 4, boosted.weights[2])
        self.assertEqual(baseline.weights[5] * 2, boosted.weights[5])
        for index in (0, 1, 3, 4):
            self.assertEqual(baseline.weights[index], boosted.weights[index])
        self.assertEqual(
            len(boosted.epoch_slots),
            len(baseline.epoch_slots)
            - baseline.weights[2]
            - baseline.weights[5]
            + boosted.weights[2]
            + boosted.weights[5],
        )

    def test_every_camera_still_appears_at_least_once(self) -> None:
        records = _records()
        plan = servo_train.build_training_sampling_plan(
            records,
            [0, 1, 2, 3],
            [[0, 1, 2, 3]],
            frame_multipliers={1: 3},
        )
        present = set(plan.epoch_slots)
        self.assertEqual(present, {0, 1, 2, 3})


class SkyHybridScopeTests(unittest.TestCase):
    def _tensors(self):
        alpha = torch.full((1, 4, 4, 1), 1.0)
        alpha[0, 0, 3, 0] = 0.0
        semantic = torch.zeros(1, 4, 4, 1, dtype=torch.long)
        semantic[0, :2] = 17
        evidence = torch.zeros(1, 4, 4, 1, dtype=torch.long)
        evidence[0, 0] = 2
        evidence[0, 1] = 1
        return alpha, semantic, evidence

    def test_restricted_scope_counts_only_certified_sky(self):
        alpha, semantic, evidence = self._tensors()
        _, samples = servo_train.semantic_sky_opacity_loss(
            alpha, semantic, evidence=evidence, tail_weight=0.0)
        self.assertEqual(samples, 4)

    def test_semantic_scope_keeps_full_recall_and_lower_loss(self):
        alpha, semantic, evidence = self._tensors()
        restricted, r_samples = servo_train.semantic_sky_opacity_loss(
            alpha, semantic, evidence=evidence, tail_weight=0.0)
        broad, b_samples = servo_train.semantic_sky_opacity_loss(
            alpha, semantic, evidence=evidence, tail_weight=0.0,
            l1_scope="semantic")
        self.assertEqual(r_samples, 4)
        self.assertEqual(b_samples, 8)
        self.assertLess(float(broad.detach()), float(restricted.detach()))

    def test_tail_bce_gradient_survives_saturation(self):
        alpha = torch.ones((1, 8, 8, 1), requires_grad=True)
        semantic = torch.full((1, 8, 8, 1), 17, dtype=torch.long)
        evidence = torch.ones((1, 8, 8, 1), dtype=torch.long)
        loss, samples = servo_train.semantic_sky_opacity_loss(
            alpha, semantic, evidence=evidence, tail_weight=0.05,
            tail_erosion_radius=1)
        self.assertGreater(samples, 0)
        loss.backward()
        self.assertGreater(float(alpha.grad.abs().sum()), 0.0)

    def test_invalid_l1_scope_is_rejected(self):
        alpha, semantic, evidence = self._tensors()
        with self.assertRaises(servo_train.TrainingError):
            servo_train.semantic_sky_opacity_loss(
                alpha, semantic, evidence=evidence, tail_weight=0.0,
                l1_scope="bogus")


if __name__ == "__main__":
    unittest.main()
