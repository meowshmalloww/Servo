#!/usr/bin/env python3
"""Publish a completed WildGS-SLAM reconstruction into Servo's world library.

The importer is intentionally fail-closed: it accepts only a real, non-empty
``final_gs.ply`` plus WildGS's saved camera trajectory. It does not manufacture
quality metrics or substitute recorded RGB frames for the Gaussian artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import numpy as np
import yaml


WORLD_SCHEMA = "servo.gaussian-world/v1"
CAMERA_SCHEMA = "servo.gaussian-cameras/v1"
DEFAULT_PROFILE = "wildgs-slam-da3-no-colmap-t2"
DEFAULT_PIPELINE_REVISION = "wildgs-slam-apache-droid-da3-depth-t2-v1"
DEFAULT_REPRESENTATION = "WildGS-SLAM optimized 3D Gaussians (SH3)"


class ImportFailure(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _ply_vertex_count(path: Path) -> int:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ImportFailure(f"Missing or empty WildGS PLY: {path}")
    with path.open("rb") as stream:
        header = stream.read(1024 * 1024)
    marker = b"end_header\n"
    end = header.find(marker)
    if end < 0:
        marker = b"end_header\r\n"
        end = header.find(marker)
    if end < 0:
        raise ImportFailure("WildGS PLY has no bounded end_header marker.")
    text = header[: end + len(marker)].decode("ascii", errors="strict")
    if not text.startswith("ply\n") and not text.startswith("ply\r\n"):
        raise ImportFailure("WildGS artifact is not a PLY file.")
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[:2] == ["element", "vertex"]:
            count = int(fields[2])
            if count <= 0:
                raise ImportFailure("WildGS PLY contains no Gaussian vertices.")
            return count
    raise ImportFailure("WildGS PLY does not declare a vertex element.")


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _finite_matrix(value: np.ndarray, name: str) -> list[list[float]]:
    if value.shape != (4, 4) or not np.isfinite(value).all():
        raise ImportFailure(f"{name} is not a finite 4x4 camera matrix.")
    rotation = value[:3, :3]
    if abs(float(np.linalg.det(rotation))) < 1e-5:
        raise ImportFailure(f"{name} contains a singular rotation.")
    return [[float(component) for component in row] for row in value]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _find_preview(output: Path) -> Path | None:
    candidates: list[Path] = []
    for directory_name in ("plots_after_refine", "plots_before_refine"):
        directory = output / directory_name
        if directory.is_dir():
            candidates.extend(sorted(directory.glob("*.png")))
            candidates.extend(sorted(directory.glob("*.jpg")))
    return candidates[len(candidates) // 2] if candidates else None


def publish(args: argparse.Namespace) -> Path:
    output = args.wildgs_output.resolve()
    ply_source = output / "final_gs.ply"
    video_source = output / "video.npz"
    config_source = output / "cfg.yaml"
    gaussian_count = _ply_vertex_count(ply_source)
    if not video_source.is_file() or not config_source.is_file():
        raise ImportFailure("WildGS output must contain video.npz and cfg.yaml.")

    with config_source.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ImportFailure("WildGS cfg.yaml is malformed.")
    camera_config = config.get("cam")
    if not isinstance(camera_config, dict):
        raise ImportFailure("WildGS cfg.yaml has no camera block.")

    archive = np.load(video_source)
    required = {"poses", "timestamps"}
    if not required.issubset(archive.files):
        raise ImportFailure("WildGS video.npz has no saved poses/timestamps.")
    poses = np.asarray(archive["poses"], dtype=np.float64)
    timestamps = np.asarray(archive["timestamps"]).reshape(-1)
    if poses.ndim != 3 or poses.shape[1:] != (4, 4) or len(poses) != len(timestamps):
        raise ImportFailure("WildGS saved trajectory shapes are inconsistent.")
    if len(poses) < 2:
        raise ImportFailure("WildGS trajectory has fewer than two cameras.")

    width = int(camera_config.get("W", 0))
    height = int(camera_config.get("H", 0))
    fx = float(camera_config.get("fx", 0.0))
    fy = float(camera_config.get("fy", 0.0))
    cx = float(camera_config.get("cx", 0.0))
    cy = float(camera_config.get("cy", 0.0))
    if width <= 0 or height <= 0 or not all(
        math.isfinite(value) and value > 0.0 for value in (fx, fy)
    ):
        raise ImportFailure("WildGS camera intrinsics are invalid.")

    jobs_root = args.jobs_root.resolve()
    job_root = jobs_root / args.world_id
    if job_root.exists():
        raise ImportFailure(f"Refusing to overwrite existing Servo job: {job_root}")
    staging = jobs_root / f".{args.world_id}.publishing"
    if staging.exists():
        raise ImportFailure(f"Stale publishing directory exists: {staging}")
    world_root = staging / "stages" / "publish" / "world"
    image_root = staging / "stages" / "pose" / "training" / "images" / "video-000"
    world_root.mkdir(parents=True, exist_ok=False)
    image_root.mkdir(parents=True, exist_ok=False)

    try:
        _link_or_copy(ply_source, world_root / "world.ply")
        _link_or_copy(video_source, world_root / "wildgs-video.npz")
        _link_or_copy(config_source, world_root / "wildgs-config.yaml")

        input_folder = Path(str(config.get("data", {}).get("input_folder", "")))
        rgb_root = input_folder / "rgb"
        cameras: list[dict[str, Any]] = []
        for ordinal, (pose, timestamp) in enumerate(zip(poses, timestamps, strict=True)):
            source_index = int(round(float(timestamp)))
            source_name = f"frame_{source_index:05d}.png"
            source_image = rgb_root / source_name
            relative_image = f"video-000/{source_name}"
            if source_image.is_file():
                _link_or_copy(source_image, image_root / source_name)
            cameras.append(
                {
                    "cameraId": 1,
                    "cameraModel": "PINHOLE",
                    "width": width,
                    "height": height,
                    "image": relative_image,
                    "sourceFrameIndex": source_index,
                    "cameraToWorldNormalized": _finite_matrix(
                        pose, f"WildGS pose {ordinal}"
                    ),
                    "calibration": [
                        [fx, 0.0, cx],
                        [0.0, fy, cy],
                        [0.0, 0.0, 1.0],
                    ],
                }
            )

        cameras_path = world_root / "cameras.json"
        _write_json(
            cameras_path,
            {
                "schema": CAMERA_SCHEMA,
                "poseSource": "WildGS-SLAM/DROID-SLAM-no-COLMAP",
                "scale": "unknown-monocular",
                # WildGS optimized every retained keyframe.  Keep this empty
                # instead of falsely presenting training cameras as held-out.
                "validationImages": [],
                "validationSemantics": "none-all-retained-keyframes-were-optimized",
                "cameras": cameras,
            },
        )

        artifacts: dict[str, str] = {
            "ply": "world.ply",
            "cameras": "cameras.json",
            "wildgsTrajectory": "wildgs-video.npz",
            "wildgsConfig": "wildgs-config.yaml",
        }
        preview = _find_preview(output)
        if preview is not None:
            suffix = preview.suffix.lower() if preview.suffix else ".png"
            preview_name = "validation-preview" + suffix
            _link_or_copy(preview, world_root / preview_name)
            artifacts["preview"] = preview_name

        hashes = {
            relative: _sha256(world_root / relative)
            for relative in artifacts.values()
        }
        manifest = {
            "schema": WORLD_SCHEMA,
            "worldId": args.world_id,
            "createdAt": args.created_at,
            "profile": args.profile,
            "pipelineRevision": args.pipeline_revision,
            "representationType": args.representation_type,
            "artifacts": artifacts,
            "coordinateSystem": {"scale": "unknown-monocular"},
            "environment": {
                "backgroundColorSrgb": [0.0, 0.0, 0.0],
                "backgroundSource": "wildgs-training-background-black",
                "finiteGeometry": False,
            },
            "quality": {
                "tier": "experimental",
                "cleanup": {"retainedGaussians": gaussian_count},
                "metricsState": "not-yet-audited",
            },
            "usage": {
                "visualDriveableDemo": False,
                "collisionValidated": False,
                "metricScale": False,
                "sideRearMeasured": False,
            },
            "evidence": {
                "sourceFrameCount": int(len(poses)),
                "posePipeline": "WildGS-SLAM/DROID-SLAM",
                "depthPrior": "Depth Anything 3 precomputed relative depth",
                "usesColmap": False,
                "recordedFramesOnly": True,
            },
            "limitations": [
                f"Experimental {args.experiment_label} artifact; quality must be judged by rendered audits.",
                "Forward monocular capture does not measure side or rear regions.",
                "DA3 depth is relative and nonmetric.",
                "Not collision validated.",
            ],
            "hashes": hashes,
        }
        _write_json(world_root / "world.json", manifest)
        _write_json(
            staging / "job.json",
            {
                "schema": "servo.reconstruction-job/v1",
                "jobId": args.world_id,
                "worldName": args.world_name,
                "createdAt": args.created_at,
                "profile": args.profile,
                "sources": [
                    {
                        "kind": "video",
                        "name": args.source_media.name,
                        "path": str(args.source_media.resolve()),
                        "sizeBytes": args.source_media.stat().st_size,
                    }
                ],
            },
        )
        jobs_root.mkdir(parents=True, exist_ok=True)
        staging.replace(job_root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return job_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wildgs-output", type=Path, required=True)
    parser.add_argument("--source-media", type=Path, required=True)
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--world-name", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--jobs-root", type=Path, required=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--pipeline-revision", default=DEFAULT_PIPELINE_REVISION)
    parser.add_argument("--representation-type", default=DEFAULT_REPRESENTATION)
    parser.add_argument("--experiment-label", default="T2")
    return parser


def main() -> int:
    try:
        result = publish(_parser().parse_args())
    except (ImportFailure, OSError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
