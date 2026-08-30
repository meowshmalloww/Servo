from __future__ import annotations

import tempfile
import unittest
import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_colmap.py"
SPEC = importlib.util.spec_from_file_location("servo_colmap_text_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
Reconstruction = MODULE.Reconstruction


class ServoColmapTextTests(unittest.TestCase):
    def test_reads_minimal_text_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cameras.txt").write_text(
                "# cameras\n1 PINHOLE 1920 1080 1000 1001 960 540\n",
                encoding="utf-8",
            )
            (root / "images.txt").write_text(
                "# images\n1 1 0 0 0 0 0 0 1 video/000.png\n10 20 7\n",
                encoding="utf-8",
            )
            (root / "points3D.txt").write_text(
                "# points\n7 1 2 3 4 5 6 0.5 1 0\n",
                encoding="utf-8",
            )
            model = Reconstruction(root)
            self.assertEqual(model.cameras[1].model_name, "PINHOLE")
            np.testing.assert_allclose(
                model.cameras[1].calibration_matrix(),
                [[1000, 0, 960], [0, 1001, 540], [0, 0, 1]],
            )
            self.assertEqual(model.images[1].name, "video/000.png")
            self.assertEqual(model.images[1].points2D[0].point3D_id, 7)
            np.testing.assert_allclose(model.points3D[7].xyz, [1, 2, 3])
            self.assertEqual(model.points3D[7].track.length(), 1)

    def test_empty_observation_line_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cameras.txt").write_text(
                "1 SIMPLE_PINHOLE 10 10 5 5 5\n", encoding="utf-8"
            )
            (root / "images.txt").write_text(
                "1 1 0 0 0 0 0 0 1 empty.png\n\n", encoding="utf-8"
            )
            (root / "points3D.txt").write_text("", encoding="utf-8")
            model = Reconstruction(root)
            self.assertEqual(model.images[1].points2D, ())


if __name__ == "__main__":
    unittest.main()
