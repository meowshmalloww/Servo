import argparse
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import yaml

from tools.reconstruction.servo_import_wildgs_world import (
    DEFAULT_PIPELINE_REVISION,
    DEFAULT_PROFILE,
    DEFAULT_REPRESENTATION,
    ImportFailure,
    publish,
)


class WildGsWorldImportTests(unittest.TestCase):
    def _fixture(self, root: Path) -> argparse.Namespace:
        output = root / "wildgs"
        (output / "plots_after_refine").mkdir(parents=True)
        (output / "final_gs.ply").write_bytes(
            b"ply\nformat binary_little_endian 1.0\n"
            b"element vertex 2\nproperty float x\nend_header\n"
            + b"\0" * 8
        )
        poses = np.repeat(np.eye(4, dtype=np.float32)[None], 2, axis=0)
        poses[1, 2, 3] = 0.25
        np.savez(output / "video.npz", poses=poses, timestamps=np.array([0, 1]))
        source = root / "input" / "rgb"
        source.mkdir(parents=True)
        for index in range(2):
            (source / f"frame_{index:05d}.png").write_bytes(b"frame")
        (output / "cfg.yaml").write_text(
            yaml.safe_dump(
                {
                    "cam": {
                        "W": 1920,
                        "H": 1080,
                        "fx": 1700.0,
                        "fy": 1700.0,
                        "cx": 960.0,
                        "cy": 540.0,
                    },
                    "data": {"input_folder": str(source.parent)},
                }
            ),
            encoding="utf-8",
        )
        media = root / "source.mov"
        media.write_bytes(b"video")
        return argparse.Namespace(
            wildgs_output=output,
            source_media=media,
            world_id="wildgs-t2-test",
            world_name="WildGS T2 Test",
            created_at="2026-08-27T23:00:00Z",
            jobs_root=root / "jobs",
            profile=DEFAULT_PROFILE,
            pipeline_revision=DEFAULT_PIPELINE_REVISION,
            representation_type=DEFAULT_REPRESENTATION,
            experiment_label="T2",
        )

    def test_publishes_real_ply_and_camera_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self._fixture(Path(temporary))
            job = publish(args)
            world = job / "stages" / "publish" / "world"
            manifest = json.loads((world / "world.json").read_text(encoding="utf-8"))
            cameras = json.loads((world / "cameras.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["quality"]["cleanup"]["retainedGaussians"], 2)
            self.assertEqual(manifest["evidence"]["usesColmap"], False)
            self.assertEqual(manifest["profile"], DEFAULT_PROFILE)
            self.assertEqual(manifest["pipelineRevision"], DEFAULT_PIPELINE_REVISION)
            self.assertEqual(len(cameras["cameras"]), 2)
            self.assertEqual(cameras["validationImages"], [])
            self.assertEqual(
                cameras["validationSemantics"],
                "none-all-retained-keyframes-were-optimized",
            )
            self.assertEqual(cameras["cameras"][1]["cameraToWorldNormalized"][2][3], 0.25)
            self.assertTrue((world / "world.ply").is_file())

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self._fixture(Path(temporary))
            publish(args)
            with self.assertRaises(ImportFailure):
                publish(args)


if __name__ == "__main__":
    unittest.main()
