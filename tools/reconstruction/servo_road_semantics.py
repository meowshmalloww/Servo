#!/usr/bin/env python3
"""Deterministic road-paint evidence for Servo reconstruction.

This clean-room module extracts *proposals*, not driving truth.  It combines
road-mask gating, local bright-ridge contrast, and white/yellow chroma.  A
separate consensus primitive can then accept or reject reference-frame
proposals using caller-supplied calibrated correspondences.  Pixels without
enough correspondence support remain explicitly unknown.

The design follows the image-evidence principles in the extended symmetric
local-threshold road-marking method (arXiv:1911.09054): road-only processing
and local dark-light-dark contrast are substantially safer than a global
brightness threshold.  It also deliberately keeps front-view evidence at its
requested resolution; perspective-warp interpolation is known to damage
distant markings (arXiv:2003.08550).  OpenCV morphology and connected-
component APIs are used as documented for OpenCV 4.11.  No project code or
pretrained weights are copied or loaded.

Important limitations:

* display-referred pixels are not radiometrically linear measurements;
* confidence is a deterministic heuristic evidence score, not probability;
* a semantic road mask can be wrong, so this output is not collision-ready;
* temporal consensus validates repeatability, not metric position accuracy.
"""

from __future__ import annotations

import dataclasses
import math
from enum import IntEnum
from typing import Sequence

import cv2
import numpy as np


ROAD_PAINT_SCHEMA = "servo.road-paint-evidence/v1"
ROAD_PAINT_CONSENSUS_SCHEMA = "servo.road-paint-consensus/v1"


class RoadPaintInputError(ValueError):
    """Raised when road-paint evidence inputs are ambiguous or malformed."""


class RoadPaintClass(IntEnum):
    """Stable output classes.

    UNKNOWN is used outside semantic road support.  Unmarked road is not
    assigned a class because this module proposes paint; it does not certify
    the absence of paint.
    """

    UNKNOWN = 0
    WHITE = 1
    YELLOW = 2


class ConsensusDecision(IntEnum):
    """Decision for a reference-frame paint proposal."""

    UNKNOWN = 0
    ACCEPTED = 1
    REJECTED = 2


@dataclasses.dataclass(frozen=True)
class RoadPaintConfig:
    """Resolution-independent extraction controls.

    Thresholds are expressed in normalized OpenCV Lab/HSV channels.  The
    local window is odd and scales with the target image, within explicit
    bounds so behavior stays inspectable at both preview and source sizes.
    """

    local_window_fraction: float = 0.15
    local_window_min: int = 15
    local_window_max: int = 81
    white_candidate_threshold: float = 0.34
    yellow_candidate_threshold: float = 0.32
    minimum_white_luminance: float = 0.62
    minimum_shadow_white_luminance: float = 0.28
    minimum_shadow_white_ridge: float = 0.72
    minimum_component_area_at_640x360: int = 4
    maximum_component_road_fraction: float = 0.04
    maximum_component_half_thickness_fraction: float = 0.025
    maximum_thick_component_road_fraction: float = 0.032
    maximum_frame_paint_road_fraction: float = 0.12
    minimum_component_mean_confidence: float = 0.34
    minimum_component_core_fraction: float = 0.08


@dataclasses.dataclass(frozen=True)
class TemporalConsensusConfig:
    """Fail-closed repeat-observation requirements."""

    minimum_observations: int = 2
    minimum_agreeing_observations: int = 2
    minimum_agreement_ratio: float = 0.60
    minimum_source_proposal_confidence: float = 0.20
    require_same_color: bool = False


@dataclasses.dataclass(frozen=True)
class RoadPaintEvidence:
    """Single-frame road-paint proposals at one explicit target resolution."""

    paint_class: np.ndarray
    candidate_mask: np.ndarray
    confidence: np.ndarray
    road_support: np.ndarray
    provenance: dict[str, object]
    metrics: dict[str, object]


