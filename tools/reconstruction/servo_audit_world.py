#!/usr/bin/env python3
"""Audit a published Servo Gaussian world along its observed camera path.

This tool does not claim metric depth. It reloads the exact serialized PLY,
compares registered views with private undistorted references when supplied,
renders interpolated poses between registered cameras, records splat support,
and estimates line-of-sight depth ambiguity from the first and second
composited depth moments. The output video is intended for visual acceptance,
not collision or navigation.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
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


AUDIT_SCHEMA = "servo.gaussian-path-audit/v2"
DIAGNOSTIC_PROVENANCE_SCHEMA = "servo.diagnostic-training-provenance/v1"
SKY_DIAGNOSTIC_SCHEMA = "servo.sky-leakage-diagnostic/v1"
SEMANTIC_SKY_LABEL = 17


class AuditError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class AuditSource:
    """Verified artifacts used by a path audit.

    A normal source is a published world.  The diagnostic variant deliberately
    accepts only an explicitly non-publishable trainer output, so a short A/B
    run can be inspected without manufacturing a world manifest or making it
    appear safe to load as a release.
    """

    root: Path
    ply_path: Path
    cameras_path: Path
    manifest: dict[str, Any]
    environment_root: Path
    non_publishable: bool


def resolve_audit_source(
    world: Path | None,
    diagnostic_training_output: Path | None,
) -> AuditSource:
    """Load a published world or a sealed, explicitly non-publishable probe."""

    if (world is None) == (diagnostic_training_output is None):
        raise AuditError(
            "Provide exactly one published world or non-publishable diagnostic output."
        )
    if diagnostic_training_output is not None:
        root = diagnostic_training_output.resolve()
        config_path = root / "training-config.json"
        metrics_path = root / "train-metrics.json"
        ply_path = root / "world.ply"
        cameras_path = root / "cameras.json"
        for required in (config_path, metrics_path, ply_path, cameras_path):
            if not required.is_file():
                raise AuditError(f"Missing diagnostic training artifact: {required}")
        config = read_json(config_path)
        provenance = config.get("diagnosticProvenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("schema") != DIAGNOSTIC_PROVENANCE_SCHEMA
            or provenance.get("nonPublishable") is not True
        ):
            raise AuditError(
                "The training output is not explicitly marked non-publishable."
            )
        output_value = config.get("output")
        if not isinstance(output_value, str) or Path(output_value).resolve() != root:
            raise AuditError("The diagnostic configuration does not bind to its output.")
        configuration_hash = config.get("configurationHash")
        if not isinstance(configuration_hash, str) or not configuration_hash.startswith(
            "sha256:"
        ):
            raise AuditError("The diagnostic configuration has no valid content hash.")
        metrics = read_json(metrics_path)
        if metrics.get("configurationHash") != configuration_hash:
            raise AuditError(
                "The diagnostic metrics do not match the training configuration."
            )
        actual_ply_hash = sha256_file(ply_path)
        if metrics.get("worldSha256") != actual_ply_hash:
            raise AuditError("The diagnostic world.ply does not match train metrics.")
        environment = metrics.get("environment")
        if not isinstance(environment, dict):
            raise AuditError("The diagnostic output has no environment provenance.")
        geometry_root_value = config.get("geometryRoot")
        if not isinstance(geometry_root_value, str):
            raise AuditError("The diagnostic output has no geometry-prior root.")
        environment_root = Path(geometry_root_value).resolve()
        if not environment_root.is_dir():
            raise AuditError("The diagnostic geometry-prior root no longer exists.")
        return AuditSource(
            root=root,
            ply_path=ply_path,
            cameras_path=cameras_path,
            manifest={
                "worldId": config.get("jobId"),
                "representationType": metrics.get("representationType"),
                "environment": environment,
                "artifactKind": "non-publishable-diagnostic-training-output",
            },
            environment_root=environment_root,
            non_publishable=True,
        )

    assert world is not None
    root = world.resolve()
    manifest_path = root / "world.json"
    ply_path = root / "world.ply"
    cameras_path = root / "cameras.json"
    for required in (manifest_path, ply_path, cameras_path):
        if not required.is_file():
            raise AuditError(f"Missing published world artifact: {required}")
    manifest = read_json(manifest_path)
    expected_ply_hash = manifest.get("hashes", {}).get("world.ply")
    if expected_ply_hash != sha256_file(ply_path):
        raise AuditError("Published world.ply does not match world.json.")
    return AuditSource(
        root=root,
        ply_path=ply_path,
        cameras_path=cameras_path,
        manifest=manifest,
        environment_root=root,
        non_publishable=False,
    )


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
    validation_images = value.get("validationImages")
    if not isinstance(validation_images, list) or not all(
        isinstance(name, str) for name in validation_images
    ):
        raise AuditError("Published cameras have no valid held-out image list.")
    validation_names = set(validation_images)
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
                "validation": str(camera.get("image", "")) in validation_names,
            }
        )
    return result


def load_reference_image(
    root: Path,
    image_name: str,
    width: int,
    height: int,
) -> np.ndarray:
    from PIL import Image, ImageOps

    root = root.resolve()
    image_path = (root / Path(image_name)).resolve()
    try:
        image_path.relative_to(root)
    except ValueError as error:
        raise AuditError(f"Reference image escapes its private root: {image_name}") from error
    if not image_path.is_file():
        raise AuditError(f"Missing private reference image: {image_name}")
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float32) / 255.0


def load_semantic_sky_mask(
    geometry_root: Path,
    image_name: str,
    width: int,
    height: int,
) -> np.ndarray | None:
    """Load observed OneFormer sky evidence for one registered camera.

    Semantic labels are an optional audit input: published worlds do not need
    to ship the private training labels.  When a geometry root does contain
    them, use only the exact camera-relative label image, block path escapes,
    and resize labels with nearest-neighbor sampling.  A missing semantic
    directory is therefore reported as unavailable rather than turned into a
    synthetic sky mask.
    """

    from PIL import Image

    root = geometry_root.resolve()
    semantic_root = root / "semantics"
    if not semantic_root.is_dir():
        return None
    label_path = (semantic_root / Path(image_name)).resolve()
    try:
        label_path.relative_to(semantic_root.resolve())
    except ValueError as error:
        raise AuditError(
            f"Semantic label image escapes its geometry root: {image_name}"
        ) from error
    if not label_path.is_file():
        return None
    with Image.open(label_path) as image:
        labels = np.asarray(image)
    if labels.ndim != 2:
        raise AuditError(
            f"Semantic label image must be single-channel: {image_name}"
        )
    if labels.shape != (height, width):
        labels = cv2.resize(
            labels,
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
    return labels == SEMANTIC_SKY_LABEL


def write_sky_leakage_diagnostic(
    output: Path,
    *,
    ordinal: int,
    image_name: str,
    rendered_rgb: np.ndarray,
    reference_rgb: np.ndarray | None,
    sky_mask: np.ndarray,
    alpha: np.ndarray,
    p95: float,
    threshold: float,
) -> str:
    """Persist a compact, human-reviewable observed-sky failure overlay.

    Red marks finite-Gaussian alpha above the recorded threshold inside an
    observed semantic-sky label.  The overlay is diagnostic evidence only; it
    never changes the trained world, invents missing sky, or asserts geometry.
    """

    if (
        rendered_rgb.ndim != 3
        or rendered_rgb.shape[-1] != 3
        or alpha.shape != rendered_rgb.shape[:2]
        or sky_mask.shape != rendered_rgb.shape[:2]
    ):
        raise AuditError("Sky-leakage diagnostic inputs have incompatible shapes.")
    if reference_rgb is not None and reference_rgb.shape != rendered_rgb.shape:
        raise AuditError("Sky-leakage reference image has an incompatible shape.")

    output.mkdir(parents=True, exist_ok=True)
    rendered_bgr = cv2.cvtColor(
        (np.clip(rendered_rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8),
        cv2.COLOR_RGB2BGR,
    )
    alpha_bgr = cv2.applyColorMap(
        (np.clip(alpha, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8),
        cv2.COLORMAP_TURBO,
    )
    alpha_bgr[~sky_mask] = (34, 34, 34)
    overlay = rendered_bgr.copy()
    leak = sky_mask & (alpha > threshold)
    overlay[sky_mask] = (
        0.72 * overlay[sky_mask].astype(np.float32)
        + 0.28 * np.array([224, 176, 32], dtype=np.float32)
    ).astype(np.uint8)
    overlay[leak] = (
        0.22 * overlay[leak].astype(np.float32)
        + 0.78 * np.array([32, 32, 232], dtype=np.float32)
    ).astype(np.uint8)
    mask_bgr = np.zeros_like(rendered_bgr)
    mask_bgr[sky_mask] = (230, 190, 34)
    if reference_rgb is None:
        reference_bgr = rendered_bgr.copy()
        reference_label = "Reference unavailable"
    else:
        reference_bgr = cv2.cvtColor(
            (np.clip(reference_rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8),
            cv2.COLOR_RGB2BGR,
        )
        reference_label = "Observed RGB"
    label_panel(reference_bgr, reference_label)
    label_panel(rendered_bgr, "Gaussian RGB render")
    label_panel(mask_bgr, "Observed semantic sky (yellow)")
    label_panel(
        alpha_bgr,
        "Finite Gaussian alpha in observed sky",
    )
    label_panel(
        overlay,
        f"Sky leakage overlay | p95 {p95:.3f} > threshold {threshold:.3f}",
    )
    cv2.putText(
        overlay,
        "red = finite splat support where observed label says sky",
        (12, overlay.shape[0] - 14),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (240, 244, 248),
        1,
        cv2.LINE_AA,
    )
    top = np.concatenate([reference_bgr, rendered_bgr], axis=1)
    bottom = np.concatenate([mask_bgr, alpha_bgr], axis=1)
    panel = np.concatenate([top, bottom], axis=0)
    # A fifth view is useful enough to retain, but preserve a regular frame
    # shape by appending it below rather than implying alpha is a reference.
    panel = np.concatenate([panel, np.concatenate([overlay, overlay], axis=1)], axis=0)
    name_digest = hashlib.sha256(image_name.encode("utf-8")).hexdigest()[:12]
    path = output / f"sky-leakage-{ordinal:03d}-{name_digest}.png"
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.png")
    try:
        if not cv2.imwrite(str(temporary), panel):
            raise AuditError(f"Unable to write sky-leakage diagnostic: {path}")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return path.name


def interpolated_cameras(
    cameras: list[dict[str, Any]],
    frames_per_segment: int,
) -> Iterator[tuple[np.ndarray, np.ndarray, str, float, str | None, bool]]:
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
            yield (
                c2w,
                calibration,
                f"{left['image']} -> {right['image']}",
                fraction,
                left["image"] if sample == 0 else None,
                bool(left["validation"]) if sample == 0 else False,
            )
    final = cameras[-1]
    yield (
        final["c2w"].copy(),
        final["calibration"].copy(),
        final["image"],
        1.0,
        final["image"],
        bool(final["validation"]),
    )


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
    world: Path | None,
    output: Path,
    width: int,
    frames_per_segment: int,
    fps: int,
    reference_images: Path | None = None,
    diagnostic_training_output: Path | None = None,
    save_sky_diagnostics: bool = False,
    sky_diagnostic_p95_threshold: float = 0.25,
) -> dict[str, Any]:
    import torch
    from gsplat.rendering import rasterization
    from servo_train import (
        composite_raster_background,
        directional_raster_background,
        ssim,
    )

    source = resolve_audit_source(world, diagnostic_training_output)
    output = output.resolve()
    manifest = source.manifest
    actual_ply_hash = sha256_file(source.ply_path)
    if "environment" not in manifest:
        if manifest.get("pipelineRevision") == "native-colmap-servo-fidelity-gs-r6":
            environment = {
                "backgroundColorSrgb": [0.0, 0.0, 0.0],
                "backgroundSource": "legacy-r6-black-default",
                "finiteSkyGeometry": False,
            }
        else:
            raise AuditError("Published r7 world has no environment provenance.")
    else:
        environment = manifest["environment"]
        if not isinstance(environment, dict):
            raise AuditError("Published environment must be a JSON object.")
    background_values = environment.get("backgroundColorSrgb")
    if (
        not isinstance(background_values, list)
        or len(background_values) != 3
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 1.0
            for value in background_values
        )
    ):
        raise AuditError("Published environment background is invalid.")
    if not torch.cuda.is_available():
        raise AuditError("The path audit requires the native CUDA renderer.")
    if width < 320 or width % 2:
        raise AuditError("Audit width must be an even integer of at least 320 pixels.")
    if (
        not math.isfinite(sky_diagnostic_p95_threshold)
        or not 0.0 <= sky_diagnostic_p95_threshold <= 1.0
    ):
        raise AuditError("Sky-diagnostic p95 threshold must be finite and in [0,1].")
    if reference_images is not None:
        reference_images = reference_images.resolve()
        if not reference_images.is_dir():
            raise AuditError("The private reference-image root does not exist.")

    cameras = camera_records(source.cameras_path)
    background = torch.tensor(
        [float(value) for value in background_values],
        dtype=torch.float32,
        device="cuda:0",
    ).view(1, 3)
    directional_environment = None
    directional_descriptor = environment.get("observedDirectionalEnvironment")
    if directional_descriptor is not None:
        try:
            from servo_environment import (
                EnvironmentError,
                load_observed_directional_environment,
            )

            directional_environment = load_observed_directional_environment(
                source.environment_root,
                directional_descriptor,
                device="cuda:0",
            )
        except (EnvironmentError, OSError, ValueError) as error:
            raise AuditError(
                f"Published directional sky evidence is invalid: {error}"
            ) from error
    elif environment.get("backgroundSource") == (
        "observed-oneformer-sky-equirectangular-plus-mean-fallback-srgb-v1"
    ):
        raise AuditError(
            "Published directional sky background has no observed evidence descriptor."
        )
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
    gaussians, sh_degree = load_gaussians(source.ply_path, device)
    encoder = create_encoder(ffmpeg, video_path, width * 3, height, fps)
    support_values: list[float] = []
    lower_support_values: list[float] = []
    center_support_values: list[float] = []
    environment_coverage_values: list[float] = []
    ambiguity_samples: list[np.ndarray] = []
    sky_diagnostics: list[dict[str, Any]] = []
    sky_diagnostic_directory = output / "sky-leakage-diagnostics"
    registered_psnr: list[float] = []
    registered_ssim: list[float] = []
    heldout_psnr: list[float] = []
    heldout_ssim: list[float] = []
    appearance_views: list[dict[str, Any]] = []
    camera_steps: list[float] = []
    for left, right in zip(cameras[:-1], cameras[1:]):
        camera_steps.append(float(np.linalg.norm(right["c2w"][:3, 3] - left["c2w"][:3, 3])))

    started = time.perf_counter()
    try:
        with torch.inference_mode():
            for frame_index, (
                c2w_np,
                calibration_np,
                segment,
                fraction,
                reference_name,
                is_validation,
            ) in enumerate(path_cameras):
                calibration_np = calibration_np.copy()
                calibration_np[0, :] *= scale_x
                calibration_np[1, :] *= scale_y
                c2w = torch.from_numpy(c2w_np.astype(np.float32))[None].to(device)
                viewmat = torch.linalg.inv(c2w)
                calibration = torch.from_numpy(calibration_np.astype(np.float32))[None].to(device)
                raster_background, environment_coverage = directional_raster_background(
                    directional_environment,
                    c2w,
                    calibration,
                    width,
                    height,
                    background,
                )
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
                    # gsplat 1.5.3 cannot accept camera-batched backgrounds in
                    # packed mode. Composite observed RGB after rasterization
                    # so expected depth remains an unmodified geometry signal.
                    backgrounds=None,
                )
                rgb_depth = composite_raster_background(
                    rgb_depth,
                    alpha,
                    raster_background,
                    "RGB+ED",
                    3,
                )
                if environment_coverage is not None:
                    environment_coverage_values.append(
                        float(environment_coverage.mean().item())
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
                rendered_rgb = rgb_depth[0, :, :, :3].clamp(0.0, 1.0)
                reference_np: np.ndarray | None = None
                if reference_images is not None and reference_name is not None:
                    reference_np = load_reference_image(
                        reference_images, reference_name, width, height
                    )
                    reference = torch.from_numpy(reference_np).to(device)
                    mse = torch.mean((rendered_rgb - reference).square()).clamp_min(1e-12)
                    psnr_value = float((-10.0 * torch.log10(mse)).item())
                    ssim_value = float(
                        ssim(
                            rendered_rgb.permute(2, 0, 1).unsqueeze(0),
                            reference.permute(2, 0, 1).unsqueeze(0),
                        ).item()
                    )
                    registered_psnr.append(psnr_value)
                    registered_ssim.append(ssim_value)
                    if is_validation:
                        heldout_psnr.append(psnr_value)
                        heldout_ssim.append(ssim_value)
                    appearance_views.append(
                        {
                            "image": reference_name,
                            "heldout": is_validation,
                            "psnr": psnr_value,
                            "ssim": ssim_value,
                        }
                    )
                rgb = rendered_rgb.cpu().numpy()
                depth = rgb_depth[0, :, :, 3].cpu().numpy()
                alpha_np = alpha[0, :, :, 0].clamp(0.0, 1.0).cpu().numpy()
                if save_sky_diagnostics and reference_name is not None:
                    sky_mask = load_semantic_sky_mask(
                        source.environment_root,
                        reference_name,
                        width,
                        height,
                    )
                    if sky_mask is not None and bool(sky_mask.any()):
                        observed_sky_alpha = alpha_np[sky_mask]
                        observed_sky_p95 = float(
                            np.percentile(observed_sky_alpha, 95)
                        )
                        if observed_sky_p95 > sky_diagnostic_p95_threshold:
                            artifact = write_sky_leakage_diagnostic(
                                sky_diagnostic_directory,
                                ordinal=len(sky_diagnostics),
                                image_name=reference_name,
                                rendered_rgb=rgb,
                                reference_rgb=reference_np,
                                sky_mask=sky_mask,
                                alpha=alpha_np,
                                p95=observed_sky_p95,
                                threshold=sky_diagnostic_p95_threshold,
                            )
                            sky_diagnostics.append(
                                {
                                    "schema": SKY_DIAGNOSTIC_SCHEMA,
                                    "image": reference_name,
                                    "heldout": is_validation,
                                    "skyPixels": int(sky_mask.sum()),
                                    "skyAlphaP95": observed_sky_p95,
                                    "threshold": sky_diagnostic_p95_threshold,
                                    "artifact": str(
                                        Path("sky-leakage-diagnostics") / artifact
                                    ),
                                    "meaning": (
                                        "Observed semantic-sky pixels with finite "
                                        "Gaussian alpha; diagnostic evidence only, "
                                        "not generated sky or collision geometry."
                                    ),
                                }
                            )
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
                if frame_index % max(1, frames_per_segment * 4) == 0:
                    print(
                        json.dumps(
                            {
                                "event": "world_audit_progress",
                                "completed": frame_index + 1,
                                "total": len(path_cameras),
                            },
                            separators=(",", ":"),
                        ),
                        flush=True,
                    )
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
    if reference_images is not None and (
        len(registered_psnr) != len(cameras)
        or len(heldout_psnr) != sum(bool(camera["validation"]) for camera in cameras)
        or not heldout_psnr
    ):
        raise AuditError(
            "Exact-Ply appearance audit did not cover every registered and held-out camera."
        )
    consecutive_degraded = 0
    maximum_consecutive_degraded = 0
    for view in appearance_views:
        if float(view["psnr"]) < 18.0 or float(view["ssim"]) < 0.60:
            consecutive_degraded += 1
            maximum_consecutive_degraded = max(
                maximum_consecutive_degraded, consecutive_degraded
            )
        else:
            consecutive_degraded = 0
    result = {
        "schema": AUDIT_SCHEMA,
        "worldId": manifest.get("worldId"),
        "artifactKind": manifest.get("artifactKind", "published-world"),
        "nonPublishable": source.non_publishable,
        "worldPlySha256": actual_ply_hash,
        "representationType": manifest.get("representationType"),
        "environment": environment,
        "environmentCoverage": {
            "observedDirectionalTexelMean": (
                float(np.mean(environment_coverage_values))
                if environment_coverage_values
                else 0.0
            ),
            "observedDirectionalTexelMinimum": (
                float(np.min(environment_coverage_values))
                if environment_coverage_values
                else 0.0
            ),
            "observedDirectionalTexelMaximum": (
                float(np.max(environment_coverage_values))
                if environment_coverage_values
                else 0.0
            ),
            "mode": (
                "observed-directional-plus-explicit-mean-fallback"
                if directional_environment is not None
                else "constant-fallback-only"
            ),
        },
        "skyLeakageDiagnostics": {
            "enabled": save_sky_diagnostics,
            "semanticSource": "observed-oneformer-label-17",
            "threshold": sky_diagnostic_p95_threshold,
            "flaggedViews": sky_diagnostics,
            "meaning": (
                "Optional resized path-audit overlays. The production gate is "
                "evaluated separately at trainer resolution."
            ),
        },
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
        "appearance": {
            "meaning": (
                "PSNR/SSIM from the reloaded serialized PLY against private "
                "undistorted references at exact registered camera poses."
            ),
            "available": reference_images is not None,
            "registeredImages": len(registered_psnr),
            "registeredPsnrMean": float(np.mean(registered_psnr))
            if registered_psnr
            else None,
            "registeredSsimMean": float(np.mean(registered_ssim))
            if registered_ssim
            else None,
            "registeredPsnrP10": float(np.percentile(registered_psnr, 10))
            if registered_psnr
            else None,
            "registeredSsimP10": float(np.percentile(registered_ssim, 10))
            if registered_ssim
            else None,
            "maximumConsecutiveDegradedViews": maximum_consecutive_degraded,
            "degradedViewDefinition": "PSNR < 18 dB or SSIM < 0.60",
            "heldoutImages": len(heldout_psnr),
            "heldoutPsnrMean": float(np.mean(heldout_psnr)) if heldout_psnr else None,
            "heldoutSsimMean": float(np.mean(heldout_ssim)) if heldout_ssim else None,
            "views": appearance_views,
        },
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
            *(
                [
                    "This is a non-publishable diagnostic training output, not a world release or safety acceptance.",
                ]
                if source.non_publishable
                else []
            ),
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
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument("--world", type=Path, help="Published Servo world directory.")
    source.add_argument(
        "--diagnostic-training-output",
        type=Path,
        help=(
            "Explicitly non-publishable direct trainer output for an A/B path audit; "
            "it can never substitute for a published world."
        ),
    )
    result.add_argument("--output", required=True, type=Path, help="Directory for the audit MP4 and JSON.")
    result.add_argument("--width", type=int, default=640, help="Per-panel render width (default: 640).")
    result.add_argument("--frames-per-segment", type=int, default=2, help="Samples per source-camera segment.")
    result.add_argument("--fps", type=int, default=30, help="Encoded audit playback rate.")
    result.add_argument(
        "--save-sky-diagnostics",
        action="store_true",
        help=(
            "Save observed-sky alpha overlays for registered audit views whose "
            "resized sky-alpha p95 exceeds the diagnostic threshold."
        ),
    )
    result.add_argument(
        "--sky-diagnostic-p95-threshold",
        type=float,
        default=0.25,
        help="Flag a resized observed-sky audit view above this p95 alpha (default: 0.25).",
    )
    result.add_argument(
        "--reference-images",
        type=Path,
        help=(
            "Private undistorted image root used to verify exact-Ply PSNR/SSIM; "
            "the path is never written to the audit result."
        ),
    )
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
            arguments.reference_images,
            arguments.diagnostic_training_output,
            arguments.save_sky_diagnostics,
            arguments.sky_diagnostic_p95_threshold,
        )
    except AuditError as error:
        print(json.dumps({"event": "world_audit_failed", "error": str(error)}, separators=(",", ":")))
        return 1
    print(json.dumps({"event": "world_audit_complete", "metrics": value}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
