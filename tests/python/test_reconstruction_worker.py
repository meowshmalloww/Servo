from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[2]
WORKER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_worker.py"
SPEC = importlib.util.spec_from_file_location("servo_worker", WORKER_PATH)
assert SPEC is not None and SPEC.loader is not None
servo_worker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = servo_worker
SPEC.loader.exec_module(servo_worker)

TRAINER_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_train.py"
TRAINER_SPEC = importlib.util.spec_from_file_location("servo_train", TRAINER_PATH)
assert TRAINER_SPEC is not None and TRAINER_SPEC.loader is not None
servo_train = importlib.util.module_from_spec(TRAINER_SPEC)
sys.modules[TRAINER_SPEC.name] = servo_train
TRAINER_SPEC.loader.exec_module(servo_train)

AUDIT_PATH = REPOSITORY / "tools" / "reconstruction" / "servo_audit_world.py"
AUDIT_SPEC = importlib.util.spec_from_file_location("servo_audit_world", AUDIT_PATH)
assert AUDIT_SPEC is not None and AUDIT_SPEC.loader is not None
servo_audit_world = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules[AUDIT_SPEC.name] = servo_audit_world
AUDIT_SPEC.loader.exec_module(servo_audit_world)


BASE_PROPERTIES = [
    "x", "y", "z",
    "f_dc_0", "f_dc_1", "f_dc_2",
    "opacity",
    "scale_0", "scale_1", "scale_2",
    "rot_0", "rot_1", "rot_2", "rot_3",
]


def write_binary_ply(
    path: Path,
    rows: list[list[float]],
    properties: list[str] | None = None,
) -> None:
    names = properties or BASE_PROPERTIES
    header = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {len(rows)}",
        *[f"property float {name}" for name in names],
        "end_header",
        "",
    ]
    with path.open("wb") as stream:
        stream.write("\n".join(header).encode("ascii"))
        for row in rows:
            stream.write(struct.pack("<" + "f" * len(row), *row))


def valid_row(properties: list[str] | None = None) -> list[float]:
    names = properties or BASE_PROPERTIES
    values = {
        "x": 1.0,
        "y": -2.0,
        "z": 3.0,
        "f_dc_0": 0.1,
        "f_dc_1": 0.2,
        "f_dc_2": 0.3,
        "opacity": 0.0,
        "scale_0": -2.0,
        "scale_1": -2.1,
        "scale_2": -2.2,
        "rot_0": 1.0,
        "rot_1": 0.0,
        "rot_2": 0.0,
        "rot_3": 0.0,
    }
    for index in range(9):
        values[f"f_rest_{index}"] = 0.01 * index
    return [values[name] for name in names]


def write_sign_contract_fixture(
    root: Path,
    *,
    job_id: str = "sign-contract-job",
    profile: str = "balanced-12gb",
    pipeline_revision: str = "fixture-r7",
    configuration_hash: str = "sha256:" + "f" * 64,
    with_verified_track: bool = False,
) -> tuple[list[Path], dict[str, object]]:
    import cv2
    import numpy as np

    frame_count = 3 if with_verified_track else 1
    semantic_files: list[Path] = []
    for index in range(frame_count):
        path = root / "semantics" / "camera" / f"{index:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(path), np.zeros((8, 8), dtype=np.uint8))
        semantic_files.append(path)

    provenance = {
        "sequence_id": job_id,
        "coordinate_frame_id": f"colmap-undistorted:{job_id}",
        "scale_provenance": "sfm-arbitrary-scale",
        "camera_source": "COLMAP registered undistorted pinhole cameras",
        "depth_source": "aligned relative depth",
        "semantic_source": "OneFormer broad signboard proposals",
        "candidate_source": "ADE20K class-43 connected components",
        "distortion_state": "undistorted",
        "depth_alignment": "camera-z-in-coordinate-frame",
        "contains_generated_pixels": False,
        "source_hashes": {
            "oneformer-checkpoint": "sha256:" + servo_worker.ONEFORMER_CHECKPOINT_SHA256,
            "video-depth-checkpoint": "sha256:" + servo_worker.VIDEO_DEPTH_CHECKPOINT_SHA256,
        },
    }
    config = {
        "minimum_views": 3,
        "minimum_nonadjacent_gap": 2,
        "atlas_max_dimension": 512,
    }
    manifest_observations: list[dict[str, object]] = []
    public_observations: list[dict[str, object]] = []
    tracks: list[dict[str, object]] = []
    proposal_count = 3 if with_verified_track else 0
    plane = {
        "normal": [0.0, 0.0, 1.0],
        "offset": -8.0,
        "center": [0.0, 0.0, 8.0],
        "scale": 1.0,
        "sampleCount": 64,
        "inlierCount": 64,
        "inlierRatio": 1.0,
        "p95InlierResidualRatio": 0.0,
    }
    candidate_ids: list[str] = []
    if with_verified_track:
        mask = np.ones((2, 2), dtype=np.uint8)
        mask_sha256 = servo_worker._sign_proposal_mask_sha256(mask)
        for index in range(3):
            candidate_id = f"sign-proposal-{index:06d}-0001"
            candidate_ids.append(candidate_id)
            evidence_sha256 = "sha256:" + f"{index + 1:x}" * 64
            image = f"camera/{index:03d}.png"
            manifest_observations.append(
                {
                    "candidateId": candidate_id,
                    "frameId": image,
                    "frameIndex": index,
                    "state": "geometry-verified",
                    "reasons": [],
                    "evidenceSha256": evidence_sha256,
                    "signFraction": 1.0,
                    "forbiddenFraction": 0.0,
                    "depthCoverage": 1.0,
                    "sharpness": 10.0,
                    "plane": plane,
                }
            )
            mask_path = root / "sign-proposals" / f"{candidate_id}.png"
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            assert cv2.imwrite(str(mask_path), mask * 255)
            public_observations.append(
                {
                    "candidateId": candidate_id,
                    "image": image,
                    "frameIndex": index,
                    "boxPriorPixels": [1, 1, 2, 2],
                    "priorSize": [8, 8],
                    "areaPixels": 4,
                    "focus": 10.0,
                    "classification": "broad-signboard-candidate",
                    "sourceSemanticClass": {
                        "taxonomy": "ADE20K",
                        "id": 43,
                        "meaning": "signboard-broad-proposal-not-regulatory-identity",
                    },
                    "proposalMaskSha256": mask_sha256,
                    "regulatoryTextVerified": False,
                    "proposalMask": f"sign-proposals/{candidate_id}.png",
                    "geometryState": "geometry-verified",
                    "geometryReasons": [],
                    "geometryEvidenceSha256": evidence_sha256,
                }
            )
        atlas = np.full((2, 2, 3), [10, 20, 30], dtype=np.uint8)
        valid_mask = np.ones((2, 2), dtype=bool)
        support_count = np.full((2, 2), 3, dtype=np.uint16)
        source_slot = np.zeros((2, 2), dtype=np.int16)
        atlas_root = root / "sign-atlases"
        atlas_root.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(atlas_root / "sign-track-000000.png"), atlas)
        np.savez_compressed(
            atlas_root / "sign-track-000000-evidence.npz",
            valid_mask=valid_mask,
            support_count=support_count,
            source_observation_slot=source_slot,
        )
        tracks.append(
            {
                "trackId": "sign-track-000000",
                "state": "geometry-verified",
                "reasons": [],
                "observationIds": candidate_ids,
                "selectedObservationIds": candidate_ids,
                "cameraBaselineRatio": 1.0,
                "centroidDispersionRatio": 0.0,
                "normalP95Degrees": 0.0,
                "plane": plane,
                "regulatoryClass": {
                    "state": "unverified",
                    "value": None,
                    "supportingObservations": [],
                    "reasons": ["fewer-than-three-external-views"],
                },
                "text": {
                    "state": "unverified",
                    "value": None,
                    "supportingObservations": [],
                    "reasons": ["fewer-than-three-external-views"],
                },
                "fusion": {
                    "shape": [2, 2, 3],
                    "validFraction": 1.0,
                    "maximumSupport": 3,
                    "observationOrder": candidate_ids,
                    "planeBounds": [-1.0, -1.0, 1.0, 1.0],
                    "sampling": "nearest-observed-pixel",
                    "generatedPixels": False,
                    "bgrSha256": servo_worker._sign_array_sha256(atlas),
                    "validMaskSha256": servo_worker._sign_array_sha256(valid_mask),
                    "sourceMapSha256": servo_worker._sign_array_sha256(source_slot),
                },
            }
        )
    manifest = {
        "schema": "servo.sign-evidence/v1",
        "algorithm": "servo-sign-plane-cleanroom/1.0.0",
        "runtime": {"numpy": np.__version__, "opencv": cv2.__version__},
        "cameraConvention": "camera-to-world; camera +x right, +y down, +z forward",
        "provenance": provenance,
        "config": config,
        "researchReferences": [],
        "safety": {
            "collisionReady": False,
            "metricGeometry": False,
            "containsGeneratedPixels": False,
            "geometryVerificationDoesNotVerifyRegulatoryMeaning": True,
        },
        "observations": manifest_observations,
        "tracks": tracks,
    }
    summary = {
        "proposalObservations": proposal_count,
        "planarObservations": proposal_count,
        "geometryVerifiedObservations": proposal_count,
        "tracks": 1 if with_verified_track else 0,
        "geometryVerifiedTracks": 1 if with_verified_track else 0,
        "regulatoryClassVerifiedTracks": 0,
        "textVerifiedTracks": 0,
    }
    observations = {
        "schema": "servo.sign-observations/v1",
        "jobId": job_id,
        "profile": profile,
        "pipelineRevision": pipeline_revision,
        "configurationHash": configuration_hash,
        "classification": "broad-semantic-proposals-with-separate-calibrated-geometry-evidence",
        "structuredEvidence": "sign-evidence.json",
        "proposalSource": {
            "producer": "shi-labs/oneformer_ade20k_swin_tiny",
            "taxonomy": "ADE20K",
            "classId": 43,
            "meaning": "broad-signboard-candidate-not-regulatory-identity",
            "exactMasksPersisted": True,
            "independentSemanticConfirmation": False,
        },
        "observations": public_observations,
        "summary": summary,
        "safety": {
            "collisionReady": False,
            "metricGeometry": False,
            "containsGeneratedPixels": False,
            "geometryDoesNotVerifyRegulatoryMeaning": True,
            "proposalAndSemanticSupportShareOneModel": True,
            "zeroVerifiedSignsIsValid": True,
        },
        "requirements": (
            "Regulatory text and class remain unverified until a separate "
            "external recognizer agrees across at least three calibrated views."
        ),
    }
    (root / "sign-evidence.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    (root / "sign-observations.json").write_text(
        json.dumps(observations, sort_keys=True), encoding="utf-8"
    )
    metrics: dict[str, object] = {
        "schema": "servo.sign-evidence/v1",
        "algorithm": "servo-sign-plane-cleanroom/1.0.0",
        **summary,
        "containsGeneratedPixels": False,
        "independentSemanticConfirmation": False,
        "metric": False,
        "collisionValidated": False,
        "zeroVerifiedSignsIsValid": True,
    }
    return semantic_files, metrics


