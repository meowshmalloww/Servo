from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_audit_world.py"
SPEC = importlib.util.spec_from_file_location("servo_audit_world_driving", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_audit_world = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_audit_world
SPEC.loader.exec_module(servo_audit_world)


class DrivingAuditTest(unittest.TestCase):
    def test_detail_metrics_distinguish_preserved_and_blurred_edges(self) -> None:
        reference = np.zeros((96, 128, 3), dtype=np.float32)
        reference[:, 32:96] = 1.0
        reference[40:56, :] = 0.25
        identical = servo_audit_world.masked_detail_metrics(reference, reference)
        assert identical is not None
        self.assertAlmostEqual(identical["laplacianVarianceRatio"], 1.0, places=5)
        self.assertAlmostEqual(identical["gradientEnergyRatio"], 1.0, places=5)
        self.assertAlmostEqual(identical["gradientSimilarityMean"], 1.0, places=5)

        blurred = cv2.GaussianBlur(reference, (0, 0), 3.0)
        degraded = servo_audit_world.masked_detail_metrics(blurred, reference)
        assert degraded is not None
        self.assertLess(degraded["laplacianVarianceRatio"], 0.5)
        self.assertLess(degraded["gradientEnergyRatio"], 1.0)
        self.assertLess(degraded["gradientSimilarityMean"], 1.0)

    def test_driving_evidence_summary_fails_closed_on_unreadable_signs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            geometry = {
                "schema": "servo.geometry-priors/v1",
                "semantics": {
                    "roadPaint": {
                        "acceptedPixels": 10,
                        "proposalPixels": 20,
                        "acceptedFractionOfProposals": 0.5,
                    },
                    "temporalConsistency": {
                        "groupIoU": {"road": 0.95, "boundary": 0.80}
                    },
                },
            }
            road = {
                "schema": "servo.road-surface/v1",
                "metric": False,
                "collisionValidated": False,
                "scaleProvenance": "sfm-arbitrary",
                "fit": {"inlierRatio": 0.98, "p95AbsoluteResidual": 0.01},
                "observedSurface": {
                    "inlierRatio": 0.94,
                    "p95AbsoluteResidual": 0.02,
                    "blockedCellCount": 2,
                    "ambiguousCellCount": 1,
                },
                "surface": {"elevations": [0.0, 0.1], "banks": [-0.05, 0.05]},
            }
            sign = {
                "schema": "servo.sign-evidence/v1",
                "observations": [
                    {"state": "geometry-verified", "sharpness": 12.0}
                ],
                "tracks": [
                    {
                        "state": "geometry-verified",
                        "fusion": {"shape": [16, 24, 3], "validFraction": 0.75},
                        "text": {"state": "unverified"},
                        "regulatoryClass": {"state": "unverified"},
                    }
                ],
            }
            for name, value in (
                ("geometry-metrics.json", geometry),
                ("road-surface.json", road),
                ("sign-evidence.json", sign),
            ):
                (root / name).write_text(json.dumps(value), encoding="utf-8")

            result = servo_audit_world.load_driving_evidence_summary(root)
            self.assertEqual(result["status"], "not-driving-ready")
            self.assertFalse(result["roadSurfacePrior"]["metric"])
            self.assertEqual(result["signEvidence"]["geometryVerifiedTracks"], 1)
            self.assertEqual(result["signEvidence"]["textVerifiedTracks"], 0)
            self.assertFalse(result["signEvidence"]["passesLegibilityGate"])

    def test_navigation_stress_poses_are_off_path_and_non_metric(self) -> None:
        cameras = []
        for index in range(5):
            c2w = np.eye(4, dtype=np.float64)
            c2w[2, 3] = float(index) * 0.1
            cameras.append({"c2w": c2w})
        anchors, baseline, cases = servo_audit_world.navigation_stress_poses(
            cameras, anchor_count=3
        )
        self.assertEqual(anchors, [0, 2, 4])
        self.assertTrue(all(type(anchor) is int for anchor in anchors))
        json.dumps(
            {
                "anchors": anchors,
                "cases": [
                    {key: value for key, value in case.items() if key != "c2w"}
                    for case in cases
                ],
            }
        )
        self.assertAlmostEqual(baseline, 0.1)
        self.assertEqual(len(cases), 30)
        lateral = next(case for case in cases if case["case"] == "lateral-right-2x")
        self.assertAlmostEqual(lateral["c2w"][0, 3], 0.2)
        self.assertEqual(lateral["group"], "lateral")

    def test_navigation_stress_aggregation_reports_worst_case(self) -> None:
        summary = servo_audit_world.aggregate_navigation_stress(
            [
                {
                    "support": 0.9,
                    "lowerHalfSupport": 0.8,
                    "depthAmbiguityP50": 0.1,
                    "depthAmbiguityP95": 0.4,
                },
                {
                    "support": 0.6,
                    "lowerHalfSupport": 0.5,
                    "depthAmbiguityP50": 0.2,
                    "depthAmbiguityP95": 0.7,
                },
            ]
        )
        self.assertEqual(summary["samples"], 2)
        self.assertAlmostEqual(summary["supportMinimum"], 0.6)
        self.assertAlmostEqual(summary["lowerHalfSupportMinimum"], 0.5)
        self.assertAlmostEqual(summary["depthAmbiguityP95Maximum"], 0.7)

    def test_yaw_sweep_covers_full_rotation_at_multiple_anchors(self) -> None:
        cameras = []
        for index in range(5):
            c2w = np.eye(4, dtype=np.float64)
            c2w[2, 3] = float(index) * 0.1
            cameras.append({"c2w": c2w})

        anchors, cases = servo_audit_world.yaw_sweep_poses(
            cameras, anchor_count=3, step_degrees=45
        )
        self.assertEqual(anchors, [0, 2, 4])
        self.assertEqual(len(cases), 24)
        self.assertEqual(
            [case["yawDegrees"] for case in cases if case["anchor"] == 2],
            [0, 45, 90, 135, 180, 225, 270, 315],
        )
        reverse = next(
            case
            for case in cases
            if case["anchor"] == 2 and case["yawDegrees"] == 180
        )
        np.testing.assert_allclose(reverse["c2w"][:3, 3], cameras[2]["c2w"][:3, 3])
        np.testing.assert_allclose(
            reverse["c2w"][:3, 2], np.asarray([0.0, 0.0, -1.0]), atol=1.0e-12
        )
        with self.assertRaises(servo_audit_world.AuditError):
            servo_audit_world.yaw_sweep_poses(cameras, step_degrees=7)

    def test_coverage_envelope_fails_unknown_without_strong_support(self) -> None:
        envelope = servo_audit_world.build_coverage_envelope(
            [
                {
                    "anchor": 1,
                    "case": "yaw-right-5deg",
                    "group": "rotation",
                    "support": 0.94,
                    "lowerHalfSupport": 0.93,
                    "depthAmbiguityP50": 0.08,
                    "depthAmbiguityP95": 0.40,
                },
                {
                    "anchor": 2,
                    "case": "lateral-right-2x",
                    "group": "lateral",
                    "support": 0.48,
                    "lowerHalfSupport": 0.61,
                    "depthAmbiguityP50": 0.24,
                    "depthAmbiguityP95": 1.10,
                },
            ],
            baseline=0.1,
            world_sha256="sha256:" + "a" * 64,
        )
        self.assertEqual(envelope["schema"], "servo.observed-coverage-envelope/v1")
        self.assertFalse(envelope["metric"])
        self.assertFalse(envelope["collisionValidated"])
        self.assertEqual(envelope["samples"][0]["evidenceState"], "observed-corridor")
        self.assertEqual(envelope["samples"][1]["evidenceState"], "unknown")
        self.assertEqual(envelope["outsidePolicy"], "unknown-not-free-space")


if __name__ == "__main__":
    unittest.main()
