from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "reconstruction" / "servo_audit_horizonstream.py"
SPEC = importlib.util.spec_from_file_location("servo_audit_horizonstream_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class AuditHorizonStreamTests(unittest.TestCase):
    def test_pose_metrics_accepts_rigid_linear_trajectory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sequence = Path(directory)
            poses = sequence / "poses"
            poses.mkdir()
            pose_lines = ["# w2c"]
            intri_lines = ["# fx fy cx cy"]
            for index in range(4):
                pose_lines.append(
                    f"{index} 1 0 0 0 1 0 0 0 1 {-index} 0 0"
                )
                intri_lines.append(f"{index} 100 100 50 50")
            (poses / "abs_pose.txt").write_text("\n".join(pose_lines), encoding="utf-8")
            (poses / "intri.txt").write_text("\n".join(intri_lines), encoding="utf-8")
            metrics, _, _ = module.pose_metrics(sequence)
            self.assertTrue(metrics["finite"])
            self.assertAlmostEqual(metrics["translationStepP50"], 1.0)
            self.assertAlmostEqual(metrics["rotationStepDegreesMax"], 0.0)
            self.assertAlmostEqual(metrics["rotationDeterminantErrorMax"], 0.0)


if __name__ == "__main__":
    unittest.main()
