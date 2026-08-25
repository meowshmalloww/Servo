#!/usr/bin/env python3
"""Forensically isolate SH and giant-splat instability in a preserved Servo PLY.

Sky is deliberately excluded from scoring. This diagnostic never changes or
publishes the source world and never interprets opacity as collision evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import cv2
import numpy as np

from servo_audit_world import (
    AuditError,
    atomic_json,
    camera_records,
    create_encoder,
    finish_encoder,
    load_gaussians,
    resolve_audit_source,
    sha256_file,
)


SCHEMA = "servo.splat-forensics/v1"


def numeric_distribution(values: Any) -> dict[str, float | int | None]:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    if not array.size:
        return {"count": 0, "p50": None, "p90": None, "p95": None, "p99": None, "maximum": None}
    return {
        "count": int(array.size),
        "p50": float(np.percentile(array, 50)),
        "p90": float(np.percentile(array, 90)),
        "p95": float(np.percentile(array, 95)),
        "p99": float(np.percentile(array, 99)),
        "maximum": float(np.max(array)),
    }


def diagnostic_masks(
    max_projected_radius: Any,
    anisotropy: Any,
    opacity: Any,
) -> dict[str, Any]:
    import torch

    count = int(max_projected_radius.numel())
    if count == 0:
        raise AuditError("The Gaussian diagnostic received an empty PLY.")
    finite = (
        torch.isfinite(max_projected_radius)
        & torch.isfinite(anisotropy)
        & torch.isfinite(opacity)
    )
    result: dict[str, Any] = {
        "original-sh3": finite,
        "sh0-only": finite,
        "anisotropy-at-most-20": finite & (anisotropy <= 20.0),
        "anisotropy-at-most-35": finite & (anisotropy <= 35.0),
    }
    for fraction, label in ((0.001, "0.1"), (0.005, "0.5"), (0.01, "1.0")):
        removal = max(1, int(math.ceil(count * fraction)))
        threshold = torch.topk(max_projected_radius, removal, largest=True).values.min()
        result[f"remove-top-{label}pct-radius"] = finite & (max_projected_radius < threshold)
    giant_threshold = torch.quantile(max_projected_radius, 0.995)
    result["remove-low-opacity-giants"] = finite & ~(
        (max_projected_radius >= giant_threshold) & (opacity < 0.10)
    )
    return result


def selected_pose_cases(cameras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indices = sorted(set(np.linspace(0, len(cameras) - 1, min(3, len(cameras))).round().astype(int)))
    steps = [
        np.linalg.norm(right["c2w"][:3, 3] - left["c2w"][:3, 3])
        for left, right in zip(cameras[:-1], cameras[1:])
    ]
    positive = np.asarray(steps, dtype=np.float64)
    positive = positive[np.isfinite(positive) & (positive > 1e-8)]
    baseline = float(np.median(positive)) if positive.size else 0.01

    def yaw_matrix(degrees: float) -> np.ndarray:
        angle = math.radians(degrees)
        cosine, sine = math.cos(angle), math.sin(angle)
        return np.asarray([[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]])

    result: list[dict[str, Any]] = []
    for index in indices:
        camera = cameras[index]
        result.append({"anchor": index, "case": "registered", "c2w": camera["c2w"], "calibration": camera["calibration"]})
        for name, lateral, yaw in (
            ("yaw-left-5deg", 0.0, -5.0),
            ("yaw-right-5deg", 0.0, 5.0),
            ("lateral-left-1x", -1.0, 0.0),
            ("lateral-right-1x", 1.0, 0.0),
        ):
            pose = camera["c2w"].copy()
            pose[:3, 3] += pose[:3, 0] * (lateral * baseline)
            pose[:3, :3] = pose[:3, :3] @ yaw_matrix(yaw)
            result.append({"anchor": index, "case": name, "c2w": pose, "calibration": camera["calibration"]})
    return result


def audit(
    training_output: Path,
    output: Path,
    width: int,
    fps: int,
) -> dict[str, Any]:
    if output.exists():
        raise AuditError(f"Refusing to overwrite existing diagnostic output: {output}")
    output.mkdir(parents=True)
    source = resolve_audit_source(None, training_output)
    cameras = camera_records(source.cameras_path)
    if width < 160 or width > 1280:
        raise AuditError("Diagnostic width must be within [160, 1280].")
    height = max(90, round(width * cameras[0]["height"] / cameras[0]["width"]))

    from servo_gsplat_runtime import prepare_gsplat_runtime

    runtime = prepare_gsplat_runtime()
    import torch
    from gsplat.rendering import rasterization

    device = "cuda"
    gaussians, sh_degree = load_gaussians(source.ply_path, device)
    count = int(gaussians["means"].shape[0])
    largest_scale = gaussians["scales"].max(dim=-1).values
    smallest_scale = gaussians["scales"].min(dim=-1).values.clamp_min(1e-12)
    anisotropy = largest_scale / smallest_scale
    opacity = gaussians["opacities"].flatten()
    max_radius = torch.zeros(count, device=device)
    minimum_depth = torch.full((count,), float("inf"), device=device)
    projected_views = torch.zeros(count, dtype=torch.int32, device=device)

    sample_indices = sorted(set(np.linspace(0, len(cameras) - 1, min(33, len(cameras))).round().astype(int)))
    with torch.inference_mode():
        for camera_index in sample_indices:
            camera = cameras[camera_index]
            scale_x = width / camera["width"]
            scale_y = height / camera["height"]
            calibration_np = camera["calibration"].copy()
            calibration_np[0, :] *= scale_x
            calibration_np[1, :] *= scale_y
            c2w = torch.from_numpy(camera["c2w"].astype(np.float32))[None].to(device)
            calibration = torch.from_numpy(calibration_np.astype(np.float32))[None].to(device)
            _, _, info = rasterization(
                means=gaussians["means"], quats=gaussians["quats"], scales=gaussians["scales"],
                opacities=gaussians["opacities"], colors=gaussians["colors"],
                viewmats=torch.linalg.inv(c2w), Ks=calibration, width=width, height=height,
                packed=True, rasterize_mode="antialiased", eps2d=0.3, camera_model="pinhole",
                render_mode="RGB", sh_degree=sh_degree, near_plane=0.01, far_plane=1e4,
                backgrounds=None,
            )
            ids = info["gaussian_ids"]
            radii = info["radii"].max(dim=-1).values.to(dtype=torch.float32)
            depths = info["depths"].to(dtype=torch.float32)
            max_radius[ids] = torch.maximum(max_radius[ids], radii)
            minimum_depth[ids] = torch.minimum(minimum_depth[ids], depths)
            projected_views.index_add_(0, ids, torch.ones_like(ids, dtype=torch.int32))

    masks = diagnostic_masks(max_radius, anisotropy, opacity)
    cases = selected_pose_cases(cameras)
    modes = list(masks)
    video_modes = ("original-sh3", "sh0-only", "remove-top-0.5pct-radius", "anisotropy-at-most-35")
    mode_results: dict[str, dict[str, Any]] = {}
    frames_by_mode: dict[str, list[np.ndarray]] = {mode: [] for mode in video_modes}

    with torch.inference_mode():
        for mode in modes:
            keep = masks[mode]
            rendered_cases: list[dict[str, Any]] = []
            for case in cases:
                camera = cameras[int(case["anchor"])]
                scale_x = width / camera["width"]
                scale_y = height / camera["height"]
                calibration_np = case["calibration"].copy()
                calibration_np[0, :] *= scale_x
                calibration_np[1, :] *= scale_y
                rgb, alpha, _ = rasterization(
                    means=gaussians["means"][keep], quats=gaussians["quats"][keep],
                    scales=gaussians["scales"][keep], opacities=gaussians["opacities"][keep],
                    colors=gaussians["colors"][keep, :1] if mode == "sh0-only" else gaussians["colors"][keep],
                    viewmats=torch.linalg.inv(torch.from_numpy(case["c2w"].astype(np.float32))[None].to(device)),
                    Ks=torch.from_numpy(calibration_np.astype(np.float32))[None].to(device),
                    width=width, height=height, packed=True, rasterize_mode="antialiased", eps2d=0.3,
                    camera_model="pinhole", render_mode="RGB", sh_degree=0 if mode == "sh0-only" else sh_degree,
                    near_plane=0.01, far_plane=1e4, backgrounds=None,
                )
                rgb_np = rgb[0].clamp(0.0, 1.0).cpu().numpy()
                alpha_np = alpha[0, :, :, 0].clamp(0.0, 1.0).cpu().numpy()
                lower = alpha_np[height // 4 :, :]
                rendered_cases.append({
                    "anchor": int(case["anchor"]), "case": case["case"],
                    "support": float(np.mean(alpha_np >= 0.5)),
                    "lowerThreeQuarterSupport": float(np.mean(lower >= 0.5)),
                    "meanAlpha": float(np.mean(alpha_np)),
                })
                if mode in frames_by_mode:
                    frame = cv2.cvtColor((rgb_np * 255.0 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR)
                    cv2.putText(frame, mode, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
                    cv2.putText(frame, f"{case['case']} / sky ignored", (10, height - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
                    frames_by_mode[mode].append(frame)
            mode_results[mode] = {
                "retainedGaussians": int(keep.sum().item()),
                "removedGaussians": int(count - keep.sum().item()),
                "supportMinimum": min(value["support"] for value in rendered_cases),
                "lowerThreeQuarterSupportMinimum": min(value["lowerThreeQuarterSupport"] for value in rendered_cases),
                "cases": rendered_cases,
            }

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AuditError("FFmpeg is required to encode the forensic comparison.")
    video_path = output / "splat-forensics.mp4"
    encoder = create_encoder(ffmpeg, video_path, width * 2, height * 2, fps)
    try:
        for frame_index in range(len(cases)):
            top = np.concatenate([frames_by_mode[video_modes[0]][frame_index], frames_by_mode[video_modes[1]][frame_index]], axis=1)
            bottom = np.concatenate([frames_by_mode[video_modes[2]][frame_index], frames_by_mode[video_modes[3]][frame_index]], axis=1)
            encoder.stdin.write(np.concatenate([top, bottom], axis=0).tobytes())
        finish_encoder(encoder)
    except Exception:
        with contextlib.suppress(Exception):
            encoder.kill()
        raise

    finite_depth = minimum_depth[torch.isfinite(minimum_depth)].cpu().numpy()
    sh0_energy = torch.linalg.vector_norm(gaussians["colors"][:, :1], dim=(1, 2))
    shn_energy = torch.linalg.vector_norm(gaussians["colors"][:, 1:], dim=(1, 2))
    result = {
        "schema": SCHEMA,
        "source": {"worldPlySha256": sha256_file(source.ply_path), "nonPublishable": True},
        "skyPolicy": "ignored-not-scored",
        "runtime": runtime,
        "sampledRegisteredViews": len(sample_indices),
        "stressCases": len(cases),
        "gaussians": count,
        "largestScale": numeric_distribution(largest_scale.cpu().numpy()),
        "anisotropy": numeric_distribution(anisotropy.cpu().numpy()),
        "opacity": numeric_distribution(opacity.cpu().numpy()),
        "maximumProjectedRadiusPixels": numeric_distribution(max_radius.cpu().numpy()),
        "minimumCameraDepth": numeric_distribution(finite_depth),
        "projectedSampledViewCount": numeric_distribution(projected_views.cpu().numpy()),
        "sh0Energy": numeric_distribution(sh0_energy.cpu().numpy()),
        "higherOrderShEnergy": numeric_distribution(shn_energy.cpu().numpy()),
        "modes": mode_results,
        "video": video_path.name,
        "limitations": [
            "Projected-view count is visibility, not compositing contribution.",
            "Stress poses have no reference image and measure support/stability, not correctness.",
            "Filtered modes are diagnostics and are not published replacement worlds.",
            "Sky is intentionally excluded from scoring at the user's request.",
        ],
    }
    atomic_json(output / "splat-forensics.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-training-output", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--fps", type=int, default=2)
    arguments = parser.parse_args()
    try:
        started = time.perf_counter()
        result = audit(arguments.diagnostic_training_output, arguments.output, arguments.width, arguments.fps)
    except (AuditError, OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"event": "splat_forensics_failed", "error": str(error)}, separators=(",", ":")))
        return 1
    print(json.dumps({"event": "splat_forensics_complete", "output": str(arguments.output.resolve()), "elapsedSeconds": time.perf_counter() - started, "modes": {name: {"retainedGaussians": value["retainedGaussians"], "supportMinimum": value["supportMinimum"]} for name, value in result["modes"].items()}}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
