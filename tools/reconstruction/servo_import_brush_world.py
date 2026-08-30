#!/usr/bin/env python3
"""Import a completed Brush PLY into Servo as an unaccepted review world."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _vertex_count(path: Path) -> int:
    with path.open("rb") as stream:
        for raw in stream:
            line = raw.decode("ascii", errors="strict").strip()
            if line.startswith("element vertex "):
                return int(line.rsplit(" ", 1)[1])
            if line == "end_header":
                break
    raise ValueError("PLY does not declare a vertex count")


def import_world(
    ply: Path,
    cameras: Path,
    dataset_receipt: Path,
    jobs_root: Path,
    world_id: str,
    world_name: str,
    source_media: Path,
    *,
    pose_pipeline: str = "WildGS-SLAM/DROID-SLAM; no COLMAP pose estimation",
    profile: str = "brush-wildgs-camera-calibration",
) -> Path:
    job_root = jobs_root / world_id
    world = job_root / "stages" / "publish" / "world"
    if world.exists():
        raise FileExistsError(f"refusing to overwrite world: {world}")
    world.mkdir(parents=True)
    source_size = source_media.stat().st_size if source_media.is_file() else 0
    (job_root / "job.json").write_text(
        json.dumps({
            "schema": "servo.reconstruction-job/v1",
            "jobId": world_id,
            "worldName": world_name,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "profile": profile,
            "sources": [{
                "kind": "video",
                "name": source_media.name,
                "path": str(source_media),
                "sizeBytes": source_size,
            }],
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _link_or_copy(ply, world / "world.ply")
    shutil.copy2(cameras, world / "cameras.json")
    shutil.copy2(dataset_receipt, world / "brush-dataset-receipt.json")
    gaussian_count = _vertex_count(ply)
    manifest = {
        "schema": "servo.gaussian-world/v1",
        "worldId": world_id,
        "name": world_name,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "profile": profile,
        "pipelineRevision": f"brush-v0.3.0-{profile}-v1",
        "representationType": "Brush optimized 3D Gaussians (SH3)",
        "coordinateSystem": {"scale": "unknown-monocular"},
        "environment": {
            "backgroundColorSrgb": [0.0, 0.0, 0.0],
            "backgroundSource": "brush-training-background-black",
            "finiteGeometry": False,
        },
        "artifacts": {
            "ply": "world.ply",
            "cameras": "cameras.json",
            "brushDatasetReceipt": "brush-dataset-receipt.json",
        },
        "hashes": {
            "world.ply": f"sha256:{_sha256(world / 'world.ply')}",
            "cameras.json": f"sha256:{_sha256(world / 'cameras.json')}",
            "brush-dataset-receipt.json": f"sha256:{_sha256(world / 'brush-dataset-receipt.json')}",
        },
        "evidence": {
            "posePipeline": pose_pipeline,
            "trainer": "Brush v0.3.0",
            "recordedFramesOnly": True,
            "sourceFrameCount": len(json.loads(cameras.read_text(encoding="utf-8"))["cameras"]),
        },
        "quality": {
            "cleanup": {"retainedGaussians": gaussian_count},
            "decision": "pending-exact-ply-audit",
            "metricsState": "not-audited",
            "tier": "review-required",
        },
        "usage": {
            "visualDriveableDemo": False,
            "collisionValidated": False,
            "metricScale": False,
            "sideRearMeasured": False,
        },
        "limitations": [
            "Independent trainer calibration; not accepted until exact-Ply audit passes.",
            "Forward monocular capture does not measure side or rear regions.",
            "Sparse relative-depth samples initialize training but are not collision evidence.",
            "Not collision validated.",
        ],
    }
    (world / "world.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return world


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ply", required=True, type=Path)
    parser.add_argument("--cameras", required=True, type=Path)
    parser.add_argument("--dataset-receipt", required=True, type=Path)
    parser.add_argument("--jobs-root", required=True, type=Path)
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--world-name", required=True)
    parser.add_argument("--source-media", required=True, type=Path)
    parser.add_argument(
        "--pose-pipeline",
        default="WildGS-SLAM/DROID-SLAM; no COLMAP pose estimation",
    )
    parser.add_argument("--profile", default="brush-wildgs-camera-calibration")
    args = parser.parse_args()
    world = import_world(
        args.ply.resolve(), args.cameras.resolve(), args.dataset_receipt.resolve(),
        args.jobs_root.resolve(), args.world_id, args.world_name, args.source_media.resolve(),
        pose_pipeline=args.pose_pipeline,
        profile=args.profile,
    )
    print(world)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
