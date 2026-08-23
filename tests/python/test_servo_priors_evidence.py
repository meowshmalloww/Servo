from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_priors.py"
SPEC = importlib.util.spec_from_file_location("servo_priors_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_priors = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_priors
SPEC.loader.exec_module(servo_priors)


class IdentityAlignment:
    def apply(self, value: np.ndarray) -> np.ndarray:
        return np.asarray(value, dtype=np.float32)


def camera_record(width: int, height: int) -> SimpleNamespace:
    calibration = np.asarray(
        [[8.0, 0.0, (width - 1.0) / 2.0], [0.0, 8.0, (height - 1.0) / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    return SimpleNamespace(
        width=width,
        height=height,
        calibration=calibration,
        camera_to_world=np.eye(4, dtype=np.float64),
    )


class CalibratedRoadPaintCorrespondenceTests(unittest.TestCase):
    def test_identity_preserves_every_finite_pixel_centre(self) -> None:
        height, width = 6, 8
        record = camera_record(width, height)
        depth = np.full((height, width), 10.0, dtype=np.float32)

        mapping = servo_priors.calibrated_depth_correspondence(
            record,
            record,
            depth,
            depth,
            IdentityAlignment(),
            IdentityAlignment(),
        )

        expected_x, expected_y = np.meshgrid(
            np.arange(width, dtype=np.float32),
            np.arange(height, dtype=np.float32),
        )
        self.assertTrue(np.isfinite(mapping).all())
        np.testing.assert_allclose(mapping[..., 0], expected_x, atol=1.0e-6)
        np.testing.assert_allclose(mapping[..., 1], expected_y, atol=1.0e-6)

    def test_nearer_observation_surface_is_occlusion_not_agreement(self) -> None:
        height, width = 6, 8
        record = camera_record(width, height)
        reference = np.full((height, width), 10.0, dtype=np.float32)
        observation = np.full((height, width), 10.0, dtype=np.float32)
        observation[1:5, 2:6] = 8.0

        mapping = servo_priors.calibrated_depth_correspondence(
            record,
            record,
            reference,
            observation,
            IdentityAlignment(),
            IdentityAlignment(),
        )

        self.assertTrue(np.isnan(mapping[1:5, 2:6]).all())
        self.assertTrue(np.isfinite(mapping[0]).all())


class CertifiedSkyEvidenceTests(unittest.TestCase):
    def test_rotation_only_mapping_ignores_camera_translation(self) -> None:
        source = camera_record(9, 9)
        target = camera_record(9, 9)
        target.camera_to_world[:3, 3] = np.asarray([50.0, -20.0, 7.0])

        mapped_x, mapped_y, valid = servo_priors.rotation_only_semantic_correspondence(
            source,
            target,
            (9, 9),
            (9, 9),
        )

        expected_x, expected_y = np.meshgrid(np.arange(9), np.arange(9))
        self.assertTrue(valid.all())
        np.testing.assert_array_equal(mapped_x, expected_x)
        np.testing.assert_array_equal(mapped_y, expected_y)

    def test_candidate_mapping_matches_full_rotation_only_mapping(self) -> None:
        source = camera_record(9, 9)
        target = camera_record(9, 9)
        target.camera_to_world[:3, 3] = np.asarray([11.0, 7.0, -3.0])
        full_x, full_y, full_valid = servo_priors.rotation_only_semantic_correspondence(
            source, target, (9, 9), (9, 9)
        )
        candidate_x = np.asarray([0, 4, 8, 2], dtype=np.int64)
        candidate_y = np.asarray([1, 4, 7, 8], dtype=np.int64)
        mapped_x, mapped_y, valid = (
            servo_priors.rotation_only_semantic_correspondence_points(
                source,
                target,
                (9, 9),
                (9, 9),
                candidate_x,
                candidate_y,
            )
        )

        np.testing.assert_array_equal(mapped_x, full_x[candidate_y, candidate_x])
        np.testing.assert_array_equal(mapped_y, full_y[candidate_y, candidate_x])
        np.testing.assert_array_equal(valid, full_valid[candidate_y, candidate_x])

    def test_two_neighbours_certify_only_eroded_rotation_consistent_sky(self) -> None:
        records = [camera_record(9, 9) for _ in range(3)]
        semantics = [np.full((9, 9), 17, dtype=np.uint8) for _ in records]
        semantics[0][0, 0] = 1

        evidence, metrics = servo_priors.certified_sky_evidence(
            records,
            semantics,
            ["video-000"] * len(records),
        )

        self.assertEqual(
            int(evidence[1][4, 4]), servo_priors.CERTIFIED_SKY_EVIDENCE_SKY
        )
        self.assertEqual(
            int(evidence[1][0, 0]), servo_priors.CERTIFIED_SKY_EVIDENCE_UNKNOWN
        )
        self.assertEqual(
            int(evidence[0][0, 0]),
            servo_priors.CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY,
        )
        self.assertGreater(metrics[1]["certifiedSkyPixels"], 0)
        self.assertEqual(metrics[1]["neighbourViews"], 2)

    def test_a_non_sky_neighbour_conflict_fails_closed(self) -> None:
        records = [camera_record(9, 9) for _ in range(3)]
        semantics = [np.full((9, 9), 17, dtype=np.uint8) for _ in records]
        semantics[2][4, 4] = 1

        evidence, _ = servo_priors.certified_sky_evidence(
            records,
            semantics,
            ["video-000"] * len(records),
        )

        self.assertEqual(
            int(evidence[1][4, 4]), servo_priors.CERTIFIED_SKY_EVIDENCE_UNKNOWN
        )

    def test_out_of_frame_neighbour_rays_remain_unknown_without_indexing(self) -> None:
        records = [camera_record(9, 9) for _ in range(3)]
        records[2].calibration[0, 2] = 1000.0
        semantics = [np.full((9, 9), 17, dtype=np.uint8) for _ in records]

        evidence, _ = servo_priors.certified_sky_evidence(
            records,
            semantics,
            ["video-000"] * len(records),
        )

        self.assertEqual(
            int(evidence[1][4, 4]), servo_priors.CERTIFIED_SKY_EVIDENCE_UNKNOWN
        )

    def test_persisted_evidence_is_hash_bound_and_tri_state(self) -> None:
        records = [camera_record(9, 9) for _ in range(3)]
        for index, record in enumerate(records):
            record.name = f"video-000/{index:08d}.png"
        semantics = [np.full((9, 9), 17, dtype=np.uint8) for _ in records]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = servo_priors.build_certified_sky_evidence(
                records,
                semantics,
                ["video-000"] * len(records),
                root,
            )

            self.assertEqual(
                descriptor["schema"], servo_priors.CERTIFIED_SKY_EVIDENCE_SCHEMA
            )
            self.assertTrue(descriptor["rotationOnlyInfiniteSky"])
            self.assertFalse(descriptor["containsGeneratedPixels"])
            self.assertEqual(len(descriptor["frames"]), 3)
            self.assertTrue((root / descriptor["manifest"]).is_file())
            for frame in descriptor["frames"]:
                self.assertTrue((root / frame["asset"]).is_file())
                self.assertTrue(frame["assetSha256"].startswith("sha256:"))

    def test_nan_observation_hole_remains_unsupported(self) -> None:
        height, width = 6, 8
        record = camera_record(width, height)
        reference = np.full((height, width), 10.0, dtype=np.float32)
        observation = np.full((height, width), 10.0, dtype=np.float32)
        observation[2:4, 3:5] = np.nan

        mapping = servo_priors.calibrated_depth_correspondence(
            record,
            record,
            reference,
            observation,
            IdentityAlignment(),
            IdentityAlignment(),
        )

        self.assertTrue(np.isnan(mapping[2:4, 3:5]).all())
        self.assertTrue(np.isfinite(mapping[0]).all())


if __name__ == "__main__":
    unittest.main()
