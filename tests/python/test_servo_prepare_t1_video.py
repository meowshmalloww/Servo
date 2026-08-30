from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_t1_video.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_t1_video_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def patterned_frame(*, blur: int = 0, shift: int = 0) -> np.ndarray:
    image = np.full((240, 320, 3), 40, dtype=np.uint8)
    for y in range(20, 230, 28):
        cv2.line(image, (10 + shift, y), (300 + shift, y), (210, 210, 210), 2)
    for x in range(20, 310, 32):
        cv2.circle(image, (x + shift, 150), 7, (30, 220, 90), -1)
    cv2.putText(
        image,
        "SERVO ROAD",
        (55 + shift, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (240, 240, 240),
        2,
        cv2.LINE_AA,
    )
    if blur:
        image = cv2.GaussianBlur(image, (blur, blur), 0)
    return image


class PrepareT1VideoTests(unittest.TestCase):
    def test_first_window_prefers_sharp_candidate(self) -> None:
        blurry = module.make_candidate(0, 0.0, patterned_frame(blur=15))
        sharp = module.make_candidate(1, 0.03, patterned_frame())
        chosen, evidence = module.choose_window_candidate([blurry, sharp], None)
        self.assertEqual(chosen.frame_index, 1)
        self.assertTrue(evidence["connected"])

    def test_next_window_prefers_connected_sharp_candidate(self) -> None:
        previous = module.make_candidate(0, 0.0, patterned_frame())
        blurry = module.make_candidate(1, 0.10, patterned_frame(blur=15, shift=2))
        sharp = module.make_candidate(2, 0.13, patterned_frame(shift=2))
        chosen, evidence = module.choose_window_candidate(
            [blurry, sharp],
            previous,
            minimum_overlap=0.05,
            minimum_matches=8,
        )
        self.assertEqual(chosen.frame_index, 2)
        self.assertTrue(evidence["connected"])
        self.assertGreaterEqual(evidence["matches"], 8)

    def test_marks_a_window_without_visual_connection(self) -> None:
        previous = module.make_candidate(0, 0.0, patterned_frame())
        blank = np.full((240, 320, 3), 128, dtype=np.uint8)
        candidate = module.make_candidate(1, 0.1, blank)
        chosen, evidence = module.choose_window_candidate([candidate], previous)
        self.assertEqual(chosen.frame_index, 1)
        self.assertFalse(evidence["connected"])
        self.assertEqual(evidence["selectionReason"], "sharpest-unconnected-window")

    def test_atomic_receipt_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            module.atomic_json(path, {"schema": module.SCHEMA, "ok": True})
            self.assertIn('"ok": true', path.read_text(encoding="utf-8"))

    def test_explicit_ffmpeg_directory_accepts_decoder_without_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ffmpeg.exe").write_bytes(b"")
            self.assertEqual(module.locate_ffmpeg_bin(root), root.resolve())


if __name__ == "__main__":
    unittest.main()
