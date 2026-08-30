from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_horizonstream_3dgs.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_horizonstream_3dgs_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareHorizonStream3dgsTests(unittest.TestCase):
    def test_da3_resize_mapping_matches_504_by_280(self) -> None:
        mapping = MODULE._resized_patch_mapping(1920, 1080, 504, 14)
        self.assertEqual(mapping["processedWidth"], 504.0)
        self.assertEqual(mapping["processedHeight"], 280.0)
        self.assertAlmostEqual(mapping["scaleX"], 504 / 1920)
        self.assertAlmostEqual(mapping["scaleY"], 280 / 1080)
        self.assertEqual(mapping["cropX"], 0.0)
        self.assertEqual(mapping["cropY"], 0.0)

    def test_existing_center_crop_mapping_is_preserved(self) -> None:
        mapping = MODULE._processed_mapping(1920, 1080, 518, 14)
        self.assertEqual(mapping["processedWidth"], 518.0)
        self.assertEqual(mapping["processedHeight"], 280.0)
        self.assertEqual(mapping["scaleX"], mapping["scaleY"])


if __name__ == "__main__":
    unittest.main()
