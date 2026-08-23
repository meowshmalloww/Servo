#!/usr/bin/env python3
"""Deterministic geometry evidence primitives for Servo reconstruction.

This module intentionally does not run a depth or segmentation model.  It
turns their outputs into auditable geometry evidence and fails closed when the
evidence is insufficient.  In particular:

* monocular depth is affine-aligned to sparse SfM samples, but is not called
  metric unless a separate metric scale anchor is recorded;
* semantic masks distinguish finite static geometry from sky, dynamics, and
  unknown pixels;
* road observations are fitted with a continuous piecewise-linear surface
  whose longitudinal elevation and cross-slope may vary, rather than forcing
  every road to be one plane;
* the safety gate only reports eligibility for further collision validation.
  It never certifies collision safety.

The clean-room implementation is informed by Video Depth Anything
(arXiv:2501.12375), DN-Splatter (arXiv:2403.17822), AutoSplat
(arXiv:2407.02598), FlexRoad (arXiv:2504.16103), Cityscapes, and ASAM
OpenLABEL.  No source code from those projects is copied here.
"""

from __future__ import annotations

import dataclasses
import math
from enum import Enum, IntEnum
from typing import Literal, Sequence

import numpy as np


GEOMETRY_SCHEMA = "servo.geometry-evidence/v1"
SEMANTIC_SCHEMA = "servo.semantic-mask/v1"


class GeometryInputError(ValueError):
    """Raised when geometry evidence is malformed or underconstrained."""


class SemanticLabel(IntEnum):
    """Servo's stable, model-independent safety semantics.

    Model-specific taxonomies must be mapped explicitly.  UNKNOWN is not
    background: it means there is no usable classification evidence.
    """

    UNKNOWN = 0
    ROAD = 1
    ROAD_MARKING = 2
    CURB = 3
    SIDEWALK = 4
    PARKING = 5
    TERRAIN = 6
    BUILDING = 7
    WALL = 8
    FENCE = 9
    GUARD_RAIL = 10
    POLE = 11
    TRAFFIC_SIGN_FRONT = 12
    TRAFFIC_SIGN_BACK = 13
    TRAFFIC_SIGN_FRAME = 14
    TRAFFIC_LIGHT = 15
    VEGETATION = 16
    SKY = 17
    VEHICLE = 18
    PERSON = 19
    RIDER = 20
    BICYCLE = 21
    MOTORCYCLE = 22
    WATER = 23
    OTHER_STATIC = 24
    FLOOR = 25


ROAD_LABELS = frozenset(
    {
        SemanticLabel.ROAD,
        SemanticLabel.ROAD_MARKING,
        SemanticLabel.PARKING,
    }
)
NAVIGABLE_SURFACE_LABELS = ROAD_LABELS | frozenset({SemanticLabel.FLOOR})
ROAD_BOUNDARY_LABELS = frozenset(
    {
        SemanticLabel.CURB,
        SemanticLabel.SIDEWALK,
        SemanticLabel.GUARD_RAIL,
    }
)
SIGN_LABELS = frozenset(
    {
        SemanticLabel.TRAFFIC_SIGN_FRONT,
        SemanticLabel.TRAFFIC_SIGN_BACK,
        SemanticLabel.TRAFFIC_SIGN_FRAME,
        SemanticLabel.TRAFFIC_LIGHT,
    }
)
DYNAMIC_LABELS = frozenset(
    {
        SemanticLabel.VEHICLE,
        SemanticLabel.PERSON,
        SemanticLabel.RIDER,
        SemanticLabel.BICYCLE,
        SemanticLabel.MOTORCYCLE,
    }
)
NON_FINITE_LABELS = frozenset({SemanticLabel.UNKNOWN, SemanticLabel.SKY})


