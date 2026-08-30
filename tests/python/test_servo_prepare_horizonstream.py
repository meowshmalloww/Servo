from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_prepare_horizonstream.py"
SPEC = importlib.util.spec_from_file_location("servo_prepare_horizonstream_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PrepareHorizonStreamTests(unittest.TestCase):
    def test_prepares_centered_contiguous_image_list_without_weights(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "selection"
            images = source / "images" / "video-000"
            images.mkdir(parents=True)
            frames = []
            for index in range(8):
                path = images / f"{index:08d}.png"
                path.write_bytes(b"png" + bytes([index]))
                frames.append(
                    {
                        "image": f"video-000/{index:08d}.png",
                        "sourceFrameIndex": index * 3,
                        "timestampSeconds": index / 10,
                        "regionalFocus": 400 + index,
                        "overlap": 0.8,
                    }
                )
            receipt = source / "selection-receipt.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema": module.EXPECTED_SELECTION_SCHEMA,
                        "input": {"sha256": "sha256:" + "1" * 64},
                        "frames": frames,
                    }
                ),
                encoding="utf-8",
            )
            horizon = root / "HorizonStream"
            (horizon / "configs").mkdir(parents=True)
            (horizon / "infer.py").write_text("", encoding="utf-8")
            (horizon / "configs" / "horizonstream_infer.yaml").write_text(
                "model: {}\ndata: {}\ninference: {}\noutput: {}\n", encoding="utf-8"
            )
            # Use a tiny real Git repository so the preparation receipt binds
            # the external source commit exactly as production does.
            import subprocess

            subprocess.run(["git", "init", "-q", str(horizon)], check=True)
            subprocess.run(["git", "-C", str(horizon), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(horizon),
                    "-c",
                    "user.name=Servo Test",
                    "-c",
                    "user.email=servo-test@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            output = root / "prepared"
            result = module.prepare(
                selection_receipt=receipt,
                horizonstream_root=horizon,
                output_root=output,
                frame_count=4,
            )
            self.assertEqual(result["selectionStartIndex"], 2)
            self.assertEqual(result["frameCount"], 4)
            self.assertEqual(result["status"], "blocked-missing-checkpoint")
            config = (output / "horizonstream-t1a-120.yaml").read_text(encoding="utf-8")
            self.assertIn("sliding_size: 1", config)
            self.assertIn("image_paths:", config)
            self.assertFalse(result["horizonStream"]["sourceLicenseFilePresent"])


if __name__ == "__main__":
    unittest.main()