@dataclasses.dataclass(frozen=True)
class RoadPaintConsensus:
    """Repeatability decision for reference-frame paint proposals."""

    decision: np.ndarray
    accepted_mask: np.ndarray
    rejected_mask: np.ndarray
    confidence: np.ndarray
    observation_count: np.ndarray
    agreement_count: np.ndarray
    provenance: dict[str, object]
    metrics: dict[str, object]


def _odd_window(size: int, config: RoadPaintConfig) -> int:
    if size <= 0:
        raise RoadPaintInputError("target dimensions must be positive")
    requested = int(round(size * config.local_window_fraction))
    requested = max(config.local_window_min, min(config.local_window_max, requested))
    requested += 1 - requested % 2
    maximum = size if size % 2 == 1 else size - 1
    return max(1, min(requested, maximum))


def _validate_config(config: RoadPaintConfig) -> None:
    if not 0.0 < config.local_window_fraction <= 1.0:
        raise RoadPaintInputError("local_window_fraction must be in (0, 1]")
    if config.local_window_min < 1 or config.local_window_max < config.local_window_min:
        raise RoadPaintInputError("local window bounds are invalid")
    for name in (
        "white_candidate_threshold",
        "yellow_candidate_threshold",
        "minimum_white_luminance",
        "minimum_shadow_white_luminance",
        "minimum_shadow_white_ridge",
    ):
        value = float(getattr(config, name))
        if not 0.0 <= value <= 1.0:
            raise RoadPaintInputError(f"{name} must be in [0, 1]")
    if config.minimum_component_area_at_640x360 < 1:
        raise RoadPaintInputError("minimum component area must be positive")
    for name in (
        "maximum_component_road_fraction",
        "maximum_component_half_thickness_fraction",
        "maximum_thick_component_road_fraction",
        "maximum_frame_paint_road_fraction",
        "minimum_component_mean_confidence",
        "minimum_component_core_fraction",
    ):
        value = float(getattr(config, name))
        if not 0.0 <= value <= 1.0:
            raise RoadPaintInputError(f"{name} must be in [0, 1]")


def _resize_inputs(
    image_bgr: np.ndarray,
    road_mask: np.ndarray,
    target_size: tuple[int, int] | None,
) -> tuple[np.ndarray, np.ndarray, str, str]:
    image = np.asarray(image_bgr)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise RoadPaintInputError("image_bgr must be an HxWx3 uint8 display-referred BGR image")
    if image.shape[0] == 0 or image.shape[1] == 0:
        raise RoadPaintInputError("image_bgr must not be empty")

    mask = np.asarray(road_mask)
    if mask.ndim != 2:
        raise RoadPaintInputError("semantic_road_mask must be a two-dimensional array")
    if not (
        mask.dtype == np.bool_
        or np.issubdtype(mask.dtype, np.integer)
        or np.issubdtype(mask.dtype, np.floating)
    ):
        raise RoadPaintInputError("semantic_road_mask must be boolean or numeric")
    if np.issubdtype(mask.dtype, np.floating) and not np.isfinite(mask).all():
        raise RoadPaintInputError("semantic_road_mask must not contain NaN or infinity")

    if target_size is None:
        target_width, target_height = image.shape[1], image.shape[0]
    else:
        if len(target_size) != 2:
            raise RoadPaintInputError("target_size must be (width, height)")
        target_width, target_height = int(target_size[0]), int(target_size[1])
        if target_width <= 0 or target_height <= 0:
            raise RoadPaintInputError("target_size dimensions must be positive")

    source_shape = image.shape[:2]
    target_shape = (target_height, target_width)
    if mask.shape not in (source_shape, target_shape):
        raise RoadPaintInputError(
            "semantic_road_mask must match the source image or requested target resolution"
        )

    if source_shape == target_shape:
        resized_image = np.array(image, copy=True)
        image_interpolation = "none"
    else:
        shrinking = target_width <= image.shape[1] and target_height <= image.shape[0]
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
        resized_image = cv2.resize(image, (target_width, target_height), interpolation=interpolation)
        image_interpolation = "area" if shrinking else "bilinear"

    if mask.shape == target_shape:
        resized_mask = mask > 0
        mask_interpolation = "none"
    else:
        resized_mask = cv2.resize(
            (mask > 0).astype(np.uint8),
            (target_width, target_height),
            interpolation=cv2.INTER_NEAREST,
        ).astype(bool)
        mask_interpolation = "nearest"

    return resized_image, resized_mask, image_interpolation, mask_interpolation


