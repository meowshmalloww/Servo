from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import torch


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_diagnose_splats.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("servo_diagnose_splats_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SplatForensicsTest(unittest.TestCase):
    def test_masks_remove_radius_and_anisotropy_outliers(self) -> None:
        radius = torch.arange(1.0, 1001.0)
        anisotropy = torch.ones(1000)
        anisotropy[10] = 40.0
        opacity = torch.ones(1000)
        opacity[-1] = 0.01
        masks = module.diagnostic_masks(radius, anisotropy, opacity)
        self.assertEqual(int((~masks["remove-top-1.0pct-radius"]).sum()), 10)
        self.assertFalse(bool(masks["anisotropy-at-most-35"][10]))
        self.assertFalse(bool(masks["remove-low-opacity-giants"][-1]))
        self.assertTrue(bool(masks["original-sh3"].all()))

    def test_distribution_is_finite_and_deterministic(self) -> None:
        value = module.numeric_distribution([1.0, 2.0, float("nan"), 3.0])
        self.assertEqual(value["count"], 3)
        self.assertEqual(value["p50"], 2.0)
        self.assertEqual(value["maximum"], 3.0)


if __name__ == "__main__":
    unittest.main()
