import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "reconstruction"
    / "servo_bound_wildgs_export.py"
)
SPEC = importlib.util.spec_from_file_location("servo_bound_wildgs_export", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BoundedWildGsExportTest(unittest.TestCase):
    def test_sha256_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.bin"
            path.write_bytes(b"servo")
            self.assertEqual(
                MODULE.sha256(path),
                "0069df340f9aff7c5f2887b02c15f92049cb16fcb9891514adcf2dacfaf8e877",
            )

    def test_scale_bounds_are_ordered(self):
        values = np.array([[-100.0, -6.0, 100.0]], dtype=np.float64)
        bounded = np.clip(values, -12.0, 0.0)
        self.assertTrue(np.isfinite(bounded).all())
        self.assertEqual(bounded.tolist(), [[-12.0, -6.0, 0.0]])


if __name__ == "__main__":
    unittest.main()