def _masked_box_mean(values: np.ndarray, support: np.ndarray, window: int) -> np.ndarray:
    support_float = support.astype(np.float32)
    numerator = cv2.boxFilter(
        values.astype(np.float32) * support_float,
        cv2.CV_32F,
        (window, window),
        normalize=True,
        borderType=cv2.BORDER_REFLECT101,
    )
    denominator = cv2.boxFilter(
        support_float,
        cv2.CV_32F,
        (window, window),
        normalize=True,
        borderType=cv2.BORDER_REFLECT101,
    )
    return numerator / np.maximum(denominator, 1e-6)


def _local_tophat(values: np.ndarray, support: np.ndarray, window: int) -> np.ndarray:
    """Return normalized local bright-ridge response without road-edge leakage."""

    if not np.any(support):
        return np.zeros(values.shape, dtype=np.float32)
    fill = float(np.median(values[support]))
    filled = np.where(support, values, fill).astype(np.float32)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (window, window))
    opened = cv2.morphologyEx(
        filled,
        cv2.MORPH_OPEN,
        kernel,
        borderType=cv2.BORDER_REFLECT101,
    )
    return np.maximum(filled - opened, 0.0).astype(np.float32)


def _linear_score(value: np.ndarray, low: np.ndarray | float, width: float) -> np.ndarray:
    return np.clip((value - low) / max(float(width), 1e-6), 0.0, 1.0).astype(np.float32)


def _component_filter(
    raw_mask: np.ndarray,
    raw_confidence: np.ndarray,
    road_support: np.ndarray,
    threshold: float,
    config: RoadPaintConfig,
) -> tuple[np.ndarray, list[dict[str, object]], int]:
    height, width = raw_mask.shape
    scale = math.sqrt((height * width) / float(640 * 360))
    minimum_area = max(2, int(round(config.minimum_component_area_at_640x360 * scale)))
    road_pixels = max(int(np.count_nonzero(road_support)), 1)
    maximum_half_thickness = max(
        2.0,
        float(config.maximum_component_half_thickness_fraction * min(height, width)),
    )

    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        raw_mask.astype(np.uint8),
        connectivity=8,
        ltype=cv2.CV_32S,
    )
    kept = np.zeros_like(raw_mask, dtype=bool)
    records: list[dict[str, object]] = []
    rejected = 0
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        component = labels == label
        values = raw_confidence[component]
        mean_confidence = float(np.mean(values)) if values.size else 0.0
        core_fraction = float(np.mean(values >= min(1.0, threshold + 0.18))) if values.size else 0.0
        road_fraction = area / road_pixels
        distance = cv2.distanceTransform(component.astype(np.uint8), cv2.DIST_L2, 5)
        maximum_half_thickness_pixels = float(np.max(distance)) if distance.size else 0.0
        keep = (
            area >= minimum_area
            and road_fraction <= config.maximum_component_road_fraction
            and (
                maximum_half_thickness_pixels <= maximum_half_thickness
                or road_fraction <= config.maximum_thick_component_road_fraction
            )
            and mean_confidence >= config.minimum_component_mean_confidence
            and core_fraction >= config.minimum_component_core_fraction
        )
        if keep:
            kept[component] = True
        else:
            rejected += 1
        records.append(
            {
                "areaPixels": area,
                "meanConfidence": mean_confidence,
                "coreFraction": core_fraction,
                "roadFraction": road_fraction,
                "maximumHalfThicknessPixels": maximum_half_thickness_pixels,
                "maximumAllowedHalfThicknessPixels": maximum_half_thickness,
                "maximumThickComponentRoadFraction": (
                    config.maximum_thick_component_road_fraction
                ),
                "kept": keep,
            }
        )
    return kept & road_support, records, rejected


