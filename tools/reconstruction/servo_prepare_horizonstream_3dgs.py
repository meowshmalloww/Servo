#!/usr/bin/env python3
"""Create a COLMAP-compatible RGB 3DGS dataset from HorizonStream evidence.

HorizonStream depth is used only to seed and track initial geometry.  The
resulting dataset is consumed by Servo's RGB Gaussian optimizer; the dense
point cloud is never the presentation representation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_indexed_rows(path: Path, columns: int) -> np.ndarray:
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            values = [float(value) for value in line.split()]
            if len(values) != columns + 1:
                raise ValueError(f"Malformed row in {path}: {line}")
            index = int(values[0])
            if index != len(rows):
                raise ValueError(f"Non-contiguous frame index {index} in {path}")
            rows.append(values[1:])
    if not rows:
        raise ValueError(f"No records found in {path}")
    return np.asarray(rows, dtype=np.float64)


def _rotation_to_qvec(rotation: np.ndarray) -> tuple[float, float, float, float]:
    """Return COLMAP's scalar-first world-to-camera quaternion."""
    matrix = np.asarray(rotation, dtype=np.float64)
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * scale
        qx = (matrix[2, 1] - matrix[1, 2]) / scale
        qy = (matrix[0, 2] - matrix[2, 0]) / scale
        qz = (matrix[1, 0] - matrix[0, 1]) / scale
    else:
        diagonal = np.diag(matrix)
        axis = int(np.argmax(diagonal))
        if axis == 0:
            scale = math.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2.0
            qw = (matrix[2, 1] - matrix[1, 2]) / scale
            qx = 0.25 * scale
            qy = (matrix[0, 1] + matrix[1, 0]) / scale
            qz = (matrix[0, 2] + matrix[2, 0]) / scale
        elif axis == 1:
            scale = math.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2.0
            qw = (matrix[0, 2] - matrix[2, 0]) / scale
            qx = (matrix[0, 1] + matrix[1, 0]) / scale
            qy = 0.25 * scale
            qz = (matrix[1, 2] + matrix[2, 1]) / scale
        else:
            scale = math.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2.0
            qw = (matrix[1, 0] - matrix[0, 1]) / scale
            qx = (matrix[0, 2] + matrix[2, 0]) / scale
            qy = (matrix[1, 2] + matrix[2, 1]) / scale
            qz = 0.25 * scale
    quaternion = np.asarray([qw, qx, qy, qz], dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[0] < 0.0:
        quaternion *= -1.0
    return tuple(float(value) for value in quaternion)


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _processed_mapping(width: int, height: int, long_edge: int, patch_size: int) -> dict[str, float]:
    scale = float(long_edge) / float(max(width, height))
    resized_width = int(round(width * scale))
    resized_height = int(round(height * scale))
    center_x = resized_width // 2
    center_y = resized_height // 2
    half_width = ((2 * center_x) // patch_size) * (patch_size // 2)
    half_height = ((2 * center_y) // patch_size) * (patch_size // 2)
    crop_x = float(center_x - half_width)
    crop_y = float(center_y - half_height)
    return {
        "scale": scale,
        "scaleX": scale,
        "scaleY": scale,
        "cropX": crop_x,
        "cropY": crop_y,
        "processedWidth": float(2 * half_width),
        "processedHeight": float(2 * half_height),
    }


def _resized_patch_mapping(
    width: int, height: int, long_edge: int, patch_size: int
) -> dict[str, float]:
    """Match DA3 upper_bound_resize followed by nearest-patch resize."""
    scale = float(long_edge) / float(max(width, height))
    resized_width = int(round(width * scale))
    resized_height = int(round(height * scale))

    def nearest_multiple(value: int) -> int:
        down = (value // patch_size) * patch_size
        up = down + patch_size
        return up if abs(up - value) <= abs(value - down) else down

    processed_width = max(patch_size, nearest_multiple(resized_width))
    processed_height = max(patch_size, nearest_multiple(resized_height))
    return {
        "scale": scale,
        "scaleX": float(processed_width) / float(width),
        "scaleY": float(processed_height) / float(height),
        "cropX": 0.0,
        "cropY": 0.0,
        "processedWidth": float(processed_width),
        "processedHeight": float(processed_height),
    }


def prepare(args: argparse.Namespace) -> dict[str, object]:
    horizon_root = args.horizon_output.resolve()
    input_root = args.input_images.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    pose_path = horizon_root / "poses" / "abs_pose.txt"
    intrinsics_path = horizon_root / "poses" / "intri.txt"
    pose_rows = _read_indexed_rows(pose_path, 12)
    poses = np.concatenate(
        [pose_rows[:, :9].reshape(-1, 3, 3), pose_rows[:, 9:].reshape(-1, 3, 1)],
        axis=2,
    )
    intrinsics = _read_indexed_rows(intrinsics_path, 4)
    image_paths = sorted(input_root.glob("*.png")) + sorted(input_root.glob("*.jpg"))
    if len(image_paths) != len(poses) or len(poses) != len(intrinsics):
        raise ValueError(
            f"Frame count mismatch: images={len(image_paths)}, poses={len(poses)}, "
            f"intrinsics={len(intrinsics)}"
        )
    sample = cv2.imread(str(image_paths[0]), cv2.IMREAD_COLOR)
    if sample is None:
        raise ValueError(f"Unable to read {image_paths[0]}")
    source_height, source_width = sample.shape[:2]
    mapping = (
        _resized_patch_mapping(
            source_width, source_height, args.model_long_edge, args.patch_size
        )
        if args.image_mapping == "resize-to-nearest-patch"
        else _processed_mapping(
            source_width, source_height, args.model_long_edge, args.patch_size
        )
    )
    model_width = int(mapping["processedWidth"])
    model_height = int(mapping["processedHeight"])
    scale_x = float(mapping["scaleX"])
    scale_y = float(mapping["scaleY"])
    crop_x = float(mapping["cropX"])
    crop_y = float(mapping["cropY"])

    depth_paths = [horizon_root / "depth" / "dpt" / f"frame_{index:06d}.npy" for index in range(len(poses))]
    conf_paths = [horizon_root / "depth" / "conf" / f"frame_{index:06d}.npy" for index in range(len(poses))]
    missing = [str(path) for path in depth_paths + conf_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing HorizonStream depth/confidence: " + ", ".join(missing[:3]))

    output.mkdir(parents=True)
    sparse = output / "sparse" / "0"
    images_out = output / "images" / "video-horizon"
    masks_out = output / "masks" / "video-horizon"
    sparse.mkdir(parents=True)
    images_out.mkdir(parents=True)
    masks_out.mkdir(parents=True)

    image_names: list[str] = []
    source_images: list[np.ndarray] = []
    for index, source in enumerate(image_paths):
        name = f"video-horizon/{index:06d}.png"
        image_names.append(name)
        destination = output / "images" / name
        _link_or_copy(source, destination)
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (source_height, source_width):
            raise ValueError(f"Inconsistent input image: {source}")
        source_images.append(image)
        mask_destination = output / "masks" / name
        cv2.imwrite(str(mask_destination), np.full((source_height, source_width), 255, dtype=np.uint8))

    depths = [np.load(path, mmap_mode="r") for path in depth_paths]
    confidences = [np.load(path, mmap_mode="r") for path in conf_paths]
    for index, (depth, confidence) in enumerate(zip(depths, confidences)):
        if depth.shape != (model_height, model_width) or confidence.shape != depth.shape:
            raise ValueError(
                f"Unexpected HorizonStream map shape at frame {index}: "
                f"depth={depth.shape}, confidence={confidence.shape}, expected={(model_height, model_width)}"
            )

    rotations = poses[:, :, :3]
    translations = poses[:, :, 3]
    observations: dict[int, list[tuple[float, float, int]]] = defaultdict(list)
    points: list[tuple[np.ndarray, tuple[int, int, int], list[tuple[int, int]]]] = []
    seeds_per_source_frame = [0 for _ in poses]
    rejected = defaultdict(int)
    confidence_thresholds = [
        float(np.percentile(np.asarray(conf)[np.isfinite(conf)], args.confidence_percentile))
        for conf in confidences
    ]
    y_values = range(args.sample_stride // 2, model_height, args.sample_stride)
    x_values = range(args.sample_stride // 2, model_width, args.sample_stride)

    for source_index in range(len(poses)):
        depth = np.asarray(depths[source_index])
        confidence = np.asarray(confidences[source_index])
        fx, fy, cx, cy = intrinsics[source_index]
        neighbor_order = [source_index]
        for delta in (1, -1, 2, -2, 3, -3):
            candidate = source_index + delta
            if 0 <= candidate < len(poses):
                neighbor_order.append(candidate)
        for y in y_values:
            for x in x_values:
                z = float(depth[y, x])
                conf = float(confidence[y, x])
                if not math.isfinite(z) or z <= args.minimum_depth or z > args.maximum_depth:
                    rejected["depth"] += 1
                    continue
                if not math.isfinite(conf) or conf < confidence_thresholds[source_index]:
                    rejected["confidence"] += 1
                    continue
                original_x = (x + crop_x) / scale_x
                original_y = (y + crop_y) / scale_y
                bgr = source_images[source_index][
                    int(np.clip(round(original_y), 0, source_height - 1)),
                    int(np.clip(round(original_x), 0, source_width - 1)),
                ]
                # Conservative sky exclusion for geometry seeds only.  Sky remains
                # RGB evidence and can later be represented by the environment layer.
                blue, green, red = (int(value) for value in bgr)
                if y < model_height * 0.62 and (
                    (red > 235 and green > 235 and blue > 235)
                    or (blue > 155 and blue > red + 8 and green > 100)
                ):
                    rejected["skyLike"] += 1
                    continue
                camera_point = np.asarray(
                    [(x - cx) * z / fx, (y - cy) * z / fy, z], dtype=np.float64
                )
                world_point = rotations[source_index].T @ (
                    camera_point - translations[source_index]
                )
                track_frames: list[tuple[int, float, float]] = []
                for target_index in neighbor_order:
                    target_camera = rotations[target_index] @ world_point + translations[target_index]
                    target_z = float(target_camera[2])
                    if not math.isfinite(target_z) or target_z <= args.minimum_depth:
                        continue
                    target_fx, target_fy, target_cx, target_cy = intrinsics[target_index]
                    target_x = float(target_fx * target_camera[0] / target_z + target_cx)
                    target_y = float(target_fy * target_camera[1] / target_z + target_cy)
                    ix, iy = int(round(target_x)), int(round(target_y))
                    if not (0 <= ix < model_width and 0 <= iy < model_height):
                        continue
                    target_depth = float(depths[target_index][iy, ix])
                    target_conf = float(confidences[target_index][iy, ix])
                    if (
                        not math.isfinite(target_depth)
                        or target_depth <= args.minimum_depth
                        or not math.isfinite(target_conf)
                        or target_conf < confidence_thresholds[target_index]
                    ):
                        continue
                    relative_error = abs(target_z - target_depth) / max(target_depth, 1e-6)
                    if relative_error > args.relative_depth_tolerance:
                        continue
                    target_original_x = (target_x + crop_x) / scale_x
                    target_original_y = (target_y + crop_y) / scale_y
                    if 0.0 <= target_original_x < source_width and 0.0 <= target_original_y < source_height:
                        track_frames.append((target_index, target_original_x, target_original_y))
                    if len(track_frames) >= args.track_length:
                        break
                if len(track_frames) < args.track_length:
                    rejected["track"] += 1
                    continue
                point_id = len(points) + 1
                track: list[tuple[int, int]] = []
                for image_index, px, py in track_frames:
                    point2d_index = len(observations[image_index])
                    observations[image_index].append((px, py, point_id))
                    track.append((image_index + 1, point2d_index))
                rgb = (red, green, blue)
                points.append((world_point, rgb, track))
                seeds_per_source_frame[source_index] += 1
                if args.max_points > 0 and len(points) >= args.max_points:
                    break
            if args.max_points > 0 and len(points) >= args.max_points:
                break
        if args.max_points > 0 and len(points) >= args.max_points:
            break

    if len(points) < 100:
        raise RuntimeError(f"Only {len(points)} consistent seeds survived")

    with (sparse / "cameras.txt").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Camera list with one line of data per camera:\n")
        stream.write("# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        for index, (fx, fy, cx, cy) in enumerate(intrinsics):
            original_fx = fx / scale_x
            original_fy = fy / scale_y
            original_cx = (cx + crop_x) / scale_x
            original_cy = (cy + crop_y) / scale_y
            stream.write(
                f"{index + 1} PINHOLE {source_width} {source_height} "
                f"{original_fx:.12g} {original_fy:.12g} {original_cx:.12g} {original_cy:.12g}\n"
            )

    with (sparse / "images.txt").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Image list with two lines of data per image:\n")
        stream.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        stream.write("# POINTS2D[] as (X, Y, POINT3D_ID)\n")
        for index, pose in enumerate(poses):
            qvec = _rotation_to_qvec(pose[:, :3])
            tx, ty, tz = (float(value) for value in pose[:, 3])
            stream.write(
                f"{index + 1} {' '.join(f'{value:.17g}' for value in qvec)} "
                f"{tx:.17g} {ty:.17g} {tz:.17g} {index + 1} {image_names[index]}\n"
            )
            stream.write(
                " ".join(
                    f"{x:.9g} {y:.9g} {point_id}"
                    for x, y, point_id in observations[index]
                )
                + "\n"
            )

    with (sparse / "points3D.txt").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# 3D point list with one line of data per point:\n")
        stream.write("# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
        for point_id, (xyz, rgb, track) in enumerate(points, start=1):
            track_text = " ".join(f"{image_id} {point2d_index}" for image_id, point2d_index in track)
            stream.write(
                f"{point_id} {xyz[0]:.12g} {xyz[1]:.12g} {xyz[2]:.12g} "
                f"{rgb[0]} {rgb[1]} {rgb[2]} 0.5 {track_text}\n"
            )

    receipt: dict[str, object] = {
        "schema": "servo.horizonstream-3dgs-dataset/v1",
        "source": {
            "horizonOutput": str(horizon_root),
            "inputImages": str(input_root),
            "poseSha256": _sha256(pose_path),
            "intrinsicsSha256": _sha256(intrinsics_path),
        },
        "frames": len(poses),
        "imageSize": [source_width, source_height],
        "modelImageSize": [model_width, model_height],
        "initialSeeds": len(points),
        "initialSeedsPerFrame": {
            "minimum": int(np.min(seeds_per_source_frame)),
            "median": float(np.median(seeds_per_source_frame)),
            "maximum": int(np.max(seeds_per_source_frame)),
            "zeroSeedFrames": int(sum(value == 0 for value in seeds_per_source_frame)),
        },
        "trackObservations": int(sum(len(value) for value in observations.values())),
        "minimumTrackLength": args.track_length,
        "rejected": dict(rejected),
        "confidencePercentile": args.confidence_percentile,
        "relativeDepthTolerance": args.relative_depth_tolerance,
        "imageMapping": args.image_mapping,
        "pointCloudRole": "confidence-filtered-initialization-only",
        "appearanceRepresentation": "rgb-optimized-3d-gaussian-splatting",
        "pointCloudIsPresentationWorld": False,
        "metricScaleValidated": False,
        "collisionValidated": False,
    }
    with (output / "horizonstream-3dgs-dataset-receipt.json").open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon-output", type=Path, required=True)
    parser.add_argument("--input-images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-long-edge", type=int, default=518)
    parser.add_argument("--patch-size", type=int, default=14)
    parser.add_argument("--sample-stride", type=int, default=8)
    parser.add_argument("--confidence-percentile", type=float, default=60.0)
    parser.add_argument("--relative-depth-tolerance", type=float, default=0.10)
    parser.add_argument("--minimum-depth", type=float, default=0.1)
    parser.add_argument("--maximum-depth", type=float, default=80.0)
    parser.add_argument("--track-length", type=int, default=3)
    parser.add_argument(
        "--max-points",
        type=int,
        default=150_000,
        help="Maximum initialization seeds; 0 removes the fixed count ceiling.",
    )
    parser.add_argument(
        "--image-mapping",
        choices=("center-crop-to-patch", "resize-to-nearest-patch"),
        default="center-crop-to-patch",
    )
    args = parser.parse_args()
    if args.track_length < 3:
        parser.error("--track-length must be at least 3")
    print(json.dumps(prepare(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
