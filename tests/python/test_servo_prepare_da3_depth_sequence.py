from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_da3_depth_sequence.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_da3_depth_sequence_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareDa3DepthSequenceTests(unittest.TestCase):
    def test_window_starts_covers_tail_without_duplicate(self) -> None:
        self.assertEqual(MODULE.window_starts(17, 8, 4), [0, 4, 8, 9])

    def test_fusion_rejects_invalid_and_uses_median(self) -> None:
        depth, confidence, spread = MODULE.fuse_predictions(
            [
                np.asarray([[10.0, np.nan]], dtype=np.float32),
                np.asarray([[12.0, 8.0]], dtype=np.float32),
                np.asarray([[100.0, 8.0]], dtype=np.float32),
            ],
            [
                np.asarray([[2.0, 1.0]], dtype=np.float32),
                np.asarray([[3.0, 2.0]], dtype=np.float32),
                np.asarray([[4.0, 2.0]], dtype=np.float32),
            ],
        )
        self.assertAlmostEqual(float(depth[0, 0]), 12.0)
        self.assertAlmostEqual(float(depth[0, 1]), 8.0)
        self.assertAlmostEqual(float(confidence[0, 0]), 3.0)
        self.assertGreater(float(spread[0, 0]), 0.0)

    def test_reads_horizon_rotation_then_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pose = root / "pose.txt"
            intrinsics = root / "intri.txt"
            pose.write_text("# pose rows\n0 1 0 0 0 1 0 0 0 1 4 5 6\n", encoding="utf-8")
            intrinsics.write_text("# camera rows\n0 10 11 12 13\n", encoding="utf-8")
            extrinsic, matrix = MODULE.read_horizon_calibration(pose, intrinsics)
            np.testing.assert_allclose(extrinsic[0, :3, :3], np.eye(3))
            np.testing.assert_allclose(extrinsic[0, :3, 3], [4, 5, 6])
            np.testing.assert_allclose(extrinsic[0, 3], [0, 0, 0, 1])
            self.assertEqual(float(matrix[0, 0, 0]), 10.0)

    def test_converts_cropped_horizon_intrinsics_back_to_source(self) -> None:
        intrinsic = np.asarray(
            [[[497.0, 0.0, 259.0], [0.0, 492.0, 140.0], [0.0, 0.0, 1.0]]],
            dtype=np.float32,
        )
        converted = MODULE.horizon_intrinsics_to_source(
            intrinsic,
            source_width=1920,
            source_height=1080,
            horizon_long_edge=518,
            patch_size=14,
        )
        self.assertGreater(float(converted[0, 0, 0]), 1800.0)
        self.assertAlmostEqual(float(converted[0, 0, 2]), 960.0, delta=4.0)
        self.assertAlmostEqual(float(converted[0, 1, 2]), 540.0, delta=8.0)


if __name__ == "__main__":
    unittest.main()
