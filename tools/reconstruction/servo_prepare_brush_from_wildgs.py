#!/usr/bin/env python3
"""Create a Brush/COLMAP-text dataset from an audited WildGS camera bundle.

This is a format conversion only: camera poses are not recomputed with COLMAP.
Sparse depth samples provide trainer initialization; Brush's output remains an
optimized Gaussian representation rather than a point-cloud product.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from pathlib import Path

import numpy as np
from PIL import Image


SCHEMA = "servo.brush-wildgs-dataset/v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rotation_to_colmap_qvec(rotation: np.ndarray) -> np.ndarray:
    """Return COLMAP's scalar-first quaternion for a world-to-camera matrix."""
    trace = float(np.trace(rotation))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        quaternion = np.array(
            [0.25 * s,
             (rotation[2, 1] - rotation[1, 2]) / s,
             (rotation[0, 2] - rotation[2, 0]) / s,
             (rotation[1, 0] - rotation[0, 1]) / s],
            dtype=np.float64,
        )
    else:
        axis = int(np.argmax(np.diag(rotation)))
        if axis == 0:
            s = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            quaternion = np.array(
                [(rotation[2, 1] - rotation[1, 2]) / s, 0.25 * s,
                 (rotation[0, 1] + rotation[1, 0]) / s,
                 (rotation[0, 2] + rotation[2, 0]) / s], dtype=np.float64)
        elif axis == 1:
            s = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            quaternion = np.array(
                [(rotation[0, 2] - rotation[2, 0]) / s,
                 (rotation[0, 1] + rotation[1, 0]) / s, 0.25 * s,
                 (rotation[1, 2] + rotation[2, 1]) / s], dtype=np.float64)
        else:
            s = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            quaternion = np.array(
                [(rotation[1, 0] - rotation[0, 1]) / s,
                 (rotation[0, 2] + rotation[2, 0]) / s,
                 (rotation[1, 2] + rotation[2, 1]) / s, 0.25 * s], dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[0] < 0.0:
        quaternion *= -1.0
    return quaternion


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def prepare(
    world: Path,
    rgb_root: Path,
    output: Path,
    *,
    sample_stride: int,
    maximum_points: int,
) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    camera_path = world / "cameras.json"
    trajectory_path = world / "wildgs-video.npz"
    camera_document = json.loads(camera_path.read_text(encoding="utf-8"))
    cameras = camera_document["cameras"]
    trajectory = np.load(trajectory_path, allow_pickle=False)
    depths = np.asarray(trajectory["depths"], dtype=np.float32)
    valid_masks = np.asarray(trajectory["valid_depth_masks"], dtype=bool)
    if len(cameras) != depths.shape[0] or depths.shape != valid_masks.shape:
        raise ValueError("camera/depth trajectory lengths do not match")

    images_root = output / "images"
    sparse_root = output / "sparse" / "0"
    sparse_root.mkdir(parents=True)

    first = cameras[0]
    calibration = np.asarray(first["calibration"], dtype=np.float64)
    width, height = int(first["width"]), int(first["height"])
    with (sparse_root / "cameras.txt").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Camera list with one line of data per camera:\n")
        stream.write("# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        stream.write(
            f"1 PINHOLE {width} {height} {calibration[0,0]:.17g} "
            f"{calibration[1,1]:.17g} {calibration[0,2]:.17g} {calibration[1,2]:.17g}\n"
        )

    image_records: list[tuple[int, np.ndarray, np.ndarray, str]] = []
    source_images: list[Path] = []
    for image_id, camera in enumerate(cameras, start=1):
        source_index = int(camera["sourceFrameIndex"])
        source = rgb_root / f"frame_{source_index:05d}.png"
        if not source.is_file():
            raise FileNotFoundError(f"source RGB frame is missing: {source}")
        name = f"frame_{source_index:05d}.png"
        _link_or_copy(source, images_root / name)
        source_images.append(source)
        c2w = np.asarray(camera["cameraToWorldNormalized"], dtype=np.float64)
        w2c = np.linalg.inv(c2w)
        qvec = _rotation_to_colmap_qvec(w2c[:3, :3])
        image_records.append((image_id, qvec, w2c[:3, 3], name))

    with (sparse_root / "images.txt").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Image list with two lines of data per image:\n")
        stream.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        for image_id, qvec, translation, name in image_records:
            values = " ".join(f"{float(value):.17g}" for value in (*qvec, *translation))
            stream.write(f"{image_id} {values} 1 {name}\n\n")

    rng = np.random.default_rng(42)
    points: list[tuple[np.ndarray, np.ndarray]] = []
    for camera, source, depth, valid in zip(cameras, source_images, depths, valid_masks):
        image = np.asarray(Image.open(source).convert("RGB"))
        c2w = np.asarray(camera["cameraToWorldNormalized"], dtype=np.float64)
        map_height, map_width = depth.shape
        fx = calibration[0, 0] * map_width / width
        fy = calibration[1, 1] * map_height / height
        cx = calibration[0, 2] * map_width / width
        cy = calibration[1, 2] * map_height / height
        finite_depth = depth[np.isfinite(depth) & valid & (depth > 0.0)]
        if finite_depth.size == 0:
            continue
        lower, upper = np.quantile(finite_depth, [0.01, 0.99])
        for v in range(sample_stride // 2, map_height, sample_stride):
            for u in range(sample_stride // 2, map_width, sample_stride):
                z = float(depth[v, u])
                if not valid[v, u] or not math.isfinite(z) or z < lower or z > upper:
                    continue
                point_camera = np.array([(u - cx) * z / fx, (v - cy) * z / fy, z, 1.0])
                point_world = (c2w @ point_camera)[:3]
                image_u = min(width - 1, max(0, int(round((u + 0.5) * width / map_width - 0.5))))
                image_v = min(height - 1, max(0, int(round((v + 0.5) * height / map_height - 0.5))))
                points.append((point_world, image[image_v, image_u]))

    if len(points) > maximum_points:
        indices = rng.choice(len(points), maximum_points, replace=False)
        points = [points[int(index)] for index in indices]
    if not points:
        raise RuntimeError("no valid initialization samples were produced")
    with (sparse_root / "points3D.txt").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# 3D point list with one line of data per point:\n")
        stream.write("# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
        for point_id, (xyz, rgb) in enumerate(points, start=1):
            stream.write(
                f"{point_id} {xyz[0]:.9g} {xyz[1]:.9g} {xyz[2]:.9g} "
                f"{int(rgb[0])} {int(rgb[1])} {int(rgb[2])} 0\n"
            )

    receipt = {
        "schema": SCHEMA,
        "poseSource": "WildGS-SLAM/DROID-SLAM; converted to COLMAP text without COLMAP pose estimation",
        "appearanceRepresentation": "Brush optimized 3D Gaussians",
        "initializationOnly": "sparse samples backprojected from WildGS relative depths",
        "cameraCount": len(cameras),
        "initialPointCount": len(points),
        "sampleStride": sample_stride,
        "sourceHashes": {
            "cameras.json": f"sha256:{_sha256(camera_path)}",
            "wildgs-video.npz": f"sha256:{_sha256(trajectory_path)}",
        },
    }
    (output / "servo-brush-dataset-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True, type=Path)
    parser.add_argument("--rgb-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-stride", type=int, default=24)
    parser.add_argument("--maximum-points", type=int, default=100_000)
    args = parser.parse_args()
    if args.sample_stride < 1 or args.maximum_points < 1:
        parser.error("sample stride and maximum points must be positive")
    print(json.dumps(prepare(
        args.world.resolve(), args.rgb_root.resolve(), args.output.resolve(),
        sample_stride=args.sample_stride, maximum_points=args.maximum_points,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
