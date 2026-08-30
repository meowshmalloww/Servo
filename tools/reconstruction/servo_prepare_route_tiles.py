#!/usr/bin/env python3
"""Partition a long COLMAP road corridor into overlapping Brush-ready tiles.

The source poses and sparse points are preserved in their original coordinate
system.  No pose estimation, normalization, or generated geometry is applied.
Each tile is independently trainable and overlaps its neighbors so a runtime
can cross-fade between locally conditioned Gaussian worlds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reconstruction.servo_colmap import Reconstruction
from tools.reconstruction.servo_prepare_brush_from_wildgs import (
    _rotation_to_colmap_qvec,
)


SCHEMA = "servo.route-tile-datasets/v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tile_ranges(count: int, tile_size: int, overlap: int) -> list[tuple[int, int]]:
    if count < 1:
        raise ValueError("camera count must be positive")
    if tile_size < 2:
        raise ValueError("tile size must be at least two")
    if overlap < 1 or overlap >= tile_size:
        raise ValueError("overlap must be positive and smaller than tile size")
    if count <= tile_size:
        return [(0, count)]
    step = tile_size - overlap
    starts = list(range(0, count - tile_size + 1, step))
    final_start = count - tile_size
    if starts[-1] != final_start:
        starts.append(final_start)
    return [(start, min(count, start + tile_size)) for start in starts]


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _write_cameras(reconstruction: Reconstruction, target: Path) -> None:
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        for camera_id in sorted(reconstruction.cameras):
            camera = reconstruction.cameras[camera_id]
            params = " ".join(f"{value:.17g}" for value in camera.params)
            stream.write(
                f"{camera.camera_id} {camera.model_name} {camera.width} "
                f"{camera.height} {params}\n"
            )


def prepare(
    dataset_root: Path,
    output: Path,
    *,
    tile_size: int,
    overlap: int,
    servo_cameras: Path | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    sparse_parent = dataset_root / "sparse"
    sparse_source = sparse_parent / "0"
    if not sparse_source.is_dir():
        sparse_source = sparse_parent
    images_source = dataset_root / "images"
    reconstruction = Reconstruction(sparse_source)
    ordered_images = sorted(
        reconstruction.images.values(), key=lambda image: (image.name, image.image_id)
    )
    servo_camera_document = None
    if servo_cameras is not None:
        servo_camera_document = json.loads(servo_cameras.read_text(encoding="utf-8"))
        available_names = {
            str(camera["image"]) for camera in servo_camera_document.get("cameras", [])
        }
        missing_names = {image.name for image in ordered_images}.difference(available_names)
        if missing_names:
            raise ValueError(
                "Servo camera manifest does not cover the COLMAP route: "
                + ", ".join(sorted(missing_names)[:5])
            )
    ranges = tile_ranges(len(ordered_images), tile_size, overlap)
    output.mkdir(parents=True)
    tiles: list[dict[str, Any]] = []

    for ordinal, (start, end) in enumerate(ranges):
        tile_id = f"tile-{ordinal:02d}-{start:04d}-{end - 1:04d}"
        tile_root = output / tile_id
        sparse_root = tile_root / "sparse" / "0"
        sparse_root.mkdir(parents=True)
        selected_images = ordered_images[start:end]
        selected_image_ids = {image.image_id for image in selected_images}
        selected_point_ids = {
            point_id
            for point_id, point in reconstruction.points3D.items()
            if any(element.image_id in selected_image_ids for element in point.track.elements)
        }
        if not selected_point_ids:
            raise RuntimeError(f"{tile_id} has no sparse points observed by its cameras")

        _write_cameras(reconstruction, sparse_root / "cameras.txt")
        with (sparse_root / "images.txt").open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
            for image in selected_images:
                source = images_source / image.name
                if not source.is_file():
                    raise FileNotFoundError(f"source image is missing: {source}")
                _link_or_copy(source, tile_root / "images" / image.name)
                w2c = image.cam_from_world().value
                qvec = _rotation_to_colmap_qvec(w2c[:3, :3])
                values = " ".join(
                    f"{float(value):.17g}" for value in (*qvec, *w2c[:3, 3])
                )
                stream.write(
                    f"{image.image_id} {values} {image.camera_id} {image.name}\n\n"
                )

        with (sparse_root / "points3D.txt").open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write("# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
            for point_id in sorted(selected_point_ids):
                point = reconstruction.points3D[point_id]
                stream.write(
                    f"{point.point3D_id} {point.xyz[0]:.17g} {point.xyz[1]:.17g} "
                    f"{point.xyz[2]:.17g} {int(point.color[0])} {int(point.color[1])} "
                    f"{int(point.color[2])} {point.error:.17g}\n"
                )

        tile_receipt = {
            "tileId": tile_id,
            "cameraStart": start,
            "cameraEndExclusive": end,
            "cameraCount": len(selected_images),
            "firstImage": selected_images[0].name,
            "lastImage": selected_images[-1].name,
            "sparsePointCount": len(selected_point_ids),
            "dataset": str(tile_root),
        }
        if servo_camera_document is not None:
            selected_names = {image.name for image in selected_images}
            tile_camera_document = dict(servo_camera_document)
            tile_camera_document["cameras"] = [
                camera
                for camera in servo_camera_document["cameras"]
                if str(camera["image"]) in selected_names
            ]
            tile_camera_document["validationImages"] = [
                name
                for name in servo_camera_document.get("validationImages", [])
                if name in selected_names
            ]
            tile_camera_document["pathStressImages"] = []
            (tile_root / "cameras.json").write_text(
                json.dumps(tile_camera_document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tile_receipt["servoCameras"] = str(tile_root / "cameras.json")
        (tile_root / "servo-route-tile.json").write_text(
            json.dumps(tile_receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tiles.append(tile_receipt)

    source_model = next(
        path
        for name in ("images.bin", "images.txt")
        if (path := sparse_source / name).is_file()
    )
    receipt = {
        "schema": SCHEMA,
        "sourceDataset": str(dataset_root),
        "sourceCameraCount": len(ordered_images),
        "tileSize": tile_size,
        "overlap": overlap,
        "tileCount": len(tiles),
        "fullRouteCovered": tiles[0]["cameraStart"] == 0
        and tiles[-1]["cameraEndExclusive"] == len(ordered_images),
        "coordinatePolicy": "preserve-source-colmap-world-coordinates",
        "poseEstimation": "none",
        "sourceModelSha256": f"sha256:{_sha256(source_model)}",
        "tiles": tiles,
    }
    (output / "route-tiles.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tile-size", type=int, default=96)
    parser.add_argument("--overlap", type=int, default=24)
    parser.add_argument("--servo-cameras", type=Path)
    args = parser.parse_args()
    receipt = prepare(
        args.dataset.resolve(),
        args.output.resolve(),
        tile_size=args.tile_size,
        overlap=args.overlap,
        servo_cameras=args.servo_cameras.resolve() if args.servo_cameras else None,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