def extract_road_paint_evidence(
    image_bgr: np.ndarray,
    semantic_road_mask: np.ndarray,
    *,
    target_size: tuple[int, int] | None = None,
    config: RoadPaintConfig | None = None,
) -> RoadPaintEvidence:
    """Extract white/yellow road-paint proposals at ``target_size``.

    ``semantic_road_mask`` may match the source image or target dimensions.
    Every output proposal and nonzero confidence value is guaranteed to be
    inside the nearest-neighbor-resampled road mask.
    """

    selected = config or RoadPaintConfig()
    _validate_config(selected)
    image, road, image_interpolation, mask_interpolation = _resize_inputs(
        image_bgr,
        semantic_road_mask,
        target_size,
    )
    height, width = road.shape
    window = _odd_window(min(height, width), selected)

    paint_class = np.zeros((height, width), dtype=np.uint8)
    confidence = np.zeros((height, width), dtype=np.float32)
    if not np.any(road):
        provenance = _extraction_provenance(
            width,
            height,
            window,
            image_interpolation,
            mask_interpolation,
            selected,
        )
        metrics = {
            "schema": ROAD_PAINT_SCHEMA,
            "targetWidth": width,
            "targetHeight": height,
            "roadPixels": 0,
            "candidatePixels": 0,
            "whitePixels": 0,
            "yellowPixels": 0,
            "paintFractionOfRoad": 0.0,
            "components": {"examined": 0, "kept": 0, "rejected": 0},
        }
        return RoadPaintEvidence(
            paint_class,
            paint_class > 0,
            confidence,
            road,
            provenance,
            metrics,
        )

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32) / 255.0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    luminance = lab[:, :, 0]
    lab_a = lab[:, :, 1] - (128.0 / 255.0)
    lab_b = lab[:, :, 2] - (128.0 / 255.0)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1] / 255.0

    local_luma_mean = _masked_box_mean(luminance, road, window)
    local_luma_square = _masked_box_mean(luminance * luminance, road, window)
    local_luma_std = np.sqrt(
        np.maximum(local_luma_square - local_luma_mean * local_luma_mean, 0.0)
    )
    luma_tophat = _local_tophat(luminance, road, window)
    yellow_tophat = _local_tophat(lab_b, road, window)

    # A local standard-deviation term raises the evidence requirement near
    # textured asphalt and illumination boundaries.  A bright half-plane from
    # a cast shadow has little top-hat response, unlike a bounded paint mark.
    adaptive_luma_floor = 0.012 + 0.16 * local_luma_std
    luma_ridge = _linear_score(luma_tophat, adaptive_luma_floor, 0.105)
    chroma_ridge = _linear_score(yellow_tophat, 0.012, 0.115)
    visibility = _linear_score(luminance, 0.12, 0.30)

    chroma_radius = np.sqrt(lab_a * lab_a + lab_b * lab_b)
    neutral = np.clip((0.20 - chroma_radius) / 0.15, 0.0, 1.0).astype(np.float32)
    white_confidence = luma_ridge * (0.55 + 0.45 * neutral) * visibility

    # A purely relative bright-ridge detector treats sunlit aggregate and
    # asphalt texture as paint.  Require either display-bright neutral paint,
    # or a much stronger local ridge for genuinely shadowed paint.  The latter
    # preserves bounded markings under cast shadows without accepting broad
    # road illumination changes.
    absolute_white = luminance >= selected.minimum_white_luminance
    shadow_white = (
        (luminance >= selected.minimum_shadow_white_luminance)
        & (luma_ridge >= selected.minimum_shadow_white_ridge)
        & (neutral >= 0.45)
    )

    # OpenCV hue for the observed Yosemite yellow/orange edge paint occupies
    # roughly 5..32, not a narrow band around pure yellow (30).  Keep the hue
    # gate explicit, then combine saturation/Lab evidence without multiplying
    # four sub-unit scores into near-zero confidence.
    hue_distance = np.abs(hue - 18.0)
    hue_distance = np.minimum(hue_distance, 180.0 - hue_distance)
    yellow_hue = np.clip(1.0 - hue_distance / 22.0, 0.0, 1.0).astype(np.float32)
    yellow_saturation = _linear_score(saturation, 0.10, 0.30)
    yellow_lab = _linear_score(lab_b, 0.030, 0.18)
    yellow_ridge = np.maximum(luma_ridge, chroma_ridge)
    yellow_color = np.sqrt(
        np.maximum(yellow_hue, 0.0)
        * np.maximum(np.maximum(yellow_saturation, yellow_lab), 0.0)
    ).astype(np.float32)
    yellow_confidence = (
        yellow_color * (0.45 + 0.55 * yellow_ridge) * visibility
    ).astype(np.float32)

    white_raw = road & (absolute_white | shadow_white) & (
        white_confidence >= selected.white_candidate_threshold
    )
    yellow_raw = road & (yellow_confidence >= selected.yellow_candidate_threshold)
    white_kept, white_components, white_rejected = _component_filter(
        white_raw,
        white_confidence,
        road,
        selected.white_candidate_threshold,
        selected,
    )
    yellow_kept, yellow_components, yellow_rejected = _component_filter(
        yellow_raw,
        yellow_confidence,
        road,
        selected.yellow_candidate_threshold,
        selected,
    )

    # Yellow wins only when its evidence is at least as strong.  This avoids
    # two labels for antialiased paint boundaries while preserving a neutral
    # white classification under warm illumination.
    choose_yellow = yellow_kept & (~white_kept | (yellow_confidence >= white_confidence))
    choose_white = white_kept & ~choose_yellow
    paint_class[choose_white] = int(RoadPaintClass.WHITE)
    paint_class[choose_yellow] = int(RoadPaintClass.YELLOW)
    confidence[choose_white] = white_confidence[choose_white]
    confidence[choose_yellow] = yellow_confidence[choose_yellow]
    confidence[~road] = 0.0
    candidate = paint_class != int(RoadPaintClass.UNKNOWN)

    # A frame whose proposed paint occupies an implausibly large share of its
    # semantic road is ambiguous (typically bright shoulder/asphalt texture),
    # not strong evidence.  Suppress the whole frame rather than select a
    # visually attractive subset that downstream temporal consensus could
    # incorrectly promote to driving truth.
    road_pixels = int(np.count_nonzero(road))
    paint_fraction = float(np.count_nonzero(candidate) / max(road_pixels, 1))
    frame_suppressed = paint_fraction > selected.maximum_frame_paint_road_fraction
    suppression_reason: str | None = None
    if frame_suppressed:
        suppression_reason = "candidate-paint-fraction-exceeds-fail-closed-limit"
        paint_class.fill(int(RoadPaintClass.UNKNOWN))
        confidence.fill(0.0)
        candidate.fill(False)
        choose_white.fill(False)
        choose_yellow.fill(False)

    candidate_values = confidence[candidate]
    examined = len(white_components) + len(yellow_components)
    rejected = white_rejected + yellow_rejected
    metrics: dict[str, object] = {
        "schema": ROAD_PAINT_SCHEMA,
        "targetWidth": width,
        "targetHeight": height,
        "roadPixels": road_pixels,
        "candidatePixels": int(np.count_nonzero(candidate)),
        "whitePixels": int(np.count_nonzero(choose_white)),
        "yellowPixels": int(np.count_nonzero(choose_yellow)),
        "paintFractionOfRoad": float(np.count_nonzero(candidate) / max(road_pixels, 1)),
        "preSuppressionPaintFractionOfRoad": paint_fraction,
        "frameSuppressed": frame_suppressed,
        "suppressionReason": suppression_reason,
        "confidence": {
            "meaning": "heuristic-evidence-score-not-probability",
            "p50": float(np.percentile(candidate_values, 50)) if candidate_values.size else 0.0,
            "p95": float(np.percentile(candidate_values, 95)) if candidate_values.size else 0.0,
        },
        "adaptiveLocalContrast": {
            "windowPixels": window,
            "lumaFloorP50": float(np.percentile(adaptive_luma_floor[road], 50)),
            "lumaFloorP95": float(np.percentile(adaptive_luma_floor[road], 95)),
        },
        "components": {
            "examined": examined,
            "kept": examined - rejected,
            "rejected": rejected,
            "minimumAreaPixels": max(
                2,
                int(
                    round(
                        selected.minimum_component_area_at_640x360
                        * math.sqrt((height * width) / float(640 * 360))
                    )
                ),
            ),
        },
    }
    provenance = _extraction_provenance(
        width,
        height,
        window,
        image_interpolation,
        mask_interpolation,
        selected,
    )
    return RoadPaintEvidence(
        paint_class=paint_class,
        candidate_mask=candidate,
        confidence=confidence,
        road_support=road,
        provenance=provenance,
        metrics=metrics,
    )


