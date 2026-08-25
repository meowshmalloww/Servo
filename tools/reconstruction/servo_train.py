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


TRAINER_VERSION = "0.7.0"
CONFIG_SCHEMA = "servo.gsplat-training/v2"
METRICS_SCHEMA = "servo.gsplat-metrics/v2"
CHECKPOINT_SCHEMA = "servo.gsplat-checkpoint/v2"
REPRESENTATION_TYPE = "servo-fidelity-3dgs-v1"
C0 = 0.28209479177387814
OPACITY_RESET_SEMANTICS = "servo-gsplat-1.5.3-fix-v2"
STATIC_CONFIDENCE_METHOD = (
    "DIS-bidirectional-flow-plus-COLMAP-epipolar-raw-evidence-v2"
)
APPEARANCE_FRAME_SELECTION_SCHEMA = (
    "servo.diagnostic-appearance-frame-selection/v1"
)
CAPTURE_HEALTH_SCHEMA = "servo.capture-health/v1"
CAPTURE_HEALTH_SELECTION_METHOD = (
    "sharpness-exposure-track-coverage-accumulated-baseline/v1"
)
SEMANTIC_PHOTOMETRIC_METHOD = (
    "servo-oneformer-rigid-static-temporal-floor-preserved-nonrigid-v4"
)
VALIDATION_STRIDE = 8
VALIDATION_OFFSET = 4
ENDPOINT_SAMPLING_WINDOW = 8
ENDPOINT_SAMPLING_MULTIPLIER = 2
MAXIMUM_SPARSE_ANCHOR_MULTIPLIER = 4
MAIN_SAMPLING_POLICY = "deterministic-weighted-shuffled-epochs/v1"
SCREEN_SPACE_REFINEMENT_POLICY = "gsplat-default-normalized-radius/v1"
DENSITY_REFINEMENT_POLICY = "main-fit-until-final-fit/v1"
DIAGNOSTIC_FIXED_DENSITY_REFINEMENT_POLICY = (
    "fixed-early-density-then-appearance/v1"
)
DIAGNOSTIC_FIXED_DENSITY_REFINEMENT_STOP = 4_500
VIDEO_CAPTURE_BOTTOM_EXCLUSION_FRACTION = 0.04
SEMANTIC_SKY_OPACITY_METHOD = (
    "observed-oneformer-temporally-confirmed-sky-alpha-mean-plus-interior-tail-bce-v4"
)
SEMANTIC_SKY_DIAGNOSTIC_ABLATION_METHOD = (
    "observed-oneformer-sky-alpha-mean-l1-v1-diagnostic-ablation"
)
SEMANTIC_SKY_HYBRID_DIAGNOSTIC_METHOD = (
    "observed-oneformer-semantic-l1-plus-certified-interior-tail-bce-v1-diagnostic"
)
DIAGNOSTIC_PROVENANCE_SCHEMA = "servo.diagnostic-training-provenance/v1"
SEMANTIC_SKY_TAIL_THRESHOLD = 0.10
SEMANTIC_SKY_TAIL_WEIGHT = 0.05
SEMANTIC_SKY_TAIL_BCE_EPSILON = 0.01
SEMANTIC_SKY_TAIL_EROSION_RADIUS = 2
SEMANTIC_SKY_TAIL_EROSION_METHOD = (
    "binary-morphological-erosion-non-sky-padding/v1"
)
CERTIFIED_SKY_EVIDENCE_SCHEMA = "servo.certified-sky-evidence/v1"
CERTIFIED_SKY_EVIDENCE_METHOD = "oneformer-rotation-only-temporal-consensus-v1"
CERTIFIED_SKY_EVIDENCE_DIRECTORY = "sky-evidence"
CERTIFIED_SKY_EVIDENCE_SKY = 1
CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY = 2
DENSITY_GROWTH_CAP_POLICY = "freeze-growth-preserve-pruning/v1"
CONTRIBUTOR_SKY_CLEANUP_METHOD = (
    "gsplat-1.5.3-certified-sky-exclusive-contributor-opacity-v1"
)
CONTRIBUTOR_SKY_CLEANUP_MINIMUM_WEIGHT = 0.01
CONTRIBUTOR_SKY_CLEANUP_MINIMUM_VIEWS = 4
CONTRIBUTOR_SKY_CLEANUP_MINIMUM_VIEW_GAP = 4
CONTRIBUTOR_SKY_CLEANUP_AUDIT_FACTOR = 4
SURFEL_ABLATION_SCHEMA = "servo.diagnostic-surfel-ablation/v1"
SURFEL_ABLATION_METHOD = "gsplat-1.5.3-rasterization-2dgs-surfel-v1"
SURFEL_ABLATION_REPRESENTATION = "servo-fidelity-3dgs-surfel-ablation-v1"
SURFEL_MINIMUM_SCALE = 1e-6
FRAME_OVERSAMPLING_SCHEMA = "servo.diagnostic-frame-oversampling/v1"
FRAME_OVERSAMPLING_METHOD = "observed-sky-offender-weighted-sampling-v1"
CROSS_VIEW_DENSE_MODE = "dense-expected-z-reprojection-v1"
CROSS_VIEW_SPARSE_TRACK_MODE = "sparse-colmap-shared-track-camera-z-v1"
DUAL_OPACITY_CORRECTED_INITIALIZATION = (
    "base-legacy-0.10-appearance-gate-near-one-v1"
)
DUAL_OPACITY_EFFECTIVE_PRUNE_POLICY = (
    "effective-low-and-no-geometry-evidence-v1"
)
DUAL_OPACITY_PRODUCT_RESET_POLICY = "product-preserving-controlled-reset-v1"
COVERAGE_DENSIFICATION_SCHEMA = "servo.diagnostic-coverage-densification/v1"
COVERAGE_DENSIFICATION_METHOD = "gsplat-1.5.3-tile-footprint-depth-scaled-v1"
COVERAGE_DENSIFICATION_FOOTPRINT_SOURCE = "tiles-per-gaussian"
COVERAGE_DENSIFICATION_DEPTH_SOURCE = "camera-space-z"


class TrainingError(RuntimeError):
    pass


class TrainingCancelled(TrainingError):
    """A cooperative cancellation after the last verified checkpoint."""


def is_nonpublishable_diagnostic_config(config: Mapping[str, Any]) -> bool:
    """Return whether a config is explicitly sealed as a diagnostic artifact."""

    provenance = config.get("diagnosticProvenance")
    return bool(
        isinstance(provenance, Mapping)
        and provenance.get("schema") == DIAGNOSTIC_PROVENANCE_SCHEMA
        and provenance.get("nonPublishable") is True
    )


def supported_density_refinement_contract(
    config: Mapping[str, Any],
    *,
    policy: str,
    stop_iter: int,
    main_fit_stop_iter: int,
    coarse_steps: int,
    dense_geometry_start: int,
) -> bool:
    """Accept the release density window or one sealed appearance ablation.

    Long visual convergence cannot be assessed by extending the screen-space
    prune phase indefinitely: that keeps removing valid small splats after
    density has already stabilized. The early-stop option is deliberately
    sealed to non-publishable diagnostics. A released world must keep the
    existing complete-main-fit refinement contract unless it receives its own
    separately reviewed release policy.
    """

    if policy == DENSITY_REFINEMENT_POLICY:
        return stop_iter == main_fit_stop_iter
    return bool(
        is_nonpublishable_diagnostic_config(config)
        and policy == DIAGNOSTIC_FIXED_DENSITY_REFINEMENT_POLICY
        and stop_iter == DIAGNOSTIC_FIXED_DENSITY_REFINEMENT_STOP
        and max(coarse_steps, dense_geometry_start) < stop_iter < main_fit_stop_iter
    )


def supported_coverage_densification_contract(
    config: Mapping[str, Any], treatment: Mapping[str, Any]
) -> bool:
    """Seal the tile-footprint densification proxy to a single diagnostic A/B.

    ``tiles_per_gauss`` is a conservative raster-tile footprint, not the exact
    contributing-pixel count used by Pixel-GS.  The treatment therefore stays
    explicitly diagnostic and changes only the running densification statistic.
    """

    try:
        maximum_footprint_fraction = float(
            treatment["maximumFootprintFraction"]
        )
        footprint_power = float(treatment["footprintPower"])
        depth_scale_fraction = float(treatment["depthScaleFraction"])
        depth_power = float(treatment["depthPower"])
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        is_nonpublishable_diagnostic_config(config)
        and treatment.get("schema") == COVERAGE_DENSIFICATION_SCHEMA
        and treatment.get("method") == COVERAGE_DENSIFICATION_METHOD
        and treatment.get("footprintSource")
        == COVERAGE_DENSIFICATION_FOOTPRINT_SOURCE
        and treatment.get("depthSource") == COVERAGE_DENSIFICATION_DEPTH_SOURCE
        and math.isclose(
            maximum_footprint_fraction, 0.02, rel_tol=0.0, abs_tol=1e-12
        )
        and math.isclose(footprint_power, 1.0, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(
            depth_scale_fraction, 0.37, rel_tol=0.0, abs_tol=1e-12
        )
        and math.isclose(depth_power, 2.0, rel_tol=0.0, abs_tol=1e-12)
        and treatment.get("packedRequired") is True
        and treatment.get("surfelAllowed") is False
        and treatment.get("dualOpacityAllowed") is False
        and treatment.get("revisedOpacity") is False
        and treatment.get("lossesChanged") is False
        and treatment.get("opacityPolicyChanged") is False
        and treatment.get("pruningPolicyChanged") is False
    )


def update_coverage_densification_state(
    params: Mapping[str, Any],
    state: dict[str, Any],
    info: Mapping[str, Any],
    *,
    key_for_gradient: str,
    absgrad: bool,
    scene_scale: float,
    maximum_footprint_fraction: float,
    footprint_power: float,
    depth_scale_fraction: float,
    depth_power: float,
) -> None:
    """Accumulate clean-room footprint/depth-aware gsplat growth statistics.

    The normalization and radius bookkeeping intentionally match gsplat 1.5.3
    ``DefaultStrategy``.  Only the gradient numerator and denominator change.
    """

    import torch

    required = (
        "width",
        "height",
        "n_cameras",
        "radii",
        "gaussian_ids",
        "depths",
        "tiles_per_gauss",
        "tile_width",
        "tile_height",
        key_for_gradient,
    )
    missing = [key for key in required if key not in info]
    if missing:
        raise TrainingError(
            "Coverage-aware densification metadata is incomplete: "
            + ", ".join(missing)
        )
    gradient_source = info[key_for_gradient]
    gradient = (
        getattr(gradient_source, "absgrad", None)
        if absgrad
        else getattr(gradient_source, "grad", None)
    )
    if gradient is None:
        raise TrainingError(
            "Coverage-aware densification did not receive projected-mean gradients."
        )
    gradients = gradient.clone()
    gaussian_ids = info["gaussian_ids"]
    radii = info["radii"].max(dim=-1).values
    depths = info["depths"]
    footprints = info["tiles_per_gauss"]
    observation_count = int(gaussian_ids.numel())
    if any(
        int(value.numel()) != observation_count
        for value in (radii, depths, footprints)
    ) or gradients.shape != (observation_count, 2):
        raise TrainingError(
            "Coverage-aware densification requires aligned packed raster metadata."
        )
    if (
        not torch.isfinite(gradients).all()
        or not torch.isfinite(depths).all()
        or not torch.isfinite(footprints).all()
        or (depths <= 0.0).any()
    ):
        raise TrainingError(
            "Coverage-aware densification rejected nonfinite or nonpositive metadata."
        )
    width = int(info["width"])
    height = int(info["height"])
    n_cameras = int(info["n_cameras"])
    tile_width = int(info["tile_width"])
    tile_height = int(info["tile_height"])
    if min(width, height, n_cameras, tile_width, tile_height) <= 0:
        raise TrainingError("Coverage-aware densification received invalid dimensions.")
    gradients[..., 0] *= width / 2.0 * n_cameras
    gradients[..., 1] *= height / 2.0 * n_cameras

    gaussian_count = len(next(iter(params.values())))
    if state.get("grad2d") is None:
        state["grad2d"] = torch.zeros(gaussian_count, device=gradients.device)
    if state.get("count") is None:
        state["count"] = torch.zeros(gaussian_count, device=gradients.device)
    if state.get("radii") is None:
        state["radii"] = torch.zeros(gaussian_count, device=gradients.device)

    total_tiles = tile_width * tile_height
    maximum_footprint = max(1.0, maximum_footprint_fraction * total_tiles)
    footprint_weights = footprints.to(dtype=gradients.dtype).clamp(
        min=1.0, max=maximum_footprint
    ).pow(footprint_power)
    depth_denominator = depth_scale_fraction * float(scene_scale)
    if not math.isfinite(depth_denominator) or depth_denominator <= 0.0:
        raise TrainingError("Coverage-aware densification has an invalid scene scale.")
    depth_weights = (depths / depth_denominator).clamp(min=0.0, max=1.0).pow(
        depth_power
    )
    weighted_observations = footprint_weights * depth_weights
    gradient_norms = gradients.norm(dim=-1)
    state["grad2d"].index_add_(
        0, gaussian_ids, gradient_norms * weighted_observations
    )
    state["count"].index_add_(0, gaussian_ids, footprint_weights)
    state["radii"][gaussian_ids] = torch.maximum(
        state["radii"][gaussian_ids],
        radii / float(max(width, height)),
    )

    diagnostics = state.setdefault(
        "coverageDensificationDiagnostics",
        {
            "observations": 0,
            "footprintSum": 0.0,
            "depthWeightedFootprintSum": 0.0,
            "maximumFootprint": 0.0,
            "cappedObservations": 0,
            "defaultGrad2d": None,
            "defaultCount": None,
            "rawFootprintSum": None,
            "depthSum": None,
        },
    )
    if (
        diagnostics.get("defaultGrad2d") is None
        or len(diagnostics["defaultGrad2d"]) != gaussian_count
        or diagnostics.get("rawFootprintSum") is None
        or diagnostics.get("depthSum") is None
    ):
        diagnostics["defaultGrad2d"] = torch.zeros(
            gaussian_count, device=gradients.device
        )
        diagnostics["defaultCount"] = torch.zeros(
            gaussian_count, device=gradients.device
        )
        diagnostics["rawFootprintSum"] = torch.zeros(
            gaussian_count, device=gradients.device
        )
        diagnostics["depthSum"] = torch.zeros(
            gaussian_count, device=gradients.device
        )
    diagnostics["defaultGrad2d"].index_add_(
        0, gaussian_ids, gradient_norms
    )
    diagnostics["defaultCount"].index_add_(
        0,
        gaussian_ids,
        torch.ones_like(gaussian_ids, dtype=gradients.dtype),
    )
    diagnostics["rawFootprintSum"].index_add_(
        0, gaussian_ids, footprints.to(dtype=gradients.dtype).clamp_min(1.0)
    )
    diagnostics["depthSum"].index_add_(0, gaussian_ids, depths)
    diagnostics["observations"] += observation_count
    diagnostics["footprintSum"] += float(footprint_weights.sum().item())
    diagnostics["depthWeightedFootprintSum"] += float(
        weighted_observations.sum().item()
    )
    diagnostics["maximumFootprint"] = max(
        float(diagnostics["maximumFootprint"]),
        float(footprint_weights.max().item()) if observation_count else 0.0,
    )
    diagnostics["cappedObservations"] += int(
        (footprints > maximum_footprint).sum().item()
    )


