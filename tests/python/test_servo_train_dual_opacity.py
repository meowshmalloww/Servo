from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch


REPOSITORY = Path(__file__).resolve().parents[2]
TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location(
    "servo_train_dual_opacity", TRAINER_PATH
)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)


class DualOpacityTests(unittest.TestCase):
    def dataset(self) -> SimpleNamespace:
        return SimpleNamespace(
            points=np.asarray([[0.0, 0.0, 1.0], [0.1, 0.0, 1.0]], dtype=np.float32),
            colors=np.asarray([[0.2, 0.4, 0.6], [0.8, 0.6, 0.4]], dtype=np.float32),
        )

    def test_dual_initialization_preserves_legacy_rgb_opacity(self) -> None:
        parameters = servo_train.create_parameters(
            self.dataset(), sh_degree=0, device="cpu", dual_opacity=True
        )

        geometry = servo_train.gaussian_opacities(parameters, geometry_only=True)
        appearance = servo_train.gaussian_opacities(parameters)

        torch.testing.assert_close(geometry, torch.full((2,), 0.99))
        torch.testing.assert_close(appearance, torch.full((2,), 0.1))

    def test_legacy_configuration_has_one_shared_opacity(self) -> None:
        parameters = servo_train.create_parameters(
            self.dataset(), sh_degree=0, device="cpu", dual_opacity=False
        )

        self.assertNotIn("appearanceOpacityGates", parameters)
        torch.testing.assert_close(
            servo_train.gaussian_opacities(parameters), torch.full((2,), 0.1)
        )

    def test_optimizer_tracks_gate_for_gsplat_densification(self) -> None:
        parameters = servo_train.create_parameters(
            self.dataset(), sh_degree=0, device="cpu", dual_opacity=True
        )
        optimizers = servo_train.create_optimizers(parameters)

        self.assertEqual(set(parameters), set(optimizers))
        self.assertIn("appearanceOpacityGates", optimizers)

    def test_dual_checkpoint_requires_appearance_gate(self) -> None:
        parameters = servo_train.create_parameters(
            self.dataset(), sh_degree=0, device="cpu", dual_opacity=False
        )
        state = {name: value.detach() for name, value in parameters.items()}

        with self.assertRaisesRegex(
            servo_train.TrainingError, "appearanceOpacityGates"
        ):
            servo_train.parameters_from_state(
                state, device="cpu", dual_opacity=True
            )


