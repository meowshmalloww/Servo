from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_environment.py"
SPEC = importlib.util.spec_from_file_location("servo_environment_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
environment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = environment
SPEC.loader.exec_module(environment)


@dataclass(frozen=True)
class Record:
    width: int
    height: int
    calibration: np.ndarray
    camera_to_world: np.ndarray


def record() -> Record:
    return Record(
        width=4,
        height=2,
        calibration=np.array([[2.0, 0.0, 2.0], [0.0, 2.0, 1.0], [0.0, 0.0, 1.0]]),
        camera_to_world=np.eye(4),
    )


class ObservedDirectionalEnvironmentTests(unittest.TestCase):
    def test_direction_mapping_has_documented_forward_and_up_axes(self) -> None:
        directions = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
        x, y = environment.direction_to_equirectangular_texels(directions, 64, 32)
        np.testing.assert_array_equal(x, np.array([32, 32, 48]))
        np.testing.assert_array_equal(y, np.array([16, 0, 16]))

    def test_build_is_deterministic_and_never_uses_non_sky_pixels(self) -> None:
        image = np.array(
            [
                [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]],
                [[12, 34, 56], [78, 90, 12], [34, 56, 78], [90, 12, 34]],
            ],
            dtype=np.uint8,
        )
        semantic = np.array([[17, 17, 1, 1], [1, 1, 1, 1]], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_descriptor = environment.build_observed_directional_environment(
                [record()], [image], [semantic], Path(first), width=64, height=32
            )
            second_descriptor = environment.build_observed_directional_environment(
                [record()], [image], [semantic], Path(second), width=64, height=32
            )
            self.assertEqual(
                {key: value for key, value in first_descriptor.items() if key != "assetSha256"},
                {key: value for key, value in second_descriptor.items() if key != "assetSha256"},
            )
            loaded = environment.load_observed_directional_environment(
                Path(first), first_descriptor, device="cpu"
            )
            self.assertFalse(first_descriptor["containsGeneratedPixels"])
            self.assertEqual(first_descriptor["sourceSkyPixels"], 2)
            self.assertEqual(first_descriptor["sampledSkyPixels"], 2)
            self.assertGreater(first_descriptor["observedTexels"], 0)
            alpha = loaded.rgba[..., 3]
            self.assertTrue(torch.all((alpha == 0.0) | (alpha == 1.0)))
            self.assertTrue(torch.all(loaded.rgba[..., :3][alpha == 0.0] == 0.0))

    def test_sampling_uses_observed_colour_and_explicit_fallback(self) -> None:
        image = np.full((2, 4, 3), [20, 40, 60], dtype=np.uint8)
        semantic = np.full((2, 4), 17, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            descriptor = environment.build_observed_directional_environment(
                [record()], [image], [semantic], Path(directory), width=64, height=32
            )
            loaded = environment.load_observed_directional_environment(
                Path(directory), descriptor, device="cpu"
            )
            directions = torch.tensor([[[0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]])
            fallback = torch.tensor([[[0.9, 0.8, 0.7], [0.9, 0.8, 0.7]]])
            sampled, coverage = environment.sample_observed_directional_environment(
                loaded, directions, fallback
            )
            self.assertEqual(tuple(sampled.shape), (1, 2, 3))
            self.assertEqual(tuple(coverage.shape), (1, 2, 1))
            self.assertGreaterEqual(float(coverage[0, 0, 0]), 0.0)
            self.assertLessEqual(float(coverage[0, 1, 0]), 1.0)
            torch.testing.assert_close(
                sampled[coverage[..., 0] == 0], fallback[coverage[..., 0] == 0]
            )

    def test_loader_rejects_path_escape_or_hash_tampering(self) -> None:
        image = np.full((2, 4, 3), 120, dtype=np.uint8)
        semantic = np.full((2, 4), 17, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = environment.build_observed_directional_environment(
                [record()], [image], [semantic], root, width=64, height=32
            )
            escaped = dict(descriptor, asset="../outside.png")
            with self.assertRaises(environment.EnvironmentError):
                environment.load_observed_directional_environment(root, escaped, device="cpu")
            tampered = root / descriptor["asset"]
            tampered.write_bytes(b"not-a-png")
            with self.assertRaises(environment.EnvironmentError):
                environment.load_observed_directional_environment(root, descriptor, device="cpu")

    def test_camera_direction_has_no_translation_dependence(self) -> None:
        base = record()
        translated = Record(
            base.width,
            base.height,
            base.calibration,
            np.array([[1.0, 0.0, 0.0, 12.0], [0.0, 1.0, 0.0, -5.0], [0.0, 0.0, 1.0, 2.0], [0.0, 0.0, 0.0, 1.0]]),
        )
        np.testing.assert_allclose(
            environment.world_directions_for_camera(
                base.camera_to_world, base.calibration, base.width, base.height
            ),
            environment.world_directions_for_camera(
                translated.camera_to_world,
                translated.calibration,
                translated.width,
                translated.height,
            ),
        )

    def test_torch_camera_sampler_has_no_translation_dependence(self) -> None:
        image = np.full((2, 4, 3), [30, 60, 90], dtype=np.uint8)
        semantic = np.full((2, 4), 17, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            descriptor = environment.build_observed_directional_environment(
                [record()], [image], [semantic], Path(directory), width=64, height=32
            )
            loaded = environment.load_observed_directional_environment(
                Path(directory), descriptor, device="cpu"
            )
            first = torch.eye(4).unsqueeze(0)
            second = first.clone()
            second[0, :3, 3] = torch.tensor([5.0, -3.0, 11.0])
            calibration = torch.tensor([[[2.0, 0.0, 2.0], [0.0, 2.0, 1.0], [0.0, 0.0, 1.0]]])
            fallback = torch.tensor([[0.9, 0.8, 0.7]])
            first_rgb, first_alpha = environment.sample_observed_directional_environment_for_camera(
                loaded, first, calibration, 4, 2, fallback
            )
            second_rgb, second_alpha = environment.sample_observed_directional_environment_for_camera(
                loaded, second, calibration, 4, 2, fallback
            )
            self.assertEqual(tuple(first_rgb.shape), (1, 2, 4, 3))
            self.assertEqual(tuple(first_alpha.shape), (1, 2, 4, 1))
            torch.testing.assert_close(first_rgb, second_rgb)
            torch.testing.assert_close(first_alpha, second_alpha)

    def test_torch_camera_sampler_keeps_one_image_per_camera(self) -> None:
        image = np.full((2, 4, 3), [30, 60, 90], dtype=np.uint8)
        semantic = np.full((2, 4), 17, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            descriptor = environment.build_observed_directional_environment(
                [record()], [image], [semantic], Path(directory), width=64, height=32
            )
            loaded = environment.load_observed_directional_environment(
                Path(directory), descriptor, device="cpu"
            )
            cameras = torch.stack((torch.eye(4), torch.eye(4)))
            cameras[1, :3, :3] = torch.tensor(
                [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]
            )
            calibration = torch.tensor(
                [
                    [[2.0, 0.0, 2.0], [0.0, 2.0, 1.0], [0.0, 0.0, 1.0]],
                    [[2.0, 0.0, 2.0], [0.0, 2.0, 1.0], [0.0, 0.0, 1.0]],
                ]
            )
            fallback = torch.tensor([[0.9, 0.8, 0.7], [0.1, 0.2, 0.3]])
            rgb, alpha = environment.sample_observed_directional_environment_for_camera(
                loaded, cameras, calibration, 4, 2, fallback
            )
            self.assertEqual(tuple(rgb.shape), (2, 2, 4, 3))
            self.assertEqual(tuple(alpha.shape), (2, 2, 4, 1))


if __name__ == "__main__":
    unittest.main()
