from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_wildgs.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_wildgs_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PrepareWildGSTests(unittest.TestCase):
    def test_prepares_sequential_frames_and_two_resolutions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wildgs = root / "WildGS-SLAM"
            (wildgs / "configs").mkdir(parents=True)
            (wildgs / "run.py").write_text("", encoding="utf-8")
            (wildgs / "configs" / "wildgs_slam.yaml").write_text("", encoding="utf-8")
            data = root / "servo"
            images = data / "images" / "video-000"
            images.mkdir(parents=True)
            for index in range(2):
                (images / f"{index:08d}.png").write_bytes(b"png" + bytes([index]))
            camera = {
                "cameraId": 1,
                "cameraModel": "PINHOLE",
                "width": 1910,
                "height": 1074,
                "calibration": [
                    [1579.5, 0.0, 955.0],
                    [0.0, 1579.5, 537.0],
                    [0.0, 0.0, 1.0],
                ],
            }
            cameras_json = root / "cameras.json"
            cameras_json.write_text(
                json.dumps(
                    {
                        "schema": "servo.gaussian-cameras/v1",
                        "cameras": [
                            {**camera, "image": "video-000/00000000.png"},
                            {**camera, "image": "video-000/00000001.png"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "comparison"
            receipt = module.prepare(
                cameras_json=cameras_json,
                servo_data_root=data,
                wildgs_root=wildgs,
                output_root=output,
            )
            self.assertEqual(receipt["frameCount"], 2)
            self.assertFalse(receipt["usesColmapPoses"])
            self.assertTrue((output / "dataset" / "rgb" / "frame_00001.png").is_file())
            safe = (output / "configs" / "yosemite-wildgs-360x640.yaml").read_text()
            high = (output / "configs" / "yosemite-wildgs-537x955.yaml").read_text()
            self.assertIn("W_out: 640", safe)
            self.assertIn("H_out: 537", high)


if __name__ == "__main__":
    unittest.main()
