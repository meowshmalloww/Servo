from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_capture_health.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("servo_capture_health_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_capture_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(servo_capture_health)


class CaptureHealthTest(unittest.TestCase):
    def test_selector_is_deterministic_and_rejects_blur(self) -> None:
        frames = []
        for index in range(8):
            frames.append(
                {
                    "image": f"video-000/{index:08d}.png",
                    "sharpness": 5.0 if index == 3 else 100.0,
                    "luminanceMean": 0.5,
                    "translationFromPrevious": 0.1 if index else 0.0,
                    "rotationFromPreviousDegrees": 0.0,
                    "sparseTrackCount": 200,
                    "trackGridCoverage": 0.8,
                }
            )
        first = servo_capture_health.select_keyframes(frames)
        second = servo_capture_health.select_keyframes(frames)
        self.assertEqual(first, second)
        selected, rejected = first
        self.assertEqual(selected[0], frames[0]["image"])
        self.assertEqual(selected[-1], frames[-1]["image"])
        blurred = next(item for item in rejected if item["image"] == frames[3]["image"])
        self.assertIn("lower-sharpness-quartile", blurred["reasons"])

    def test_distribution_has_stable_percentiles(self) -> None:
        result = servo_capture_health.distribution([4.0, 1.0, 3.0, 2.0])
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["minimum"], 1.0)
        self.assertEqual(result["maximum"], 4.0)
        self.assertEqual(result["p50"], 2.5)


if __name__ == "__main__":
    unittest.main()
