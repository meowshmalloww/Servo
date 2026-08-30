import importlib.util
import unittest
from pathlib import Path

import numpy as np


PATH = Path(__file__).parents[2] / "tools" / "reconstruction" / "servo_camera_forensics.py"
SPEC = importlib.util.spec_from_file_location("servo_camera_forensics", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CameraForensicsTests(unittest.TestCase):
    def test_selection_covers_sequence(self):
        records = [{
            "sharpness": float(index + 1), "darkFraction": 0.0,
            "brightFraction": 0.0, "rollingShutterSuspected": False,
        } for index in range(20)]
        selected = MODULE._select_indices(records, 4)
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(a < b for a, b in zip(selected, selected[1:])))
        self.assertGreaterEqual(selected[0], 0)
        self.assertLess(selected[-1], 20)

    def test_static_pair_has_no_rolling_shutter_claim(self):
        image = np.zeros((240, 320), dtype=np.uint8)
        for y in range(20, 220, 30):
            for x in range(20, 300, 30):
                image[y - 2:y + 3, x - 2:x + 3] = 255
        result = MODULE._row_motion_residual(image, image.copy())
        self.assertFalse(result["suspected"])
        self.assertLess(result["residualP95"], 0.1)


if __name__ == "__main__":
    unittest.main()
