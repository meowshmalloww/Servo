from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_360_capture.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_360_capture_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class Prepare360CaptureTests(unittest.TestCase):
    def test_face_centers_have_expected_directions(self) -> None:
        expected = {
            "front": np.array((0.0, 0.0, 1.0)),
            "right": np.array((1.0, 0.0, 0.0)),
            "back": np.array((0.0, 0.0, -1.0)),
            "left": np.array((-1.0, 0.0, 0.0)),
            "up": np.array((0.0, -1.0, 0.0)),
            "down": np.array((0.0, 1.0, 0.0)),
        }
        for face, direction in expected.items():
            rays = module.face_directions(face, 3)
            np.testing.assert_allclose(rays[1, 1], direction, atol=1e-12)

    def test_front_center_samples_panorama_center(self) -> None:
        map_x, map_y = module.equirectangular_remap("front", 3, 360, 180)
        self.assertAlmostEqual(float(map_x[1, 1]), 179.5, places=5)
        self.assertAlmostEqual(float(map_y[1, 1]), 89.5, places=5)

    def test_prepare_writes_six_hash_bound_faces_and_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "panorama.png"
            panorama = np.zeros((64, 128, 3), dtype=np.uint8)
            panorama[:, :, 0] = np.arange(128, dtype=np.uint8)[None, :]
            self.assertTrue(cv2.imwrite(str(source), panorama))
            output = root / "cubemap"
            receipt = module.prepare(source, output, 16)
            self.assertEqual(receipt["schema"], module.SCHEMA)
            self.assertTrue(receipt["sharedOpticalCenter"])
            self.assertEqual(set(receipt["cameras"]), set(module.FACE_CAMERA_TO_EQUIRECT))
            self.assertEqual(len(receipt["frames"][0]["faces"]), 6)
            self.assertTrue((output / "images" / "back" / "frame_000000.png").is_file())
            parsed = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
            self.assertFalse(parsed["generatedPixels"])

    def test_rejects_flat_pinhole_image(self) -> None:
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "2:1"):
            module.convert_frame(image, 16)

    def test_refuses_nonempty_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "panorama.png"
            cv2.imwrite(str(source), np.zeros((32, 64, 3), dtype=np.uint8))
            output = root / "output"
            output.mkdir()
            (output / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Refusing"):
                module.prepare(source, output, 8)


if __name__ == "__main__":
    unittest.main()
