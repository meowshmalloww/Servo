from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


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
                profile=SimpleNamespace(
                    sample_hz=10.0,
                    max_dimension=640,
                    min_interval_seconds=0.05,
                    max_interval_seconds=0.5,
                    jpeg_quality=92,
                ),
                events=events,
                check_cancel=lambda: None,
            )
            selected, rejected = servo_worker.extract_video(
                context,
                {"path": str(video), "kind": "video"},
                7,
                "video-007",
                images,
                4,
            )

            self.assertGreaterEqual(len(selected), 20)
            self.assertGreaterEqual(rejected, 0)
            self.assertTrue(events.records)
            self.assertEqual({frame["sourceId"] for frame in selected}, {"s007"})
            self.assertEqual(selected[0]["image"], "video-007/00000004.jpg")
            timestamps = [float(frame["timestampSeconds"]) for frame in selected]
            self.assertEqual(timestamps, sorted(timestamps))
            self.assertEqual(len(timestamps), len(set(timestamps)))
            for frame in selected:
                self.assertTrue((images / str(frame["image"])).is_file())

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