def _extraction_provenance(
    width: int,
    height: int,
    window: int,
    image_interpolation: str,
    mask_interpolation: str,
    config: RoadPaintConfig,
) -> dict[str, object]:
    return {
        "schema": ROAD_PAINT_SCHEMA,
        "method": "road-gated-absolute-color-local-ridge-thickness-components-v2",
        "deterministic": True,
        "pretrainedWeights": None,
        "inputEncoding": "display-referred-bgr-uint8-unlinearized",
        "targetResolution": {"width": width, "height": height},
        "resampling": {
            "image": image_interpolation,
            "semanticRoadMask": mask_interpolation,
        },
        "roadMaskContract": "all proposals and nonzero confidence are inside supplied road support",
        "localContrast": {
            "operator": "elliptical-morphological-tophat-plus-road-masked-local-statistics",
            "windowPixels": window,
        },
        "colorEvidence": ["opencv-lab-8bit", "opencv-hsv-8bit"],
        "confidenceMeaning": "heuristic-evidence-score-not-probability",
        "configuration": dataclasses.asdict(config),
        "references": [
            "https://arxiv.org/abs/1911.09054",
            "https://arxiv.org/abs/2003.08550",
            "https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html",
            "https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html",
        ],
    }


def _validate_evidence(evidence: RoadPaintEvidence, name: str) -> tuple[int, int]:
    candidate = np.asarray(evidence.candidate_mask)
    confidence = np.asarray(evidence.confidence)
    paint_class = np.asarray(evidence.paint_class)
    support = np.asarray(evidence.road_support)
    if candidate.ndim != 2:
        raise RoadPaintInputError(f"{name}.candidate_mask must be two-dimensional")
    shape = candidate.shape
    if confidence.shape != shape or paint_class.shape != shape or support.shape != shape:
        raise RoadPaintInputError(f"{name} evidence arrays must have identical shapes")
    if not np.isfinite(confidence).all():
        raise RoadPaintInputError(f"{name}.confidence must be finite")
    if np.any(confidence < 0.0) or np.any(confidence > 1.0):
        raise RoadPaintInputError(f"{name}.confidence must be in [0, 1]")
    if np.any(candidate.astype(bool) & ~support.astype(bool)):
        raise RoadPaintInputError(f"{name} contains paint proposals outside road support")
    known_classes = np.isin(
        paint_class,
        [int(RoadPaintClass.UNKNOWN), int(RoadPaintClass.WHITE), int(RoadPaintClass.YELLOW)],
    )
    if not np.all(known_classes):
        raise RoadPaintInputError(f"{name}.paint_class contains an unknown class identifier")
    return shape


