#!/usr/bin/env python3
"""Audit a published Servo Gaussian world along its observed camera path.

This tool does not claim metric depth. It renders only interpolated poses between
registered source cameras, records splat support, and estimates line-of-sight
depth ambiguity from the first and second composited depth moments. The output
video is intended for visual acceptance, not collision or navigation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from typing import Any, Iterator

import cv2
import numpy as np


AUDIT_SCHEMA = "servo.gaussian-path-audit/v1"


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"Unable to read {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"Expected a JSON object in {path}.")
    return value


def parse_binary_ply(path: Path) -> tuple[np.memmap, list[str], int]:
    with path.open("rb") as stream:
        header = stream.read(1024 * 1024)
    marker = b"end_header\n"
    end = header.find(marker)
    if end < 0:
        marker = b"end_header\r\n"
        end = header.find(marker)
    if end < 0:
        raise AuditError("The Gaussian PLY has no complete header.")
    try:
        lines = header[: end + len(marker)].decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise AuditError("The Gaussian PLY header is not ASCII.") from error
    if "format binary_little_endian 1.0" not in lines:
        raise AuditError("The path audit requires a binary little-endian Gaussian PLY.")
    vertex_line = next((line for line in lines if line.startswith("element vertex ")), "")
    try:
        count = int(vertex_line.rsplit(" ", 1)[-1])
    except ValueError as error:
        raise AuditError("The Gaussian PLY has an invalid vertex count.") from error
    properties: list[str] = []
    current_element = ""
    for line in lines:
        if line.startswith("element "):
            parts = line.split()
            current_element = parts[1] if len(parts) >= 3 else ""
        elif line.startswith("property ") and current_element == "vertex":
            parts = line.split()
            if len(parts) != 3 or parts[1] not in {"float", "float32"}:
                raise AuditError("The path audit requires scalar float32 vertex properties.")
            properties.append(parts[2])
    required = {
        "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
        "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
    }
    missing = sorted(required.difference(properties))
    if missing:
        raise AuditError("The Gaussian PLY is missing: " + ", ".join(missing))
    dtype = np.dtype([(name, "<f4") for name in properties])
    header_bytes = end + len(marker)
    expected = header_bytes + count * dtype.itemsize
    if path.stat().st_size != expected:
        raise AuditError(f"Unexpected PLY byte length: expected {expected}, found {path.stat().st_size}.")
    records = np.memmap(path, dtype=dtype, mode="r", offset=header_bytes, shape=(count,))
    return records, properties, header_bytes


def field_matrix(records: np.memmap, names: list[str]) -> np.ndarray:
    return np.column_stack([records[name] for name in names]).astype(np.float32, copy=False)


def load_gaussians(path: Path, device: str) -> tuple[dict[str, Any], int]:
    import torch

    records, properties, _ = parse_binary_ply(path)
    rest_names = sorted(
        (name for name in properties if name.startswith("f_rest_")),
        key=lambda name: int(name.rsplit("_", 1)[-1]),
    )
    if len(rest_names) % 3:
        raise AuditError("The Gaussian PLY has a partial spherical-harmonic basis.")
    basis_count = len(rest_names) // 3 + 1
    sh_degree = round(math.sqrt(basis_count) - 1)
    if (sh_degree + 1) ** 2 != basis_count:
        raise AuditError("The Gaussian PLY has a non-square spherical-harmonic basis.")

    means = field_matrix(records, ["x", "y", "z"])
    sh0 = field_matrix(records, ["f_dc_0", "f_dc_1", "f_dc_2"])[:, None, :]
    if rest_names:
        rest_flat = field_matrix(records, rest_names)
        shn = rest_flat.reshape(len(records), 3, -1).transpose(0, 2, 1)
    else:
        shn = np.empty((len(records), 0, 3), dtype=np.float32)
    result = {
        "means": torch.from_numpy(np.array(means, copy=True)).to(device),
        "colors": torch.from_numpy(np.concatenate([sh0, shn], axis=1).copy()).to(device),
        "opacities": torch.sigmoid(
            torch.from_numpy(np.array(records["opacity"], dtype=np.float32, copy=True)).to(device)
        ),
        "scales": torch.exp(
            torch.from_numpy(field_matrix(records, ["scale_0", "scale_1", "scale_2"]).copy()).to(device)
        ),
        "quats": torch.from_numpy(
            field_matrix(records, ["rot_0", "rot_1", "rot_2", "rot_3"]).copy()
        ).to(device),
    }
    del records
    return result, sh_degree


def camera_records(path: Path) -> list[dict[str, Any]]:
    value = read_json(path)
    cameras = value.get("cameras")
    if not isinstance(cameras, list) or len(cameras) < 2:
        raise AuditError("At least two published cameras are required for a path audit.")
    result: list[dict[str, Any]] = []
    for index, camera in enumerate(cameras):
        if not isinstance(camera, dict):
            raise AuditError(f"Published camera {index} is invalid.")
        c2w = np.asarray(camera.get("cameraToWorldNormalized"), dtype=np.float64)
        calibration = np.asarray(camera.get("calibration"), dtype=np.float64)
        if c2w.shape != (4, 4) or calibration.shape != (3, 3):
            raise AuditError(f"Published camera {index} has invalid matrices.")
        if not np.isfinite(c2w).all() or not np.isfinite(calibration).all():
            raise AuditError(f"Published camera {index} contains non-finite values.")
        result.append(
            {
                "c2w": c2w,
                "calibration": calibration,
                "width": int(camera["width"]),
                "height": int(camera["height"]),
                "image": str(camera.get("image", f"camera-{index:04d}")),
            }
        )
    return result


def interpolated_cameras(
    cameras: list[dict[str, Any]],
    frames_per_segment: int,
) -> Iterator[tuple[np.ndarray, np.ndarray, str, float]]:
    from scipy.spatial.transform import Rotation, Slerp

    if frames_per_segment < 1:
        raise AuditError("frames-per-segment must be at least one.")
    for index, (left, right) in enumerate(zip(cameras[:-1], cameras[1:])):
        left_rotation = Rotation.from_matrix(left["c2w"][:3, :3])
        right_rotation = Rotation.from_matrix(right["c2w"][:3, :3])
        slerp = Slerp([0.0, 1.0], Rotation.concatenate([left_rotation, right_rotation]))
        for sample in range(frames_per_segment):
            fraction = sample / frames_per_segment
            c2w = np.eye(4, dtype=np.float64)
            c2w[:3, :3] = slerp([fraction]).as_matrix()[0]
            c2w[:3, 3] = (
                (1.0 - fraction) * left["c2w"][:3, 3]
                + fraction * right["c2w"][:3, 3]
            )
            calibration = (
                (1.0 - fraction) * left["calibration"]
                + fraction * right["calibration"]
            )
            yield c2w, calibration, f"{left['image']} -> {right['image']}", fraction
    final = cameras[-1]
    yield final["c2w"].copy(), final["calibration"].copy(), final["image"], 1.0


def colorize_depth(depth: np.ndarray, alpha: np.ndarray, near: float, far: float) -> np.ndarray:
    valid = np.isfinite(depth) & (depth > 0.0) & (alpha >= 0.5)
    normalized = np.zeros(depth.shape, dtype=np.float32)
    if valid.any():
        log_near = math.log(max(near, 1e-6))
        log_far = math.log(max(far, near + 1e-6))
        normalized[valid] = np.clip(
            (np.log(np.clip(depth[valid], near, far)) - log_near) / (log_far - log_near),
            0.0,
            1.0,
        )
    colored = cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    colored[~valid] = (24, 0, 96)
    return colored


def colorize_ambiguity(relative_std: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    valid = np.isfinite(relative_std) & (alpha >= 0.5)
    normalized = np.zeros(relative_std.shape, dtype=np.float32)
    normalized[valid] = np.clip(relative_std[valid] / 0.20, 0.0, 1.0)
    colored = cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    colored[~valid] = (255, 0, 255)
    return colored


def label_panel(image: np.ndarray, label: str) -> None:
    cv2.rectangle(image, (0, 0), (image.shape[1], 34), (8, 10, 14), thickness=-1)
    cv2.putText(
        image,
        label,
        (12, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (240, 244, 248),
        1,
        cv2.LINE_AA,
    )


def create_encoder(ffmpeg: str, path: Path, width: int, height: int, fps: int) -> subprocess.Popen[bytes]:
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.mp4")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s:v",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    setattr(process, "servo_temporary_path", temporary)
    setattr(process, "servo_final_path", path)
    return process


def finish_encoder(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None:
        process.stdin.close()
    stderr = process.stderr.read() if process.stderr is not None else b""
    return_code = process.wait()
    temporary = Path(getattr(process, "servo_temporary_path"))
    final = Path(getattr(process, "servo_final_path"))
    if return_code != 0:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise AuditError(
            f"FFmpeg path-audit encoding failed with code {return_code}: "
            + stderr.decode("utf-8", errors="replace")[-2000:]
        )
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise AuditError("FFmpeg did not produce a path-audit video.")
    os.replace(temporary, final)


def audit(
    world: Path,
    output: Path,
    width: int,
    frames_per_segment: int,
    fps: int,
) -> dict[str, Any]:
    import torch
    from gsplat.rendering import rasterization

    world = world.resolve()
    output = output.resolve()
    manifest_path = world / "world.json"
    ply_path = world / "world.ply"
    cameras_path = world / "cameras.json"
    for required in (manifest_path, ply_path, cameras_path):
        if not required.is_file():
            raise AuditError(f"Missing published world artifact: {required}")
    manifest = read_json(manifest_path)
    expected_ply_hash = manifest.get("hashes", {}).get("world.ply")
    actual_ply_hash = sha256_file(ply_path)
    if expected_ply_hash != actual_ply_hash:
        raise AuditError("Published world.ply does not match world.json.")
    if not torch.cuda.is_available():
        raise AuditError("The path audit requires the native CUDA renderer.")
    if width < 320 or width % 2:
        raise AuditError("Audit width must be an even integer of at least 320 pixels.")

    cameras = camera_records(cameras_path)
    base_width = cameras[0]["width"]
    base_height = cameras[0]["height"]
    height = max(2, round(base_height * width / base_width))
    if height % 2:
        height += 1
    scale_x = width / base_width
    scale_y = height / base_height
    path_cameras = list(interpolated_cameras(cameras, frames_per_segment))
    output.mkdir(parents=True, exist_ok=True)
    video_path = output / "observed-path-audit.mp4"
    metrics_path = output / "observed-path-audit.json"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AuditError("FFmpeg is required to encode the path audit.")

    device = "cuda"
    gaussians, sh_degree = load_gaussians(ply_path, device)
    encoder = create_encoder(ffmpeg, video_path, width * 3, height, fps)
    support_values: list[float] = []
    lower_support_values: list[float] = []
    center_support_values: list[float] = []
    ambiguity_samples: list[np.ndarray] = []
    camera_steps: list[float] = []
    for left, right in zip(cameras[:-1], cameras[1:]):
        camera_steps.append(float(np.linalg.norm(right["c2w"][:3, 3] - left["c2w"][:3, 3])))

    started = time.perf_counter()
    try:
        with torch.inference_mode():
            for frame_index, (c2w_np, calibration_np, segment, fraction) in enumerate(path_cameras):
                calibration_np = calibration_np.copy()
                calibration_np[0, :] *= scale_x
                calibration_np[1, :] *= scale_y
                c2w = torch.from_numpy(c2w_np.astype(np.float32))[None].to(device)
                viewmat = torch.linalg.inv(c2w)
                calibration = torch.from_numpy(calibration_np.astype(np.float32))[None].to(device)
                rgb_depth, alpha, _ = rasterization(
                    means=gaussians["means"],
                    quats=gaussians["quats"],
                    scales=gaussians["scales"],
                    opacities=gaussians["opacities"],
                    colors=gaussians["colors"],
                    viewmats=viewmat,
                    Ks=calibration,
                    width=width,
                    height=height,
                    packed=True,
                    rasterize_mode="antialiased",
                    eps2d=0.3,
                    camera_model="pinhole",
                    render_mode="RGB+ED",
                    sh_degree=sh_degree,
                    near_plane=0.01,
                    far_plane=1e4,
                )
                rotation = viewmat[0, :3, :3]
                translation = viewmat[0, :3, 3]
                camera_z = (gaussians["means"] @ rotation.T + translation)[:, 2]
                second_moment, _, _ = rasterization(
                    means=gaussians["means"],
                    quats=gaussians["quats"],
                    scales=gaussians["scales"],
                    opacities=gaussians["opacities"],
                    colors=camera_z.square()[:, None],
                    viewmats=viewmat,
                    Ks=calibration,
                    width=width,
                    height=height,
                    packed=True,
                    rasterize_mode="antialiased",
                    eps2d=0.3,
                    camera_model="pinhole",
                    render_mode="RGB",
                    sh_degree=None,
                    near_plane=0.01,
                    far_plane=1e4,
                )
                rgb = rgb_depth[0, :, :, :3].clamp(0.0, 1.0).cpu().numpy()
                depth = rgb_depth[0, :, :, 3].cpu().numpy()
                alpha_np = alpha[0, :, :, 0].clamp(0.0, 1.0).cpu().numpy()
                moment2 = second_moment[0, :, :, 0].cpu().numpy() / np.maximum(alpha_np, 1e-6)
                variance = np.maximum(moment2 - depth * depth, 0.0)
                relative_std = np.sqrt(variance) / np.maximum(depth, 1e-4)
                valid = np.isfinite(relative_std) & np.isfinite(depth) & (depth > 0.0) & (alpha_np >= 0.5)

                support = float(np.mean(alpha_np >= 0.5))
                lower_support = float(np.mean(alpha_np[height // 2 :, :] >= 0.5))
                center_support = float(np.mean(alpha_np[height // 5 : 4 * height // 5, width // 5 : 4 * width // 5] >= 0.5))
                support_values.append(support)
                lower_support_values.append(lower_support)
                center_support_values.append(center_support)
                if valid.any():
                    ambiguity_samples.append(relative_std[::4, ::4][valid[::4, ::4]].astype(np.float32, copy=True))

                rgb_bgr = cv2.cvtColor((rgb * 255.0 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR)
                depth_bgr = colorize_depth(depth, alpha_np, near=0.03, far=8.0)
                ambiguity_bgr = colorize_ambiguity(relative_std, alpha_np)
                label_panel(rgb_bgr, f"RGB render | frame {frame_index + 1}/{len(path_cameras)}")
                label_panel(depth_bgr, "Expected depth | magenta = unsupported")
                label_panel(ambiguity_bgr, "Depth spread proxy | bright = mixed layers")
                cv2.putText(
                    ambiguity_bgr,
                    f"support {support * 100:.1f}% | segment {fraction:.2f}",
                    (12, height - 14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,
                    (240, 244, 248),
                    1,
                    cv2.LINE_AA,
                )
                frame = np.concatenate([rgb_bgr, depth_bgr, ambiguity_bgr], axis=1)
                if encoder.stdin is None:
                    raise AuditError("FFmpeg input pipe is unavailable.")
                encoder.stdin.write(frame.tobytes())
        torch.cuda.synchronize()
        finish_encoder(encoder)
    except Exception:
        with contextlib.suppress(Exception):
            encoder.kill()
        temporary = Path(getattr(encoder, "servo_temporary_path"))
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise

    elapsed = time.perf_counter() - started
    ambiguity = np.concatenate(ambiguity_samples) if ambiguity_samples else np.empty(0, dtype=np.float32)
    result = {
        "schema": AUDIT_SCHEMA,
        "worldId": manifest.get("worldId"),
        "worldPlySha256": actual_ply_hash,
        "representationType": manifest.get("representationType"),
        "cameraPath": {
            "policy": "piecewise-linear-position/slerp-orientation-between-published-cameras",
            "sourceCameras": len(cameras),
            "framesPerSegment": frames_per_segment,
            "renderedFrames": len(path_cameras),
            "extrapolatedFrames": 0,
            "medianCameraStepNormalized": float(np.median(camera_steps)),
            "maximumCameraStepNormalized": float(np.max(camera_steps)),
        },
        "render": {
            "width": width,
            "height": height,
            "fps": fps,
            "elapsedSeconds": elapsed,
            "offlineFramesPerSecond": len(path_cameras) / max(elapsed, 1e-9),
            "video": video_path.name,
            "videoBytes": video_path.stat().st_size,
            "videoSha256": sha256_file(video_path),
        },
        "gaussians": int(gaussians["means"].shape[0]),
        "shDegree": sh_degree,
        "support": {
            "meaning": "Fraction of pixels whose composited splat alpha is at least 0.5; this is not geometry accuracy.",
            "overallMean": float(np.mean(support_values)),
            "overallMinimum": float(np.min(support_values)),
            "lowerHalfMean": float(np.mean(lower_support_values)),
            "lowerHalfMinimum": float(np.min(lower_support_values)),
            "centerMean": float(np.mean(center_support_values)),
            "centerMinimum": float(np.min(center_support_values)),
        },
        "depthAmbiguity": {
            "meaning": "Relative standard deviation of composited Gaussian camera-space depth; this detects mixed layers but is not ground-truth depth error.",
            "sampleCount": int(ambiguity.size),
            "relativeStdP50": float(np.percentile(ambiguity, 50)) if ambiguity.size else None,
            "relativeStdP95": float(np.percentile(ambiguity, 95)) if ambiguity.size else None,
            "fractionAboveFivePercent": float(np.mean(ambiguity > 0.05)) if ambiguity.size else None,
            "fractionAboveTenPercent": float(np.mean(ambiguity > 0.10)) if ambiguity.size else None,
        },
        "limitations": [
            "No metric or ground-truth depth was available.",
            "The path stays between registered cameras and does not test extrapolation outside the capture envelope.",
            "Splat opacity support is not a collision surface or free-space certificate.",
            "Dynamic vegetation and other transient content can remain blurred or geometrically inconsistent.",
            "Offline CUDA throughput is not Vulkan application frame rate.",
        ],
    }
    atomic_json(metrics_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--world", required=True, type=Path, help="Published Servo world directory.")
    result.add_argument("--output", required=True, type=Path, help="Directory for the audit MP4 and JSON.")
    result.add_argument("--width", type=int, default=640, help="Per-panel render width (default: 640).")
    result.add_argument("--frames-per-segment", type=int, default=2, help="Samples per source-camera segment.")
    result.add_argument("--fps", type=int, default=30, help="Encoded audit playback rate.")
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        value = audit(
            arguments.world,
            arguments.output,
            arguments.width,
            arguments.frames_per_segment,
            arguments.fps,
        )
    except AuditError as error:
        print(json.dumps({"event": "world_audit_failed", "error": str(error)}, separators=(",", ":")))
        return 1
    print(json.dumps({"event": "world_audit_complete", "metrics": value}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