def supported_semantic_sky_opacity_contract(
    config: Mapping[str, Any],
    *,
    method: str,
    tail_threshold: float,
    tail_weight: float,
    tail_bce_epsilon: float,
    tail_erosion_method: str,
    tail_erosion_radius: int,
) -> bool:
    """Accept the release loss or one sealed diagnostic control only.

    The zero-tail control exists solely to separate the effect of the recent
    growth/pruning lifecycle repair from the stronger sky-tail objective.  It
    is deliberately impossible in a publishable configuration, preventing an
    A/B shortcut from silently becoming a release recipe.
    """

    shared = (
        math.isclose(
            tail_threshold,
            SEMANTIC_SKY_TAIL_THRESHOLD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            tail_bce_epsilon,
            SEMANTIC_SKY_TAIL_BCE_EPSILON,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and tail_erosion_method == SEMANTIC_SKY_TAIL_EROSION_METHOD
        and tail_erosion_radius == SEMANTIC_SKY_TAIL_EROSION_RADIUS
    )
    return bool(
        shared
        and (
            (
                method == SEMANTIC_SKY_OPACITY_METHOD
                and math.isclose(
                    tail_weight,
                    SEMANTIC_SKY_TAIL_WEIGHT,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            )
            or (
                is_nonpublishable_diagnostic_config(config)
                and method == SEMANTIC_SKY_DIAGNOSTIC_ABLATION_METHOD
                and math.isclose(tail_weight, 0.0, rel_tol=0.0, abs_tol=1e-12)
            )
            or (
                is_nonpublishable_diagnostic_config(config)
                and method == SEMANTIC_SKY_HYBRID_DIAGNOSTIC_METHOD
                and math.isclose(
                    tail_weight,
                    SEMANTIC_SKY_TAIL_WEIGHT,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            )
        )
    )


def supported_contributor_sky_cleanup_contract(
    config: Mapping[str, Any],
    *,
    enabled: bool,
    method: str,
    start_step: int,
    refine_stop_iter: int,
    minimum_weight: float,
    minimum_views: int,
    minimum_view_gap: int,
    audit_factor: int,
    loss_weight: float,
) -> bool:
    """Seal contributor cleanup to a conservative diagnostic A/B.

    This treatment is intentionally unavailable to publishable jobs until a
    complete observed-path audit proves that it removes finite sky support
    without erasing foliage, signs, mountains, or road-edge evidence.
    """

    if not enabled:
        return True
    return bool(
        is_nonpublishable_diagnostic_config(config)
        and method == CONTRIBUTOR_SKY_CLEANUP_METHOD
        and start_step == refine_stop_iter
        and math.isclose(
            minimum_weight,
            CONTRIBUTOR_SKY_CLEANUP_MINIMUM_WEIGHT,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and minimum_views == CONTRIBUTOR_SKY_CLEANUP_MINIMUM_VIEWS
        and minimum_view_gap == CONTRIBUTOR_SKY_CLEANUP_MINIMUM_VIEW_GAP
        and audit_factor == CONTRIBUTOR_SKY_CLEANUP_AUDIT_FACTOR
        and math.isfinite(loss_weight)
        and 0.0 < loss_weight <= 0.05
    )


def supported_surfel_ablation_contract(
    config: Mapping[str, Any],
    *,
    schema: str,
    method: str,
    depth_distortion_weight: float,
    normal_consistency_weight: float,
    normal_consistency_start: int,
    coarse_steps: int,
) -> bool:
    """Seal the native gsplat 2DGS surfel A/B to non-publishable diagnostics.

    The 2DGS representation is a research A/B against the released 3DGS path.
    Its render/export parity with the production Vulkan 3DGS renderer is not
    verified, so the treatment must stay impossible in publishable jobs until
    that parity work lands separately.
    """

    if schema != SURFEL_ABLATION_SCHEMA or method != SURFEL_ABLATION_METHOD:
        return False
    if not is_nonpublishable_diagnostic_config(config):
        return False
    if (
        not math.isfinite(depth_distortion_weight)
        or not 0.0 <= depth_distortion_weight <= 1.0
    ):
        return False
    if (
        not math.isfinite(normal_consistency_weight)
        or not 0.0 <= normal_consistency_weight <= 0.5
    ):
        return False
    return normal_consistency_start > max(coarse_steps, 0)


def supported_frame_oversampling_contract(
    config: Mapping[str, Any],
    *,
    schema: str,
    method: str,
    multiplier: int,
    frames: Sequence[str],
    record_names: Mapping[str, int],
) -> bool:
    """Seal per-frame oversampling to non-publishable diagnostics.

    Oversampling and per-frame sky-weight strengthening are an offender-frame
    repair, not a general training recipe. The frame list must name registered
    images explicitly so the treatment stays auditable against the sky-leakage
    receipts that justified it.
    """

    if schema != FRAME_OVERSAMPLING_SCHEMA:
        return False
    if method != FRAME_OVERSAMPLING_METHOD:
        return False
    if not is_nonpublishable_diagnostic_config(config):
        return False
    if isinstance(multiplier, bool) or not isinstance(multiplier, int):
        return False
    if not 2 <= multiplier <= 8:
        return False
    if not isinstance(frames, Sequence) or isinstance(frames, str):
        return False
    names = [str(frame) for frame in frames]
    if not names or len(set(names)) != len(names) or len(names) > 64:
        return False
    return all(name in record_names for name in names)


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


def validate_experiment_configuration_hash(config: Mapping[str, Any]) -> None:
    """Validate an optional content hash used by direct diagnostic runs."""

    expected = config.get("experimentConfigurationHash")
    if expected is None:
        return
    if not isinstance(expected, str) or not expected.startswith("sha256:"):
        raise TrainingError("experimentConfigurationHash is malformed.")
    payload = dict(config)
    payload.pop("experimentConfigurationHash", None)
    actual = "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()
    if actual != expected:
        raise TrainingError(
            "The diagnostic experiment configuration hash does not match its content."
        )


def prepare_training_output(output: Path, config: Mapping[str, Any]) -> None:
    """Create a fresh output or permit only an identity-matched resume."""

    config_path = output / "training-config.json"
    if output.exists() and not output.is_dir():
        raise TrainingError("The configured training output is not a directory.")
    if output.exists() and any(output.iterdir()):
        if not config_path.is_file():
            raise TrainingError(
                "Refusing to train into a nonempty output without a matching "
                "training-config.json receipt."
            )
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise TrainingError(
                "The existing training output has an unreadable configuration receipt."
            ) from error
        identity_fields = (
            "configurationHash",
            "experimentConfigurationHash",
            "pipelineCodeHash",
            "trainingInputHash",
            "output",
        )
        if any(existing.get(field) != config.get(field) for field in identity_fields):
            raise TrainingError(
                "Refusing to reuse a nonempty output whose experiment identity "
                "does not match this configuration."
            )
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(config_path, config)


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
    sparse_pixels: Any
    sparse_depths: Any
    sparse_point_ids: Any = None


@dataclasses.dataclass(frozen=True)
class TrainingSamplingPlan:
    epoch_slots: tuple[int, ...]
    weights: dict[int, int]
    endpoint_indices: frozenset[int]
    sparse_anchor_counts: dict[int, int]
    median_sparse_anchors: float


def bracketed_validation_indices(
    indices: Sequence[int],
    *,
    stride: int = VALIDATION_STRIDE,
    offset: int = VALIDATION_OFFSET,
    endpoint_guard: int = 1,
) -> set[int]:
    """Return deterministic held-out indices with trained neighbors on both sides.

    Video endpoints are reconstruction evidence, not honest novel-view probes: an
    endpoint has observations on only one temporal side.  Keep a configurable
    endpoint window in training and hold out only regularly spaced interior views.
    """

    ordered = list(indices)
    if stride <= 1 or not 0 <= offset < stride:
        raise TrainingError("The validation stride and offset are invalid.")
    guard = max(1, int(endpoint_guard))
    if len(ordered) <= guard * 2:
        return set()
    return {
        index
        for ordinal, index in enumerate(ordered)
        if ordinal % stride == offset
        and guard <= ordinal < len(ordered) - guard
    }


def build_training_sampling_plan(
    records: Sequence[ImageRecord],
    train_indices: Sequence[int],
    sequence_groups: Sequence[Sequence[int]],
    *,
    endpoint_window: int = ENDPOINT_SAMPLING_WINDOW,
    endpoint_multiplier: int = ENDPOINT_SAMPLING_MULTIPLIER,
    maximum_sparse_multiplier: int = MAXIMUM_SPARSE_ANCHOR_MULTIPLIER,
    frame_multipliers: Mapping[int, int] | None = None,
) -> TrainingSamplingPlan:
    """Build a deterministic integer-weighted camera epoch.

    Every trained camera occurs at least once.  Capture endpoints receive at
    least two slots, while cameras with unusually few SfM depth anchors receive
    up to four slots using a bounded inverse-median rule.  Taking the maximum,
    rather than multiplying both weights, prevents endpoint scenes from
    monopolizing an epoch.  ``frame_multipliers`` then multiplies the resolved
    weight of explicitly listed diagnostic offender frames only.
    """

    ordered_train = [int(index) for index in train_indices]
    if not ordered_train or len(set(ordered_train)) != len(ordered_train):
        raise TrainingError("Training sampling requires unique camera indices.")
    if endpoint_window <= 0 or endpoint_multiplier < 2:
        raise TrainingError("Endpoint sampling must reserve a positive 2x window.")
    if maximum_sparse_multiplier < endpoint_multiplier:
        raise TrainingError("Sparse-anchor sampling has an invalid multiplier cap.")
    train_set = set(ordered_train)
    endpoint_indices: set[int] = set()
    for group in sequence_groups:
        ordered_group = [int(index) for index in group]
        if not ordered_group:
            continue
        window = min(endpoint_window, len(ordered_group))
        endpoint_indices.update(ordered_group[:window])
        endpoint_indices.update(ordered_group[-window:])
    endpoint_indices.intersection_update(train_set)

    sparse_anchor_counts = {
        index: int(len(records[index].sparse_depths)) for index in ordered_train
    }
    positive_counts = sorted(
        count for count in sparse_anchor_counts.values() if count > 0
    )
    if positive_counts:
        middle = len(positive_counts) // 2
        if len(positive_counts) % 2:
            median_sparse_anchors = float(positive_counts[middle])
        else:
            median_sparse_anchors = float(
                (positive_counts[middle - 1] + positive_counts[middle]) / 2.0
            )
    else:
        median_sparse_anchors = 0.0

    weights: dict[int, int] = {}
    epoch_slots: list[int] = []
    for index in ordered_train:
        anchors = sparse_anchor_counts[index]
        sparse_weight = (
            maximum_sparse_multiplier
            if anchors <= 0 and median_sparse_anchors > 0.0
            else max(
                1,
                min(
                    maximum_sparse_multiplier,
                    math.ceil(median_sparse_anchors / max(anchors, 1)),
                ),
            )
        )
        endpoint_weight = endpoint_multiplier if index in endpoint_indices else 1
        weight = max(endpoint_weight, sparse_weight)
        if frame_multipliers is not None:
            multiplier = int(frame_multipliers.get(index, 1))
            if multiplier > 1:
                weight *= multiplier
        weights[index] = weight
        epoch_slots.extend([index] * weight)
    return TrainingSamplingPlan(
        epoch_slots=tuple(epoch_slots),
        weights=weights,
        endpoint_indices=frozenset(endpoint_indices),
        sparse_anchor_counts=sparse_anchor_counts,
        median_sparse_anchors=median_sparse_anchors,
    )


def parse_frame_oversampling_config(
    config: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Parse the sealed diagnostic treatment before dataset construction."""

    if not isinstance(config.get("frameOversampling"), Mapping):
        return None
    raw = dict(config["frameOversampling"])
    try:
        multiplier = int(raw["multiplier"])
        frames = [str(name) for name in raw["frames"]]
    except (KeyError, TypeError, ValueError) as error:
        raise TrainingError(
            "The frame-oversampling configuration is incomplete."
        ) from error
    return {
        "schema": str(raw.get("schema", "")),
        "method": str(raw.get("method", "")),
        "multiplier": multiplier,
        "frames": frames,
    }


def apply_frame_oversampling(
    config: Mapping[str, Any],
    dataset: Any,
    receipt: dict[str, Any] | None,
) -> tuple[dict[int, int] | None, dict[str, Any] | None]:
    """Validate named cameras and apply their weights to the live dataset."""

    if receipt is None:
        return None, None
    record_names = {
        record.name: index for index, record in enumerate(dataset.records)
    }
    if not supported_frame_oversampling_contract(
        config,
        schema=receipt["schema"],
        method=receipt["method"],
        multiplier=receipt["multiplier"],
        frames=receipt["frames"],
        record_names=record_names,
    ):
        raise TrainingError(
            "The frame-oversampling contract is sealed to non-publishable "
            "diagnostics with 2-8x weight and explicitly named registered "
            "offender frames."
        )
    trainable_names = {
        dataset.records[index].name for index in dataset.train_indices
    }
    oversampled_train_indices = {
        record_names[name]
        for name in receipt["frames"]
        if name in trainable_names
    }
    if not oversampled_train_indices:
        raise TrainingError(
            "Frame oversampling listed no trainable camera; every listed "
            "frame was excluded as held-out validation evidence."
        )
    multipliers = {
        index: int(receipt["multiplier"])
        for index in oversampled_train_indices
    }
    dataset.training_sampling_plan = build_training_sampling_plan(
        dataset.records,
        dataset.train_indices,
        dataset.sequence_groups,
        frame_multipliers=multipliers,
    )
    receipt["trainableFrames"] = sorted(
        dataset.records[index].name for index in oversampled_train_indices
    )
    receipt["heldOutFrames"] = sorted(
        name for name in receipt["frames"] if name not in trainable_names
    )
    return multipliers, receipt


def apply_appearance_frame_selection(
    config: Mapping[str, Any], dataset: Any
) -> dict[str, Any] | None:
    """Keep all registered poses while restricting appearance optimization.

    This diagnostic treatment separates camera-path evidence from RGB fitting
    evidence. The capture-health receipt is hash verified, and both main fit and
    final fit use only its selected frames. Rejected cameras remain in
    ``dataset.records`` for path playback and later pose diagnostics.
    """

    raw = config.get("appearanceFrameSelection")
    dataset.appearance_indices = list(range(len(dataset.records)))
    if raw is None:
        return None
    provenance = config.get("diagnosticProvenance")
    if (
        not isinstance(raw, Mapping)
        or not isinstance(provenance, Mapping)
        or provenance.get("nonPublishable") is not True
        or raw.get("schema") != APPEARANCE_FRAME_SELECTION_SCHEMA
        or raw.get("method") != CAPTURE_HEALTH_SELECTION_METHOD
    ):
        raise TrainingError(
            "Appearance frame selection is sealed to a non-publishable "
            "capture-health diagnostic."
        )
    path_value = raw.get("captureHealthPath")
    expected_hash = raw.get("captureHealthSha256")
    if (
        not isinstance(path_value, str)
        or not isinstance(expected_hash, str)
        or not expected_hash.startswith("sha256:")
    ):
        raise TrainingError("Appearance frame selection provenance is incomplete.")
    receipt_path = Path(path_value)
    if not receipt_path.is_file() or sha256_file(receipt_path) != expected_hash:
        raise TrainingError("The capture-health receipt failed hash verification.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        selection = receipt["selection"]
        selected_names = [str(name) for name in selection["selectedFrames"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise TrainingError("The capture-health receipt is malformed.") from error
    if (
        receipt.get("schema") != CAPTURE_HEALTH_SCHEMA
        or selection.get("method") != CAPTURE_HEALTH_SELECTION_METHOD
        or int(selection.get("selectedCount", -1)) != len(selected_names)
        or len(selected_names) != len(set(selected_names))
    ):
        raise TrainingError("The capture-health selection contract is invalid.")
    record_names = {record.name: index for index, record in enumerate(dataset.records)}
    unknown = sorted(set(selected_names) - set(record_names))
    if unknown:
        raise TrainingError(
            "Capture health selected unregistered frames: " + ", ".join(unknown[:5])
        )
    selected_indices = sorted(record_names[name] for name in selected_names)
    if len(selected_indices) < 16 or len(selected_indices) * 4 < len(dataset.records):
        raise TrainingError(
            "Appearance selection retained too little evidence for a bounded diagnostic."
        )
    selected_set = set(selected_indices)
    selected_validation = set(dataset.validation_indices) & selected_set
    if not selected_validation:
        raise TrainingError("Appearance selection retained no held-out validation camera.")
    selected_training = [
        index for index in selected_indices if index not in selected_validation
    ]
    if not selected_training:
        raise TrainingError("Appearance selection retained no training camera.")
    selected_groups = [
        [index for index in group if index in selected_set]
        for group in dataset.sequence_groups
    ]
    selected_groups = [group for group in selected_groups if group]
    dataset.appearance_indices = selected_indices
    dataset.validation_indices = selected_validation
    dataset.train_indices = selected_training
    dataset.sequence_groups = selected_groups
    dataset.training_sampling_plan = build_training_sampling_plan(
        dataset.records,
        dataset.train_indices,
        dataset.sequence_groups,
    )
    return {
        "schema": APPEARANCE_FRAME_SELECTION_SCHEMA,
        "method": CAPTURE_HEALTH_SELECTION_METHOD,
        "captureHealthPath": str(receipt_path),
        "captureHealthSha256": expected_hash,
        "registeredFrames": len(dataset.records),
        "appearanceFrames": len(selected_indices),
        "trainingFrames": len(selected_training),
        "validationFrames": len(selected_validation),
        "poseOnlyFrames": len(dataset.records) - len(selected_indices),
    }


def geometry_render_requirements(
    *,
    sparse_depth_weight: float = 0.0,
    depth_layer_variance_weight: float = 0.0,
    driving_surface_variance_weight: float = 0.0,
    dense_relative_depth_weight: float = 0.0,
    road_surface_depth_weight: float = 0.0,
    surface_alignment_weight: float = 0.0,
    road_planarity_weight: float = 0.0,
    cross_view_depth_weight: float = 0.0,
    semantic_sky_opacity_weight: float = 0.0,
    surfel_depth_distortion_weight: float = 0.0,
    surfel_normal_consistency_weight: float = 0.0,
) -> dict[str, bool]:
    """Declare renderer outputs from objective needs in one auditable place."""

    needs_depth = any(
        weight > 0.0
        for weight in (
            sparse_depth_weight,
            depth_layer_variance_weight,
            driving_surface_variance_weight,
            dense_relative_depth_weight,
            road_surface_depth_weight,
            surface_alignment_weight,
            road_planarity_weight,
            cross_view_depth_weight,
        )
    )
    needs_surfel_aux = any(
        weight > 0.0
        for weight in (
            surfel_depth_distortion_weight,
            surfel_normal_consistency_weight,
        )
    )
    needs_geometry_alpha = needs_depth or semantic_sky_opacity_weight > 0.0
    return {
        "depth": needs_depth,
        "geometryAlpha": needs_geometry_alpha,
        "surfelAux": needs_surfel_aux,
        "geometryRender": needs_geometry_alpha or needs_surfel_aux,
    }


def freeze_density_growth_at_target(strategy: Any) -> None:
    """Freeze gsplat growth without disabling its scheduled pruning pass.

    ``DefaultStrategy.step_post_backward`` returns before both growth *and*
    pruning when ``step >= refine_stop_iter``. Reusing that stop switch for a
    Gaussian-count budget therefore leaves oversized screen-space splats in
    the scene. The default strategy also allows screen-radius-only splitting,
    so both its gradient and screen-radius growth triggers must be disabled.
    Its refinement stop remains untouched: opacity and screen-size pruning
    continue until the configured geometry-freeze step.
    """

    strategy.grow_grad2d = math.inf
    strategy.grow_scale2d = math.inf


class DeterministicWeightedEpochSampler:
    """Resume-safe shuffled epochs whose order is content-bound."""

    def __init__(self, slots: Sequence[int], seed: str, phase: str) -> None:
        self._slots = tuple(int(index) for index in slots)
        if not self._slots:
            raise TrainingError("A deterministic sampling epoch cannot be empty.")
        self._seed = str(seed)
        self._phase = str(phase)
        self._epoch = -1
        self._order: list[int] = []

    def index(self, offset: int) -> int:
        if offset < 0:
            raise TrainingError("A deterministic sampling offset cannot be negative.")
        epoch = offset // len(self._slots)
        if epoch != self._epoch:
            self._epoch = epoch
            self._order = list(self._slots)
            random.Random(f"{self._seed}:{self._phase}:{epoch}").shuffle(self._order)
        return self._order[offset % len(self._slots)]


def build_cross_view_pair_plan(
    records: Sequence[ImageRecord],
    train_indices: Sequence[int],
    sequence_groups: Sequence[Sequence[int]],
    observation_ids: Mapping[int, frozenset[int]],
    *,
    minimum_shared_tracks: int = 30,
    minimum_frame_gap: int = 8,
    maximum_frame_gap: int = 48,
    maximum_rotation_degrees: float = 60.0,
) -> tuple[dict[int, int], dict[str, Any]]:
    """Select deterministic calibrated pairs with measured SfM co-visibility.

    Long-baseline pairs provide a useful depth-consistency signal, but only
    when enough of the same reconstructed tracks remain visible.  The score
    balances baseline and shared-track evidence and never uses a held-out
    camera, preserving the pre-final-fit validation contract.
    """

    import numpy as np

    train_set = {int(index) for index in train_indices}
    pair_by_source: dict[int, int] = {}
    selected_shared: list[int] = []
    selected_baselines: list[float] = []
    selected_rotations: list[float] = []
    for group in sequence_groups:
        positions = {int(index): ordinal for ordinal, index in enumerate(group)}
        eligible = [int(index) for index in group if int(index) in train_set]
        for source in eligible:
            source_ids = observation_ids.get(source, frozenset())
            source_pose = np.asarray(records[source].camera_to_world, dtype=np.float64)
            candidates: list[tuple[float, int, int, float, float]] = []
            for target in eligible:
                gap = abs(positions[target] - positions[source])
                if not minimum_frame_gap <= gap <= maximum_frame_gap:
                    continue
                shared = len(source_ids.intersection(observation_ids.get(target, frozenset())))
                if shared < minimum_shared_tracks:
                    continue
                target_pose = np.asarray(records[target].camera_to_world, dtype=np.float64)
                relative_rotation = source_pose[:3, :3].T @ target_pose[:3, :3]
                cosine = float(np.clip((np.trace(relative_rotation) - 1.0) * 0.5, -1.0, 1.0))
                rotation_degrees = math.degrees(math.acos(cosine))
                if rotation_degrees > maximum_rotation_degrees:
                    continue
                baseline = float(
                    np.linalg.norm(source_pose[:3, 3] - target_pose[:3, 3])
                )
                if not math.isfinite(baseline) or baseline <= 1e-6:
                    continue
                score = baseline * math.log1p(shared)
                candidates.append((score, target, shared, baseline, rotation_degrees))
            if not candidates:
                continue
            _, target, shared, baseline, rotation = max(
                candidates, key=lambda item: (item[0], -item[1])
            )
            pair_by_source[source] = target
            selected_shared.append(shared)
            selected_baselines.append(baseline)
            selected_rotations.append(rotation)

    def median(values: Sequence[float | int]) -> float:
        if not values:
            return 0.0
        ordered = sorted(float(value) for value in values)
        middle = len(ordered) // 2
        return (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) * 0.5
        )

    receipt = {
        "method": "colmap-shared-track-baseline-score-v1",
        "pairCount": len(pair_by_source),
        "eligibleTrainingViews": len(train_set),
        "minimumSharedTracks": minimum_shared_tracks,
        "minimumFrameGap": minimum_frame_gap,
        "maximumFrameGap": maximum_frame_gap,
        "maximumRotationDegrees": maximum_rotation_degrees,
        "medianSharedTracks": median(selected_shared),
        "minimumSelectedSharedTracks": min(selected_shared, default=0),
        "medianNormalizedBaseline": median(selected_baselines),
        "medianRotationDegrees": median(selected_rotations),
    }
    return pair_by_source, receipt


def build_sparse_track_pair_samples(
    records: Sequence[ImageRecord],
    pairs: Mapping[int, int],
) -> dict[int, dict[str, Any]]:
    """Bind each selected camera pair to the same external COLMAP tracks.

    Unlike dense self-reprojection, both targets come from one triangulated
    point in the calibrated SfM solve.  The samples therefore cannot make two
    mutually drifting rendered depth fields supervise one another.
    """

    import numpy as np

    result: dict[int, dict[str, Any]] = {}
    for source_index, target_index in pairs.items():
        source = records[int(source_index)]
        target = records[int(target_index)]
        if source.sparse_point_ids is None or target.sparse_point_ids is None:
            continue
        source_ids = np.asarray(source.sparse_point_ids, dtype=np.int64).reshape(-1)
        target_ids = np.asarray(target.sparse_point_ids, dtype=np.int64).reshape(-1)
        if (
            len(source_ids) != len(source.sparse_depths)
            or len(target_ids) != len(target.sparse_depths)
        ):
            raise TrainingError("Sparse COLMAP point IDs do not match their observations.")
        source_lookup = {int(point_id): offset for offset, point_id in enumerate(source_ids)}
        target_lookup = {int(point_id): offset for offset, point_id in enumerate(target_ids)}
        shared = sorted(source_lookup.keys() & target_lookup.keys())
        if not shared:
            continue
        source_offsets = np.asarray([source_lookup[point_id] for point_id in shared])
        target_offsets = np.asarray([target_lookup[point_id] for point_id in shared])
        result[int(source_index)] = {
            "targetIndex": int(target_index),
            "pointIds": np.asarray(shared, dtype=np.int64),
            "sourcePixels": np.asarray(source.sparse_pixels, dtype=np.float32)[source_offsets],
            "sourceDepths": np.asarray(source.sparse_depths, dtype=np.float32)[source_offsets],
            "targetPixels": np.asarray(target.sparse_pixels, dtype=np.float32)[target_offsets],
            "targetDepths": np.asarray(target.sparse_depths, dtype=np.float32)[target_offsets],
        }
    return result


def semantic_sparse_point_filter(
    reconstruction: Any,
    point_ids: Any,
    semantic_root: Path,
) -> tuple[Any, dict[str, Any]]:
    """Reject sparse seeds consistently observed as sky or dynamic content.

    COLMAP may triangulate clouds, sky edges, reflections, vehicles, or people.
    Zeroing their later photometric loss is insufficient because an initialized
    Gaussian can otherwise survive without receiving an opacity gradient.  This
    filter votes only at the point's own calibrated track observations and
    requires repeated semantic evidence, so a single segmentation mistake does
    not remove an otherwise reliable static point.
    """

    import cv2
    import numpy as np

    image_masks: dict[int, Any] = {}
    image_sizes: dict[int, tuple[int, int]] = {}
    missing_images = 0
    for image_id, image in reconstruction.images.items():
        semantic_path = semantic_root / Path(image.name).with_suffix(".png")
        semantic = cv2.imread(str(semantic_path), cv2.IMREAD_GRAYSCALE)
        if semantic is None:
            missing_images += 1
            continue
        camera = reconstruction.cameras[image.camera_id]
        image_masks[int(image_id)] = semantic
        image_sizes[int(image_id)] = (int(camera.width), int(camera.height))

    identifiers = np.asarray(point_ids, dtype=np.int64)
    keep = np.ones(len(identifiers), dtype=bool)
    excluded_labels = {0, 17, 18, 19, 20, 21, 22}
    classified_points = 0
    rejected_points = 0
    sky_rejected = 0
    dynamic_rejected = 0
    observations = 0
    for ordinal, point_id in enumerate(identifiers.tolist()):
        point = reconstruction.points3D[int(point_id)]
        labels: list[int] = []
        for element in point.track.elements:
            image_id = int(element.image_id)
            semantic = image_masks.get(image_id)
            source_size = image_sizes.get(image_id)
            if semantic is None or source_size is None:
                continue
            image = reconstruction.images[image_id]
            point_index = int(element.point2D_idx)
            if point_index < 0 or point_index >= len(image.points2D):
                continue
            xy = np.asarray(image.points2D[point_index].xy, dtype=np.float64)
            if xy.shape != (2,) or not np.isfinite(xy).all():
                continue
            source_width, source_height = source_size
            x = int(np.clip(round((xy[0] + 0.5) * semantic.shape[1] / source_width - 0.5), 0, semantic.shape[1] - 1))
            y = int(np.clip(round((xy[1] + 0.5) * semantic.shape[0] / source_height - 0.5), 0, semantic.shape[0] - 1))
            labels.append(int(semantic[y, x]))
        observations += len(labels)
        if len(labels) < 2:
            continue
        classified_points += 1
        excluded = sum(label in excluded_labels for label in labels)
        if excluded / len(labels) < 0.60:
            continue
        keep[ordinal] = False
        rejected_points += 1
        sky_votes = sum(label == 17 for label in labels)
        dynamic_votes = sum(18 <= label <= 22 for label in labels)
        if sky_votes >= dynamic_votes:
            sky_rejected += 1
        else:
            dynamic_rejected += 1

    return keep, {
        "method": "calibrated-track-semantic-majority-v1",
        "minimumObservations": 2,
        "exclusionVoteFraction": 0.60,
        "classifiedPoints": classified_points,
        "rejectedPoints": rejected_points,
        "skyRejectedPoints": sky_rejected,
        "dynamicRejectedPoints": dynamic_rejected,
        "semanticObservations": observations,
        "missingSemanticImages": missing_images,
    }


class ColmapDataset:
    def __init__(
        self,
        root: Path,
        factor: int,
        cache_size: int = 8,
        max_point_error: float = 3.0,
        require_static_masks: bool = False,
        geometry_root: Path | None = None,
        require_geometry_priors: bool = False,
        require_certified_sky_evidence: bool = False,
    ) -> None:
        import numpy as np
        try:
            import pycolmap
        except ModuleNotFoundError:
            import servo_colmap as pycolmap
            self.colmap_runtime = "servo-native-binary-reader-v1"
        else:
            self.colmap_runtime = "pycolmap"

        self.root = root.resolve()
        self.factor = max(1, int(factor))
        self.image_root = self.root / "images"
        self.mask_root = self.root / "masks"
        self.geometry_root = geometry_root.resolve() if geometry_root else None
        self.depth_prior_root = (
            self.geometry_root / "depth" if self.geometry_root else None
        )
        self.semantic_prior_root = (
            self.geometry_root / "semantics" if self.geometry_root else None
        )
        self.certified_sky_evidence_root = (
            self.geometry_root / CERTIFIED_SKY_EVIDENCE_DIRECTORY
            if self.geometry_root
            else None
        )
        sparse_candidates = [self.root / "sparse", self.root / "sparse" / "0"]
        model_root = next(
            (candidate for candidate in sparse_candidates if candidate.is_dir() and any(candidate.glob("cameras.*"))),
            None,
        )
        if model_root is None:
            raise TrainingError(f"No COLMAP model was found beneath {self.root}.")
        reconstruction = pycolmap.Reconstruction(str(model_root))
        point_items = list(reconstruction.points3D.items())
        point_ids = np.asarray([int(point_id) for point_id, _ in point_items], dtype=np.int64)
        points = [point for _, point in point_items]
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
        point_ids = point_ids[confidence]
        if len(xyz) > 500_000:
            generator = np.random.default_rng(42)
            indices = np.sort(generator.choice(len(xyz), 500_000, replace=False))
            xyz = xyz[indices]
            rgb = rgb[indices]
            point_ids = point_ids[indices]

        semantic_seed_stats: dict[str, Any] = {
            "method": "disabled",
            "rejectedPoints": 0,
        }
        if self.semantic_prior_root is not None and self.semantic_prior_root.is_dir():
            semantic_keep, semantic_seed_stats = semantic_sparse_point_filter(
                reconstruction,
                point_ids,
                self.semantic_prior_root,
            )
            xyz = xyz[semantic_keep]
            rgb = rgb[semantic_keep]
            point_ids = point_ids[semantic_keep]
            if len(xyz) < 100:
                raise TrainingError(
                    "Fewer than 100 reliable static sparse points remain after "
                    "semantic sky/dynamic filtering."
                )

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
        point_ids = point_ids[within_scene]
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
            "semanticSparsePointFilter": semantic_seed_stats,
        }
        xyz = (xyz - center[None, :]) * scale
        self.points = xyz.astype(np.float32, copy=False)
        self.colors = (rgb / 255.0).clip(0.0, 1.0).astype(np.float32, copy=False)

        reliable_point_ids = {int(point_id) for point_id in point_ids.tolist()}
        images_by_name = {
            image.name: image for image in reconstruction.images.values() if image.has_pose
        }
        sparse_observation_counts: list[int] = []

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
            sparse_pixels: list[list[float]] = []
            sparse_depths: list[float] = []
            sparse_point_ids: list[int] = []
            source_image = images_by_name.get(name)
            if source_image is not None:
                camera_from_world = np.asarray(
                    source_image.cam_from_world().matrix(), dtype=np.float64
                )
                for observation in source_image.points2D:
                    if not observation.has_point3D():
                        continue
                    point_id = int(observation.point3D_id)
                    if point_id not in reliable_point_ids:
                        continue
                    point = reconstruction.points3D[point_id]
                    point_camera = (
                        camera_from_world[:, :3]
                        @ np.asarray(point.xyz, dtype=np.float64)
                        + camera_from_world[:, 3]
                    )
                    xy = np.asarray(observation.xy, dtype=np.float64)
                    depth = float(point_camera[2] * scale)
                    if (
                        xy.shape == (2,)
                        and np.isfinite(xy).all()
                        and math.isfinite(depth)
                        and depth > 1e-5
                        and 0.0 <= xy[0] < width
                        and 0.0 <= xy[1] < height
                    ):
                        sparse_pixels.append(
                            [
                                float(xy[0] * scaled_width / width),
                                float(xy[1] * scaled_height / height),
                            ]
                        )
                        sparse_depths.append(depth)
                        sparse_point_ids.append(point_id)
            sparse_pixels_array = np.asarray(sparse_pixels, dtype=np.float32).reshape(-1, 2)
            sparse_depths_array = np.asarray(sparse_depths, dtype=np.float32)
            sparse_point_ids_array = np.asarray(sparse_point_ids, dtype=np.int64)
            sparse_observation_counts.append(len(sparse_depths_array))
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
                    sparse_pixels=sparse_pixels_array,
                    sparse_depths=sparse_depths_array,
                    sparse_point_ids=sparse_point_ids_array,
                )
            )
        self.initialization_stats["sparseDepthObservations"] = int(
            sum(sparse_observation_counts)
        )
        self.initialization_stats["medianSparseDepthObservationsPerImage"] = float(
            np.median(sparse_observation_counts)
        )
        grouped: dict[str, list[int]] = collections.defaultdict(list)
        for index, record in enumerate(self.records):
            grouped[Path(record.name).parent.as_posix()].append(index)
        self.validation_indices: set[int] = set()
        self.path_stress_indices: set[int] = set()
        static_indices: list[int] = []
        sequence_groups: list[list[int]] = []
        for group, indices in sorted(grouped.items()):
            if Path(group).name.startswith("video-"):
                sequence_groups.append(indices)
                # The hard novel-view gate is distributed over the whole
                # capture, so every withheld view remains bracketed by observed
                # neighbors. Endpoint windows remain training evidence because
                # they have observations on only one temporal side.
                if len(indices) >= 5:
                    self.validation_indices.update(
                        bracketed_validation_indices(
                            indices,
                            endpoint_guard=ENDPOINT_SAMPLING_WINDOW,
                        )
                    )
            else:
                static_indices.extend(indices)
        self.validation_indices.update(
            bracketed_validation_indices(
                static_indices,
                endpoint_guard=1,
            )
        )
        if not self.validation_indices:
            fallback_candidates = [
                index
                for indices in sequence_groups
                for index in indices[1:-1]
            ]
            if not fallback_candidates:
                fallback_candidates = static_indices[1:-1]
            if not fallback_candidates:
                fallback_candidates = list(range(1, len(self.records) - 1))
            if not fallback_candidates:
                raise TrainingError(
                    "The validation policy has no interior camera to hold out."
                )
            self.validation_indices = {
                fallback_candidates[len(fallback_candidates) // 2]
            }
        self.validation_policy = (
            "interleaved-every-8th-interior-bracketed-endpoint-guard-8/"
            "final-all-camera-audit-v4"
        )
        excluded_indices = self.validation_indices
        self.train_indices = [
            index for index in range(len(self.records)) if index not in excluded_indices
        ]
        if not self.train_indices:
            raise TrainingError("The validation policy left no images for training.")
        observation_ids: dict[int, frozenset[int]] = {}
        for index, record in enumerate(self.records):
            source_image = images_by_name.get(record.name)
            observation_ids[index] = frozenset(
                int(observation.point3D_id)
                for observation in (
                    source_image.points2D if source_image is not None else ()
                )
                if observation.has_point3D()
                and int(observation.point3D_id) in reliable_point_ids
            )
        (
            self.cross_view_pairs,
            self.cross_view_pair_receipt,
        ) = build_cross_view_pair_plan(
            self.records,
            self.train_indices,
            sequence_groups,
            observation_ids,
        )
        self.cross_view_sparse_tracks = build_sparse_track_pair_samples(
            self.records,
            self.cross_view_pairs,
        )
        sparse_pair_counts = [
            len(samples["pointIds"])
            for samples in self.cross_view_sparse_tracks.values()
        ]
        self.cross_view_pair_receipt["sparseTrackPairCount"] = len(
            self.cross_view_sparse_tracks
        )
        self.cross_view_pair_receipt["medianSparseTracks"] = float(
            np.median(sparse_pair_counts) if sparse_pair_counts else 0.0
        )
        self.cross_view_pair_receipt["minimumSparseTracks"] = int(
            min(sparse_pair_counts, default=0)
        )
        self.training_sampling_plan = build_training_sampling_plan(
            self.records,
            self.train_indices,
            sequence_groups,
        )
        self.sequence_groups = [
            list(group) for group in sequence_groups
        ]
        missing_masks = [
            record.name
            for record in self.records
            if not (self.mask_root / record.name).is_file()
        ]
        if require_static_masks and missing_masks:
            raise TrainingError(
                "Static-confidence masks are missing for registered images: "
                + ", ".join(missing_masks[:5])
            )
        self.static_confidence_masks = not missing_masks
        self.initialization_stats["staticConfidenceMasks"] = (
            len(self.records) - len(missing_masks)
        )
        missing_geometry: list[str] = []
        if self.geometry_root is not None:
            for record in self.records:
                depth_path = self.depth_prior_root / Path(record.name).with_suffix(".npz")
                semantic_path = self.semantic_prior_root / Path(record.name).with_suffix(".png")
                if not depth_path.is_file() or not semantic_path.is_file():
                    missing_geometry.append(record.name)
        elif require_geometry_priors:
            missing_geometry = [record.name for record in self.records]
        if require_geometry_priors and missing_geometry:
            raise TrainingError(
                "Dense geometry priors are missing for registered images: "
                + ", ".join(missing_geometry[:5])
            )
        self.geometry_priors = self.geometry_root is not None and not missing_geometry
        self.initialization_stats["geometryPriors"] = (
            len(self.records) - len(missing_geometry) if self.geometry_root else 0
        )
        missing_sky_evidence: list[str] = []
        if self.certified_sky_evidence_root is not None:
            missing_sky_evidence = [
                record.name
                for record in self.records
                if not (
                    self.certified_sky_evidence_root
                    / Path(record.name).with_suffix(".png")
                ).is_file()
            ]
        elif require_certified_sky_evidence:
            missing_sky_evidence = [record.name for record in self.records]
        if require_certified_sky_evidence and missing_sky_evidence:
            raise TrainingError(
                "Temporally certified sky evidence is missing for registered images: "
                + ", ".join(missing_sky_evidence[:5])
            )
        self.certified_sky_evidence = (
            self.certified_sky_evidence_root is not None and not missing_sky_evidence
        )
        self.initialization_stats["certifiedSkyEvidence"] = (
            len(self.records) - len(missing_sky_evidence)
            if self.certified_sky_evidence_root is not None
            else 0
        )
        self._cache: collections.OrderedDict[int, Any] = collections.OrderedDict()
        self._prior_cache: collections.OrderedDict[int, Any] = collections.OrderedDict()
        self._sky_evidence_cache: collections.OrderedDict[int, Any] = collections.OrderedDict()
        self._cache_size = max(1, cache_size)

    def __len__(self) -> int:
        return len(self.records)

    def load(self, index: int) -> tuple[Any, Any, Any, Any]:
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
            mask_path = self.mask_root / record.name
            if mask_path.is_file():
                with Image.open(mask_path) as mask_image:
                    mask_image = mask_image.convert("L")
                    if mask_image.size != (pixels.shape[1], pixels.shape[0]):
                        mask_image = mask_image.resize(
                            (pixels.shape[1], pixels.shape[0]),
                            Image.Resampling.BILINEAR,
                        )
                    confidence = np.asarray(mask_image, dtype=np.uint8).copy()
            else:
                confidence = np.full(pixels.shape[:2], 255, dtype=np.uint8)
            cached = (torch.from_numpy(pixels), torch.from_numpy(confidence))
        self._cache[index] = cached
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        record = self.records[index]
        return (
            cached[0],
            torch.from_numpy(record.camera_to_world.copy()),
            torch.from_numpy(record.calibration.copy()),
            cached[1],
        )

    def load_priors(self, index: int) -> tuple[Any, Any, Any]:
        """Load relative depth, road-surface depth, and stable semantic IDs."""

        import cv2
        import numpy as np
        import torch

        if not self.geometry_priors or self.depth_prior_root is None or self.semantic_prior_root is None:
            raise TrainingError("Dense geometry priors were not configured for this dataset.")
        cached = self._prior_cache.pop(index, None)
        if cached is None:
            record = self.records[index]
            depth_path = self.depth_prior_root / Path(record.name).with_suffix(".npz")
            semantic_path = self.semantic_prior_root / Path(record.name).with_suffix(".png")
            try:
                with np.load(depth_path, allow_pickle=False) as archive:
                    relative = np.asarray(
                        archive["relative_inverse_depth"], dtype=np.float32
                    ).copy()
                    road_depth = np.asarray(
                        archive["road_surface_depth"], dtype=np.float32
                    ).copy()
            except (OSError, KeyError, ValueError) as error:
                raise TrainingError(
                    f"Unable to load dense depth prior {depth_path.name}: {error}"
                ) from error
            semantic = cv2.imread(str(semantic_path), cv2.IMREAD_GRAYSCALE)
            if semantic is None:
                raise TrainingError(f"Unable to load semantic prior {semantic_path.name}.")
            if relative.ndim != 2 or road_depth.shape != relative.shape or semantic.shape != relative.shape:
                raise TrainingError(
                    f"Geometry prior shapes disagree for {record.name}."
                )
            if not np.isfinite(relative).all() or bool((relative < 0.0).any()):
                raise TrainingError(
                    f"Relative depth prior is invalid for {record.name}."
                )
            cached = (
                torch.from_numpy(relative),
                torch.from_numpy(road_depth),
                torch.from_numpy(semantic.copy()),
            )
        self._prior_cache[index] = cached
        while len(self._prior_cache) > self._cache_size:
            self._prior_cache.popitem(last=False)
        return cached

    def load_certified_sky_evidence(self, index: int) -> Any:
        """Load one tri-state, hash-bound sky-evidence raster.

        The trainer treats value 1 as the sole allowed opacity-loss target.
        Value 2 is observed non-sky evidence; 0 remains unknown.  This avoids
        converting uncertain OneFormer sky boundaries into destructive targets.
        """

        import cv2
        import numpy as np
        import torch

        if (
            not self.certified_sky_evidence
            or self.certified_sky_evidence_root is None
        ):
            raise TrainingError("Temporally certified sky evidence was not configured.")
        cached = self._sky_evidence_cache.pop(index, None)
        if cached is None:
            record = self.records[index]
            path = self.certified_sky_evidence_root / Path(record.name).with_suffix(
                ".png"
            )
            raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if raw is None or raw.dtype != np.uint8:
                raise TrainingError(f"Unable to load certified sky evidence {path.name}.")
            _, _, semantic = self.load_priors(index)
            if raw.shape != tuple(semantic.shape):
                raise TrainingError(
                    f"Certified sky evidence dimensions disagree for {record.name}."
                )
            if not np.all(
                np.isin(
                    raw,
                    [
                        0,
                        CERTIFIED_SKY_EVIDENCE_SKY,
                        CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY,
                    ],
                )
            ):
                raise TrainingError(f"Certified sky evidence labels are invalid for {record.name}.")
            cached = torch.from_numpy(raw.copy())
        self._sky_evidence_cache[index] = cached
        while len(self._sky_evidence_cache) > self._cache_size:
            self._sky_evidence_cache.popitem(last=False)
        return cached


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


def create_parameters(
    dataset: ColmapDataset,
    sh_degree: int,
    device: str,
    dual_opacity: bool = False,
    dual_opacity_initialization: str = "legacy-saturated-base-v1",
) -> Any:
    import torch

    points = torch.from_numpy(dataset.points)
    colors = torch.from_numpy(dataset.colors)
    scales = torch.from_numpy(nearest_scales(dataset.points)).unsqueeze(-1).repeat(1, 3)
    count = len(points)
    quaternions = torch.zeros((count, 4), dtype=torch.float32)
    quaternions[:, 0] = 1.0
    corrected_dual_opacity = (
        dual_opacity
        and dual_opacity_initialization == DUAL_OPACITY_CORRECTED_INITIALIZATION
    )
    initial_geometry_opacity = 0.1 if corrected_dual_opacity or not dual_opacity else 0.99
    opacities = torch.logit(
        torch.full((count,), initial_geometry_opacity, dtype=torch.float32)
    )
    coefficients = torch.zeros((count, (sh_degree + 1) ** 2, 3), dtype=torch.float32)
    coefficients[:, 0, :] = (colors - 0.5) / C0
    values = {
        "means": torch.nn.Parameter(points),
        "scales": torch.nn.Parameter(scales),
        "quats": torch.nn.Parameter(quaternions),
        "opacities": torch.nn.Parameter(opacities),
        "sh0": torch.nn.Parameter(coefficients[:, :1, :]),
        "shN": torch.nn.Parameter(coefficients[:, 1:, :]),
    }
    if dual_opacity:
        # Geometry opacity remains the parameter inspected by gsplat's
        # densifier/pruner.  Its high initial support is paired with a low RGB
        # gate whose product exactly matches legacy 0.1 initialization.  This
        # gives geometry and appearance separate capacity from the first step.
        initial_gate = 0.99 if corrected_dual_opacity else 0.1 / initial_geometry_opacity
        values["appearanceOpacityGates"] = torch.nn.Parameter(
            torch.logit(torch.full((count,), initial_gate, dtype=torch.float32))
        )
    return torch.nn.ParameterDict(values).to(device)


def parameters_from_state(
    state: dict[str, Any], device: str, dual_opacity: bool = False
) -> Any:
    import torch

    required = {"means", "scales", "quats", "opacities", "sh0", "shN"}
    if dual_opacity:
        required.add("appearanceOpacityGates")
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
    if "appearanceOpacityGates" in parameters:
        rates["appearanceOpacityGates"] = 5e-3
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


def ssim(prediction: Any, target: Any, weight: Any | None = None) -> Any:
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
    if weight is None:
        return score.mean()
    if weight.ndim != 4 or weight.shape[1] != 1:
        raise TrainingError("SSIM confidence must have shape [batch, 1, height, width].")
    if weight.shape[0] != score.shape[0] or weight.shape[2:] != score.shape[2:]:
        raise TrainingError("SSIM confidence dimensions do not match the image.")
    denominator = weight.sum().clamp_min(1e-6) * score.shape[1]
    return (score * weight).sum() / denominator


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
        "experimentConfigurationHash": config.get(
            "experimentConfigurationHash"
        ),
        "trainingInputHash": config["trainingInputHash"],
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
        if verification.get("experimentConfigurationHash") != config.get(
            "experimentConfigurationHash"
        ):
            raise TrainingError(
                "Checkpoint experiment configuration hash changed during save."
            )
        if verification.get("trainingInputHash") != config["trainingInputHash"]:
            raise TrainingError("Checkpoint training-input hash changed during save.")
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
        "experimentConfigurationHash": config.get(
            "experimentConfigurationHash"
        ),
        "trainingInputHash": config["trainingInputHash"],
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
    protected_names: set[str] = set()
    heldout_metrics_path = checkpoint_dir.parent / "heldout-metrics.json"
    if heldout_metrics_path.is_file():
        try:
            heldout_metrics = json.loads(heldout_metrics_path.read_text(encoding="utf-8"))
            heldout_checkpoint = heldout_metrics.get("checkpoint", {})
            protected_name = heldout_checkpoint.get("path")
            if isinstance(protected_name, str) and protected_name:
                protected_names.add(protected_name)
        except (OSError, json.JSONDecodeError):
            # A malformed held-out receipt is rejected by the trainer/worker.
            # Do not let checkpoint cleanup turn that recoverable validation
            # error into silent loss of the evaluated state.
            protected_names.update(path.name for path in checkpoints)
    newest_names = {path.name for path in checkpoints[-2:]}
    for stale in checkpoints:
        if stale.name in newest_names or stale.name in protected_names:
            continue
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
        if pointer_value.get("trainingInputHash") != config["trainingInputHash"]:
            archive_checkpoints(
                checkpoint_dir,
                "incompatible-input",
                "The training inputs changed; archived old checkpoints.",
            )
            return None
        if pointer_value.get("experimentConfigurationHash") != config.get(
            "experimentConfigurationHash"
        ):
            archive_checkpoints(
                checkpoint_dir,
                "incompatible",
                "experiment_configuration_changed",
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
        if (
            receipt.get("configurationHash") != config["configurationHash"]
            or receipt.get("experimentConfigurationHash")
            != config.get("experimentConfigurationHash")
            or receipt.get("trainingInputHash") != config["trainingInputHash"]
        ):
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
            or checkpoint.get("experimentConfigurationHash")
            != config.get("experimentConfigurationHash")
            or checkpoint.get("trainingInputHash") != config["trainingInputHash"]
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
    sh_degree: int | None,
    packed: bool,
    absgrad: bool,
    rasterization_mode: str,
    eps2d: float,
    render_mode: str = "RGB",
    colors_override: Any | None = None,
    backgrounds: Any | None = None,
    surfel_ablation: Mapping[str, Any] | None = None,
    geometry_opacity: bool = False,
) -> tuple[Any, Any, dict[str, Any]]:
    import torch

    # ``rasterize`` is also a public test/diagnostic entry point, so it cannot
    # assume that ``train`` or ``kernel-check`` already prepared gsplat.  Keep
    # every path on the same verified no-install native runtime; otherwise
    # gsplat falls back to JIT compilation on Windows.
    try:
        from servo_gsplat_runtime import prepare_gsplat_runtime
    except ModuleNotFoundError:
        # Tests may load this file directly from its path instead of executing
        # it as a script, in which case only the repository root is importable.
        from tools.reconstruction.servo_gsplat_runtime import prepare_gsplat_runtime

    prepare_gsplat_runtime()

    if surfel_ablation is not None:
        from gsplat.rendering import rasterization_2dgs

        scales = torch.exp(parameters["scales"])
        # A surfel has no extent along its normal axis. Pinning the third
        # scale keeps every splat planar for both rendering and export while
        # leaving the stored parameter untouched for the densifier.
        scales = torch.cat(
            [
                scales[..., :2],
                torch.full_like(scales[..., :1], SURFEL_MINIMUM_SCALE),
            ],
            dim=-1,
        )
        colors = (
            colors_override
            if colors_override is not None
            else torch.cat([parameters["sh0"], parameters["shN"]], dim=1)
        )
        if sh_degree is None and colors.dim() == 2:
            # Per-Gaussian feature overrides arrive as [N, D]; the unpacked
            # 2DGS kernel expects an explicit camera axis [..., C, N, D].
            colors = colors.unsqueeze(0)
        rendered, alpha, normals, depth_normals, distort, _median, meta = (
            rasterization_2dgs(
                means=parameters["means"],
                quats=parameters["quats"],
                scales=scales,
                opacities=gaussian_opacities(parameters, geometry_opacity),
                colors=colors,
                viewmats=torch.linalg.inv(camera_to_world),
                Ks=calibration,
                width=width,
                height=height,
                # gsplat 1.5.3 rasterization_2dgs never packs per-Gaussian
                # colors (the packing block is commented out upstream), so
                # packed=True raises inside rasterize_to_pixels_2dgs. The
                # diagnostic therefore always renders unpacked.
                packed=False,
                absgrad=absgrad,
                eps2d=eps2d,
                render_mode=render_mode,
                sh_degree=sh_degree,
                distloss=render_mode in ("D", "ED", "RGB+D", "RGB+ED"),
                near_plane=0.01,
                far_plane=1e4,
                backgrounds=None,
            )
        )
        # render_normals leave the kernel in camera space and are rotated to
        # world space by gsplat; depth_to_normal derives world-space normals
        # from the rendered expected depth, so both maps share one frame and
        # their cosine is the 2DGS normal-consistency residual.
        if depth_normals is not None and depth_normals.dim() == normals.dim() - 1:
            depth_normals = depth_normals.unsqueeze(0)
        meta["surfelNormal"] = normals
        meta["surfelDepthNormal"] = depth_normals
        meta["surfelDistortion"] = distort
        rendered = composite_raster_background(
            rendered,
            alpha,
            backgrounds,
            render_mode,
            3 if sh_degree is not None else int(colors.shape[-1]),
        )
        return rendered, alpha, meta

    from gsplat.rendering import rasterization

    colors = (
        colors_override
        if colors_override is not None
        else torch.cat([parameters["sh0"], parameters["shN"]], dim=1)
    )
    color_channels = 3 if sh_degree is not None else int(colors.shape[-1])
    rendered, alpha, information = rasterization(
        means=parameters["means"],
        quats=parameters["quats"],
        scales=torch.exp(parameters["scales"]),
        opacities=gaussian_opacities(parameters, geometry_opacity),
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
        render_mode=render_mode,
        sh_degree=sh_degree,
        near_plane=0.01,
        far_plane=1e4,
        # gsplat 1.5.3 rejects camera-shaped backgrounds in packed mode after
        # internally appending the depth channel.  Render transparent, then
        # perform the equivalent alpha composite on color channels only.
        backgrounds=None,
    )
    rendered = composite_raster_background(
        rendered,
        alpha,
        backgrounds,
        render_mode,
        color_channels,
    )
    return rendered, alpha, information


def front_to_back_intersection_weights(alphas: Any, ray_ids: Any) -> Any:
    """Return exact front-to-back compositing weights for sorted ray hits.

    ``gsplat.cuda.rasterize_to_indices_in_range`` returns intersections in
    near-to-far order within each pixel.  This segmented prefix product mirrors
    gsplat 1.5.3's reference alpha compositing without adding a nerfacc runtime
    dependency.
    """

    import torch

    if alphas.ndim != 1 or ray_ids.ndim != 1 or alphas.shape != ray_ids.shape:
        raise TrainingError("Contributor intersections must be matching vectors.")
    if len(alphas) == 0:
        return alphas
    if not bool(torch.isfinite(alphas).all()) or bool(
        ((alphas < 0.0) | (alphas >= 1.0)).any()
    ):
        raise TrainingError("Contributor intersection alpha is invalid.")
    if bool((ray_ids[1:] < ray_ids[:-1]).any()):
        raise TrainingError("Contributor intersections are not grouped by ray.")
    log_survival = torch.log1p(-alphas)
    exclusive_prefix = torch.cumsum(log_survival, dim=0) - log_survival
    starts = torch.ones_like(ray_ids, dtype=torch.bool)
    starts[1:] = ray_ids[1:] != ray_ids[:-1]
    segment_ids = torch.cumsum(starts.to(dtype=torch.int64), dim=0) - 1
    segment_prefix = exclusive_prefix[starts]
    transmittance = torch.exp(exclusive_prefix - segment_prefix[segment_ids])
    return alphas * transmittance


def contributor_sky_cleanup_loss(opacity_logits: Any, qualified: Any) -> Any:
    """Transparent-target BCE on pre-qualified Gaussian opacity logits only."""

    import torch
    import torch.nn.functional as functional

    if opacity_logits.ndim != 1 or qualified.ndim != 1:
        raise TrainingError("Contributor cleanup expects one-dimensional tensors.")
    if opacity_logits.shape != qualified.shape or qualified.dtype != torch.bool:
        raise TrainingError("Contributor cleanup mask does not match opacity logits.")
    if not bool(qualified.any()):
        return opacity_logits.sum() * 0.0
    return functional.softplus(opacity_logits[qualified]).mean()


def build_certified_sky_contributor_ledger(
    parameters: Any,
    dataset: Any,
    device: str,
    *,
    sh_degree: int,
    packed: bool,
    rasterization_mode: str,
    eps2d: float,
    audit_factor: int,
    minimum_weight: float,
    minimum_views: int,
    minimum_view_gap: int,
    cancel_path: Path,
    descriptor: Mapping[str, Any],
    config: Mapping[str, Any],
    output: Path,
) -> tuple[Any, dict[str, Any]]:
    """Attribute certified-sky and observed-non-sky support to Gaussian IDs.

    A Gaussian qualifies only when exact compositing contributions exceed the
    configured visibility floor in several temporally separated certified-sky
    views and no registered view contains equivalent observed-non-sky support.
    Density must already be frozen, so the returned IDs remain stable.
    """

    import torch
    from gsplat.cuda._wrapper import rasterize_to_indices_in_range

    count = int(len(parameters["means"]))
    sky_mass = torch.zeros(count, device=device, dtype=torch.float32)
    non_sky_mass = torch.zeros_like(sky_mass)
    sky_views = torch.zeros(count, device=device, dtype=torch.int32)
    non_sky_views = torch.zeros(count, device=device, dtype=torch.int32)
    last_sky_view = torch.full(
        (count,), -minimum_view_gap, device=device, dtype=torch.int32
    )
    observed_intersections = 0
    with torch.no_grad():
        for index in range(len(dataset)):
            if cancel_path.exists():
                raise TrainingCancelled(
                    "Contributor attribution stopped at a verified training state."
                )
            pixels_cpu, camera_cpu, calibration_cpu, _ = dataset.load(index)
            camera = camera_cpu.to(device, non_blocking=True).unsqueeze(0)
            calibration = calibration_cpu.to(device, non_blocking=True).unsqueeze(0)
            height = max(1, round(int(pixels_cpu.shape[0]) / audit_factor))
            width = max(1, round(int(pixels_cpu.shape[1]) / audit_factor))
            calibration = calibration.clone()
            calibration[:, 0, :] *= width / int(pixels_cpu.shape[1])
            calibration[:, 1, :] *= height / int(pixels_cpu.shape[0])
            evidence = resize_certified_sky_evidence(
                dataset.load_certified_sky_evidence(index),
                height,
                width,
                device,
            )[0, ..., 0]
            _, _, information = rasterize(
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
            if not packed:
                raise TrainingError("Contributor attribution requires packed gsplat mode.")
            gs_ids, pixel_ids, image_ids = rasterize_to_indices_in_range(
                0,
                1_000_000_000,
                torch.ones((height, width), device=device),
                information["means2d"],
                information["conics"],
                information["opacities"],
                width,
                height,
                int(information["tile_size"]),
                information["isect_offsets"][0],
                information["flatten_ids"],
            )
            if len(gs_ids) == 0:
                continue
            if bool((pixel_ids[1:] < pixel_ids[:-1]).any()):
                order = torch.argsort(pixel_ids, stable=True)
                gs_ids = gs_ids[order]
                pixel_ids = pixel_ids[order]
                image_ids = image_ids[order]
            pixel_x = pixel_ids % width
            pixel_y = pixel_ids // width
            coordinates = torch.stack([pixel_x, pixel_y], dim=-1).to(torch.float32) + 0.5
            deltas = coordinates - information["means2d"][gs_ids]
            conics = information["conics"][gs_ids]
            sigmas = 0.5 * (
                conics[:, 0] * deltas[:, 0].square()
                + conics[:, 2] * deltas[:, 1].square()
            ) + conics[:, 1] * deltas[:, 0] * deltas[:, 1]
            alphas = torch.clamp_max(
                information["opacities"][gs_ids] * torch.exp(-sigmas),
                0.999,
            ).clamp_min(0.0)
            ray_ids = image_ids * (height * width) + pixel_ids
            weights = front_to_back_intersection_weights(alphas, ray_ids)
            original_ids = information["gaussian_ids"][gs_ids].to(torch.int64)
            labels = evidence.reshape(-1)[pixel_ids]
            visible = weights >= minimum_weight
            sky_hits = visible & (labels == CERTIFIED_SKY_EVIDENCE_SKY)
            non_sky_hits = visible & (
                labels == CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY
            )
            observed_intersections += int(visible.sum().item())
            if bool(sky_hits.any()):
                sky_mass.scatter_add_(0, original_ids[sky_hits], weights[sky_hits])
                unique = torch.unique(original_ids[sky_hits])
                separated = index - last_sky_view[unique] >= minimum_view_gap
                accepted = unique[separated]
                sky_views[accepted] += 1
                last_sky_view[accepted] = index
            if bool(non_sky_hits.any()):
                non_sky_mass.scatter_add_(
                    0, original_ids[non_sky_hits], weights[non_sky_hits]
                )
                non_sky_views[torch.unique(original_ids[non_sky_hits])] += 1
            del information, gs_ids, pixel_ids, image_ids, weights
            if (index + 1) % 25 == 0 or index + 1 == len(dataset):
                emit(
                    "contributor_attribution_progress",
                    views=index + 1,
                    totalViews=len(dataset),
                )
    qualified = (sky_views >= minimum_views) & (non_sky_views == 0)
    mask_bytes = qualified.detach().to(device="cpu", dtype=torch.uint8).numpy().tobytes()
    ledger = {
        "schema": "servo.certified-sky-contributor-ledger/v1",
        "method": CONTRIBUTOR_SKY_CLEANUP_METHOD,
        "configurationHash": config["configurationHash"],
        "trainingInputHash": config["trainingInputHash"],
        "pipelineCodeHash": config["pipelineCodeHash"],
        "certifiedSkyEvidenceManifestSha256": descriptor["manifestSha256"],
        "gaussians": count,
        "views": len(dataset),
        "auditFactor": audit_factor,
        "minimumCompositingWeight": minimum_weight,
        "minimumTemporallySeparatedSkyViews": minimum_views,
        "minimumViewGap": minimum_view_gap,
        "observedIntersections": observed_intersections,
        "gaussiansWithCertifiedSkyEvidence": int((sky_views > 0).sum().item()),
        "gaussiansWithObservedNonSkyEvidence": int((non_sky_views > 0).sum().item()),
        "qualifiedGaussians": int(qualified.sum().item()),
        "qualifiedMaskSha256": "sha256:" + hashlib.sha256(mask_bytes).hexdigest(),
        "maximumSkyViewCount": int(sky_views.max().item()),
        "skyContributionMass": float(sky_mass.sum().item()),
        "observedNonSkyContributionMass": float(non_sky_mass.sum().item()),
        "meaning": (
            "Reversible opacity-loss targets only; no Gaussian was deleted. "
            "Any observed non-sky contribution vetoes qualification."
        ),
    }
    atomic_json(output / "certified-sky-contributor-ledger.json", ledger)
    emit("contributor_attribution_completed", **ledger)
    torch.cuda.empty_cache()
    return qualified, ledger


def gaussian_opacities(parameters: Any, geometry_only: bool = False) -> Any:
    """Return geometry opacity or the export-equivalent appearance opacity.

    The optional second gate follows StableGS's dual-opacity principle: depth,
    road, and sky constraints act on the base geometry opacity, while RGB uses
    the product.  Export bakes the product into a standard 3DGS opacity so the
    runtime and PLY format need no special-case representation.
    """

    import torch

    geometry = torch.sigmoid(parameters["opacities"])
    if geometry_only or "appearanceOpacityGates" not in parameters:
        return geometry
    return geometry * torch.sigmoid(parameters["appearanceOpacityGates"])


def reset_dual_opacity_preserving_product(
    parameters: Any,
    optimizers: Mapping[str, Any],
    value: float,
) -> None:
    """Reset saturated base opacity without changing the rendered product."""

    import torch

    with torch.no_grad():
        product = gaussian_opacities(parameters).clamp(1e-6, 1.0 - 1e-6)
        base = torch.maximum(product, torch.full_like(product, float(value))).clamp(
            1e-6, 1.0 - 1e-6
        )
        gate = (product / base).clamp(1e-6, 1.0 - 1e-6)
        parameters["opacities"].data.copy_(torch.logit(base))
        parameters["appearanceOpacityGates"].data.copy_(torch.logit(gate))
        for name in ("opacities", "appearanceOpacityGates"):
            optimizer = optimizers[name]
            state = optimizer.state.get(parameters[name], {})
            for key in ("exp_avg", "exp_avg_sq"):
                value_tensor = state.get(key)
                if value_tensor is not None:
                    value_tensor.zero_()


def composite_raster_background(
    rendered: Any,
    alpha: Any,
    backgrounds: Any | None,
    render_mode: str,
    color_channels: int,
) -> Any:
    """Composite color features without changing depth or auxiliary channels."""
    import torch

    if backgrounds is None or render_mode in {"D", "ED"}:
        return rendered
    if render_mode not in {"RGB", "RGB+D", "RGB+ED"}:
        raise TrainingError(f"Unsupported gsplat render mode: {render_mode}")
    expected_channels = color_channels + (
        1 if render_mode in {"RGB+D", "RGB+ED"} else 0
    )
    if color_channels < 1 or int(rendered.shape[-1]) != expected_channels:
        raise TrainingError(
            "The gsplat raster output does not match the requested color/depth "
            f"layout ({tuple(rendered.shape)}, {render_mode}, {color_channels})."
        )
    constant_shape = tuple(rendered.shape[:-3]) + (color_channels,)
    image_shape = tuple(rendered.shape[:-1]) + (color_channels,)
    if tuple(backgrounds.shape) not in {constant_shape, image_shape}:
        raise TrainingError(
            "The raster background must be either camera-constant or an exact "
            "per-pixel color image; "
            f"got {tuple(backgrounds.shape)} for {tuple(rendered.shape)}."
        )
    if tuple(alpha.shape) != tuple(rendered.shape[:-1]) + (1,):
        raise TrainingError(
            "The gsplat alpha shape does not match the raster output: "
            f"{tuple(alpha.shape)} versus {tuple(rendered.shape)}."
        )

    background = backgrounds
    if tuple(background.shape) == constant_shape:
        while background.ndim < rendered.ndim:
            background = background.unsqueeze(-2)
    composited = (
        rendered[..., :color_channels]
        + (1.0 - alpha) * background
    )
    if expected_channels == color_channels:
        return composited
    return torch.cat([composited, rendered[..., color_channels:]], dim=-1)


def load_observed_directional_environment(
    geometry_root: Path | None,
    descriptor: Any,
    device: str,
) -> Any | None:
    """Load verified observed sky evidence from the committed geometry stage.

    ``geometryRoot`` is intentionally the only allowed private filesystem root.
    The public descriptor contains a bundle-relative asset path and hash, so a
    training config cannot redirect the renderer to an arbitrary local image.
    ``None`` remains a legacy/direct-diagnostic fallback; production worker
    configs require the descriptor before this trainer is launched.
    """

    if descriptor is None:
        return None
    if geometry_root is None:
        raise TrainingError(
            "Observed directional environment requires a committed geometry root."
        )
    try:
        from servo_environment import EnvironmentError, load_observed_directional_environment as load_environment

        return load_environment(geometry_root, descriptor, device=device)
    except (EnvironmentError, OSError, ValueError) as error:
        raise TrainingError(
            f"Observed directional environment evidence is invalid: {error}"
        ) from error


def validate_certified_sky_evidence_descriptor(
    geometry_root: Path | None,
    descriptor: Any,
) -> dict[str, Any]:
    """Bind temporal sky evidence to the immutable geometry-stage receipt."""

    if geometry_root is None or not isinstance(descriptor, dict):
        raise TrainingError("Temporally certified sky-evidence provenance is incomplete.")
    if (
        descriptor.get("schema") != CERTIFIED_SKY_EVIDENCE_SCHEMA
        or descriptor.get("method") != CERTIFIED_SKY_EVIDENCE_METHOD
        or descriptor.get("rotationOnlyInfiniteSky") is not True
        or descriptor.get("containsGeneratedPixels") is not False
        or descriptor.get("manifest") != "sky-evidence.json"
    ):
        raise TrainingError("Temporally certified sky-evidence policy is unsupported.")
    expected_hash = descriptor.get("manifestSha256")
    if not isinstance(expected_hash, str) or not expected_hash.startswith("sha256:"):
        raise TrainingError("Temporally certified sky-evidence manifest hash is invalid.")
    manifest_path = geometry_root / "sky-evidence.json"
    if not manifest_path.is_file() or sha256_file(manifest_path) != expected_hash:
        raise TrainingError("Temporally certified sky-evidence manifest failed hash verification.")
    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingError("Temporally certified sky-evidence manifest is unreadable.") from error
    expected_manifest = {
        key: value
        for key, value in descriptor.items()
        if key not in {"manifest", "manifestSha256"}
    }
    if manifest != expected_manifest:
        raise TrainingError("Temporally certified sky-evidence manifest disagrees with config.")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or int(manifest.get("registeredImages", -1)) != len(frames):
        raise TrainingError("Temporally certified sky-evidence frame receipt is malformed.")
    seen_images: set[str] = set()
    root = geometry_root.resolve()
    for frame in frames:
        if not isinstance(frame, dict):
            raise TrainingError("Temporally certified sky-evidence frame is malformed.")
        image = frame.get("image")
        asset = frame.get("asset")
        asset_hash = frame.get("assetSha256")
        if (
            not isinstance(image, str)
            or not image
            or not isinstance(asset, str)
            or not asset
            or not isinstance(asset_hash, str)
            or not asset_hash.startswith("sha256:")
            or image in seen_images
        ):
            raise TrainingError("Temporally certified sky-evidence frame identity is invalid.")
        seen_images.add(image)
        image_path = Path(image)
        relative_asset = Path(asset)
        expected_asset = (
            Path(CERTIFIED_SKY_EVIDENCE_DIRECTORY) / image_path.with_suffix(".png")
        )
        if (
            image_path.is_absolute()
            or relative_asset.is_absolute()
            or ".." in image_path.parts
            or ".." in relative_asset.parts
            or relative_asset.as_posix() != expected_asset.as_posix()
        ):
            raise TrainingError("Temporally certified sky-evidence asset escapes its geometry bundle.")
        resolved = (geometry_root / relative_asset).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise TrainingError("Temporally certified sky-evidence asset escapes its geometry bundle.") from error
        if not resolved.is_file() or sha256_file(resolved) != asset_hash:
            raise TrainingError("Temporally certified sky-evidence asset failed hash verification.")
    return descriptor


def directional_raster_background(
    environment: Any | None,
    camera_to_world: Any,
    calibration: Any,
    width: int,
    height: int,
    fallback: Any,
) -> tuple[Any, Any | None]:
    """Return a captured directional background or the explicit mean fallback.

    Only RGB is later composited behind the Gaussian alpha.  Geometry/depth
    outputs never receive the background, preserving their physical meaning.
    """

    if environment is None:
        return fallback, None
    try:
        from servo_environment import EnvironmentError, sample_observed_directional_environment_for_camera

        with __import__("torch").no_grad():
            return sample_observed_directional_environment_for_camera(
                environment,
                camera_to_world,
                calibration,
                width,
                height,
                fallback,
            )
    except EnvironmentError as error:
        raise TrainingError(
            f"Observed directional environment sampling failed: {error}"
        ) from error


def cross_view_depth_consistency_loss(
    source_depth: Any,
    source_alpha: Any,
    source_camera_to_world: Any,
    source_calibration: Any,
    target_depth: Any,
    target_alpha: Any,
    target_camera_to_world: Any,
    target_calibration: Any,
    confidence: Any | None = None,
    *,
    alpha_threshold: float = 0.5,
    maximum_log_residual: float = math.log(2.0),
) -> tuple[Any, int]:
    """Reproject a rendered depth map and compare it in a calibrated view.

    Only mutually supported, in-bounds samples contribute. A broad detached
    visibility gate rejects genuine occlusion boundaries while retaining the
    moderate inconsistent-depth layers that the loss is intended to remove.
    Log-depth residuals make the objective insensitive to scene units.
    """

    import torch
    import torch.nn.functional as functional

    if (
        source_depth.ndim != 4
        or target_depth.ndim != 4
        or source_depth.shape[-1] != 1
        or target_depth.shape[-1] != 1
        or source_alpha.shape != source_depth.shape
        or target_alpha.shape != target_depth.shape
    ):
        raise TrainingError("Cross-view depth tensors must use [B,H,W,1] layout.")
    batch, source_height, source_width, _ = source_depth.shape
    if batch != 1 or int(target_depth.shape[0]) != batch:
        raise TrainingError("Cross-view depth consistency currently requires one camera pair.")
    if (
        tuple(source_camera_to_world.shape) != (batch, 4, 4)
        or tuple(target_camera_to_world.shape) != (batch, 4, 4)
        or tuple(source_calibration.shape) != (batch, 3, 3)
        or tuple(target_calibration.shape) != (batch, 3, 3)
    ):
        raise TrainingError("Cross-view camera tensors have incompatible shapes.")
    if confidence is None:
        confidence = torch.ones_like(source_depth)
    if confidence.shape != source_depth.shape:
        raise TrainingError("Cross-view confidence must match the source depth map.")

    dtype = source_depth.dtype
    device = source_depth.device
    rows, columns = torch.meshgrid(
        torch.arange(source_height, dtype=dtype, device=device),
        torch.arange(source_width, dtype=dtype, device=device),
        indexing="ij",
    )
    depth = source_depth[..., 0]
    source_fx = source_calibration[:, 0, 0, None, None]
    source_fy = source_calibration[:, 1, 1, None, None]
    source_cx = source_calibration[:, 0, 2, None, None]
    source_cy = source_calibration[:, 1, 2, None, None]
    source_points = torch.stack(
        [
            (columns[None] - source_cx) * depth / source_fx,
            (rows[None] - source_cy) * depth / source_fy,
            depth,
        ],
        dim=-1,
    )
    source_rotation = source_camera_to_world[:, :3, :3]
    source_translation = source_camera_to_world[:, :3, 3]
    world_points = (
        torch.einsum("bij,bhwj->bhwi", source_rotation, source_points)
        + source_translation[:, None, None, :]
    )
    target_world_to_camera = torch.linalg.inv(target_camera_to_world)
    target_points = (
        torch.einsum(
            "bij,bhwj->bhwi", target_world_to_camera[:, :3, :3], world_points
        )
        + target_world_to_camera[:, None, None, :3, 3]
    )
    projected_depth = target_points[..., 2]
    safe_depth = projected_depth.clamp_min(1e-6)
    target_columns = (
        target_calibration[:, 0, 0, None, None] * target_points[..., 0] / safe_depth
        + target_calibration[:, 0, 2, None, None]
    )
    target_rows = (
        target_calibration[:, 1, 1, None, None] * target_points[..., 1] / safe_depth
        + target_calibration[:, 1, 2, None, None]
    )
    target_height, target_width = target_depth.shape[1:3]
    grid = torch.stack(
        [
            2.0 * (target_columns + 0.5) / target_width - 1.0,
            2.0 * (target_rows + 0.5) / target_height - 1.0,
        ],
        dim=-1,
    )
    sampled_depth = functional.grid_sample(
        target_depth.permute(0, 3, 1, 2),
        grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=False,
    ).permute(0, 2, 3, 1)[..., 0]
    sampled_alpha = functional.grid_sample(
        target_alpha.permute(0, 3, 1, 2),
        grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=False,
    ).permute(0, 2, 3, 1)[..., 0]
    log_residual = (
        torch.log(safe_depth) - torch.log(sampled_depth.clamp_min(1e-6))
    ).abs()
    valid = (
        torch.isfinite(depth)
        & torch.isfinite(projected_depth)
        & torch.isfinite(sampled_depth)
        & (depth > 1e-5)
        & (projected_depth > 1e-5)
        & (source_alpha[..., 0] >= alpha_threshold)
        & (sampled_alpha >= alpha_threshold)
        & (target_columns >= 0.0)
        & (target_columns <= target_width - 1.0)
        & (target_rows >= 0.0)
        & (target_rows <= target_height - 1.0)
        & (log_residual.detach() <= maximum_log_residual)
        & (confidence[..., 0] > 0.0)
    )
    sample_count = int(valid.sum().item())
    if sample_count == 0:
        return source_depth.sum() * 0.0 + target_depth.sum() * 0.0, 0
    weights = (
        source_alpha[..., 0] * sampled_alpha * confidence[..., 0]
    )[valid]
    robust = functional.smooth_l1_loss(
        torch.log(safe_depth[valid]),
        torch.log(sampled_depth[valid].clamp_min(1e-6)),
        beta=0.05,
        reduction="none",
    )
    return (robust * weights).sum() / weights.sum().clamp_min(1e-6), sample_count


def sparse_depth_consistency_loss(
    expected_depth: Any,
    alpha: Any,
    record: ImageRecord,
    resolution_factor: int,
    maximum_observations: int = 4096,
) -> tuple[Any, int]:
    """Anchor rendered depth to reliable COLMAP tracks at observed pixels.

    This is a geometric constraint derived from the same multi-view solve, not
    a learned monocular guess. Relative Huber residuals keep near and far
    points comparable while alpha gating avoids supervising unsupported pixels.
    """
    import torch
    import torch.nn.functional as functional

    zero = expected_depth.sum() * 0.0
    count = int(len(record.sparse_depths))
    if count < 8:
        return zero, 0
    if count > maximum_observations:
        selected = torch.linspace(
            0, count - 1, maximum_observations, device=expected_depth.device
        ).round().long()
    else:
        selected = None
    pixels = torch.from_numpy(record.sparse_pixels).to(
        device=expected_depth.device, dtype=torch.float32
    )
    targets = torch.from_numpy(record.sparse_depths).to(
        device=expected_depth.device, dtype=torch.float32
    )
    if selected is not None:
        pixels = pixels[selected]
        targets = targets[selected]
    factor = max(1, int(resolution_factor))
    pixels = pixels / float(factor)
    height, width = expected_depth.shape[1:3]
    finite = (
        torch.isfinite(pixels).all(dim=1)
        & torch.isfinite(targets)
        & (targets > 1e-5)
        & (pixels[:, 0] >= 0.0)
        & (pixels[:, 0] <= width - 1)
        & (pixels[:, 1] >= 0.0)
        & (pixels[:, 1] <= height - 1)
    )
    if int(finite.sum().item()) < 8:
        return zero, 0
    pixels = pixels[finite]
    targets = targets[finite]
    grid_x = pixels[:, 0] * (2.0 / max(width - 1, 1)) - 1.0
    grid_y = pixels[:, 1] * (2.0 / max(height - 1, 1)) - 1.0
    grid = torch.stack([grid_x, grid_y], dim=-1).view(1, 1, -1, 2)
    predicted = functional.grid_sample(
        expected_depth.permute(0, 3, 1, 2),
        grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=True,
    ).reshape(-1)
    support = functional.grid_sample(
        alpha.permute(0, 3, 1, 2),
        grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=True,
    ).reshape(-1)
    supported = (
        torch.isfinite(predicted)
        & (predicted > 1e-5)
        & torch.isfinite(support)
        & (support >= 0.25)
    )
    supported_count = int(supported.sum().item())
    if supported_count < 8:
        return zero, 0
    relative = (predicted[supported] - targets[supported]) / targets[
        supported
    ].clamp_min(1e-5)
    return (
        functional.smooth_l1_loss(
            relative,
            torch.zeros_like(relative),
            beta=0.05,
        ),
        supported_count,
    )


def sparse_track_pair_camera_z_loss(
    source_depth: Any,
    source_alpha: Any,
    target_depth: Any,
    target_alpha: Any,
    samples: Mapping[str, Any],
    source_resolution_factor: int,
    target_resolution_factor: int,
    *,
    minimum_valid_tracks: int = 64,
    maximum_tracks: int = 4096,
) -> tuple[Any, int, int]:
    """Anchor two renders to the same reliable COLMAP track camera-Z values.

    The two rendered fields receive gradients, but neither supervises the
    other: both are compared with externally triangulated camera-space Z.
    This deliberately avoids the self-reinforcing expected-depth midpoint
    failure of dense R21 reprojection.
    """

    import torch
    import torch.nn.functional as functional

    zero = source_depth.sum() * 0.0 + target_depth.sum() * 0.0
    point_ids = torch.as_tensor(samples["pointIds"], device=source_depth.device)
    available = int(point_ids.numel())
    if available < minimum_valid_tracks:
        return zero, 0, available
    if available > maximum_tracks:
        selected = torch.linspace(
            0, available - 1, maximum_tracks, device=source_depth.device
        ).round().long()
    else:
        selected = None

    def sample_view(
        depth: Any,
        alpha: Any,
        pixel_values: Any,
        target_values: Any,
        factor: int,
    ) -> tuple[Any, Any, Any]:
        pixels = torch.as_tensor(
            pixel_values, device=depth.device, dtype=torch.float32
        )
        targets = torch.as_tensor(
            target_values, device=depth.device, dtype=torch.float32
        )
        if selected is not None:
            pixels = pixels[selected]
            targets = targets[selected]
        pixels = pixels / float(max(1, int(factor)))
        height, width = depth.shape[1:3]
        finite = (
            torch.isfinite(pixels).all(dim=1)
            & torch.isfinite(targets)
            & (targets > 1e-5)
            & (pixels[:, 0] >= 0.0)
            & (pixels[:, 0] <= width - 1)
            & (pixels[:, 1] >= 0.0)
            & (pixels[:, 1] <= height - 1)
        )
        grid_x = pixels[:, 0] * (2.0 / max(width - 1, 1)) - 1.0
        grid_y = pixels[:, 1] * (2.0 / max(height - 1, 1)) - 1.0
        grid = torch.stack([grid_x, grid_y], dim=-1).view(1, 1, -1, 2)
        predicted = functional.grid_sample(
            depth.permute(0, 3, 1, 2),
            grid,
            mode="bilinear",
            padding_mode="zeros",
            align_corners=True,
        ).reshape(-1)
        support = functional.grid_sample(
            alpha.permute(0, 3, 1, 2),
            grid,
            mode="bilinear",
            padding_mode="zeros",
            align_corners=True,
        ).reshape(-1)
        valid = (
            finite
            & torch.isfinite(predicted)
            & (predicted > 1e-5)
            & torch.isfinite(support)
            & (support >= 0.25)
        )
        relative = (predicted - targets) / targets.clamp_min(1e-5)
        return relative, support, valid

    source_relative, source_support, source_valid = sample_view(
        source_depth,
        source_alpha,
        samples["sourcePixels"],
        samples["sourceDepths"],
        source_resolution_factor,
    )
    target_relative, target_support, target_valid = sample_view(
        target_depth,
        target_alpha,
        samples["targetPixels"],
        samples["targetDepths"],
        target_resolution_factor,
    )
    valid = source_valid & target_valid
    valid_count = int(valid.sum().item())
    if valid_count < minimum_valid_tracks:
        return zero, 0, available
    source_error = functional.smooth_l1_loss(
        source_relative[valid],
        torch.zeros_like(source_relative[valid]),
        beta=0.05,
        reduction="none",
    )
    target_error = functional.smooth_l1_loss(
        target_relative[valid],
        torch.zeros_like(target_relative[valid]),
        beta=0.05,
        reduction="none",
    )
    # The maximum prevents one well-fit view from hiding a badly layered one.
    paired_error = torch.maximum(source_error, target_error)
    weights = torch.minimum(source_support[valid], target_support[valid]).detach()
    return (
        (paired_error * weights).sum() / weights.sum().clamp_min(1e-6),
        valid_count,
        available,
    )


def depth_layer_variance_loss(expected_depth: Any, second_moment: Any, alpha: Any) -> Any:
    """Penalize mixed front/back Gaussian layers along supported camera rays."""
    import torch

    depth = expected_depth[..., 0]
    support = alpha[..., 0]
    moment2 = second_moment[..., 0] / support.clamp_min(1e-6)
    relative_variance = torch.clamp(moment2 - depth.square(), min=0.0) \
                        / depth.square().clamp_min(1e-6)
    valid = (
        torch.isfinite(relative_variance)
        & torch.isfinite(depth)
        & (depth > 1e-4)
        & (support >= 0.5)
    )
    if not bool(valid.any()):
        return expected_depth.sum() * 0.0
    return relative_variance[valid].clamp(max=4.0).mean()


def driving_surface_depth_variance_loss(
    expected_depth: Any,
    second_moment: Any,
    alpha: Any,
    semantic: Any,
    confidence: Any,
) -> Any:
    """Concentrate splats along rays supported by driving-critical surfaces.

    The loss reduces front/back layer mixtures without assuming that a road is
    globally flat. Consequently, real slope, banking, curbs, and sign planes
    can remain while unsupported floating layers receive no target.
    """

    import torch

    if semantic.shape != expected_depth.shape or confidence.shape != expected_depth.shape:
        raise TrainingError(
            "Driving-surface variance requires depth-shaped semantic and confidence tensors."
        )
    depth = expected_depth[..., 0]
    support = alpha[..., 0]
    moment2 = second_moment[..., 0] / support.clamp_min(1e-6)
    relative_variance = torch.clamp(moment2 - depth.square(), min=0.0) \
                        / depth.square().clamp_min(1e-6)
    labels = semantic[..., 0]
    critical = (
        (labels == 1)
        | (labels == 2)
        | (labels == 3)
        | (labels == 4)
        | (labels == 5)
        | (labels == 10)
        | (labels == 12)
        | (labels == 13)
        | (labels == 14)
        | (labels == 15)
        | (labels == 25)
    )
    weights = confidence[..., 0].clamp(0.0, 1.0)
    weights = torch.where((labels == 2) | ((labels >= 12) & (labels <= 15)), weights * 2.0, weights)
    valid = (
        critical
        & torch.isfinite(relative_variance)
        & torch.isfinite(depth)
        & (depth > 1e-4)
        & (support >= 0.5)
        & (weights > 0.0)
    )
    if not bool(valid.any()):
        return expected_depth.sum() * 0.0
    return (
        relative_variance[valid].clamp(max=4.0) * weights[valid]
    ).sum() / weights[valid].sum().clamp_min(1e-6)


def driving_surface_alignment_loss(
    rendered_features: Any,
    depth_normals: Any,
    alpha: Any,
    semantic: Any,
    confidence: Any,
) -> tuple[Any, Any, int, int]:
    """Align visible 3D Gaussian normals to observed driving surfaces.

    ``rendered_features`` contains the alpha-composited shortest-axis normal
    and shortest/longest scale ratio of every contributing 3D Gaussian.  The
    normal target is derived from the same rendered expected-depth map, so the
    loss regularizes internal surface consistency without claiming metric
    depth.  Planarity is restricted to observed road-like pixels; it is not
    applied to foliage, sky, or unobserved space.
    """

    import torch
    import torch.nn.functional as functional

    expected_shape = (*alpha.shape[:3], 4)
    if (
        rendered_features.shape != expected_shape
        or depth_normals.shape != (*alpha.shape[:3], 3)
        or semantic.shape != alpha.shape
        or confidence.shape != alpha.shape
    ):
        raise TrainingError(
            "Driving-surface alignment requires matching BHWC feature, normal, "
            "alpha, semantic, and confidence tensors."
        )
    zero = rendered_features.sum() * 0.0
    support = alpha[..., 0]
    labels = semantic[..., 0]
    weights = confidence[..., 0].clamp(0.0, 1.0)
    accumulated_normal = rendered_features[..., :3]
    visible_normal = functional.normalize(
        accumulated_normal / support[..., None].clamp_min(1e-6), dim=-1
    )
    target_normal = functional.normalize(depth_normals, dim=-1)
    normal_valid = (
        torch.isfinite(visible_normal).all(dim=-1)
        & torch.isfinite(target_normal).all(dim=-1)
        & (torch.linalg.vector_norm(accumulated_normal, dim=-1) > 1e-4)
        & (torch.linalg.vector_norm(depth_normals, dim=-1) > 0.5)
        & (support >= 0.5)
        & (weights > 0.0)
    )
    road_surface = (
        (labels == 1) | (labels == 2) | (labels == 5) | (labels == 25)
    )
    normal_valid &= road_surface
    normal_count = int(normal_valid.sum().item())
    normal_loss = zero
    if normal_count > 0:
        cosine = (visible_normal * target_normal).sum(dim=-1).abs()
        normal_loss = (
            torch.clamp_min(1.0 - cosine[normal_valid], 0.0)
            * weights[normal_valid]
        ).sum() / weights[normal_valid].sum().clamp_min(1e-6)

    planarity = rendered_features[..., 3] / support.clamp_min(1e-6)
    planarity_valid = (
        road_surface
        & torch.isfinite(planarity)
        & (support >= 0.5)
        & (weights > 0.0)
    )
    planarity_count = int(planarity_valid.sum().item())
    planarity_loss = zero
    if planarity_count > 0:
        # Smooth L1 avoids rewarding an unstable collapse to a zero-thickness
        # primitive while still preferring surface-like road contributors.
        planarity_loss = (
            functional.smooth_l1_loss(
                planarity[planarity_valid],
                torch.full_like(planarity[planarity_valid], 0.10),
                beta=0.05,
                reduction="none",
            )
            * weights[planarity_valid]
        ).sum() / weights[planarity_valid].sum().clamp_min(1e-6)
    return normal_loss, planarity_loss, normal_count, planarity_count


def observed_detail_gradient_loss(
    rendered: Any,
    reference: Any,
    confidence: Any,
    semantic: Any,
) -> Any:
    """Preserve source-resolved road, curb, marking, and sign edges.

    This is an evidence-only loss: it compares against gradients present in the
    registered source frame and therefore cannot invent unreadable sign text.
    Semantic weights focus the finite training budget on driving-relevant rigid
    surfaces while the existing confidence mask excludes dynamic/unknown pixels.
    """

    import torch
    import torch.nn.functional as functional

    if (
        rendered.ndim != 4
        or reference.shape != rendered.shape
        or rendered.shape[-1] != 3
        or confidence.shape != (*rendered.shape[:3], 1)
        or semantic.shape != (*rendered.shape[:3], 1)
    ):
        raise TrainingError(
            "Observed-detail loss requires matching BHWC RGB, confidence, and semantic tensors."
        )
    dtype = rendered.dtype
    device = rendered.device
    kernel_x = torch.tensor(
        [[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]],
        dtype=dtype,
        device=device,
    ).view(1, 1, 3, 3) / 8.0
    kernel_y = kernel_x.transpose(-1, -2)
    luminance = torch.tensor(
        [0.2126, 0.7152, 0.0722], dtype=dtype, device=device
    ).view(1, 3, 1, 1)

    def gradients(image: Any) -> tuple[Any, Any]:
        gray = (image.permute(0, 3, 1, 2) * luminance).sum(dim=1, keepdim=True)
        return (
            functional.conv2d(gray, kernel_x, padding=1),
            functional.conv2d(gray, kernel_y, padding=1),
        )

    rendered_x, rendered_y = gradients(rendered)
    reference_x, reference_y = gradients(reference.detach())
    labels = semantic[..., 0]
    importance = torch.ones_like(labels, dtype=dtype)
    importance = torch.where(
        (labels == 1) | (labels == 5), 1.5, importance
    )
    importance = torch.where(labels == 2, 3.0, importance)
    importance = torch.where(
        (labels == 3) | (labels == 4) | (labels == 10), 2.0, importance
    )
    importance = torch.where(
        (labels == 12) | (labels == 13) | (labels == 14) | (labels == 15),
        4.0,
        importance,
    )
    weights = confidence[..., 0].clamp(0.0, 1.0) * importance
    reference_strength = torch.sqrt(
        reference_x.square() + reference_y.square() + 1e-8
    )[:, 0]
    # Retain smooth-surface supervision while prioritizing edges that the
    # source actually resolved. The clamp prevents foliage or compression
    # ringing from consuming the entire detail budget.
    weights = weights * (0.25 + (reference_strength / 0.05).clamp(max=2.0))
    supported = weights > 0.0
    if not bool(supported.any()):
        return rendered.sum() * 0.0
    error = functional.smooth_l1_loss(
        rendered_x,
        reference_x,
        beta=0.02,
        reduction="none",
    ) + functional.smooth_l1_loss(
        rendered_y,
        reference_y,
        beta=0.02,
        reduction="none",
    )
    return (error[:, 0] * weights).sum() / weights.sum().clamp_min(1e-6)


def semantic_sky_tail_interior_mask(
    semantic: Any,
    *,
    erosion_radius: int = SEMANTIC_SKY_TAIL_EROSION_RADIUS,
    sky_label: int = 17,
) -> Any:
    """Return only observed-sky pixels safely away from semantic boundaries.

    OneFormer labels are useful observed evidence, but a one-pixel sky/tree or
    sky/mountain boundary is not a reliable reason to erase finite geometry.
    The normal mean-alpha term still covers all observed sky.  The stronger
    high-opacity tail term uses an eroded sky interior with explicit non-sky
    image padding, so border pixels and uncertain object boundaries cannot
    receive the stronger correction.
    """

    import torch
    import torch.nn.functional as functional

    if semantic.ndim != 4 or semantic.shape[-1] != 1:
        raise TrainingError(
            "Semantic sky-tail erosion requires a [camera,height,width,1] tensor."
        )
    if (
        isinstance(erosion_radius, bool)
        or not isinstance(erosion_radius, int)
        or erosion_radius < 0
        or isinstance(sky_label, bool)
        or not isinstance(sky_label, int)
    ):
        raise TrainingError("Semantic sky-tail erosion radius is invalid.")
    sky = semantic == sky_label
    if erosion_radius == 0:
        return sky
    non_sky = (~sky).to(dtype=torch.float32).permute(0, 3, 1, 2)
    # Padding with non-sky evidence makes a sky label on an image boundary
    # ineligible for the stronger loss as well.
    padded = functional.pad(
        non_sky,
        (erosion_radius, erosion_radius, erosion_radius, erosion_radius),
        mode="constant",
        value=1.0,
    )
    nearby_non_sky = functional.max_pool2d(
        padded,
        kernel_size=erosion_radius * 2 + 1,
        stride=1,
    )
    return (nearby_non_sky == 0.0).permute(0, 2, 3, 1)


def semantic_sky_opacity_loss(
    alpha: Any,
    semantic: Any,
    *,
    evidence: Any | None = None,
    tail_threshold: float = SEMANTIC_SKY_TAIL_THRESHOLD,
    tail_weight: float = 0.0,
    tail_bce_epsilon: float = SEMANTIC_SKY_TAIL_BCE_EPSILON,
    tail_erosion_radius: int = SEMANTIC_SKY_TAIL_EROSION_RADIUS,
    l1_scope: str = "evidence-restricted",
) -> tuple[Any, int]:
    """Remove finite Gaussian support from pixels observed as sky.

    Sky is represented by the separately recorded environment background, not
    by finite scene Gaussians.  The loss is intentionally one-sided: it drives
    accumulated opacity toward zero only on observed semantic-sky pixels and
    never forces non-sky pixels opaque.  This follows the sky-opacity objective
    used by outdoor Gaussian reconstruction systems while remaining honest in
    genuinely unobserved regions.  The loss is a direct mean-alpha penalty,
    rather than a generative sky completion objective: every non-finite value
    is ignored, every finite observed-sky contribution gets the same bounded
    corrective gradient, and no unobserved direction is assigned a target.
    Servo's controlled road A/B selected this L1 formulation over BCE, so its
    evidence contract deliberately records the measured-better formulation.

    A pooled L1 average can still hide a nearly opaque finite splat in a small
    part of one sky view.  When the caller enables the tail term, pixels above
    a recorded opacity threshold receive a stable transparent-target BCE
    penalty.  The term is computed inside the current camera only, so every
    training view has its own tail correction rather than sky-rich frames
    diluting sparse-sky frames.  It remains one-sided and is never applied to
    unobserved, non-sky, or actor pixels.
    """

    import torch

    if alpha.shape != semantic.shape or alpha.ndim != 4 or alpha.shape[-1] != 1:
        raise TrainingError(
            "Semantic sky-opacity loss requires matching [camera,height,width,1] tensors."
        )
    if (
        not math.isfinite(tail_threshold)
        or not 0.0 <= tail_threshold < 1.0
        or not math.isfinite(tail_weight)
        or tail_weight < 0.0
        or not math.isfinite(tail_bce_epsilon)
        or not 0.0 < tail_bce_epsilon < 1.0
        or isinstance(tail_erosion_radius, bool)
        or not isinstance(tail_erosion_radius, int)
        or tail_erosion_radius < 0
        or l1_scope not in ("evidence-restricted", "semantic")
    ):
        raise TrainingError("Semantic sky-tail settings are invalid.")
    sky = semantic == 17
    if evidence is not None:
        if (
            evidence.shape != semantic.shape
            or evidence.ndim != 4
            or evidence.shape[-1] != 1
        ):
            raise TrainingError(
                "Certified sky evidence requires matching [camera,height,width,1] tensors."
            )
        if not bool(
            (
                (evidence == 0)
                | (evidence == CERTIFIED_SKY_EVIDENCE_SKY)
                | (evidence == CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY)
            ).all()
        ):
            raise TrainingError("Certified sky evidence contains an unknown label.")
        sky = sky & (evidence == CERTIFIED_SKY_EVIDENCE_SKY)
    if l1_scope == "semantic":
        # Diagnostic hybrid arm: the mean-L1 term keeps the full semantic-sky
        # recall while only the tail term narrows to certified interior sky.
        sky = semantic == 17
    valid = sky & torch.isfinite(alpha)
    samples = int(valid.sum().item())
    if samples == 0:
        return torch.nan_to_num(alpha).sum() * 0.0, 0
    sky_alpha = alpha[valid]
    loss = sky_alpha.mean()
    if tail_weight <= 0.0:
        return loss, samples
    # Only the observed, non-boundary high-opacity sky tail is strengthened.
    # Epsilon keeps the transparent-target BCE finite and caps the derivative
    # near alpha=1 without zeroing its corrective gradient.
    tail_source = evidence if evidence is not None else semantic
    tail_label = CERTIFIED_SKY_EVIDENCE_SKY if evidence is not None else 17
    tail_mask = (
        semantic_sky_tail_interior_mask(
            tail_source,
            erosion_radius=tail_erosion_radius,
            sky_label=tail_label,
        )
        & torch.isfinite(alpha)
        & (alpha > tail_threshold)
    )
    tail_alpha = alpha[tail_mask]
    if tail_alpha.numel() == 0:
        return loss, samples
    transparent_bce = (
        -torch.log1p(-tail_alpha + tail_bce_epsilon)
        + math.log1p(tail_bce_epsilon)
    ).mean()
    return loss + tail_weight * transparent_bce, samples


def semantic_sky_view_diagnostic(
    alpha: Any,
    semantic: Any,
    image: str,
) -> dict[str, Any] | None:
    """Describe finite-splat support in one observed semantic-sky view."""

    import torch

    if alpha.shape != semantic.shape or alpha.ndim != 4 or alpha.shape[-1] != 1:
        raise TrainingError(
            "Semantic sky diagnostics require matching [camera,height,width,1] tensors."
        )
    if not isinstance(image, str) or not image:
        raise TrainingError("Semantic sky diagnostics require an image name.")
    values = alpha[(semantic == 17) & torch.isfinite(alpha)]
    if values.numel() == 0:
        return None
    values = values.float()
    return {
        "image": image,
        "skyPixels": int(values.numel()),
        "skyAlphaMean": float(values.mean().item()),
        "skyAlphaP50": float(torch.quantile(values, 0.50).item()),
        "skyAlphaP95": float(torch.quantile(values, 0.95).item()),
        "skyAlphaP99": float(torch.quantile(values, 0.99).item()),
        "skyAlphaAboveTenPercentFraction": float(
            (values > SEMANTIC_SKY_TAIL_THRESHOLD).float().mean().item()
        ),
    }


def fuse_semantic_photometric_confidence(
    temporal_confidence: Any,
    semantic: Any,
    *,
    rigid_static_confidence_floor: float = 0.25,
    vegetation_confidence_floor: float = 0.0,
    water_confidence_floor: float = 0.0,
    hard_exclusion: Any | None = None,
) -> Any:
    """Fuse raw temporal evidence without erasing observed static RGB.

    Bidirectional flow failure is ambiguous: it may indicate a transient object,
    but it also occurs on low-texture asphalt, image borders, thin structures,
    and disocclusions.  Treating a zero flow weight as a hard exclusion created
    permanent holes in rigid road and foreground geometry.  Stable semantic
    classes therefore retain their measured temporal confidence with a small
    floor, rather than replacing every sample with full confidence. Vegetation and
    water retain their raw temporal evidence rather than receiving an artificial
    floor: their motion and occlusion are genuinely ambiguous in a single drive.
    Unknown, sky, and actor classes remain exactly zero (fail closed).  A
    hard exclusion is applied last.  It represents pixels that are known not
    to belong to the reconstructed world (for example the capture vehicle at
    the bottom of a driving video), so a broad semantic label such as ROAD
    must never turn that evidence back on.

    The semantic IDs are Servo's stable safety taxonomy:
    rigid static = 1..15, 24, 25; vegetation = 16; sky = 17;
    dynamic actors = 18..22; water = 23; unknown = 0.
    """

    import torch

    if (
        temporal_confidence.shape != semantic.shape
        or temporal_confidence.ndim != 4
        or temporal_confidence.shape[-1] != 1
    ):
        raise TrainingError(
            "Semantic photometric fusion requires matching "
            "[camera,height,width,1] tensors."
        )
    for name, value in (
        ("rigid static confidence floor", rigid_static_confidence_floor),
        ("vegetation confidence floor", vegetation_confidence_floor),
        ("water confidence floor", water_confidence_floor),
    ):
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise TrainingError(f"The semantic {name} must be finite and in [0,1].")
    if not bool(torch.isfinite(temporal_confidence).all().item()):
        raise TrainingError("Temporal photometric confidence contains non-finite values.")
    if bool(
        ((temporal_confidence < 0.0) | (temporal_confidence > 1.0)).any().item()
    ):
        raise TrainingError("Temporal photometric confidence must remain in [0,1].")

    labels = semantic.to(dtype=torch.int64)
    rigid_static = ((labels >= 1) & (labels <= 15)) | (labels == 24) | (labels == 25)
    vegetation = labels == 16
    water = labels == 23
    fused = torch.zeros_like(temporal_confidence)
    fused = torch.where(
        rigid_static,
        torch.maximum(
            temporal_confidence,
            torch.full_like(fused, float(rigid_static_confidence_floor)),
        ),
        fused,
    )
    fused = torch.where(
        vegetation,
        torch.maximum(
            temporal_confidence,
            torch.full_like(fused, float(vegetation_confidence_floor)),
        ),
        fused,
    )
    fused = torch.where(
        water,
        torch.maximum(
            temporal_confidence,
            torch.full_like(fused, float(water_confidence_floor)),
        ),
        fused,
    )
    if hard_exclusion is None:
        return fused
    if hard_exclusion.shape != temporal_confidence.shape:
        raise TrainingError(
            "Semantic photometric hard exclusion must match [camera,height,width,1]."
        )
    if hard_exclusion.dtype != torch.bool:
        raise TrainingError("Semantic photometric hard exclusion must be boolean.")
    return torch.where(hard_exclusion, torch.zeros_like(fused), fused)


def video_capture_bottom_exclusion_mask(
    record_name: str,
    height: int,
    width: int,
    device: str,
) -> Any | None:
    """Return the immutable vehicle/dashboard exclusion for video frames only.

    The worker writes this same lower strip as zero confidence before training.
    It is represented separately here because semantic retention intentionally
    restores static road/curb evidence where optical flow fails, but must not
    restore the camera vehicle merely because a semantic model calls it road.
    """

    import torch

    if height <= 0 or width <= 0:
        raise TrainingError("Capture exclusion requires a positive image shape.")
    if not Path(record_name).parent.name.startswith("video-"):
        return None
    bottom = max(1, round(height * VIDEO_CAPTURE_BOTTOM_EXCLUSION_FRACTION))
    exclusion = torch.zeros((1, height, width, 1), dtype=torch.bool, device=device)
    exclusion[:, -bottom:, :, :] = True
    return exclusion


def resize_geometry_priors(
    relative_inverse_depth: Any,
    road_surface_depth: Any,
    semantic: Any,
    height: int,
    width: int,
    device: str,
) -> tuple[Any, Any, Any, Any, Any]:
    """Resize priors and keep appearance masking separate from geometry weights."""

    import torch
    import torch.nn.functional as functional

    relative = relative_inverse_depth.to(
        device=device, dtype=torch.float32, non_blocking=True
    ).view(1, 1, *relative_inverse_depth.shape)
    road = road_surface_depth.to(
        device=device, dtype=torch.float32, non_blocking=True
    ).view(1, 1, *road_surface_depth.shape)
    labels = semantic.to(
        device=device, dtype=torch.float32, non_blocking=True
    ).view(1, 1, *semantic.shape)
    relative = functional.interpolate(
        relative, size=(height, width), mode="bilinear", align_corners=False
    ).permute(0, 2, 3, 1)
    road_valid_source = (road > 0.0).to(torch.float32)
    road_support = functional.interpolate(
        road_valid_source,
        size=(height, width),
        mode="area" if height <= road.shape[-2] and width <= road.shape[-1] else "bilinear",
        **(
            {}
            if height <= road.shape[-2] and width <= road.shape[-1]
            else {"align_corners": False}
        ),
    )
    road_weighted = functional.interpolate(
        road * road_valid_source,
        size=(height, width),
        mode="area" if height <= road.shape[-2] and width <= road.shape[-1] else "bilinear",
        **(
            {}
            if height <= road.shape[-2] and width <= road.shape[-1]
            else {"align_corners": False}
        ),
    )
    road = torch.where(
        road_support >= 0.50,
        road_weighted / road_support.clamp_min(1e-6),
        torch.zeros_like(road_weighted),
    ).permute(0, 2, 3, 1)
    labels = functional.interpolate(
        labels, size=(height, width), mode="nearest"
    ).to(torch.int64).permute(0, 2, 3, 1)
    photometric_mask = torch.ones_like(relative)
    geometry_confidence = torch.ones_like(relative)
    excluded = (
        (labels == 0)
        | (labels == 17)
        | ((labels >= 18) & (labels <= 22))
    )
    photometric_mask[excluded] = 0.0
    geometry_confidence[excluded] = 0.0
    # These are conservative geometry weights, not model probabilities.  They
    # must never reduce the observed-RGB loss: moving foliage and water have
    # weak surface depth but their visible appearance still needs full detail.
    geometry_confidence[labels == 16] = 0.20
    geometry_confidence[labels == 23] = 0.10
    return relative, road, labels, photometric_mask, geometry_confidence


def resize_certified_sky_evidence(
    evidence: Any,
    height: int,
    width: int,
    device: str,
) -> Any:
    """Resize tri-state sky evidence without inventing fractional labels."""

    import torch
    import torch.nn.functional as functional

    if evidence.ndim != 2:
        raise TrainingError("Certified sky evidence must be a two-dimensional raster.")
    labels = evidence.to(device=device, dtype=torch.float32, non_blocking=True).view(
        1, 1, *evidence.shape
    )
    labels = functional.interpolate(labels, size=(height, width), mode="nearest")
    labels = labels.to(torch.int64).permute(0, 2, 3, 1)
    valid = (
        (labels == 0)
        | (labels == CERTIFIED_SKY_EVIDENCE_SKY)
        | (labels == CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY)
    )
    if not bool(valid.all()):
        raise TrainingError("Certified sky evidence labels are invalid after resize.")
    return labels


def dense_geometry_prior_loss(
    expected_depth: Any,
    alpha: Any,
    relative_inverse_depth: Any,
    road_surface_depth: Any,
    semantic: Any,
    confidence: Any,
    maximum_samples: int = 32768,
) -> tuple[Any, Any, int, int]:
    """Match relative depth ordering and a robustly fitted road surface.

    Video Depth Anything Small predicts affine-relative inverse depth.  The
    weighted Pearson term is therefore intentionally invariant to unknown
    global scale and shift.  Road pixels additionally use the SfM-aligned,
    robust piecewise surface in the same arbitrary normalized frame as gsplat.
    Neither term is interpreted as LiDAR or metres.
    """

    import torch
    import torch.nn.functional as functional

    zero = expected_depth.sum() * 0.0
    predicted_depth = expected_depth[..., 0]
    support = alpha[..., 0]
    prior = relative_inverse_depth[..., 0]
    labels = semantic[..., 0]
    weights = confidence[..., 0] * support.clamp(0.0, 1.0)
    valid = (
        torch.isfinite(predicted_depth)
        & (predicted_depth > 1e-4)
        & torch.isfinite(prior)
        & (prior > 1e-6)
        & torch.isfinite(weights)
        & (weights > 0.05)
        & (support >= 0.25)
    )
    flat_indices = torch.nonzero(valid.reshape(-1), as_tuple=False).reshape(-1)
    if len(flat_indices) > maximum_samples:
        selection = torch.linspace(
            0,
            len(flat_indices) - 1,
            maximum_samples,
            device=flat_indices.device,
        ).round().long()
        flat_indices = flat_indices[selection]
    relative_count = int(len(flat_indices))
    relative_loss = zero
    if relative_count >= 64:
        inverse = predicted_depth.reciprocal().reshape(-1)[flat_indices]
        target = prior.reshape(-1)[flat_indices]
        sample_weights = weights.reshape(-1)[flat_indices]
        weight_sum = sample_weights.sum().clamp_min(1e-6)
        inverse_centered = inverse - (sample_weights * inverse).sum() / weight_sum
        target_centered = target - (sample_weights * target).sum() / weight_sum
        covariance = (sample_weights * inverse_centered * target_centered).sum()
        inverse_energy = (sample_weights * inverse_centered.square()).sum()
        target_energy = (sample_weights * target_centered.square()).sum()
        correlation = covariance / torch.sqrt(
            (inverse_energy * target_energy).clamp_min(1e-12)
        )
        relative_loss = 1.0 - correlation.clamp(-1.0, 1.0)

    road_target = road_surface_depth[..., 0]
    road_label = (labels == 1) | (labels == 2) | (labels == 5) | (labels == 25)
    road_valid = (
        road_label
        & torch.isfinite(road_target)
        & (road_target > 1e-4)
        & torch.isfinite(predicted_depth)
        & (predicted_depth > 1e-4)
        & (support >= 0.35)
        & (confidence[..., 0] > 0.20)
    )
    road_indices = torch.nonzero(road_valid.reshape(-1), as_tuple=False).reshape(-1)
    if len(road_indices) > maximum_samples:
        selection = torch.linspace(
            0,
            len(road_indices) - 1,
            maximum_samples,
            device=road_indices.device,
        ).round().long()
        road_indices = road_indices[selection]
    road_count = int(len(road_indices))
    road_loss = zero
    if road_count >= 64:
        predicted = predicted_depth.reshape(-1)[road_indices]
        target = road_target.reshape(-1)[road_indices]
        relative_residual = (predicted - target) / target.clamp_min(1e-4)
        road_loss = functional.smooth_l1_loss(
            relative_residual,
            torch.zeros_like(relative_residual),
            beta=0.05,
        )
    return relative_loss, road_loss, relative_count, road_count


def validate_parameters(parameters: Any) -> None:
    import torch

    for name, value in parameters.items():
        if not bool(torch.isfinite(value).all()):
            raise TrainingError(f"Gaussian tensor {name} contains NaN or infinity.")
    if bool((torch.linalg.vector_norm(parameters["quats"], dim=-1) < 1e-8).any()):
        raise TrainingError("Gaussian orientation contains a zero quaternion.")


def clamp_parameters(parameters: Any, pin_surfel_z: bool = False) -> None:
    import torch
    import torch.nn.functional as functional

    with torch.no_grad():
        parameters["quats"].data.copy_(functional.normalize(parameters["quats"].data, dim=-1))
        parameters["scales"].data.clamp_(-12.0, 2.5)
        if pin_surfel_z:
            parameters["scales"].data[..., 2] = math.log(SURFEL_MINIMUM_SCALE)
        parameters["opacities"].data.clamp_(-12.0, 12.0)
        if "appearanceOpacityGates" in parameters:
            parameters["appearanceOpacityGates"].data.clamp_(-12.0, 12.0)


def cleanup_parameters(
    parameters: Any,
    normalization: dict[str, Any],
    surfel: bool = False,
) -> tuple[Any, dict[str, Any]]:
    import torch

    with torch.no_grad():
        opacity = gaussian_opacities(parameters)
        scales = torch.exp(parameters["scales"])
        # Surfels are planar by construction; anisotropy is only meaningful
        # across the two in-plane axes.
        in_plane_scales = scales[..., :2] if surfel else scales
        largest_scale = in_plane_scales.max(dim=-1).values
        anisotropy = largest_scale / in_plane_scales.min(dim=-1).values.clamp_min(1e-12)
        radius = torch.linalg.vector_norm(parameters["means"], dim=-1)
        radius_limit = max(
            10.0,
            float(normalization.get("cleanupRadiusLimitNormalized", 10.0)),
        )
        scale_limit = max(
            2.0,
            float(normalization.get("cleanupScaleLimitNormalized", 2.0)),
        )
        # Match the pinned gsplat strategy's opacity pruning threshold. Using
        # a stricter post-training cutoff silently discarded weak fine-detail
        # splats that the optimizer itself considered valid.
        transparent = opacity < 0.005
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
                "opacity>=0.005, anisotropy<=50, "
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
    indices: Sequence[int] | None = None,
    cancel_path: Path | None = None,
    phase: str = "validation",
    background_color: Any | None = None,
    directional_environment: Any | None = None,
    surfel_ablation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    import numpy as np
    import torch
    from PIL import Image

    output.mkdir(parents=True, exist_ok=True)
    psnr_values: list[float] = []
    ssim_values: list[float] = []
    ambiguity_samples: list[Any] = []
    sky_alpha_samples: list[Any] = []
    sky_alpha_views: list[dict[str, Any]] = []
    dynamic_alpha_samples: list[Any] = []
    road_relative_error_samples: list[Any] = []
    road_ambiguity_samples: list[Any] = []
    road_supported_pixels = 0
    road_target_pixels = 0
    evaluation_indices = sorted(
        dataset.validation_indices if indices is None else set(indices)
    )
    with evaluation_mode():
        for ordinal, index in enumerate(evaluation_indices):
            if cancel_path is not None and cancel_path.exists():
                raise TrainingCancelled(
                    f"Reconstruction was cancelled during {phase}."
                )
            emit(
                "evaluation_progress",
                phase=phase,
                completed=ordinal,
                total=len(evaluation_indices),
            )
            pixels_cpu, camera_cpu, calibration_cpu, _ = dataset.load(index)
            pixels = pixels_cpu.to(device=device, dtype=torch.float32).unsqueeze(0) / 255.0
            camera = camera_cpu.to(device).unsqueeze(0)
            calibration = calibration_cpu.to(device).unsqueeze(0)
            height, width = pixels.shape[1:3]
            raster_background, _ = directional_raster_background(
                directional_environment,
                camera,
                calibration,
                width,
                height,
                background_color,
            )
            rendered_depth, alpha, _ = rasterize(
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
                render_mode="RGB+ED",
                backgrounds=raster_background,
                surfel_ablation=surfel_ablation,
            )
            rendered = rendered_depth[..., :3].clamp(0.0, 1.0)
            mse = torch.mean((rendered - pixels).square()).clamp_min(1e-12)
            psnr_values.append(float((-10.0 * torch.log10(mse)).item()))
            ssim_values.append(float(ssim(rendered.permute(0, 3, 1, 2), pixels.permute(0, 3, 1, 2)).item()))
            comparison = torch.cat([pixels, rendered], dim=2)[0].mul(255).byte().cpu().numpy()
            Image.fromarray(np.asarray(comparison)).save(output / f"compare-{ordinal:03d}.png")
            view = torch.linalg.inv(camera)
            camera_z = (
                parameters["means"] @ view[0, :3, :3].transpose(0, 1)
                + view[0, :3, 3]
            )[:, 2]
            second_moment, _, _ = rasterize(
                parameters,
                camera,
                calibration,
                width,
                height,
                None,
                packed,
                False,
                rasterization_mode,
                eps2d,
                colors_override=camera_z.square().unsqueeze(1),
                surfel_ablation=surfel_ablation,
            )
            depth = rendered_depth[..., 3]
            alpha_value = alpha[..., 0].clamp_min(1e-6)
            moment2 = second_moment[..., 0] / alpha_value
            relative_std = torch.sqrt(torch.clamp(moment2 - depth.square(), min=0.0)) \
                           / depth.clamp_min(1e-4)
            valid = (
                torch.isfinite(relative_std)
                & torch.isfinite(depth)
                & (depth > 0.0)
                & (alpha_value >= 0.5)
            )
            sampled = relative_std[:, ::4, ::4][valid[:, ::4, ::4]]
            if sampled.numel() > 0:
                ambiguity_samples.append(sampled.float().cpu().numpy())
            if dataset.geometry_priors:
                relative_cpu, road_cpu, semantic_cpu = dataset.load_priors(index)
                _, road_prior, semantic_prior, _, _ = resize_geometry_priors(
                    relative_cpu,
                    road_cpu,
                    semantic_cpu,
                    height,
                    width,
                    device,
                )
                labels = semantic_prior[..., 0]
                support = alpha[..., 0]
                sky = labels == 17
                if bool(sky.any()):
                    sky_values = support[sky]
                    sky_alpha_samples.append(sky_values[::4].float().cpu().numpy())
                    sky_diagnostic = semantic_sky_view_diagnostic(
                        alpha,
                        semantic_prior,
                        dataset.records[index].name,
                    )
                    if sky_diagnostic is not None:
                        sky_alpha_views.append(sky_diagnostic)
                dynamic = (labels >= 18) & (labels <= 22)
                if bool(dynamic.any()):
                    dynamic_alpha_samples.append(
                        support[dynamic][::4].float().cpu().numpy()
                    )
                road_target = road_prior[..., 0]
                road_valid = torch.isfinite(road_target) & (road_target > 1e-4)
                road_target_pixels += int(torch.count_nonzero(road_valid).item())
                road_supported = road_valid & torch.isfinite(depth) & (depth > 1e-4) & (support >= 0.5)
                road_supported_pixels += int(torch.count_nonzero(road_supported).item())
                if bool(road_supported.any()):
                    relative_error = (
                        (depth - road_target).abs() / road_target.clamp_min(1e-4)
                    )
                    road_relative_error_samples.append(
                        relative_error[road_supported][::4].float().cpu().numpy()
                    )
                    road_ambiguity_samples.append(
                        relative_std[road_supported][::4].float().cpu().numpy()
                    )
    emit(
        "evaluation_progress",
        phase=phase,
        completed=len(evaluation_indices),
        total=len(evaluation_indices),
    )
    if not psnr_values:
        raise TrainingError("No frames were available for evaluation.")
    if not ambiguity_samples:
        raise TrainingError("Held-out renders contain no supported depth samples.")
    ambiguity = np.concatenate(ambiguity_samples)
    sky_alpha = (
        np.concatenate(sky_alpha_samples)
        if sky_alpha_samples
        else np.empty(0, dtype=np.float32)
    )
    dynamic_alpha = (
        np.concatenate(dynamic_alpha_samples)
        if dynamic_alpha_samples
        else np.empty(0, dtype=np.float32)
    )
    road_relative_error = (
        np.concatenate(road_relative_error_samples)
        if road_relative_error_samples
        else np.empty(0, dtype=np.float32)
    )
    road_ambiguity = (
        np.concatenate(road_ambiguity_samples)
        if road_ambiguity_samples
        else np.empty(0, dtype=np.float32)
    )
    return {
        "validationImages": len(psnr_values),
        "psnrMean": float(np.mean(psnr_values)),
        "psnrMedian": float(np.median(psnr_values)),
        "ssimMean": float(np.mean(ssim_values)),
        "ssimMedian": float(np.median(ssim_values)),
        "depthAmbiguityRelativeStdP50": float(np.percentile(ambiguity, 50)),
        "depthAmbiguityRelativeStdP95": float(np.percentile(ambiguity, 95)),
        "depthAmbiguityFractionAbove10Percent": float(np.mean(ambiguity > 0.10)),
        "depthAmbiguityMeaning": (
            "Relative standard deviation of composited camera-space depth; "
            "this detects mixed Gaussian layers and is not metric depth error."
        ),
        "semanticGeometry": {
            "meaning": (
                "Image-space consistency against r7 semantic and SfM-aligned "
                "navigable-surface priors; this is not metric or collision validation."
            ),
            "skySamples": int(sky_alpha.size),
            "skyAlphaP95": float(np.percentile(sky_alpha, 95))
            if sky_alpha.size
            else 0.0,
            "skyAlphaAboveTenPercentFraction": float(np.mean(sky_alpha > 0.10))
            if sky_alpha.size
            else 0.0,
            "maximumViewSkyAlphaP95": max(
                (float(view["skyAlphaP95"]) for view in sky_alpha_views),
                default=0.0,
            ),
            "skyViewCount": len(sky_alpha_views),
            "worstSkyViews": sorted(
                sky_alpha_views,
                key=lambda view: (-float(view["skyAlphaP95"]), str(view["image"])),
            )[:16],
            "dynamicSamples": int(dynamic_alpha.size),
            "dynamicAlphaP95": float(np.percentile(dynamic_alpha, 95))
            if dynamic_alpha.size
            else None,
            "roadTargetPixels": road_target_pixels,
            "roadSupportedPixels": road_supported_pixels,
            "roadSupportFraction": road_supported_pixels / max(road_target_pixels, 1),
            "roadRelativeDepthSamples": int(road_relative_error.size),
            "roadRelativeDepthP50": float(np.percentile(road_relative_error, 50))
            if road_relative_error.size
            else None,
            "roadRelativeDepthP95": float(np.percentile(road_relative_error, 95))
            if road_relative_error.size
            else None,
            "roadDepthAmbiguityP50": float(np.percentile(road_ambiguity, 50))
            if road_ambiguity.size
            else None,
            "roadDepthAmbiguityP95": float(np.percentile(road_ambiguity, 95))
            if road_ambiguity.size
            else None,
        },
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
            "pathStressImages": [
                dataset.records[index].name
                for index in sorted(dataset.path_stress_indices)
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
                    "trained": True,
                    "trainingPhase": "final-fit-all-frames",
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
    baked_opacity_logits = torch.logit(
        gaussian_opacities(parameters).clamp(1e-6, 1.0 - 1e-6)
    )
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
                        baked_opacity_logits[start:stop].unsqueeze(1),
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

    from servo_gsplat_runtime import prepare_gsplat_runtime

    gsplat_runtime_receipt = prepare_gsplat_runtime()
    from gsplat.strategy import DefaultStrategy
    from gsplat.strategy.ops import remove, reset_opa

    class EffectiveOpacityDefaultStrategy(DefaultStrategy):
        """Use export-visible opacity for pruning while preserving gsplat growth."""

        @torch.no_grad()
        def _prune_gs(
            self,
            params: Any,
            optimizers: Any,
            state: Any,
            step: int,
        ) -> int:
            is_prune = gaussian_opacities(params).flatten() < self.prune_opa
            if step > self.reset_every:
                is_too_big = (
                    torch.exp(params["scales"]).max(dim=-1).values
                    > self.prune_scale3d * state["scene_scale"]
                )
                if step < self.refine_scale2d_stop_iter:
                    is_too_big |= state["radii"] > self.prune_scale2d
                is_prune |= is_too_big
            count = int(is_prune.sum().item())
            if count > 0:
                remove(
                    params=params,
                    optimizers=optimizers,
                    state=state,
                    mask=is_prune,
                )
            return count

    class FootprintDepthDefaultStrategy(DefaultStrategy):
        """Change only gsplat's running growth statistic for the R24 A/B."""

        @torch.no_grad()
        def _update_state(
            self,
            params: Any,
            state: Any,
            info: Any,
            packed: bool = False,
        ) -> None:
            if not packed:
                raise TrainingError(
                    "Coverage-aware densification requires packed gsplat metadata."
                )
            update_coverage_densification_state(
                params,
                state,
                info,
                key_for_gradient=self.key_for_gradient,
                absgrad=self.absgrad,
                scene_scale=float(state["scene_scale"]),
                maximum_footprint_fraction=0.02,
                footprint_power=1.0,
                depth_scale_fraction=0.37,
                depth_power=2.0,
            )

        @torch.no_grad()
        def _grow_gs(
            self,
            params: Any,
            optimizers: Any,
            state: Any,
            step: int,
        ) -> tuple[int, int]:
            diagnostics = state["coverageDensificationDiagnostics"]
            treatment_score = state["grad2d"] / state["count"].clamp_min(1.0)
            default_score = diagnostics["defaultGrad2d"] / diagnostics[
                "defaultCount"
            ].clamp_min(1.0)
            treatment_candidates = treatment_score > self.grow_grad2d
            default_candidates = default_score > self.grow_grad2d
            observed = diagnostics["defaultCount"] > 0.0
            mean_footprint = diagnostics["rawFootprintSum"] / diagnostics[
                "defaultCount"
            ].clamp_min(1.0)
            mean_depth = diagnostics["depthSum"] / diagnostics[
                "defaultCount"
            ].clamp_min(1.0)
            footprint_q75 = torch.quantile(mean_footprint[observed], 0.75)
            depth_q10 = torch.quantile(mean_depth[observed], 0.10)
            top_footprint = observed & (mean_footprint >= footprint_q75)
            nearest_depth = observed & (mean_depth <= depth_q10)
            is_small = (
                torch.exp(params["scales"]).max(dim=-1).values
                <= self.grow_scale3d * state["scene_scale"]
            )

            def split_candidates(score: Any) -> Any:
                selected = (score > self.grow_grad2d) & ~is_small
                if step < self.refine_scale2d_stop_iter:
                    selected |= state["radii"] > self.grow_scale2d
                return selected

            treatment_split = split_candidates(treatment_score)
            default_split = split_candidates(default_score)
            added_split = treatment_split & ~default_split
            added_split_count = int(added_split.sum().item())
            emit(
                "coverage_densification_decision",
                step=step,
                method=COVERAGE_DENSIFICATION_METHOD,
                observations=int(diagnostics["observations"]),
                footprintSum=float(diagnostics["footprintSum"]),
                depthWeightedFootprintSum=float(
                    diagnostics["depthWeightedFootprintSum"]
                ),
                maximumFootprint=float(diagnostics["maximumFootprint"]),
                cappedObservationFraction=(
                    float(diagnostics["cappedObservations"])
                    / max(int(diagnostics["observations"]), 1)
                ),
                treatmentCandidates=int(treatment_candidates.sum().item()),
                defaultCandidates=int(default_candidates.sum().item()),
                addedCandidates=int(
                    (treatment_candidates & ~default_candidates).sum().item()
                ),
                suppressedCandidates=int(
                    (default_candidates & ~treatment_candidates).sum().item()
                ),
                treatmentSplitCandidates=int(treatment_split.sum().item()),
                defaultSplitCandidates=int(default_split.sum().item()),
                addedSplitCandidates=added_split_count,
                addedSplitTopFootprintFraction=(
                    float((added_split & top_footprint).sum().item())
                    / max(added_split_count, 1)
                ),
                addedSplitNearestDepthFraction=(
                    float((added_split & nearest_depth).sum().item())
                    / max(added_split_count, 1)
                ),
                topFootprintQuartileThreshold=float(footprint_q75.item()),
                nearestDepthDecileThreshold=float(depth_q10.item()),
                treatmentScoreMean=float(treatment_score.mean().item()),
                defaultScoreMean=float(default_score.mean().item()),
            )
            result = super()._grow_gs(params, optimizers, state, step)
            diagnostics.update(
                {
                    "observations": 0,
                    "footprintSum": 0.0,
                    "depthWeightedFootprintSum": 0.0,
                    "maximumFootprint": 0.0,
                    "cappedObservations": 0,
                    "defaultGrad2d": None,
                    "defaultCount": None,
                    "rawFootprintSum": None,
                    "depthSum": None,
                }
            )
            return result

    with config_path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if config.get("schema") != CONFIG_SCHEMA:
        raise TrainingError(f"Expected training config schema {CONFIG_SCHEMA}.")
    if config.get("representationType") != REPRESENTATION_TYPE:
        raise TrainingError(
            f"Expected reconstruction representation {REPRESENTATION_TYPE}."
        )
    for field in ("configurationHash", "pipelineCodeHash", "trainingInputHash"):
        value = config.get(field)
        if not isinstance(value, str) or not value.startswith("sha256:"):
            raise TrainingError(f"Training configuration is missing a valid {field}.")
    validate_experiment_configuration_hash(config)
    seed_value = config.get("seed", 42)
    if (
        isinstance(seed_value, bool)
        or not isinstance(seed_value, int)
        or not 0 <= seed_value <= 0xFFFFFFFF
    ):
        raise TrainingError("seed must be an unsigned 32-bit integer.")
    seed = int(seed_value)
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
    prepare_training_output(output, config)
    cancel_path = Path(config["cancelPath"])
    set_determinism(seed)
    geometry_root = (
        Path(config["geometryRoot"])
        if isinstance(config.get("geometryRoot"), str)
        else None
    )
    configured_semantic_sky_method = str(
        config.get("semanticSkyOpacityMethod", "")
    )
    contributor_sky_cleanup_enabled = config.get("contributorSkyCleanup") is True
    semantic_photometric_method = str(
        config.get("semanticPhotometricMaskMethod", "")
    )
    try:
        semantic_rigid_static_confidence_floor = float(
            config["semanticRigidStaticConfidenceFloor"]
        )
        semantic_vegetation_confidence_floor = float(
            config["semanticVegetationConfidenceFloor"]
        )
        semantic_water_confidence_floor = float(
            config["semanticWaterConfidenceFloor"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TrainingError(
            "Semantic photometric-confidence policy is incomplete."
        ) from error
    if (
        config.get("staticConfidenceMasks") is not True
        or config.get("staticConfidenceMethod") != STATIC_CONFIDENCE_METHOD
        or config.get("semanticPhotometricMask") is not True
        or semantic_photometric_method != SEMANTIC_PHOTOMETRIC_METHOD
        or not math.isclose(
            semantic_rigid_static_confidence_floor,
            0.25,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            semantic_vegetation_confidence_floor,
            0.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            semantic_water_confidence_floor,
            0.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise TrainingError(
            "The static/semantic photometric-confidence evidence contract is unsupported."
        )
    expected_geometry_hash = config.get("geometryPriorsMetricsSha256")
    certified_sky_evidence_descriptor: dict[str, Any] | None = None
    contributor_sky_evidence_descriptor: dict[str, Any] | None = None
    if config.get("geometryPriors") is True:
        if (
            geometry_root is None
            or config.get("geometryPriorsSchema") != "servo.geometry-priors/v1"
            or not isinstance(expected_geometry_hash, str)
            or not expected_geometry_hash.startswith("sha256:")
        ):
            raise TrainingError("Dense geometry-prior provenance is incomplete.")
        geometry_metrics_path = geometry_root / "geometry-metrics.json"
        if (
            not geometry_metrics_path.is_file()
            or sha256_file(geometry_metrics_path) != expected_geometry_hash
        ):
            raise TrainingError("Dense geometry-prior metrics failed hash verification.")
        if config.get("semanticPhotometricMask") is not True:
            raise TrainingError(
                "r7 geometry priors require semantic exclusion during appearance fitting."
            )
        if configured_semantic_sky_method in (
            SEMANTIC_SKY_OPACITY_METHOD,
            SEMANTIC_SKY_HYBRID_DIAGNOSTIC_METHOD,
        ):
            certified_sky_evidence_descriptor = validate_certified_sky_evidence_descriptor(
                geometry_root,
                config.get("certifiedSkyEvidence"),
            )
        if contributor_sky_cleanup_enabled:
            contributor_sky_evidence_descriptor = validate_certified_sky_evidence_descriptor(
                geometry_root,
                config.get("certifiedSkyEvidence"),
            )
    frame_oversampling_receipt = parse_frame_oversampling_config(config)
    dataset = ColmapDataset(
        Path(config["data"]),
        int(config["dataFactor"]),
        max_point_error=float(config.get("maxReprojectionError", 3.0)),
        require_static_masks=config.get("staticConfidenceMasks") is True,
        geometry_root=geometry_root,
        require_geometry_priors=config.get("geometryPriors") is True,
        require_certified_sky_evidence=(
            configured_semantic_sky_method
            in (
                SEMANTIC_SKY_OPACITY_METHOD,
                SEMANTIC_SKY_HYBRID_DIAGNOSTIC_METHOD,
            )
            or contributor_sky_cleanup_enabled
        ),
    )
    appearance_frame_selection_receipt = apply_appearance_frame_selection(
        config, dataset
    )
    (
        oversampled_frame_multipliers,
        frame_oversampling_receipt,
    ) = apply_frame_oversampling(config, dataset, frame_oversampling_receipt)
    device = "cuda:0"
    background_values = config.get("backgroundColorSrgb", [0.0, 0.0, 0.0])
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
        raise TrainingError("backgroundColorSrgb must contain three finite [0,1] values.")
    background_color = torch.tensor(
        [float(value) for value in background_values],
        device=device,
        dtype=torch.float32,
    ).view(1, 3)
    directional_environment = load_observed_directional_environment(
        geometry_root,
        config.get("observedDirectionalEnvironment"),
        device,
    )
    sh_degree = int(config.get("shDegree", 3))
    packed = bool(config.get("packed", True))
    coverage_densification: dict[str, Any] | None = None
    if isinstance(config.get("coverageAwareDensification"), Mapping):
        coverage_densification = dict(config["coverageAwareDensification"])
        if not supported_coverage_densification_contract(
            config, coverage_densification
        ):
            raise TrainingError(
                "Coverage-aware densification is sealed to the R24 "
                "non-publishable diagnostic contract."
            )
    max_steps = int(config["maxSteps"])
    checkpoint_every = int(config["checkpointEvery"])
    rasterization_mode = str(config.get("rasterizationMode", ""))
    eps2d = float(config.get("eps2d", 0.3))
    absgrad = config.get("absgrad") is True
    grow_grad2d = float(config.get("growGrad2d", 0.0008 if absgrad else 0.0002))
    coarse_factor = int(config.get("coarseFactor", 1))
    coarse_steps = int(config.get("coarseSteps", 0))
    final_fit_steps = int(config.get("finalFitSteps", 0))
    main_sampling_policy = str(config.get("mainSamplingPolicy", ""))
    endpoint_sampling_window = int(config.get("endpointSamplingWindow", 0))
    endpoint_sampling_multiplier = int(
        config.get("endpointSamplingMultiplier", 0)
    )
    maximum_sparse_anchor_multiplier = int(
        config.get("maximumSparseAnchorMultiplier", 0)
    )
    screen_space_refinement_policy = str(
        config.get("screenSpaceRefinementPolicy", "")
    )
    density_refinement_policy = str(
        config.get("densityRefinementPolicy", DENSITY_REFINEMENT_POLICY)
    )
    grow_scale2d = float(config.get("growScale2d", 0.0))
    prune_scale2d = float(config.get("pruneScale2d", 0.0))
    refine_scale2d_stop_iter = int(config.get("refineScale2dStopIter", 0))
    refine_start_iter = int(config.get("refineStartIter", 500))
    refine_every = int(config.get("refineEvery", 100))
    target_gaussians = int(config.get("targetGaussians", 0))
    max_gaussians = int(config.get("maxGaussians", 0))
    quality_gate = config.get("qualityGate", {})
    minimum_psnr = float(quality_gate.get("minimumPsnr", 18.0))
    minimum_ssim = float(quality_gate.get("minimumSsim", 0.60))
    maximum_depth_ambiguity = float(
        quality_gate.get("maximumDepthAmbiguityP50", 0.25)
    )
    maximum_depth_ambiguity_p95 = float(
        quality_gate.get("maximumDepthAmbiguityP95", 1.0)
    )
    maximum_depth_ambiguity_fraction = float(
        quality_gate.get("maximumDepthAmbiguityFractionAbove10Percent", 0.75)
    )
    minimum_final_artifact_psnr = float(
        quality_gate.get("minimumFinalArtifactPsnr", 16.0)
    )
    minimum_final_artifact_ssim = float(
        quality_gate.get("minimumFinalArtifactSsim", 0.50)
    )
    maximum_final_psnr_regression = float(
        quality_gate.get("maximumFinalPsnrRegression", 0.5)
    )
    maximum_final_ssim_regression = float(
        quality_gate.get("maximumFinalSsimRegression", 0.03)
    )
    maximum_sky_alpha_p95 = float(quality_gate.get("maximumSkyAlphaP95", 0.10))
    maximum_sky_alpha_fraction = float(
        quality_gate.get("maximumSkyAlphaAboveTenPercentFraction", 0.10)
    )
    maximum_view_sky_alpha_p95 = float(
        quality_gate.get("maximumViewSkyAlphaP95", 0.25)
    )
    minimum_road_surface_support = float(
        quality_gate.get("minimumRoadSurfaceSupport", 0.95)
    )
    maximum_road_relative_depth_p50 = float(
        quality_gate.get("maximumRoadRelativeDepthP50", 0.10)
    )
    maximum_road_relative_depth_p95 = float(
        quality_gate.get("maximumRoadRelativeDepthP95", 0.35)
    )
    maximum_road_ambiguity_p50 = float(
        quality_gate.get("maximumRoadDepthAmbiguityP50", 0.20)
    )
    maximum_road_ambiguity_p95 = float(
        quality_gate.get("maximumRoadDepthAmbiguityP95", 1.0)
    )
    appearance_enabled = config.get("appearanceCompensation") is True
    appearance_learning_rate = float(config.get("appearanceLearningRate", 1e-3))
    appearance_regularization_weight = float(
        config.get("appearanceRegularization", 1e-4)
    )
    sparse_depth_weight = float(config.get("sparseDepthWeight", 0.0))
    depth_layer_variance_weight = float(
        config.get("depthLayerVarianceWeight", 0.0)
    )
    driving_surface_variance_weight = float(
        config.get("drivingSurfaceVarianceWeight", 0.0)
    )
    surface_alignment_weight = float(config.get("surfaceAlignmentWeight", 0.0))
    road_planarity_weight = float(config.get("roadPlanarityWeight", 0.0))
    dual_opacity_enabled = config.get("dualOpacityEnabled") is True
    dual_opacity_initialization = str(
        config.get("dualOpacityInitialization", "legacy-saturated-base-v1")
    )
    dual_opacity_geometry_rgb_weight = float(
        config.get("dualOpacityGeometryRgbWeight", 0.0)
    )
    dual_opacity_prune_policy = str(
        config.get("dualOpacityPrunePolicy", "base-opacity-v1")
    )
    dual_opacity_reset_policy = str(
        config.get("dualOpacityResetPolicy", "disabled-v1")
    )
    corrected_dual_opacity = (
        dual_opacity_enabled
        and dual_opacity_initialization == DUAL_OPACITY_CORRECTED_INITIALIZATION
    )
    cross_view_depth_weight = float(
        config.get("crossViewDepthConsistencyWeight", 0.0)
    )
    if (
        appearance_frame_selection_receipt is not None
        and cross_view_depth_weight > 0.0
    ):
        raise TrainingError(
            "Appearance-frame selection currently requires cross-view depth "
            "consistency to remain disabled; pair receipts still cover every "
            "registered pose camera."
        )
    cross_view_depth_every = int(
        config.get("crossViewDepthConsistencyEvery", 8)
    )
    cross_view_depth_start = int(
        config.get("crossViewDepthConsistencyStart", 1_000)
    )
    cross_view_depth_mode = str(
        config.get("crossViewDepthMode", CROSS_VIEW_DENSE_MODE)
    )
    cross_view_minimum_valid_tracks = int(
        config.get("crossViewMinimumValidTracksPerStep", 64)
    )
    surface_alignment_every = int(config.get("surfaceAlignmentEvery", 4))
    surface_alignment_start = int(config.get("surfaceAlignmentStart", 1_000))
    depth_layer_variance_every = int(config.get("depthLayerVarianceEvery", 8))
    depth_layer_variance_start = int(config.get("depthLayerVarianceStart", 1_000))
    dense_relative_depth_weight = float(
        config.get("denseRelativeDepthWeight", 0.0)
    )
    road_surface_depth_weight = float(
        config.get("roadSurfaceDepthWeight", 0.0)
    )
    observed_detail_weight = float(config.get("observedDetailWeight", 0.0))
    observed_detail_every = int(config.get("observedDetailEvery", 1))
    observed_detail_start = int(config.get("observedDetailStart", coarse_steps))
    semantic_sky_opacity_weight = float(
        config.get("semanticSkyOpacityWeight", 0.0)
    )
    semantic_sky_opacity_method = str(
        config.get("semanticSkyOpacityMethod", "")
    )
    semantic_sky_tail_threshold = float(
        config.get("semanticSkyOpacityTailThreshold", 0.0)
    )
    semantic_sky_tail_weight = float(
        config.get("semanticSkyOpacityTailWeight", 0.0)
    )
    semantic_sky_tail_bce_epsilon = float(
        config.get("semanticSkyOpacityTailBceEpsilon", 0.0)
    )
    semantic_sky_tail_erosion_method = str(
        config.get("semanticSkyOpacityTailErosionMethod", "")
    )
    semantic_sky_tail_erosion_radius = int(
        config.get("semanticSkyOpacityTailErosionRadius", -1)
    )
    contributor_sky_cleanup_method = str(
        config.get("contributorSkyCleanupMethod", "")
    )
    contributor_sky_cleanup_start = int(
        config.get("contributorSkyCleanupStart", -1)
    )
    contributor_sky_cleanup_weight = float(
        config.get("contributorSkyCleanupWeight", 0.0)
    )
    contributor_sky_cleanup_minimum_weight = float(
        config.get("contributorSkyCleanupMinimumCompositingWeight", 0.0)
    )
    contributor_sky_cleanup_minimum_views = int(
        config.get("contributorSkyCleanupMinimumViews", 0)
    )
    contributor_sky_cleanup_minimum_view_gap = int(
        config.get("contributorSkyCleanupMinimumViewGap", 0)
    )
    contributor_sky_cleanup_audit_factor = int(
        config.get("contributorSkyCleanupAuditFactor", 0)
    )
    dense_geometry_every = int(config.get("denseGeometryEvery", 2))
    dense_geometry_start = int(config.get("denseGeometryStart", 500))
    surfel_ablation: dict[str, Any] | None = None
    surfel_depth_distortion_weight = 0.0
    surfel_normal_consistency_weight = 0.0
    surfel_normal_consistency_start = 0
    configured_surfel_schema = ""
    if isinstance(config.get("surfelAblation"), Mapping):
        raw_surfel = dict(config["surfelAblation"])
        configured_surfel_schema = str(raw_surfel.get("schema", ""))
        try:
            surfel_depth_distortion_weight = float(
                raw_surfel["depthDistortionWeight"]
            )
            surfel_normal_consistency_weight = float(
                raw_surfel["normalConsistencyWeight"]
            )
            surfel_normal_consistency_start = int(
                raw_surfel["normalConsistencyStart"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TrainingError(
                "The surfel 2DGS A/B configuration is incomplete."
            ) from error
        if not supported_surfel_ablation_contract(
            config,
            schema=configured_surfel_schema,
            method=str(raw_surfel.get("method", "")),
            depth_distortion_weight=surfel_depth_distortion_weight,
            normal_consistency_weight=surfel_normal_consistency_weight,
            normal_consistency_start=surfel_normal_consistency_start,
            coarse_steps=coarse_steps,
        ):
            raise TrainingError(
                "The surfel 2DGS A/B contract is sealed to non-publishable "
                "diagnostics with bounded weights and a post-coarse normal start."
            )
        surfel_ablation = {
            "schema": configured_surfel_schema,
            "method": str(raw_surfel.get("method", "")),
            "depthDistortionWeight": surfel_depth_distortion_weight,
            "normalConsistencyWeight": surfel_normal_consistency_weight,
            "normalConsistencyStart": surfel_normal_consistency_start,
        }
    if max_steps <= 0 or checkpoint_every <= 0:
        raise TrainingError("Training and checkpoint step counts must be positive.")
    if (
        refine_start_iter < 0
        or refine_start_iter >= refine_scale2d_stop_iter
        or refine_every <= 0
        or (
            (refine_start_iter != 500 or refine_every != 100)
            and not (
                is_nonpublishable_diagnostic_config(config)
                and refine_start_iter == 100
                and refine_every == 100
            )
        )
    ):
        raise TrainingError("The density refinement schedule is unsupported.")
    if corrected_dual_opacity and (
        not is_nonpublishable_diagnostic_config(config)
        or not 0.0 < dual_opacity_geometry_rgb_weight <= 0.10
        or dual_opacity_prune_policy != DUAL_OPACITY_EFFECTIVE_PRUNE_POLICY
        or dual_opacity_reset_policy != DUAL_OPACITY_PRODUCT_RESET_POLICY
    ):
        raise TrainingError(
            "The corrected dual-opacity lifecycle is sealed to its bounded "
            "non-publishable diagnostic contract."
        )
    if coverage_densification is not None and (
        not packed
        or surfel_ablation is not None
        or dual_opacity_enabled
        or cross_view_depth_weight > 0.0
        or bool(config.get("revisedOpacity", False))
    ):
        raise TrainingError(
            "R24 coverage-aware densification requires packed, single-opacity "
            "3DGS with no cross-view or surfel treatment."
        )
    if (
        dual_opacity_enabled
        and not corrected_dual_opacity
        and dual_opacity_geometry_rgb_weight > 0.0
    ):
        raise TrainingError(
            "Base-opacity RGB accountability requires the corrected lifecycle."
        )
    if rasterization_mode not in {"classic", "antialiased"}:
        raise TrainingError("rasterizationMode must be classic or antialiased.")
    if not math.isfinite(eps2d) or eps2d <= 0.0:
        raise TrainingError("eps2d must be a positive finite value.")
    if not math.isfinite(grow_grad2d) or grow_grad2d <= 0.0:
        raise TrainingError("growGrad2d must be a positive finite value.")
    if coarse_factor < 1 or coarse_steps < 0 or coarse_steps >= max_steps:
        raise TrainingError("The coarse-to-fine resolution schedule is invalid.")
    if final_fit_steps <= 0 or final_fit_steps >= max_steps // 2:
        raise TrainingError("finalFitSteps must reserve a bounded finishing phase.")
    # Production keeps density refinement throughout main fitting. A sealed
    # diagnostic can freeze it at the proven early geometry point, then spend
    # the remaining budget on full-resolution appearance convergence.
    main_fit_stop_iter = max_steps - final_fit_steps
    if (
        main_sampling_policy != MAIN_SAMPLING_POLICY
        or endpoint_sampling_window != ENDPOINT_SAMPLING_WINDOW
        or endpoint_sampling_multiplier != ENDPOINT_SAMPLING_MULTIPLIER
        or maximum_sparse_anchor_multiplier != MAXIMUM_SPARSE_ANCHOR_MULTIPLIER
    ):
        raise TrainingError("The deterministic capture-coverage sampling policy is unsupported.")
    if (
        screen_space_refinement_policy != SCREEN_SPACE_REFINEMENT_POLICY
        or not math.isclose(grow_scale2d, 0.05, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(prune_scale2d, 0.15, rel_tol=0.0, abs_tol=1e-12)
        or not supported_density_refinement_contract(
            config,
            policy=density_refinement_policy,
            stop_iter=refine_scale2d_stop_iter,
            main_fit_stop_iter=main_fit_stop_iter,
            coarse_steps=coarse_steps,
            dense_geometry_start=dense_geometry_start,
        )
    ):
        raise TrainingError("The gsplat screen-space refinement policy is unsupported.")
    if target_gaussians < 100_000 or target_gaussians * 2 > max_gaussians:
        raise TrainingError(
            "targetGaussians must be meaningful and no greater than half the allocation ceiling."
        )
    if max_gaussians < 100_000:
        raise TrainingError("maxGaussians must reserve a meaningful bounded scene budget.")
    if (
        not math.isfinite(minimum_psnr)
        or not math.isfinite(minimum_ssim)
        or not math.isfinite(maximum_depth_ambiguity)
        or not math.isfinite(maximum_depth_ambiguity_p95)
        or not math.isfinite(maximum_depth_ambiguity_fraction)
        or not math.isfinite(minimum_final_artifact_psnr)
        or not math.isfinite(minimum_final_artifact_ssim)
        or not math.isfinite(maximum_final_psnr_regression)
        or not math.isfinite(maximum_final_ssim_regression)
        or minimum_psnr <= 0.0
        or not 0.0 < minimum_ssim <= 1.0
        or maximum_depth_ambiguity <= 0.0
        or maximum_depth_ambiguity_p95 <= 0.0
        or not 0.0 <= maximum_depth_ambiguity_fraction <= 1.0
        or minimum_final_artifact_psnr <= 0.0
        or not 0.0 < minimum_final_artifact_ssim <= 1.0
        or maximum_final_psnr_regression < 0.0
        or maximum_final_ssim_regression < 0.0
    ):
        raise TrainingError("The configured quality gate is invalid.")
    if (
        not math.isfinite(appearance_learning_rate)
        or appearance_learning_rate <= 0.0
        or not math.isfinite(appearance_regularization_weight)
        or appearance_regularization_weight < 0.0
    ):
        raise TrainingError("Appearance compensation settings are invalid.")
    if (
        not math.isfinite(sparse_depth_weight)
        or sparse_depth_weight < 0.0
        or not math.isfinite(depth_layer_variance_weight)
        or depth_layer_variance_weight < 0.0
        or depth_layer_variance_every <= 0
        or depth_layer_variance_start < 0
        or depth_layer_variance_start >= max_steps
        or not math.isfinite(dense_relative_depth_weight)
        or dense_relative_depth_weight < 0.0
        or not math.isfinite(road_surface_depth_weight)
        or road_surface_depth_weight < 0.0
        or not math.isfinite(observed_detail_weight)
        or observed_detail_weight < 0.0
        or observed_detail_every <= 0
        or observed_detail_start < 0
        or not math.isfinite(driving_surface_variance_weight)
        or driving_surface_variance_weight < 0.0
        or not math.isfinite(surface_alignment_weight)
        or surface_alignment_weight < 0.0
        or not math.isfinite(road_planarity_weight)
        or road_planarity_weight < 0.0
        or surface_alignment_every <= 0
        or surface_alignment_start < 0
        or surface_alignment_start >= max_steps
        or not math.isfinite(semantic_sky_opacity_weight)
        or semantic_sky_opacity_weight < 0.0
        or not math.isfinite(semantic_sky_tail_threshold)
        or not 0.0 <= semantic_sky_tail_threshold < 1.0
        or not math.isfinite(semantic_sky_tail_weight)
        or semantic_sky_tail_weight < 0.0
        or not math.isfinite(semantic_sky_tail_bce_epsilon)
        or not 0.0 < semantic_sky_tail_bce_epsilon < 1.0
        or semantic_sky_tail_erosion_radius < 0
        or dense_geometry_every <= 0
        or dense_geometry_start < 0
        or dense_geometry_start >= max_steps
    ):
        raise TrainingError("Geometry regularization settings are invalid.")
    if (
        dense_relative_depth_weight > 0.0
        or road_surface_depth_weight > 0.0
        or semantic_sky_opacity_weight > 0.0
    ) and not dataset.geometry_priors:
        raise TrainingError(
            "Dense geometry regularization requires complete depth and semantic priors."
        )
    if dual_opacity_enabled and not any(
        weight > 0.0
        for weight in (
            sparse_depth_weight,
            depth_layer_variance_weight,
            dense_relative_depth_weight,
            road_surface_depth_weight,
            surface_alignment_weight,
            road_planarity_weight,
            driving_surface_variance_weight,
            semantic_sky_opacity_weight,
            contributor_sky_cleanup_weight,
            cross_view_depth_weight,
            surfel_depth_distortion_weight,
            surfel_normal_consistency_weight,
        )
    ):
        raise TrainingError(
            "Dual opacity requires at least one geometry or certified cleanup "
            "objective; otherwise its geometry channel is unconstrained."
        )
    if (
        cross_view_depth_weight < 0.0
        or cross_view_depth_every <= 0
        or cross_view_depth_start < 0
        or cross_view_depth_start >= max_steps
        or cross_view_minimum_valid_tracks < 8
    ):
        raise TrainingError("Cross-view depth consistency settings are invalid.")
    if cross_view_depth_mode not in {
        CROSS_VIEW_DENSE_MODE,
        CROSS_VIEW_SPARSE_TRACK_MODE,
    }:
        raise TrainingError("The cross-view depth mode is unsupported.")
    if cross_view_depth_weight > 0.0:
        if cross_view_depth_mode == CROSS_VIEW_DENSE_MODE and not dual_opacity_enabled:
            raise TrainingError(
                "Dense self-reprojected cross-view depth requires dual opacity."
            )
        if cross_view_depth_mode == CROSS_VIEW_SPARSE_TRACK_MODE and (
            dual_opacity_enabled
            or not is_nonpublishable_diagnostic_config(config)
            or cross_view_depth_weight > 0.01
        ):
            raise TrainingError(
                "Sparse shared-track cross-view depth is sealed to a bounded "
                "single-opacity non-publishable diagnostic."
            )
    if cross_view_depth_weight > 0.0 and not dataset.cross_view_pairs:
        raise TrainingError(
            "No calibrated co-visible training pairs satisfy the cross-view contract."
        )
    if (
        cross_view_depth_weight > 0.0
        and cross_view_depth_mode == CROSS_VIEW_SPARSE_TRACK_MODE
        and not dataset.cross_view_sparse_tracks
    ):
        raise TrainingError(
            "No selected camera pair has shared reliable COLMAP track samples."
        )
    if (
        semantic_sky_opacity_weight > 0.0
        and not supported_semantic_sky_opacity_contract(
            config,
            method=semantic_sky_opacity_method,
            tail_threshold=semantic_sky_tail_threshold,
            tail_weight=semantic_sky_tail_weight,
            tail_bce_epsilon=semantic_sky_tail_bce_epsilon,
            tail_erosion_method=semantic_sky_tail_erosion_method,
            tail_erosion_radius=semantic_sky_tail_erosion_radius,
        )
    ):
        raise TrainingError(
            "Semantic sky-opacity regularization has an unsupported evidence contract."
        )
    if not supported_contributor_sky_cleanup_contract(
        config,
        enabled=contributor_sky_cleanup_enabled,
        method=contributor_sky_cleanup_method,
        start_step=contributor_sky_cleanup_start,
        refine_stop_iter=refine_scale2d_stop_iter,
        minimum_weight=contributor_sky_cleanup_minimum_weight,
        minimum_views=contributor_sky_cleanup_minimum_views,
        minimum_view_gap=contributor_sky_cleanup_minimum_view_gap,
        audit_factor=contributor_sky_cleanup_audit_factor,
        loss_weight=contributor_sky_cleanup_weight,
    ):
        raise TrainingError(
            "Contributor sky cleanup has an unsupported diagnostic contract."
        )
    if (
        sparse_depth_weight > 0.0
        and int(dataset.initialization_stats.get("sparseDepthObservations", 0))
        < len(dataset) * 8
    ):
        raise TrainingError(
            "The COLMAP model has too few reliable image-space depth anchors "
            "for geometry-regularized Gaussian fitting."
        )
    render_requirements = geometry_render_requirements(
        sparse_depth_weight=sparse_depth_weight,
        depth_layer_variance_weight=depth_layer_variance_weight,
        driving_surface_variance_weight=driving_surface_variance_weight,
        dense_relative_depth_weight=dense_relative_depth_weight,
        road_surface_depth_weight=road_surface_depth_weight,
        surface_alignment_weight=surface_alignment_weight,
        road_planarity_weight=road_planarity_weight,
        cross_view_depth_weight=cross_view_depth_weight,
        semantic_sky_opacity_weight=semantic_sky_opacity_weight,
        surfel_depth_distortion_weight=surfel_depth_distortion_weight,
        surfel_normal_consistency_weight=surfel_normal_consistency_weight,
    )
    needs_geometry_depth = render_requirements["depth"]
    needs_geometry_render = render_requirements["geometryRender"]
    needs_surfel_aux = render_requirements["surfelAux"]
    strategy_type = (
        FootprintDepthDefaultStrategy
        if coverage_densification is not None
        else EffectiveOpacityDefaultStrategy
        if corrected_dual_opacity
        else DefaultStrategy
    )
    strategy = strategy_type(
        prune_opa=0.005,
        grow_grad2d=0.0002 if surfel_ablation is not None else grow_grad2d,
        grow_scale3d=0.01,
        grow_scale2d=grow_scale2d,
        prune_scale3d=0.10,
        prune_scale2d=prune_scale2d,
        refine_scale2d_stop_iter=refine_scale2d_stop_iter,
        refine_start_iter=refine_start_iter,
        refine_stop_iter=refine_scale2d_stop_iter,
        # Resetting the geometry opacity would collapse the RGB product and
        # defeat the dual-opacity representation. Densification and pruning
        # remain active; only periodic opacity reset is moved beyond the run.
        reset_every=(
            3_000 if corrected_dual_opacity or not dual_opacity_enabled else max_steps + 1
        ),
        refine_every=refine_every,
        absgrad=False if surfel_ablation is not None else absgrad,
        verbose=False,
        key_for_gradient=(
            "gradient_2dgs" if surfel_ablation is not None else "means2d"
        ),
    )
    checkpoint_dir = output / "checkpoints"
    checkpoint = load_checkpoint(checkpoint_dir, config)
    if checkpoint is None:
        parameters = create_parameters(
            dataset,
            sh_degree,
            device,
            dual_opacity=dual_opacity_enabled,
            dual_opacity_initialization=dual_opacity_initialization,
        )
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
        density_growth_frozen = False
        recent_loss: float | None = None
        sparse_depth_samples = 0
        cross_view_depth_steps = 0
        cross_view_depth_samples = 0
        recent_cross_view_depth_loss = 0.0
        depth_layer_variance_steps = 0
        recent_sparse_depth_loss = 0.0
        recent_depth_layer_variance_loss = 0.0
        recent_depth_layer_variance_step: int | None = None
        recent_driving_surface_variance_loss = 0.0
        surface_alignment_steps = 0
        surface_alignment_samples = 0
        road_planarity_samples = 0
        recent_surface_alignment_loss = 0.0
        recent_road_planarity_loss = 0.0
        dense_geometry_steps = 0
        dense_relative_depth_samples = 0
        road_surface_depth_samples = 0
        recent_dense_relative_depth_loss = 0.0
        recent_road_surface_depth_loss = 0.0
        recent_dense_geometry_step: int | None = None
        observed_detail_steps = 0
        recent_observed_detail_loss = 0.0
        recent_observed_detail_step: int | None = None
        surfel_depth_distortion_steps = 0
        recent_surfel_depth_distortion_loss = 0.0
        surfel_normal_consistency_steps = 0
        recent_surfel_normal_consistency_loss = 0.0
        semantic_sky_opacity_steps = 0
        semantic_sky_opacity_samples = 0
        recent_semantic_sky_opacity_loss = 0.0
        elapsed_before = 0.0
        peak_allocated_before = 0.0
        peak_reserved_before = 0.0
        emit("training_initialized", gaussians=len(parameters["means"]), images=len(dataset))
    else:
        parameters = parameters_from_state(
            checkpoint["splats"], device, dual_opacity=dual_opacity_enabled
        )
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
        density_growth_frozen = bool(
            checkpoint.get("policyState", {}).get("densityGrowthFrozen", False)
        )
        # Checkpoints created before the explicit growth-freeze receipt used
        # the limit reason only.  Preserve the safer target-cap meaning while
        # still allowing a memory-recovery checkpoint to stop all refinement.
        if (
            not density_growth_frozen
            and densification_limit_reason == "gaussian-target-reached"
        ):
            density_growth_frozen = True
        recent_loss_value = checkpoint.get("policyState", {}).get("recentLoss")
        recent_loss = (
            float(recent_loss_value)
            if isinstance(recent_loss_value, (int, float))
            and math.isfinite(float(recent_loss_value))
            else None
        )
        sparse_depth_samples = int(
            checkpoint.get("policyState", {}).get("sparseDepthSamples", 0)
        )
        cross_view_depth_steps = int(
            checkpoint.get("policyState", {}).get("crossViewDepthSteps", 0)
        )
        cross_view_depth_samples = int(
            checkpoint.get("policyState", {}).get("crossViewDepthSamples", 0)
        )
        recent_cross_view_depth_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentCrossViewDepthLoss", 0.0
            )
        )
        depth_layer_variance_steps = int(
            checkpoint.get("policyState", {}).get("depthLayerVarianceSteps", 0)
        )
        recent_sparse_depth_loss = float(
            checkpoint.get("policyState", {}).get("recentSparseDepthLoss", 0.0)
        )
        recent_depth_layer_variance_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentDepthLayerVarianceLoss", 0.0
            )
        )
        recent_depth_layer_variance_step_value = checkpoint.get(
            "policyState", {}
        ).get("recentDepthLayerVarianceStep")
        recent_depth_layer_variance_step = (
            int(recent_depth_layer_variance_step_value)
            if isinstance(recent_depth_layer_variance_step_value, int)
            else None
        )
        recent_driving_surface_variance_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentDrivingSurfaceVarianceLoss", 0.0
            )
        )
        surface_alignment_steps = int(
            checkpoint.get("policyState", {}).get("surfaceAlignmentSteps", 0)
        )
        surface_alignment_samples = int(
            checkpoint.get("policyState", {}).get("surfaceAlignmentSamples", 0)
        )
        road_planarity_samples = int(
            checkpoint.get("policyState", {}).get("roadPlanaritySamples", 0)
        )
        recent_surface_alignment_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentSurfaceAlignmentLoss", 0.0
            )
        )
        recent_road_planarity_loss = float(
            checkpoint.get("policyState", {}).get("recentRoadPlanarityLoss", 0.0)
        )
        dense_geometry_steps = int(
            checkpoint.get("policyState", {}).get("denseGeometrySteps", 0)
        )
        dense_relative_depth_samples = int(
            checkpoint.get("policyState", {}).get(
                "denseRelativeDepthSamples", 0
            )
        )
        road_surface_depth_samples = int(
            checkpoint.get("policyState", {}).get(
                "roadSurfaceDepthSamples", 0
            )
        )
        recent_dense_relative_depth_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentDenseRelativeDepthLoss", 0.0
            )
        )
        recent_road_surface_depth_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentRoadSurfaceDepthLoss", 0.0
            )
        )
        recent_dense_geometry_step_value = checkpoint.get("policyState", {}).get(
            "recentDenseGeometryStep"
        )
        recent_dense_geometry_step = (
            int(recent_dense_geometry_step_value)
            if isinstance(recent_dense_geometry_step_value, int)
            else None
        )
        observed_detail_steps = int(
            checkpoint.get("policyState", {}).get("observedDetailSteps", 0)
        )
        recent_observed_detail_loss = float(
            checkpoint.get("policyState", {}).get("recentObservedDetailLoss", 0.0)
        )
        recent_observed_detail_step_value = checkpoint.get("policyState", {}).get(
            "recentObservedDetailStep"
        )
        recent_observed_detail_step = (
            int(recent_observed_detail_step_value)
            if isinstance(recent_observed_detail_step_value, int)
            else None
        )
        semantic_sky_opacity_steps = int(
            checkpoint.get("policyState", {}).get(
                "semanticSkyOpacitySteps", 0
            )
        )
        semantic_sky_opacity_samples = int(
            checkpoint.get("policyState", {}).get(
                "semanticSkyOpacitySamples", 0
            )
        )
        recent_semantic_sky_opacity_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentSemanticSkyOpacityLoss", 0.0
            )
        )
        surfel_depth_distortion_steps = int(
            checkpoint.get("policyState", {}).get(
                "surfelDepthDistortionSteps", 0
            )
        )
        recent_surfel_depth_distortion_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentSurfelDepthDistortionLoss", 0.0
            )
        )
        surfel_normal_consistency_steps = int(
            checkpoint.get("policyState", {}).get(
                "surfelNormalConsistencySteps", 0
            )
        )
        recent_surfel_normal_consistency_loss = float(
            checkpoint.get("policyState", {}).get(
                "recentSurfelNormalConsistencyLoss", 0.0
            )
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
        if density_growth_frozen:
            freeze_density_growth_at_target(strategy)
        elif densification_limited:
            strategy.refine_stop_iter = min(strategy.refine_stop_iter, start_step)
        restore_rng(checkpoint)
        emit("training_resumed", step=start_step, gaussians=len(parameters["means"]))
    strategy.check_sanity(parameters, optimizers)
    recovery_policy_path = checkpoint_dir / "recovery-policy.json"
    heldout_metrics_path = output / "heldout-metrics.json"
    heldout_evaluation_step = max_steps - final_fit_steps
    all_indices = list(dataset.appearance_indices)
    main_sampler = DeterministicWeightedEpochSampler(
        dataset.training_sampling_plan.epoch_slots,
        config["trainingInputHash"],
        "main-fit",
    )
    main_fit_visits = [0] * len(dataset)
    completed_main_fit = min(max(start_step, 0), heldout_evaluation_step)
    for completed_offset in range(completed_main_fit):
        main_fit_visits[main_sampler.index(completed_offset)] += 1
    if final_fit_steps < len(all_indices):
        raise TrainingError(
            "finalFitSteps must visit every selected appearance camera at least once."
        )
    final_fit_seen: set[int] = set()
    final_fit_epoch = -1
    final_fit_order: list[int] = []
    contributor_sky_cleanup_mask = None
    contributor_sky_cleanup_ledger: dict[str, Any] | None = None
    contributor_sky_cleanup_steps = 0
    recent_contributor_sky_cleanup_loss = 0.0

    def final_fit_index(offset: int) -> int:
        nonlocal final_fit_epoch, final_fit_order
        epoch = offset // len(all_indices)
        if epoch != final_fit_epoch:
            final_fit_epoch = epoch
            final_fit_order = all_indices.copy()
            random.Random(
                f"{config['trainingInputHash']}:final-fit:{epoch}"
            ).shuffle(final_fit_order)
        return final_fit_order[offset % len(all_indices)]

    completed_final_fit = max(
        0,
        min(final_fit_steps, start_step - heldout_evaluation_step),
    )
    for completed_offset in range(completed_final_fit):
        final_fit_seen.add(final_fit_index(completed_offset))
    if recovery_policy_path.is_file():
        with recovery_policy_path.open("r", encoding="utf-8") as stream:
            recovery_policy = json.load(stream)
        if (
            recovery_policy.get("schema")
            in {"servo.gsplat-recovery-policy/v1", "servo.gsplat-recovery-policy/v2"}
            and recovery_policy.get("configurationHash") == config["configurationHash"]
            and recovery_policy.get("trainingInputHash") == config["trainingInputHash"]
            and (
                recovery_policy.get("disableDensification") is True
                or recovery_policy.get("freezeGrowth") is True
            )
        ):
            densification_limited = True
            densification_limit_reason = str(
                recovery_policy.get("reason") or "recovery-policy"
            )
            density_growth_frozen = bool(
                recovery_policy.get("freezeGrowth") is True
                or densification_limit_reason == "gaussian-target-reached"
            )
            if density_growth_frozen:
                freeze_density_growth_at_target(strategy)
            else:
                strategy.refine_stop_iter = min(strategy.refine_stop_iter, start_step)
            emit(
                "densification_recovery_enabled",
                step=start_step,
                growthFrozen=density_growth_frozen,
                pruningContinuesUntil=(
                    strategy.refine_stop_iter if density_growth_frozen else None
                ),
            )
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

    recent_dual_opacity_geometry_rgb_loss = 0.0

    def current_policy_state() -> dict[str, Any]:
        return {
            "densificationLimited": densification_limited,
            "densificationLimitReason": densification_limit_reason,
            "densityGrowthFrozen": density_growth_frozen,
            "densityGrowthCapPolicy": DENSITY_GROWTH_CAP_POLICY,
            "recentLoss": recent_loss,
            "sparseDepthSamples": sparse_depth_samples,
            "crossViewDepthSteps": cross_view_depth_steps,
            "crossViewDepthSamples": cross_view_depth_samples,
            "recentCrossViewDepthLoss": recent_cross_view_depth_loss,
            "depthLayerVarianceSteps": depth_layer_variance_steps,
            "recentSparseDepthLoss": recent_sparse_depth_loss,
            "recentDepthLayerVarianceLoss": recent_depth_layer_variance_loss,
            "recentDepthLayerVarianceStep": recent_depth_layer_variance_step,
            "recentDrivingSurfaceVarianceLoss": recent_driving_surface_variance_loss,
            "surfaceAlignmentSteps": surface_alignment_steps,
            "surfaceAlignmentSamples": surface_alignment_samples,
            "roadPlanaritySamples": road_planarity_samples,
            "recentSurfaceAlignmentLoss": recent_surface_alignment_loss,
            "recentRoadPlanarityLoss": recent_road_planarity_loss,
            "denseGeometrySteps": dense_geometry_steps,
            "denseRelativeDepthSamples": dense_relative_depth_samples,
            "roadSurfaceDepthSamples": road_surface_depth_samples,
            "recentDenseRelativeDepthLoss": recent_dense_relative_depth_loss,
            "recentRoadSurfaceDepthLoss": recent_road_surface_depth_loss,
            "recentDenseGeometryStep": recent_dense_geometry_step,
            "observedDetailSteps": observed_detail_steps,
            "recentObservedDetailLoss": recent_observed_detail_loss,
            "recentObservedDetailStep": recent_observed_detail_step,
            "semanticSkyOpacitySteps": semantic_sky_opacity_steps,
            "semanticSkyOpacitySamples": semantic_sky_opacity_samples,
            "recentSemanticSkyOpacityLoss": recent_semantic_sky_opacity_loss,
            "surfelDepthDistortionSteps": surfel_depth_distortion_steps,
            "recentSurfelDepthDistortionLoss": recent_surfel_depth_distortion_loss,
            "surfelNormalConsistencySteps": surfel_normal_consistency_steps,
            "recentSurfelNormalConsistencyLoss": (
                recent_surfel_normal_consistency_loss
            ),
            "contributorSkyCleanupSteps": contributor_sky_cleanup_steps,
            "recentContributorSkyCleanupLoss": recent_contributor_sky_cleanup_loss,
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

    def require_heldout_snapshot(value: Any) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or value.get("schema") != "servo.gsplat-heldout-evaluation/v1"
            or value.get("jobId") != config.get("jobId")
            or value.get("profile") != config.get("profile")
            or value.get("pipelineRevision") != config.get("pipelineRevision")
            or value.get("configurationHash") != config["configurationHash"]
            or value.get("trainingInputHash") != config["trainingInputHash"]
            or value.get("evaluatedAtStep") != heldout_evaluation_step
        ):
            raise TrainingError("The pre-fit held-out evaluation is incompatible.")
        checkpoint_reference = value.get("checkpoint")
        if not isinstance(checkpoint_reference, dict):
            raise TrainingError("The held-out evaluation has no checkpoint receipt.")
        checkpoint_name = checkpoint_reference.get("path")
        if (
            not isinstance(checkpoint_name, str)
            or Path(checkpoint_name).name != checkpoint_name
            or int(checkpoint_reference.get("step", -2))
            != heldout_evaluation_step - 1
            or checkpoint_reference.get("configurationHash")
            != config["configurationHash"]
            or checkpoint_reference.get("trainingInputHash")
            != config["trainingInputHash"]
        ):
            raise TrainingError("The held-out checkpoint receipt is incompatible.")
        checkpoint_path = checkpoint_dir / checkpoint_name
        if not checkpoint_path.is_file():
            raise TrainingError("The exact held-out checkpoint has been lost.")
        expected_bytes = int(checkpoint_reference.get("bytes", -1))
        expected_digest = checkpoint_reference.get("sha256")
        if (
            checkpoint_path.stat().st_size != expected_bytes
            or not isinstance(expected_digest, str)
            or sha256_file(checkpoint_path) != expected_digest
        ):
            raise TrainingError("The exact held-out checkpoint failed verification.")
        return value

    if start_step > heldout_evaluation_step:
        if not heldout_metrics_path.is_file():
            raise TrainingError(
                "The final-fit checkpoint is missing its pre-fit held-out evaluation."
            )
        with heldout_metrics_path.open("r", encoding="utf-8") as stream:
            heldout_snapshot = require_heldout_snapshot(json.load(stream))

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
        if (
            contributor_sky_cleanup_enabled
            and contributor_sky_cleanup_mask is None
            and step >= contributor_sky_cleanup_start
        ):
            if contributor_sky_evidence_descriptor is None:
                raise TrainingError(
                    "Contributor cleanup requires certified sky evidence."
                )
            if step < int(strategy.refine_stop_iter):
                raise TrainingError(
                    "Contributor attribution cannot run before Gaussian IDs freeze."
                )
            (
                contributor_sky_cleanup_mask,
                contributor_sky_cleanup_ledger,
            ) = build_certified_sky_contributor_ledger(
                parameters,
                dataset,
                device,
                sh_degree=sh_degree,
                packed=packed,
                rasterization_mode=rasterization_mode,
                eps2d=eps2d,
                audit_factor=contributor_sky_cleanup_audit_factor,
                minimum_weight=contributor_sky_cleanup_minimum_weight,
                minimum_views=contributor_sky_cleanup_minimum_views,
                minimum_view_gap=contributor_sky_cleanup_minimum_view_gap,
                cancel_path=cancel_path,
                descriptor=contributor_sky_evidence_descriptor,
                config=config,
                output=output,
            )
            if not bool(contributor_sky_cleanup_mask.any()):
                contributor_sky_cleanup_enabled = False
                contributor_sky_cleanup_mask = None
                emit(
                    "contributor_cleanup_skipped",
                    reason="no-qualified-targets",
                    qualifiedGaussians=0,
                )
        if step == heldout_evaluation_step:
            # Persist the exact parameter/optimizer state that is about to be
            # evaluated.  Later final-fit checkpoints must not replace it:
            # held-out metrics are only reproducible when they are bound to
            # this verified checkpoint receipt.
            heldout_checkpoint_path = save_checkpoint(
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
            heldout_checkpoint_receipt = json.loads(
                heldout_checkpoint_path.with_suffix(".json").read_text(
                    encoding="utf-8"
                )
            )
            heldout_snapshot = {
                "schema": "servo.gsplat-heldout-evaluation/v1",
                "jobId": config.get("jobId"),
                "profile": config.get("profile"),
                "pipelineRevision": config.get("pipelineRevision"),
                "configurationHash": config["configurationHash"],
                "trainingInputHash": config["trainingInputHash"],
                "evaluatedAtStep": step,
                "checkpoint": {
                    key: heldout_checkpoint_receipt[key]
                    for key in (
                        "step",
                        "path",
                        "sha256",
                        "bytes",
                        "configurationHash",
                        "trainingInputHash",
                    )
                },
                **evaluate(
                    parameters,
                    dataset,
                    device,
                    sh_degree,
                    packed,
                    rasterization_mode,
                    eps2d,
                    output / "validation",
                    cancel_path=cancel_path,
                    phase="heldout-validation",
                    background_color=background_color,
                    directional_environment=directional_environment,
                    surfel_ablation=surfel_ablation,
                ),
            }
            if dataset.path_stress_indices:
                heldout_snapshot["pathStress"] = evaluate(
                    parameters,
                    dataset,
                    device,
                    sh_degree,
                    packed,
                    rasterization_mode,
                    eps2d,
                    output / "path-stress-validation",
                    dataset.path_stress_indices,
                    cancel_path=cancel_path,
                    phase="path-stress-validation",
                    background_color=background_color,
                    directional_environment=directional_environment,
                    surfel_ablation=surfel_ablation,
                )
            atomic_json(heldout_metrics_path, heldout_snapshot)
            emit(
                "heldout_evaluation_completed",
                step=step,
                psnrMean=heldout_snapshot["psnrMean"],
                ssimMean=heldout_snapshot["ssimMean"],
                finalFitSteps=final_fit_steps,
            )
            if (
                float(heldout_snapshot["psnrMean"]) < minimum_psnr
                or float(heldout_snapshot["ssimMean"]) < minimum_ssim
                or float(heldout_snapshot["depthAmbiguityRelativeStdP50"])
                > maximum_depth_ambiguity
                or float(heldout_snapshot["depthAmbiguityRelativeStdP95"])
                > maximum_depth_ambiguity_p95
                or float(
                    heldout_snapshot[
                        "depthAmbiguityFractionAbove10Percent"
                    ]
                )
                > maximum_depth_ambiguity_fraction
            ):
                raise TrainingError(
                    "The unbiased held-out reconstruction failed the configured "
                    "appearance or geometry gate; final fitting was not started."
                )
        final_fit = step >= heldout_evaluation_step
        if final_fit:
            final_fit_offset = step - heldout_evaluation_step
            index = final_fit_index(final_fit_offset)
            final_fit_seen.add(index)
        else:
            index = main_sampler.index(step)
            main_fit_visits[index] += 1
        pixels_cpu, camera_cpu, calibration_cpu, confidence_cpu = dataset.load(index)
        geometry_cpu = dataset.load_priors(index) if dataset.geometry_priors else None
        pixels = pixels_cpu.to(device=device, dtype=torch.float32, non_blocking=True).unsqueeze(0) / 255.0
        confidence = (
            confidence_cpu.to(device=device, dtype=torch.float32, non_blocking=True)
            .unsqueeze(0)
            .unsqueeze(-1)
            / 255.0
        )
        camera = camera_cpu.to(device, non_blocking=True).unsqueeze(0)
        calibration = calibration_cpu.to(device, non_blocking=True).unsqueeze(0)
        active_resolution_factor = coarse_factor if step < coarse_steps else 1
        pixels, calibration = downscale_training_sample(
            pixels,
            calibration,
            active_resolution_factor,
        )
        if active_resolution_factor > 1:
            confidence = functional.interpolate(
                confidence.permute(0, 3, 1, 2),
                size=pixels.shape[1:3],
                mode="area",
            ).permute(0, 2, 3, 1)
        height, width = pixels.shape[1:3]
        relative_prior = None
        road_depth_prior = None
        semantic_prior = None
        certified_sky_prior = None
        geometry_confidence = None
        if geometry_cpu is not None:
            (
                relative_prior,
                road_depth_prior,
                semantic_prior,
                _semantic_photometric_mask,
                geometry_confidence,
            ) = resize_geometry_priors(
                geometry_cpu[0],
                geometry_cpu[1],
                geometry_cpu[2],
                height,
                width,
                device,
            )
            if certified_sky_evidence_descriptor is not None:
                certified_sky_prior = resize_certified_sky_evidence(
                    dataset.load_certified_sky_evidence(index),
                    height,
                    width,
                    device,
                )
            confidence = fuse_semantic_photometric_confidence(
                confidence,
                semantic_prior,
                rigid_static_confidence_floor=semantic_rigid_static_confidence_floor,
                vegetation_confidence_floor=semantic_vegetation_confidence_floor,
                water_confidence_floor=semantic_water_confidence_floor,
                hard_exclusion=video_capture_bottom_exclusion_mask(
                    dataset.records[index].name,
                    height,
                    width,
                    device,
                ),
            )
        active_degree = min(step // 1000, sh_degree)
        try:
            raster_background, _ = directional_raster_background(
                directional_environment,
                camera,
                calibration,
                width,
                height,
                background_color,
            )
            appearance_render_mode = (
                "RGB"
                if dual_opacity_enabled
                else (
                    "RGB+ED"
                    if needs_geometry_depth or needs_surfel_aux
                    else "RGB"
                )
            )
            rendered_depth, appearance_alpha, information = rasterize(
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
                render_mode=appearance_render_mode,
                backgrounds=raster_background,
                surfel_ablation=surfel_ablation,
            )
            rendered = rendered_depth[..., :3]
            expected_depth = (
                rendered_depth[..., 3:4]
                if needs_geometry_depth and not dual_opacity_enabled
                else None
            )
            alpha = appearance_alpha
            geometry_information = information
            geometry_color_render = None
            if dual_opacity_enabled and needs_geometry_render:
                # Render geometry evidence through the base opacity.  RGB and
                # the densification gradient continue to use the appearance
                # product above, preventing road/sign detail from being
                # sacrificed to a geometry-only objective.
                geometry_render_mode = (
                    "RGB+ED"
                    if dual_opacity_geometry_rgb_weight > 0.0
                    else ("ED" if needs_geometry_depth or needs_surfel_aux else "RGB")
                )
                geometry_depth, alpha, geometry_information = rasterize(
                    parameters,
                    camera,
                    calibration,
                    width,
                    height,
                    active_degree,
                    packed,
                    False,
                    rasterization_mode,
                    eps2d,
                    render_mode=geometry_render_mode,
                    colors_override=(
                        torch.cat(
                            [parameters["sh0"], parameters["shN"]], dim=1
                        ).detach()
                        if dual_opacity_geometry_rgb_weight > 0.0
                        else None
                    ),
                    backgrounds=(
                        raster_background
                        if dual_opacity_geometry_rgb_weight > 0.0
                        else None
                    ),
                    surfel_ablation=surfel_ablation,
                    geometry_opacity=True,
                )
                if needs_geometry_depth:
                    expected_depth = (
                        geometry_depth[..., 3:4]
                        if geometry_render_mode == "RGB+ED"
                        else geometry_depth[..., :1]
                    )
                if dual_opacity_geometry_rgb_weight > 0.0:
                    geometry_color_render = geometry_depth[..., :3]
            training_render = apply_appearance(rendered, appearance, index)
            strategy.step_pre_backward(
                params=parameters,
                optimizers=optimizers,
                state=strategy_state,
                step=step,
                info=information,
            )
            confidence_sum = confidence.sum().clamp_min(1e-6)
            l1 = (
                (training_render - pixels).abs() * confidence
            ).sum() / (confidence_sum * training_render.shape[-1])
            ssim_loss = 1.0 - ssim(
                training_render.permute(0, 3, 1, 2),
                pixels.permute(0, 3, 1, 2),
                confidence.permute(0, 3, 1, 2),
            )
            loss = 0.8 * l1 + 0.2 * ssim_loss
            recent_dual_opacity_geometry_rgb_loss = 0.0
            if geometry_color_render is not None:
                geometry_training_render = apply_appearance(
                    geometry_color_render, appearance, index
                )
                geometry_l1 = (
                    (geometry_training_render - pixels).abs() * confidence
                ).sum() / (confidence_sum * geometry_training_render.shape[-1])
                geometry_ssim_loss = 1.0 - ssim(
                    geometry_training_render.permute(0, 3, 1, 2),
                    pixels.permute(0, 3, 1, 2),
                    confidence.permute(0, 3, 1, 2),
                )
                geometry_rgb_loss = 0.8 * geometry_l1 + 0.2 * geometry_ssim_loss
                loss = loss + dual_opacity_geometry_rgb_weight * geometry_rgb_loss
                recent_dual_opacity_geometry_rgb_loss = float(
                    geometry_rgb_loss.detach().item()
                )
            recent_sparse_depth_loss = 0.0
            recent_semantic_sky_opacity_loss = 0.0
            recent_contributor_sky_cleanup_loss = 0.0
            recent_surfel_depth_distortion_loss = 0.0
            recent_surfel_normal_consistency_loss = 0.0
            if (
                surfel_ablation is not None
                and surfel_depth_distortion_weight > 0.0
                and geometry_information.get("surfelDistortion") is not None
            ):
                depth_distortion_loss = geometry_information[
                    "surfelDistortion"
                ].mean()
                loss = loss + surfel_depth_distortion_weight * (
                    depth_distortion_loss
                )
                surfel_depth_distortion_steps += 1
                recent_surfel_depth_distortion_loss = float(
                    depth_distortion_loss.detach().item()
                )
            if (
                surfel_ablation is not None
                and surfel_normal_consistency_weight > 0.0
                and step >= surfel_normal_consistency_start
                and geometry_information.get("surfelNormal") is not None
                and geometry_information.get("surfelDepthNormal") is not None
            ):
                normal_mask = alpha[..., 0].detach() > 0.5
                if bool(normal_mask.any()):
                    cosine = (
                        geometry_information["surfelNormal"]
                        * geometry_information["surfelDepthNormal"]
                    ).sum(dim=-1)
                    normal_consistency_loss = torch.clamp_min(
                        1.0 - cosine[normal_mask], 0.0
                    ).mean()
                    loss = loss + surfel_normal_consistency_weight * (
                        normal_consistency_loss
                    )
                    surfel_normal_consistency_steps += 1
                    recent_surfel_normal_consistency_loss = float(
                        normal_consistency_loss.detach().item()
                    )
            if (
                observed_detail_weight > 0.0
                and semantic_prior is not None
                and step >= observed_detail_start
                and step % observed_detail_every == 0
            ):
                detail_loss = observed_detail_gradient_loss(
                    training_render,
                    pixels,
                    confidence,
                    semantic_prior,
                )
                loss = loss + observed_detail_weight * detail_loss
                observed_detail_steps += 1
                recent_observed_detail_loss = float(detail_loss.detach().item())
                recent_observed_detail_step = step
            if sparse_depth_weight > 0.0 and expected_depth is not None:
                sparse_loss, supported_sparse_depths = sparse_depth_consistency_loss(
                    expected_depth,
                    alpha,
                    dataset.records[index],
                    active_resolution_factor,
                )
                loss = loss + sparse_depth_weight * sparse_loss
                sparse_depth_samples += supported_sparse_depths
                recent_sparse_depth_loss = float(sparse_loss.detach().item())
            if (
                cross_view_depth_weight > 0.0
                and expected_depth is not None
                and step >= cross_view_depth_start
                and step % cross_view_depth_every == 0
                and index in dataset.cross_view_pairs
            ):
                target_index = dataset.cross_view_pairs[index]
                target_record = dataset.records[target_index]
                target_camera = torch.from_numpy(
                    target_record.camera_to_world
                ).to(device=device, dtype=torch.float32).unsqueeze(0)
                target_calibration = torch.from_numpy(
                    target_record.calibration
                ).to(device=device, dtype=torch.float32).unsqueeze(0)
                target_width = max(
                    1, round(target_record.width / active_resolution_factor)
                )
                target_height = max(
                    1, round(target_record.height / active_resolution_factor)
                )
                if active_resolution_factor > 1:
                    target_calibration = target_calibration.clone()
                    target_calibration[:, 0, :] *= (
                        target_width / target_record.width
                    )
                    target_calibration[:, 1, :] *= (
                        target_height / target_record.height
                    )
                target_geometry_depth, target_geometry_alpha, _ = rasterize(
                    parameters,
                    target_camera,
                    target_calibration,
                    target_width,
                    target_height,
                    active_degree,
                    packed,
                    False,
                    rasterization_mode,
                    eps2d,
                    render_mode="ED",
                    surfel_ablation=surfel_ablation,
                    geometry_opacity=(
                        cross_view_depth_mode == CROSS_VIEW_DENSE_MODE
                    ),
                )
                if cross_view_depth_mode == CROSS_VIEW_SPARSE_TRACK_MODE:
                    pair_samples = dataset.cross_view_sparse_tracks.get(index)
                    if pair_samples is None:
                        cross_view_loss = expected_depth.sum() * 0.0
                        cross_view_samples = 0
                    else:
                        (
                            cross_view_loss,
                            cross_view_samples,
                            _,
                        ) = sparse_track_pair_camera_z_loss(
                            expected_depth,
                            alpha,
                            target_geometry_depth[..., :1],
                            target_geometry_alpha,
                            pair_samples,
                            active_resolution_factor,
                            active_resolution_factor,
                            minimum_valid_tracks=(
                                cross_view_minimum_valid_tracks
                            ),
                        )
                else:
                    cross_view_loss, cross_view_samples = (
                        cross_view_depth_consistency_loss(
                            expected_depth,
                            alpha,
                            camera,
                            calibration,
                            target_geometry_depth[..., :1],
                            target_geometry_alpha,
                            target_camera,
                            target_calibration,
                            confidence,
                        )
                    )
                loss = loss + cross_view_depth_weight * cross_view_loss
                if cross_view_samples > 0:
                    cross_view_depth_steps += 1
                    cross_view_depth_samples += cross_view_samples
                    recent_cross_view_depth_loss = float(
                        cross_view_loss.detach().item()
                    )
            if (
                (
                    depth_layer_variance_weight > 0.0
                    or driving_surface_variance_weight > 0.0
                )
                and expected_depth is not None
                and step >= depth_layer_variance_start
                and step % depth_layer_variance_every == 0
            ):
                view = torch.linalg.inv(camera)
                camera_z = (
                    parameters["means"] @ view[0, :3, :3].transpose(0, 1)
                    + view[0, :3, 3]
                )[:, 2]
                second_moment, _, _ = rasterize(
                    parameters,
                    camera,
                    calibration,
                    width,
                    height,
                    None,
                    packed,
                    False,
                    rasterization_mode,
                    eps2d,
                    colors_override=camera_z.square().unsqueeze(1),
                    surfel_ablation=surfel_ablation,
                    geometry_opacity=dual_opacity_enabled,
                )
                variance_loss = depth_layer_variance_loss(
                    expected_depth, second_moment, alpha
                )
                if depth_layer_variance_weight > 0.0:
                    loss = loss + depth_layer_variance_weight * variance_loss
                if (
                    driving_surface_variance_weight > 0.0
                    and semantic_prior is not None
                    and geometry_confidence is not None
                ):
                    driving_variance_loss = driving_surface_depth_variance_loss(
                        expected_depth,
                        second_moment,
                        alpha,
                        semantic_prior,
                        confidence * geometry_confidence,
                    )
                    loss = (
                        loss
                        + driving_surface_variance_weight * driving_variance_loss
                    )
                    recent_driving_surface_variance_loss = float(
                        driving_variance_loss.detach().item()
                    )
                depth_layer_variance_steps += 1
                recent_depth_layer_variance_loss = float(
                    variance_loss.detach().item()
                )
                recent_depth_layer_variance_step = step
            if (
                expected_depth is not None
                and semantic_prior is not None
                and geometry_confidence is not None
                and step >= surface_alignment_start
                and step % surface_alignment_every == 0
                and (
                    surface_alignment_weight > 0.0
                    or road_planarity_weight > 0.0
                )
            ):
                from gsplat.utils import depth_to_normal, normalized_quat_to_rotmat

                gaussian_scales = torch.exp(parameters["scales"])
                shortest_axis = gaussian_scales.argmin(dim=-1)
                rotations = normalized_quat_to_rotmat(parameters["quats"])
                gaussian_normals = rotations.gather(
                    2,
                    shortest_axis[:, None, None].expand(-1, 3, 1),
                ).squeeze(2)
                camera_position = camera[0, :3, 3]
                facing = (
                    (camera_position - parameters["means"]) * gaussian_normals
                ).sum(dim=-1)
                gaussian_normals = gaussian_normals * torch.where(
                    facing >= 0.0,
                    torch.ones_like(facing),
                    -torch.ones_like(facing),
                ).detach()[:, None]
                thickness_ratio = (
                    gaussian_scales.min(dim=-1).values
                    / gaussian_scales.max(dim=-1).values.clamp_min(1e-6)
                )
                surface_features = torch.cat(
                    [gaussian_normals, thickness_ratio[:, None]], dim=-1
                )
                rendered_features, feature_alpha, _ = rasterize(
                    parameters,
                    camera,
                    calibration,
                    width,
                    height,
                    None,
                    packed,
                    False,
                    rasterization_mode,
                    eps2d,
                    colors_override=surface_features,
                    surfel_ablation=surfel_ablation,
                    geometry_opacity=dual_opacity_enabled,
                )
                depth_normals = depth_to_normal(
                    expected_depth, camera, calibration, z_depth=True
                )
                (
                    alignment_loss,
                    planarity_loss,
                    alignment_samples,
                    planarity_samples,
                ) = driving_surface_alignment_loss(
                    rendered_features,
                    depth_normals,
                    feature_alpha,
                    semantic_prior,
                    confidence * geometry_confidence,
                )
                loss = (
                    loss
                    + surface_alignment_weight * alignment_loss
                    + road_planarity_weight * planarity_loss
                )
                surface_alignment_steps += 1
                surface_alignment_samples += alignment_samples
                road_planarity_samples += planarity_samples
                recent_surface_alignment_loss = float(
                    alignment_loss.detach().item()
                )
                recent_road_planarity_loss = float(planarity_loss.detach().item())
            if (
                expected_depth is not None
                and relative_prior is not None
                and road_depth_prior is not None
                and semantic_prior is not None
                and step >= dense_geometry_start
                and step % dense_geometry_every == 0
                and (
                    dense_relative_depth_weight > 0.0
                    or road_surface_depth_weight > 0.0
                )
            ):
                (
                    dense_loss,
                    road_loss,
                    dense_samples,
                    road_samples,
                ) = dense_geometry_prior_loss(
                    expected_depth,
                    alpha,
                    relative_prior,
                    road_depth_prior,
                    semantic_prior,
                    confidence * geometry_confidence,
                )
                loss = (
                    loss
                    + dense_relative_depth_weight * dense_loss
                    + road_surface_depth_weight * road_loss
                )
                dense_geometry_steps += 1
                dense_relative_depth_samples += dense_samples
                road_surface_depth_samples += road_samples
                recent_dense_relative_depth_loss = float(
                    dense_loss.detach().item()
                )
                recent_road_surface_depth_loss = float(
                    road_loss.detach().item()
                )
                recent_dense_geometry_step = step
            if (
                semantic_sky_opacity_weight > 0.0
                and semantic_prior is not None
            ):
                # Diagnostic offender frames carry a strengthened observed-sky
                # alpha objective; the non-sky veto semantics of the loss are
                # untouched, only its weight scales for the listed frames.
                sky_weight_for_frame = semantic_sky_opacity_weight * (
                    oversampled_frame_multipliers.get(index, 1)
                    if oversampled_frame_multipliers is not None
                    else 1
                )
                sky_opacity_loss, sky_opacity_samples = semantic_sky_opacity_loss(
                    alpha,
                    semantic_prior,
                    evidence=certified_sky_prior,
                    tail_threshold=semantic_sky_tail_threshold,
                    tail_weight=semantic_sky_tail_weight,
                    tail_bce_epsilon=semantic_sky_tail_bce_epsilon,
                    tail_erosion_radius=semantic_sky_tail_erosion_radius,
                    l1_scope=(
                        "semantic"
                        if configured_semantic_sky_method
                        == SEMANTIC_SKY_HYBRID_DIAGNOSTIC_METHOD
                        else "evidence-restricted"
                    ),
                )
                loss = loss + sky_weight_for_frame * sky_opacity_loss
                if sky_opacity_samples > 0:
                    semantic_sky_opacity_steps += 1
                    semantic_sky_opacity_samples += sky_opacity_samples
                    recent_semantic_sky_opacity_loss = float(
                        sky_opacity_loss.detach().item()
                    )
            if contributor_sky_cleanup_mask is not None:
                cleanup_loss = contributor_sky_cleanup_loss(
                    parameters["opacities"], contributor_sky_cleanup_mask
                )
                loss = loss + contributor_sky_cleanup_weight * cleanup_loss
                contributor_sky_cleanup_steps += 1
                recent_contributor_sky_cleanup_loss = float(
                    cleanup_loss.detach().item()
                )
            if appearance is not None and appearance_regularization_weight > 0.0:
                loss = loss + appearance_regularization_weight * appearance_regularization(
                    appearance,
                    index,
                )
            if scale_regularization > 0:
                scales = torch.exp(parameters["scales"])
                if surfel_ablation is not None:
                    # Anisotropy across a pinned near-zero surfel normal axis
                    # is meaningless, so regularize the in-plane pair only.
                    scales = scales[..., :2]
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
                and len(parameters["means"]) >= target_gaussians
            ):
                # One DefaultStrategy split/duplicate pass can at most double
                # the active set.  Stopping at half of the hard allocation
                # ceiling makes the allocation cap deterministic before a large
                # temporary densification allocation is attempted.  Do not use
                # refine_stop_iter here: gsplat short-circuits pruning there as
                # well, which previously allowed giant screen-space splats to
                # survive the rest of the geometry phase.
                freeze_density_growth_at_target(strategy)
                densification_limited = True
                density_growth_frozen = True
                densification_limit_reason = "gaussian-target-reached"
                atomic_json(
                    recovery_policy_path,
                    {
                        "schema": "servo.gsplat-recovery-policy/v2",
                        "configurationHash": config["configurationHash"],
                        "trainingInputHash": config["trainingInputHash"],
                        "disableDensification": False,
                        "freezeGrowth": True,
                        "growthCapPolicy": DENSITY_GROWTH_CAP_POLICY,
                        "reason": densification_limit_reason,
                        "step": step,
                        "gaussians": len(parameters["means"]),
                        "targetGaussians": target_gaussians,
                        "hardMaximumGaussians": max_gaussians,
                    },
                )
                emit(
                    "densification_limited",
                    step=step,
                    reason=densification_limit_reason,
                    gaussians=len(parameters["means"]),
                    targetGaussians=target_gaussians,
                    hardMaximumGaussians=max_gaussians,
                    growthFrozen=True,
                    pruningContinuesUntil=strategy.refine_stop_iter,
                )
            strategy.step_post_backward(
                params=parameters,
                optimizers=optimizers,
                state=strategy_state,
                step=step,
                info=information,
                packed=False if surfel_ablation is not None else packed,
            )
            # gsplat 1.5.3 uses a bitwise operator in this condition, so its
            # intended periodic opacity reset never runs. Keep the pinned
            # release and apply the corrected upstream semantics explicitly.
            if should_reset_opacity(
                step, strategy.reset_every, strategy.refine_stop_iter
            ):
                if corrected_dual_opacity:
                    reset_dual_opacity_preserving_product(
                        parameters,
                        optimizers,
                        strategy.prune_opa * 2.0,
                    )
                    emit("opacity_reset", step=step, productPreserved=True)
                else:
                    reset_opa(
                        params=parameters,
                        optimizers=optimizers,
                        state=strategy_state,
                        value=strategy.prune_opa * 2.0,
                    )
                    emit("opacity_reset", step=step)
            clamp_parameters(
                parameters, pin_surfel_z=surfel_ablation is not None
            )
            clamp_appearance(appearance)
            reserved_gib = torch.cuda.memory_reserved() / 1024**3
            if not densification_limited and reserved_gib >= max_vram_gib * 0.80:
                strategy.refine_stop_iter = min(strategy.refine_stop_iter, step + 1)
                densification_limited = True
                densification_limit_reason = "memory-warning-threshold"
                atomic_json(
                    recovery_policy_path,
                    {
                        "schema": "servo.gsplat-recovery-policy/v2",
                        "configurationHash": config["configurationHash"],
                        "trainingInputHash": config["trainingInputHash"],
                        "disableDensification": True,
                        "freezeGrowth": False,
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
                    "schema": "servo.gsplat-recovery-policy/v2",
                    "configurationHash": config["configurationHash"],
                    "trainingInputHash": config["trainingInputHash"],
                    "disableDensification": True,
                    "freezeGrowth": False,
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
                phase="final-fit-all-frames" if final_fit else "heldout-training",
                loss=recent_loss,
                gaussians=len(parameters["means"]),
                resolutionFactor=active_resolution_factor,
                rasterizationMode=rasterization_mode,
                peakVramGiB=torch.cuda.max_memory_allocated() / 1024**3,
                peakReservedVramGiB=torch.cuda.max_memory_reserved() / 1024**3,
                maxVramGiB=max_vram_gib,
                elapsedSeconds=time.monotonic() - started,
                sparseDepthLoss=recent_sparse_depth_loss,
                sparseDepthSamples=sparse_depth_samples,
                crossViewDepthLoss=recent_cross_view_depth_loss,
                crossViewDepthSteps=cross_view_depth_steps,
                crossViewDepthSamples=cross_view_depth_samples,
                dualOpacityGeometryRgbLoss=(
                    recent_dual_opacity_geometry_rgb_loss
                ),
                depthLayerVarianceLoss=recent_depth_layer_variance_loss,
                depthLayerVarianceSteps=depth_layer_variance_steps,
                drivingSurfaceVarianceLoss=recent_driving_surface_variance_loss,
                surfaceAlignmentLoss=recent_surface_alignment_loss,
                roadPlanarityLoss=recent_road_planarity_loss,
                surfaceAlignmentSteps=surface_alignment_steps,
                denseRelativeDepthLoss=recent_dense_relative_depth_loss,
                roadSurfaceDepthLoss=recent_road_surface_depth_loss,
                denseGeometrySteps=dense_geometry_steps,
                denseRelativeDepthSamples=dense_relative_depth_samples,
                roadSurfaceDepthSamples=road_surface_depth_samples,
                observedDetailLoss=recent_observed_detail_loss,
                observedDetailSteps=observed_detail_steps,
                semanticSkyOpacityLoss=recent_semantic_sky_opacity_loss,
                semanticSkyOpacitySteps=semantic_sky_opacity_steps,
                semanticSkyOpacitySamples=semantic_sky_opacity_samples,
                contributorSkyCleanupSteps=contributor_sky_cleanup_steps,
                contributorSkyCleanupLoss=recent_contributor_sky_cleanup_loss,
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
    if len(final_fit_seen) != len(all_indices):
        raise TrainingError(
            "The deterministic final-fit phase did not visit every selected "
            "appearance camera."
        )
    validate_parameters(parameters)
    if not heldout_metrics_path.is_file():
        raise TrainingError("The pre-fit held-out evaluation was not committed.")
    with heldout_metrics_path.open("r", encoding="utf-8") as stream:
        heldout_snapshot = require_heldout_snapshot(json.load(stream))
    validation = {
        field: heldout_snapshot[field]
        for field in (
            "validationImages",
            "psnrMean",
            "psnrMedian",
            "ssimMean",
            "ssimMedian",
            "depthAmbiguityRelativeStdP50",
            "depthAmbiguityRelativeStdP95",
            "depthAmbiguityFractionAbove10Percent",
            "depthAmbiguityMeaning",
        )
    }
    appearance_summary = appearance_metrics(appearance, all_indices)
    del optimizers
    del scheduler
    del strategy_state
    if appearance_optimizer is not None:
        del appearance_optimizer
    if appearance_scheduler is not None:
        del appearance_scheduler
    gc.collect()
    torch.cuda.empty_cache()
    parameters, cleanup = cleanup_parameters(
        parameters, dataset.normalization, surfel=surfel_ablation is not None
    )
    validate_parameters(parameters)
    final_artifact_validation = evaluate(
        parameters,
        dataset,
        device,
        sh_degree,
        packed,
        rasterization_mode,
        eps2d,
        output / "final-validation",
        all_indices,
        cancel_path=cancel_path,
        phase="final-artifact-validation",
        background_color=background_color,
        directional_environment=directional_environment,
        surfel_ablation=surfel_ablation,
    )
    semantic_geometry = final_artifact_validation.get("semanticGeometry")
    if not isinstance(semantic_geometry, dict):
        raise TrainingError("The final artifact has no semantic geometry audit.")

    def required_semantic_metric(name: str) -> float:
        value = semantic_geometry.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise TrainingError(f"The final artifact semantic metric {name} is missing.")
        return float(value)

    if (
        float(final_artifact_validation["psnrMean"]) < minimum_final_artifact_psnr
        or float(final_artifact_validation["ssimMean"])
        < minimum_final_artifact_ssim
        or float(final_artifact_validation["depthAmbiguityRelativeStdP50"])
        > maximum_depth_ambiguity
        or float(final_artifact_validation["depthAmbiguityRelativeStdP95"])
        > maximum_depth_ambiguity_p95
        or float(
            final_artifact_validation["depthAmbiguityFractionAbove10Percent"]
        )
        > maximum_depth_ambiguity_fraction
        or float(final_artifact_validation["psnrMean"])
        < float(heldout_snapshot["psnrMean"]) - maximum_final_psnr_regression
        or float(final_artifact_validation["ssimMean"])
        < float(heldout_snapshot["ssimMean"]) - maximum_final_ssim_regression
        or required_semantic_metric("skyAlphaP95") > maximum_sky_alpha_p95
        or required_semantic_metric("skyAlphaAboveTenPercentFraction")
        > maximum_sky_alpha_fraction
        or required_semantic_metric("maximumViewSkyAlphaP95")
        > maximum_view_sky_alpha_p95
        or required_semantic_metric("roadSupportFraction")
        < minimum_road_surface_support
        or required_semantic_metric("roadRelativeDepthP50")
        > maximum_road_relative_depth_p50
        or required_semantic_metric("roadRelativeDepthP95")
        > maximum_road_relative_depth_p95
        or required_semantic_metric("roadDepthAmbiguityP50")
        > maximum_road_ambiguity_p50
        or required_semantic_metric("roadDepthAmbiguityP95")
        > maximum_road_ambiguity_p95
    ):
        raise TrainingError(
            "The cleaned final artifact failed its all-camera appearance or geometry gate."
        )
    export_cameras(dataset, output / "cameras.json")
    export_appearance(dataset, appearance, output / "appearance.json")
    export_world(
        parameters,
        output / "world.ply",
        rasterization_mode,
        eps2d,
        (
            SURFEL_ABLATION_REPRESENTATION
            if surfel_ablation is not None
            else REPRESENTATION_TYPE
        ),
    )
    world_sha256 = sha256_file(output / "world.ply")
    import importlib.metadata

    if sum(main_fit_visits) != heldout_evaluation_step:
        raise TrainingError("The main sampling receipt does not cover every pre-fit step.")
    train_visit_counts = [main_fit_visits[index] for index in dataset.train_indices]
    if not train_visit_counts or min(train_visit_counts) <= 0:
        raise TrainingError("The main sampling receipt omitted a trained camera.")
    endpoint_visit_counts = [
        main_fit_visits[index]
        for index in sorted(dataset.training_sampling_plan.endpoint_indices)
    ]
    main_sampling_receipt = {
        "policy": main_sampling_policy,
        "endpointWindow": endpoint_sampling_window,
        "endpointMultiplier": endpoint_sampling_multiplier,
        "maximumSparseAnchorMultiplier": maximum_sparse_anchor_multiplier,
        "medianSparseAnchors": dataset.training_sampling_plan.median_sparse_anchors,
        "epochSlots": len(dataset.training_sampling_plan.epoch_slots),
        "epochs": heldout_evaluation_step
        / len(dataset.training_sampling_plan.epoch_slots),
        "totalVisits": sum(main_fit_visits),
        "minimumVisits": min(train_visit_counts),
        "maximumVisits": max(train_visit_counts),
        "endpointImageCount": len(endpoint_visit_counts),
        "minimumEndpointVisits": min(endpoint_visit_counts)
        if endpoint_visit_counts
        else None,
        "maximumEndpointVisits": max(endpoint_visit_counts)
        if endpoint_visit_counts
        else None,
        "perImage": [
            {
                "image": dataset.records[index].name,
                "visits": main_fit_visits[index],
                "weight": dataset.training_sampling_plan.weights[index],
                "sparseAnchors": dataset.training_sampling_plan.sparse_anchor_counts[
                    index
                ],
                "endpoint": index in dataset.training_sampling_plan.endpoint_indices,
            }
            for index in dataset.train_indices
        ],
    }

    metrics = {
        "schema": METRICS_SCHEMA,
        "trainerVersion": TRAINER_VERSION,
        "pipelineRevision": config.get("pipelineRevision"),
        "jobId": config.get("jobId"),
        "profile": config.get("profile"),
        "seed": seed,
        "configurationHash": config["configurationHash"],
        "experimentConfigurationHash": config.get(
            "experimentConfigurationHash"
        ),
        "pipelineCodeHash": config["pipelineCodeHash"],
        "trainingInputHash": config["trainingInputHash"],
        "representationType": (
            SURFEL_ABLATION_REPRESENTATION
            if surfel_ablation is not None
            else REPRESENTATION_TYPE
        ),
        "rasterizationMode": rasterization_mode,
        "antialiasedRasterizationApplied": surfel_ablation is None,
        "eps2d": eps2d,
        "densificationStrategy": (
            "default-2dgs-gradient"
            if surfel_ablation is not None
            else COVERAGE_DENSIFICATION_METHOD
            if coverage_densification is not None
            else ("default-absgrad" if absgrad else "default")
        ),
        "absgrad": absgrad,
        "growGrad2d": grow_grad2d,
        "screenSpaceRefinement": {
            "policy": screen_space_refinement_policy,
            "densityRefinementPolicy": density_refinement_policy,
            "growScale2d": grow_scale2d,
            "pruneScale2d": prune_scale2d,
            "stopIter": refine_scale2d_stop_iter,
            "startIter": refine_start_iter,
            "refineEvery": refine_every,
            "actualStopIter": int(strategy.refine_stop_iter),
            "mainFitStopIter": main_fit_stop_iter,
            "growthFrozenAtTarget": density_growth_frozen,
            "growthCapPolicy": DENSITY_GROWTH_CAP_POLICY,
            "radiusNormalization": "max-image-dimension",
        },
        "mainSampling": main_sampling_receipt,
        "frameOversampling": frame_oversampling_receipt,
        "coverageAwareDensification": coverage_densification,
        "surfelAblation": (
            {
                **surfel_ablation,
                "depthDistortionSteps": surfel_depth_distortion_steps,
                "recentDepthDistortionLoss": recent_surfel_depth_distortion_loss,
                "normalConsistencySteps": surfel_normal_consistency_steps,
                "recentNormalConsistencyLoss": (
                    recent_surfel_normal_consistency_loss
                ),
                "densificationGradientKey": "gradient_2dgs",
                "absgradDensification": False,
                "packedForcedFalse": True,
                "note": (
                    "Diagnostic 2DGS surfel A/B; rasterization_2dgs does not "
                    "apply the antialiased mode and render/export parity with "
                    "the Vulkan 3DGS renderer is unverified."
                ),
            }
            if surfel_ablation is not None
            else None
        ),
        "targetGaussians": target_gaussians,
        "maxGaussians": max_gaussians,
        "resolutionSchedule": {
            "coarseFactor": coarse_factor,
            "coarseSteps": coarse_steps,
            "fullResolutionSteps": max_steps - coarse_steps,
        },
        "appearance": appearance_summary,
        "dualOpacity": {
            "enabled": dual_opacity_enabled,
            "method": (
                (
                    "stablegs-inspired-corrected-lifecycle-v2"
                    if corrected_dual_opacity
                    else "stablegs-inspired-geometry-opacity-times-appearance-gate-v1"
                )
                if dual_opacity_enabled
                else "disabled"
            ),
            "initialization": dual_opacity_initialization,
            "geometryRgbWeight": dual_opacity_geometry_rgb_weight,
            "recentGeometryRgbLoss": recent_dual_opacity_geometry_rgb_loss,
            "prunePolicy": dual_opacity_prune_policy,
            "resetPolicy": dual_opacity_reset_policy,
            "geometryObjectivesUseBaseOpacity": dual_opacity_enabled,
            "rgbAndExportUseProductOpacity": dual_opacity_enabled,
            "opacityResetDisabled": (
                dual_opacity_enabled and not corrected_dual_opacity
            ),
        },
        "geometryRegularization": {
            "staticConfidenceMasks": dataset.static_confidence_masks,
            "staticConfidenceMethod": config.get("staticConfidenceMethod"),
            "semanticPhotometricMask": config.get("semanticPhotometricMask") is True,
            "semanticPhotometricMaskMethod": semantic_photometric_method,
            "semanticPhotometricSource": (
                "pinned-oneformer-ade20k-observed-pixels-mapped-to-servo-taxonomy"
            ),
            "semanticRigidStaticLabels": [*range(1, 16), 24, 25],
            "semanticExcludedLabels": [0, 17, 18, 19, 20, 21, 22],
            "semanticRigidStaticConfidenceFloor": (
                semantic_rigid_static_confidence_floor
            ),
            "semanticVegetationConfidenceFloor": (
                semantic_vegetation_confidence_floor
            ),
            "semanticWaterConfidenceFloor": semantic_water_confidence_floor,
            "geometryPriors": dataset.geometry_priors,
            "geometryPriorsSchema": config.get("geometryPriorsSchema"),
            "geometryPriorsMetricsSha256": config.get(
                "geometryPriorsMetricsSha256"
            ),
            "sparseDepthSource": "filtered-colmap-track-observations",
            "sparseDepthWeight": sparse_depth_weight,
            "sparseDepthSamples": sparse_depth_samples,
            "recentSparseDepthLoss": recent_sparse_depth_loss,
            "crossViewDepthConsistencyWeight": cross_view_depth_weight,
            "crossViewDepthMode": cross_view_depth_mode,
            "crossViewDepthConsistencyEvery": cross_view_depth_every,
            "crossViewDepthConsistencyStart": cross_view_depth_start,
            "crossViewMinimumValidTracksPerStep": (
                cross_view_minimum_valid_tracks
            ),
            "crossViewDepthPairPlan": dataset.cross_view_pair_receipt,
            "crossViewDepthSteps": cross_view_depth_steps,
            "crossViewDepthSamples": cross_view_depth_samples,
            "recentCrossViewDepthLoss": recent_cross_view_depth_loss,
            "depthLayerVarianceWeight": depth_layer_variance_weight,
            "depthLayerVarianceEvery": depth_layer_variance_every,
            "depthLayerVarianceStart": depth_layer_variance_start,
            "depthLayerVarianceSteps": depth_layer_variance_steps,
            "recentDepthLayerVarianceLoss": recent_depth_layer_variance_loss,
            "recentDepthLayerVarianceStep": recent_depth_layer_variance_step,
            "drivingSurfaceVarianceWeight": driving_surface_variance_weight,
            "recentDrivingSurfaceVarianceLoss": recent_driving_surface_variance_loss,
            "surfaceAlignmentMethod": (
                "3dgs-shortest-axis-vs-rendered-depth-normal-road-only-v2"
            ),
            "surfaceAlignmentWeight": surface_alignment_weight,
            "roadPlanarityWeight": road_planarity_weight,
            "surfaceAlignmentEvery": surface_alignment_every,
            "surfaceAlignmentStart": surface_alignment_start,
            "surfaceAlignmentSteps": surface_alignment_steps,
            "surfaceAlignmentSamples": surface_alignment_samples,
            "roadPlanaritySamples": road_planarity_samples,
            "recentSurfaceAlignmentLoss": recent_surface_alignment_loss,
            "recentRoadPlanarityLoss": recent_road_planarity_loss,
            "denseRelativeDepthSource": "video-depth-anything-small-relative-inverse-depth",
            "denseRelativeDepthWeight": dense_relative_depth_weight,
            "roadSurfaceDepthSource": (
                "evidence-bounded-observed-cell-graph-with-piecewise-grade-bank-fallback-v1"
            ),
            "roadSurfaceDepthWeight": road_surface_depth_weight,
            "denseGeometryEvery": dense_geometry_every,
            "denseGeometryStart": dense_geometry_start,
            "denseGeometrySteps": dense_geometry_steps,
            "denseRelativeDepthSamples": dense_relative_depth_samples,
            "roadSurfaceDepthSamples": road_surface_depth_samples,
            "recentDenseRelativeDepthLoss": recent_dense_relative_depth_loss,
            "recentRoadSurfaceDepthLoss": recent_road_surface_depth_loss,
            "recentDenseGeometryStep": recent_dense_geometry_step,
            "observedDetailWeight": observed_detail_weight,
            "observedDetailEvery": observed_detail_every,
            "observedDetailStart": observed_detail_start,
            "observedDetailSteps": observed_detail_steps,
            "recentObservedDetailLoss": recent_observed_detail_loss,
            "recentObservedDetailStep": recent_observed_detail_step,
            "semanticSkyOpacitySource": (
                "oneformer-rotation-only-temporally-confirmed-sky-alpha-zero"
            ),
            "certifiedSkyEvidence": certified_sky_evidence_descriptor,
            "semanticSkyOpacityMethod": semantic_sky_opacity_method,
            "semanticSkyOpacityWeight": semantic_sky_opacity_weight,
            "semanticSkyOpacityTailThreshold": semantic_sky_tail_threshold,
            "semanticSkyOpacityTailWeight": semantic_sky_tail_weight,
            "semanticSkyOpacityTailBceEpsilon": semantic_sky_tail_bce_epsilon,
            "semanticSkyOpacityTailErosionMethod": semantic_sky_tail_erosion_method,
            "semanticSkyOpacityTailErosionRadius": semantic_sky_tail_erosion_radius,
            "semanticSkyOpacitySteps": semantic_sky_opacity_steps,
            "semanticSkyOpacitySamples": semantic_sky_opacity_samples,
            "recentSemanticSkyOpacityLoss": recent_semantic_sky_opacity_loss,
            "contributorSkyCleanup": {
                "enabled": contributor_sky_cleanup_enabled,
                "method": contributor_sky_cleanup_method,
                "startStep": contributor_sky_cleanup_start,
                "lossWeight": contributor_sky_cleanup_weight,
                "steps": contributor_sky_cleanup_steps,
                "recentLoss": recent_contributor_sky_cleanup_loss,
                "ledger": contributor_sky_cleanup_ledger,
            },
        },
        "environment": {
            "backgroundColorSrgb": [float(value) for value in background_values],
            "backgroundSource": config.get("backgroundSource"),
            "observedDirectionalEnvironment": (
                directional_environment.descriptor
                if directional_environment is not None
                else None
            ),
            "finiteSkyGeometryAllowed": False,
            "finiteSkyOpacityAudit": {
                key: final_artifact_validation["semanticGeometry"][key]
                for key in (
                    "skySamples",
                    "skyAlphaP95",
                    "skyAlphaAboveTenPercentFraction",
                    "maximumViewSkyAlphaP95",
                )
            },
        },
        "steps": max_steps,
        "heldoutEvaluationStep": heldout_evaluation_step,
        "finalFitSteps": final_fit_steps,
        "finalFitImages": len(all_indices),
        "finalFitUniqueImages": len(final_fit_seen),
        "finalFitEpochs": final_fit_steps / len(all_indices),
        "worldSha256": world_sha256,
        "finalArtifactValidation": final_artifact_validation,
        "gaussians": len(parameters["means"]),
        "trainingImages": len(dataset.train_indices),
        "validationImages": len(dataset.validation_indices),
        "registeredPoseImages": len(dataset),
        "appearanceFrameSelection": appearance_frame_selection_receipt,
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
        "densityGrowthFrozen": density_growth_frozen,
        "densityGrowthCapPolicy": DENSITY_GROWTH_CAP_POLICY,
        "elapsedSeconds": elapsed_before + time.monotonic() - started,
        "normalization": dataset.normalization,
        "initialization": dataset.initialization_stats,
        "cleanup": cleanup,
        "validationPolicy": dataset.validation_policy,
        "runtime": {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gsplat": importlib.metadata.version("gsplat"),
            "pycolmap": (
                importlib.metadata.version("pycolmap")
                if dataset.colmap_runtime == "pycolmap"
                else None
            ),
            "colmapReader": dataset.colmap_runtime,
            "device": torch.cuda.get_device_name(0),
            "nativeExtension": gsplat_runtime_receipt,
        },
        **validation,
    }
    atomic_json(output / "train-metrics.json", metrics)
    emit("training_completed", **metrics)
    return 0


def kernel_check() -> int:
    import numpy as np
    import torch

    from servo_gsplat_runtime import prepare_gsplat_runtime

    gsplat_runtime_receipt = prepare_gsplat_runtime()
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
    rendered_depth, depth_alpha, _ = rasterization(
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
        rasterize_mode="antialiased",
        eps2d=0.3,
        render_mode="RGB+ED",
    )
    moment, moment_alpha, _ = rasterization(
        means,
        quaternions,
        scales,
        opacities,
        means.detach()[:, 2:3].square(),
        views,
        calibrations,
        64,
        64,
        packed=True,
        rasterize_mode="antialiased",
        eps2d=0.3,
        render_mode="RGB",
        sh_degree=None,
    )
    background = torch.tensor([[0.15, 0.25, 0.35]], device=device)
    servo_rgb_depth, servo_depth_alpha, _ = rasterize(
        {
            "means": means,
            "quats": quaternions,
            "scales": torch.log(scales),
            "opacities": torch.logit(opacities),
        },
        torch.eye(4, device=device).unsqueeze(0),
        calibrations,
        64,
        64,
        None,
        True,
        False,
        "antialiased",
        0.3,
        render_mode="RGB+ED",
        colors_override=colors,
        backgrounds=background,
    )
    expected_servo_rgb = (
        rendered_depth[..., :3]
        + (1.0 - depth_alpha) * background[:, None, None, :]
    )
    depth_record = ImageRecord(
        name="kernel-check.png",
        path=Path("kernel-check.png"),
        camera_id=1,
        camera_model="PINHOLE",
        camera_to_world=np.eye(4, dtype=np.float32),
        calibration=np.eye(3, dtype=np.float32),
        width=64,
        height=64,
        sparse_pixels=np.asarray(
            [[31, 31], [32, 31], [33, 31], [31, 32], [32, 32], [33, 32], [31, 33], [32, 33]],
            dtype=np.float32,
        ),
        sparse_depths=np.full(8, 2.0, dtype=np.float32),
    )
    sparse_depth_loss, sparse_depth_samples = sparse_depth_consistency_loss(
        rendered_depth[..., 3:4], depth_alpha, depth_record, 1
    )
    layer_variance_loss = depth_layer_variance_loss(
        rendered_depth[..., 3:4], moment, depth_alpha
    )
    information["means2d"].retain_grad()
    loss = (
        rendered.sum()
        + alpha.sum()
        + 0.05 * sparse_depth_loss
        + 0.01 * layer_variance_loss
    )
    loss.backward()
    if (
        not bool(torch.isfinite(rendered).all())
        or rendered_depth.shape[-1] != 4
        or moment.shape[-1] != 1
        or not bool(torch.isfinite(rendered_depth).all())
        or not bool(torch.isfinite(depth_alpha).all())
        or not bool(torch.isfinite(moment).all())
        or not bool(torch.isfinite(moment_alpha).all())
        or servo_rgb_depth.shape[-1] != 4
        or not bool(torch.isfinite(servo_rgb_depth).all())
        or not torch.allclose(servo_depth_alpha, depth_alpha, atol=1e-6, rtol=1e-6)
        or not torch.allclose(
            servo_rgb_depth[..., :3], expected_servo_rgb, atol=1e-6, rtol=1e-6
        )
        or not torch.allclose(
            servo_rgb_depth[..., 3:], rendered_depth[..., 3:], atol=1e-6, rtol=1e-6
        )
        or not bool(torch.isfinite(sparse_depth_loss))
        or not bool(torch.isfinite(layer_variance_loss))
        or sparse_depth_samples != 8
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
        rgbDepthShape=list(rendered_depth.shape),
        momentShape=list(moment.shape),
        servoBackgroundRgbDepthShape=list(servo_rgb_depth.shape),
        sparseDepthSamples=sparse_depth_samples,
        sparseDepthLoss=float(sparse_depth_loss.detach().item()),
        depthLayerVarianceLoss=float(layer_variance_loss.detach().item()),
        nativeExtension=gsplat_runtime_receipt,
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
    except TrainingCancelled as error:
        emit("training_cancelled", message=str(error))
        return 130
    except TrainingError as error:
        emit("training_failed", message=str(error))
        return 2
    except Exception as error:
        emit("training_failed", message=str(error), details=traceback.format_exc())
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