def _validate_consensus_config(config: TemporalConsensusConfig) -> None:
    if config.minimum_observations < 2:
        raise RoadPaintInputError("minimum_observations must be at least 2")
    if config.minimum_agreeing_observations < 2:
        raise RoadPaintInputError("minimum_agreeing_observations must be at least 2")
    if config.minimum_agreeing_observations > config.minimum_observations:
        raise RoadPaintInputError(
            "minimum_agreeing_observations cannot exceed minimum_observations"
        )
    if not 0.5 <= config.minimum_agreement_ratio <= 1.0:
        raise RoadPaintInputError("minimum_agreement_ratio must be in [0.5, 1]")
    if not 0.0 <= config.minimum_source_proposal_confidence <= 1.0:
        raise RoadPaintInputError("minimum_source_proposal_confidence must be in [0, 1]")


def calibrated_multiframe_paint_consensus(
    reference: RoadPaintEvidence,
    observations: Sequence[RoadPaintEvidence],
    reference_to_observation_maps: Sequence[np.ndarray],
    *,
    config: TemporalConsensusConfig | None = None,
) -> RoadPaintConsensus:
    """Accept/reject reference proposals using calibrated dense warp maps.

    Every map has shape ``reference H x reference W x 2`` and stores
    ``(source_x, source_y)`` for the corresponding observation.  Nearest-
    neighbor sampling is intentional for categorical masks.  A valid mapped
    road pixel with no source proposal is a negative observation; an invalid
    map or a mapped non-road pixel provides no evidence and remains unknown.
    """

    selected = config or TemporalConsensusConfig()
    _validate_consensus_config(selected)
    reference_shape = _validate_evidence(reference, "reference")
    if len(observations) != len(reference_to_observation_maps):
        raise RoadPaintInputError("each observation requires exactly one correspondence map")

    proposal = np.asarray(reference.candidate_mask, dtype=bool)
    reference_support = np.asarray(reference.road_support, dtype=bool)
    reference_class = np.asarray(reference.paint_class, dtype=np.uint8)
    height, width = reference_shape
    observation_count = np.zeros(reference_shape, dtype=np.uint16)
    agreement_count = np.zeros(reference_shape, dtype=np.uint16)
    agreement_confidence_sum = np.zeros(reference_shape, dtype=np.float32)
    observation_count[proposal & reference_support] = 1
    agreement_count[proposal & reference_support] = 1
    agreement_confidence_sum[proposal & reference_support] = np.asarray(
        reference.confidence, dtype=np.float32
    )[proposal & reference_support]

    invalid_map_pixels = 0
    supported_warp_samples = 0
    for index, (observation, correspondence) in enumerate(
        zip(observations, reference_to_observation_maps)
    ):
        _validate_evidence(observation, f"observation[{index}]")
        warp = np.asarray(correspondence, dtype=np.float32)
        if warp.shape != (height, width, 2):
            raise RoadPaintInputError(
                f"correspondence[{index}] must have shape {(height, width, 2)}"
            )
        map_x = warp[:, :, 0]
        map_y = warp[:, :, 1]
        source_height, source_width = np.asarray(observation.candidate_mask).shape
        finite = np.isfinite(map_x) & np.isfinite(map_y)
        inside = (
            finite
            & (map_x >= -0.5)
            & (map_x <= source_width - 0.5)
            & (map_y >= -0.5)
            & (map_y <= source_height - 0.5)
        )
        invalid_map_pixels += int(np.count_nonzero(proposal & ~inside))
        safe_x = np.where(inside, map_x, 0.0).astype(np.float32)
        safe_y = np.where(inside, map_y, 0.0).astype(np.float32)
        source_support = cv2.remap(
            np.asarray(observation.road_support, dtype=np.uint8),
            safe_x,
            safe_y,
            interpolation=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ).astype(bool)
        valid_support = proposal & inside & source_support
        supported_warp_samples += int(np.count_nonzero(valid_support))
        observation_count[valid_support] += 1

        source_candidate = cv2.remap(
            np.asarray(observation.candidate_mask, dtype=np.uint8),
            safe_x,
            safe_y,
            interpolation=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ).astype(bool)
        source_confidence = cv2.remap(
            np.asarray(observation.confidence, dtype=np.float32),
            safe_x,
            safe_y,
            interpolation=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )
        agrees = valid_support & source_candidate & (
            source_confidence >= selected.minimum_source_proposal_confidence
        )
        if selected.require_same_color:
            source_class = cv2.remap(
                np.asarray(observation.paint_class, dtype=np.uint8),
                safe_x,
                safe_y,
                interpolation=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=int(RoadPaintClass.UNKNOWN),
            )
            agrees &= source_class == reference_class
        agreement_count[agrees] += 1
        agreement_confidence_sum[agrees] += source_confidence[agrees]

    ratio = agreement_count.astype(np.float32) / np.maximum(
        observation_count.astype(np.float32), 1.0
    )
    enough_support = proposal & (observation_count >= selected.minimum_observations)
    accepted = (
        enough_support
        & (agreement_count >= selected.minimum_agreeing_observations)
        & (ratio >= selected.minimum_agreement_ratio)
    )
    rejected = enough_support & ~accepted
    unsupported = proposal & ~enough_support
    decision = np.full(reference_shape, int(ConsensusDecision.UNKNOWN), dtype=np.uint8)
    decision[accepted] = int(ConsensusDecision.ACCEPTED)
    decision[rejected] = int(ConsensusDecision.REJECTED)
    decision_confidence = np.zeros(reference_shape, dtype=np.float32)
    decision_confidence[accepted] = (
        agreement_confidence_sum[accepted]
        / np.maximum(agreement_count[accepted].astype(np.float32), 1.0)
        * ratio[accepted]
    )
    decision_confidence[rejected] = 1.0 - ratio[rejected]

    proposed_count = int(np.count_nonzero(proposal))
    metrics: dict[str, object] = {
        "schema": ROAD_PAINT_CONSENSUS_SCHEMA,
        "proposedPixels": proposed_count,
        "acceptedPixels": int(np.count_nonzero(accepted)),
        "rejectedPixels": int(np.count_nonzero(rejected)),
        "unsupportedPixels": int(np.count_nonzero(unsupported)),
        "acceptedFractionOfProposals": float(np.count_nonzero(accepted) / max(proposed_count, 1)),
        "correspondenceMaps": len(reference_to_observation_maps),
        "invalidProposalMapSamples": invalid_map_pixels,
        "supportedWarpSamples": supported_warp_samples,
        "observationCountMaximum": int(np.max(observation_count)) if proposed_count else 0,
    }
    provenance: dict[str, object] = {
        "schema": ROAD_PAINT_CONSENSUS_SCHEMA,
        "method": "calibrated-dense-warp-repeat-observation-v1",
        "deterministic": True,
        "correspondenceConvention": "reference-pixel-to-observation-source-xy",
        "categoricalInterpolation": "nearest",
        "invalidOrNonRoadCorrespondence": "unsupported-unknown",
        "supportedNonProposalCorrespondence": "negative-observation",
        "confidenceMeaning": "repeatability-decision-score-not-probability",
        "configuration": dataclasses.asdict(selected),
        "referenceEvidenceSchema": reference.provenance.get("schema", "unknown"),
        "observationEvidenceSchemas": [
            item.provenance.get("schema", "unknown") for item in observations
        ],
    }
    return RoadPaintConsensus(
        decision=decision,
        accepted_mask=accepted,
        rejected_mask=rejected,
        confidence=decision_confidence,
        observation_count=observation_count,
        agreement_count=agreement_count,
        provenance=provenance,
        metrics=metrics,
    )


__all__ = [
    "ConsensusDecision",
    "ROAD_PAINT_CONSENSUS_SCHEMA",
    "ROAD_PAINT_SCHEMA",
    "RoadPaintClass",
    "RoadPaintConfig",
    "RoadPaintConsensus",
    "RoadPaintEvidence",
    "RoadPaintInputError",
    "TemporalConsensusConfig",
    "calibrated_multiframe_paint_consensus",
    "extract_road_paint_evidence",
]
