from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "reconstruction"
    / "servo_run_da3_t2.py"
)
SPEC = importlib.util.spec_from_file_location("servo_run_da3_t2", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RunDa3T2Tests(unittest.TestCase):
    def test_discovers_and_selects_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("0002.png", "0000.png", "0001.png", "ignore.txt"):
                (root / name).write_bytes(b"x")
            frames = MODULE.discover_frames(root)
            self.assertEqual([path.name for path in frames], ["0000.png", "0001.png", "0002.png"])
            selected = MODULE.select_frame_paths(frames, start=0, count=2, stride=2)
            self.assertEqual([path.name for path in selected], ["0000.png", "0002.png"])

    def test_selection_rejects_short_window(self) -> None:
        frames = [Path("0.png"), Path("1.png")]
        with self.assertRaises(RuntimeError):
            MODULE.select_frame_paths(frames, start=1, count=2, stride=1)

    def test_camera_normalization_centers_and_scales_path(self) -> None:
        camera_to_world = np.repeat(np.eye(4)[None], 3, axis=0)
        camera_to_world[:, 0, 3] = [0.0, 2.0, 4.0]
        extrinsics = np.linalg.inv(camera_to_world)
        center, scale, normalized = MODULE.scene_normalization(extrinsics)
        np.testing.assert_allclose(center, [2.0, 0.0, 0.0])
        self.assertGreater(scale, 0.0)
        np.testing.assert_allclose(normalized[1, :3, 3], [0.0, 0.0, 0.0])

    def test_camera_normalization_accepts_three_by_four_extrinsics(self) -> None:
        camera_to_world = np.repeat(np.eye(4)[None], 2, axis=0)
        camera_to_world[1, 2, 3] = 3.0
        extrinsics = np.linalg.inv(camera_to_world)[:, :3, :]
        _, scale, normalized = MODULE.scene_normalization(extrinsics)
        self.assertEqual(normalized.shape, (2, 4, 4))
        self.assertGreater(scale, 0.0)

    def test_reads_horizon_pose_and_intrinsics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pose = root / "pose.txt"
            intrinsics = root / "intri.txt"
            pose.write_text(
                "# w2c\n0 1 0 0 0 0 1 0 0 0 0 1 0\n"
                "1 1 0 0 0 1 0 0 0 1 -2 0 0\n",
                encoding="utf-8",
            )
            intrinsics.write_text(
                "# fx fy cx cy\n0 500 501 250 140\n1 502 503 251 141\n",
                encoding="utf-8",
            )
            extrinsics, calibration = MODULE.read_horizon_calibration(pose, intrinsics)
            self.assertEqual(extrinsics.shape, (2, 4, 4))
            self.assertEqual(calibration.shape, (2, 3, 3))
            self.assertEqual(extrinsics[1, 0, 3], -2.0)
            self.assertEqual(calibration[1, 1, 1], 503.0)


if __name__ == "__main__":
    unittest.main()