class DiagnosticExperimentIdentityTests(unittest.TestCase):
    def config(self, output: Path) -> dict:
        value = {
            "configurationHash": "sha256:" + "1" * 64,
            "pipelineCodeHash": "sha256:" + "2" * 64,
            "trainingInputHash": "sha256:" + "3" * 64,
            "output": str(output),
            "seed": 42,
        }
        value["experimentConfigurationHash"] = "sha256:" + hashlib.sha256(
            servo_train.canonical_json(value)
        ).hexdigest()
        return value

    def test_fresh_output_and_identity_matched_resume_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            config = self.config(output)
            servo_train.validate_experiment_configuration_hash(config)
            servo_train.prepare_training_output(output, config)
            servo_train.prepare_training_output(output, config)
            written = json.loads(
                (output / "training-config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(written, config)

    def test_nonempty_unbound_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            output.mkdir()
            (output / "foreign.txt").write_text("owned", encoding="utf-8")
            with self.assertRaisesRegex(servo_train.TrainingError, "nonempty"):
                servo_train.prepare_training_output(output, self.config(output))

    def test_changed_config_fails_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.config(Path(temporary) / "run")
            config["seed"] = 43
            with self.assertRaisesRegex(
                servo_train.TrainingError, "does not match"
            ):
                servo_train.validate_experiment_configuration_hash(config)


class CrossViewGeometryTests(unittest.TestCase):
    def camera(self, x: float = 0.0) -> torch.Tensor:
        value = torch.eye(4).unsqueeze(0)
        value[:, 0, 3] = x
        return value

    def calibration(self) -> torch.Tensor:
        return torch.tensor(
            [[[4.0, 0.0, 1.5], [0.0, 4.0, 1.5], [0.0, 0.0, 1.0]]]
        )

    def test_identical_planar_depth_is_consistent_after_translation(self) -> None:
        source = torch.full((1, 4, 4, 1), 2.0, requires_grad=True)
        target = torch.full((1, 4, 4, 1), 2.0, requires_grad=True)
        alpha = torch.ones_like(source)

        loss, samples = servo_train.cross_view_depth_consistency_loss(
            source,
            alpha,
            self.camera(0.0),
            self.calibration(),
            target,
            alpha,
            self.camera(0.1),
            self.calibration(),
        )

        self.assertGreater(samples, 0)
        torch.testing.assert_close(loss, torch.tensor(0.0))

    def test_inconsistent_target_depth_has_positive_loss_and_gradients(self) -> None:
        source = torch.full((1, 4, 4, 1), 2.0, requires_grad=True)
        target = torch.full((1, 4, 4, 1), 2.4, requires_grad=True)
        alpha = torch.ones_like(source)

        loss, samples = servo_train.cross_view_depth_consistency_loss(
            source,
            alpha,
            self.camera(),
            self.calibration(),
            target,
            alpha,
            self.camera(),
            self.calibration(),
        )
        loss.backward()

        self.assertEqual(samples, 16)
        self.assertGreater(float(loss.detach()), 0.0)
        self.assertGreater(float(source.grad.abs().sum()), 0.0)
        self.assertGreater(float(target.grad.abs().sum()), 0.0)

    def sparse_pair_samples(self, count: int = 64) -> dict:
        pixels = np.asarray(
            [[float(index % 4), float((index // 4) % 4)] for index in range(count)],
            dtype=np.float32,
        )
        return {
            "pointIds": np.arange(count, dtype=np.int64),
            "sourcePixels": pixels,
            "sourceDepths": np.full(count, 2.0, dtype=np.float32),
            "targetPixels": pixels.copy(),
            "targetDepths": np.full(count, 2.0, dtype=np.float32),
        }

    def test_sparse_track_pair_uses_external_camera_z_for_both_views(self) -> None:
        source = torch.full((1, 4, 4, 1), 2.0, requires_grad=True)
        target = torch.full((1, 4, 4, 1), 2.4, requires_grad=True)
        alpha = torch.ones_like(source)

        loss, valid, available = servo_train.sparse_track_pair_camera_z_loss(
            source,
            alpha,
            target,
            alpha,
            self.sparse_pair_samples(),
            1,
            1,
        )
        loss.backward()

        self.assertEqual(available, 64)
        self.assertEqual(valid, 64)
        self.assertGreater(float(loss.detach()), 0.0)
        # The already-correct source is not moved to agree with the bad target;
        # the external track target keeps its gradient at zero.
        torch.testing.assert_close(source.grad, torch.zeros_like(source.grad))
        self.assertGreater(float(target.grad.abs().sum()), 0.0)

    def test_sparse_track_pair_rejects_low_support(self) -> None:
        depth = torch.full((1, 4, 4, 1), 2.0, requires_grad=True)
        alpha = torch.zeros_like(depth)

        loss, valid, available = servo_train.sparse_track_pair_camera_z_loss(
            depth,
            alpha,
            depth,
            alpha,
            self.sparse_pair_samples(),
            1,
            1,
        )

        self.assertEqual(available, 64)
        self.assertEqual(valid, 0)
        torch.testing.assert_close(loss, torch.tensor(0.0))

    def test_sparse_track_pair_builder_intersects_point_ids(self) -> None:
        records = []
        for index, point_ids in enumerate(([1, 2, 3], [2, 3, 4])):
            records.append(
                servo_train.ImageRecord(
                    name=f"video-000/{index:08d}.png",
                    path=Path(f"{index}.png"),
                    camera_id=1,
                    camera_model="PINHOLE",
                    camera_to_world=np.eye(4, dtype=np.float32),
                    calibration=np.eye(3, dtype=np.float32),
                    width=4,
                    height=4,
                    sparse_pixels=np.asarray(
                        [[0, 0], [1, 1], [2, 2]], dtype=np.float32
                    ),
                    sparse_depths=np.asarray([1, 2, 3], dtype=np.float32),
                    sparse_point_ids=np.asarray(point_ids, dtype=np.int64),
                )
            )

        pairs = servo_train.build_sparse_track_pair_samples(records, {0: 1})

        self.assertEqual(pairs[0]["pointIds"].tolist(), [2, 3])
        self.assertEqual(pairs[0]["sourceDepths"].tolist(), [2.0, 3.0])
        self.assertEqual(pairs[0]["targetDepths"].tolist(), [1.0, 2.0])

    def test_pair_plan_never_uses_heldout_view(self) -> None:
        records = []
        for index in range(4):
            pose = np.eye(4, dtype=np.float32)
            pose[0, 3] = float(index)
            records.append(
                servo_train.ImageRecord(
                    name=f"video-000/{index:08d}.png",
                    path=Path(f"{index}.png"),
                    camera_id=1,
                    camera_model="PINHOLE",
                    camera_to_world=pose,
                    calibration=np.eye(3, dtype=np.float32),
                    width=4,
                    height=4,
                    sparse_pixels=np.empty((0, 2), dtype=np.float32),
                    sparse_depths=np.empty((0,), dtype=np.float32),
                )
            )
        observations = {
            index: frozenset(range(100)) for index in range(len(records))
        }

        pairs, receipt = servo_train.build_cross_view_pair_plan(
            records,
            train_indices=[0, 1, 3],
            sequence_groups=[[0, 1, 2, 3]],
            observation_ids=observations,
            minimum_frame_gap=1,
            maximum_frame_gap=3,
        )

        self.assertNotIn(2, pairs)
        self.assertNotIn(2, pairs.values())
        self.assertEqual(receipt["pairCount"], 3)


if __name__ == "__main__":
    unittest.main()
