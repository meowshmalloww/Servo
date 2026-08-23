"""Observed-only directional environment evidence for Servo Gaussian worlds.

Finite 3D Gaussians are a poor representation for the sky: the same distant
direction is visible from many camera positions, while a finite splat can turn
into a floater when the camera translates.  This module builds a compact
equirectangular *directional* background from pixels independently labelled as
sky by Servo's pinned semantic stage.  It never inpaints, hallucinates, or
fills an unseen texel.  The RGBA alpha channel is therefore evidence coverage,
not opacity or a confidence calibrated for geometry.

The orientation is intentionally specified here instead of relying on a
renderer convention:

``u = atan2(world_direction.x, world_direction.z) / (2*pi) + 0.5``
``v = acos(clamp(world_direction.y, -1, 1)) / pi``

The same convention is consumed by the trainer, serialized-PLY audit, and
Vulkan viewer.  It maps the c2w camera's +Z forward axis to the middle of the
environment image and world +Y to its top edge.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence


ENVIRONMENT_SCHEMA = "servo.observed-directional-environment/v1"
ENVIRONMENT_METHOD = "oneformer-observed-sky-equirectangular-rgba-v1"
ENVIRONMENT_PROJECTION = "equirectangular-atan2-x-z-y-up-v1"
DEFAULT_WIDTH = 2048
DEFAULT_HEIGHT = 1024
DEFAULT_ASSET = "environment/observed-sky-equirectangular.png"


class EnvironmentError(RuntimeError):
    """An observed-directional environment is malformed or unsupported."""


@dataclass(frozen=True)
class ObservedDirectionalEnvironment:
    """A verified environment image and its immutable public descriptor."""

    descriptor: dict[str, Any]
    rgba: Any
    asset_path: Path


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _safe_relative_asset(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise EnvironmentError("Directional environment asset must be a relative string path.")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.name != value.split("/")[-1]:
        raise EnvironmentError("Directional environment asset path escapes its bundle.")
    if candidate.suffix.lower() != ".png":
        raise EnvironmentError("Directional environment evidence must be a PNG asset.")
    return candidate


def _resolve_asset(bundle_root: Path, asset: Any) -> Path:
    relative = _safe_relative_asset(asset)
    root = bundle_root.resolve()
    resolved = (root / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise EnvironmentError("Directional environment asset escapes its bundle.") from error
    return resolved


def _record_value(record: Any, name: str) -> Any:
    try:
        value = getattr(record, name)
    except AttributeError as error:
        raise EnvironmentError(f"Directional environment record lacks {name}.") from error
    return value


def _image_at(images_rgb: Sequence[Any] | Callable[[int], Any], index: int) -> Any:
    return images_rgb(index) if callable(images_rgb) else images_rgb[index]


def _validate_dimensions(width: int, height: int) -> None:
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width < 64
        or height < 32
        or width > 8192
        or height > 4096
        or width != height * 2
    ):
        raise EnvironmentError(
            "Directional environment dimensions must be finite 2:1 equirectangular "
            "dimensions within [64x32, 8192x4096]."
        )


def world_directions_for_camera(
    camera_to_world: Any,
    calibration: Any,
    width: int,
    height: int,
    *,
    device: str | None = None,
) -> Any:
    """Return normalized c2w world directions for pixel centres.

    This contains no depth.  Camera translation therefore cannot change a
    sample, which is the key distinction from a finite Gaussian sky.
    """

    import numpy as np

    if width <= 0 or height <= 0:
        raise EnvironmentError("Camera dimensions must be positive.")
    matrix = np.asarray(camera_to_world, dtype=np.float64)
    intrinsic = np.asarray(calibration, dtype=np.float64)
    if matrix.shape != (4, 4) or intrinsic.shape != (3, 3):
        raise EnvironmentError("Directional environment requires 4x4 c2w and 3x3 calibration.")
    if not np.isfinite(matrix).all() or not np.isfinite(intrinsic).all():
        raise EnvironmentError("Directional environment camera inputs must be finite.")
    fx, fy = float(intrinsic[0, 0]), float(intrinsic[1, 1])
    cx, cy = float(intrinsic[0, 2]), float(intrinsic[1, 2])
    if fx <= 0.0 or fy <= 0.0:
        raise EnvironmentError("Directional environment focal lengths must be positive.")
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    rays = np.stack(
        (
            (grid_x.astype(np.float64) + 0.5 - cx) / fx,
            (grid_y.astype(np.float64) + 0.5 - cy) / fy,
            np.ones((height, width), dtype=np.float64),
        ),
        axis=-1,
    )
    world = rays @ matrix[:3, :3].T
    lengths = np.linalg.norm(world, axis=-1, keepdims=True)
    if not np.isfinite(lengths).all() or np.any(lengths <= 1e-12):
        raise EnvironmentError("Directional environment camera rotation is degenerate.")
    world = (world / lengths).astype(np.float32)
    if device is None:
        return world
    import torch

    return torch.from_numpy(world).to(device)


def direction_to_equirectangular_texels(
    directions: Any,
    width: int,
    height: int,
) -> tuple[Any, Any]:
    """Map normalized world directions to nearest observed equirect texels."""

    import numpy as np

    _validate_dimensions(width, height)
    value = np.asarray(directions, dtype=np.float64)
    if value.ndim < 1 or value.shape[-1] != 3 or not np.isfinite(value).all():
        raise EnvironmentError("Directional environment samples require finite [...,3] directions.")
    lengths = np.linalg.norm(value, axis=-1)
    if np.any(lengths <= 1e-12):
        raise EnvironmentError("Directional environment samples contain a zero direction.")
    normalized = value / lengths[..., None]
    longitude = np.arctan2(normalized[..., 0], normalized[..., 2])
    u = np.mod(longitude / (2.0 * math.pi) + 0.5, 1.0)
    v = np.arccos(np.clip(normalized[..., 1], -1.0, 1.0)) / math.pi
    x = np.floor(u * width).astype(np.int64) % width
    y = np.minimum(np.floor(v * height).astype(np.int64), height - 1)
    return x, y


def build_observed_directional_environment(
    records: Sequence[Any],
    images_rgb: Sequence[Any] | Callable[[int], Any],
    semantics: Sequence[Any],
    output_root: Path,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    asset: str = DEFAULT_ASSET,
    sky_label: int = 17,
    maximum_samples_per_image: int = 250_000,
) -> dict[str, Any]:
    """Write a deterministic, observed-only RGBA directional background.

    RGB is an unweighted arithmetic mean of original sky samples assigned to a
    texel.  Alpha is exactly 255 for a texel with one or more observed samples
    and 0 otherwise.  Black RGB under alpha zero is storage padding, never an
    inferred sky colour.
    """

    import cv2
    import numpy as np

    _validate_dimensions(width, height)
    if (
        isinstance(sky_label, bool)
        or not isinstance(sky_label, int)
        or not 0 <= sky_label <= 255
    ):
        raise EnvironmentError("Directional environment sky label must be uint8-compatible.")
    if (
        isinstance(maximum_samples_per_image, bool)
        or not isinstance(maximum_samples_per_image, int)
        or maximum_samples_per_image <= 0
    ):
        raise EnvironmentError("Directional environment sample budget must be positive.")
    if len(records) != len(semantics):
        raise EnvironmentError("Directional environment records and semantics must cover every view.")
    if not callable(images_rgb) and len(images_rgb) != len(records):
        raise EnvironmentError("Directional environment records and RGB images must cover every view.")

    relative_asset = _safe_relative_asset(asset)
    sums = np.zeros((height * width, 3), dtype=np.float64)
    observations = np.zeros(height * width, dtype=np.uint32)
    source_sky_pixels = 0
    sampled_sky_pixels = 0
    images_with_sky = 0

    for index, (record, semantic_value) in enumerate(zip(records, semantics, strict=True)):
        rgb = np.asarray(_image_at(images_rgb, index))
        semantic = np.asarray(semantic_value)
        if (
            rgb.ndim != 3
            or rgb.shape[-1] != 3
            or rgb.shape[:2] != semantic.shape
            or semantic.ndim != 2
            or rgb.dtype != np.uint8
        ):
            raise EnvironmentError(
                "Directional environment RGB/semantic evidence must be matching HxWx3 uint8 and HxW arrays."
            )
        mask = semantic == sky_label
        source_count = int(np.count_nonzero(mask))
        source_sky_pixels += source_count
        if source_count == 0:
            continue
        images_with_sky += 1
        ys, xs = np.nonzero(mask)
        if source_count > maximum_samples_per_image:
            sampled = np.linspace(
                0, source_count - 1, maximum_samples_per_image, dtype=np.float64
            ).round().astype(np.int64)
            ys, xs = ys[sampled], xs[sampled]
        sampled_sky_pixels += len(xs)

        record_width = int(_record_value(record, "width"))
        record_height = int(_record_value(record, "height"))
        if record_width <= 0 or record_height <= 0:
            raise EnvironmentError("Directional environment record dimensions must be positive.")
        calibration = np.asarray(_record_value(record, "calibration"), dtype=np.float64)
        camera_to_world = np.asarray(_record_value(record, "camera_to_world"), dtype=np.float64)
        if calibration.shape != (3, 3) or camera_to_world.shape != (4, 4):
            raise EnvironmentError("Directional environment records require 3x3 calibration and 4x4 c2w.")
        if not np.isfinite(calibration).all() or not np.isfinite(camera_to_world).all():
            raise EnvironmentError("Directional environment record camera values must be finite.")
        fx, fy = calibration[0, 0], calibration[1, 1]
        if fx <= 0.0 or fy <= 0.0:
            raise EnvironmentError("Directional environment record focal lengths must be positive.")
        full_x = (xs.astype(np.float64) + 0.5) * record_width / semantic.shape[1] - 0.5
        full_y = (ys.astype(np.float64) + 0.5) * record_height / semantic.shape[0] - 0.5
        rays = np.column_stack(
            (
                (full_x - calibration[0, 2]) / fx,
                (full_y - calibration[1, 2]) / fy,
                np.ones(len(xs), dtype=np.float64),
            )
        )
        world = rays @ camera_to_world[:3, :3].T
        norms = np.linalg.norm(world, axis=1)
        valid = np.isfinite(world).all(axis=1) & np.isfinite(norms) & (norms > 1e-12)
        if not np.any(valid):
            continue
        world = world[valid] / norms[valid, None]
        texel_x, texel_y = direction_to_equirectangular_texels(world, width, height)
        flat = texel_y * width + texel_x
        colors = rgb[ys[valid], xs[valid]].astype(np.float64)
        np.add.at(sums, flat, colors)
        np.add.at(observations, flat, 1)

    covered = observations > 0
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    if np.any(covered):
        averaged = np.zeros_like(sums, dtype=np.float64)
        averaged[covered] = sums[covered] / observations[covered, None]
        rgba[..., :3] = np.clip(
            np.rint(averaged.reshape(height, width, 3)), 0.0, 255.0
        ).astype(np.uint8)
        rgba[..., 3] = covered.reshape(height, width).astype(np.uint8) * 255
    asset_path = _resolve_asset(output_root, relative_asset.as_posix())
    encoded, payload = cv2.imencode(
        ".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA), [cv2.IMWRITE_PNG_COMPRESSION, 9]
    )
    if not encoded:
        raise EnvironmentError("Unable to encode observed directional environment PNG.")
    _atomic_bytes(asset_path, payload.tobytes())
    asset_hash = sha256_file(asset_path)
    descriptor = {
        "schema": ENVIRONMENT_SCHEMA,
        "method": ENVIRONMENT_METHOD,
        "projection": ENVIRONMENT_PROJECTION,
        "asset": relative_asset.as_posix(),
        "assetSha256": asset_hash,
        "width": width,
        "height": height,
        "colorSpace": "srgb",
        "alphaMeaning": "one-or-more-observed-oneformer-sky-samples-per-texel",
        "aggregation": "deterministic-mean-observed-sky-rgb-per-texel-no-inpainting-v1",
        "sourceSkyLabel": sky_label,
        "sourceImages": len(records),
        "imagesWithSky": images_with_sky,
        "sourceSkyPixels": source_sky_pixels,
        "sampledSkyPixels": sampled_sky_pixels,
        "observedTexels": int(np.count_nonzero(covered)),
        "coverageFraction": float(np.mean(covered)),
        "containsGeneratedPixels": False,
        "finiteGeometry": False,
        "metric": False,
    }
    return descriptor


def load_observed_directional_environment(
    bundle_root: Path,
    descriptor: Any,
    *,
    device: str | None = None,
) -> ObservedDirectionalEnvironment:
    """Fail closed when a published directional background is not exact evidence."""

    import cv2
    import numpy as np

    if not isinstance(descriptor, dict):
        raise EnvironmentError("Directional environment descriptor must be an object.")
    if descriptor.get("schema") != ENVIRONMENT_SCHEMA:
        raise EnvironmentError("Directional environment schema is unsupported.")
    if descriptor.get("method") != ENVIRONMENT_METHOD:
        raise EnvironmentError("Directional environment method is unsupported.")
    if descriptor.get("projection") != ENVIRONMENT_PROJECTION:
        raise EnvironmentError("Directional environment projection is unsupported.")
    if descriptor.get("containsGeneratedPixels") is not False:
        raise EnvironmentError("Directional environment must explicitly contain no generated pixels.")
    width, height = descriptor.get("width"), descriptor.get("height")
    _validate_dimensions(width, height)
    asset_path = _resolve_asset(bundle_root, descriptor.get("asset"))
    expected_hash = descriptor.get("assetSha256")
    if not isinstance(expected_hash, str) or not expected_hash.startswith("sha256:"):
        raise EnvironmentError("Directional environment asset hash is missing.")
    if not asset_path.is_file() or sha256_file(asset_path) != expected_hash:
        raise EnvironmentError("Directional environment PNG hash does not match its descriptor.")
    bgr = cv2.imread(str(asset_path), cv2.IMREAD_UNCHANGED)
    if bgr is None or bgr.shape != (height, width, 4) or bgr.dtype != np.uint8:
        raise EnvironmentError("Directional environment PNG must be exact RGBA8 dimensions.")
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGRA2RGBA)
    alpha = rgba[..., 3]
    if np.any((alpha != 0) & (alpha != 255)):
        raise EnvironmentError("Directional environment alpha must be exact observed/unobserved coverage.")
    if np.any(rgba[alpha == 0, :3] != 0):
        raise EnvironmentError("Unobserved directional environment texels must contain zero RGB padding.")
    value: Any = rgba
    if device is not None:
        import torch

        value = torch.from_numpy(rgba.astype(np.float32) / 255.0).to(device)
    return ObservedDirectionalEnvironment(dict(descriptor), value, asset_path)


def sample_observed_directional_environment(
    environment: ObservedDirectionalEnvironment,
    world_directions: Any,
    fallback: Any,
) -> tuple[Any, Any]:
    """Nearest-sample evidence and return ``(RGB background, observed alpha)``.

    Nearest sampling avoids turning transparent, unseen texels into invented
    colour through a filter footprint.  The caller can render the fallback mean
    where coverage is zero, but the returned alpha remains available for a UI
    uncertainty display and audit.
    """

    import torch

    rgba = environment.rgba
    if not isinstance(rgba, torch.Tensor) or rgba.ndim != 3 or rgba.shape[-1] != 4:
        raise EnvironmentError("Directional environment must be loaded as an HxWx4 torch tensor.")
    directions = world_directions
    if not isinstance(directions, torch.Tensor) or directions.shape[-1] != 3:
        raise EnvironmentError("Directional environment sampling requires torch [...,3] directions.")
    if not torch.isfinite(directions).all():
        raise EnvironmentError("Directional environment sampling directions must be finite.")
    lengths = torch.linalg.vector_norm(directions, dim=-1, keepdim=True)
    if bool((lengths <= 1e-12).any()):
        raise EnvironmentError("Directional environment sampling directions contain zero vectors.")
    direction = directions / lengths
    width, height = int(rgba.shape[1]), int(rgba.shape[0])
    longitude = torch.atan2(direction[..., 0], direction[..., 2])
    u = torch.remainder(longitude / (2.0 * math.pi) + 0.5, 1.0)
    v = torch.acos(direction[..., 1].clamp(-1.0, 1.0)) / math.pi
    texel_x = torch.floor(u * width).to(torch.long).remainder(width)
    texel_y = torch.floor(v * height).to(torch.long).clamp(0, height - 1)
    sampled = rgba[texel_y, texel_x]
    if not isinstance(fallback, torch.Tensor) or fallback.shape[-1] != 3:
        raise EnvironmentError("Directional environment fallback must be a torch [...,3] tensor.")
    try:
        fallback_rgb = torch.broadcast_to(fallback, sampled[..., :3].shape)
    except RuntimeError as error:
        raise EnvironmentError("Directional environment fallback is not broadcast-compatible.") from error
    coverage = sampled[..., 3:4].clamp(0.0, 1.0)
    return sampled[..., :3] * coverage + fallback_rgb * (1.0 - coverage), coverage


def sample_observed_directional_environment_for_camera(
    environment: ObservedDirectionalEnvironment,
    camera_to_world: Any,
    calibration: Any,
    width: int,
    height: int,
    fallback: Any,
) -> tuple[Any, Any]:
    """Sample the environment at every pixel ray of one or more c2w cameras.

    The result is a background image shaped ``[camera,height,width,3]`` and a
    separate observed-coverage image.  It is deliberately a pure function of
    camera rotation/intrinsics: camera position is validated but unused for
    direction lookup, so translation cannot pull a distant sky into a finite
    reconstruction layer.
    """

    import torch

    _validate_dimensions(int(environment.rgba.shape[1]), int(environment.rgba.shape[0]))
    if width <= 0 or height <= 0:
        raise EnvironmentError("Directional environment render dimensions must be positive.")
    if not isinstance(camera_to_world, torch.Tensor) or not isinstance(calibration, torch.Tensor):
        raise EnvironmentError("Directional environment camera sampling requires torch tensors.")
    c2w = camera_to_world
    intrinsic = calibration
    if c2w.ndim == 2:
        c2w = c2w.unsqueeze(0)
    if intrinsic.ndim == 2:
        intrinsic = intrinsic.unsqueeze(0)
    if c2w.ndim != 3 or c2w.shape[1:] != (4, 4):
        raise EnvironmentError("Directional environment c2w must be [camera,4,4].")
    if intrinsic.ndim != 3 or intrinsic.shape != (c2w.shape[0], 3, 3):
        raise EnvironmentError("Directional environment calibration must be [camera,3,3].")
    if not torch.isfinite(c2w).all() or not torch.isfinite(intrinsic).all():
        raise EnvironmentError("Directional environment camera tensors must be finite.")
    device = environment.rgba.device
    dtype = torch.float32
    c2w = c2w.to(device=device, dtype=dtype)
    intrinsic = intrinsic.to(device=device, dtype=dtype)
    camera_count = int(c2w.shape[0])
    fx = intrinsic[:, 0, 0]
    fy = intrinsic[:, 1, 1]
    if bool((fx <= 0.0).any()) or bool((fy <= 0.0).any()):
        raise EnvironmentError("Directional environment camera focal lengths must be positive.")
    grid_y, grid_x = torch.meshgrid(
        torch.arange(height, device=device, dtype=dtype),
        torch.arange(width, device=device, dtype=dtype),
        indexing="ij",
    )
    rays = torch.stack(
        (
            (grid_x.unsqueeze(0) + 0.5 - intrinsic[:, 0, 2, None, None])
            / fx[:, None, None],
            (grid_y.unsqueeze(0) + 0.5 - intrinsic[:, 1, 2, None, None])
            / fy[:, None, None],
            torch.ones((camera_count, height, width), device=device, dtype=dtype),
        ),
        dim=-1,
    )
    # ``torch.matmul`` broadcasts every leading dimension.  Adding singleton
    # image dimensions to the per-camera rotation therefore creates a second
    # camera axis (``[C,C,H,W,3]``) instead of one direction per camera.  Use
    # an explicit per-camera contraction: world_direction = R @ camera_ray.
    directions = torch.einsum("chwi,cji->chwj", rays, c2w[:, :3, :3])
    if tuple(directions.shape) != (camera_count, height, width, 3):
        raise EnvironmentError("Directional environment camera rays have an invalid shape.")
    if not isinstance(fallback, torch.Tensor):
        raise EnvironmentError("Directional environment fallback must be a torch tensor.")
    fallback = fallback.to(device=device, dtype=dtype)
    if fallback.shape == (3,):
        fallback = fallback.view(1, 1, 1, 3)
    elif fallback.shape == (camera_count, 3):
        fallback = fallback[:, None, None, :]
    elif fallback.shape != (camera_count, height, width, 3):
        raise EnvironmentError("Directional environment fallback has unsupported camera/image shape.")
    return sample_observed_directional_environment(environment, directions, fallback)