class ReconstructionWorkerTests(unittest.TestCase):
    def test_pipeline_snapshot_hashes_evidence_implementations(self) -> None:
        manifest = servo_worker.pipeline_source_manifest()
        self.assertIn("servo_road_semantics.py", manifest)
        self.assertIn("servo_sign_evidence.py", manifest)
        for name in ("servo_road_semantics.py", "servo_sign_evidence.py"):
            self.assertRegex(manifest[name], r"^sha256:[0-9a-f]{64}$")

    def test_observed_road_surface_gate_requires_converged_supported_graph(self) -> None:
        valid = {
            "observedSurface": {
                "model": "sparse-connected-road-cell-graph-v1",
                "converged": True,
                "candidateCellCount": 587,
                "retainedCellCount": 576,
                "componentCount": 7,
                "retainedComponentCount": 1,
                "anchorCellCount": 498,
                "blockedCellCount": 50,
                "ambiguousCellCount": 0,
                "inlierRatio": 0.94,
                "p50AbsoluteResidual": 0.0003,
                "p95AbsoluteResidual": 0.004,
                "maxAbsoluteResidual": 0.046,
                "maximumCellP95Residual": 0.00356,
                "iterations": 105,
                "solverPolicy": "adaptive-huber-with-cycle-midpoint-freeze-v1",
                "huberScale": 0.0000164,
                "huberScaleFrozen": True,
                "huberObjective": 0.000145,
                "relativeSolutionChange": 9.4e-10,
                "normalizedWeightChange": 9.9e-6,
                "twoCycleSolutionChange": 1.2e-7,
                "twoCycleWeightChange": 9.1e-6,
                "firstOrderOptimality": 2.1e-5,
                "backtrackingSteps": 0,
                "terminationReason": "cycle-midpoint-fixed-scale-huber",
            }
        }
        self.assertIs(
            servo_worker.validate_observed_road_surface_metrics(valid),
            valid["observedSurface"],
        )
        for field, value in (
            ("converged", False),
            ("retainedCellCount", 0),
            ("retainedComponentCount", 0),
            ("anchorCellCount", 0),
            ("anchorCellCount", 577),
            ("inlierRatio", 0.64),
            ("p95AbsoluteResidual", 0.151),
            ("maximumCellP95Residual", -0.001),
            ("maximumCellP95Residual", 0.10),
            ("maximumCellP95Residual", 0.151),
            ("model", "nearest-neighbour-fill"),
            ("candidateCellCount", 1200),
            ("ambiguousCellCount", 51),
            ("iterations", 257),
            ("solverPolicy", "adaptive-mad-with-unbounded-cycle"),
            ("huberScale", -0.001),
            ("huberObjective", -0.001),
            ("relativeSolutionChange", 1.1e-8),
            ("normalizedWeightChange", 1.1e-5),
            ("firstOrderOptimality", 1.1e-4),
            ("backtrackingSteps", 1001),
            ("terminationReason", "iteration-limit"),
            ("huberScaleFrozen", False),
            ("huberScale", 0.0),
            ("huberObjective", 0.0),
            ("twoCycleSolutionChange", 1.1e-5),
            ("twoCycleWeightChange", 1.1e-3),
        ):
            rejected = json.loads(json.dumps(valid))
            rejected["observedSurface"][field] = value
            with self.subTest(field=field), self.assertRaises(
                servo_worker.WorkerError
            ):
                servo_worker.validate_observed_road_surface_metrics(rejected)

    def test_road_surface_document_is_bound_to_gated_metrics(self) -> None:
        observed = {
            "model": "sparse-connected-road-cell-graph-v1",
            "solverPolicy": "adaptive-huber-with-cycle-midpoint-freeze-v1",
            "converged": True,
            "candidateCellCount": 2,
            "retainedCellCount": 2,
            "componentCount": 1,
            "retainedComponentCount": 1,
            "anchorCellCount": 1,
            "blockedCellCount": 1,
            "ambiguousCellCount": 0,
            "inlierRatio": 0.94,
            "p50AbsoluteResidual": 0.0003,
            "p95AbsoluteResidual": 0.004,
            "maxAbsoluteResidual": 0.046,
            "maximumCellP95Residual": 0.00356,
            "iterations": 144,
            "huberScale": 0.0000164,
            "huberScaleFrozen": True,
            "huberObjective": 0.000145,
            "relativeSolutionChange": 9.4e-10,
            "normalizedWeightChange": 9.9e-6,
            "twoCycleSolutionChange": 1.2e-7,
            "twoCycleWeightChange": 9.1e-6,
            "firstOrderOptimality": 2.1e-5,
            "backtrackingSteps": 0,
            "terminationReason": "cycle-midpoint-fixed-scale-huber",
        }
        road_metrics = {
            "model": "piecewise-linear-elevation-and-bank-plus-observed-cell-graph-v1",
            "observedSurface": observed,
        }
        road_observed = {
            **observed,
            "cellIndices": [[0, 0], [1, 0]],
            "heights": [0.0, 0.01],
            "slopes": [[0.0, 0.0], [0.0, 0.0]],
            "supportCounts": [4, 5],
            "frameCounts": [3, 3],
            "blockedCellKeys": [7],
            "gridOrigin": [0.0, 0.0],
            "gridShape": [2, 2],
        }
        document = {
            "schema": "servo.road-surface/v1",
            "jobId": "job",
            "profile": "fidelity-12gb",
            "pipelineRevision": servo_worker.PIPELINE_REVISION,
            "configurationHash": "sha256:" + "a" * 64,
            "sourceFrames": 3,
            "metric": False,
            "collisionValidated": False,
            "scaleProvenance": "sfm-arbitrary",
            "surface": {"model": road_metrics["model"]},
            "observedSurface": road_observed,
        }
        self.assertIs(
            servo_worker.validate_road_surface_document(
                document,
                road_metrics,
                expected_images=3,
                job_id="job",
                profile="fidelity-12gb",
                pipeline_revision=servo_worker.PIPELINE_REVISION,
                configuration_hash="sha256:" + "a" * 64,
            ),
            document,
        )
        for mutation in (
            lambda value: value["observedSurface"].__setitem__("heights", [0.0]),
            lambda value: value["observedSurface"].__setitem__("inlierRatio", 0.95),
            lambda value: value.__setitem__("sourceFrames", 2),
        ):
            rejected = json.loads(json.dumps(document))
            mutation(rejected)
            with self.assertRaises(servo_worker.WorkerError):
                servo_worker.validate_road_surface_document(
                    rejected,
                    road_metrics,
                    expected_images=3,
                    job_id="job",
                    profile="fidelity-12gb",
                    pipeline_revision=servo_worker.PIPELINE_REVISION,
                    configuration_hash="sha256:" + "a" * 64,
                )

    def test_zero_evidence_road_paint_artifacts_cover_every_frame(self) -> None:
        import numpy as np
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            image_names = ["camera/000.jpg", "camera/001.jpg"]
            semantic_files: list[Path] = []
            for image_name in image_names:
                relative = Path(image_name).with_suffix(".png")
                semantic = output / "semantics" / relative
                classes = output / "road-paint" / "classes" / relative
                confidence = output / "road-paint" / "confidence" / relative
                for path in (semantic, classes, confidence):
                    path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(np.ones((3, 4), dtype=np.uint8)).save(semantic)
                Image.fromarray(np.zeros((3, 4), dtype=np.uint8)).save(classes)
                Image.fromarray(np.zeros((3, 4), dtype=np.uint8)).save(confidence)
                semantic_files.append(semantic)

            frame_metrics = [
                {
                    "image": image_name,
                    "neighbourViews": 1,
                    "availableObservations": 2,
                    "proposedPixels": 0,
                    "acceptedPixels": 0,
                    "rejectedPixels": 0,
                    "unsupportedPixels": 0,
                    "extractionSuppressed": False,
                }
                for image_name in image_names
            ]
            metrics = {
                "schema": "servo.road-paint-consensus/v1",
                "method": (
                    "road-gated-absolute-color-local-ridge-plus-calibrated-"
                    "same-color-adjacent-depth-consensus-v2"
                ),
                "frames": 2,
                "proposalPixels": 0,
                "preSuppressionProposalPixels": 0,
                "suppressedFrames": 0,
                "longestConsecutiveSuppressedFrames": 0,
                "acceptedPixels": 0,
                "rejectedPixels": 0,
                "unsupportedPixels": 0,
                "acceptedFractionOfProposals": 0.0,
                "whitePixels": 0,
                "yellowPixels": 0,
                "supportedWarpSamples": 0,
                "correspondenceOcclusionPolicy": {
                    "nearerObservationRelativeTolerance": 0.08,
                    "maximumSymmetricRelativeDepthDisagreement": 0.25,
                    "borderSampling": "finite-pixel-centres-only",
                },
                "pretrainedWeights": None,
                "metric": False,
                "collisionValidated": False,
                "extractionProvenance": {
                    "schema": "servo.road-paint-evidence/v1",
                    "method": "road-gated-absolute-color-local-ridge-thickness-components-v2",
                    "deterministic": True,
                    "pretrainedWeights": None,
                },
                "consensusProvenance": {
                    "schema": "servo.road-paint-consensus/v1",
                    "method": "calibrated-dense-warp-repeat-observation-v1",
                    "deterministic": True,
                    "configuration": {"require_same_color": True},
                },
                "framesMetrics": frame_metrics,
                "maximumResidentEvidenceFrames": 3,
                "limitations": ["No visible paint is a valid observed result."],
            }
            classes, confidence = servo_worker.validate_road_paint_artifacts(
                output, semantic_files, metrics, len(image_names)
            )
            self.assertEqual(len(classes), 2)
            self.assertEqual(len(confidence), 2)

            metrics["correspondenceOcclusionPolicy"][
                "nearerObservationRelativeTolerance"
            ] = 0.09
            with self.assertRaisesRegex(
                servo_worker.WorkerError, "occlusion policy"
            ):
                servo_worker.validate_road_paint_artifacts(
                    output, semantic_files, metrics, len(image_names)
                )
            metrics["correspondenceOcclusionPolicy"][
                "nearerObservationRelativeTolerance"
            ] = 0.08

            metrics["longestConsecutiveSuppressedFrames"] = 1
            with self.assertRaises(servo_worker.WorkerError):
                servo_worker.validate_road_paint_artifacts(
                    output, semantic_files, metrics, len(image_names)
                )
            metrics["longestConsecutiveSuppressedFrames"] = 0

            confidence[-1].unlink()
            with self.assertRaisesRegex(
                servo_worker.WorkerError, "do not cover every registered image"
            ):
                servo_worker.validate_road_paint_artifacts(
                    output, semantic_files, metrics, len(image_names)
                )

    def test_zero_proposal_sign_evidence_is_valid_and_path_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            semantic_files, metrics = write_sign_contract_fixture(root)
            artifacts = servo_worker.validate_sign_evidence_artifacts(
                root,
                semantic_files,
                metrics,
                1,
                job_id="sign-contract-job",
                profile="balanced-12gb",
                pipeline_revision="fixture-r7",
                configuration_hash="sha256:" + "f" * 64,
            )
            self.assertEqual(artifacts, [root / "sign-evidence.json"])

            manifest = json.loads(
                (root / "sign-evidence.json").read_text(encoding="utf-8")
            )
            manifest["provenance"]["coordinate_frame_id"] = (
                r"C:\private\capture"
            )
            (root / "sign-evidence.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaises(servo_worker.WorkerError):
                servo_worker.validate_sign_evidence_artifacts(
                    root,
                    semantic_files,
                    metrics,
                    1,
                    job_id="sign-contract-job",
                    profile="balanced-12gb",
                    pipeline_revision="fixture-r7",
                    configuration_hash="sha256:" + "f" * 64,
                )

    def test_observed_directional_environment_is_hashed_and_never_fills_unknown_texels(self) -> None:
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "environment" / "observed-sky-equirectangular.png"
            asset.parent.mkdir(parents=True, exist_ok=True)
            rgba = np.zeros((32, 64, 4), dtype=np.uint8)
            rgba[16, 32] = np.asarray([30, 20, 10, 255], dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(asset), rgba))
            descriptor = {
                "schema": "servo.observed-directional-environment/v1",
                "method": "oneformer-observed-sky-equirectangular-rgba-v1",
                "projection": "equirectangular-atan2-x-z-y-up-v1",
                "asset": "environment/observed-sky-equirectangular.png",
                "assetSha256": servo_worker.sha256_file(asset),
                "width": 64,
                "height": 32,
                "colorSpace": "srgb",
                "alphaMeaning": "one-or-more-observed-oneformer-sky-samples-per-texel",
                "aggregation": "deterministic-mean-observed-sky-rgb-per-texel-no-inpainting-v1",
                "sourceSkyLabel": 17,
                "sourceImages": 2,
                "imagesWithSky": 1,
                "sourceSkyPixels": 1,
                "sampledSkyPixels": 1,
                "observedTexels": 1,
                "coverageFraction": 1.0 / (64 * 32),
                "containsGeneratedPixels": False,
                "finiteGeometry": False,
                "metric": False,
            }
            self.assertEqual(
                servo_worker.validate_observed_directional_environment_artifact(
                    root, descriptor, 2
                ),
                asset,
            )
            rgba[0, 0] = np.asarray([1, 1, 1, 0], dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(asset), rgba))
            descriptor["assetSha256"] = servo_worker.sha256_file(asset)
            with self.assertRaisesRegex(servo_worker.WorkerError, "generated colour"):
                servo_worker.validate_observed_directional_environment_artifact(
                    root, descriptor, 2
                )

    def test_certified_sky_evidence_is_hash_bound_and_cannot_target_non_sky(self) -> None:
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames: list[dict[str, object]] = []
            semantic_files: list[Path] = []
            for index in range(3):
                image = f"camera/{index:03d}.png"
                semantic_path = root / "semantics" / image
                evidence_path = root / "sky-evidence" / image
                semantic_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                semantic = np.full((9, 9), 17, dtype=np.uint8)
                evidence = np.full((9, 9), 1, dtype=np.uint8)
                self.assertTrue(cv2.imwrite(str(semantic_path), semantic))
                self.assertTrue(cv2.imwrite(str(evidence_path), evidence))
                semantic_files.append(semantic_path)
                frames.append(
                    {
                        "image": image,
                        "asset": f"sky-evidence/{image}",
                        "assetSha256": servo_worker.sha256_file(evidence_path),
                        "rawSkyPixels": 81,
                        "interiorSkyPixels": 81,
                        "certifiedSkyPixels": 81,
                        "unconfirmedSkyPixels": 0,
                        "observedNonSkyPixels": 0,
                        "neighbourViews": 2,
                    }
                )
            manifest = {
                "schema": "servo.certified-sky-evidence/v1",
                "method": "oneformer-rotation-only-temporal-consensus-v1",
                "storage": "uint8-tristate/0-unknown/1-certified-sky/2-observed-non-sky",
                "rotationOnlyInfiniteSky": True,
                "minimumSupportingViews": 2,
                "neighbourWindow": 4,
                "erosionRadius": 2,
                "sourceSemanticLabel": 17,
                "source": "pinned-oneformer-ade20k-temporal-consensus",
                "frames": frames,
                "registeredImages": 3,
                "certifiedSkyPixels": 243,
                "unconfirmedSkyPixels": 0,
                "containsGeneratedPixels": False,
                "finiteGeometry": False,
                "metric": False,
            }
            manifest_path = root / "sky-evidence.json"
            servo_worker.atomic_write_json(manifest_path, manifest)
            descriptor = {
                **manifest,
                "manifest": "sky-evidence.json",
                "manifestSha256": servo_worker.sha256_file(manifest_path),
            }
            files = servo_worker.validate_certified_sky_evidence_artifact(
                root, descriptor, semantic_files, 3
            )
            self.assertEqual(files[0], manifest_path)
            self.assertEqual(len(files), 4)

            semantic = cv2.imread(str(semantic_files[0]), cv2.IMREAD_UNCHANGED)
            assert semantic is not None
            semantic[0, 0] = 1
            self.assertTrue(cv2.imwrite(str(semantic_files[0]), semantic))
            with self.assertRaisesRegex(servo_worker.WorkerError, "destructive"):
                servo_worker.validate_certified_sky_evidence_artifact(
                    root, descriptor, semantic_files, 3
                )

    def test_sign_masks_atlases_and_maps_are_hash_verified_without_ocr(self) -> None:
        import cv2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            semantic_files, metrics = write_sign_contract_fixture(
                root, with_verified_track=True
            )
            artifacts = servo_worker.validate_sign_evidence_artifacts(
                root,
                semantic_files,
                metrics,
                3,
                job_id="sign-contract-job",
                profile="balanced-12gb",
                pipeline_revision="fixture-r7",
                configuration_hash="sha256:" + "f" * 64,
            )
            self.assertEqual(len(artifacts), 6)
            self.assertEqual(
                len([path for path in artifacts if path.parent.name == "sign-proposals"]),
                3,
            )

            observations_path = root / "sign-observations.json"
            observations = json.loads(observations_path.read_text(encoding="utf-8"))
            observations["observations"][0]["image"] = r"C:\private\frame.png"
            observations_path.write_text(json.dumps(observations), encoding="utf-8")
            with self.assertRaisesRegex(servo_worker.WorkerError, "private"):
                servo_worker.validate_sign_evidence_artifacts(
                    root,
                    semantic_files,
                    metrics,
                    3,
                    job_id="sign-contract-job",
                    profile="balanced-12gb",
                    pipeline_revision="fixture-r7",
                    configuration_hash="sha256:" + "f" * 64,
                )
            observations["observations"][0]["image"] = "camera/000.png"
            observations_path.write_text(json.dumps(observations), encoding="utf-8")

            manifest_path = root / "sign-evidence.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tracks"][0]["regulatoryClass"] = {
                "state": "cross-view-verified",
                "value": "STOP",
                "supportingObservations": manifest["tracks"][0]["observationIds"],
                "reasons": [],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(servo_worker.WorkerError, "unverified"):
                servo_worker.validate_sign_evidence_artifacts(
                    root,
                    semantic_files,
                    metrics,
                    3,
                    job_id="sign-contract-job",
                    profile="balanced-12gb",
                    pipeline_revision="fixture-r7",
                    configuration_hash="sha256:" + "f" * 64,
                )
            manifest["tracks"][0]["regulatoryClass"] = {
                "state": "unverified",
                "value": None,
                "supportingObservations": [],
                "reasons": ["fewer-than-three-external-views"],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            atlas_path = root / "sign-atlases" / "sign-track-000000.png"
            atlas = cv2.imread(str(atlas_path), cv2.IMREAD_COLOR)
            self.assertIsNotNone(atlas)
            atlas[0, 0, 0] ^= 1
            self.assertTrue(cv2.imwrite(str(atlas_path), atlas))
            with self.assertRaisesRegex(servo_worker.WorkerError, "hashes"):
                servo_worker.validate_sign_evidence_artifacts(
                    root,
                    semantic_files,
                    metrics,
                    3,
                    job_id="sign-contract-job",
                    profile="balanced-12gb",
                    pipeline_revision="fixture-r7",
                    configuration_hash="sha256:" + "f" * 64,
                )

    def test_validates_binary_degree_zero_ply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.ply"
            write_binary_ply(path, [valid_row(), valid_row()])
            result = servo_worker.parse_ply_header(path)
            self.assertEqual(result["vertexCount"], 2)
            self.assertEqual(result["shDegree"], 0)
            self.assertEqual(result["format"], "binary_little_endian")
            self.assertEqual(result["boundsMin"], [1.0, -2.0, 3.0])
            self.assertGreater(result["payloadBytes"], 0)

    def test_accepts_complete_degree_one_sh_basis(self) -> None:
        properties = BASE_PROPERTIES + [f"f_rest_{index}" for index in range(9)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "degree-one.ply"
            write_binary_ply(path, [valid_row(properties)], properties)
            result = servo_worker.parse_ply_header(path)
            self.assertEqual(result["shDegree"], 1)

    def test_rejects_partial_sh_basis(self) -> None:
        properties = BASE_PROPERTIES + [f"f_rest_{index}" for index in range(8)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.ply"
            write_binary_ply(path, [valid_row(properties)], properties)
            with self.assertRaises(servo_worker.WorkerError):
                servo_worker.parse_ply_header(path)

    def test_rejects_truncated_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.ply"
            write_binary_ply(path, [valid_row()])
            path.write_bytes(path.read_bytes()[:-3])
            with self.assertRaisesRegex(servo_worker.WorkerError, "truncated"):
                servo_worker.parse_ply_header(path)

    def test_rejects_non_finite_and_zero_quaternion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            nan_path = Path(directory) / "nan.ply"
            row = valid_row()
            row[0] = math.nan
            write_binary_ply(nan_path, [row])
            with self.assertRaisesRegex(servo_worker.WorkerError, "NaN"):
                servo_worker.parse_ply_header(nan_path)

            quaternion_path = Path(directory) / "zero-quaternion.ply"
            row = valid_row()
            for index in range(10, 14):
                row[index] = 0.0
            write_binary_ply(quaternion_path, [row])
            with self.assertRaisesRegex(servo_worker.WorkerError, "zero quaternion"):
                servo_worker.parse_ply_header(quaternion_path)

    def test_stage_receipt_detects_artifact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jpg"
            source.write_bytes(b"source")
            job_path = root / "job.json"
            job = {
                "schema": servo_worker.JOB_SCHEMA,
                "jobId": "receipt-test",
                "profile": "balanced-12gb",
                "sources": [{"path": str(source), "kind": "image"}],
            }
            job_path.write_text(json.dumps(job), encoding="utf-8")
            context = servo_worker.JobContext(
                job_path,
                job,
                servo_worker.PROFILES["balanced-12gb"],
            )
            artifact = context.stage_path("hash") / "sources.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "schema": "servo.reconstruction-sources/v1",
                        "sources": [
                            {
                                "path": str(source.resolve()),
                                "bytes": source.stat().st_size,
                                "sha256": servo_worker.sha256_file(source),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            context.commit_receipt("hash", {"count": 1}, [artifact])
            self.assertIsNotNone(context.valid_receipt("hash"))
            artifact.write_text("mutated", encoding="utf-8")
            self.assertIsNone(context.valid_receipt("hash"))

    def test_hash_receipt_detects_original_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jpg"
            source.write_bytes(b"source-one")
            job_path = root / "job.json"
            job = {
                "schema": servo_worker.JOB_SCHEMA,
                "jobId": "source-mutation-test",
                "profile": "balanced-12gb",
                "sources": [{"path": str(source), "kind": "image"}],
            }
            job_path.write_text(json.dumps(job), encoding="utf-8")
            context = servo_worker.JobContext(
                job_path,
                job,
                servo_worker.PROFILES["balanced-12gb"],
            )
            manifest = context.stage_path("hash") / "sources.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "servo.reconstruction-sources/v1",
                        "sources": [
                            {
                                "path": str(source.resolve()),
                                "bytes": source.stat().st_size,
                                "sha256": servo_worker.sha256_file(source),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            context.commit_receipt("hash", {"count": 1}, [manifest])
            self.assertIsNotNone(context.valid_receipt("hash"))
            source.write_bytes(b"source-two")
            self.assertIsNone(context.valid_receipt("hash"))

    def test_public_provenance_uses_allowlists_and_redacts_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "private" / "capture.jpg"
            sources, source_ids = servo_worker.public_source_records(
                [
                    {
                        "path": str(source_path),
                        "kind": "image",
                        "width": 1920,
                        "height": 1080,
                        "sha256": "sha256:test",
                        "privateUrl": "https://secret.invalid/token",
                        "catalogFingerprint": "host-private",
                    }
                ]
            )
            self.assertEqual(sources[0]["name"], "capture.jpg")
            self.assertEqual(sources[0]["sourceId"], "s000")
            self.assertNotIn("path", sources[0])
            self.assertNotIn("privateUrl", sources[0])
            self.assertNotIn("catalogFingerprint", sources[0])
            frames = servo_worker.public_frame_records(
                [
                    {
                        "image": "photo/000.jpg",
                        "source": str(source_path),
                        "focus": 80.0,
                        "privateNote": "do not publish",
                    }
                ],
                source_ids,
            )
            self.assertEqual(frames[0]["sourceId"], "s000")
            self.assertNotIn("source", frames[0])
            self.assertNotIn("privateNote", frames[0])

    def test_profiles_are_bounded_for_twelve_gigabytes(self) -> None:
        for profile in servo_worker.PROFILES.values():
            self.assertLessEqual(profile.expected_vram_gib, 11.0)
            self.assertGreater(profile.checkpoint_every, 0)
            self.assertGreaterEqual(profile.min_registered_ratio, 0.8)
            self.assertEqual(profile.rasterization_mode, "antialiased")
            self.assertEqual(profile.target_gaussians, 0)
            self.assertEqual(profile.max_gaussians, 0)
            self.assertLess(profile.coarse_steps, profile.max_steps)
            if profile.absgrad:
                self.assertGreaterEqual(profile.grow_grad2d, 0.0008)

    def test_pose_selection_prefers_candidate_that_passes_quality_gate(self) -> None:
        profile = servo_worker.PROFILES["balanced-12gb"]
        failed_incremental = (
            {
                "registeredImages": 100,
                "registeredRatio": 1.0,
                "points3D": 100_000,
                "p95ReprojectionError": profile.max_reprojection_error + 1.0,
            },
            "incremental",
            Path("incremental-0"),
        )
        passing_global = (
            {
                "registeredImages": 95,
                "registeredRatio": 0.95,
                "points3D": 80_000,
                "p95ReprojectionError": profile.max_reprojection_error - 0.1,
                "medianTrackLength": profile.min_median_track_length + 1.0,
                "cameraForwardStepMaxDegrees": 2.0,
                "cameraUpStepMaxDegrees": 2.0,
                "cameraSpeedMaxRatio": 2.0,
            },
            "global",
            Path("global-0"),
        )
        selected = servo_worker.select_pose_candidate(
            [failed_incremental, passing_global], profile
        )
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected[1], "global")

    def test_fidelity_pose_filter_retains_long_clean_tracks(self) -> None:
        profile = servo_worker.PROFILES["fidelity-12gb"]
        self.assertEqual(servo_worker.pose_filter_min_track_length(profile), 5)
        candidate = {
            "registeredImages": 373,
            "registeredRatio": 1.0,
            "points3D": 66_900,
            "p95ReprojectionError": 0.848,
            "medianTrackLength": 8.0,
            "cameraForwardStepMaxDegrees": 1.1,
            "cameraUpStepMaxDegrees": 0.28,
            "cameraSpeedMaxRatio": 1.7,
        }
        self.assertTrue(servo_worker.pose_candidate_passes_gate(candidate, profile))
        self.assertEqual(servo_worker.minimum_reliable_pose_points(candidate), 7_460)

        candidate["points3D"] = 7_459
        self.assertFalse(servo_worker.pose_candidate_passes_gate(candidate, profile))

    def test_pose_selection_prefers_broader_clean_fidelity_evidence(self) -> None:
        profile = servo_worker.PROFILES["fidelity-12gb"]
        smaller = (
            {
                "registeredImages": 373,
                "registeredRatio": 1.0,
                "points3D": 55_659,
                "p95ReprojectionError": 0.781,
                "medianTrackLength": 8.0,
                "cameraForwardStepMaxDegrees": 1.1,
                "cameraUpStepMaxDegrees": 0.28,
                "cameraSpeedMaxRatio": 2.3,
            },
            "global+confidence-filter",
            Path("filtered-global"),
        )
        exhaustive = (
            {
                "registeredImages": 373,
                "registeredRatio": 1.0,
                "points3D": 66_900,
                "p95ReprojectionError": 0.848,
                "medianTrackLength": 8.0,
                "cameraForwardStepMaxDegrees": 1.1,
                "cameraUpStepMaxDegrees": 0.28,
                "cameraSpeedMaxRatio": 1.7,
            },
            "global+exhaustive-guided+confidence-filter",
            Path("filtered-exhaustive"),
        )
        selected = servo_worker.select_pose_candidate([smaller, exhaustive], profile)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected[1], exhaustive[1])

    def test_fidelity_refinement_compares_incremental_and_global_seeds(self) -> None:
        profile = servo_worker.PROFILES["fidelity-12gb"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "database.db"
            database.write_bytes(b"sqlite-fixture")
            images = root / "images"
            images.mkdir()
            output = root / "pose"
            output.mkdir()
            for name in ("incremental", "global"):
                (root / name).mkdir()

            raw_scored = [
                (
                    {
                        "registeredImages": 373,
                        "registeredRatio": 1.0,
                        "points3D": 84_383,
                        "p95ReprojectionError": 1.59,
                        "medianTrackLength": 6.0,
                        "cameraForwardStepMaxDegrees": 1.1,
                    },
                    "incremental",
                    root / "incremental",
                ),
                (
                    {
                        "registeredImages": 373,
                        "registeredRatio": 1.0,
                        "points3D": 103_982,
                        "p95ReprojectionError": 1.32,
                        "medianTrackLength": 5.0,
                        "cameraForwardStepMaxDegrees": 1.1,
                    },
                    "global",
                    root / "global",
                ),
            ]
            context = SimpleNamespace(
                profile=profile,
                require_free_space=mock.Mock(),
                events=SimpleNamespace(emit=mock.Mock()),
            )

            def filtered_result(
                _context: object,
                _model: Path,
                filtered_output: Path,
                _selected_count: int,
                _timestamps: dict[str, float],
                solver: str,
            ) -> tuple[dict[str, object], str, Path]:
                return (
                    {
                        "registeredImages": 373,
                        "registeredRatio": 1.0,
                        "points3D": 66_900,
                        "p95ReprojectionError": 0.848,
                        "medianTrackLength": 8.0,
                        "cameraForwardStepMaxDegrees": 1.1,
                        "cameraUpStepMaxDegrees": 0.28,
                        "cameraSpeedMaxRatio": 1.7,
                    },
                    f"{solver}+confidence-filter",
                    filtered_output,
                )

            with (
                mock.patch.object(servo_worker, "run_colmap") as run_colmap,
                mock.patch.object(
                    servo_worker,
                    "filter_pose_candidate",
                    side_effect=filtered_result,
                ) as filter_candidate,
            ):
                results = servo_worker.fidelity_refine_pose_candidates(
                    context,
                    output,
                    images,
                    database,
                    raw_scored,
                    373,
                    {},
                )

            commands = [call.args[2][0] for call in run_colmap.call_args_list]
            self.assertEqual(commands.count("exhaustive_matcher"), 1)
            self.assertEqual(commands.count("point_triangulator"), 2)
            self.assertEqual(commands.count("bundle_adjuster"), 2)
            self.assertEqual(filter_candidate.call_count, 2)
            self.assertEqual(len(results), 2)
            self.assertEqual(
                {result[0]["fidelityRefinement"]["seedSolver"] for result in results},
                {"incremental", "global"},
            )

    def test_checkpoint_is_flushed_verified_and_published(self) -> None:
        import torch

        with tempfile.TemporaryDirectory() as directory:
            parameter = torch.nn.Parameter(torch.zeros((1, 3)))
            optimizer = torch.optim.Adam([parameter], lr=1e-3)
            scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.99)
            path = servo_train.save_checkpoint(
                Path(directory),
                17,
                {"means": parameter},
                {"means": optimizer},
                scheduler,
                {},
                {"densificationLimited": True},
                {
                    "configurationHash": "checkpoint-test",
                    "trainingInputHash": "sha256:" + "1" * 64,
                },
                SimpleNamespace(normalization={"scale": 1.0}),
            )
            self.assertTrue(path.is_file())
            pointer = json.loads((Path(directory) / "last-good.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["step"], 17)
            self.assertEqual(pointer["path"], path.name)
            self.assertEqual(pointer["sha256"], servo_train.sha256_file(path))
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
            self.assertEqual(
                checkpoint["opacityResetSemantics"],
                servo_train.OPACITY_RESET_SEMANTICS,
            )
            self.assertTrue(checkpoint["policyState"]["densificationLimited"])

    def test_checkpoint_rolls_back_when_latest_is_corrupt(self) -> None:
        import torch

        with tempfile.TemporaryDirectory() as directory:
            checkpoint_dir = Path(directory) / "checkpoints"
            parameter = torch.nn.Parameter(torch.zeros((1, 3)))
            optimizer = torch.optim.Adam([parameter], lr=1e-3)
            scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.99)
            config = {
                "configurationHash": "rollback-test",
                "trainingInputHash": "sha256:" + "2" * 64,
                "pipelineRevision": "test-pipeline",
            }
            dataset = SimpleNamespace(normalization={"scale": 1.0})
            first = servo_train.save_checkpoint(
                checkpoint_dir,
                9,
                {"means": parameter},
                {"means": optimizer},
                scheduler,
                {},
                {"densificationLimited": False},
                config,
                dataset,
            )
            latest = servo_train.save_checkpoint(
                checkpoint_dir,
                19,
                {"means": parameter},
                {"means": optimizer},
                scheduler,
                {},
                {"densificationLimited": False},
                config,
                dataset,
            )
            latest.write_bytes(latest.read_bytes() + b"corrupt")
            checkpoint = servo_train.load_checkpoint(checkpoint_dir, config)
            self.assertIsNotNone(checkpoint)
            assert checkpoint is not None
            self.assertEqual(checkpoint["step"], 9)
            pointer = json.loads(
                (checkpoint_dir / "last-good.json").read_text(encoding="utf-8")
            )
            self.assertEqual(pointer["path"], first.name)

    def test_streaming_export_writes_standard_degree_three_ply(self) -> None:
        import torch

        parameters = {
            "means": torch.zeros((2, 3), dtype=torch.float32),
            "sh0": torch.zeros((2, 1, 3), dtype=torch.float32),
            "shN": torch.zeros((2, 15, 3), dtype=torch.float32),
            "opacities": torch.zeros((2,), dtype=torch.float32),
            "scales": torch.full((2, 3), -2.0, dtype=torch.float32),
            "quats": torch.tensor(
                [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]],
                dtype=torch.float32,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.ply"
            servo_train.export_world(parameters, path)
            result = servo_worker.parse_ply_header(path)
            self.assertEqual(result["vertexCount"], 2)
            self.assertEqual(result["shDegree"], 3)

    def test_fidelity_export_records_renderer_contract(self) -> None:
        import torch

        parameters = {
            "means": torch.zeros((1, 3), dtype=torch.float32),
            "sh0": torch.zeros((1, 1, 3), dtype=torch.float32),
            "shN": torch.zeros((1, 15, 3), dtype=torch.float32),
            "opacities": torch.zeros((1,), dtype=torch.float32),
            "scales": torch.full((1, 3), -2.0, dtype=torch.float32),
            "quats": torch.tensor([[1.0, 0.0, 0.0, 0.0]], dtype=torch.float32),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fidelity.ply"
            servo_train.export_world(
                parameters,
                path,
                rasterization_mode="antialiased",
                eps2d=0.3,
            )
            result = servo_worker.parse_ply_header(path)
            self.assertIn(
                f"ServoRepresentation {servo_train.REPRESENTATION_TYPE}",
                result["comments"],
            )
            self.assertIn("ServoRasterizationMode antialiased", result["comments"])
            self.assertIn("ServoEps2d 0.3", result["comments"])

    def test_coarse_training_sample_scales_intrinsics_exactly(self) -> None:
        import torch

        pixels = torch.zeros((1, 101, 203, 3), dtype=torch.float32)
        calibration = torch.tensor(
            [[[200.0, 0.0, 101.0], [0.0, 180.0, 50.0], [0.0, 0.0, 1.0]]],
            dtype=torch.float32,
        )
        resized, scaled = servo_train.downscale_training_sample(
            pixels,
            calibration,
            2,
        )
        self.assertEqual(tuple(resized.shape), (1, 50, 102, 3))
        self.assertAlmostEqual(float(scaled[0, 0, 0]), 200.0 * 102.0 / 203.0, places=5)
        self.assertAlmostEqual(float(scaled[0, 1, 1]), 180.0 * 50.0 / 101.0, places=5)
        self.assertAlmostEqual(float(scaled[0, 0, 2]), 101.0 * 102.0 / 203.0, places=5)
        self.assertAlmostEqual(float(scaled[0, 1, 2]), 50.0 * 50.0 / 101.0, places=5)

    def test_sparse_depth_and_layer_variance_losses_are_geometric(self) -> None:
        import numpy as np
        import torch

        pixels = np.asarray(
            [[0, 0], [1, 0], [2, 0], [3, 0], [0, 3], [1, 3], [2, 3], [3, 3]],
            dtype=np.float32,
        )
        record = servo_train.ImageRecord(
            name="frame.png",
            path=Path("frame.png"),
            camera_id=1,
            camera_model="PINHOLE",
            camera_to_world=np.eye(4, dtype=np.float32),
            calibration=np.eye(3, dtype=np.float32),
            width=4,
            height=4,
            sparse_pixels=pixels,
            sparse_depths=np.ones(8, dtype=np.float32),
        )
        expected = torch.full((1, 4, 4, 1), 2.0, requires_grad=True)
        alpha = torch.ones((1, 4, 4, 1))
        sparse_loss, count = servo_train.sparse_depth_consistency_loss(
            expected, alpha, record, 1
        )
        self.assertEqual(count, 8)
        self.assertGreater(float(sparse_loss.item()), 0.0)
        sparse_loss.backward()
        self.assertIsNotNone(expected.grad)
        self.assertTrue(torch.isfinite(expected.grad).all())

        zero_variance = servo_train.depth_layer_variance_loss(
            expected.detach(), torch.full_like(expected, 4.0), alpha
        )
        mixed_variance = servo_train.depth_layer_variance_loss(
            expected.detach(), torch.full_like(expected, 8.0), alpha
        )
        self.assertAlmostEqual(float(zero_variance.item()), 0.0, places=6)
        self.assertGreater(float(mixed_variance.item()), 0.5)

    def test_static_pair_confidence_tracks_epipolar_motion(self) -> None:
        import cv2
        import numpy as np

        generator = np.random.default_rng(17)
        first = generator.integers(0, 256, (128, 160), dtype=np.uint8)
        first = cv2.GaussianBlur(first, (3, 3), 0.6)
        second = cv2.warpAffine(
            first,
            np.asarray([[1.0, 0.0, 2.0], [0.0, 1.0, 0.0]], dtype=np.float32),
            (first.shape[1], first.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
        # Rectified horizontal camera translation: corresponding points retain
        # their image row even though their x coordinate changes.
        fundamental = np.asarray(
            [[0.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
            dtype=np.float64,
        )
        first_confidence, second_confidence = servo_worker.static_pair_confidence(
            first, second, fundamental
        )
        self.assertEqual(first_confidence.shape, first.shape)
        self.assertEqual(second_confidence.shape, second.shape)
        self.assertTrue(
            set(np.unique(first_confidence).tolist()).issubset({0, 96, 255})
        )
        self.assertGreater(float(np.mean(first_confidence > 0)), 0.70)
        self.assertGreater(float(np.mean(second_confidence > 0)), 0.70)

    def test_static_confidence_builds_for_registered_still_image(self) -> None:
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            training_root = Path(directory)
            sparse_root = training_root / "sparse"
            sparse_root.mkdir(parents=True)
            (sparse_root / "cameras.bin").touch()
            (training_root / "images").mkdir()

            reconstruction = SimpleNamespace(
                images={
                    1: SimpleNamespace(
                        name="frame.png",
                        has_pose=True,
                        camera_id=1,
                    )
                },
                cameras={},
            )
            context = SimpleNamespace(
                check_cancel=mock.Mock(),
                events=SimpleNamespace(emit=mock.Mock()),
            )
            gray = np.full((12, 16), 127, dtype=np.uint8)
            fake_pycolmap = SimpleNamespace(
                Reconstruction=mock.Mock(return_value=reconstruction)
            )
            with (
                mock.patch.dict(sys.modules, {"pycolmap": fake_pycolmap}),
                mock.patch("cv2.imread", return_value=gray),
                mock.patch.object(servo_worker, "write_selected_frame") as write_mask,
            ):
                metrics = servo_worker.build_static_confidence_masks(
                    context,
                    training_root,
                    {},
                )

            self.assertEqual(metrics["registeredImages"], 1)
            self.assertEqual(metrics["videoImages"], 0)
            self.assertEqual(metrics["meanCoverage"], 1.0)
            write_mask.assert_called_once()

    def test_weighted_ssim_ignores_zero_confidence_region(self) -> None:
        import torch

        target = torch.zeros((1, 3, 32, 32), dtype=torch.float32)
        prediction = target.clone()
        prediction[:, :, :16, :] = 1.0
        weight = torch.zeros((1, 1, 32, 32), dtype=torch.float32)
        # Leave more than the 11x11 SSIM window radius between the corrupted
        # half and the trusted pixels.
        weight[:, :, 24:, :] = 1.0
        unweighted = servo_train.ssim(prediction, target)
        weighted = servo_train.ssim(prediction, target, weight)
        self.assertGreater(float(weighted), float(unweighted))
        self.assertGreater(float(weighted), 0.90)

    def test_appearance_state_is_bounded_and_checkpointed(self) -> None:
        import torch

        with tempfile.TemporaryDirectory() as directory:
            appearance = servo_train.create_appearance_parameters(2, "cpu")
            with torch.no_grad():
                appearance["logGains"][0].fill_(10.0)
                appearance["biases"][0].fill_(-10.0)
            servo_train.clamp_appearance(appearance)
            self.assertLessEqual(
                float(appearance["logGains"].detach().abs().max()),
                math.log(2.0) + 1e-6,
            )
            self.assertLessEqual(
                float(appearance["biases"].detach().abs().max()),
                0.25,
            )

            parameter = torch.nn.Parameter(torch.zeros((1, 3)))
            optimizer = torch.optim.Adam([parameter], lr=1e-3)
            scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.99)
            appearance_optimizer = servo_train.create_appearance_optimizer(
                appearance,
                1e-3,
            )
            appearance_scheduler = torch.optim.lr_scheduler.ExponentialLR(
                appearance_optimizer,
                gamma=0.99,
            )
            config = {
                "configurationHash": "appearance-test",
                "trainingInputHash": "sha256:" + "3" * 64,
                "pipelineRevision": "test-pipeline",
                "appearanceCompensation": True,
            }
            checkpoint_dir = Path(directory) / "checkpoints"
            servo_train.save_checkpoint(
                checkpoint_dir,
                3,
                {"means": parameter},
                {"means": optimizer},
                scheduler,
                {},
                {"densificationLimited": False},
                config,
                SimpleNamespace(normalization={"scale": 1.0}),
                appearance,
                appearance_optimizer,
                appearance_scheduler,
            )
            checkpoint = servo_train.load_checkpoint(checkpoint_dir, config)
            self.assertIsNotNone(checkpoint)
            assert checkpoint is not None
            self.assertIn("appearance", checkpoint)
            self.assertIn("appearanceOptimizer", checkpoint)
            self.assertEqual(
                tuple(checkpoint["appearance"]["logGains"].shape),
                (2, 3),
            )

    def test_pinned_gsplat_opacity_reset_schedule(self) -> None:
        self.assertFalse(servo_train.should_reset_opacity(0, 3_000, 15_000))
        self.assertFalse(servo_train.should_reset_opacity(2_999, 3_000, 15_000))
        self.assertTrue(servo_train.should_reset_opacity(3_000, 3_000, 15_000))
        self.assertTrue(servo_train.should_reset_opacity(12_000, 3_000, 15_000))
        self.assertFalse(servo_train.should_reset_opacity(15_000, 3_000, 15_000))
        self.assertFalse(servo_train.should_reset_opacity(18_000, 3_000, 15_000))

    def test_adaptive_gaussian_budget_preflights_growth_without_count_ceiling(self) -> None:
        gib = 1024**3
        self.assertFalse(
            servo_train.adaptive_growth_would_exceed_vram(
                gaussian_count=1_500_000,
                allocated_bytes=int(2.7 * gib),
                reserved_bytes=int(4.6 * gib),
                maximum_bytes=11 * gib,
            )
        )
        self.assertTrue(
            servo_train.adaptive_growth_would_exceed_vram(
                gaussian_count=3_000_000,
                allocated_bytes=int(4.5 * gib),
                reserved_bytes=int(6.0 * gib),
                maximum_bytes=11 * gib,
            )
        )

    def test_overlap_matcher_accepts_one_neighbor_results(self) -> None:
        import numpy as np

        descriptors = np.zeros((1, 32), dtype=np.uint8)
        movement, overlap, matches = servo_worker.overlap_motion(
            [], descriptors, [], descriptors, 100.0
        )
        self.assertEqual((movement, overlap, matches), (0.0, 0.0, 0))

    def test_video_extraction_decodes_encoded_media_and_keeps_source_identity(self) -> None:
        import cv2
        import numpy as np

        environment = servo_worker.compiler_environment()
        if (
            shutil.which("ffmpeg", path=environment.get("PATH")) is None
            or shutil.which("ffprobe", path=environment.get("PATH")) is None
        ):
            self.skipTest("FFmpeg and ffprobe are required")

        class Events:
            def __init__(self) -> None:
                self.records: list[tuple[str, dict[str, object]]] = []

            def emit(self, event: str, **payload: object) -> None:
                self.records.append((event, payload))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "moving-texture.avi"
            images = root / "frames"
            images.mkdir()

            width, height = 640, 360
            writer = cv2.VideoWriter(
                str(video),
                cv2.VideoWriter_fourcc(*"MJPG"),
                30.0,
                (width, height),
            )
            self.assertTrue(writer.isOpened(), "OpenCV must provide an encoded-video writer")
            rng = np.random.default_rng(17)
            base = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            for row in range(30, height, 45):
                cv2.line(base, (0, row), (width - 1, row), (255, 255, 255), 2)
            for column in range(30, width, 55):
                cv2.line(base, (column, 0), (column, height - 1), (0, 0, 0), 2)
            cv2.putText(
                base,
                "SERVO VIDEO RECONSTRUCTION",
                (40, 190),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 255),
                3,
                cv2.LINE_AA,
            )
            try:
                for frame_index in range(90):
                    transform = np.float32([[1.0, 0.0, frame_index * 2.0], [0.0, 1.0, 0.0]])
                    frame = cv2.warpAffine(
                        base,
                        transform,
                        (width, height),
                        flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REFLECT,
                    )
                    writer.write(frame)
            finally:
                writer.release()
            self.assertGreater(video.stat().st_size, 0)

            events = Events()
            context = SimpleNamespace(
                root=root,
                profile=SimpleNamespace(
                    sample_hz=10.0,
                    max_dimension=640,
                    min_interval_seconds=0.05,
                    max_interval_seconds=0.5,
                    motion_threshold=0.002,
                ),
                events=events,
                check_cancel=lambda: None,
            )
            selected, rejected, decode = servo_worker.extract_video(
                context,
                {"path": str(video), "kind": "video"},
                7,
                "video-007",
                images,
                4,
            )

            self.assertGreaterEqual(len(selected), 20)
            self.assertGreaterEqual(rejected, 0)
            self.assertEqual(decode["decodedFrames"], 90)
            self.assertEqual(decode["losslessFrameFormat"], "png")
            self.assertTrue(events.records)
            self.assertEqual({frame["sourceId"] for frame in selected}, {"s007"})
            self.assertEqual(selected[0]["image"], "video-007/00000004.png")
            timestamps = [float(frame["timestampSeconds"]) for frame in selected]
            self.assertEqual(timestamps, sorted(timestamps))
            self.assertEqual(len(timestamps), len(set(timestamps)))
            for frame in selected:
                self.assertTrue((images / str(frame["image"])).is_file())

    def test_hlg_probe_requires_explicit_bt2020_to_srgb_transform(self) -> None:
        environment = servo_worker.compiler_environment()
        ffmpeg = shutil.which("ffmpeg", path=environment.get("PATH"))
        ffprobe = shutil.which("ffprobe", path=environment.get("PATH"))
        if ffmpeg is None or ffprobe is None:
            self.skipTest("FFmpeg and ffprobe are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "synthetic-hlg.mp4"
            result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x180:rate=5:duration=0.6",
                    "-c:v",
                    "libx265",
                    "-preset",
                    "ultrafast",
                    "-x265-params",
                    (
                        "log-level=error:colorprim=bt2020:transfer=arib-std-b67:"
                        "colormatrix=bt2020nc:range=limited"
                    ),
                    "-tag:v",
                    "hvc1",
                    "-pix_fmt",
                    "yuv420p10le",
                    "-color_primaries",
                    "bt2020",
                    "-color_trc",
                    "arib-std-b67",
                    "-colorspace",
                    "bt2020nc",
                    "-color_range",
                    "tv",
                    str(video),
                ],
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            probe = servo_worker.probe_video_decode(video, 320)
            self.assertEqual(probe["colorTransfer"], "arib-std-b67")
            self.assertEqual(
                probe["displayTransform"],
                "bt2020-hlg-limited-to-bt709-srgb-mobius-v1",
            )
            self.assertIn("tonemap=mobius", probe["filter"])
            self.assertEqual(len(probe["timestamps"]), 3)

    def test_exact_ply_reference_loader_resizes_and_blocks_escape(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "references"
            nested = root / "video-000"
            nested.mkdir(parents=True)
            Image.new("RGB", (20, 10), "red").save(nested / "frame.png")
            pixels = servo_audit_world.load_reference_image(
                root, "video-000/frame.png", 10, 6
            )
            self.assertEqual(pixels.shape, (6, 10, 3))
            self.assertTrue((pixels[..., 0] > 0.99).all())
            outside = Path(directory) / "outside.png"
            Image.new("RGB", (4, 4), "blue").save(outside)
            with self.assertRaises(servo_audit_world.AuditError):
                servo_audit_world.load_reference_image(root, "../outside.png", 4, 4)

    def test_sky_leakage_diagnostic_uses_only_safe_observed_labels(self) -> None:
        import numpy as np
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            geometry = Path(directory) / "geometry"
            semantic = geometry / "semantics" / "video-000"
            semantic.mkdir(parents=True)
            labels = np.zeros((4, 6), dtype=np.uint8)
            labels[:2, 2:5] = servo_audit_world.SEMANTIC_SKY_LABEL
            Image.fromarray(labels, mode="L").save(semantic / "frame.png")

            sky = servo_audit_world.load_semantic_sky_mask(
                geometry,
                "video-000/frame.png",
                12,
                8,
            )
            self.assertIsNotNone(sky)
            assert sky is not None
            self.assertEqual(sky.shape, (8, 12))
            self.assertTrue(sky[:4, 4:10].all())
            self.assertFalse(sky[4:, :].any())
            self.assertIsNone(
                servo_audit_world.load_semantic_sky_mask(
                    geometry,
                    "video-000/missing.png",
                    12,
                    8,
                )
            )
            with self.assertRaises(servo_audit_world.AuditError):
                servo_audit_world.load_semantic_sky_mask(
                    geometry,
                    "../outside.png",
                    12,
                    8,
                )

            alpha = np.zeros((8, 12), dtype=np.float32)
            alpha[sky] = 0.8
            artifact = servo_audit_world.write_sky_leakage_diagnostic(
                Path(directory) / "out",
                ordinal=0,
                image_name="video-000/frame.png",
                rendered_rgb=np.zeros((8, 12, 3), dtype=np.float32),
                reference_rgb=np.ones((8, 12, 3), dtype=np.float32),
                sky_mask=sky,
                alpha=alpha,
                p95=0.8,
                threshold=0.25,
            )
            output = Path(directory) / "out" / artifact
            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual(image.size, (24, 24))

    def test_nonpublishable_diagnostic_audit_source_is_explicit_and_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "diagnostic"
            geometry = Path(directory) / "geometry"
            root.mkdir()
            geometry.mkdir()
            world = root / "world.ply"
            world.write_bytes(b"diagnostic-ply")
            cameras = root / "cameras.json"
            cameras.write_text("{}\n", encoding="utf-8")
            configuration_hash = "sha256:" + "a" * 64
            config = {
                "output": str(root),
                "configurationHash": configuration_hash,
                "geometryRoot": str(geometry),
                "diagnosticProvenance": {
                    "schema": "servo.diagnostic-training-provenance/v1",
                    "nonPublishable": True,
                },
                "jobId": "quality-probe",
            }
            (root / "training-config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
            (root / "train-metrics.json").write_text(
                json.dumps(
                    {
                        "configurationHash": configuration_hash,
                        "worldSha256": servo_audit_world.sha256_file(world),
                        "representationType": "servo-fidelity-3dgs-v1",
                        "environment": {
                            "backgroundColorSrgb": [0.0, 0.0, 0.0],
                            "backgroundSource": "diagnostic-test",
                        },
                    }
                ),
                encoding="utf-8",
            )

            source = servo_audit_world.resolve_audit_source(None, root)

            self.assertTrue(source.non_publishable)
            self.assertEqual(source.manifest["artifactKind"], "non-publishable-diagnostic-training-output")
            self.assertEqual(source.environment_root, geometry.resolve())
            self.assertFalse((root / "world.json").exists())

            config["diagnosticProvenance"]["nonPublishable"] = False
            (root / "training-config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
            with self.assertRaises(servo_audit_world.AuditError):
                servo_audit_world.resolve_audit_source(None, root)

    def test_camera_groups_share_verified_photo_signatures(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jpg"
            second = root / "second.jpg"
            different = root / "different.jpg"
            Image.new("RGB", (320, 240), "red").save(first)
            Image.new("RGB", (320, 240), "blue").save(second)
            Image.new("RGB", (640, 480), "green").save(different)
            group = servo_worker.camera_group_for_source(
                {"path": str(first), "kind": "image"}, 0
            )
            self.assertEqual(
                group,
                servo_worker.camera_group_for_source(
                    {"path": str(second), "kind": "image"}, 1
                ),
            )
            self.assertNotEqual(
                group,
                servo_worker.camera_group_for_source(
                    {"path": str(different), "kind": "image"}, 2
                ),
            )
            self.assertEqual(
                servo_worker.camera_group_for_source(
                    {
                        "path": str(first),
                        "kind": "image",
                        "cameraGroup": "Camera A",
                    },
                    3,
                ),
                "image-manual-Camera-A",
            )

    def test_camera_group_uses_exif_oriented_dimensions(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oriented = root / "sensor-landscape-exif-portrait.jpg"
            portrait = root / "portrait.jpg"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (320, 240), "red").save(oriented, exif=exif)
            Image.new("RGB", (240, 320), "blue").save(portrait)
            self.assertEqual(
                servo_worker.camera_group_for_source(
                    {"path": str(oriented), "kind": "image"}, 0
                ),
                servo_worker.camera_group_for_source(
                    {"path": str(portrait), "kind": "image"}, 1
                ),
            )

    def test_cleanup_scales_scene_limits_for_short_baselines(self) -> None:
        import torch

        count = 101
        means = torch.zeros((count, 3), dtype=torch.float32)
        means[:100, 0] = 30.0
        means[100, 0] = 100.0
        scale_logs = torch.full((count, 3), math.log(3.0), dtype=torch.float32)
        parameters = {
            "means": torch.nn.Parameter(means),
            "sh0": torch.nn.Parameter(torch.zeros((count, 1, 3))),
            "shN": torch.nn.Parameter(torch.zeros((count, 15, 3))),
            "opacities": torch.nn.Parameter(torch.ones((count,))),
            "scales": torch.nn.Parameter(scale_logs),
            "quats": torch.nn.Parameter(
                torch.tensor([[1.0, 0.0, 0.0, 0.0]]).repeat(count, 1)
            ),
        }
        cleaned, metrics = servo_train.cleanup_parameters(
            parameters,
            {
                "cleanupRadiusLimitNormalized": 60.0,
                "cleanupScaleLimitNormalized": 4.0,
            },
        )
        self.assertEqual(len(cleaned["means"]), 100)
        self.assertEqual(metrics["spatialOutlierCandidates"], 1)
        self.assertEqual(metrics["oversizedCandidates"], 0)

    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are Windows-only")
    def test_windows_job_object_terminates_nested_child(self) -> None:
        parent_code = (
            "import subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "print(child.pid,flush=True); time.sleep(60)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", parent_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                | servo_worker.WINDOWS_CREATE_SUSPENDED
            ),
        )
        job = None
        child_pid = None
        try:
            job = servo_worker.create_windows_kill_job(
                int(getattr(process, "_handle", 0))
            )
            self.assertIsNotNone(job)
            self.assertTrue(
                servo_worker.resume_windows_process_threads(process.pid)
            )
            assert process.stdout is not None
            child_line = process.stdout.readline().strip()
            self.assertTrue(child_line.isdigit())
            child_pid = int(child_line)
            self.assertTrue(servo_worker.process_is_alive(child_pid))
            self.assertTrue(servo_worker.terminate_windows_job(job))
            process.wait(timeout=10)
            for _ in range(50):
                if not servo_worker.process_is_alive(child_pid):
                    break
                __import__("time").sleep(0.02)
            self.assertFalse(servo_worker.process_is_alive(child_pid))
        finally:
            servo_worker.terminate_windows_job(job)
            servo_worker.close_windows_handle(job)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def test_process_probe_is_non_destructive_and_lock_rejects_live_owner(self) -> None:
        self.assertTrue(servo_worker.process_is_alive(os.getpid()))
        identity = servo_worker.process_identity(os.getpid())
        self.assertIsNotNone(identity)
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "live.lock"
            lock.write_text(
                json.dumps({"pid": os.getpid(), "processIdentity": identity}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(servo_worker.WorkerError, "already active"):
                with servo_worker.exclusive_process_lock(
                    lock,
                    "busy",
                    "The owner is already active.",
                ):
                    self.fail("A live lock must not be acquired.")
            self.assertTrue(servo_worker.process_is_alive(os.getpid(), identity))


if __name__ == "__main__":
    unittest.main()
