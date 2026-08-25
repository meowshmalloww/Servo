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


AUDIT_SCHEMA = "servo.gaussian-path-audit/v4"
DIAGNOSTIC_PROVENANCE_SCHEMA = "servo.diagnostic-training-provenance/v1"
SKY_DIAGNOSTIC_SCHEMA = "servo.sky-leakage-diagnostic/v1"
SEMANTIC_SKY_LABEL = 17
SEMANTIC_ROAD_LABELS = frozenset({1, 2, 5})
SEMANTIC_ROAD_MARKING_LABELS = frozenset({2})
SEMANTIC_ROAD_BOUNDARY_LABELS = frozenset({3, 4, 10})
SEMANTIC_ROADSIDE_SIGN_LABELS = frozenset({12, 13, 14, 15})


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


def load_semantic_labels(
    geometry_root: Path,
    image_name: str,
    width: int,
    height: int,
) -> np.ndarray | None:
    """Load observed Servo semantic evidence for one registered camera.

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
    return labels.astype(np.uint8, copy=False)


def load_semantic_sky_mask(
    geometry_root: Path,
    image_name: str,
    width: int,
    height: int,
) -> np.ndarray | None:
    labels = load_semantic_labels(
        geometry_root,
        image_name,
        width,
        height,
    )
    return None if labels is None else labels == SEMANTIC_SKY_LABEL


def masked_detail_metrics(
    rendered_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> dict[str, float | int] | None:
    """Measure reference-relative detail without treating noise as correctness.

    Laplacian variance and gradient energy expose blur that PSNR/SSIM can hide,
    but either can also be inflated by ringing, floaters, or sensor noise.  The
    ratios are therefore reported beside a gradient-similarity score and never
    used alone as a safety or geometry gate.
    """

    rendered = np.asarray(rendered_rgb, dtype=np.float32)
    reference = np.asarray(reference_rgb, dtype=np.float32)
    if rendered.shape != reference.shape or rendered.ndim != 3 or rendered.shape[2] != 3:
        raise AuditError("Detail metrics require matching RGB images.")
    if mask is None:
        selected = np.ones(rendered.shape[:2], dtype=bool)
    else:
        selected = np.asarray(mask, dtype=bool)
        if selected.shape != rendered.shape[:2]:
            raise AuditError("Detail-metric mask does not match the RGB image.")
        # Prevent the semantic-mask outline from dominating edge energy.
        if int(np.count_nonzero(selected)) >= 64:
            eroded = cv2.erode(selected.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            if int(np.count_nonzero(eroded)) >= 16:
                selected = eroded
    pixel_count = int(np.count_nonzero(selected))
    if pixel_count < 16:
        return None

    weights = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    rendered_y = np.sum(rendered * weights, axis=2)
    reference_y = np.sum(reference * weights, axis=2)
    rendered_laplacian = cv2.Laplacian(rendered_y, cv2.CV_32F, ksize=3)
    reference_laplacian = cv2.Laplacian(reference_y, cv2.CV_32F, ksize=3)
    rendered_dx = cv2.Sobel(rendered_y, cv2.CV_32F, 1, 0, ksize=3)
    rendered_dy = cv2.Sobel(rendered_y, cv2.CV_32F, 0, 1, ksize=3)
    reference_dx = cv2.Sobel(reference_y, cv2.CV_32F, 1, 0, ksize=3)
    reference_dy = cv2.Sobel(reference_y, cv2.CV_32F, 0, 1, ksize=3)
    rendered_gradient = np.hypot(rendered_dx, rendered_dy)
    reference_gradient = np.hypot(reference_dx, reference_dy)
    epsilon = 1.0e-8
    rendered_laplacian_variance = float(np.var(rendered_laplacian[selected]))
    reference_laplacian_variance = float(np.var(reference_laplacian[selected]))
    rendered_gradient_mean = float(np.mean(rendered_gradient[selected]))
    reference_gradient_mean = float(np.mean(reference_gradient[selected]))
    gradient_similarity = (
        2.0 * rendered_gradient[selected] * reference_gradient[selected] + 1.0e-4
    ) / (
        np.square(rendered_gradient[selected])
        + np.square(reference_gradient[selected])
        + 1.0e-4
    )
    squared_error = np.square(rendered[selected] - reference[selected])
    mse = float(np.mean(squared_error))
    return {
        "pixels": pixel_count,
        "maskedPsnr": float(-10.0 * math.log10(max(mse, 1.0e-12))),
        "laplacianVarianceRatio": rendered_laplacian_variance
        / max(reference_laplacian_variance, epsilon),
        "gradientEnergyRatio": rendered_gradient_mean
        / max(reference_gradient_mean, epsilon),
        "gradientSimilarityMean": float(np.mean(gradient_similarity)),
    }


def aggregate_detail_metrics(
    views: list[dict[str, float | int]],
) -> dict[str, Any]:
    if not views:
        return {"available": False, "views": 0, "pixels": 0}
    fields = (
        "maskedPsnr",
        "laplacianVarianceRatio",
        "gradientEnergyRatio",
        "gradientSimilarityMean",
    )
    result: dict[str, Any] = {
        "available": True,
        "views": len(views),
        "pixels": int(sum(int(view["pixels"]) for view in views)),
    }
    for field in fields:
        values = np.asarray([float(view[field]) for view in views], dtype=np.float64)
        result[field + "Mean"] = float(np.mean(values))
        result[field + "P10"] = float(np.percentile(values, 10))
        result[field + "P90"] = float(np.percentile(values, 90))
    return result


def _numeric_distribution(values: list[float]) -> dict[str, float | int | None]:
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=np.float64)
    if not finite.size:
        return {"count": 0, "minimum": None, "p10": None, "p50": None, "p90": None, "maximum": None}
    return {
        "count": int(finite.size),
        "minimum": float(np.min(finite)),
        "p10": float(np.percentile(finite, 10)),
        "p50": float(np.percentile(finite, 50)),
        "p90": float(np.percentile(finite, 90)),
        "maximum": float(np.max(finite)),
    }


def load_driving_evidence_summary(geometry_root: Path) -> dict[str, Any]:
    """Summarize sealed road/sign evidence without upgrading it to truth."""

    geometry_path = geometry_root / "geometry-metrics.json"
    road_path = geometry_root / "road-surface.json"
    sign_path = geometry_root / "sign-evidence.json"
    required = (geometry_path, road_path, sign_path)
    if not all(path.is_file() for path in required):
        return {
            "available": False,
            "status": "incomplete",
            "reason": "sealed-road-or-sign-evidence-unavailable",
        }
    geometry = read_json(geometry_path)
    road = read_json(road_path)
    sign = read_json(sign_path)
    if geometry.get("schema") != "servo.geometry-priors/v1":
        raise AuditError("Driving audit found an unsupported geometry-prior schema.")
    if road.get("schema") != "servo.road-surface/v1":
        raise AuditError("Driving audit found an unsupported road-surface schema.")
    if sign.get("schema") != "servo.sign-evidence/v1":
        raise AuditError("Driving audit found an unsupported sign-evidence schema.")

    semantics = geometry.get("semantics", {})
    road_paint = semantics.get("roadPaint", {}) if isinstance(semantics, dict) else {}
    temporal = semantics.get("temporalConsistency", {}) if isinstance(semantics, dict) else {}
    fit = road.get("fit", {})
    observed = road.get("observedSurface", {})
    surface = road.get("surface", {})
    elevations = [float(value) for value in surface.get("elevations", [])]
    banks = [float(value) for value in surface.get("banks", [])]
    tracks = sign.get("tracks", [])
    observations = sign.get("observations", [])
    verified_tracks = [
        track for track in tracks
        if isinstance(track, dict) and track.get("state") == "geometry-verified"
    ]
    atlas_heights: list[float] = []
    atlas_widths: list[float] = []
    atlas_valid: list[float] = []
    for track in verified_tracks:
        fusion = track.get("fusion")
        if not isinstance(fusion, dict):
            continue
        shape = fusion.get("shape")
        if isinstance(shape, list) and len(shape) >= 2:
            atlas_heights.append(float(shape[0]))
            atlas_widths.append(float(shape[1]))
        valid_fraction = fusion.get("validFraction")
        if isinstance(valid_fraction, (int, float)) and not isinstance(valid_fraction, bool):
            atlas_valid.append(float(valid_fraction))
    sharpness = [
        float(item["sharpness"])
        for item in observations
        if isinstance(item, dict)
        and item.get("state") == "geometry-verified"
        and isinstance(item.get("sharpness"), (int, float))
        and not isinstance(item.get("sharpness"), bool)
    ]
    text_verified = sum(
        isinstance(track, dict)
        and isinstance(track.get("text"), dict)
        and track["text"].get("state") == "cross-view-verified"
        for track in tracks
    )
    class_verified = sum(
        isinstance(track, dict)
        and isinstance(track.get("regulatoryClass"), dict)
        and track["regulatoryClass"].get("state") == "cross-view-verified"
        for track in tracks
    )
    group_iou = temporal.get("groupIoU", {}) if isinstance(temporal, dict) else {}
    road_fit_metric = road.get("metric") is True
    collision_validated = road.get("collisionValidated") is True
    return {
        "available": True,
        "status": "not-driving-ready",
        "artifacts": {
            "geometryMetricsSha256": sha256_file(geometry_path),
            "roadSurfaceSha256": sha256_file(road_path),
            "signEvidenceSha256": sha256_file(sign_path),
        },
        "roadSurfacePrior": {
            "sourceOnly": True,
            "metric": road_fit_metric,
            "collisionValidated": collision_validated,
            "scaleProvenance": road.get("scaleProvenance"),
            "inlierRatio": fit.get("inlierRatio"),
            "p95ResidualInSourceScale": fit.get("p95AbsoluteResidual"),
            "observedCellInlierRatio": observed.get("inlierRatio"),
            "observedCellP95ResidualInSourceScale": observed.get("p95AbsoluteResidual"),
            "blockedCells": observed.get("blockedCellCount"),
            "ambiguousCells": observed.get("ambiguousCellCount"),
            "elevationInSourceScale": _numeric_distribution(elevations),
            "crossSlope": _numeric_distribution(banks),
            "crossSlopeDegrees": _numeric_distribution(
                [math.degrees(math.atan(value)) for value in banks]
            ),
            "meaning": (
                "Piecewise source-depth prior preserving grade and bank. It is not a "
                "measurement of the serialized Gaussian surface and its units are not "
                "metres without a metric scale anchor."
            ),
        },
        "roadPaintEvidence": {
            "sourceOnly": True,
            "acceptedPixels": road_paint.get("acceptedPixels"),
            "proposalPixels": road_paint.get("proposalPixels"),
            "acceptedFractionOfProposals": road_paint.get("acceptedFractionOfProposals"),
            "whitePixels": road_paint.get("whitePixels"),
            "yellowPixels": road_paint.get("yellowPixels"),
            "suppressedFrames": road_paint.get("suppressedFrames"),
            "roadTemporalIoU": group_iou.get("road") if isinstance(group_iou, dict) else None,
            "boundaryTemporalIoU": group_iou.get("boundary") if isinstance(group_iou, dict) else None,
            "meaning": (
                "Repeated observed source-image paint evidence; it does not prove that "
                "the Gaussian render preserves the marking or its metric lane position."
            ),
        },
        "signEvidence": {
            "broadObservations": len(observations),
            "tracks": len(tracks),
            "geometryVerifiedTracks": len(verified_tracks),
            "textVerifiedTracks": int(text_verified),
            "regulatoryClassVerifiedTracks": int(class_verified),
            "atlasHeightPixels": _numeric_distribution(atlas_heights),
            "atlasWidthPixels": _numeric_distribution(atlas_widths),
            "atlasValidFraction": _numeric_distribution(atlas_valid),
            "verifiedObservationSharpness": _numeric_distribution(sharpness),
            "passesLegibilityGate": bool(verified_tracks) and text_verified == len(verified_tracks),
            "meaning": (
                "Geometry-verified means a repeated planar candidate, not a recognized "
                "traffic sign. Source-illegible text remains unknown and is never invented."
            ),
        },
    }


def navigation_stress_poses(
    cameras: list[dict[str, Any]], anchor_count: int = 9
) -> tuple[list[int], float, list[dict[str, Any]]]:
    """Build scale-honest off-path poses without making metric lane claims."""

    if len(cameras) < 2:
        raise AuditError("Navigation stress requires at least two cameras.")
    steps = np.asarray(
        [
            np.linalg.norm(right["c2w"][:3, 3] - left["c2w"][:3, 3])
            for left, right in zip(cameras[:-1], cameras[1:])
        ],
        dtype=np.float64,
    )
    positive = steps[np.isfinite(steps) & (steps > 1e-8)]
    if not positive.size:
        raise AuditError("Navigation stress cannot derive a positive camera baseline.")
    baseline = float(np.median(positive))
    count = min(max(2, anchor_count), len(cameras))
    anchors = [
        int(value)
        for value in sorted(
            set(np.linspace(0, len(cameras) - 1, count).round().astype(int))
        )
    ]

    def rotation(yaw_degrees: float = 0.0, pitch_degrees: float = 0.0) -> np.ndarray:
        yaw = math.radians(yaw_degrees)
        pitch = math.radians(pitch_degrees)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        yaw_matrix = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
        pitch_matrix = np.asarray([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
        return yaw_matrix @ pitch_matrix

    definitions = (
        ("lateral-left-1x", -1.0, 0.0, 0.0),
        ("lateral-right-1x", 1.0, 0.0, 0.0),
        ("lateral-left-2x", -2.0, 0.0, 0.0),
        ("lateral-right-2x", 2.0, 0.0, 0.0),
        ("yaw-left-5deg", 0.0, -5.0, 0.0),
        ("yaw-right-5deg", 0.0, 5.0, 0.0),
        ("pitch-up-3deg", 0.0, 0.0, -3.0),
        ("pitch-down-3deg", 0.0, 0.0, 3.0),
        ("left-1x-yaw-left-5deg", -1.0, -5.0, 0.0),
        ("right-1x-yaw-right-5deg", 1.0, 5.0, 0.0),
    )
    cases: list[dict[str, Any]] = []
    for anchor in anchors:
        base = cameras[anchor]["c2w"]
        for name, lateral, yaw, pitch in definitions:
            pose = base.copy()
            pose[:3, 3] += base[:3, 0] * (lateral * baseline)
            pose[:3, :3] = base[:3, :3] @ rotation(yaw, pitch)
            cases.append(
                {
                    "anchor": anchor,
                    "case": name,
                    "group": (
                        "combined"
                        if lateral and (yaw or pitch)
                        else "lateral"
                        if lateral
                        else "rotation"
                    ),
                    "lateralBaselineMultiples": lateral,
                    "yawDegrees": yaw,
                    "pitchDegrees": pitch,
                    "c2w": pose,
                }
            )
    return anchors, baseline, cases


def aggregate_navigation_stress(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"samples": 0}
    return {
        "samples": len(samples),
        "supportMean": float(np.mean([sample["support"] for sample in samples])),
        "supportMinimum": float(np.min([sample["support"] for sample in samples])),
        "lowerHalfSupportMean": float(
            np.mean([sample["lowerHalfSupport"] for sample in samples])
        ),
        "lowerHalfSupportMinimum": float(
            np.min([sample["lowerHalfSupport"] for sample in samples])
        ),
        "depthAmbiguityP50Mean": float(
            np.mean([sample["depthAmbiguityP50"] for sample in samples])
        ),
        "depthAmbiguityP95Maximum": float(
            np.max([sample["depthAmbiguityP95"] for sample in samples])
        ),
    }


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
    from servo_train import (
        composite_raster_background,
        directional_raster_background,
        ssim,
    )

    from servo_gsplat_runtime import prepare_gsplat_runtime

    prepare_gsplat_runtime()
    from gsplat.rendering import rasterization

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
    support_thresholds = (0.10, 0.25, 0.50, 0.75)
    support_curves: dict[float, list[float]] = {
        threshold: [] for threshold in support_thresholds
    }
    lower_support_curves: dict[float, list[float]] = {
        threshold: [] for threshold in support_thresholds
    }
    environment_coverage_values: list[float] = []
    ambiguity_samples: list[np.ndarray] = []
    sky_diagnostics: list[dict[str, Any]] = []
    sky_diagnostic_directory = output / "sky-leakage-diagnostics"
    registered_psnr: list[float] = []
    registered_ssim: list[float] = []
    heldout_psnr: list[float] = []
    heldout_ssim: list[float] = []
    appearance_views: list[dict[str, Any]] = []
    detail_views: list[dict[str, float | int]] = []
    road_detail_views: list[dict[str, float | int]] = []
    road_marking_detail_views: list[dict[str, float | int]] = []
    road_boundary_detail_views: list[dict[str, float | int]] = []
    roadside_sign_detail_views: list[dict[str, float | int]] = []
    camera_steps: list[float] = []
    for left, right in zip(cameras[:-1], cameras[1:]):
        camera_steps.append(float(np.linalg.norm(right["c2w"][:3, 3] - left["c2w"][:3, 3])))

    def render_stress_pose(
        c2w_np: np.ndarray, calibration_np: np.ndarray
    ) -> dict[str, Any]:
        """Render geometry signals for a navigation stress pose."""

        scaled_calibration = calibration_np.copy()
        scaled_calibration[0, :] *= scale_x
        scaled_calibration[1, :] *= scale_y
        c2w = torch.from_numpy(c2w_np.astype(np.float32))[None].to(device)
        viewmat = torch.linalg.inv(c2w)
        calibration = torch.from_numpy(scaled_calibration.astype(np.float32))[None].to(device)
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
            backgrounds=None,
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
        alpha_np = alpha[0, :, :, 0].clamp(0.0, 1.0).cpu().numpy()
        depth = rgb_depth[0, :, :, 3].cpu().numpy()
        moment2 = second_moment[0, :, :, 0].cpu().numpy() / np.maximum(alpha_np, 1e-6)
        relative_std = np.sqrt(np.maximum(moment2 - depth * depth, 0.0)) / np.maximum(
            depth, 1e-4
        )
        valid = (
            np.isfinite(relative_std)
            & np.isfinite(depth)
            & (depth > 0.0)
            & (alpha_np >= 0.5)
        )
        ambiguity = relative_std[valid]
        return {
            "rgb": rgb_depth[0, :, :, :3].clamp(0.0, 1.0).cpu().numpy(),
            "alpha": alpha_np,
            "support": float(np.mean(alpha_np >= 0.5)),
            "lowerHalfSupport": float(np.mean(alpha_np[height // 2 :, :] >= 0.5)),
            "depthAmbiguityP50": float(np.percentile(ambiguity, 50))
            if ambiguity.size
            else 1.0,
            "depthAmbiguityP95": float(np.percentile(ambiguity, 95))
            if ambiguity.size
            else 1.0,
        }

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
                rgb = rendered_rgb.cpu().numpy()
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
                    detail = masked_detail_metrics(rgb, reference_np)
                    if detail is not None:
                        detail_views.append(detail)
                    labels = load_semantic_labels(
                        source.environment_root,
                        reference_name,
                        width,
                        height,
                    )
                    region_detail: dict[str, dict[str, float | int]] = {}
                    if labels is not None:
                        for name, identifiers, destination in (
                            ("road", SEMANTIC_ROAD_LABELS, road_detail_views),
                            (
                                "roadMarking",
                                SEMANTIC_ROAD_MARKING_LABELS,
                                road_marking_detail_views,
                            ),
                            (
                                "roadBoundary",
                                SEMANTIC_ROAD_BOUNDARY_LABELS,
                                road_boundary_detail_views,
                            ),
                            (
                                "roadsideSign",
                                SEMANTIC_ROADSIDE_SIGN_LABELS,
                                roadside_sign_detail_views,
                            ),
                        ):
                            region = masked_detail_metrics(
                                rgb,
                                reference_np,
                                np.isin(labels, tuple(identifiers)),
                            )
                            if region is not None:
                                destination.append(region)
                                region_detail[name] = region
                    appearance_views.append(
                        {
                            "image": reference_name,
                            "heldout": is_validation,
                            "psnr": psnr_value,
                            "ssim": ssim_value,
                            "detail": detail,
                            "drivingRegions": region_detail,
                        }
                    )
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
                for threshold in support_thresholds:
                    support_curves[threshold].append(
                        float(np.mean(alpha_np >= threshold))
                    )
                    lower_support_curves[threshold].append(
                        float(np.mean(alpha_np[height // 2 :, :] >= threshold))
                    )
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

    path_elapsed = time.perf_counter() - started
    stress_started = time.perf_counter()
    anchors, stress_baseline, stress_cases = navigation_stress_poses(cameras)
    baseline_renders: dict[int, dict[str, Any]] = {}
    reverse_max_rgb_difference = 0.0
    reverse_max_alpha_difference = 0.0
    stress_samples: list[dict[str, Any]] = []
    micro_motion_alpha_deltas: list[float] = []
    with torch.inference_mode():
        for anchor in anchors:
            camera = cameras[anchor]
            baseline_renders[anchor] = render_stress_pose(
                camera["c2w"], camera["calibration"]
            )
        for anchor in reversed(anchors):
            camera = cameras[anchor]
            reverse = render_stress_pose(camera["c2w"], camera["calibration"])
            forward = baseline_renders[anchor]
            reverse_max_rgb_difference = max(
                reverse_max_rgb_difference,
                float(np.max(np.abs(reverse["rgb"] - forward["rgb"]))),
            )
            reverse_max_alpha_difference = max(
                reverse_max_alpha_difference,
                float(np.max(np.abs(reverse["alpha"] - forward["alpha"]))),
            )
        for case in stress_cases:
            camera = cameras[int(case["anchor"])]
            rendered = render_stress_pose(case["c2w"], camera["calibration"])
            stress_samples.append(
                {
                    key: value
                    for key, value in {**case, **rendered}.items()
                    if key not in {"c2w", "rgb", "alpha"}
                }
            )
        for anchor in anchors:
            camera = cameras[anchor]
            left = camera["c2w"].copy()
            right = camera["c2w"].copy()
            delta = camera["c2w"][:3, 0] * (0.25 * stress_baseline)
            left[:3, 3] -= delta
            right[:3, 3] += delta
            left_render = render_stress_pose(left, camera["calibration"])
            right_render = render_stress_pose(right, camera["calibration"])
            micro_motion_alpha_deltas.append(
                float(np.mean(np.abs(left_render["alpha"] - right_render["alpha"])))
            )
    torch.cuda.synchronize()
    stress_elapsed = time.perf_counter() - stress_started
    grouped_stress = {
        group: aggregate_navigation_stress(
            [sample for sample in stress_samples if sample["group"] == group]
        )
        for group in ("lateral", "rotation", "combined")
    }
    navigation_stress = {
        "status": "measured-diagnostic-not-ground-truth",
        "observedForward": {"measured": True, "groundTruth": "registered-views-only"},
        "observedReverse": {
            "measured": True,
            "maximumAbsoluteRgbDifference": reverse_max_rgb_difference,
            "maximumAbsoluteAlphaDifference": reverse_max_alpha_difference,
            "meaning": "Stateless reverse-order determinism only; it does not validate geometry.",
        },
        "midpointInterpolation": {
            "measured": frames_per_segment > 1,
            "groundTruth": False,
        },
        "lateralOffsets": {"measured": True, "metricLaneChange": False, **grouped_stress["lateral"]},
        "yawPitchPerturbations": {"measured": True, "groundTruth": False, **grouped_stress["rotation"]},
        "combinedTranslationRotation": {"measured": True, "groundTruth": False, **grouped_stress["combined"]},
        "temporalPopping": {
            "measured": True,
            "method": "symmetric-quarter-baseline-alpha-discontinuity-proxy/v1",
            "meanAbsoluteAlphaDeltaMean": float(np.mean(micro_motion_alpha_deltas)),
            "meanAbsoluteAlphaDeltaMaximum": float(np.max(micro_motion_alpha_deltas)),
            "meaning": "Coverage discontinuity under tiny camera motion; not flow-warped RGB correctness.",
        },
        "anchors": len(anchors),
        "baseline": {
            "normalizedCameraStepMedian": stress_baseline,
            "metric": False,
        },
        "samples": stress_samples,
        "elapsedSeconds": stress_elapsed,
        "unobservedSpace": {"validated": False, "policy": "unknown-not-free-space"},
    }
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
            "elapsedSeconds": path_elapsed,
            "offlineFramesPerSecond": len(path_cameras) / max(path_elapsed, 1e-9),
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
        "detailPreservation": {
            "meaning": (
                "Reference-relative luminance detail at exact registered cameras. "
                "Laplacian and gradient ratios below one can expose blur; values above "
                "one can be false detail from noise, ringing, or floaters."
            ),
            "overall": aggregate_detail_metrics(detail_views),
            "road": aggregate_detail_metrics(road_detail_views),
            "roadMarking": aggregate_detail_metrics(road_marking_detail_views),
            "roadBoundary": aggregate_detail_metrics(road_boundary_detail_views),
            "roadsideSign": aggregate_detail_metrics(roadside_sign_detail_views),
        },
        "support": {
            "meaning": "Fraction of pixels whose composited splat alpha is at least 0.5; this is not geometry accuracy.",
            "overallMean": float(np.mean(support_values)),
            "overallMinimum": float(np.min(support_values)),
            "lowerHalfMean": float(np.mean(lower_support_values)),
            "lowerHalfMinimum": float(np.min(lower_support_values)),
            "centerMean": float(np.mean(center_support_values)),
            "centerMinimum": float(np.min(center_support_values)),
            "thresholdCurve": {
                f"alphaAtLeast{threshold:.2f}": {
                    "meaning": (
                        "Fraction of observed-path pixels above this accumulated "
                        "finite-Gaussian alpha threshold; not occupancy or geometry."
                    ),
                    "overallMean": float(np.mean(support_curves[threshold])),
                    "overallMinimum": float(np.min(support_curves[threshold])),
                    "lowerHalfMean": float(
                        np.mean(lower_support_curves[threshold])
                    ),
                    "lowerHalfMinimum": float(
                        np.min(lower_support_curves[threshold])
                    ),
                }
                for threshold in support_thresholds
            },
        },
        "depthAmbiguity": {
            "meaning": "Relative standard deviation of composited Gaussian camera-space depth; this detects mixed layers but is not ground-truth depth error.",
            "sampleCount": int(ambiguity.size),
            "relativeStdP50": float(np.percentile(ambiguity, 50)) if ambiguity.size else None,
            "relativeStdP95": float(np.percentile(ambiguity, 95)) if ambiguity.size else None,
            "fractionAboveFivePercent": float(np.mean(ambiguity > 0.05)) if ambiguity.size else None,
            "fractionAboveTenPercent": float(np.mean(ambiguity > 0.10)) if ambiguity.size else None,
        },
        "drivingEvidence": load_driving_evidence_summary(source.environment_root),
        "navigationStress": navigation_stress,
        "drivingReadiness": {
            "status": "not-ready",
            "collisionValidated": False,
            "metricScale": False,
            "completeNavigationStressSuite": False,
            "signLegibilityValidated": False,
            "roadSurfaceValidatedAgainstMetricGroundTruth": False,
            "reason": (
                "Observed-path appearance is only one acceptance dimension; sign "
                "legibility, metric road geometry, lateral/rotational extrapolation, "
                "and temporal popping are not all validated."
            ),
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
            "Off-path stress has no reference imagery and therefore measures stability/support, not correctness.",
            "Splat opacity support is not a collision surface or free-space certificate.",
            "Dynamic vegetation and other transient content can remain blurred or geometrically inconsistent.",
            "Road/sign priors describe source evidence and do not by themselves verify the serialized Gaussian render.",
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
