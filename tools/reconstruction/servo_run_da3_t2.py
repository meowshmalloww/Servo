#!/usr/bin/env python3
"""Run a sealed Depth Anything 3 Gaussian diagnostic for Servo T2.

This runner intentionally lives outside Servo's published reconstruction path.
It consumes selected source frames, lets the official DA3 model estimate poses
and Gaussians, and writes a standard SH3 PLY plus Servo camera metadata.  The
result remains a non-commercial, non-collision-ready diagnostic because the
DA3-GIANT-1.1 weights are CC BY-NC 4.0.
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
from typing import Any, Sequence

import numpy as np


SCHEMA = "servo.diagnostic-da3-gaussian/v1"
CAMERA_SCHEMA = "servo.gaussian-cameras/v1"
MODEL_ID = "depth-anything/DA3-GIANT-1.1"
MODEL_LICENSE = "CC-BY-NC-4.0"
MAX_MODEL_BYTES = 10 * 1024**3


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def git_revision(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def discover_frames(root: Path) -> list[Path]:
    suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    frames = sorted(path for path in root.rglob("*") if path.suffix.lower() in suffixes)
    if not frames:
        raise RuntimeError(f"No image frames were found below {root}")
    return frames


def select_frame_paths(
    frames: Sequence[Path], *, start: int, count: int, stride: int
) -> list[Path]:
    if start < 0:
        raise ValueError("start must be non-negative")
    if count < 2:
        raise ValueError("count must be at least two")
    if stride < 1:
        raise ValueError("stride must be at least one")
    selected = list(frames[start : start + count * stride : stride])
    if len(selected) != count:
        raise RuntimeError(
            f"Requested {count} frames from index {start} with stride {stride}, "
            f"but only {len(selected)} are available."
        )
    return selected


def read_horizon_calibration(
    pose_path: Path, intrinsics_path: Path
) -> tuple[np.ndarray, np.ndarray]:
    poses: dict[int, np.ndarray] = {}
    for line in pose_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) != 13:
            raise RuntimeError(f"Malformed Horizon pose line: {line}")
        index = int(fields[0])
        matrix = np.eye(4, dtype=np.float64)
        values = np.asarray([float(value) for value in fields[1:]], dtype=np.float64)
        # HorizonStream writes R00..R22 followed by tx,ty,tz.  Treating the
        # line as a flattened 3x4 matrix creates a non-rigid camera frame.
        matrix[:3, :3] = values[:9].reshape(3, 3)
        matrix[:3, 3] = values[9:12]
        poses[index] = matrix
    calibrations: dict[int, np.ndarray] = {}
    for line in intrinsics_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) != 5:
            raise RuntimeError(f"Malformed Horizon intrinsics line: {line}")
        index = int(fields[0])
        fx, fy, cx, cy = [float(value) for value in fields[1:]]
        calibrations[index] = np.asarray(
            [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64
        )
    shared = sorted(set(poses).intersection(calibrations))
    if shared != list(range(len(shared))):
        raise RuntimeError("Horizon calibration indices must be contiguous from zero.")
    return (
        np.stack([poses[index] for index in shared]),
        np.stack([calibrations[index] for index in shared]),
    )


def scene_normalization(extrinsics: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    if extrinsics.ndim != 3 or extrinsics.shape[1:] not in ((3, 4), (4, 4)):
        raise RuntimeError(f"Expected Nx3x4 or Nx4x4 extrinsics, got {extrinsics.shape}")
    world_to_camera = np.repeat(
        np.eye(4, dtype=np.float64)[None], extrinsics.shape[0], axis=0
    )
    world_to_camera[:, : extrinsics.shape[1], :4] = extrinsics.astype(np.float64)
    camera_to_world = np.linalg.inv(world_to_camera)
    centers = camera_to_world[:, :3, 3]
    center = np.median(centers, axis=0)
    distances = np.linalg.norm(centers - center, axis=1)
    positive = distances[np.isfinite(distances) & (distances > 1e-8)]
    scale = float(np.quantile(positive, 0.90)) if positive.size else 1.0
    if not math.isfinite(scale) or scale <= 1e-8:
        scale = 1.0
    camera_to_world[:, :3, 3] = (centers - center) / scale
    return center, scale, camera_to_world


def write_cameras(
    path: Path,
    selected: Sequence[Path],
    extrinsics: np.ndarray,
    intrinsics: np.ndarray,
    processed_images: np.ndarray,
    center: np.ndarray,
    scale: float,
) -> None:
    _, _, camera_to_world = scene_normalization(extrinsics)
    height, width = processed_images.shape[1:3]
    cameras = []
    for index, (frame, calibration, transform) in enumerate(
        zip(selected, intrinsics, camera_to_world, strict=True)
    ):
        cameras.append(
            {
                "cameraId": index + 1,
                "cameraModel": "PINHOLE",
                "image": frame.name,
                "width": int(width),
                "height": int(height),
                "calibration": np.asarray(calibration, dtype=np.float64).tolist(),
                "cameraToWorldNormalized": transform.tolist(),
            }
        )
    atomic_json(
        path,
        {
            "schema": CAMERA_SCHEMA,
            "cameras": cameras,
            "normalization": {
                "method": "camera-center-median-p90-v1",
                "center": np.asarray(center, dtype=np.float64).tolist(),
                "scale": scale,
                "metric": False,
            },
            "validationImages": [],
            "pathStressImages": [],
            "validationPolicy": {
                "method": "external-learned-gaussian-diagnostic-v1",
                "trueHeldout": False,
            },
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--da3-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--process-res", type=int, default=392)
    parser.add_argument("--use-ray-pose", action="store_true")
    parser.add_argument("--pose-file", type=Path)
    parser.add_argument("--intrinsics-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"Refusing to overwrite T2 output: {args.output}")
    source_root = args.da3_root / "src"
    model_file = args.model / "model.safetensors"
    config_file = args.model / "config.json"
    if not source_root.is_dir():
        raise RuntimeError(f"DA3 source directory is missing: {source_root}")
    if not model_file.is_file() or not config_file.is_file():
        raise RuntimeError(f"DA3 model is incomplete: {args.model}")
    if model_file.stat().st_size > MAX_MODEL_BYTES:
        raise RuntimeError("DA3 checkpoint exceeds Servo's 10 GiB external-model limit.")
    if args.process_res < 252 or args.process_res > 1008:
        raise RuntimeError("process-res must be between 252 and 1008 pixels.")

    frames = discover_frames(args.frames)
    selected = select_frame_paths(
        frames, start=args.start, count=args.count, stride=args.stride
    )
    supplied_extrinsics = None
    supplied_intrinsics = None
    if (args.pose_file is None) != (args.intrinsics_file is None):
        raise RuntimeError("pose-file and intrinsics-file must be provided together.")
    if args.pose_file is not None and args.intrinsics_file is not None:
        all_extrinsics, all_intrinsics = read_horizon_calibration(
            args.pose_file, args.intrinsics_file
        )
        selected_indices = list(
            range(args.start, args.start + args.count * args.stride, args.stride)
        )
        if selected_indices[-1] >= all_extrinsics.shape[0]:
            raise RuntimeError("Selected frame window exceeds supplied calibration.")
        supplied_extrinsics = all_extrinsics[selected_indices]
        supplied_intrinsics = all_intrinsics[selected_indices]
    args.output.mkdir(parents=True)

    revision = git_revision(args.da3_root)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "backend": {
            "repository": "https://github.com/ByteDance-Seed/Depth-Anything-3",
            "revision": revision,
            "model": MODEL_ID,
            "modelLicense": MODEL_LICENSE,
            "modelBytes": model_file.stat().st_size,
            "modelSha256": sha256_file(model_file),
            "configSha256": sha256_file(config_file),
        },
        "input": {
            "root": str(args.frames.resolve()),
            "availableFrames": len(frames),
            "selectedFrames": [str(path.resolve()) for path in selected],
            "start": args.start,
            "count": args.count,
            "stride": args.stride,
        },
        "settings": {
            "processResolution": args.process_res,
            "processResolutionMethod": "upper_bound_resize",
            "inferGaussians": True,
            "useRayPose": args.use_ray_pose,
            "referenceViewStrategy": "saddle_balanced",
            "shExport": "dc-plus-zero-sh3",
            "cameraConditioning": (
                "horizonstream-world-to-camera-v1"
                if supplied_extrinsics is not None
                else "da3-estimated"
            ),
        },
        "claims": {
            "generatedEvidence": True,
            "metric": False,
            "collisionValidated": False,
            "publishable": False,
        },
    }
    atomic_json(args.output / "t2-receipt.json", receipt)

    sys.path.insert(0, str(source_root))
    import torch
    from depth_anything_3.api import DepthAnything3
    from depth_anything_3.utils.gsply_helpers import save_gaussian_ply

    if not torch.cuda.is_available():
        raise RuntimeError("T2 DA3 inference requires CUDA.")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = DepthAnything3.from_pretrained(str(args.model)).to(device=torch.device("cuda"))
    model.eval()
    loaded = time.perf_counter()
    prediction = model.inference(
        [str(path) for path in selected],
        extrinsics=supplied_extrinsics,
        intrinsics=supplied_intrinsics,
        infer_gs=True,
        use_ray_pose=args.use_ray_pose,
        ref_view_strategy="saddle_balanced",
        process_res=args.process_res,
        process_res_method="upper_bound_resize",
    )
    inferred = time.perf_counter()
    if prediction.gaussians is None:
        raise RuntimeError("DA3 completed without a Gaussian prediction.")
    if prediction.extrinsics is None or prediction.intrinsics is None:
        raise RuntimeError("DA3 completed without camera calibration.")

    center, scale, _ = scene_normalization(prediction.extrinsics)
    prediction.gaussians.means = (
        prediction.gaussians.means -
        torch.as_tensor(center, device=prediction.gaussians.means.device)
    ) / scale
    prediction.gaussians.scales = prediction.gaussians.scales / scale
    depth = torch.from_numpy(prediction.depth).unsqueeze(-1).to(prediction.gaussians.means)
    ply_path = args.output / "world.ply"
    save_gaussian_ply(
        gaussians=prediction.gaussians,
        save_path=str(ply_path),
        ctx_depth=depth,
        shift_and_scale=False,
        save_sh_dc_only=True,
        gs_views_interval=1,
        inv_opacity=True,
        prune_by_depth_percent=0.98,
        prune_border_gs=True,
        match_3dgs_mcmc_dev=True,
    )
    exported = time.perf_counter()
    write_cameras(
        args.output / "cameras.json",
        selected,
        prediction.extrinsics,
        prediction.intrinsics,
        prediction.processed_images,
        center,
        scale,
    )
    np.savez_compressed(
        args.output / "prediction-evidence.npz",
        depth=prediction.depth,
        confidence=prediction.conf,
        extrinsics=prediction.extrinsics,
        intrinsics=prediction.intrinsics,
        sky=prediction.sky,
    )

    receipt.update(
        {
            "status": "completed",
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "timingSeconds": {
                "modelLoad": loaded - started,
                "inference": inferred - loaded,
                "export": exported - inferred,
                "total": exported - started,
            },
            "gpu": {
                "name": torch.cuda.get_device_name(0),
                "peakAllocatedGiB": torch.cuda.max_memory_allocated() / 1024**3,
                "peakReservedGiB": torch.cuda.max_memory_reserved() / 1024**3,
            },
            "output": {
                "ply": ply_path.name,
                "plyBytes": ply_path.stat().st_size,
                "plySha256": sha256_file(ply_path),
                "cameras": "cameras.json",
                "evidence": "prediction-evidence.npz",
                "rawGaussianCount": int(prediction.gaussians.means.shape[1]),
            },
        }
    )
    atomic_json(args.output / "t2-receipt.json", receipt)
    atomic_json(
        args.output / "world.json",
        {
            "schema": "servo.gaussian-world/v1",
            "worldId": args.output.name,
            "createdAt": receipt["completedAt"],
            "profile": "external-da3-giant11-diagnostic",
            "pipelineRevision": "external-da3-giant11-direct-gaussians-v1",
            "representationType": "learned-direct-3dgs-diagnostic",
            "artifacts": {
                "ply": "world.ply",
                "cameras": "cameras.json",
                "evidence": "prediction-evidence.npz",
                "receipt": "t2-receipt.json",
            },
            "hashes": {"world.ply": receipt["output"]["plySha256"]},
            "coordinateSystem": {
                "scale": "unknown-monocular",
                "normalization": "camera-center-median-p90-v1",
            },
            "environment": {
                "backgroundColorSrgb": [0.0, 0.0, 0.0],
                "finiteGeometry": False,
                "containsGeneratedPixels": False,
            },
            "quality": {
                "tier": "unrated-diagnostic",
                "rawGaussians": receipt["output"]["rawGaussianCount"],
            },
            "provenance": receipt["claims"] | {
                "backend": MODEL_ID,
                "modelLicense": MODEL_LICENSE,
            },
        },
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
