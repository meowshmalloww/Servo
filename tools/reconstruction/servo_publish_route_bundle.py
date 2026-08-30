#!/usr/bin/env python3
"""Publish independently audited route tiles as one immutable Servo world.

The publisher never merges Gaussian parameters.  Each local field stays intact
and the native UI selects a tile explicitly, avoiding the severe quality loss
measured when unrelated local fields were destructively concatenated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any


ROUTE_SCHEMA = "servo.route-tile-datasets/v1"
VALIDATION_SCHEMA = "servo.route-bundle-validation/v1"
BUNDLE_SCHEMA = "servo.gaussian-route-bundle/v1"
WORLD_SCHEMA = "servo.gaussian-world/v1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_bindings(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        tile_id, separator, path_value = value.partition("=")
        if not separator or not tile_id or not path_value:
            raise ValueError("Tile bindings must be TILE_ID=PATH_TO_WORLD.")
        if tile_id in result:
            raise ValueError(f"Duplicate tile binding: {tile_id}")
        result[tile_id] = Path(path_value).resolve()
    return result


def link_or_copy(source: Path, target: Path) -> str:
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        shutil.copy2(source, target)
        return "copy"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--tile", action="append", required=True)
    parser.add_argument("--cameras", type=Path, required=True)
    parser.add_argument("--jobs-root", type=Path, required=True)
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--world-name", required=True)
    parser.add_argument("--source-media", type=Path, required=True)
    parser.add_argument(
        "--review-only",
        action="store_true",
        help=(
            "Publish a complete route that did not pass every visual gate as an "
            "explicitly review-required, non-collision world."
        ),
    )
    arguments = parser.parse_args()

    route = read_json(arguments.route.resolve())
    validation = read_json(arguments.validation.resolve())
    if route.get("schema") != ROUTE_SCHEMA or not route.get("fullRouteCovered"):
        raise ValueError("The route receipt is not a complete Servo route.")
    if validation.get("schema") != VALIDATION_SCHEMA:
        raise ValueError("The route validation receipt has an unsupported schema.")
    visual_route_passed = validation.get("visualRoutePassed") is True
    if not visual_route_passed and not arguments.review_only:
        raise ValueError(
            "The route did not pass every visual gate. Use --review-only to publish "
            "it without claiming acceptance."
        )

    bindings = parse_bindings(arguments.tile)
    route_tiles = route.get("tiles")
    if not isinstance(route_tiles, list) or not route_tiles:
        raise ValueError("The route has no tiles.")
    expected_ids = [str(tile.get("tileId", "")) for tile in route_tiles]
    if set(bindings) != set(expected_ids):
        raise ValueError("Tile bindings do not exactly match the route receipt.")

    job_root = (arguments.jobs_root.resolve() / arguments.world_id)
    if job_root.exists():
        raise FileExistsError(f"Refusing to overwrite {job_root}")
    world_root = job_root / "stages" / "publish" / "world"
    tile_root = world_root / "tiles"
    tile_root.mkdir(parents=True)

    cameras_document = read_json(arguments.cameras.resolve())
    source_cameras = cameras_document.get("cameras")
    if not isinstance(source_cameras, list) or len(source_cameras) < int(route["sourceCameraCount"]):
        raise ValueError("Camera manifest does not cover the complete route.")

    published_tiles: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    total_gaussians = 0
    for route_tile in route_tiles:
        tile_id = str(route_tile["tileId"])
        source_root = bindings[tile_id]
        source_manifest = read_json(source_root / "world.json")
        if source_manifest.get("schema") != WORLD_SCHEMA:
            raise ValueError(f"Invalid source world for {tile_id}")
        artifacts = source_manifest.get("artifacts", {})
        source_ply = (source_root / str(artifacts.get("ply", "world.ply"))).resolve()
        expected_hash = source_manifest.get("hashes", {}).get("world.ply")
        if not source_ply.is_file() or sha256(source_ply) != expected_hash:
            raise ValueError(f"Source PLY hash mismatch for {tile_id}")

        # GaussianSplatView discovers cameras.json beside the PLY. Keep every
        # independently fitted field in its own directory with the matching
        # camera slice; a shared global cameras.json makes a local field jump
        # to unsupported route poses and explode into screen-spanning splats.
        relative_ply = Path("tiles") / tile_id / "world.ply"
        target_ply = world_root / relative_ply
        target_ply.parent.mkdir(parents=True, exist_ok=True)
        storage_method = link_or_copy(source_ply, target_ply)
        target_hash = sha256(target_ply)
        hashes[relative_ply.as_posix()] = target_hash
        gaussian_count = int(
            source_manifest.get("quality", {})
            .get("cleanup", {})
            .get("retainedGaussians", 0)
        )
        total_gaussians += gaussian_count
        camera_start = int(route_tile["cameraStart"])
        camera_end = int(route_tile["cameraEndExclusive"])
        tile_cameras = dict(cameras_document)
        tile_cameras["cameras"] = source_cameras[camera_start:camera_end]
        tile_cameras_path = target_ply.parent / "cameras.json"
        atomic_json(tile_cameras_path, tile_cameras)
        tile_cameras_hash = sha256(tile_cameras_path)
        hashes[(relative_ply.parent / "cameras.json").as_posix()] = tile_cameras_hash
        published_tiles.append(
            {
                "tileId": tile_id,
                "cameraStart": camera_start,
                "cameraEndExclusive": camera_end,
                "cameraCount": int(route_tile["cameraCount"]),
                "ply": relative_ply.as_posix(),
                "plySha256": target_hash,
                "cameras": (relative_ply.parent / "cameras.json").as_posix(),
                "camerasSha256": tile_cameras_hash,
                "gaussianCount": gaussian_count,
                "sourceWorldId": source_manifest.get("worldId"),
                "sourceProfile": source_manifest.get("profile"),
                "storageMethod": storage_method,
            }
        )

    cameras_source = arguments.cameras.resolve()
    cameras_target = world_root / "cameras.json"
    shutil.copy2(cameras_source, cameras_target)
    hashes["cameras.json"] = sha256(cameras_target)

    bundle = {
        "schema": BUNDLE_SCHEMA,
        "selectionPolicy": "explicit-overlap-safe-local-field-v1",
        "fullRouteCovered": True,
        "sourceCameraCount": int(route["sourceCameraCount"]),
        "tileCount": len(published_tiles),
        "overlap": int(route["overlap"]),
        "routeReceiptSha256": sha256(arguments.route.resolve()),
        "validationSha256": sha256(arguments.validation.resolve()),
        "reviewRequired": not visual_route_passed,
        "tiles": published_tiles,
        "limitations": [
            "Tiles remain independent appearance fields and are not collision geometry.",
            "Tile switching preserves local fits; seamless dual-field cross-fading is not claimed.",
            "Side and rear regions outside the recorded corridor remain unknown.",
        ],
    }
    bundle_path = world_root / "route-bundle.json"
    atomic_json(bundle_path, bundle)
    hashes["route-bundle.json"] = sha256(bundle_path)

    values = validation.get("values", {})
    manifest = {
        "schema": WORLD_SCHEMA,
        "worldId": arguments.world_id,
        "name": arguments.world_name,
        "createdAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "profile": "t5-all-route-tiles-high-detail-v1",
        "pipelineRevision": "t5-independent-route-fields-no-destructive-merge-v1",
        "representationType": "Spatially tiled 3D Gaussian appearance fields (SH3)",
        "coordinateSystem": {"scale": "unknown-monocular"},
        "artifacts": {
            "ply": published_tiles[0]["ply"],
            "cameras": "cameras.json",
            "routeBundle": "route-bundle.json",
        },
        "hashes": {
            "world.ply": published_tiles[0]["plySha256"],
            "cameras.json": hashes["cameras.json"],
            "route-bundle.json": hashes["route-bundle.json"],
        },
        "routeTiles": published_tiles,
        "quality": {
            "tier": (
                "hackathon-visual-route"
                if visual_route_passed
                else "review-required"
            ),
            "decision": (
                "visual-route-pass"
                if visual_route_passed
                else "visual-route-review-required"
            ),
            "psnrMean": float(values.get("minimumRegisteredPsnrMean", -1.0)),
            "ssimMean": float(values.get("meanRegisteredSsim", -1.0)),
            "cleanup": {"retainedGaussians": total_gaussians},
            "validationPassFraction": float(validation.get("passFraction", 0.0)),
        },
        "environment": {
            "backgroundColorSrgb": [0.0, 0.0, 0.0],
            "backgroundSource": "tile-local-training-background",
            "finiteGeometry": False,
        },
        "usage": {
            "visualDriveableDemo": visual_route_passed,
            "collisionValidated": False,
            "metricScale": False,
            "sideRearMeasured": False,
        },
        "limitations": bundle["limitations"],
    }
    atomic_json(world_root / "world.json", manifest)

    source_hash = sha256(arguments.source_media.resolve())
    job = {
        "schema": "servo.reconstruction-job/v1",
        "jobId": arguments.world_id,
        "worldName": arguments.world_name,
        "profile": manifest["profile"],
        "createdAt": manifest["createdAt"],
        "state": "completed",
        "sources": [
            {
                "path": str(arguments.source_media.resolve()),
                "name": arguments.source_media.name,
                "sha256": source_hash,
            }
        ],
    }
    atomic_json(job_root / "job.json", job)
    print(world_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
