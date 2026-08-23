from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np


REPOSITORY = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_sign_evidence.py"
SPEC = importlib.util.spec_from_file_location("servo_sign_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_sign_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_sign_evidence
SPEC.loader.exec_module(servo_sign_evidence)

PRIORS_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_priors.py"
PRIORS_SPEC = importlib.util.spec_from_file_location("servo_priors", PRIORS_PATH)
assert PRIORS_SPEC is not None and PRIORS_SPEC.loader is not None
servo_priors = importlib.util.module_from_spec(PRIORS_SPEC)
sys.modules[PRIORS_SPEC.name] = servo_priors
PRIORS_SPEC.loader.exec_module(servo_priors)


class IdentityDepthAlignment:
    def apply(self, value: np.ndarray) -> np.ndarray:
        return np.asarray(value)


def provenance() -> servo_sign_evidence.SignEvidenceProvenance:
    return servo_sign_evidence.SignEvidenceProvenance(
        sequence_id="synthetic-road-sequence",
        coordinate_frame_id="sfm-model-7",
        scale_provenance="sfm-arbitrary-scale",
        camera_source="synthetic calibrated camera fixture",
        depth_source="synthetic camera-Z fixture aligned to SfM",
        semantic_source="synthetic Servo label fixture",
        candidate_source="synthetic detector fixture",
        source_hashes=(("fixture", "sha256:" + "a" * 64),),
    )


def sign_pattern(*, blurred: bool, color_shift: int = 0) -> np.ndarray:
    y, x = np.indices((32, 32))
    checker = ((x // 2 + y // 2) % 2).astype(np.uint8)
    image = np.empty((32, 32, 3), dtype=np.uint8)
    image[..., 0] = np.where(checker, 20 + color_shift, 220)
    image[..., 1] = np.where(checker, 210, 30 + color_shift)
    image[..., 2] = np.where(checker, 240, 40)
    if blurred:
        image = cv2.GaussianBlur(image, (9, 9), 2.5)
    return image


def candidate(
    candidate_id: str,
    frame_index: int,
    camera_x: float,
    *,
    sign_x: float = 0.0,
    blurred: bool = False,
    forbidden: int | None = None,
    inconsistent_depth: bool = False,
    recognition: servo_sign_evidence.ExternalRecognition | None = None,
    observed_hole: bool = False,
) -> servo_sign_evidence.SignCandidate:
    focal = 120.0
    center_x = focal * (sign_x - camera_x) / 8.0 + 64.0
    center_y = 48.0
    box = (center_x - 12.0, center_y - 9.0, center_x + 12.0, center_y + 9.0)
    crop = sign_pattern(blurred=blurred, color_shift=round(sign_x * 3))
    mask = np.ones((32, 32), dtype=bool)
    mask[[0, -1], :] = False
    mask[:, [0, -1]] = False
    semantic = np.zeros((32, 32), dtype=np.int16)
    semantic[mask] = 12  # Servo TRAFFIC_SIGN_FRONT.
    if forbidden is not None:
        semantic[4:16, 4:16] = forbidden
    depth = np.full((32, 32), np.nan, dtype=np.float64)
    depth[mask] = 8.0
    if inconsistent_depth:
        y, x = np.indices(depth.shape)
        depth[mask & (((x // 2 + y // 2) % 2) == 0)] = 11.0
    observed = mask.copy()
    if observed_hole:
        observed[10:22, 10:22] = False
        mask = observed.copy()
    calibration = np.asarray(
        [[focal, 0.0, 64.0], [0.0, focal, 48.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    camera_to_world = np.eye(4, dtype=np.float64)
    camera_to_world[0, 3] = camera_x
    return servo_sign_evidence.SignCandidate(
        candidate_id=candidate_id,
        frame_id=f"frame-{frame_index:04d}",
        frame_index=frame_index,
        box_xyxy=box,
        crop_bgr=crop,
        candidate_mask=mask,
        semantic_crop=semantic,
        depth_crop=depth,
        calibration=calibration,
        camera_to_world=camera_to_world,
        observed_mask=observed,
        recognition=recognition,
    )


def three_view_candidates(
    *, recognition_values: tuple[str, str, str] | None = None
) -> list[servo_sign_evidence.SignCandidate]:
    frames = (0, 1, 3)
    cameras = (-0.65, 0.0, 0.65)
    values = recognition_values or ("", "", "")
    result = []
    for slot, (frame, camera_x, value) in enumerate(zip(frames, cameras, values)):
        recognition = None
        if value:
            recognition = servo_sign_evidence.ExternalRecognition(
                engine_id="external-ocr-and-sign-classifier",
                engine_revision="fixture-v1",
                confidence=0.96,
                regulatory_class=value,
                text="SPEED 25" if value == "SPEED_LIMIT_25" else "SPEED 35",
            )
        result.append(
            candidate(
                f"candidate-{slot}",
                frame,
                camera_x,
                blurred=slot != 1,
                recognition=recognition,
                observed_hole=slot == 1,
            )
        )
    return result


class ServoSignEvidenceTests(unittest.TestCase):
    def test_three_nonadjacent_views_verify_geometry_and_fuse_only_observed_pixels(self) -> None:
        candidates = three_view_candidates()
        bundle = servo_sign_evidence.build_sign_evidence(candidates, provenance())
        self.assertEqual(len(bundle.tracks), 1)
        track = bundle.tracks[0]
        self.assertEqual(track.state, servo_sign_evidence.GeometryState.GEOMETRY_VERIFIED)
        self.assertEqual(track.reasons, ())
        self.assertIsNotNone(track.plane)
        assert track.plane is not None and track.fusion is not None
        self.assertGreater(abs(float(track.plane.normal[2])), 0.999)
        self.assertLess(track.plane.p95_inlier_residual_ratio, 1e-8)
        self.assertGreater(track.camera_baseline_ratio, 0.4)
        self.assertEqual(track.fusion.observation_order[0], "candidate-1")
        self.assertFalse(track.fusion.generated_pixels)
        self.assertEqual(track.fusion.sampling, "nearest-observed-pixel")
        self.assertTrue(np.all(track.fusion.source_observation_slot[~track.fusion.valid_mask] == -1))
        self.assertTrue(np.all(track.fusion.bgr[~track.fusion.valid_mask] == 0))
        source_colors = {
            tuple(int(channel) for channel in pixel)
            for item in candidates
            for pixel in item.crop_bgr[np.asarray(item.observed_mask, dtype=bool)]
        }
        atlas_colors = {
            tuple(int(channel) for channel in pixel)
            for pixel in track.fusion.bgr[track.fusion.valid_mask]
        }
        self.assertTrue(atlas_colors.issubset(source_colors))
        self.assertTrue(
            all(
                observation.state is servo_sign_evidence.GeometryState.GEOMETRY_VERIFIED
                for observation in bundle.observations
            )
        )

    def test_fewer_than_three_or_only_adjacent_views_remain_unverified(self) -> None:
        only_two = three_view_candidates()[:2]
        bundle = servo_sign_evidence.build_sign_evidence(only_two, provenance())
        self.assertEqual(bundle.tracks[0].state, servo_sign_evidence.GeometryState.UNVERIFIED)
        self.assertIn("fewer-than-three-unique-views", bundle.tracks[0].reasons)
        adjacent = [
            candidate("a", 8, -0.5),
            candidate("b", 8, 0.0),
            candidate("c", 9, 0.5),
        ]
        bundle = servo_sign_evidence.build_sign_evidence(adjacent, provenance())
        self.assertEqual(bundle.tracks[0].state, servo_sign_evidence.GeometryState.UNVERIFIED)
        self.assertIn("no-nonadjacent-view", bundle.tracks[0].reasons)

    def test_semantic_sky_road_and_dynamic_contamination_is_rejected(self) -> None:
        for label in (1, 17, 18):  # road, sky, vehicle
            with self.subTest(label=label):
                item = candidate("bad", 0, 0.0, forbidden=label)
                result = servo_sign_evidence.evaluate_observation(
                    item, servo_sign_evidence.SignEvidenceConfig()
                )
                self.assertEqual(result.state, servo_sign_evidence.GeometryState.UNVERIFIED)
                self.assertIn("sky-road-or-dynamic-contamination", result.reasons)
                self.assertIsNone(result.plane)

    def test_inconsistent_depth_is_rejected_before_tracking(self) -> None:
        result = servo_sign_evidence.evaluate_observation(
            candidate("bad-depth", 0, 0.0, inconsistent_depth=True),
            servo_sign_evidence.SignEvidenceConfig(),
        )
        self.assertTrue(any(reason.startswith("inconsistent-depth-plane:") for reason in result.reasons))
        self.assertIsNone(result.plane)

    def test_nearby_physical_signs_are_separate_tracks(self) -> None:
        candidates = three_view_candidates()
        candidates.extend(
            candidate(f"other-{slot}", frame, camera_x, sign_x=3.0)
            for slot, (frame, camera_x) in enumerate(zip((0, 1, 3), (-0.65, 0.0, 0.65)))
        )
        bundle = servo_sign_evidence.build_sign_evidence(candidates, provenance())
        self.assertEqual(len(bundle.tracks), 2)
        self.assertTrue(
            all(track.state is servo_sign_evidence.GeometryState.GEOMETRY_VERIFIED for track in bundle.tracks)
        )

    def test_regulatory_class_and_text_require_external_cross_view_agreement(self) -> None:
        no_recognition = servo_sign_evidence.build_sign_evidence(
            three_view_candidates(), provenance()
        ).tracks[0]
        self.assertEqual(no_recognition.regulatory_class.state, servo_sign_evidence.ClaimState.UNVERIFIED)
        self.assertEqual(no_recognition.text.state, servo_sign_evidence.ClaimState.UNVERIFIED)

        agreed = servo_sign_evidence.build_sign_evidence(
            three_view_candidates(
                recognition_values=("SPEED_LIMIT_25", "SPEED_LIMIT_25", "SPEED_LIMIT_25")
            ),
            provenance(),
        ).tracks[0]
        self.assertEqual(agreed.regulatory_class.state, servo_sign_evidence.ClaimState.CROSS_VIEW_VERIFIED)
        self.assertEqual(agreed.regulatory_class.value, "SPEED_LIMIT_25")
        self.assertEqual(agreed.text.state, servo_sign_evidence.ClaimState.CROSS_VIEW_VERIFIED)
        self.assertEqual(agreed.text.value, "SPEED 25")

        disagreement = servo_sign_evidence.build_sign_evidence(
            three_view_candidates(
                recognition_values=("SPEED_LIMIT_25", "SPEED_LIMIT_35", "SPEED_LIMIT_25")
            ),
            provenance(),
        ).tracks[0]
        self.assertEqual(disagreement.regulatory_class.state, servo_sign_evidence.ClaimState.UNVERIFIED)
        self.assertIn("external-cross-view-disagreement", disagreement.regulatory_class.reasons)
        self.assertEqual(disagreement.text.state, servo_sign_evidence.ClaimState.UNVERIFIED)

    def test_manifest_and_writer_are_deterministic_and_explicitly_not_collision_ready(self) -> None:
        bundle = servo_sign_evidence.build_sign_evidence(three_view_candidates(), provenance())
        first = json.dumps(bundle.manifest(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        second = json.dumps(bundle.manifest(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(first, second)
        manifest = json.loads(first)
        self.assertEqual(manifest["schema"], "servo.sign-evidence/v1")
        self.assertFalse(manifest["safety"]["collisionReady"])
        self.assertFalse(manifest["safety"]["containsGeneratedPixels"])
        self.assertFalse(manifest["safety"]["metricGeometry"])
        with tempfile.TemporaryDirectory() as directory:
            path = servo_sign_evidence.write_sign_evidence(bundle, Path(directory))
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written, manifest)
            self.assertTrue((Path(directory) / "sign-atlases" / "sign-track-000000.png").is_file())
            self.assertTrue(
                (Path(directory) / "sign-atlases" / "sign-track-000000-evidence.npz").is_file()
            )

    def test_malformed_camera_and_generated_provenance_fail_closed(self) -> None:
        malformed = candidate("bad-camera", 0, 0.0)
        pose = np.asarray(malformed.camera_to_world).copy()
        pose[0, 0] = 2.0
        malformed = servo_sign_evidence.dataclasses.replace(malformed, camera_to_world=pose)
        with self.assertRaisesRegex(servo_sign_evidence.SignEvidenceError, "orthonormal"):
            servo_sign_evidence.build_sign_evidence([malformed], provenance())
        generated = servo_sign_evidence.dataclasses.replace(
            provenance(), contains_generated_pixels=True
        )
        with self.assertRaisesRegex(servo_sign_evidence.SignEvidenceError, "generated pixels"):
            servo_sign_evidence.build_sign_evidence([candidate("one", 0, 0.0)], generated)


class ServoSignPipelineIntegrationTests(unittest.TestCase):
    @staticmethod
    def proposal_digest(mask: np.ndarray) -> str:
        value = np.asarray(mask, dtype=np.uint8)
        digest = hashlib.sha256()
        digest.update(
            servo_priors.canonical_json(
                {"dtype": str(value.dtype), "shape": list(value.shape)}
            )
        )
        digest.update(value.tobytes())
        return "sha256:" + digest.hexdigest()

    def test_component_crop_excludes_disconnected_pixels_inside_overlapping_box(self) -> None:
        # A hollow signboard-shaped component encloses another disconnected
        # proposal.  Cropping the binary class mask (the previous behavior)
        # wrongly includes both even though OpenCV's area belongs to one.
        binary = np.zeros((15, 15), dtype=np.uint8)
        binary[1, 1:14] = 1
        binary[13, 1:14] = 1
        binary[1:14, 1] = 1
        binary[1:14, 13] = 1
        binary[6:9, 6:9] = 1
        count, labels, statistics, _ = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )
        self.assertEqual(count, 3)
        outer = int(labels[1, 1])
        x, y, width, height, area = (
            int(value) for value in statistics[outer].tolist()
        )
        legacy_crop = binary[y : y + height, x : x + width]
        self.assertGreater(int(np.count_nonzero(legacy_crop)), area)

        exact = servo_priors.exact_connected_component_crop(
            labels, statistics, outer
        )
        self.assertEqual(exact[:5], (x, y, width, height, area))
        exact_mask = exact[5]
        self.assertEqual(int(np.count_nonzero(exact_mask)), area)
        self.assertEqual(int(exact_mask[6, 6]), 0)

    def test_prior_pipeline_preserves_broad_proposals_and_verifies_only_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = []
            depths = []
            semantics = []
            observations = []
            focal = 120.0
            for frame_index, camera_x in zip((0, 1, 3), (-0.65, 0.0, 0.65)):
                image = np.zeros((96, 128, 3), dtype=np.uint8)
                center_x = focal * -camera_x / 8.0 + 64.0
                x = round(center_x - 12.0)
                y, width, height = 39, 24, 18
                image[y : y + height, x : x + width] = cv2.resize(
                    sign_pattern(blurred=frame_index != 1),
                    (width, height),
                    interpolation=cv2.INTER_AREA,
                )
                image_path = root / f"frame-{frame_index:04d}.png"
                self.assertTrue(cv2.imwrite(str(image_path), image))
                calibration = np.asarray(
                    [[focal, 0.0, 64.0], [0.0, focal, 48.0], [0.0, 0.0, 1.0]],
                    dtype=np.float64,
                )
                camera_to_world = np.eye(4, dtype=np.float64)
                camera_to_world[0, 3] = camera_x
                records.append(
                    SimpleNamespace(
                        name=f"frame-{frame_index:04d}.png",
                        path=image_path,
                        width=128,
                        height=96,
                        calibration=calibration,
                        camera_to_world=camera_to_world,
                    )
                )
                depths.append(np.full((96, 128), 8.0, dtype=np.float32))
                semantics.append(np.full((96, 128), 24, dtype=np.uint8))
                mask = np.ones((height, width), dtype=np.uint8)
                candidate_id = f"sign-proposal-{len(records) - 1:06d}-0001"
                observations.append(
                    {
                        "candidateId": candidate_id,
                        "image": records[-1].name,
                        "frameIndex": len(records) - 1,
                        "boxPriorPixels": [x, y, width, height],
                        "priorSize": [128, 96],
                        "areaPixels": int(mask.sum()),
                        "focus": 1.0,
                        "classification": "broad-signboard-candidate",
                        "sourceSemanticClass": {
                            "taxonomy": "ADE20K",
                            "id": 43,
                            "meaning": "signboard-broad-proposal-not-regulatory-identity",
                        },
                        "proposalMaskSha256": self.proposal_digest(mask),
                        "regulatoryTextVerified": False,
                        "_candidateMask": mask,
                    }
                )

            metrics = servo_priors.integrate_sign_evidence(
                records,
                depths,
                semantics,
                [IdentityDepthAlignment()] * len(records),
                observations,
                root / "evidence",
                128,
                job_id="fixture-job",
                profile="Fidelity",
                pipeline_revision="fixture-r7",
                configuration_hash="f" * 64,
            )
            self.assertEqual(metrics["proposalObservations"], 3)
            self.assertEqual(metrics["geometryVerifiedTracks"], 1)
            self.assertEqual(metrics["regulatoryClassVerifiedTracks"], 0)
            self.assertEqual(metrics["textVerifiedTracks"], 0)
            manifest = json.loads(
                (root / "evidence" / "sign-evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["tracks"][0]["state"], "geometry-verified")
            self.assertEqual(
                manifest["tracks"][0]["regulatoryClass"]["state"], "unverified"
            )
            self.assertEqual(manifest["tracks"][0]["text"]["state"], "unverified")
            self.assertFalse(manifest["safety"]["containsGeneratedPixels"])
            broad = json.loads(
                (root / "evidence" / "sign-observations.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(broad["summary"]["proposalObservations"], 3)
            self.assertEqual(broad["summary"]["geometryVerifiedTracks"], 1)
            self.assertFalse(broad["safety"]["metricGeometry"])
            self.assertFalse(
                broad["proposalSource"]["independentSemanticConfirmation"]
            )
            self.assertTrue(
                broad["safety"]["proposalAndSemanticSupportShareOneModel"]
            )
            self.assertTrue(
                all("_candidateMask" not in item for item in broad["observations"])
            )
            self.assertTrue(
                all(
                    (root / "evidence" / item["proposalMask"]).is_file()
                    for item in broad["observations"]
                )
            )

    def test_zero_proposals_is_a_valid_unverified_evidence_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            metrics = servo_priors.integrate_sign_evidence(
                [],
                [],
                [],
                [],
                [],
                output,
                128,
                job_id="empty-fixture",
                profile="Fidelity",
                pipeline_revision="fixture-r7",
                configuration_hash="e" * 64,
            )
            self.assertEqual(metrics["proposalObservations"], 0)
            self.assertEqual(metrics["geometryVerifiedTracks"], 0)
            self.assertTrue(metrics["zeroVerifiedSignsIsValid"])
            manifest = json.loads(
                (output / "sign-evidence.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["observations"], [])
            self.assertEqual(manifest["tracks"], [])
            broad = json.loads(
                (output / "sign-observations.json").read_text(encoding="utf-8")
            )
            self.assertTrue(broad["safety"]["zeroVerifiedSignsIsValid"])


if __name__ == "__main__":
    unittest.main()
