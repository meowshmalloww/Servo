import unittest

import numpy as np

from tools.reconstruction.servo_prepare_da3_unposed_depth import robust_overlap_scale


class Da3UnposedDepthTests(unittest.TestCase):
    def test_robust_overlap_scale_recovers_relative_window_scale(self):
        reference = np.full((32, 32), 4.0, dtype=np.float32)
        existing = [[reference], [reference * 2.0], [], []]
        current = np.stack(
            [reference / 2.0, reference, reference * 3.0], axis=0
        )
        self.assertAlmostEqual(robust_overlap_scale(existing, 0, current), 2.0, places=5)

    def test_no_overlap_uses_identity_scale(self):
        current = np.ones((2, 16, 16), dtype=np.float32)
        self.assertEqual(robust_overlap_scale([[], []], 0, current), 1.0)


if __name__ == "__main__":
    unittest.main()
