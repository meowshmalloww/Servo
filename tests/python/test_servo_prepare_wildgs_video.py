import math
import unittest

from tools.reconstruction.servo_prepare_wildgs_video import (
    selection_score,
    temporal_bins,
)


class WildGsVideoSelectionTests(unittest.TestCase):
    def test_temporal_bins_cover_every_source_frame_once(self):
        bins = temporal_bins(1307, 360)
        self.assertEqual(len(bins), 360)
        self.assertEqual(bins[0][0], 0)
        self.assertEqual(bins[-1][1], 1307)
        self.assertEqual(sum(end - start for start, end in bins), 1307)
        for left, right in zip(bins, bins[1:]):
            self.assertEqual(left[1], right[0])

    def test_selection_prefers_sharp_normally_exposed_frame(self):
        good = selection_score(100.0, 0.50, 0.20)
        blurry = selection_score(10.0, 0.50, 0.20)
        clipped = selection_score(100.0, 0.99, 0.01)
        self.assertGreater(good, blurry)
        self.assertGreater(good, clipped)
        self.assertEqual(selection_score(math.nan, 0.5, 0.2), -math.inf)


if __name__ == "__main__":
    unittest.main()
