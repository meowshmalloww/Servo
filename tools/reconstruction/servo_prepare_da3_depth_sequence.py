#!/usr/bin/env python3
"""Fuse pose-conditioned DA3 depth over a bounded monocular video sequence.

This is an external-model diagnostic.  It does not export a presentation point
cloud.  The resulting depth/confidence maps are only geometry evidence for a
later full-resolution RGB 3DGS optimization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


SCHEMA = "servo.da3-depth-sequence/v1"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_indexed_rows(path: Path, columns: int) -> np.ndarray:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        values = [float(value) for value in fields]
        if len(values) == columns + 1:
            values = values[1:]
        if len(values) != columns:
            raise ValueError(f"Expected {columns} values in {path}, received {len(values)}")
        rows.append(values)
    if not rows:
        raise ValueError(f"No calibration rows in {path}")
    return np.asarray(rows, dtype=np.float32)


def read_horizon_calibration(
    pose_path: Path,
    intrinsics_path: Path,
) -> tuple[np.ndarray, np.ndarray]:
    pose_rows = read_indexed_rows(pose_path, 12)
    extrinsics = np.repeat(np.eye(4, dtype=np.float32)[None, ...], len(pose_rows), axis=0)
    extrinsics[:, :3, :3] = pose_rows[:, :9].reshape(-1, 3, 3)
    extrinsics[:, :3, 3] = pose_rows[:, 9:]
    intrinsics_rows = read_indexed_rows(intrinsics_path, 4)
    intrinsics = np.zeros((len(intrinsics_rows), 3, 3), dtype=np.float32)
    intrinsics[:, 0, 0] = intrinsics_rows[:, 0]
    intrinsics[:, 1, 1] = intrinsics_rows[:, 1]
    intrinsics[:, 0, 2] = intrinsics_rows[:, 2]
    intrinsics[:, 1, 2] = intrinsics_rows[:, 3]
    intrinsics[:, 2, 2] = 1.0
    if len(extrinsics) != len(intrinsics):
        raise ValueError("Pose and intrinsic row counts differ.")
    determinants = np.linalg.det(extrinsics[:, :3, :3])
    if not np.all(np.isfinite(determinants)) or np.max(np.abs(determinants - 1.0)) > 1e-3:
        raise ValueError("Horizon calibration contains a non-rigid or reflected camera rotation.")
    return extrinsics, intrinsics


def horizon_intrinsics_to_source(
    intrinsics: np.ndarray,
    *,
    source_width: int,
    source_height: int,
    horizon_long_edge: int,
    patch_size: int,
) -> np.ndarray:
    scale = float(horizon_long_edge) / float(max(source_width, source_height))
    resized_width = int(round(source_width * scale))
    resized_height = int(round(source_height * scale))
    processed_width = (resized_width // patch_size) * patch_size
    processed_height = (resized_height // patch_size) * patch_size
    crop_x = (resized_width - processed_width) // 2
    crop_y = (resized_height - processed_height) // 2
    result = intrinsics.copy()
    result[:, 0, 0] /= scale
    result[:, 1, 1] /= scale
    result[:, 0, 2] = (result[:, 0, 2] + crop_x) / scale
    result[:, 1, 2] = (result[:, 1, 2] + crop_y) / scale
    return result


def window_starts(frame_count: int, window: int, overlap: int) -> list[int]:
    if frame_count <= 0 or window <= 0 or overlap < 0 or overlap >= window:
        raise ValueError("Invalid frame/window/overlap configuration.")
    if frame_count <= window:
        return [0]
    stride = window - overlap
    starts = list(range(0, frame_count - window + 1, stride))
    final = frame_count - window
    if starts[-1] != final:
        starts.append(final)
    return starts


def fuse_predictions(
    depths: list[np.ndarray], confidences: list[np.ndarray]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not depths or len(depths) != len(confidences):
        raise ValueError("Depth/confidence prediction lists must be nonempty and aligned.")
    depth_stack = np.stack(depths).astype(np.float32, copy=False)
    confidence_stack = np.stack(confidences).astype(np.float32, copy=False)
    valid = (
        np.isfinite(depth_stack)
        & (depth_stack > 0.0)
        & np.isfinite(confidence_stack)
        & (confidence_stack > 0.0)
    )
    masked_depth = np.where(valid, depth_stack, np.nan)
    fused_depth = np.nanmedian(masked_depth, axis=0).astype(np.float32)
    fused_confidence = np.nanmedian(
        np.where(valid, confidence_stack, np.nan), axis=0
    ).astype(np.float32)
    relative_spread = np.nanmedian(
        np.abs(masked_depth - fused_depth[None, ...])
        / np.maximum(fused_depth[None, ...], 1e-6),
        axis=0,
    ).astype(np.float32)
    fused_depth[~np.isfinite(fused_depth)] = 0.0
    fused_confidence[~np.isfinite(fused_confidence)] = 0.0
    relative_spread[~np.isfinite(relative_spread)] = 1.0
    return fused_depth, fused_confidence, relative_spread


def discover_images(root: Path) -> list[Path]:
    images = sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not images:
        raise FileNotFoundError(f"No source images in {root}")
    return images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--da3-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--pose-file", type=Path, required=True)
    parser.add_argument("--intrinsics-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--process-res", type=int, default=504)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--overlap", type=int, default=4)
    parser.add_argument("--horizon-long-edge", type=int, default=518)
    parser.add_argument("--patch-size", type=int, default=14)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite output: {output}")
    source_root = args.da3_root.resolve() / "src"
    model_file = args.model.resolve() / "model.safetensors"
    model_config = args.model.resolve() / "config.json"
    for required in (source_root, model_file, model_config, args.pose_file, args.intrinsics_file):
        if not required.exists():
            raise FileNotFoundError(required)

    images = discover_images(args.frames.resolve())
    width, height = Image.open(images[0]).size
    if any(Image.open(path).size != (width, height) for path in images):
        raise ValueError("Source frame sizes differ.")
    extrinsics, horizon_intrinsics = read_horizon_calibration(
        args.pose_file.resolve(), args.intrinsics_file.resolve()
    )
    if len(images) != len(extrinsics):
        raise ValueError(
            f"Frame/calibration count mismatch: {len(images)} images, {len(extrinsics)} poses"
        )
    source_intrinsics = horizon_intrinsics_to_source(
        horizon_intrinsics,
        source_width=width,
        source_height=height,
        horizon_long_edge=args.horizon_long_edge,
        patch_size=args.patch_size,
    )
    starts = window_starts(len(images), args.window, args.overlap)

    output.mkdir(parents=True)
    (output / "depth" / "dpt").mkdir(parents=True)
    (output / "depth" / "conf").mkdir(parents=True)
    (output / "depth" / "spread").mkdir(parents=True)
    (output / "poses").mkdir(parents=True)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "frames": str(args.frames.resolve()),
            "frameCount": len(images),
            "imageSize": [width, height],
            "poseFile": str(args.pose_file.resolve()),
            "poseSha256": sha256_file(args.pose_file.resolve()),
            "intrinsicsFile": str(args.intrinsics_file.resolve()),
            "intrinsicsSha256": sha256_file(args.intrinsics_file.resolve()),
        },
        "model": {
            "repository": "https://github.com/ByteDance-Seed/depth-anything-3",
            "modelId": "depth-anything/DA3-GIANT-1.1",
            "modelSha256": sha256_file(model_file),
            "configSha256": sha256_file(model_config),
            "license": "CC-BY-NC-4.0",
            "distributionAllowed": False,
        },
        "window": args.window,
        "overlap": args.overlap,
        "windowStarts": starts,
        "processResolution": args.process_res,
        "claims": {
            "pointCloudIsPresentationWorld": False,
            "appearanceRepresentation": "pending-full-resolution-rgb-3dgs",
            "metricScaleValidated": False,
            "collisionValidated": False,
            "publishable": False,
        },
    }
    atomic_json(output / "da3-depth-sequence-receipt.json", receipt)

    sys.path.insert(0, str(source_root))
    import torch
    from depth_anything_3.api import DepthAnything3

    if not torch.cuda.is_available():
        raise RuntimeError("DA3 sequence inference requires CUDA.")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    start_time = time.perf_counter()
    model = DepthAnything3.from_pretrained(str(args.model.resolve())).to("cuda").eval()
    loaded_time = time.perf_counter()
    depth_candidates: list[list[np.ndarray]] = [[] for _ in images]
    confidence_candidates: list[list[np.ndarray]] = [[] for _ in images]
    processed_intrinsics: list[np.ndarray | None] = [None for _ in images]
    window_receipts: list[dict[str, Any]] = []
    for ordinal, start in enumerate(starts):
        end = min(start + args.window, len(images))
        prediction = model.inference(
            [str(path) for path in images[start:end]],
            extrinsics=extrinsics[start:end],
            intrinsics=source_intrinsics[start:end],
            align_to_input_ext_scale=True,
            infer_gs=False,
            use_ray_pose=False,
            ref_view_strategy="saddle_balanced",
            process_res=args.process_res,
            process_res_method="upper_bound_resize",
        )
        if prediction.extrinsics is None or prediction.intrinsics is None:
            raise RuntimeError(f"DA3 window {start}:{end} omitted calibration.")
        returned_extrinsics = np.asarray(prediction.extrinsics)
        expected_extrinsics = extrinsics[start:end, :3, :4]
        if returned_extrinsics.shape != expected_extrinsics.shape:
            raise RuntimeError(
                f"DA3 window {start}:{end} returned unexpected extrinsics shape "
                f"{returned_extrinsics.shape}."
            )
        if np.max(np.abs(returned_extrinsics - expected_extrinsics)) > 1e-4:
            raise RuntimeError(f"DA3 window {start}:{end} changed supplied camera poses.")
        for local, frame_index in enumerate(range(start, end)):
            depth_candidates[frame_index].append(np.asarray(prediction.depth[local]))
            confidence_candidates[frame_index].append(np.asarray(prediction.conf[local]))
            current_intrinsics = np.asarray(prediction.intrinsics[local])
            if processed_intrinsics[frame_index] is None:
                processed_intrinsics[frame_index] = current_intrinsics
            elif np.max(np.abs(processed_intrinsics[frame_index] - current_intrinsics)) > 1e-4:
                raise RuntimeError(f"Processed intrinsics changed for frame {frame_index}.")
        window_receipts.append(
            {
                "ordinal": ordinal,
                "start": start,
                "endExclusive": end,
                "elapsedSeconds": time.perf_counter() - start_time,
            }
        )
        receipt["completedWindows"] = window_receipts
        atomic_json(output / "da3-depth-sequence-receipt.json", receipt)

    spread_medians: list[float] = []
    spread_p95s: list[float] = []
    for index, (depths, confidences) in enumerate(
        zip(depth_candidates, confidence_candidates)
    ):
        depth, confidence, spread = fuse_predictions(depths, confidences)
        np.save(output / "depth" / "dpt" / f"frame_{index:06d}.npy", depth)
        np.save(output / "depth" / "conf" / f"frame_{index:06d}.npy", confidence)
        np.save(output / "depth" / "spread" / f"frame_{index:06d}.npy", spread)
        finite_spread = spread[np.isfinite(spread)]
        spread_medians.append(float(np.median(finite_spread)))
        spread_p95s.append(float(np.percentile(finite_spread, 95)))

    pose_rows = np.concatenate(
        [extrinsics[:, :3, :3].reshape(-1, 9), extrinsics[:, :3, 3]], axis=1
    )
    intrinsic_matrices = np.stack(
        [matrix for matrix in processed_intrinsics if matrix is not None]
    )
    if len(intrinsic_matrices) != len(images):
        raise RuntimeError("One or more frames have no processed intrinsics.")
    intrinsic_rows = np.stack(
        [
            intrinsic_matrices[:, 0, 0],
            intrinsic_matrices[:, 1, 1],
            intrinsic_matrices[:, 0, 2],
            intrinsic_matrices[:, 1, 2],
        ],
        axis=1,
    )
    np.savetxt(
        output / "poses" / "abs_pose.txt",
        np.column_stack([np.arange(len(images)), pose_rows]),
        fmt=["%d"] + ["%.9g"] * 12,
    )
    np.savetxt(
        output / "poses" / "intri.txt",
        np.column_stack([np.arange(len(images)), intrinsic_rows]),
        fmt=["%d"] + ["%.9g"] * 4,
    )
    finished = time.perf_counter()
    receipt.update(
        {
            "status": "completed",
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "processedImageSize": [
                int(depth_candidates[0][0].shape[1]),
                int(depth_candidates[0][0].shape[0]),
            ],
            "timingSeconds": {
                "modelLoad": loaded_time - start_time,
                "inferenceAndFusion": finished - loaded_time,
                "total": finished - start_time,
            },
            "cuda": {
                "peakAllocatedGiB": torch.cuda.max_memory_allocated() / (1024**3),
                "peakReservedGiB": torch.cuda.max_memory_reserved() / (1024**3),
            },
            "crossWindowRelativeDepthSpread": {
                "frameMedianP50": float(np.median(spread_medians)),
                "frameP95Maximum": float(np.max(spread_p95s)),
            },
        }
    )
    atomic_json(output / "da3-depth-sequence-receipt.json", receipt)
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
