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


class ReconstructionWorkerTests(unittest.TestCase):
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
            self.assertGreaterEqual(profile.max_gaussians, 100_000)
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
                {"configurationHash": "checkpoint-test"},
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
        if ffmpeg is None:
            self.skipTest("FFmpeg is unavailable")
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