def _as_float_array(value: object, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.size == 0:
        raise GeometryInputError(f"{name} must not be empty")
    return result


def _weighted_percentile(
    values: np.ndarray,
    weights: np.ndarray,
    percentile: float,
) -> float:
    if values.ndim != 1 or weights.ndim != 1 or values.shape != weights.shape:
        raise GeometryInputError("weighted percentile inputs must be matching vectors")
    if not 0.0 <= percentile <= 100.0:
        raise GeometryInputError("percentile must be between 0 and 100")
    positive = np.isfinite(values) & np.isfinite(weights) & (weights > 0.0)
    if not np.any(positive):
        raise GeometryInputError("weighted percentile has no positive finite weights")
    filtered_values = values[positive]
    filtered_weights = weights[positive]
    order = np.argsort(filtered_values, kind="stable")
    filtered_values = filtered_values[order]
    filtered_weights = filtered_weights[order]
    cumulative = np.cumsum(filtered_weights)
    target = percentile * 0.01 * cumulative[-1]
    index = int(np.searchsorted(cumulative, target, side="left"))
    return float(filtered_values[min(index, len(filtered_values) - 1)])


def _robust_sigma(residuals: np.ndarray, weights: np.ndarray) -> float:
    center = _weighted_percentile(residuals, weights, 50.0)
    mad = _weighted_percentile(np.abs(residuals - center), weights, 50.0)
    sigma = 1.4826 * mad
    if sigma > np.finfo(np.float64).eps:
        return float(sigma)
    denominator = float(np.sum(weights))
    if denominator <= 0.0:
        return 0.0
    return float(math.sqrt(np.sum(weights * residuals * residuals) / denominator))


def _solve_weighted_linear(
    design: np.ndarray,
    target: np.ndarray,
    weights: np.ndarray,
    regularizer: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    positive = np.isfinite(weights) & (weights > 0.0)
    if np.count_nonzero(positive) < design.shape[1]:
        raise GeometryInputError("weighted system has insufficient positive support")
    root_weight = np.sqrt(weights[positive])
    system = design[positive] * root_weight[:, None]
    values = target[positive] * root_weight
    if regularizer is not None and regularizer.size:
        system = np.vstack((system, regularizer))
        values = np.concatenate((values, np.zeros(regularizer.shape[0])))
    condition = float(np.linalg.cond(system))
    if not math.isfinite(condition) or condition > 1.0e12:
        raise GeometryInputError(
            f"geometry fit is numerically underconstrained (condition={condition:.3g})"
        )
    solution, _, rank, _ = np.linalg.lstsq(system, values, rcond=None)
    if rank < design.shape[1]:
        raise GeometryInputError("geometry fit does not have full rank")
    return solution, condition


@dataclasses.dataclass(frozen=True)
class DepthAlignmentResult:
    """Robust alignment from relative predictions into the SfM coordinate frame."""

    representation: Literal["depth", "inverse-depth"]
    scale: float
    shift: float
    sample_count: int
    inlier_count: int
    inlier_ratio: float
    weighted_rmse: float
    median_absolute_residual: float
    p95_absolute_residual: float
    normalized_p95_residual: float
    condition_number: float
    iterations: int
    converged: bool
    sample_mask: np.ndarray = dataclasses.field(repr=False)
    inlier_mask: np.ndarray = dataclasses.field(repr=False)

    def apply(
        self,
        relative_prediction: object,
        *,
        output: Literal["depth", "aligned-domain"] = "depth",
    ) -> np.ndarray:
        """Apply the fitted transform while preserving invalid evidence as NaN."""

        prediction = np.asarray(relative_prediction, dtype=np.float64)
        aligned = self.scale * prediction + self.shift
        aligned = np.where(np.isfinite(aligned) & (aligned > 0.0), aligned, np.nan)
        if output == "aligned-domain":
            return aligned
        if output != "depth":
            raise GeometryInputError(f"unsupported alignment output: {output}")
        if self.representation == "inverse-depth":
            return 1.0 / aligned
        return aligned


def align_relative_depth_to_sfm(
    relative_prediction: object,
    sfm_depth: object,
    confidence: object | None = None,
    valid_mask: object | None = None,
    *,
    representation: Literal["depth", "inverse-depth"] = "inverse-depth",
    min_samples: int = 8,
    huber_delta: float = 1.345,
    inlier_sigma: float = 3.5,
    max_iterations: int = 30,
) -> DepthAlignmentResult:
    """Robustly align affine-relative depth to sparse positive SfM depths.

    ``representation`` describes the prediction.  In inverse-depth mode, the
    sparse SfM depths are inverted before fitting and converted back only when
    :meth:`DepthAlignmentResult.apply` is requested in depth units.  This
    explicit domain avoids silently fitting inverse-depth predictions to depth.

    Confidence values are reliability weights in [0, 1].  They may encode SfM
    track length, reprojection quality, depth-model confidence, or a product of
    independently recorded terms.  This function does not manufacture them.
    """

    prediction = _as_float_array(relative_prediction, "relative_prediction")
    sparse_depth = _as_float_array(sfm_depth, "sfm_depth")
    if prediction.shape != sparse_depth.shape:
        raise GeometryInputError("relative_prediction and sfm_depth shapes differ")
    if representation not in {"depth", "inverse-depth"}:
        raise GeometryInputError(f"unsupported depth representation: {representation}")
    if min_samples < 3:
        raise GeometryInputError("min_samples must be at least 3")
    if huber_delta <= 0.0 or inlier_sigma <= 0.0 or max_iterations <= 0:
        raise GeometryInputError("robust fit parameters must be positive")

    if confidence is None:
        reliability = np.ones(prediction.shape, dtype=np.float64)
    else:
        reliability = np.asarray(confidence, dtype=np.float64)
        if reliability.shape != prediction.shape:
            raise GeometryInputError("confidence shape differs from depth inputs")
        if np.any(np.isfinite(reliability) & ((reliability < 0.0) | (reliability > 1.0))):
            raise GeometryInputError("confidence must be within [0, 1]")

    if valid_mask is None:
        requested = np.ones(prediction.shape, dtype=bool)
    else:
        requested = np.asarray(valid_mask, dtype=bool)
        if requested.shape != prediction.shape:
            raise GeometryInputError("valid_mask shape differs from depth inputs")

    sample_mask = (
        requested
        & np.isfinite(prediction)
        & np.isfinite(sparse_depth)
        & np.isfinite(reliability)
        & (sparse_depth > 0.0)
        & (reliability > 0.0)
    )
    if int(np.count_nonzero(sample_mask)) < min_samples:
        raise GeometryInputError(
            f"depth alignment needs at least {min_samples} valid SfM samples"
        )

    x = prediction[sample_mask]
    target = sparse_depth[sample_mask]
    if representation == "inverse-depth":
        target = 1.0 / target
    base_weights = reliability[sample_mask]
    design = np.column_stack((x, np.ones_like(x)))

    weights = base_weights.copy()
    previous: np.ndarray | None = None
    converged = False
    condition = math.inf
    solution = np.zeros(2, dtype=np.float64)
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        solution, condition = _solve_weighted_linear(design, target, weights)
        residuals = design @ solution - target
        sigma = _robust_sigma(residuals, base_weights)
        if sigma <= np.finfo(np.float64).eps:
            converged = True
            break
        cutoff = huber_delta * sigma
        magnitude = np.abs(residuals)
        huber_weights = np.ones_like(magnitude)
        outside = magnitude > cutoff
        huber_weights[outside] = cutoff / magnitude[outside]
        updated = base_weights * huber_weights
        if previous is not None:
            parameter_change = float(
                np.linalg.norm(solution - previous)
                / max(1.0, np.linalg.norm(previous))
            )
            weight_change = float(
                np.max(np.abs(updated - weights)) / max(1.0, np.max(base_weights))
            )
            if parameter_change <= 1.0e-9 and weight_change <= 1.0e-7:
                weights = updated
                converged = True
                break
        previous = solution.copy()
        weights = updated

    scale, shift = (float(solution[0]), float(solution[1]))
    if not math.isfinite(scale) or not math.isfinite(shift) or scale <= 0.0:
        raise GeometryInputError(
            "relative prediction is not positively monotonic with sparse SfM depth"
        )

    residuals = design @ solution - target
    center = _weighted_percentile(residuals, base_weights, 50.0)
    sigma = _robust_sigma(residuals, base_weights)
    target_span = _weighted_percentile(target, base_weights, 95.0) - _weighted_percentile(
        target, base_weights, 5.0
    )
    numerical_floor = max(abs(target_span), float(np.max(np.abs(target))), 1.0) * 1.0e-9
    cutoff = max(inlier_sigma * sigma, numerical_floor)
    local_inliers = np.abs(residuals - center) <= cutoff
    if int(np.count_nonzero(local_inliers)) < min_samples:
        raise GeometryInputError("robust depth alignment retained insufficient inliers")

    # Remove the remaining gross outliers, then make one confidence-weighted
    # refit.  The reported residual metrics always describe this final model.
    final_weights = base_weights * local_inliers
    solution, condition = _solve_weighted_linear(design, target, final_weights)
    scale, shift = (float(solution[0]), float(solution[1]))
    if scale <= 0.0:
        raise GeometryInputError("final depth alignment has a non-positive scale")
    residuals = design @ solution - target
    inlier_residuals = residuals[local_inliers]
    inlier_weights = base_weights[local_inliers]
    weight_sum = float(np.sum(inlier_weights))
    weighted_rmse = float(
        math.sqrt(np.sum(inlier_weights * inlier_residuals**2) / weight_sum)
    )
    median_absolute = _weighted_percentile(
        np.abs(inlier_residuals), inlier_weights, 50.0
    )
    p95_absolute = _weighted_percentile(np.abs(inlier_residuals), inlier_weights, 95.0)
    normalized_p95 = p95_absolute / max(abs(target_span), numerical_floor)

    inlier_mask = np.zeros(prediction.shape, dtype=bool)
    inlier_mask[sample_mask] = local_inliers
    return DepthAlignmentResult(
        representation=representation,
        scale=scale,
        shift=shift,
        sample_count=int(len(x)),
        inlier_count=int(np.count_nonzero(local_inliers)),
        inlier_ratio=float(np.mean(local_inliers)),
        weighted_rmse=weighted_rmse,
        median_absolute_residual=median_absolute,
        p95_absolute_residual=p95_absolute,
        normalized_p95_residual=float(normalized_p95),
        condition_number=condition,
        iterations=iterations,
        converged=converged,
        sample_mask=sample_mask,
        inlier_mask=inlier_mask,
    )


def validate_semantic_mask(mask: object) -> np.ndarray:
    """Validate and return a stable integer semantic mask without remapping."""

    value = np.asarray(mask)
    if value.ndim != 2 or value.size == 0:
        raise GeometryInputError("semantic mask must be a non-empty 2D array")
    if not np.issubdtype(value.dtype, np.integer):
        if not np.issubdtype(value.dtype, np.floating) or not np.all(
            np.isfinite(value) & (value == np.floor(value))
        ):
            raise GeometryInputError("semantic mask must contain integer label IDs")
    labels = value.astype(np.int16, copy=False)
    allowed = np.array([int(label) for label in SemanticLabel], dtype=np.int16)
    invalid = ~np.isin(labels, allowed)
    if np.any(invalid):
        unique = np.unique(labels[invalid])
        raise GeometryInputError(f"semantic mask contains unknown label IDs: {unique.tolist()}")
    return labels


def finite_static_geometry_mask(mask: object) -> np.ndarray:
    """Return pixels eligible to contribute finite, static geometry."""

    labels = validate_semantic_mask(mask)
    excluded = np.array(
        [int(label) for label in NON_FINITE_LABELS | DYNAMIC_LABELS], dtype=np.int16
    )
    return ~np.isin(labels, excluded)


@dataclasses.dataclass(frozen=True)
class TemporalSemanticFrame:
    """A semantic mask already warped into a shared geometric reference."""

    frame_id: str
    mask: np.ndarray
    valid: np.ndarray
    confidence: np.ndarray
    warp_provenance: str


@dataclasses.dataclass(frozen=True)
class SemanticConsistencyPolicy:
    """Engineering defaults for reconstruction QA, not a safety standard."""

    min_pair_overlap: float = 0.20
    min_weighted_agreement: float = 0.85
    min_road_iou: float = 0.75
    min_boundary_iou: float = 0.60
    min_sky_iou: float = 0.80
    max_unknown_fraction: float = 0.20

    def __post_init__(self) -> None:
        for name, value in dataclasses.asdict(self).items():
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise GeometryInputError(f"{name} must be a finite fraction in [0, 1]")


@dataclasses.dataclass(frozen=True)
class SemanticConsistencyResult:
    pair_count: int
    overlap_fraction: float
    weighted_agreement: float
    unknown_fraction: float
    group_iou: dict[str, float | None]
    class_iou: dict[str, float]
    passes: bool
    failures: tuple[str, ...]


def _validate_temporal_frame(frame: TemporalSemanticFrame) -> TemporalSemanticFrame:
    if not frame.frame_id:
        raise GeometryInputError("temporal semantic frame_id must not be empty")
    if not frame.warp_provenance or frame.warp_provenance.strip().lower() in {
        "raw",
        "none",
        "unknown",
    }:
        raise GeometryInputError(
            "semantic temporal validation requires recorded geometric warp provenance"
        )
    mask = validate_semantic_mask(frame.mask)
    valid = np.asarray(frame.valid, dtype=bool)
    confidence = np.asarray(frame.confidence, dtype=np.float64)
    if valid.shape != mask.shape or confidence.shape != mask.shape:
        raise GeometryInputError("semantic mask, valid, and confidence shapes differ")
    if np.any(np.isfinite(confidence) & ((confidence < 0.0) | (confidence > 1.0))):
        raise GeometryInputError("semantic confidence must be within [0, 1]")
    confidence = np.where(np.isfinite(confidence), confidence, 0.0)
    return TemporalSemanticFrame(
        frame_id=frame.frame_id,
        mask=mask,
        valid=valid,
        confidence=confidence,
        warp_provenance=frame.warp_provenance,
    )


def validate_temporal_semantic_consistency(
    frames: Sequence[TemporalSemanticFrame],
    policy: SemanticConsistencyPolicy | None = None,
) -> SemanticConsistencyResult:
    """Measure adjacent-frame agreement after caller-supplied geometric warps.

    Raw camera masks must not be compared pixel-for-pixel.  The required
    ``warp_provenance`` makes that precondition explicit and auditable.
    """

    if len(frames) < 2:
        raise GeometryInputError("temporal consistency needs at least two frames")
    checked = [_validate_temporal_frame(frame) for frame in frames]
    shape = checked[0].mask.shape
    if any(frame.mask.shape != shape for frame in checked[1:]):
        raise GeometryInputError("warped semantic frames must share a reference shape")
    active_policy = policy or SemanticConsistencyPolicy()

    overlap_pixels = 0
    union_pixels = 0
    agreement_weight = 0.0
    total_weight = 0.0
    intersections = {label: 0.0 for label in SemanticLabel}
    unions = {label: 0.0 for label in SemanticLabel}
    for first, second in zip(checked, checked[1:]):
        overlap = first.valid & second.valid
        union_valid = first.valid | second.valid
        overlap_pixels += int(np.count_nonzero(overlap))
        union_pixels += int(np.count_nonzero(union_valid))
        weights = np.minimum(first.confidence, second.confidence) * overlap
        pair_weight = float(np.sum(weights))
        total_weight += pair_weight
        agreement_weight += float(np.sum(weights * (first.mask == second.mask)))
        for label in SemanticLabel:
            label_value = int(label)
            first_is = first.mask == label_value
            second_is = second.mask == label_value
            intersections[label] += float(np.sum(weights * first_is * second_is))
            unions[label] += float(np.sum(weights * (first_is | second_is)))

    if union_pixels == 0 or total_weight <= 0.0:
        raise GeometryInputError("semantic frames have no positively weighted overlap")
    overlap_fraction = overlap_pixels / union_pixels
    weighted_agreement = agreement_weight / total_weight

    all_valid = np.concatenate([frame.valid.ravel() for frame in checked])
    all_masks = np.concatenate([frame.mask.ravel() for frame in checked])
    unknown_fraction = float(
        np.count_nonzero(all_valid & (all_masks == int(SemanticLabel.UNKNOWN)))
        / max(1, np.count_nonzero(all_valid))
    )
    class_iou = {
        label.name.lower(): intersections[label] / unions[label]
        for label in SemanticLabel
        if unions[label] > 0.0
    }

    def group_iou(group: frozenset[SemanticLabel]) -> float | None:
        intersection = sum(intersections[label] for label in group)
        union = sum(unions[label] for label in group)
        return intersection / union if union > 0.0 else None

    groups = {
        "road": group_iou(ROAD_LABELS),
        "road_boundary": group_iou(ROAD_BOUNDARY_LABELS),
        "sign": group_iou(SIGN_LABELS),
        "dynamic": group_iou(DYNAMIC_LABELS),
        "sky": group_iou(frozenset({SemanticLabel.SKY})),
    }
    failures: list[str] = []
    if overlap_fraction < active_policy.min_pair_overlap:
        failures.append("semantic_overlap_below_policy")
    if weighted_agreement < active_policy.min_weighted_agreement:
        failures.append("semantic_agreement_below_policy")
    if groups["road"] is not None and groups["road"] < active_policy.min_road_iou:
        failures.append("road_semantic_iou_below_policy")
    if (
        groups["road_boundary"] is not None
        and groups["road_boundary"] < active_policy.min_boundary_iou
    ):
        failures.append("road_boundary_iou_below_policy")
    if groups["sky"] is not None and groups["sky"] < active_policy.min_sky_iou:
        failures.append("sky_semantic_iou_below_policy")
    if unknown_fraction > active_policy.max_unknown_fraction:
        failures.append("semantic_unknown_fraction_above_policy")
    return SemanticConsistencyResult(
        pair_count=len(checked) - 1,
        overlap_fraction=float(overlap_fraction),
        weighted_agreement=float(weighted_agreement),
        unknown_fraction=unknown_fraction,
        group_iou=groups,
        class_iou=class_iou,
        passes=not failures,
        failures=tuple(failures),
    )


def _linear_spline_basis(values: np.ndarray, knots: np.ndarray) -> np.ndarray:
    basis = np.zeros((len(values), len(knots)), dtype=np.float64)
    right = np.searchsorted(knots, values, side="right")
    left = np.clip(right - 1, 0, len(knots) - 2)
    width = knots[left + 1] - knots[left]
    fraction = np.clip((values - knots[left]) / width, 0.0, 1.0)
    rows = np.arange(len(values))
    basis[rows, left] = 1.0 - fraction
    basis[rows, left + 1] = fraction
    return basis


def _second_difference(count: int) -> np.ndarray:
    if count < 3:
        return np.zeros((0, count), dtype=np.float64)
    result = np.zeros((count - 2, count), dtype=np.float64)
    rows = np.arange(count - 2)
    result[rows, rows] = 1.0
    result[rows, rows + 1] = -2.0
    result[rows, rows + 2] = 1.0
    return result


@dataclasses.dataclass(frozen=True)
class RoadSurfaceFit:
    """Macro road surface with continuous elevation and cross-slope."""

    knots: np.ndarray
    elevations: np.ndarray
    banks: np.ndarray
    lateral_origin: float
    lateral_min: float
    lateral_max: float
    forward_axis: int
    lateral_axis: int
    up_axis: int
    sample_count: int
    inlier_count: int
    inlier_ratio: float
    p50_absolute_residual: float
    p95_absolute_residual: float
    max_absolute_residual: float
    support_per_knot: np.ndarray
    covered_knot_fraction: float
    condition_number: float
    iterations: int
    converged: bool
    sample_mask: np.ndarray = dataclasses.field(repr=False)
    inlier_mask: np.ndarray = dataclasses.field(repr=False)

    def predict(
        self,
        points: object,
        *,
        allow_extrapolation: bool = False,
    ) -> np.ndarray:
        """Predict surface height, returning NaN outside observed support by default."""

        value = np.asarray(points, dtype=np.float64)
        if value.shape[-1] != 3:
            raise GeometryInputError("road prediction points must end in XYZ")
        forward = value[..., self.forward_axis]
        lateral = value[..., self.lateral_axis]
        clipped = np.clip(forward, self.knots[0], self.knots[-1])
        elevation = np.interp(clipped, self.knots, self.elevations)
        bank = np.interp(clipped, self.knots, self.banks)
        prediction = elevation + bank * (lateral - self.lateral_origin)
        if allow_extrapolation:
            return prediction
        observed = (
            (forward >= self.knots[0])
            & (forward <= self.knots[-1])
            & (lateral >= self.lateral_min)
            & (lateral <= self.lateral_max)
        )
        return np.where(observed, prediction, np.nan)

    @property
    def grades(self) -> np.ndarray:
        return np.diff(self.elevations) / np.diff(self.knots)


@dataclasses.dataclass(frozen=True)
class ObservedRoadSurfaceFit:
    """Sparse, evidence-bounded local road surface.

    Each retained cell contains temporally repeated semantic-road depth
    evidence and belongs to a graph component connected to the primary camera
    corridor.  A query is valid only in one of those retained cells.  This is
    deliberately unlike a convex-hull or nearest-neighbour extrapolator: gaps,
    disconnected semantic islands, and space outside the observations remain
    unknown.
    """

    cell_size: float
    grid_origin: np.ndarray
    grid_shape: tuple[int, int]
    cell_indices: np.ndarray
    cell_keys: np.ndarray
    blocked_cell_keys: np.ndarray
    heights: np.ndarray
    slopes: np.ndarray
    support_counts: np.ndarray
    frame_counts: np.ndarray
    sample_count: int
    inlier_count: int
    inlier_ratio: float
    p50_absolute_residual: float
    p95_absolute_residual: float
    max_absolute_residual: float
    maximum_cell_p95_residual: float
    candidate_cell_count: int
    retained_cell_count: int
    component_count: int
    retained_component_count: int
    anchor_cell_count: int
    ambiguous_cell_count: int
    iterations: int
    converged: bool
    huber_scale: float
    huber_scale_frozen: bool
    huber_objective: float
    relative_solution_change: float
    normalized_weight_change: float
    two_cycle_solution_change: float
    two_cycle_weight_change: float
    first_order_optimality: float
    backtracking_steps: int
    termination_reason: str
    forward_axis: int = 0
    lateral_axis: int = 1
    up_axis: int = 2
    sample_mask: np.ndarray = dataclasses.field(
        repr=False, default_factory=lambda: np.empty(0, bool)
    )
    inlier_mask: np.ndarray = dataclasses.field(
        repr=False, default_factory=lambda: np.empty(0, bool)
    )

    def predict(self, points: object) -> np.ndarray:
        """Predict height only inside retained observed cells; elsewhere NaN."""

        value = np.asarray(points, dtype=np.float64)
        if value.shape[-1] != 3:
            raise GeometryInputError("observed-road prediction points must end in XYZ")
        flat = value.reshape(-1, 3)
        prediction = np.full(len(flat), np.nan, dtype=np.float64)
        plane = flat[:, [self.forward_axis, self.lateral_axis]]
        finite = np.all(np.isfinite(plane), axis=1)
        if not np.any(finite):
            return prediction.reshape(value.shape[:-1])
        indices = np.zeros((len(flat), 2), dtype=np.int64)
        indices[finite] = np.floor(
            (plane[finite] - self.grid_origin) / self.cell_size
        ).astype(np.int64)
        inside = (
            finite
            & (indices[:, 0] >= 0)
            & (indices[:, 1] >= 0)
            & (indices[:, 0] < self.grid_shape[0])
            & (indices[:, 1] < self.grid_shape[1])
        )
        rows = np.flatnonzero(inside)
        if len(rows) == 0:
            return prediction.reshape(value.shape[:-1])
        keys = indices[rows, 0] * self.grid_shape[1] + indices[rows, 1]
        positions = np.searchsorted(self.cell_keys, keys)
        matched = positions < len(self.cell_keys)
        matched[matched] &= self.cell_keys[positions[matched]] == keys[matched]
        if not np.any(matched):
            return prediction.reshape(value.shape[:-1])
        query_rows = rows[matched]
        node_rows = positions[matched]
        centers = self.grid_origin + (
            self.cell_indices[node_rows].astype(np.float64) + 0.5
        ) * self.cell_size
        offset = plane[query_rows] - centers
        prediction[query_rows] = self.heights[node_rows] + np.sum(
            self.slopes[node_rows] * offset, axis=1
        )
        return prediction.reshape(value.shape[:-1])

    def blocked_mask(self, points: object) -> np.ndarray:
        """Return cells where repeated evidence exists but no single layer is safe."""

        value = np.asarray(points, dtype=np.float64)
        if value.shape[-1] != 3:
            raise GeometryInputError("observed-road query points must end in XYZ")
        flat = value.reshape(-1, 3)
        result = np.zeros(len(flat), dtype=bool)
        if len(self.blocked_cell_keys) == 0:
            return result.reshape(value.shape[:-1])
        plane = flat[:, [self.forward_axis, self.lateral_axis]]
        finite = np.all(np.isfinite(plane), axis=1)
        indices = np.zeros((len(flat), 2), dtype=np.int64)
        indices[finite] = np.floor(
            (plane[finite] - self.grid_origin) / self.cell_size
        ).astype(np.int64)
        inside = (
            finite
            & (indices[:, 0] >= 0)
            & (indices[:, 1] >= 0)
            & (indices[:, 0] < self.grid_shape[0])
            & (indices[:, 1] < self.grid_shape[1])
        )
        rows = np.flatnonzero(inside)
        if len(rows):
            keys = indices[rows, 0] * self.grid_shape[1] + indices[rows, 1]
            positions = np.searchsorted(self.blocked_cell_keys, keys)
            matched = positions < len(self.blocked_cell_keys)
            matched[matched] &= (
                self.blocked_cell_keys[positions[matched]] == keys[matched]
            )
            result[rows[matched]] = True
        return result.reshape(value.shape[:-1])


@dataclasses.dataclass(frozen=True)
class EvidenceBoundedRoadSurfaceFit:
    """Primary path surface with observed branch/intersection support."""

    primary: RoadSurfaceFit
    observed: ObservedRoadSurfaceFit | None

    def predict(
        self,
        points: object,
        *,
        allow_extrapolation: bool = False,
    ) -> np.ndarray:
        primary = self.primary.predict(
            points, allow_extrapolation=allow_extrapolation
        )
        if allow_extrapolation or self.observed is None:
            return primary
        local = self.observed.predict(points)
        # Repeated, residual-qualified local evidence is more specific than
        # the path-wide elevation/bank model. It therefore owns supported
        # cells, including intersections and branches; the primary fit is the
        # smooth fallback only where no retained observed cell exists.
        result = np.where(np.isfinite(local), local, primary)
        blocked = self.observed.blocked_mask(points) & ~np.isfinite(local)
        return np.where(blocked, np.nan, result)


def fit_piecewise_road_surface(
    points: object,
    confidence: object | None = None,
    *,
    knot_spacing: float,
    forward_axis: int = 0,
    lateral_axis: int = 1,
    up_axis: int = 2,
    min_points: int = 30,
    min_support_per_knot: int = 3,
    max_knots: int = 128,
    smoothness: float = 0.05,
    huber_delta: float = 1.345,
    inlier_sigma: float = 3.5,
    max_iterations: int = 40,
) -> RoadSurfaceFit:
    """Fit a robust road surface without erasing sustained grade or banking.

    The model is ``z(s,t) = elevation(s) + bank(s) * t``.  Elevation and bank
    use continuous linear splines along the forward coordinate.  A second-
    difference penalty discourages isolated bumps but has zero cost for a
    sustained constant grade or bank.  Gross vertical residuals are rejected
    with Huber IRLS before final confidence-weighted fitting.

    The coordinates remain in the caller's SfM frame.  ``knot_spacing`` and
    residuals are therefore not metres unless provenance records a metric
    anchor.
    """

    value = _as_float_array(points, "points")
    if value.ndim != 2 or value.shape[1] != 3:
        raise GeometryInputError("road points must be an N x 3 array")
    if len({forward_axis, lateral_axis, up_axis}) != 3 or any(
        axis not in {0, 1, 2} for axis in (forward_axis, lateral_axis, up_axis)
    ):
        raise GeometryInputError("road coordinate axes must be distinct XYZ indices")
    if knot_spacing <= 0.0 or min_points < 6 or min_support_per_knot < 1:
        raise GeometryInputError("road fit spacing and support parameters are invalid")
    if max_knots < 2 or smoothness < 0.0 or huber_delta <= 0.0:
        raise GeometryInputError("road fit regularization parameters are invalid")

    if confidence is None:
        reliability = np.ones(len(value), dtype=np.float64)
    else:
        reliability = np.asarray(confidence, dtype=np.float64)
        if reliability.shape != (len(value),):
            raise GeometryInputError("road confidence must contain one value per point")
        if np.any(np.isfinite(reliability) & ((reliability < 0.0) | (reliability > 1.0))):
            raise GeometryInputError("road confidence must be within [0, 1]")
    sample_mask = (
        np.all(np.isfinite(value), axis=1)
        & np.isfinite(reliability)
        & (reliability > 0.0)
    )
    if int(np.count_nonzero(sample_mask)) < min_points:
        raise GeometryInputError(f"road surface needs at least {min_points} valid points")
    samples = value[sample_mask]
    base_weights = reliability[sample_mask]
    forward = samples[:, forward_axis]
    lateral = samples[:, lateral_axis]
    height = samples[:, up_axis]
    extent = float(np.max(forward) - np.min(forward))
    if extent <= np.finfo(np.float64).eps:
        raise GeometryInputError("road points have no longitudinal extent")
    knot_count = max(2, int(math.ceil(extent / knot_spacing)) + 1)
    if knot_count > max_knots:
        raise GeometryInputError(
            f"road fit needs {knot_count} knots, exceeding configured max {max_knots}"
        )
    knots = np.linspace(float(np.min(forward)), float(np.max(forward)), knot_count)
    basis = _linear_spline_basis(forward, knots)
    lateral_origin = _weighted_percentile(lateral, base_weights, 50.0)
    lateral_span = _weighted_percentile(lateral, base_weights, 95.0) - _weighted_percentile(
        lateral, base_weights, 5.0
    )
    lateral_scale = max(abs(lateral_span), float(np.std(lateral)), 1.0e-6)
    normalized_lateral = (lateral - lateral_origin) / lateral_scale
    design = np.hstack((basis, basis * normalized_lateral[:, None]))

    second = _second_difference(knot_count)
    if second.size and smoothness > 0.0:
        # Scale regularization with mean sample support so adding duplicate
        # observations does not silently change the surface prior.
        penalty = math.sqrt(smoothness * float(np.sum(base_weights)) / knot_count)
        regularizer = np.zeros((2 * len(second), 2 * knot_count), dtype=np.float64)
        regularizer[: len(second), :knot_count] = penalty * second
        regularizer[len(second) :, knot_count:] = penalty * second
    else:
        regularizer = None

    weights = base_weights.copy()
    previous: np.ndarray | None = None
    solution = np.zeros(2 * knot_count, dtype=np.float64)
    condition = math.inf
    converged = False
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        solution, condition = _solve_weighted_linear(
            design, height, weights, regularizer
        )
        residuals = design @ solution - height
        sigma = _robust_sigma(residuals, base_weights)
        if sigma <= np.finfo(np.float64).eps:
            converged = True
            break
        cutoff = huber_delta * sigma
        magnitude = np.abs(residuals)
        robust = np.ones_like(magnitude)
        outside = magnitude > cutoff
        robust[outside] = cutoff / magnitude[outside]
        updated = base_weights * robust
        if previous is not None:
            parameter_change = float(
                np.linalg.norm(solution - previous)
                / max(1.0, np.linalg.norm(previous))
            )
            weight_change = float(
                np.max(np.abs(updated - weights)) / max(1.0, np.max(base_weights))
            )
            if parameter_change <= 1.0e-9 and weight_change <= 1.0e-7:
                weights = updated
                converged = True
                break
        previous = solution.copy()
        weights = updated

    residuals = design @ solution - height
    center = _weighted_percentile(residuals, base_weights, 50.0)
    sigma = _robust_sigma(residuals, base_weights)
    height_span = _weighted_percentile(height, base_weights, 95.0) - _weighted_percentile(
        height, base_weights, 5.0
    )
    floor = max(abs(height_span), float(np.max(np.abs(height))), 1.0) * 1.0e-9
    local_inliers = np.abs(residuals - center) <= max(inlier_sigma * sigma, floor)
    if int(np.count_nonzero(local_inliers)) < min_points:
        raise GeometryInputError("road fit retained insufficient inlier support")
    solution, condition = _solve_weighted_linear(
        design,
        height,
        base_weights * local_inliers,
        regularizer,
    )
    residuals = design @ solution - height
    inlier_residuals = np.abs(residuals[local_inliers])
    inlier_weights = base_weights[local_inliers]

    nearest_knot = np.argmax(basis, axis=1)
    support = np.bincount(
        nearest_knot[local_inliers], minlength=knot_count
    ).astype(np.int64)
    covered_fraction = float(np.mean(support >= min_support_per_knot))
    full_inlier_mask = np.zeros(len(value), dtype=bool)
    full_inlier_mask[sample_mask] = local_inliers
    inlier_lateral = lateral[local_inliers]
    inlier_lateral_weights = base_weights[local_inliers]
    return RoadSurfaceFit(
        knots=knots,
        elevations=solution[:knot_count],
        banks=solution[knot_count:] / lateral_scale,
        lateral_origin=float(lateral_origin),
        lateral_min=_weighted_percentile(
            inlier_lateral, inlier_lateral_weights, 1.0
        ),
        lateral_max=_weighted_percentile(
            inlier_lateral, inlier_lateral_weights, 99.0
        ),
        forward_axis=forward_axis,
        lateral_axis=lateral_axis,
        up_axis=up_axis,
        sample_count=int(len(samples)),
        inlier_count=int(np.count_nonzero(local_inliers)),
        inlier_ratio=float(np.mean(local_inliers)),
        p50_absolute_residual=_weighted_percentile(
            inlier_residuals, inlier_weights, 50.0
        ),
        p95_absolute_residual=_weighted_percentile(
            inlier_residuals, inlier_weights, 95.0
        ),
        max_absolute_residual=float(np.max(inlier_residuals)),
        support_per_knot=support,
        covered_knot_fraction=covered_fraction,
        condition_number=condition,
        iterations=iterations,
        converged=converged,
        sample_mask=sample_mask,
        inlier_mask=full_inlier_mask,
    )


def fit_observed_road_surface(
    points: object,
    confidence: object,
    frame_ids: object,
    *,
    primary_surface: RoadSurfaceFit,
    cell_size: float,
    min_samples_per_cell: int = 3,
    min_frames_per_cell: int = 2,
    smoothness: float = 0.08,
    huber_delta: float = 1.345,
    inlier_sigma: float = 3.5,
    max_cell_p95_residual: float | None = None,
    max_iterations: int = 160,
) -> ObservedRoadSurfaceFit:
    """Fit local road branches without filling unobserved horizontal space.

    Samples are quantized into a sparse horizontal grid.  A cell survives only
    when it has repeated frame support, bounded within-cell height residual,
    and an 8-neighbour path to a cell supported by ``primary_surface``.  The
    last condition retains a T-junction branch while rejecting disconnected
    semantic-road islands.  Weak Huber graph smoothing reduces monocular depth
    jitter without connecting cells across gaps or large height jumps.

    Coordinates and tolerances remain in arbitrary SfM scale.  The result is a
    soft training target, not a metric or collision surface.
    """

    from scipy.sparse import csr_matrix, diags
    from scipy.sparse.csgraph import connected_components, laplacian
    from scipy.sparse.linalg import spsolve

    value = _as_float_array(points, "points")
    reliability = np.asarray(confidence, dtype=np.float64)
    frames = np.asarray(frame_ids)
    if value.ndim != 2 or value.shape[1] != 3:
        raise GeometryInputError("observed road points must be an N x 3 array")
    if reliability.shape != (len(value),) or frames.shape != (len(value),):
        raise GeometryInputError(
            "observed road confidence and frame IDs must match the points"
        )
    if np.any(
        np.isfinite(reliability)
        & ((reliability < 0.0) | (reliability > 1.0))
    ):
        raise GeometryInputError("observed road confidence must be within [0, 1]")
    if (
        not math.isfinite(cell_size)
        or cell_size <= 0.0
        or min_samples_per_cell < 2
        or min_frames_per_cell < 1
        or not math.isfinite(smoothness)
        or smoothness < 0.0
        or huber_delta <= 0.0
        or inlier_sigma <= 0.0
        or max_iterations < 1
    ):
        raise GeometryInputError("observed road surface parameters are invalid")
    if max_cell_p95_residual is not None and (
        not math.isfinite(max_cell_p95_residual)
        or max_cell_p95_residual <= 0.0
    ):
        raise GeometryInputError(
            "max_cell_p95_residual must be positive when configured"
        )

    sample_mask = (
        np.all(np.isfinite(value), axis=1)
        & np.isfinite(reliability)
        & (reliability > 0.0)
    )
    if int(np.count_nonzero(sample_mask)) < max(6, min_samples_per_cell):
        raise GeometryInputError("observed road surface has insufficient evidence")
    samples = value[sample_mask]
    weights = reliability[sample_mask]
    sample_frames = frames[sample_mask]
    plane = samples[:, [primary_surface.forward_axis, primary_surface.lateral_axis]]
    height = samples[:, primary_surface.up_axis]

    grid_origin = np.floor(np.min(plane, axis=0) / cell_size) * cell_size
    cell_indices = np.floor((plane - grid_origin) / cell_size).astype(np.int64)
    grid_shape_array = np.max(cell_indices, axis=0) + 1
    if np.any(grid_shape_array <= 0):
        raise GeometryInputError("observed road grid has invalid bounds")
    if int(grid_shape_array[0]) * int(grid_shape_array[1]) >= np.iinfo(np.int64).max:
        raise GeometryInputError("observed road grid key space exceeds int64")
    grid_shape = (int(grid_shape_array[0]), int(grid_shape_array[1]))
    keys = cell_indices[:, 0] * grid_shape[1] + cell_indices[:, 1]
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    unique_keys, starts, counts = np.unique(
        sorted_keys, return_index=True, return_counts=True
    )
    node_count = len(unique_keys)
    node_height = np.full(node_count, np.nan, dtype=np.float64)
    node_p95 = np.full(node_count, np.inf, dtype=np.float64)
    node_support = np.zeros(node_count, dtype=np.int64)
    node_frames = np.zeros(node_count, dtype=np.int64)
    raw_node_support = np.zeros(node_count, dtype=np.int64)
    raw_node_frames = np.zeros(node_count, dtype=np.int64)
    node_ambiguous = np.zeros(node_count, dtype=bool)
    node_weight = np.zeros(node_count, dtype=np.float64)
    robust_point = np.zeros(len(samples), dtype=bool)

    height_scale = max(
        float(np.percentile(height, 95) - np.percentile(height, 5)),
        float(np.max(np.abs(height))),
        1.0,
    )
    numeric_floor = height_scale * 1.0e-9
    ambiguity_gap = max(0.35 * cell_size, numeric_floor)
    for node, (start, count) in enumerate(zip(starts, counts, strict=True)):
        rows = order[start : start + count]
        local_height = height[rows]
        local_weight = weights[rows]
        local_frames = sample_frames[rows]
        raw_node_support[node] = len(rows)
        raw_node_frames[node] = len(np.unique(local_frames))
        height_order = np.argsort(local_height, kind="stable")
        ordered_height = local_height[height_order]
        gaps = np.diff(ordered_height)
        for split in np.flatnonzero(gaps >= ambiguity_gap):
            left = height_order[: split + 1]
            right = height_order[split + 1 :]
            if (
                len(left) >= min_frames_per_cell
                and len(right) >= min_frames_per_cell
                and len(np.unique(local_frames[left])) >= min_frames_per_cell
                and len(np.unique(local_frames[right])) >= min_frames_per_cell
            ):
                node_ambiguous[node] = True
                break
        center = _weighted_percentile(local_height, local_weight, 50.0)
        residual = local_height - center
        sigma = _robust_sigma(residual, local_weight)
        # A small cell-relative floor keeps ordinary multi-frame alignment
        # jitter from deleting a cell when its MAD happens to be nearly zero;
        # large floating depths remain far outside this bounded tolerance.
        cutoff = max(
            inlier_sigma * sigma,
            0.02 * cell_size,
            numeric_floor,
        )
        local_inlier = np.abs(residual) <= cutoff
        if int(np.count_nonzero(local_inlier)) < min_samples_per_cell:
            continue
        inlier_rows = rows[local_inlier]
        inlier_height = height[inlier_rows]
        inlier_weight = weights[inlier_rows]
        center = _weighted_percentile(inlier_height, inlier_weight, 50.0)
        absolute = np.abs(inlier_height - center)
        node_height[node] = center
        node_p95[node] = _weighted_percentile(absolute, inlier_weight, 95.0)
        node_support[node] = len(inlier_rows)
        node_frames[node] = len(np.unique(sample_frames[inlier_rows]))
        node_weight[node] = float(np.sum(inlier_weight))
        robust_point[inlier_rows] = True

    repeated = (
        np.isfinite(node_height)
        & (node_support >= min_samples_per_cell)
        & (node_frames >= min_frames_per_cell)
    )
    if int(np.count_nonzero(repeated)) < 2:
        raise GeometryInputError(
            "observed road surface has insufficient repeated cell evidence"
        )
    repeated_p95 = node_p95[repeated]
    center_p95 = float(np.median(repeated_p95))
    p95_mad = float(np.median(np.abs(repeated_p95 - center_p95)))
    automatic_limit = max(
        center_p95 + 4.0 * 1.4826 * p95_mad,
        0.02 * cell_size,
        numeric_floor,
    )
    automatic_limit = min(automatic_limit, 0.35 * cell_size)
    residual_limit = (
        automatic_limit
        if max_cell_p95_residual is None
        else float(max_cell_p95_residual)
    )
    candidate = repeated & ~node_ambiguous & (node_p95 <= residual_limit)
    if int(np.count_nonzero(candidate)) < 2:
        raise GeometryInputError(
            "observed road surface rejected all cells by residual policy"
        )

    primary_prediction = primary_surface.predict(samples)
    anchor_limit = max(
        3.0 * primary_surface.p95_absolute_residual,
        2.0 * residual_limit,
        0.05 * cell_size,
        numeric_floor,
    )
    point_anchor = (
        robust_point
        & np.isfinite(primary_prediction)
        & (np.abs(height - primary_prediction) <= anchor_limit)
    )
    anchor_per_node = np.bincount(
        np.searchsorted(unique_keys, keys[point_anchor]), minlength=node_count
    ) > 0

    candidate_rows = np.flatnonzero(candidate)
    candidate_keys = unique_keys[candidate_rows]
    candidate_heights = node_height[candidate_rows]
    candidate_indices = np.column_stack(
        (candidate_keys // grid_shape[1], candidate_keys % grid_shape[1])
    ).astype(np.int64)
    candidate_lookup = {
        int(key): index for index, key in enumerate(candidate_keys.tolist())
    }
    edge_height_limit = max(6.0 * residual_limit, 0.60 * cell_size)
    edge_scale = max(3.0 * residual_limit, 0.10 * cell_size)
    edge_rows: list[int] = []
    edge_columns: list[int] = []
    edge_values: list[float] = []
    for index, (cell, cell_height) in enumerate(
        zip(candidate_indices, candidate_heights, strict=True)
    ):
        for offset in ((0, 1), (1, -1), (1, 0), (1, 1)):
            neighbour = cell + offset
            if (
                neighbour[0] < 0
                or neighbour[1] < 0
                or neighbour[0] >= grid_shape[0]
                or neighbour[1] >= grid_shape[1]
            ):
                continue
            neighbour_key = int(neighbour[0] * grid_shape[1] + neighbour[1])
            other = candidate_lookup.get(neighbour_key)
            if other is None:
                continue
            difference = abs(float(cell_height - candidate_heights[other]))
            if difference > edge_height_limit:
                continue
            weight = 1.0 / (1.0 + (difference / edge_scale) ** 2)
            edge_rows.extend((index, other))
            edge_columns.extend((other, index))
            edge_values.extend((weight, weight))
    candidate_graph = csr_matrix(
        (edge_values, (edge_rows, edge_columns)),
        shape=(len(candidate_rows), len(candidate_rows)),
        dtype=np.float64,
    )
    component_count, component_labels = connected_components(
        candidate_graph, directed=False, return_labels=True
    )
    candidate_anchor = anchor_per_node[candidate_rows]
    anchored_components = np.unique(component_labels[candidate_anchor])
    if len(anchored_components) == 0:
        raise GeometryInputError(
            "observed road surface has no component attached to the primary path"
        )
    retained_candidate = np.isin(component_labels, anchored_components)
    retained_rows = candidate_rows[retained_candidate]
    retained_keys = unique_keys[retained_rows]
    raw_repeated = (
        (raw_node_support >= min_samples_per_cell)
        & (raw_node_frames >= min_frames_per_cell)
    )
    blocked_cell_keys = unique_keys[
        raw_repeated & ~np.isin(unique_keys, retained_keys, assume_unique=True)
    ]
    retained_indices = np.column_stack(
        (retained_keys // grid_shape[1], retained_keys % grid_shape[1])
    ).astype(np.int64)
    retained_raw_height = node_height[retained_rows]
    retained_support = node_support[retained_rows]
    retained_frames = node_frames[retained_rows]
    retained_weight = node_weight[retained_rows]
    retained_lookup = {
        int(key): index for index, key in enumerate(retained_keys.tolist())
    }

    smooth_rows: list[int] = []
    smooth_columns: list[int] = []
    smooth_values: list[float] = []
    for index, (cell, cell_height) in enumerate(
        zip(retained_indices, retained_raw_height, strict=True)
    ):
        for offset in ((0, 1), (1, -1), (1, 0), (1, 1)):
            neighbour = cell + offset
            if (
                neighbour[0] < 0
                or neighbour[1] < 0
                or neighbour[0] >= grid_shape[0]
                or neighbour[1] >= grid_shape[1]
            ):
                continue
            neighbour_key = int(neighbour[0] * grid_shape[1] + neighbour[1])
            other = retained_lookup.get(neighbour_key)
            if other is None:
                continue
            difference = abs(float(cell_height - retained_raw_height[other]))
            if difference > edge_height_limit:
                continue
            weight = 1.0 / (1.0 + (difference / edge_scale) ** 2)
            smooth_rows.extend((index, other))
            smooth_columns.extend((other, index))
            smooth_values.extend((weight, weight))
    graph = csr_matrix(
        (smooth_values, (smooth_rows, smooth_columns)),
        shape=(len(retained_rows), len(retained_rows)),
        dtype=np.float64,
    )
    base_node_weight = retained_weight * np.sqrt(retained_frames)
    base_node_weight /= max(float(np.median(base_node_weight)), 1.0e-12)
    node_solution = retained_raw_height.copy()
    converged = False
    iterations = 0
    huber_scale = 0.0
    huber_scale_frozen = False
    huber_objective = 0.0
    relative_solution_change = math.inf
    normalized_weight_change = math.inf
    two_cycle_solution_change = math.inf
    two_cycle_weight_change = math.inf
    first_order_optimality = math.inf
    backtracking_steps = 0
    termination_reason = "iteration-limit"
    if graph.nnz == 0 or smoothness == 0.0:
        converged = True
        relative_solution_change = 0.0
        normalized_weight_change = 0.0
        two_cycle_solution_change = 0.0
        two_cycle_weight_change = 0.0
        first_order_optimality = 0.0
        termination_reason = "no-smoothing-required"
    else:
        graph_laplacian = laplacian(graph, normed=False)
        robust_weight = base_node_weight.copy()
        huber_cutoff = 0.0
        current_objective = math.inf
        solution_two_iterations_ago: np.ndarray | None = None
        previous_target_weight: np.ndarray | None = None
        target_weight_two_iterations_ago: np.ndarray | None = None
        previous_raw_scale: float | None = None
        two_cycle_streak = 0

        def fixed_huber_objective(candidate: np.ndarray) -> float:
            residual = candidate - retained_raw_height
            magnitude = np.abs(residual)
            loss = np.where(
                magnitude <= huber_cutoff,
                0.5 * residual * residual,
                huber_cutoff * (magnitude - 0.5 * huber_cutoff),
            )
            graph_energy = float(candidate @ (graph_laplacian @ candidate))
            return float(
                np.sum(base_node_weight * loss)
                + 0.5 * smoothness * graph_energy
            )

        for iterations in range(1, max_iterations + 1):
            system = (
                diags(robust_weight + 1.0e-12)
                + smoothness * graph_laplacian
            )
            updated = np.asarray(
                spsolve(system, robust_weight * retained_raw_height),
                dtype=np.float64,
            )
            if not np.all(np.isfinite(updated)):
                termination_reason = "non-finite-linear-solve"
                break

            residual = updated - retained_raw_height
            raw_scale = _robust_sigma(residual, base_node_weight)
            if raw_scale <= np.finfo(np.float64).eps:
                node_solution = updated
                huber_scale = raw_scale
                converged = True
                relative_solution_change = 0.0
                normalized_weight_change = 0.0
                two_cycle_solution_change = 0.0
                two_cycle_weight_change = 0.0
                first_order_optimality = 0.0
                termination_reason = "exact-fit"
                break

            if huber_scale_frozen:
                candidate_objective = fixed_huber_objective(updated)
                objective_tolerance = (
                    256.0
                    * np.finfo(np.float64).eps
                    * max(
                        abs(current_objective),
                        abs(candidate_objective),
                        np.finfo(np.float64).tiny,
                    )
                )
                if candidate_objective > current_objective + objective_tolerance:
                    # An exact Huber MM step is descending.  Backtracking is a
                    # numerical safety net for an inexact sparse solve; it
                    # never accepts an increase in the fixed objective.
                    direction = updated - node_solution
                    accepted = False
                    step = 1.0
                    for _ in range(24):
                        step *= 0.5
                        backtracking_steps += 1
                        candidate = node_solution + step * direction
                        candidate_objective = fixed_huber_objective(candidate)
                        if candidate_objective <= current_objective + objective_tolerance:
                            updated = candidate
                            accepted = True
                            break
                    if not accepted:
                        termination_reason = "objective-descent-failed"
                        break
                residual = updated - retained_raw_height

            active_scale = huber_scale if huber_scale_frozen else raw_scale
            active_cutoff = huber_delta * active_scale
            magnitude = np.abs(residual)
            huber_weight = np.ones_like(magnitude)
            outside = magnitude > active_cutoff
            huber_weight[outside] = active_cutoff / magnitude[outside]
            target_weight = base_node_weight * huber_weight
            raw_solution_change = float(
                np.max(np.abs(updated - node_solution))
                / max(1.0, float(np.max(np.abs(node_solution))))
            )

            if (
                not huber_scale_frozen
                and solution_two_iterations_ago is not None
                and target_weight_two_iterations_ago is not None
            ):
                two_cycle_solution_change = float(
                    np.max(np.abs(updated - solution_two_iterations_ago))
                    / max(
                        1.0,
                        float(np.max(np.abs(solution_two_iterations_ago))),
                    )
                )
                two_cycle_weight_change = float(
                    np.max(
                        np.abs(target_weight - target_weight_two_iterations_ago)
                    )
                    / max(1.0, float(np.max(base_node_weight)))
                )
                raw_weight_change = float(
                    np.max(np.abs(target_weight - robust_weight))
                    / max(1.0, float(np.max(base_node_weight)))
                )
                strict_two_cycle = (
                    raw_solution_change > 1.0e-8
                    and raw_weight_change > 1.0e-5
                    and two_cycle_solution_change
                    <= 0.05 * raw_solution_change
                    and two_cycle_weight_change <= 0.05 * raw_weight_change
                )
                two_cycle_streak = two_cycle_streak + 1 if strict_two_cycle else 0

                if two_cycle_streak >= 2 and previous_raw_scale is not None:
                    # A weighted MAD is an order statistic and can toggle at a
                    # median boundary.  Once two consecutive iterates prove a
                    # strict period-two orbit, freeze at the midpoint of its
                    # two scales.  Subsequent Huber IRLS steps then minimize
                    # one convex objective monotonically instead of alternating
                    # between two different objectives.
                    huber_scale = 0.5 * (raw_scale + previous_raw_scale)
                    huber_cutoff = huber_delta * huber_scale
                    huber_scale_frozen = True
                    magnitude = np.abs(residual)
                    huber_weight = np.ones_like(magnitude)
                    outside = magnitude > huber_cutoff
                    huber_weight[outside] = huber_cutoff / magnitude[outside]
                    target_weight = base_node_weight * huber_weight
                    current_objective = fixed_huber_objective(updated)

            if not huber_scale_frozen:
                huber_scale = raw_scale
                huber_cutoff = active_cutoff

            next_weight = target_weight
            relative_solution_change = raw_solution_change
            normalized_weight_change = float(
                np.max(np.abs(next_weight - robust_weight))
                / max(1.0, float(np.max(base_node_weight)))
            )
            solution_two_iterations_ago = node_solution.copy()
            target_weight_two_iterations_ago = previous_target_weight
            previous_target_weight = target_weight.copy()
            previous_raw_scale = raw_scale
            node_solution = updated
            robust_weight = next_weight
            if huber_scale_frozen:
                current_objective = fixed_huber_objective(node_solution)
            if (
                relative_solution_change <= 1.0e-8
                and normalized_weight_change <= 1.0e-5
            ):
                converged = True
                termination_reason = (
                    "cycle-midpoint-fixed-scale-huber"
                    if huber_scale_frozen
                    else "adaptive-huber-step-and-weight"
                )
                break

        if huber_cutoff > 0.0 and np.all(np.isfinite(node_solution)):
            residual = node_solution - retained_raw_height
            data_gradient = base_node_weight * np.clip(
                residual, -huber_cutoff, huber_cutoff
            )
            graph_gradient = smoothness * np.asarray(
                graph_laplacian @ node_solution, dtype=np.float64
            )
            gradient = data_gradient + graph_gradient
            gradient_scale = max(
                float(np.max(np.abs(data_gradient))),
                float(np.max(np.abs(graph_gradient))),
                np.finfo(np.float64).tiny,
            )
            first_order_optimality = float(
                np.max(np.abs(gradient)) / gradient_scale
            )
            huber_objective = fixed_huber_objective(node_solution)

    slopes = np.zeros((len(retained_rows), 2), dtype=np.float64)
    for index in range(len(retained_rows)):
        neighbours = graph.indices[graph.indptr[index] : graph.indptr[index + 1]]
        if len(neighbours) == 0:
            continue
        delta = (
            retained_indices[neighbours] - retained_indices[index]
        ).astype(np.float64) * cell_size
        target = node_solution[neighbours] - node_solution[index]
        local_weight = graph.data[graph.indptr[index] : graph.indptr[index + 1]]
        normal = delta.T @ (local_weight[:, None] * delta)
        normal += np.eye(2, dtype=np.float64) * (cell_size**2 * 1.0e-6)
        rhs = delta.T @ (local_weight * target)
        local_slope = np.linalg.solve(normal, rhs)
        magnitude = float(np.linalg.norm(local_slope))
        if magnitude > 0.75:
            local_slope *= 0.75 / magnitude
        slopes[index] = local_slope

    sample_positions = np.searchsorted(retained_keys, keys)
    supported_point = sample_positions < len(retained_keys)
    supported_point[supported_point] &= (
        retained_keys[sample_positions[supported_point]]
        == keys[supported_point]
    )
    sample_prediction = np.full(len(samples), np.nan, dtype=np.float64)
    supported_rows = np.flatnonzero(supported_point)
    if len(supported_rows):
        nodes = sample_positions[supported_rows]
        centers = grid_origin + (
            retained_indices[nodes].astype(np.float64) + 0.5
        ) * cell_size
        sample_prediction[supported_rows] = node_solution[nodes] + np.sum(
            slopes[nodes] * (plane[supported_rows] - centers), axis=1
        )
    absolute_residual = np.abs(sample_prediction - height)
    point_residual_limit = max(3.0 * residual_limit, 0.10 * cell_size)
    local_inlier = (
        robust_point
        & supported_point
        & np.isfinite(absolute_residual)
        & (absolute_residual <= point_residual_limit)
    )
    if int(np.count_nonzero(local_inlier)) < min_samples_per_cell:
        raise GeometryInputError(
            "observed road surface retained insufficient point support"
        )
    supported_residual = absolute_residual[supported_point]
    supported_weight = weights[supported_point]
    full_inlier_mask = np.zeros(len(value), dtype=bool)
    full_inlier_mask[np.flatnonzero(sample_mask)[local_inlier]] = True

    return ObservedRoadSurfaceFit(
        cell_size=float(cell_size),
        grid_origin=grid_origin,
        grid_shape=grid_shape,
        cell_indices=retained_indices,
        cell_keys=retained_keys,
        blocked_cell_keys=blocked_cell_keys,
        heights=node_solution,
        slopes=slopes,
        support_counts=retained_support,
        frame_counts=retained_frames,
        sample_count=int(len(samples)),
        inlier_count=int(np.count_nonzero(local_inlier)),
        inlier_ratio=float(np.mean(local_inlier)),
        p50_absolute_residual=_weighted_percentile(
            supported_residual, supported_weight, 50.0
        ),
        p95_absolute_residual=_weighted_percentile(
            supported_residual, supported_weight, 95.0
        ),
        max_absolute_residual=float(np.max(supported_residual)),
        maximum_cell_p95_residual=float(residual_limit),
        candidate_cell_count=int(np.count_nonzero(candidate)),
        retained_cell_count=int(len(retained_rows)),
        component_count=int(component_count),
        retained_component_count=int(len(anchored_components)),
        anchor_cell_count=int(np.count_nonzero(candidate_anchor)),
        ambiguous_cell_count=int(np.count_nonzero(node_ambiguous & raw_repeated)),
        iterations=iterations,
        converged=converged,
        huber_scale=float(huber_scale),
        huber_scale_frozen=huber_scale_frozen,
        huber_objective=float(huber_objective),
        relative_solution_change=float(relative_solution_change),
        normalized_weight_change=float(normalized_weight_change),
        two_cycle_solution_change=float(two_cycle_solution_change),
        two_cycle_weight_change=float(two_cycle_weight_change),
        first_order_optimality=float(first_order_optimality),
        backtracking_steps=int(backtracking_steps),
        termination_reason=termination_reason,
        forward_axis=primary_surface.forward_axis,
        lateral_axis=primary_surface.lateral_axis,
        up_axis=primary_surface.up_axis,
        sample_mask=sample_mask,
        inlier_mask=full_inlier_mask,
    )


class EvidenceKind(str, Enum):
    OBSERVED_RGB = "observed-rgb"
    SFM_TRIANGULATED = "sfm-triangulated"
    MODEL_INFERRED = "model-inferred"
    SENSOR_MEASURED = "sensor-measured"
    GENERATED = "generated"


class ScaleProvenance(str, Enum):
    UNKNOWN_MONOCULAR = "unknown-monocular"
    SFM_ARBITRARY = "sfm-arbitrary"
    KNOWN_DISTANCE = "known-distance"
    CALIBRATED_STEREO = "calibrated-stereo"
    DEPTH_SENSOR = "depth-sensor"
    LIDAR = "lidar"
    GNSS_IMU = "gnss-imu"

    @property
    def is_metric(self) -> bool:
        return self not in {
            ScaleProvenance.UNKNOWN_MONOCULAR,
            ScaleProvenance.SFM_ARBITRARY,
        }


@dataclasses.dataclass(frozen=True)
class EvidenceSource:
    kind: EvidenceKind
    producer: str
    version: str
    license_id: str
    source_ids: tuple[str, ...]
    generated: bool = False

    def __post_init__(self) -> None:
        if not self.producer or not self.version or not self.license_id:
            raise GeometryInputError("evidence producer, version, and license are required")
        if not self.source_ids:
            raise GeometryInputError("evidence must reference at least one source ID")
        if self.kind == EvidenceKind.GENERATED and not self.generated:
            raise GeometryInputError("generated evidence must be marked generated")


@dataclasses.dataclass(frozen=True)
class GeometryProvenance:
    sfm: EvidenceSource
    depth: EvidenceSource
    semantics: EvidenceSource
    scale: ScaleProvenance
    coordinate_frame: str
    metric_anchor: str | None = None
    gravity_aligned: bool = False
    gravity_source: str | None = None

    def __post_init__(self) -> None:
        if not self.coordinate_frame:
            raise GeometryInputError("geometry coordinate frame must be recorded")
        if self.scale.is_metric and not self.metric_anchor:
            raise GeometryInputError("metric scale provenance requires an anchor description")
        if not self.scale.is_metric and self.metric_anchor:
            raise GeometryInputError("non-metric scale must not claim a metric anchor")
        if self.gravity_aligned and not self.gravity_source:
            raise GeometryInputError(
                "gravity-aligned provenance requires a gravity source description"
            )
        if not self.gravity_aligned and self.gravity_source:
            raise GeometryInputError(
                "gravity source must not be claimed when the frame is not gravity aligned"
            )

    @property
    def contains_generated_evidence(self) -> bool:
        return any(source.generated for source in (self.sfm, self.depth, self.semantics))


@dataclasses.dataclass(frozen=True)
class GeometryObservationMetrics:
    """Fractions are measured over the explicitly validated evidence domain."""

    unobserved_fraction: float
    finite_sky_geometry_fraction: float
    dynamic_geometry_fraction: float

    def __post_init__(self) -> None:
        for name, value in dataclasses.asdict(self).items():
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise GeometryInputError(f"{name} must be a finite fraction in [0, 1]")


@dataclasses.dataclass(frozen=True)
class GeometrySafetyPolicy:
    """Project policy, not regulatory certification.

    ``max_road_p95_residual`` intentionally defaults to ``None``.  A caller
    must choose a tolerance in a metric coordinate frame for a concrete robot
    and operational design domain before collision validation can begin.
    """

    min_depth_samples: int = 32
    min_depth_inlier_ratio: float = 0.80
    max_depth_normalized_p95: float = 0.10
    min_road_points: int = 100
    min_road_inlier_ratio: float = 0.90
    min_road_covered_knot_fraction: float = 0.80
    max_road_p95_residual: float | None = None
    max_unobserved_fraction: float = 0.05
    max_finite_sky_geometry_fraction: float = 0.0
    max_dynamic_geometry_fraction: float = 0.01
    require_metric_scale: bool = True
    allow_generated_geometry: bool = False

    def __post_init__(self) -> None:
        if self.min_depth_samples < 3 or self.min_road_points < 6:
            raise GeometryInputError("safety sample thresholds are too small")
        fraction_fields = (
            "min_depth_inlier_ratio",
            "max_depth_normalized_p95",
            "min_road_inlier_ratio",
            "min_road_covered_knot_fraction",
            "max_unobserved_fraction",
            "max_finite_sky_geometry_fraction",
            "max_dynamic_geometry_fraction",
        )
        for name in fraction_fields:
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise GeometryInputError(f"{name} must be a finite fraction in [0, 1]")
        if self.max_road_p95_residual is not None and (
            not math.isfinite(self.max_road_p95_residual)
            or self.max_road_p95_residual <= 0.0
        ):
            raise GeometryInputError("max_road_p95_residual must be positive when set")


@dataclasses.dataclass(frozen=True)
class GeometrySafetyGateResult:
    """Fail-closed preflight for later collision-system validation."""

    eligible_for_collision_validation: bool
    visualization_publishable: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]


def evaluate_geometry_safety_gate(
    alignment: DepthAlignmentResult,
    road: RoadSurfaceFit,
    semantics: SemanticConsistencyResult,
    provenance: GeometryProvenance,
    observations: GeometryObservationMetrics,
    policy: GeometrySafetyPolicy | None = None,
) -> GeometrySafetyGateResult:
    """Evaluate evidence quality without claiming that geometry is safe."""

    active = policy or GeometrySafetyPolicy()
    failures: list[str] = []
    warnings: list[str] = []
    if active.require_metric_scale and not provenance.scale.is_metric:
        failures.append("metric_scale_anchor_missing")
    if not provenance.gravity_aligned:
        failures.append("gravity_alignment_missing")
    if provenance.contains_generated_evidence and not active.allow_generated_geometry:
        failures.append("generated_geometry_not_allowed")
    if alignment.sample_count < active.min_depth_samples:
        failures.append("depth_sample_count_below_policy")
    if alignment.inlier_ratio < active.min_depth_inlier_ratio:
        failures.append("depth_inlier_ratio_below_policy")
    if alignment.normalized_p95_residual > active.max_depth_normalized_p95:
        failures.append("depth_alignment_residual_above_policy")
    if road.sample_count < active.min_road_points:
        failures.append("road_sample_count_below_policy")
    if road.inlier_ratio < active.min_road_inlier_ratio:
        failures.append("road_inlier_ratio_below_policy")
    if road.covered_knot_fraction < active.min_road_covered_knot_fraction:
        failures.append("road_longitudinal_coverage_below_policy")
    if active.max_road_p95_residual is None:
        failures.append("metric_road_residual_tolerance_not_configured")
    elif road.p95_absolute_residual > active.max_road_p95_residual:
        failures.append("road_surface_residual_above_policy")
    if not semantics.passes:
        failures.extend(semantics.failures)
    if observations.unobserved_fraction > active.max_unobserved_fraction:
        failures.append("unobserved_fraction_above_policy")
    if (
        observations.finite_sky_geometry_fraction
        > active.max_finite_sky_geometry_fraction
    ):
        failures.append("finite_sky_geometry_present")
    if observations.dynamic_geometry_fraction > active.max_dynamic_geometry_fraction:
        failures.append("dynamic_geometry_leakage_above_policy")
    if not alignment.converged:
        warnings.append("depth_alignment_iteration_limit_reached")
    if not road.converged:
        warnings.append("road_fit_iteration_limit_reached")

    # Visual publication may use arbitrary scale, but still rejects finite sky
    # and temporally inconsistent semantics.  It remains separate from robot
    # or collision use.
    visualization_publishable = (
        observations.finite_sky_geometry_fraction
        <= active.max_finite_sky_geometry_fraction
        and semantics.passes
        and road.inlier_ratio >= active.min_road_inlier_ratio
    )
    unique_failures = tuple(dict.fromkeys(failures))
    return GeometrySafetyGateResult(
        eligible_for_collision_validation=not unique_failures,
        visualization_publishable=visualization_publishable,
        failures=unique_failures,
        warnings=tuple(dict.fromkeys(warnings)),
    )


__all__ = [
    "DYNAMIC_LABELS",
    "GEOMETRY_SCHEMA",
    "NON_FINITE_LABELS",
    "NAVIGABLE_SURFACE_LABELS",
    "ROAD_BOUNDARY_LABELS",
    "ROAD_LABELS",
    "SEMANTIC_SCHEMA",
    "SIGN_LABELS",
    "DepthAlignmentResult",
    "EvidenceKind",
    "EvidenceSource",
    "GeometryInputError",
    "GeometryObservationMetrics",
    "GeometryProvenance",
    "GeometrySafetyGateResult",
    "GeometrySafetyPolicy",
    "EvidenceBoundedRoadSurfaceFit",
    "ObservedRoadSurfaceFit",
    "RoadSurfaceFit",
    "ScaleProvenance",
    "SemanticConsistencyPolicy",
    "SemanticConsistencyResult",
    "SemanticLabel",
    "TemporalSemanticFrame",
    "align_relative_depth_to_sfm",
    "evaluate_geometry_safety_gate",
    "finite_static_geometry_mask",
    "fit_observed_road_surface",
    "fit_piecewise_road_surface",
    "validate_semantic_mask",
    "validate_temporal_semantic_consistency",
]
