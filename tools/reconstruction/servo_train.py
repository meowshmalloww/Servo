#!/usr/bin/env python3
"""Servo's bounded, checkpointable gsplat 1.5.3 fidelity trainer.

This module follows the maintained Apache-2.0 gsplat training API while keeping
Servo's own data, checkpoint, cancellation, metric, and artifact contracts.
The fidelity representation uses antialiased anisotropic 3D Gaussians, AbsGS
detail-aware densification, a coarse-to-fine image schedule, and bounded
per-frame photometric compensation.  Pose optimization, learned depth, and
generated geometry remain separate evidence layers rather than being hidden in
the appearance artifact.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import gc
import hashlib
import json
import math
import os
import random
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterator, Sequence


TRAINER_VERSION = "0.3.0"
CONFIG_SCHEMA = "servo.gsplat-training/v2"
METRICS_SCHEMA = "servo.gsplat-metrics/v2"
CHECKPOINT_SCHEMA = "servo.gsplat-checkpoint/v2"
REPRESENTATION_TYPE = "servo-fidelity-3dgs-v1"
C0 = 0.28209479177387814
OPACITY_RESET_SEMANTICS = "servo-gsplat-1.5.3-fix-v2"


class TrainingError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def emit(event: str, **fields: Any) -> None:
    value = {
        "schema": "servo.gsplat-event/v1",
        "trainerVersion": TRAINER_VERSION,
        "opacityResetSemantics": OPACITY_RESET_SEMANTICS,
        "event": event,
        **fields,
    }
    print(canonical_json(value).decode("utf-8"), flush=True)


def set_determinism(seed: int = 42) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def should_reset_opacity(step: int, reset_every: int, refine_stop_iter: int) -> bool:
    return (
        step > 0
        and reset_every > 0
        and step < refine_stop_iter
        and step % reset_every == 0
    )


@dataclasses.dataclass(frozen=True)
class ImageRecord:
    name: str
    path: Path
    camera_id: int
    camera_model: str
    camera_to_world: Any
    calibration: Any
    width: int
    height: int


class ColmapDataset:
    def __init__(
        self,
        root: Path,
        factor: int,
        cache_size: int = 8,
        max_point_error: float = 3.0,
    ) -> None:
        import numpy as np
        import pycolmap

        self.root = root.resolve()
        self.factor = max(1, int(factor))
        self.image_root = self.root / "images"
        sparse_candidates = [self.root / "sparse", self.root / "sparse" / "0"]
        model_root = next(
            (candidate for candidate in sparse_candidates if candidate.is_dir() and any(candidate.glob("cameras.*"))),
            None,
        )
        if model_root is None:
            raise TrainingError(f"No COLMAP model was found beneath {self.root}.")
        reconstruction = pycolmap.Reconstruction(str(model_root))
        points = list(reconstruction.points3D.values())
        if len(points) < 100:
            raise TrainingError("The sparse reconstruction has too few 3D points to initialize Gaussians.")
        xyz = np.asarray([point.xyz for point in points], dtype=np.float32)
        rgb = np.asarray([point.color for point in points], dtype=np.float32)
        track_lengths = np.asarray([point.track.length() for point in points], dtype=np.int32)
        point_errors = np.asarray([point.error for point in points], dtype=np.float32)
        confidence = (
            np.isfinite(xyz).all(axis=1)
            & np.isfinite(rgb).all(axis=1)
            & np.isfinite(point_errors)
            & (track_lengths >= 3)
            & (point_errors <= max_point_error)
        )
        rejected_confidence = int(len(xyz) - int(confidence.sum()))
        xyz = xyz[confidence]
        rgb = rgb[confidence]
        if len(xyz) > 500_000:
            generator = np.random.default_rng(42)
            indices = np.sort(generator.choice(len(xyz), 500_000, replace=False))
            xyz = xyz[indices]
            rgb = rgb[indices]

        raw_records: list[tuple[str, Path, int, str, Any, Any, int, int]] = []
        camera_centers = []
        for image in sorted(reconstruction.images.values(), key=lambda item: item.name):
            if not image.has_pose:
                continue
            camera = reconstruction.cameras[image.camera_id]
            image_path = self.image_root / image.name
            if not image_path.is_file():
                continue
            world_from_camera = image.cam_from_world().inverse().matrix()
            matrix = np.eye(4, dtype=np.float32)
            matrix[:3, :4] = np.asarray(world_from_camera, dtype=np.float32)
            calibration = np.asarray(camera.calibration_matrix(), dtype=np.float32)
            raw_records.append(
                (
                    image.name,
                    image_path,
                    int(image.camera_id),
                    str(camera.model_name),
                    matrix,
                    calibration,
                    int(camera.width),
                    int(camera.height),
                )
            )
            camera_centers.append(matrix[:3, 3])
        if len(raw_records) < 4:
            raise TrainingError("Fewer than four registered images are available for Gaussian training.")

        centers = np.asarray(camera_centers, dtype=np.float32)
        center = np.median(centers, axis=0)
        distances = np.linalg.norm(centers - center[None, :], axis=1)
        extent = float(np.percentile(distances, 90))
        if not math.isfinite(extent) or extent <= 1e-8:
            raise TrainingError("The recovered camera trajectory has no usable spatial extent.")
        scale = 1.0 / extent
        point_radii = np.linalg.norm(xyz - center[None, :], axis=1)
        radius_p50 = float(np.percentile(point_radii, 50))
        radius_p95 = float(np.percentile(point_radii, 95))
        radius_p99 = float(np.percentile(point_radii, 99))
        # Camera motion is not a scene-size estimate.  A short-baseline capture
        # can legitimately observe walls tens of trajectory radii away, so use
        # the confidence-filtered sparse geometry to set the robust upper bound.
        scene_filter_radius = max(extent * 8.0, radius_p99 * 1.5)
        within_scene = point_radii <= scene_filter_radius
        rejected_bounds = int(len(xyz) - int(within_scene.sum()))
        xyz = xyz[within_scene]
        rgb = rgb[within_scene]
        if len(xyz) < 100:
            raise TrainingError(
                "Fewer than 100 reliable COLMAP points remain after confidence and scene-bound filtering."
            )
        retained_radii = np.linalg.norm(xyz - center[None, :], axis=1)
        reliable_scene_radius = max(
            extent,
            float(np.percentile(retained_radii, 99)),
        )
        reliable_scene_radius_normalized = reliable_scene_radius * scale
        cleanup_radius_limit = max(10.0, reliable_scene_radius_normalized * 1.5)
        cleanup_scale_limit = max(2.0, reliable_scene_radius_normalized * 0.10)
        colmap_to_normalized = np.eye(4, dtype=np.float32)
        colmap_to_normalized[:3, :3] *= scale
        colmap_to_normalized[:3, 3] = -center * scale
        normalized_to_colmap = np.eye(4, dtype=np.float32)
        normalized_to_colmap[:3, :3] /= scale
        normalized_to_colmap[:3, 3] = center
        self.normalization = {
            "center": center.tolist(),
            "scale": scale,
            "method": "median-camera-center/p90-radius",
            "cameraExtent": extent,
            "sparsePointRadiusP50": radius_p50,
            "sparsePointRadiusP95": radius_p95,
            "sparsePointRadiusP99": radius_p99,
            "sceneFilterRadius": scene_filter_radius,
            "reliableSceneRadius": reliable_scene_radius,
            "reliableSceneRadiusNormalized": reliable_scene_radius_normalized,
            "cleanupRadiusLimitNormalized": cleanup_radius_limit,
            "cleanupScaleLimitNormalized": cleanup_scale_limit,
            "colmapToNormalized": colmap_to_normalized.tolist(),
            "normalizedToColmap": normalized_to_colmap.tolist(),
        }
        self.initialization_stats = {
            "inputPoints": len(points),
            "rejectedConfidence": rejected_confidence,
            "rejectedSceneBounds": rejected_bounds,
            "retainedPoints": int(len(xyz)),
            "minimumTrackLength": 3,
            "maximumReprojectionError": max_point_error,
            "sceneFilterRadius": scene_filter_radius,
            "reliableSceneRadius": reliable_scene_radius,
        }
        xyz = (xyz - center[None, :]) * scale
        self.points = xyz.astype(np.float32, copy=False)
        self.colors = (rgb / 255.0).clip(0.0, 1.0).astype(np.float32, copy=False)

        self.records: list[ImageRecord] = []
        for (
            name,
            image_path,
            camera_id,
            camera_model,
            matrix,
            calibration,
            width,
            height,
        ) in raw_records:
            matrix = matrix.copy()
            matrix[:3, 3] = (matrix[:3, 3] - center) * scale
            calibration = calibration.copy()
            scaled_width = max(1, round(width / self.factor))
            scaled_height = max(1, round(height / self.factor))
            calibration[0, :] *= scaled_width / width
            calibration[1, :] *= scaled_height / height
            self.records.append(
                ImageRecord(
                    name=name,
                    path=image_path,
                    camera_id=camera_id,
                    camera_model=camera_model,
                    camera_to_world=matrix,
                    calibration=calibration,
                    width=scaled_width,
                    height=scaled_height,
                )
            )
        grouped: dict[str, list[int]] = collections.defaultdict(list)
        for index, record in enumerate(self.records):
            grouped[Path(record.name).parent.as_posix()].append(index)
        self.validation_indices: set[int] = set()
        static_indices: list[int] = []
        for group, indices in sorted(grouped.items()):
            if Path(group).name.startswith("video-") and len(indices) >= 5:
                count = max(1, min(len(indices) - 2, round(len(indices) * 0.10)))
                start = min(len(indices) - count - 1, max(1, round(len(indices) * 0.70)))
                self.validation_indices.update(indices[start : start + count])
            else:
                static_indices.extend(indices)
        self.validation_indices.update(
            index for ordinal, index in enumerate(static_indices) if ordinal % 8 == 4
        )
        if not self.validation_indices:
            self.validation_indices = {len(self.records) - 1}
        self.validation_policy = "temporal-blocks-per-video/isolated-stratified-stills-v1"
        self.train_indices = [
            index for index in range(len(self.records)) if index not in self.validation_indices
        ]
        self._cache: collections.OrderedDict[int, Any] = collections.OrderedDict()
        self._cache_size = max(1, cache_size)

    def __len__(self) -> int:
        return len(self.records)

    def load(self, index: int) -> tuple[Any, Any, Any]:
        import numpy as np
        import torch
        from PIL import Image, ImageOps

        cached = self._cache.pop(index, None)
        if cached is None:
            record = self.records[index]
            with Image.open(record.path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                if self.factor > 1:
                    target = (
                        max(1, round(image.width / self.factor)),
                        max(1, round(image.height / self.factor)),
                    )
                    image = image.resize(target, Image.Resampling.LANCZOS)
                pixels = np.asarray(image, dtype=np.uint8).copy()
            cached = torch.from_numpy(pixels)
        self._cache[index] = cached
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        record = self.records[index]
        return (
            cached,
            torch.from_numpy(record.camera_to_world.copy()),
            torch.from_numpy(record.calibration.copy()),
        )


def nearest_scales(points: Any) -> Any:
    import numpy as np
    from scipy.spatial import cKDTree

    tree = cKDTree(points)
    distances, _ = tree.query(points, k=min(4, len(points)), workers=-1)
    if distances.ndim == 1:
        distances = distances[:, None]
    neighbors = distances[:, 1:] if distances.shape[1] > 1 else distances
    mean_distance = np.sqrt(np.maximum(np.mean(neighbors**2, axis=1), 1e-12))
    return np.log(mean_distance).astype(np.float32)


def create_parameters(dataset: ColmapDataset, sh_degree: int, device: str) -> Any:
    import torch

    points = torch.from_numpy(dataset.points)
    colors = torch.from_numpy(dataset.colors)
    scales = torch.from_numpy(nearest_scales(dataset.points)).unsqueeze(-1).repeat(1, 3)
    count = len(points)
    quaternions = torch.zeros((count, 4), dtype=torch.float32)
    quaternions[:, 0] = 1.0
    opacities = torch.logit(torch.full((count,), 0.1, dtype=torch.float32))
    coefficients = torch.zeros((count, (sh_degree + 1) ** 2, 3), dtype=torch.float32)
    coefficients[:, 0, :] = (colors - 0.5) / C0
    return torch.nn.ParameterDict(
        {
            "means": torch.nn.Parameter(points),
            "scales": torch.nn.Parameter(scales),
            "quats": torch.nn.Parameter(quaternions),
            "opacities": torch.nn.Parameter(opacities),
            "sh0": torch.nn.Parameter(coefficients[:, :1, :]),
            "shN": torch.nn.Parameter(coefficients[:, 1:, :]),
        }
    ).to(device)


def parameters_from_state(state: dict[str, Any], device: str) -> Any:
    import torch

    required = {"means", "scales", "quats", "opacities", "sh0", "shN"}
    missing = required.difference(state)
    if missing:
        raise TrainingError("Checkpoint is missing Gaussian tensors: " + ", ".join(sorted(missing)))
    return torch.nn.ParameterDict(
        {name: torch.nn.Parameter(state[name].to(device=device, dtype=torch.float32)) for name in sorted(required)}
    )


def create_optimizers(
    parameters: Any,
    scene_scale: float = 1.0,
    learning_rate_scale: float = 1.0,
) -> dict[str, Any]:
    import torch

    rates = {
        "means": 1.6e-4 * scene_scale,
        "scales": 5e-3,
        "quats": 1e-3,
        "opacities": 5e-2,
        "sh0": 2.5e-3,
        "shN": 2.5e-3 / 20.0,
    }
    return {
        name: torch.optim.Adam(
            [
                {
                    "params": parameters[name],
                    "lr": rates[name] * learning_rate_scale,
                    "name": name,
                }
            ],
            eps=1e-15,
            betas=(0.9, 0.999),
        )
        for name in rates
    }


def create_appearance_parameters(count: int, device: str) -> Any:
    """Create a bounded canonical-to-capture color transform per input view.

    Log-gain plus bias is intentionally smaller and more identifiable than a
    free 3x4 color matrix.  The exported splat remains the canonical scene;
    these nuisance parameters only prevent auto exposure/white balance changes
    from being baked into geometry and spherical harmonics.
    """
    import torch

    return torch.nn.ParameterDict(
        {
            "logGains": torch.nn.Parameter(torch.zeros((count, 3))),
            "biases": torch.nn.Parameter(torch.zeros((count, 3))),
        }
    ).to(device)


def appearance_from_state(state: dict[str, Any], count: int, device: str) -> Any:
    import torch

    required = {"logGains", "biases"}
    if set(state) != required:
        raise TrainingError("Checkpoint appearance tensors use an incompatible schema.")
    if tuple(state["logGains"].shape) != (count, 3) or tuple(state["biases"].shape) != (count, 3):
        raise TrainingError("Checkpoint appearance tensors do not match the camera set.")
    return torch.nn.ParameterDict(
        {
            name: torch.nn.Parameter(state[name].to(device=device, dtype=torch.float32))
            for name in sorted(required)
        }
    )


def create_appearance_optimizer(appearance: Any, learning_rate: float) -> Any:
    import torch

    return torch.optim.Adam(
        [
            {"params": appearance["logGains"], "lr": learning_rate, "name": "logGains"},
            {"params": appearance["biases"], "lr": learning_rate, "name": "biases"},
        ],
        eps=1e-15,
        betas=(0.9, 0.999),
    )


def apply_appearance(image: Any, appearance: Any | None, image_index: int) -> Any:
    import torch

    if appearance is None:
        return image
    gain = torch.exp(appearance["logGains"][image_index]).view(1, 1, 1, 3)
    bias = appearance["biases"][image_index].view(1, 1, 1, 3)
    return image * gain + bias


def clamp_appearance(appearance: Any | None) -> None:
    if appearance is None:
        return
    import torch

    with torch.no_grad():
        # At most one stop of gain and a conservative channel bias.  Captures
        # outside this range need explicit HDR/ISP handling, not an unconstrained
        # nuisance model that can conceal reconstruction errors.
        appearance["logGains"].data.clamp_(-math.log(2.0), math.log(2.0))
        appearance["biases"].data.clamp_(-0.25, 0.25)


def appearance_regularization(appearance: Any | None, image_index: int) -> Any:
    if appearance is None:
        return 0.0
    return (
        appearance["logGains"][image_index].square().mean()
        + 4.0 * appearance["biases"][image_index].square().mean()
    )


def appearance_metrics(
    appearance: Any | None,
    indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    if appearance is None:
        return {"mode": "disabled"}
    import numpy as np
    import torch

    with torch.no_grad():
        gains = torch.exp(appearance["logGains"]).detach().cpu().numpy()
        biases = appearance["biases"].detach().cpu().numpy()
    if indices is not None:
        selected = list(indices)
        gains = gains[selected]
        biases = biases[selected]
    return {
        "mode": "per-frame-log-gain-bias-v1",
        "gainP05": float(np.percentile(gains, 5)),
        "gainMedian": float(np.median(gains)),
        "gainP95": float(np.percentile(gains, 95)),
        "maximumAbsoluteBias": float(np.abs(biases).max(initial=0.0)),
    }


def downscale_training_sample(
    pixels: Any,
    calibration: Any,
    factor: int,
) -> tuple[Any, Any]:
    """Area-downsample a BCHW-compatible sample and scale K exactly."""
    import torch.nn.functional as functional

    factor = max(1, int(factor))
    if factor == 1:
        return pixels, calibration
    height, width = pixels.shape[1:3]
    target_width = max(1, round(width / factor))
    target_height = max(1, round(height / factor))
    resized = functional.interpolate(
        pixels.permute(0, 3, 1, 2),
        size=(target_height, target_width),
        mode="area",
    ).permute(0, 2, 3, 1)
    scaled = calibration.clone()
    scaled[:, 0, :] *= target_width / width
    scaled[:, 1, :] *= target_height / height
    return resized, scaled


def gaussian_window(channels: int, device: Any, dtype: Any, size: int = 11, sigma: float = 1.5) -> Any:
    import torch

    coordinates = torch.arange(size, device=device, dtype=dtype) - size // 2
    kernel = torch.exp(-(coordinates**2) / (2.0 * sigma**2))
    kernel /= kernel.sum()
    window = (kernel[:, None] * kernel[None, :]).expand(channels, 1, size, size).contiguous()
    return window


def ssim(prediction: Any, target: Any) -> Any:
    import torch.nn.functional as functional

    channels = prediction.shape[1]
    window = gaussian_window(channels, prediction.device, prediction.dtype)
    padding = window.shape[-1] // 2
    mu_prediction = functional.conv2d(prediction, window, padding=padding, groups=channels)
    mu_target = functional.conv2d(target, window, padding=padding, groups=channels)
    mu_prediction_sq = mu_prediction.square()
    mu_target_sq = mu_target.square()
    mu_both = mu_prediction * mu_target
    sigma_prediction = functional.conv2d(prediction.square(), window, padding=padding, groups=channels) - mu_prediction_sq
    sigma_target = functional.conv2d(target.square(), window, padding=padding, groups=channels) - mu_target_sq
    sigma_both = functional.conv2d(prediction * target, window, padding=padding, groups=channels) - mu_both
    c1 = 0.01**2
    c2 = 0.03**2
    score = ((2 * mu_both + c1) * (2 * sigma_both + c2)) / (
        (mu_prediction_sq + mu_target_sq + c1) * (sigma_prediction + sigma_target + c2)
    )
    return score.mean()


def optimizer_state_to_device(optimizer: Any, device: str) -> None:
    import torch

    for state in optimizer.state.values():
        for key, value in state.items():
            if isinstance(value, torch.Tensor):
                state[key] = value.to(device)


def tree_to_device(value: Any, device: str) -> Any:
    import torch

    if isinstance(value, torch.Tensor):
        return value.to(device)
    if isinstance(value, dict):
        return {key: tree_to_device(item, device) for key, item in value.items()}
    if isinstance(value, list):
        return [tree_to_device(item, device) for item in value]
    if isinstance(value, tuple):
        return tuple(tree_to_device(item, device) for item in value)
    return value


def checkpoint_payload(
    step: int,
    parameters: Any,
    optimizers: dict[str, Any],
    scheduler: Any,
    strategy_state: dict[str, Any],
    policy_state: dict[str, Any],
    config: dict[str, Any],
    dataset: ColmapDataset,
    appearance: Any | None = None,
    appearance_optimizer: Any | None = None,
    appearance_scheduler: Any | None = None,
) -> dict[str, Any]:
    import numpy as np
    import torch

    numpy_state = np.random.get_state()

    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "trainerVersion": TRAINER_VERSION,
        "opacityResetSemantics": OPACITY_RESET_SEMANTICS,
        "pipelineRevision": config.get("pipelineRevision"),
        "step": step,
        "configurationHash": config["configurationHash"],
        "normalization": dataset.normalization,
        "splats": {name: value.detach().cpu() for name, value in parameters.items()},
        "optimizers": {name: optimizer.state_dict() for name, optimizer in optimizers.items()},
        "scheduler": scheduler.state_dict(),
        "strategyState": tree_to_device(strategy_state, "cpu"),
        "policyState": policy_state,
        "rng": {
            "python": random.getstate(),
            "numpy": {
                "bitGenerator": numpy_state[0],
                "keys": numpy_state[1].tolist(),
                "position": int(numpy_state[2]),
                "hasGauss": int(numpy_state[3]),
                "cachedGauss": float(numpy_state[4]),
            },
            "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all(),
        },
    }
    if appearance is not None:
        if appearance_optimizer is None or appearance_scheduler is None:
            raise TrainingError("Appearance checkpoint state is incomplete.")
        payload["appearance"] = {
            name: value.detach().cpu() for name, value in appearance.items()
        }
        payload["appearanceOptimizer"] = appearance_optimizer.state_dict()
        payload["appearanceScheduler"] = appearance_scheduler.state_dict()
    return payload


def tensor_payload_bytes(value: Any) -> int:
    import torch

    if isinstance(value, torch.Tensor):
        return int(value.numel() * value.element_size())
    if isinstance(value, Mapping):
        return sum(tensor_payload_bytes(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(tensor_payload_bytes(item) for item in value)
    return 0


def save_checkpoint(
    checkpoint_dir: Path,
    step: int,
    parameters: Any,
    optimizers: dict[str, Any],
    scheduler: Any,
    strategy_state: dict[str, Any],
    policy_state: dict[str, Any],
    config: dict[str, Any],
    dataset: ColmapDataset,
    appearance: Any | None = None,
    appearance_optimizer: Any | None = None,
    appearance_scheduler: Any | None = None,
) -> Path:
    import torch

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    estimated_payload_bytes = (
        tensor_payload_bytes(parameters)
        + sum(tensor_payload_bytes(optimizer.state_dict()) for optimizer in optimizers.values())
        + tensor_payload_bytes(strategy_state)
        + tensor_payload_bytes(appearance)
        + tensor_payload_bytes(
            appearance_optimizer.state_dict()
            if appearance_optimizer is not None
            else {}
        )
    )
    required_free_bytes = int(estimated_payload_bytes * 1.25) + 512 * 1024**2
    available_bytes = shutil.disk_usage(checkpoint_dir).free
    if available_bytes < required_free_bytes:
        raise TrainingError(
            "Not enough free storage for an atomic verified checkpoint: "
            f"{required_free_bytes} bytes required, {available_bytes} available."
        )
    path = checkpoint_dir / f"checkpoint-{step:08d}.pt"
    temporary = checkpoint_dir / f".{path.name}.{uuid.uuid4().hex}.tmp"
    payload = checkpoint_payload(
        step,
        parameters,
        optimizers,
        scheduler,
        strategy_state,
        policy_state,
        config,
        dataset,
        appearance,
        appearance_optimizer,
        appearance_scheduler,
    )
    try:
        with temporary.open("wb") as stream:
            torch.save(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        verification = torch.load(temporary, map_location="cpu", weights_only=True)
        if verification.get("schema") != CHECKPOINT_SCHEMA or verification.get("step") != step:
            raise TrainingError("Checkpoint verification failed.")
        if verification.get("configurationHash") != config["configurationHash"]:
            raise TrainingError("Checkpoint configuration hash changed during save.")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    digest = sha256_file(path)
    checkpoint_receipt = {
        "schema": "servo.gsplat-checkpoint-receipt/v1",
        "step": step,
        "path": path.name,
        "sha256": digest,
        "bytes": path.stat().st_size,
        "configurationHash": config["configurationHash"],
    }
    atomic_json(path.with_suffix(".json"), checkpoint_receipt)
    atomic_json(
        checkpoint_dir / "last-good.json",
        {
            "schema": "servo.gsplat-last-good/v1",
            **{key: value for key, value in checkpoint_receipt.items() if key != "schema"},
        },
    )
    checkpoints = sorted(checkpoint_dir.glob("checkpoint-*.pt"))
    for stale in checkpoints[:-2]:
        stale.unlink()
        with contextlib.suppress(FileNotFoundError):
            stale.with_suffix(".json").unlink()
    return path


def archive_checkpoints(
    checkpoint_dir: Path,
    category: str,
    reason: str,
    detail: str = "",
) -> None:
    archived = checkpoint_dir.with_name(
        f"{checkpoint_dir.name}.{category}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    )
    os.replace(checkpoint_dir, archived)
    emit("checkpoint_archived", reason=reason, path=str(archived), detail=detail)


def load_checkpoint(checkpoint_dir: Path, config: dict[str, Any]) -> dict[str, Any] | None:
    import torch

    pointer = checkpoint_dir / "last-good.json"
    if not checkpoint_dir.is_dir():
        return None
    receipts: dict[str, dict[str, Any]] = {}
    pointer_value: dict[str, Any] | None = None
    if pointer.is_file():
        try:
            with pointer.open("r", encoding="utf-8") as stream:
                pointer_value = json.load(stream)
        except Exception as error:
            archive_checkpoints(
                checkpoint_dir,
                "corrupt",
                "invalid-last-good-receipt",
                str(error),
            )
            return None
        if (
            pointer_value.get("configurationHash") is not None
            and pointer_value.get("configurationHash") != config["configurationHash"]
        ):
            archive_checkpoints(
                checkpoint_dir,
                "incompatible",
                "configuration_changed",
            )
            return None
        receipts[str(pointer_value.get("path", ""))] = pointer_value
    for receipt_path in checkpoint_dir.glob("checkpoint-*.json"):
        try:
            with receipt_path.open("r", encoding="utf-8") as stream:
                receipt = json.load(stream)
        except Exception:
            continue
        if receipt.get("schema") != "servo.gsplat-checkpoint-receipt/v1":
            continue
        receipts[str(receipt.get("path", ""))] = receipt
    if not receipts:
        return None

    candidates = sorted(
        receipts.values(),
        key=lambda receipt: int(receipt.get("step", -1)),
        reverse=True,
    )
    current_configuration_seen = False
    failures: list[str] = []
    for receipt in candidates:
        if receipt.get("configurationHash") != config["configurationHash"]:
            continue
        current_configuration_seen = True
        name = str(receipt.get("path", ""))
        if (
            not name.startswith("checkpoint-")
            or not name.endswith(".pt")
            or Path(name).name != name
        ):
            failures.append(f"unsafe checkpoint path {name!r}")
            continue
        path = checkpoint_dir / name
        if not path.is_file():
            failures.append(f"{name} is missing")
            continue
        if int(receipt.get("bytes", -1)) != path.stat().st_size:
            failures.append(f"{name} has the wrong byte count")
            continue
        if sha256_file(path) != receipt.get("sha256"):
            failures.append(f"{name} failed its SHA-256 receipt")
            continue
        try:
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        except Exception as error:
            failures.append(f"{name} could not be safely loaded: {error}")
            continue
        if (
            checkpoint.get("schema") != CHECKPOINT_SCHEMA
            or checkpoint.get("trainerVersion") != TRAINER_VERSION
            or checkpoint.get("pipelineRevision") != config.get("pipelineRevision")
            or checkpoint.get("configurationHash") != config["configurationHash"]
        ):
            failures.append(f"{name} uses an incompatible schema or runtime")
            continue
        if config.get("appearanceCompensation") is True and not all(
            key in checkpoint
            for key in ("appearance", "appearanceOptimizer", "appearanceScheduler")
        ):
            failures.append(f"{name} is missing appearance compensation state")
            continue
        if pointer_value is None or pointer_value.get("path") != name:
            atomic_json(
                pointer,
                {
                    "schema": "servo.gsplat-last-good/v1",
                    **{key: value for key, value in receipt.items() if key != "schema"},
                },
            )
            emit(
                "checkpoint_rolled_back",
                step=int(receipt["step"]) + 1,
                path=str(path),
                reason="newer-checkpoint-unavailable",
            )
        return checkpoint

    archive_checkpoints(
        checkpoint_dir,
        "corrupt" if current_configuration_seen else "incompatible",
        "no-verified-compatible-checkpoint",
        "; ".join(failures[-4:]),
    )
    return None


def restore_rng(checkpoint: dict[str, Any]) -> None:
    import numpy as np
    import torch

    rng = checkpoint.get("rng", {})
    if "python" in rng:
        random.setstate(rng["python"])
    if "numpy" in rng:
        numpy_state = rng["numpy"]
        np.random.set_state(
            (
                numpy_state["bitGenerator"],
                np.asarray(numpy_state["keys"], dtype=np.uint32),
                int(numpy_state["position"]),
                int(numpy_state["hasGauss"]),
                float(numpy_state["cachedGauss"]),
            )
        )
    if "torch" in rng:
        torch.set_rng_state(rng["torch"])
    if "cuda" in rng:
        torch.cuda.set_rng_state_all(rng["cuda"])


def rasterize(
    parameters: Any,
    camera_to_world: Any,
    calibration: Any,
    width: int,
    height: int,
    sh_degree: int,
    packed: bool,
    absgrad: bool,
    rasterization_mode: str,
    eps2d: float,
) -> tuple[Any, Any, dict[str, Any]]:
    import torch
    from gsplat.rendering import rasterization

    colors = torch.cat([parameters["sh0"], parameters["shN"]], dim=1)
    rendered, alpha, information = rasterization(
        means=parameters["means"],
        quats=parameters["quats"],
        scales=torch.exp(parameters["scales"]),
        opacities=torch.sigmoid(parameters["opacities"]),
        colors=colors,
        viewmats=torch.linalg.inv(camera_to_world),
        Ks=calibration,
        width=width,
        height=height,
        packed=packed,
        absgrad=absgrad,
        sparse_grad=False,
        rasterize_mode=rasterization_mode,
        eps2d=eps2d,
        camera_model="pinhole",
        render_mode="RGB",
        sh_degree=sh_degree,
        near_plane=0.01,
        far_plane=1e4,
    )
    return rendered, alpha, information


def validate_parameters(parameters: Any) -> None:
    import torch

    for name, value in parameters.items():
        if not bool(torch.isfinite(value).all()):
            raise TrainingError(f"Gaussian tensor {name} contains NaN or infinity.")
    if bool((torch.linalg.vector_norm(parameters["quats"], dim=-1) < 1e-8).any()):
        raise TrainingError("Gaussian orientation contains a zero quaternion.")


def clamp_parameters(parameters: Any) -> None:
    import torch
    import torch.nn.functional as functional

    with torch.no_grad():
        parameters["quats"].data.copy_(functional.normalize(parameters["quats"].data, dim=-1))
        parameters["scales"].data.clamp_(-12.0, 2.5)
        parameters["opacities"].data.clamp_(-12.0, 12.0)


def cleanup_parameters(
    parameters: Any,
    normalization: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    import torch

    with torch.no_grad():
        opacity = torch.sigmoid(parameters["opacities"])
        scales = torch.exp(parameters["scales"])
        largest_scale = scales.max(dim=-1).values
        anisotropy = largest_scale / scales.min(dim=-1).values.clamp_min(1e-12)
        radius = torch.linalg.vector_norm(parameters["means"], dim=-1)
        radius_limit = max(
            10.0,
            float(normalization.get("cleanupRadiusLimitNormalized", 10.0)),
        )
        scale_limit = max(
            2.0,
            float(normalization.get("cleanupScaleLimitNormalized", 2.0)),
        )
        transparent = opacity < 0.01
        needle = anisotropy > 50.0
        oversized = largest_scale > scale_limit
        spatial_outlier = radius > radius_limit
        keep = ~(transparent | needle | oversized | spatial_outlier)
        retained = int(keep.sum().item())
        if retained < 100:
            raise TrainingError(
                "Final artifact cleanup left fewer than 100 reliable Gaussians."
            )
        cleaned = torch.nn.ParameterDict(
            {
                name: torch.nn.Parameter(value.detach()[keep].contiguous())
                for name, value in parameters.items()
            }
        )
        metrics = {
            "inputGaussians": int(len(keep)),
            "retainedGaussians": retained,
            "removedGaussians": int(len(keep) - retained),
            "transparentCandidates": int(transparent.sum().item()),
            "needleCandidates": int(needle.sum().item()),
            "oversizedCandidates": int(oversized.sum().item()),
            "spatialOutlierCandidates": int(spatial_outlier.sum().item()),
            "radiusLimitNormalized": radius_limit,
            "scaleLimitNormalized": scale_limit,
            "policy": (
                "opacity>=0.01, anisotropy<=50, "
                f"scale<={scale_limit:g}, normalized-radius<={radius_limit:g}"
            ),
        }
    return cleaned, metrics


@contextlib.contextmanager
def evaluation_mode() -> Iterator[None]:
    import torch

    with torch.no_grad():
        yield


def evaluate(
    parameters: Any,
    dataset: ColmapDataset,
    device: str,
    sh_degree: int,
    packed: bool,
    rasterization_mode: str,
    eps2d: float,
    output: Path,
) -> dict[str, Any]:
    import numpy as np
    import torch
    from PIL import Image

    output.mkdir(parents=True, exist_ok=True)
    psnr_values: list[float] = []
    ssim_values: list[float] = []
    with evaluation_mode():
        for ordinal, index in enumerate(sorted(dataset.validation_indices)):
            pixels_cpu, camera_cpu, calibration_cpu = dataset.load(index)
            pixels = pixels_cpu.to(device=device, dtype=torch.float32).unsqueeze(0) / 255.0
            camera = camera_cpu.to(device).unsqueeze(0)
            calibration = calibration_cpu.to(device).unsqueeze(0)
            height, width = pixels.shape[1:3]
            rendered, _, _ = rasterize(
                parameters,
                camera,
                calibration,
                width,
                height,
                sh_degree,
                packed,
                False,
                rasterization_mode,
                eps2d,
            )
            rendered = rendered[..., :3].clamp(0.0, 1.0)
            mse = torch.mean((rendered - pixels).square()).clamp_min(1e-12)
            psnr_values.append(float((-10.0 * torch.log10(mse)).item()))
            ssim_values.append(float(ssim(rendered.permute(0, 3, 1, 2), pixels.permute(0, 3, 1, 2)).item()))
            comparison = torch.cat([pixels, rendered], dim=2)[0].mul(255).byte().cpu().numpy()
            Image.fromarray(np.asarray(comparison)).save(output / f"compare-{ordinal:03d}.png")
    if not psnr_values:
        raise TrainingError("No held-out frames were available for evaluation.")
    return {
        "validationImages": len(psnr_values),
        "psnrMean": float(np.mean(psnr_values)),
        "psnrMedian": float(np.median(psnr_values)),
        "ssimMean": float(np.mean(ssim_values)),
        "ssimMedian": float(np.median(ssim_values)),
    }


def export_cameras(dataset: ColmapDataset, path: Path) -> None:
    atomic_json(
        path,
        {
            "schema": "servo.gaussian-cameras/v1",
            "normalization": dataset.normalization,
            "validationPolicy": dataset.validation_policy,
            "validationImages": [
                dataset.records[index].name
                for index in sorted(dataset.validation_indices)
            ],
            "cameras": [
                {
                    "image": record.name,
                    "cameraId": record.camera_id,
                    "cameraModel": record.camera_model,
                    "width": record.width,
                    "height": record.height,
                    "cameraToWorldNormalized": record.camera_to_world.tolist(),
                    "calibration": record.calibration.tolist(),
                }
                for record in dataset.records
            ],
        },
    )


def export_appearance(dataset: ColmapDataset, appearance: Any | None, path: Path) -> None:
    if appearance is None:
        atomic_json(
            path,
            {
                "schema": "servo.gaussian-appearance/v1",
                "mode": "disabled",
                "views": [],
            },
        )
        return
    import torch

    with torch.no_grad():
        log_gains = appearance["logGains"].detach().cpu()
        biases = appearance["biases"].detach().cpu()
    atomic_json(
        path,
        {
            "schema": "servo.gaussian-appearance/v1",
            "mode": "per-frame-log-gain-bias-v1",
            "canonicalRender": "identity-transform",
            "views": [
                {
                    "image": record.name,
                    "trained": index in dataset.train_indices,
                    "logGain": log_gains[index].tolist(),
                    "bias": biases[index].tolist(),
                }
                for index, record in enumerate(dataset.records)
            ],
        },
    )


def export_world(
    parameters: Any,
    path: Path,
    rasterization_mode: str = "classic",
    eps2d: float = 0.3,
    representation_type: str = REPRESENTATION_TYPE,
) -> None:
    import numpy as np
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    count = int(parameters["means"].shape[0])
    sh_rest_count = int(parameters["shN"].shape[1]) * 3
    properties = [
        "x",
        "y",
        "z",
        "f_dc_0",
        "f_dc_1",
        "f_dc_2",
        *[f"f_rest_{index}" for index in range(sh_rest_count)],
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
    ]
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"comment ServoRepresentation {representation_type}\n"
        f"comment ServoRasterizationMode {rasterization_mode}\n"
        f"comment ServoEps2d {eps2d:.9g}\n"
        f"element vertex {count}\n"
        + "".join(f"property float {name}\n" for name in properties)
        + "end_header\n"
    ).encode("ascii")
    required_bytes = len(header) + count * len(properties) * 4
    free_bytes = shutil.disk_usage(path.parent).free
    if free_bytes < required_bytes + 1024**3:
        raise TrainingError(
            "Not enough free storage to stream the Gaussian PLY safely: "
            f"{required_bytes + 1024**3} bytes required, {free_bytes} available."
        )
    try:
        with temporary.open("wb") as stream:
            stream.write(header)
            for start in range(0, count, 65_536):
                stop = min(start + 65_536, count)
                sh_rest = (
                    parameters["shN"][start:stop]
                    .permute(0, 2, 1)
                    .reshape(stop - start, -1)
                )
                chunk = torch.cat(
                    [
                        parameters["means"][start:stop],
                        parameters["sh0"][start:stop].squeeze(1),
                        sh_rest,
                        parameters["opacities"][start:stop].unsqueeze(1),
                        parameters["scales"][start:stop],
                        parameters["quats"][start:stop],
                    ],
                    dim=1,
                )
                values = chunk.detach().to(device="cpu", dtype=torch.float32).numpy()
                stream.write(values.astype(np.dtype("<f4"), copy=False).tobytes())
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size != required_bytes:
            raise TrainingError("The streamed Gaussian PLY has an unexpected byte length.")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def train(config_path: Path) -> int:
    import torch
    import torch.nn.functional as functional
    from gsplat.strategy import DefaultStrategy
    from gsplat.strategy.ops import reset_opa

    with config_path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if config.get("schema") != CONFIG_SCHEMA:
        raise TrainingError(f"Expected training config schema {CONFIG_SCHEMA}.")
    if config.get("representationType") != REPRESENTATION_TYPE:
        raise TrainingError(
            f"Expected reconstruction representation {REPRESENTATION_TYPE}."
        )
    if not torch.cuda.is_available():
        raise TrainingError("PyTorch cannot access an NVIDIA CUDA device.")
    max_vram_gib = float(config.get("maxVramGiB", 0.0))
    total_vram_gib = torch.cuda.get_device_properties(0).total_memory / 1024**3
    if max_vram_gib <= 0.0:
        raise TrainingError("A positive maxVramGiB budget is required.")
    if max_vram_gib > total_vram_gib:
        raise TrainingError(
            f"This profile requires {max_vram_gib:.1f} GiB, but the CUDA device has "
            f"{total_vram_gib:.1f} GiB."
        )
    allocator_fraction = min(max_vram_gib / total_vram_gib, 0.95)
    torch.cuda.set_per_process_memory_fraction(allocator_fraction, device=0)
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=True)
    cancel_path = Path(config["cancelPath"])
    set_determinism(42)
    dataset = ColmapDataset(
        Path(config["data"]),
        int(config["dataFactor"]),
        max_point_error=float(config.get("maxReprojectionError", 3.0)),
    )
    device = "cuda:0"
    sh_degree = int(config.get("shDegree", 3))
    packed = bool(config.get("packed", True))
    max_steps = int(config["maxSteps"])
    checkpoint_every = int(config["checkpointEvery"])
    rasterization_mode = str(config.get("rasterizationMode", ""))
    eps2d = float(config.get("eps2d", 0.3))
    absgrad = config.get("absgrad") is True
    grow_grad2d = float(config.get("growGrad2d", 0.0008 if absgrad else 0.0002))
    coarse_factor = int(config.get("coarseFactor", 1))
    coarse_steps = int(config.get("coarseSteps", 0))
    max_gaussians = int(config.get("maxGaussians", 0))
    appearance_enabled = config.get("appearanceCompensation") is True
    appearance_learning_rate = float(config.get("appearanceLearningRate", 1e-3))
    appearance_regularization_weight = float(
        config.get("appearanceRegularization", 1e-4)
    )
    if max_steps <= 0 or checkpoint_every <= 0:
        raise TrainingError("Training and checkpoint step counts must be positive.")
    if rasterization_mode not in {"classic", "antialiased"}:
        raise TrainingError("rasterizationMode must be classic or antialiased.")
    if not math.isfinite(eps2d) or eps2d <= 0.0:
        raise TrainingError("eps2d must be a positive finite value.")
    if not math.isfinite(grow_grad2d) or grow_grad2d <= 0.0:
        raise TrainingError("growGrad2d must be a positive finite value.")
    if coarse_factor < 1 or coarse_steps < 0 or coarse_steps >= max_steps:
        raise TrainingError("The coarse-to-fine resolution schedule is invalid.")
    if max_gaussians < 100_000:
        raise TrainingError("maxGaussians must reserve a meaningful bounded scene budget.")
    if (
        not math.isfinite(appearance_learning_rate)
        or appearance_learning_rate <= 0.0
        or not math.isfinite(appearance_regularization_weight)
        or appearance_regularization_weight < 0.0
    ):
        raise TrainingError("Appearance compensation settings are invalid.")
    strategy = DefaultStrategy(
        prune_opa=0.005,
        grow_grad2d=grow_grad2d,
        grow_scale3d=0.01,
        prune_scale3d=0.10,
        refine_start_iter=500,
        refine_stop_iter=min(15_000, max_steps - 1),
        reset_every=3_000,
        refine_every=100,
        absgrad=absgrad,
        verbose=False,
    )
    checkpoint_dir = output / "checkpoints"
    checkpoint = load_checkpoint(checkpoint_dir, config)
    if checkpoint is None:
        parameters = create_parameters(dataset, sh_degree, device)
        optimizers = create_optimizers(parameters)
        scheduler = torch.optim.lr_scheduler.ExponentialLR(
            optimizers["means"], gamma=0.01 ** (1.0 / max_steps)
        )
        strategy_state = strategy.initialize_state(scene_scale=1.0)
        appearance = (
            create_appearance_parameters(len(dataset), device)
            if appearance_enabled
            else None
        )
        appearance_optimizer = (
            create_appearance_optimizer(appearance, appearance_learning_rate)
            if appearance is not None
            else None
        )
        appearance_scheduler = (
            torch.optim.lr_scheduler.ExponentialLR(
                appearance_optimizer,
                gamma=0.1 ** (1.0 / max_steps),
            )
            if appearance_optimizer is not None
            else None
        )
        start_step = 0
        densification_limited = False
        densification_limit_reason: str | None = None
        recent_loss: float | None = None
        elapsed_before = 0.0
        peak_allocated_before = 0.0
        peak_reserved_before = 0.0
        emit("training_initialized", gaussians=len(parameters["means"]), images=len(dataset))
    else:
        parameters = parameters_from_state(checkpoint["splats"], device)
        optimizers = create_optimizers(parameters)
        for name, optimizer in optimizers.items():
            optimizer.load_state_dict(checkpoint["optimizers"][name])
            optimizer_state_to_device(optimizer, device)
        scheduler = torch.optim.lr_scheduler.ExponentialLR(
            optimizers["means"], gamma=0.01 ** (1.0 / max_steps)
        )
        scheduler.load_state_dict(checkpoint["scheduler"])
        strategy_state = tree_to_device(checkpoint["strategyState"], device)
        appearance = (
            appearance_from_state(checkpoint["appearance"], len(dataset), device)
            if appearance_enabled
            else None
        )
        appearance_optimizer = (
            create_appearance_optimizer(appearance, appearance_learning_rate)
            if appearance is not None
            else None
        )
        appearance_scheduler = (
            torch.optim.lr_scheduler.ExponentialLR(
                appearance_optimizer,
                gamma=0.1 ** (1.0 / max_steps),
            )
            if appearance_optimizer is not None
            else None
        )
        if appearance_optimizer is not None and appearance_scheduler is not None:
            appearance_optimizer.load_state_dict(checkpoint["appearanceOptimizer"])
            optimizer_state_to_device(appearance_optimizer, device)
            appearance_scheduler.load_state_dict(checkpoint["appearanceScheduler"])
        start_step = int(checkpoint["step"]) + 1
        densification_limited = bool(
            checkpoint.get("policyState", {}).get("densificationLimited", False)
        )
        densification_limit_reason_value = checkpoint.get("policyState", {}).get(
            "densificationLimitReason"
        )
        densification_limit_reason = (
            str(densification_limit_reason_value)
            if densification_limit_reason_value
            else None
        )
        recent_loss_value = checkpoint.get("policyState", {}).get("recentLoss")
        recent_loss = (
            float(recent_loss_value)
            if isinstance(recent_loss_value, (int, float))
            and math.isfinite(float(recent_loss_value))
            else None
        )
        elapsed_before = float(
            checkpoint.get("policyState", {}).get("elapsedSeconds", 0.0)
        )
        peak_allocated_before = float(
            checkpoint.get("policyState", {}).get("peakVramGiB", 0.0)
        )
        peak_reserved_before = float(
            checkpoint.get("policyState", {}).get("peakReservedVramGiB", 0.0)
        )
        if densification_limited:
            strategy.refine_stop_iter = min(strategy.refine_stop_iter, start_step)
        restore_rng(checkpoint)
        emit("training_resumed", step=start_step, gaussians=len(parameters["means"]))
    strategy.check_sanity(parameters, optimizers)
    recovery_policy_path = checkpoint_dir / "recovery-policy.json"
    if recovery_policy_path.is_file():
        with recovery_policy_path.open("r", encoding="utf-8") as stream:
            recovery_policy = json.load(stream)
        if (
            recovery_policy.get("schema") == "servo.gsplat-recovery-policy/v1"
            and recovery_policy.get("configurationHash") == config["configurationHash"]
            and recovery_policy.get("disableDensification") is True
        ):
            densification_limited = True
            densification_limit_reason = str(
                recovery_policy.get("reason") or "recovery-policy"
            )
            strategy.refine_stop_iter = min(strategy.refine_stop_iter, start_step)
            emit("densification_recovery_enabled", step=start_step)
    if (
        checkpoint is not None
        and checkpoint.get("opacityResetSemantics") is None
        and start_step > strategy.reset_every
        and start_step <= strategy.refine_stop_iter
        and start_step % strategy.reset_every != 0
    ):
        reset_opa(
            params=parameters,
            optimizers=optimizers,
            state=strategy_state,
            value=strategy.prune_opa * 2.0,
        )
        emit(
            "opacity_reset_recovered",
            step=start_step,
            reason="upstream-gsplat-1.5.3-reset-condition",
        )
    scale_regularization = float(config.get("scaleRegularization", 0.001))
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()

    def current_policy_state() -> dict[str, Any]:
        return {
            "densificationLimited": densification_limited,
            "densificationLimitReason": densification_limit_reason,
            "recentLoss": recent_loss,
            "elapsedSeconds": elapsed_before + time.monotonic() - started,
            "peakVramGiB": max(
                peak_allocated_before,
                torch.cuda.max_memory_allocated() / 1024**3,
            ),
            "peakReservedVramGiB": max(
                peak_reserved_before,
                torch.cuda.max_memory_reserved() / 1024**3,
            ),
        }

    for step in range(start_step, max_steps):
        if cancel_path.exists():
            if step > start_step or checkpoint is not None:
                save_checkpoint(
                    checkpoint_dir,
                    step - 1,
                    parameters,
                    optimizers,
                    scheduler,
                    strategy_state,
                    current_policy_state(),
                    config,
                    dataset,
                    appearance,
                    appearance_optimizer,
                    appearance_scheduler,
                )
            emit("training_cancelled", step=step)
            return 130
        index = random.choice(dataset.train_indices)
        pixels_cpu, camera_cpu, calibration_cpu = dataset.load(index)
        pixels = pixels_cpu.to(device=device, dtype=torch.float32, non_blocking=True).unsqueeze(0) / 255.0
        camera = camera_cpu.to(device, non_blocking=True).unsqueeze(0)
        calibration = calibration_cpu.to(device, non_blocking=True).unsqueeze(0)
        active_resolution_factor = coarse_factor if step < coarse_steps else 1
        pixels, calibration = downscale_training_sample(
            pixels,
            calibration,
            active_resolution_factor,
        )
        height, width = pixels.shape[1:3]
        active_degree = min(step // 1000, sh_degree)
        try:
            rendered, _, information = rasterize(
                parameters,
                camera,
                calibration,
                width,
                height,
                active_degree,
                packed,
                absgrad,
                rasterization_mode,
                eps2d,
            )
            rendered = rendered[..., :3]
            training_render = apply_appearance(rendered, appearance, index)
            strategy.step_pre_backward(
                params=parameters,
                optimizers=optimizers,
                state=strategy_state,
                step=step,
                info=information,
            )
            l1 = functional.l1_loss(training_render, pixels)
            ssim_loss = 1.0 - ssim(
                training_render.permute(0, 3, 1, 2),
                pixels.permute(0, 3, 1, 2),
            )
            loss = 0.8 * l1 + 0.2 * ssim_loss
            if appearance is not None and appearance_regularization_weight > 0.0:
                loss = loss + appearance_regularization_weight * appearance_regularization(
                    appearance,
                    index,
                )
            if scale_regularization > 0:
                scales = torch.exp(parameters["scales"])
                anisotropy = scales.max(dim=-1).values / scales.min(dim=-1).values.clamp_min(1e-6)
                loss = loss + scale_regularization * (
                    scales.mean() + functional.relu(anisotropy - 20.0).mean()
                )
            loss.backward()
            for optimizer in optimizers.values():
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            if appearance_optimizer is not None:
                appearance_optimizer.step()
                appearance_optimizer.zero_grad(set_to_none=True)
            scheduler.step()
            if appearance_scheduler is not None:
                appearance_scheduler.step()
            if (
                not densification_limited
                and len(parameters["means"]) >= max_gaussians // 2
            ):
                # One DefaultStrategy split/duplicate pass can at most double
                # the active set.  Stopping at half of the hard allocation
                # ceiling makes the profile cap deterministic before a large
                # temporary densification allocation is attempted.
                strategy.refine_stop_iter = min(strategy.refine_stop_iter, step)
                densification_limited = True
                densification_limit_reason = "gaussian-allocation-guard"
                atomic_json(
                    recovery_policy_path,
                    {
                        "schema": "servo.gsplat-recovery-policy/v1",
                        "configurationHash": config["configurationHash"],
                        "disableDensification": True,
                        "reason": densification_limit_reason,
                        "step": step,
                        "gaussians": len(parameters["means"]),
                        "hardMaximumGaussians": max_gaussians,
                    },
                )
                emit(
                    "densification_limited",
                    step=step,
                    reason=densification_limit_reason,
                    gaussians=len(parameters["means"]),
                    hardMaximumGaussians=max_gaussians,
                )
            strategy.step_post_backward(
                params=parameters,
                optimizers=optimizers,
                state=strategy_state,
                step=step,
                info=information,
                packed=packed,
            )
            # gsplat 1.5.3 uses a bitwise operator in this condition, so its
            # intended periodic opacity reset never runs. Keep the pinned
            # release and apply the corrected upstream semantics explicitly.
            if should_reset_opacity(
                step, strategy.reset_every, strategy.refine_stop_iter
            ):
                reset_opa(
                    params=parameters,
                    optimizers=optimizers,
                    state=strategy_state,
                    value=strategy.prune_opa * 2.0,
                )
                emit("opacity_reset", step=step)
            clamp_parameters(parameters)
            clamp_appearance(appearance)
            reserved_gib = torch.cuda.memory_reserved() / 1024**3
            if not densification_limited and reserved_gib >= max_vram_gib * 0.80:
                strategy.refine_stop_iter = min(strategy.refine_stop_iter, step + 1)
                densification_limited = True
                densification_limit_reason = "memory-warning-threshold"
                atomic_json(
                    recovery_policy_path,
                    {
                        "schema": "servo.gsplat-recovery-policy/v1",
                        "configurationHash": config["configurationHash"],
                        "disableDensification": True,
                        "reason": densification_limit_reason,
                        "step": step,
                    },
                )
                emit(
                    "densification_limited",
                    step=step,
                    reason=densification_limit_reason,
                    reservedVramGiB=reserved_gib,
                    maxVramGiB=max_vram_gib,
                    gaussians=len(parameters["means"]),
                )
        except torch.OutOfMemoryError as error:
            torch.cuda.empty_cache()
            densification_limit_reason = "allocator-out-of-memory"
            atomic_json(
                recovery_policy_path,
                {
                    "schema": "servo.gsplat-recovery-policy/v1",
                    "configurationHash": config["configurationHash"],
                    "disableDensification": True,
                    "reason": densification_limit_reason,
                    "step": step,
                },
            )
            raise TrainingError(
                "CUDA reached the profile memory ceiling. Retry this job from its last "
                "verified checkpoint, or create a new Recovery-profile job."
            ) from error
        recent_loss = float(loss.detach().item())
        completed_step = step + 1
        if completed_step % 25 == 0 or completed_step == max_steps:
            emit(
                "training_progress",
                step=completed_step,
                total=max_steps,
                loss=recent_loss,
                gaussians=len(parameters["means"]),
                resolutionFactor=active_resolution_factor,
                rasterizationMode=rasterization_mode,
                peakVramGiB=torch.cuda.max_memory_allocated() / 1024**3,
                peakReservedVramGiB=torch.cuda.max_memory_reserved() / 1024**3,
                maxVramGiB=max_vram_gib,
                elapsedSeconds=time.monotonic() - started,
            )
        if completed_step % checkpoint_every == 0 or completed_step == max_steps:
            validate_parameters(parameters)
            path = save_checkpoint(
                checkpoint_dir,
                step,
                parameters,
                optimizers,
                scheduler,
                strategy_state,
                current_policy_state(),
                config,
                dataset,
                appearance,
                appearance_optimizer,
                appearance_scheduler,
            )
            emit("checkpoint_saved", step=completed_step, path=str(path))

    if recent_loss is None or not math.isfinite(recent_loss):
        raise TrainingError(
            "The final checkpoint does not contain a finite recent training loss."
        )
    validate_parameters(parameters)
    appearance_summary = appearance_metrics(appearance, dataset.train_indices)
    del optimizers
    del scheduler
    del strategy_state
    if appearance_optimizer is not None:
        del appearance_optimizer
    if appearance_scheduler is not None:
        del appearance_scheduler
    gc.collect()
    torch.cuda.empty_cache()
    parameters, cleanup = cleanup_parameters(parameters, dataset.normalization)
    validate_parameters(parameters)
    validation = evaluate(
        parameters,
        dataset,
        device,
        sh_degree,
        packed,
        rasterization_mode,
        eps2d,
        output / "validation",
    )
    export_cameras(dataset, output / "cameras.json")
    export_appearance(dataset, appearance, output / "appearance.json")
    export_world(
        parameters,
        output / "world.ply",
        rasterization_mode,
        eps2d,
        REPRESENTATION_TYPE,
    )
    import importlib.metadata

    metrics = {
        "schema": METRICS_SCHEMA,
        "trainerVersion": TRAINER_VERSION,
        "pipelineRevision": config.get("pipelineRevision"),
        "jobId": config.get("jobId"),
        "profile": config.get("profile"),
        "configurationHash": config["configurationHash"],
        "representationType": REPRESENTATION_TYPE,
        "rasterizationMode": rasterization_mode,
        "eps2d": eps2d,
        "densificationStrategy": "default-absgrad" if absgrad else "default",
        "absgrad": absgrad,
        "growGrad2d": grow_grad2d,
        "maxGaussians": max_gaussians,
        "resolutionSchedule": {
            "coarseFactor": coarse_factor,
            "coarseSteps": coarse_steps,
            "fullResolutionSteps": max_steps - coarse_steps,
        },
        "appearance": appearance_summary,
        "steps": max_steps,
        "gaussians": len(parameters["means"]),
        "trainingImages": len(dataset.train_indices),
        "validationImages": len(dataset.validation_indices),
        "finalLoss": recent_loss,
        "peakVramGiB": max(
            peak_allocated_before, torch.cuda.max_memory_allocated() / 1024**3
        ),
        "peakReservedVramGiB": max(
            peak_reserved_before, torch.cuda.max_memory_reserved() / 1024**3
        ),
        "maxVramGiB": max_vram_gib,
        "densificationLimited": densification_limited,
        "densificationLimitReason": densification_limit_reason,
        "elapsedSeconds": elapsed_before + time.monotonic() - started,
        "normalization": dataset.normalization,
        "initialization": dataset.initialization_stats,
        "cleanup": cleanup,
        "validationPolicy": dataset.validation_policy,
        "runtime": {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gsplat": importlib.metadata.version("gsplat"),
            "pycolmap": importlib.metadata.version("pycolmap"),
            "device": torch.cuda.get_device_name(0),
        },
        **validation,
    }
    atomic_json(output / "train-metrics.json", metrics)
    emit("training_completed", **metrics)
    return 0


def kernel_check() -> int:
    import torch
    from gsplat.rendering import rasterization

    if not torch.cuda.is_available():
        raise TrainingError("CUDA is unavailable to PyTorch.")
    device = "cuda:0"
    means = torch.tensor([[0.0, 0.0, 2.0]], device=device, requires_grad=True)
    quaternions = torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device, requires_grad=True)
    scales = torch.tensor([[0.05, 0.05, 0.05]], device=device, requires_grad=True)
    opacities = torch.tensor([0.8], device=device, requires_grad=True)
    colors = torch.tensor([[1.0, 0.0, 0.0]], device=device, requires_grad=True)
    views = torch.eye(4, device=device).unsqueeze(0)
    calibrations = torch.tensor(
        [[[100.0, 0.0, 32.0], [0.0, 100.0, 32.0], [0.0, 0.0, 1.0]]],
        device=device,
    )
    rendered, alpha, information = rasterization(
        means,
        quaternions,
        scales,
        opacities,
        colors,
        views,
        calibrations,
        64,
        64,
        packed=True,
        absgrad=True,
        rasterize_mode="antialiased",
        eps2d=0.3,
    )
    information["means2d"].retain_grad()
    loss = rendered.sum() + alpha.sum()
    loss.backward()
    if (
        not bool(torch.isfinite(rendered).all())
        or means.grad is None
        or not hasattr(information["means2d"], "absgrad")
        or not bool(torch.isfinite(information["means2d"].absgrad).all())
    ):
        raise TrainingError("gsplat CUDA forward/backward verification failed.")
    emit(
        "kernel_ready",
        torch=torch.__version__,
        cuda=torch.version.cuda,
        gpu=torch.cuda.get_device_name(0),
        rasterizationMode="antialiased",
        absgrad=True,
        renderedShape=list(rendered.shape),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=TRAINER_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("kernel-check")
    train_parser = commands.add_parser("train")
    train_parser.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "kernel-check":
            return kernel_check()
        if arguments.command == "train":
            return train(arguments.config)
    except TrainingError as error:
        emit("training_failed", message=str(error))
        return 2
    except Exception as error:
        emit("training_failed", message=str(error), details=traceback.format_exc())
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
