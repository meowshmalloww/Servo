import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


MODULE_PATH = Path(__file__).parents[2] / "tools" / "reconstruction" / "servo_prepare_brush_from_wildgs.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_brush_from_wildgs", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BrushWildGsDatasetTests(unittest.TestCase):
    def test_rotation_to_qvec_identity(self):
        np.testing.assert_allclose(
            MODULE._rotation_to_colmap_qvec(np.eye(3)), np.array([1.0, 0.0, 0.0, 0.0])
        )

    def test_link_or_copy_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            target = root / "nested" / "target.png"
            Image.new("RGB", (2, 2), (10, 20, 30)).save(source)
            MODULE._link_or_copy(source, target)
            self.assertEqual(source.read_bytes(), target.read_bytes())


if __name__ == "__main__":
    unittest.main()
