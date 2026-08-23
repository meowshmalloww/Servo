#!/usr/bin/env python3
"""Deterministic, fail-closed multi-view evidence for planar road signs.

This module consumes *already detected* sign regions, undistorted calibrated
cameras, semantic masks, and depth expressed in the same coordinate frame as
the camera translations.  It does not detect signs, run OCR, infer regulatory
meaning, or invent unseen pixels.  ``geometry-verified`` means only that at
least three sufficiently separated observations support one stable plane in
the supplied coordinate frame; it is not a collision-safety certificate.

The clean-room design follows the plane/homography geometry described by
Hartley and Zisserman, robust consensus fitting from Fischler and Bolles, and
the multi-view sign-plane formulation of Cui et al.  Rectification uses
OpenCV's documented perspective mapping with nearest-neighbour sampling so
every atlas pixel can be traced to one observed source pixel.  No source code
from those works is copied here.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import numpy as np


SIGN_EVIDENCE_SCHEMA = "servo.sign-evidence/v1"
SIGN_EVIDENCE_ALGORITHM = "servo-sign-plane-cleanroom/1.0.0"
CAMERA_CONVENTION = "camera-to-world; camera +x right, +y down, +z forward"
RESEARCH_REFERENCES = (
    "https://www.robots.ox.ac.uk/~vgg/hzbook/index.html",
    "https://graphics.stanford.edu/courses/cs164-10-spring/Handouts/papers_RANSAC.pdf",
    "https://docs.opencv.org/4.5.1/d9/dab/tutorial_homography.html",
    "https://docs.opencv.org/5.0/tutorials/features/akaze_tracking/akaze_tracking.html",
    "https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-ipr.2019.0023",
    "https://doi.org/10.1117/1.2931461",
    "https://colmap.github.io/format.html",
)


class SignEvidenceError(ValueError):
    """Raised when evidence is malformed or geometrically under-specified."""


class GeometryState(str, Enum):
    UNVERIFIED = "unverified"
    GEOMETRY_VERIFIED = "geometry-verified"


class ClaimState(str, Enum):
    UNVERIFIED = "unverified"
    CROSS_VIEW_VERIFIED = "cross-view-verified"


@dataclasses.dataclass(frozen=True)
class SignEvidenceProvenance:
    """Required provenance shared by every observation in one build.

    Depth may be arbitrary scale, but it must already be aligned to the same
    coordinate frame as ``camera_to_world``.  Per-frame unaligned monocular
    depth is intentionally not accepted.
    """

    sequence_id: str
    coordinate_frame_id: str
    scale_provenance: Literal["sfm-arbitrary-scale", "metric-anchored"]
    camera_source: str
    depth_source: str
    semantic_source: str
    candidate_source: str
    distortion_state: Literal["undistorted"] = "undistorted"
    depth_alignment: Literal["camera-z-in-coordinate-frame"] = "camera-z-in-coordinate-frame"
    contains_generated_pixels: bool = False
    source_hashes: tuple[tuple[str, str], ...] = ()

    def validate(self) -> None:
        for name in (
            "sequence_id",
            "coordinate_frame_id",
            "camera_source",
            "depth_source",
            "semantic_source",
            "candidate_source",
        ):
            if not getattr(self, name).strip():
                raise SignEvidenceError(f"provenance {name} must not be empty")
        if self.scale_provenance not in {"sfm-arbitrary-scale", "metric-anchored"}:
            raise SignEvidenceError("unsupported scale provenance")
        if self.distortion_state != "undistorted":
            raise SignEvidenceError("sign evidence requires undistorted imagery")
        if self.depth_alignment != "camera-z-in-coordinate-frame":
            raise SignEvidenceError("depth must be camera-Z aligned to the camera coordinate frame")
        if self.contains_generated_pixels:
            raise SignEvidenceError("generated pixels cannot be sign evidence")
        if len({name for name, _ in self.source_hashes}) != len(self.source_hashes):
            raise SignEvidenceError("source hash names must be unique")
        for name, digest in self.source_hashes:
            if not name.strip() or not digest.startswith("sha256:") or len(digest) != 71:
                raise SignEvidenceError("source hashes must be named sha256 digests")


@dataclasses.dataclass(frozen=True)
class ExternalRecognition:
    """Optional output from an external OCR/classifier, never generated here."""

    engine_id: str
    engine_revision: str
    confidence: float
    regulatory_class: str | None = None
    text: str | None = None


@dataclasses.dataclass(frozen=True)
class SignCandidate:
    """One calibrated sign observation.

    ``box_xyxy`` is expressed in full, undistorted image coordinates.  The
    crop may be resized; its pixel centres are mapped affinely back into that
    box.  ``depth_crop`` stores positive camera-space Z in the same coordinate
    frame/scale as the camera translations.  ``candidate_mask`` selects the
    physical sign inside the crop, while ``observed_mask`` marks pixels that
    genuinely came from the sensor image.
    """

    candidate_id: str
    frame_id: str
    frame_index: int
    box_xyxy: tuple[float, float, float, float]
    crop_bgr: np.ndarray = dataclasses.field(repr=False)
    candidate_mask: np.ndarray = dataclasses.field(repr=False)
    semantic_crop: np.ndarray = dataclasses.field(repr=False)
    depth_crop: np.ndarray = dataclasses.field(repr=False)
    calibration: np.ndarray = dataclasses.field(repr=False)
    camera_to_world: np.ndarray = dataclasses.field(repr=False)
    observed_mask: np.ndarray | None = dataclasses.field(default=None, repr=False)
    confidence_crop: np.ndarray | None = dataclasses.field(default=None, repr=False)
    recognition: ExternalRecognition | None = None


@dataclasses.dataclass(frozen=True)
class SignEvidenceConfig:
    minimum_views: int = 3
    minimum_nonadjacent_gap: int = 2
    minimum_sign_fraction: float = 0.85
    maximum_forbidden_fraction: float = 0.05
    minimum_depth_coverage: float = 0.70
    candidate_plane_threshold_ratio: float = 0.025
    candidate_plane_minimum_inlier_ratio: float = 0.80
    association_centroid_ratio: float = 0.45
    association_normal_degrees: float = 25.0
    association_scale_ratio: float = 2.5
    global_plane_threshold_ratio: float = 0.025
    global_plane_minimum_inlier_ratio: float = 0.85
    maximum_centroid_dispersion_ratio: float = 0.25
    maximum_normal_p95_degrees: float = 18.0
    minimum_camera_baseline_ratio: float = 0.03
    recognition_minimum_confidence: float = 0.80
    atlas_max_dimension: int = 512
    maximum_points_per_observation: int = 384

    def validate(self) -> None:
        if self.minimum_views < 3:
            raise SignEvidenceError("minimum_views cannot be below three")
        if self.minimum_nonadjacent_gap < 2:
            raise SignEvidenceError("nonadjacent frame gap cannot be below two")
        for name in (
            "minimum_sign_fraction",
            "maximum_forbidden_fraction",
            "minimum_depth_coverage",
            "candidate_plane_minimum_inlier_ratio",
            "global_plane_minimum_inlier_ratio",
            "recognition_minimum_confidence",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise SignEvidenceError(f"{name} must be within [0, 1]")
        for name in (
            "candidate_plane_threshold_ratio",
            "association_centroid_ratio",
            "association_normal_degrees",
            "association_scale_ratio",
            "global_plane_threshold_ratio",
            "maximum_centroid_dispersion_ratio",
            "maximum_normal_p95_degrees",
            "minimum_camera_baseline_ratio",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0:
                raise SignEvidenceError(f"{name} must be positive and finite")
        if self.atlas_max_dimension < 16 or self.maximum_points_per_observation < 32:
            raise SignEvidenceError("atlas/point limits are too small")


@dataclasses.dataclass(frozen=True)
class PlaneFit:
    normal: np.ndarray = dataclasses.field(repr=False)
    offset: float
    center: np.ndarray = dataclasses.field(repr=False)
    scale: float
    sample_count: int
    inlier_count: int
    inlier_ratio: float
    p95_inlier_residual_ratio: float
    inlier_mask: np.ndarray = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class ObservationEvidence:
    candidate: SignCandidate = dataclasses.field(repr=False)
    state: GeometryState
    reasons: tuple[str, ...]
    evidence_sha256: str
    sign_fraction: float
    forbidden_fraction: float
    depth_coverage: float
    sharpness: float
    camera_center: np.ndarray | None = dataclasses.field(default=None, repr=False)
    points_world: np.ndarray | None = dataclasses.field(default=None, repr=False)
    plane: PlaneFit | None = dataclasses.field(default=None, repr=False)


@dataclasses.dataclass(frozen=True)
class RecognitionClaim:
    state: ClaimState
    value: str | None
    supporting_observations: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RectifiedFusion:
    """Traceable atlas: each RGB output pixel comes from one sensor pixel."""

    bgr: np.ndarray = dataclasses.field(repr=False)
    valid_mask: np.ndarray = dataclasses.field(repr=False)
    support_count: np.ndarray = dataclasses.field(repr=False)
    source_observation_slot: np.ndarray = dataclasses.field(repr=False)
    observation_order: tuple[str, ...]
    plane_bounds: tuple[float, float, float, float]
    sampling: Literal["nearest-observed-pixel"] = "nearest-observed-pixel"
    generated_pixels: bool = False


@dataclasses.dataclass(frozen=True)
class SignTrackEvidence:
    track_id: str
    state: GeometryState
    reasons: tuple[str, ...]
    observation_ids: tuple[str, ...]
    selected_observation_ids: tuple[str, ...]
    plane: PlaneFit | None = dataclasses.field(repr=False)
    camera_baseline_ratio: float
    centroid_dispersion_ratio: float
    normal_p95_degrees: float
    regulatory_class: RecognitionClaim
    text: RecognitionClaim
    fusion: RectifiedFusion | None = dataclasses.field(default=None, repr=False)


@dataclasses.dataclass(frozen=True)
class SignEvidenceBundle:
    provenance: SignEvidenceProvenance
    config: SignEvidenceConfig
    observations: tuple[ObservationEvidence, ...]
    tracks: tuple[SignTrackEvidence, ...]

    def manifest(self) -> dict[str, Any]:
        import cv2

        manifest: dict[str, Any] = {
            "schema": SIGN_EVIDENCE_SCHEMA,
            "algorithm": SIGN_EVIDENCE_ALGORITHM,
            "runtime": {"numpy": np.__version__, "opencv": cv2.__version__},
            "cameraConvention": CAMERA_CONVENTION,
            "provenance": _json_dataclass(self.provenance),
            "config": _json_dataclass(self.config),
            "researchReferences": list(RESEARCH_REFERENCES),
            "safety": {
                "collisionReady": False,
                "metricGeometry": self.provenance.scale_provenance == "metric-anchored",
                "containsGeneratedPixels": False,
                "geometryVerificationDoesNotVerifyRegulatoryMeaning": True,
            },
            "observations": [],
            "tracks": [],
        }
        for item in self.observations:
            plane = _plane_manifest(item.plane)
            manifest["observations"].append(
                {
                    "candidateId": item.candidate.candidate_id,
                    "frameId": item.candidate.frame_id,
                    "frameIndex": item.candidate.frame_index,
                    "state": item.state.value,
                    "reasons": list(item.reasons),
                    "evidenceSha256": item.evidence_sha256,
                    "signFraction": item.sign_fraction,
                    "forbiddenFraction": item.forbidden_fraction,
                    "depthCoverage": item.depth_coverage,
                    "sharpness": item.sharpness,
                    "plane": plane,
                }
            )
        for track in self.tracks:
            fusion = None
            if track.fusion is not None:
                fusion = {
                    "shape": list(track.fusion.bgr.shape),
                    "validFraction": float(np.mean(track.fusion.valid_mask)),
                    "maximumSupport": int(np.max(track.fusion.support_count, initial=0)),
                    "observationOrder": list(track.fusion.observation_order),
                    "planeBounds": list(track.fusion.plane_bounds),
                    "sampling": track.fusion.sampling,
                    "generatedPixels": track.fusion.generated_pixels,
                    "bgrSha256": _array_sha256(track.fusion.bgr),
                    "validMaskSha256": _array_sha256(track.fusion.valid_mask),
                    "sourceMapSha256": _array_sha256(track.fusion.source_observation_slot),
                }
            manifest["tracks"].append(
                {
                    "trackId": track.track_id,
                    "state": track.state.value,
                    "reasons": list(track.reasons),
                    "observationIds": list(track.observation_ids),
                    "selectedObservationIds": list(track.selected_observation_ids),
                    "cameraBaselineRatio": track.camera_baseline_ratio,
                    "centroidDispersionRatio": track.centroid_dispersion_ratio,
                    "normalP95Degrees": track.normal_p95_degrees,
                    "plane": _plane_manifest(track.plane),
                    "regulatoryClass": _claim_manifest(track.regulatory_class),
                    "text": _claim_manifest(track.text),
                    "fusion": fusion,
                }
            )
        return manifest


_SIGN_LABELS = frozenset({12, 13, 14})
_FORBIDDEN_LABELS = frozenset({1, 2, 5, 17, 18, 19, 20, 21, 22})


def _json_dataclass(value: Any) -> dict[str, Any]:
    result = dataclasses.asdict(value)
    if "source_hashes" in result:
        result["source_hashes"] = {key: digest for key, digest in value.source_hashes}
    return result


def _array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
    digest.update(array.tobytes())
    return "sha256:" + digest.hexdigest()


def _candidate_sha256(candidate: SignCandidate) -> str:
    digest = hashlib.sha256()
    metadata = {
        "candidateId": candidate.candidate_id,
        "frameId": candidate.frame_id,
        "frameIndex": candidate.frame_index,
        "box": candidate.box_xyxy,
    }
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for array in (
        candidate.crop_bgr,
        candidate.candidate_mask,
        candidate.semantic_crop,
        candidate.depth_crop,
        candidate.calibration,
        candidate.camera_to_world,
    ):
        digest.update(_array_sha256(np.asarray(array)).encode("ascii"))
    if candidate.observed_mask is not None:
        digest.update(_array_sha256(np.asarray(candidate.observed_mask)).encode("ascii"))
    if candidate.confidence_crop is not None:
        digest.update(_array_sha256(np.asarray(candidate.confidence_crop)).encode("ascii"))
    if candidate.recognition is not None:
        digest.update(
            json.dumps(
                dataclasses.asdict(candidate.recognition),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    return "sha256:" + digest.hexdigest()


def _plane_manifest(plane: PlaneFit | None) -> dict[str, Any] | None:
    if plane is None:
        return None
    return {
        "normal": [float(value) for value in plane.normal],
        "offset": plane.offset,
        "center": [float(value) for value in plane.center],
        "scale": plane.scale,
        "sampleCount": plane.sample_count,
        "inlierCount": plane.inlier_count,
        "inlierRatio": plane.inlier_ratio,
        "p95InlierResidualRatio": plane.p95_inlier_residual_ratio,
    }


def _claim_manifest(claim: RecognitionClaim) -> dict[str, Any]:
    return {
        "state": claim.state.value,
        "value": claim.value,
        "supportingObservations": list(claim.supporting_observations),
        "reasons": list(claim.reasons),
    }


def _validate_candidate(candidate: SignCandidate) -> tuple[np.ndarray, np.ndarray]:
    if not candidate.candidate_id.strip() or not candidate.frame_id.strip():
        raise SignEvidenceError("candidate/frame identifiers must not be empty")
    if candidate.frame_index < 0:
        raise SignEvidenceError("frame_index must not be negative")
    crop = np.asarray(candidate.crop_bgr)
    if crop.ndim != 3 or crop.shape[2] != 3 or crop.dtype != np.uint8:
        raise SignEvidenceError("crop_bgr must be an HxWx3 uint8 image")
    shape = crop.shape[:2]
    candidate_mask = np.asarray(candidate.candidate_mask, dtype=bool)
    semantic = np.asarray(candidate.semantic_crop)
    depth = np.asarray(candidate.depth_crop, dtype=np.float64)
    if candidate_mask.shape != shape or semantic.shape != shape or depth.shape != shape:
        raise SignEvidenceError("candidate mask, semantics, and depth must match the crop")
    if not np.any(candidate_mask):
        raise SignEvidenceError("candidate_mask must contain observed candidate pixels")
    observed = candidate_mask if candidate.observed_mask is None else np.asarray(candidate.observed_mask, dtype=bool)
    if observed.shape != shape:
        raise SignEvidenceError("observed_mask must match the crop")
    if np.any(candidate_mask & ~observed):
        raise SignEvidenceError("candidate_mask cannot claim unobserved pixels")
    if candidate.confidence_crop is not None:
        confidence = np.asarray(candidate.confidence_crop, dtype=np.float64)
        if confidence.shape != shape or np.any(~np.isfinite(confidence)) or np.any((confidence < 0) | (confidence > 1)):
            raise SignEvidenceError("confidence_crop must be finite [0,1] and match the crop")
    box = np.asarray(candidate.box_xyxy, dtype=np.float64)
    if box.shape != (4,) or not np.isfinite(box).all() or box[2] <= box[0] or box[3] <= box[1]:
        raise SignEvidenceError("box_xyxy must be a finite positive-area box")
    calibration = np.asarray(candidate.calibration, dtype=np.float64)
    if calibration.shape != (3, 3) or not np.isfinite(calibration).all():
        raise SignEvidenceError("calibration must be a finite 3x3 matrix")
    if calibration[0, 0] <= 0 or calibration[1, 1] <= 0 or abs(np.linalg.det(calibration)) <= 1e-12:
        raise SignEvidenceError("calibration must have positive focal lengths and full rank")
    if not np.allclose(calibration[2], [0.0, 0.0, 1.0], atol=1e-10):
        raise SignEvidenceError("calibration must use the pinhole camera-Z convention")
    pose = np.asarray(candidate.camera_to_world, dtype=np.float64)
    if pose.shape != (4, 4) or not np.isfinite(pose).all() or not np.allclose(pose[3], [0, 0, 0, 1], atol=1e-8):
        raise SignEvidenceError("camera_to_world must be a finite rigid 4x4 transform")
    rotation = pose[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=2e-4) or not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=2e-4):
        raise SignEvidenceError("camera_to_world rotation must be right-handed and orthonormal")
    if candidate.recognition is not None:
        recognition = candidate.recognition
        if not recognition.engine_id.strip() or not recognition.engine_revision.strip():
            raise SignEvidenceError("external recognition requires engine identity and revision")
        if not math.isfinite(recognition.confidence) or not 0.0 <= recognition.confidence <= 1.0:
            raise SignEvidenceError("external recognition confidence must be within [0,1]")
    return candidate_mask, observed


def _pixel_coordinates(candidate: SignCandidate) -> tuple[np.ndarray, np.ndarray]:
    height, width = candidate.crop_bgr.shape[:2]
    x0, y0, x1, y1 = candidate.box_xyxy
    x = x0 + (np.arange(width, dtype=np.float64) + 0.5) * ((x1 - x0) / width)
    y = y0 + (np.arange(height, dtype=np.float64) + 0.5) * ((y1 - y0) / height)
    return np.meshgrid(x, y)


def _even_subsample(mask: np.ndarray, maximum: int) -> np.ndarray:
    indices = np.flatnonzero(mask.ravel())
    if len(indices) <= maximum:
        return indices
    selection = np.linspace(0, len(indices) - 1, maximum, dtype=np.int64)
    return indices[selection]


def _unproject_candidate(candidate: SignCandidate, valid: np.ndarray, maximum: int) -> np.ndarray:
    flat_indices = _even_subsample(valid, maximum)
    if len(flat_indices) < 12:
        raise SignEvidenceError("candidate has fewer than twelve valid depth samples")
    x_grid, y_grid = _pixel_coordinates(candidate)
    pixels = np.column_stack(
        (x_grid.ravel()[flat_indices], y_grid.ravel()[flat_indices], np.ones(len(flat_indices)))
    )
    rays = pixels @ np.linalg.inv(np.asarray(candidate.calibration, dtype=np.float64)).T
    depth = np.asarray(candidate.depth_crop, dtype=np.float64).ravel()[flat_indices]
    camera = rays * (depth / rays[:, 2])[:, None]
    pose = np.asarray(candidate.camera_to_world, dtype=np.float64)
    return camera @ pose[:3, :3].T + pose[:3, 3]


def _robust_extent(points: np.ndarray) -> float:
    low, high = np.percentile(points, [5.0, 95.0], axis=0)
    return max(float(np.linalg.norm(high - low)), np.finfo(np.float64).eps)


def _fit_plane(points: np.ndarray, threshold_ratio: float, minimum_inlier_ratio: float) -> PlaneFit:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 12 or not np.isfinite(points).all():
        raise SignEvidenceError("plane fitting requires at least twelve finite 3D points")
    scale = _robust_extent(points)
    threshold = max(scale * threshold_ratio, 1e-9)
    candidate_indices = _even_subsample(np.ones(len(points), dtype=bool), min(len(points), 72))
    rng = np.random.default_rng(0x53_49_47_4E)
    hypotheses: list[tuple[int, float, tuple[int, int, int], np.ndarray]] = []
    seen: set[tuple[int, int, int]] = set()
    maximum_hypotheses = min(768, max(96, len(candidate_indices) * 8))
    while len(seen) < maximum_hypotheses:
        chosen = tuple(sorted(int(value) for value in rng.choice(candidate_indices, 3, replace=False)))
        if chosen in seen:
            if len(seen) >= math.comb(len(candidate_indices), 3):
                break
            continue
        seen.add(chosen)
        first, second, third = points[list(chosen)]
        normal = np.cross(second - first, third - first)
        length = float(np.linalg.norm(normal))
        if length <= scale * 1e-7:
            continue
        normal /= length
        distances = np.abs((points - first) @ normal)
        inlier = distances <= threshold
        count = int(np.count_nonzero(inlier))
        median = float(np.median(distances[inlier])) if count else math.inf
        hypotheses.append((-count, median, chosen, inlier))
    if not hypotheses:
        raise SignEvidenceError("plane samples are degenerate")
    hypotheses.sort(key=lambda item: (item[0], item[1], item[2]))
    inlier = hypotheses[0][3]
    if float(np.mean(inlier)) < minimum_inlier_ratio:
        raise SignEvidenceError("depth is not sufficiently planar")
    center = np.mean(points[inlier], axis=0)
    _, singular, vh = np.linalg.svd(points[inlier] - center, full_matrices=False)
    if singular[1] <= scale * 1e-5:
        raise SignEvidenceError("plane support is effectively one-dimensional")
    normal = vh[-1]
    normal /= np.linalg.norm(normal)
    residual = np.abs((points - center) @ normal)
    refined = residual <= threshold
    if float(np.mean(refined)) < minimum_inlier_ratio:
        raise SignEvidenceError("refined plane lost required support")
    center = np.mean(points[refined], axis=0)
    _, singular, vh = np.linalg.svd(points[refined] - center, full_matrices=False)
    if singular[1] <= scale * 1e-5:
        raise SignEvidenceError("refined plane support is one-dimensional")
    normal = vh[-1] / np.linalg.norm(vh[-1])
    residual = np.abs((points - center) @ normal)
    inlier = residual <= threshold
    p95 = float(np.percentile(residual[inlier], 95.0) / scale)
    return PlaneFit(
        normal=normal,
        offset=-float(np.dot(normal, center)),
        center=center,
        scale=scale,
        sample_count=len(points),
        inlier_count=int(np.count_nonzero(inlier)),
        inlier_ratio=float(np.mean(inlier)),
        p95_inlier_residual_ratio=p95,
        inlier_mask=inlier,
    )


def _sharpness(crop: np.ndarray, mask: np.ndarray) -> float:
    import cv2

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    canonical = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_AREA)
    canonical_mask = cv2.resize(mask.astype(np.uint8), (96, 96), interpolation=cv2.INTER_NEAREST) > 0
    gradient_x = cv2.Sobel(canonical, cv2.CV_64F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(canonical, cv2.CV_64F, 0, 1, ksize=3)
    values = gradient_x[canonical_mask] ** 2 + gradient_y[canonical_mask] ** 2
    return float(np.mean(values)) if values.size else 0.0


def evaluate_observation(candidate: SignCandidate, config: SignEvidenceConfig) -> ObservationEvidence:
    candidate_mask, observed = _validate_candidate(candidate)
    semantic = np.asarray(candidate.semantic_crop)
    labels = semantic[candidate_mask]
    sign_fraction = float(np.mean(np.isin(labels, tuple(_SIGN_LABELS))))
    forbidden_fraction = float(np.mean(np.isin(labels, tuple(_FORBIDDEN_LABELS))))
    depth = np.asarray(candidate.depth_crop, dtype=np.float64)
    valid_depth = candidate_mask & observed & np.isfinite(depth) & (depth > 0)
    if candidate.confidence_crop is not None:
        valid_depth &= np.asarray(candidate.confidence_crop, dtype=np.float64) > 0
    depth_coverage = float(np.count_nonzero(valid_depth) / np.count_nonzero(candidate_mask))
    sharpness = _sharpness(candidate.crop_bgr, candidate_mask & observed)
    reasons: list[str] = []
    if sign_fraction < config.minimum_sign_fraction:
        reasons.append("insufficient-sign-semantics")
    if forbidden_fraction > config.maximum_forbidden_fraction:
        reasons.append("sky-road-or-dynamic-contamination")
    if depth_coverage < config.minimum_depth_coverage:
        reasons.append("insufficient-positive-depth")
    points: np.ndarray | None = None
    plane: PlaneFit | None = None
    if not reasons:
        try:
            points = _unproject_candidate(candidate, valid_depth, config.maximum_points_per_observation)
            plane = _fit_plane(
                points,
                config.candidate_plane_threshold_ratio,
                config.candidate_plane_minimum_inlier_ratio,
            )
            camera_center = np.asarray(candidate.camera_to_world, dtype=np.float64)[:3, 3]
            if float(np.dot(plane.normal, camera_center - plane.center)) < 0:
                plane = dataclasses.replace(
                    plane,
                    normal=-plane.normal,
                    offset=-plane.offset,
                )
        except (SignEvidenceError, np.linalg.LinAlgError) as error:
            reasons.append("inconsistent-depth-plane:" + str(error))
            points = None
            plane = None
    return ObservationEvidence(
        candidate=candidate,
        state=GeometryState.UNVERIFIED,
        reasons=tuple(reasons),
        evidence_sha256=_candidate_sha256(candidate),
        sign_fraction=sign_fraction,
        forbidden_fraction=forbidden_fraction,
        depth_coverage=depth_coverage,
        sharpness=sharpness,
        camera_center=np.asarray(candidate.camera_to_world, dtype=np.float64)[:3, 3],
        points_world=points,
        plane=plane,
    )


def _compatible(first: ObservationEvidence, second: ObservationEvidence, config: SignEvidenceConfig) -> bool:
    if first.plane is None or second.plane is None:
        return False
    scale_ratio = max(first.plane.scale, second.plane.scale) / min(first.plane.scale, second.plane.scale)
    if scale_ratio > config.association_scale_ratio:
        return False
    normal_similarity = abs(float(np.dot(first.plane.normal, second.plane.normal)))
    if normal_similarity < math.cos(math.radians(config.association_normal_degrees)):
        return False
    distance = float(np.linalg.norm(first.plane.center - second.plane.center))
    return distance <= config.association_centroid_ratio * min(first.plane.scale, second.plane.scale)


def _cluster_observations(
    observations: Sequence[ObservationEvidence], config: SignEvidenceConfig
) -> list[list[ObservationEvidence]]:
    valid = sorted(
        (item for item in observations if item.plane is not None and not item.reasons),
        key=lambda item: (item.candidate.frame_index, item.candidate.frame_id, item.candidate.candidate_id),
    )
    parent = list(range(len(valid)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first_index in range(len(valid)):
        for second_index in range(first_index + 1, len(valid)):
            if _compatible(valid[first_index], valid[second_index], config):
                first_root, second_root = root(first_index), root(second_index)
                if first_root != second_root:
                    parent[max(first_root, second_root)] = min(first_root, second_root)
    clusters: dict[int, list[ObservationEvidence]] = {}
    for index, item in enumerate(valid):
        clusters.setdefault(root(index), []).append(item)
    # Split accidental union-find chains with a deterministic complete-link pass.
    result: list[list[ObservationEvidence]] = []
    for values in clusters.values():
        complete: list[list[ObservationEvidence]] = []
        for value in values:
            destination = next(
                (cluster for cluster in complete if all(_compatible(value, other, config) for other in cluster)),
                None,
            )
            if destination is None:
                complete.append([value])
            else:
                destination.append(value)
        result.extend(complete)
    return result


def _unique_best_views(cluster: Sequence[ObservationEvidence]) -> list[ObservationEvidence]:
    best: dict[str, ObservationEvidence] = {}
    for item in cluster:
        previous = best.get(item.candidate.frame_id)
        if previous is None or (-item.sharpness, item.candidate.candidate_id) < (
            -previous.sharpness,
            previous.candidate.candidate_id,
        ):
            best[item.candidate.frame_id] = item
    return sorted(best.values(), key=lambda item: (item.candidate.frame_index, item.candidate.frame_id))


def _cross_view_claim(
    observations: Sequence[ObservationEvidence],
    field: Literal["regulatory_class", "text"],
    config: SignEvidenceConfig,
) -> RecognitionClaim:
    accepted: list[tuple[ObservationEvidence, str]] = []
    for item in observations:
        recognition = item.candidate.recognition
        if recognition is None or recognition.confidence < config.recognition_minimum_confidence:
            continue
        raw = getattr(recognition, field)
        if raw is None or not raw.strip():
            continue
        value = " ".join(raw.strip().upper().split())
        accepted.append((item, value))
    if len(accepted) < config.minimum_views:
        return RecognitionClaim(ClaimState.UNVERIFIED, None, (), ("fewer-than-three-external-views",))
    values = {value for _, value in accepted}
    if len(values) != 1:
        return RecognitionClaim(ClaimState.UNVERIFIED, None, (), ("external-cross-view-disagreement",))
    indices = [item.candidate.frame_index for item, _ in accepted]
    if max(indices) - min(indices) < config.minimum_nonadjacent_gap:
        return RecognitionClaim(ClaimState.UNVERIFIED, None, (), ("no-nonadjacent-external-view",))
    return RecognitionClaim(
        ClaimState.CROSS_VIEW_VERIFIED,
        next(iter(values)),
        tuple(item.candidate.candidate_id for item, _ in accepted),
        (),
    )


def _plane_basis(plane: PlaneFit, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    centered = points - plane.center
    projected = centered - np.outer(centered @ plane.normal, plane.normal)
    _, singular, vh = np.linalg.svd(projected, full_matrices=False)
    if singular[1] <= plane.scale * 1e-6:
        raise SignEvidenceError("sign plane has no stable two-dimensional extent")
    first = vh[0] - np.dot(vh[0], plane.normal) * plane.normal
    first /= np.linalg.norm(first)
    second = np.cross(plane.normal, first)
    second /= np.linalg.norm(second)
    # Resolve SVD sign ambiguity for deterministic manifests.
    dominant = int(np.argmax(np.abs(first)))
    if first[dominant] < 0:
        first, second = -first, -second
    coordinates = np.column_stack((centered @ first, centered @ second))
    return first, second, coordinates


def _project_world(candidate: SignCandidate, world: np.ndarray) -> np.ndarray:
    pose = np.asarray(candidate.camera_to_world, dtype=np.float64)
    camera = (world - pose[:3, 3]) @ pose[:3, :3]
    if np.any(camera[:, 2] <= 1e-8):
        raise SignEvidenceError("rectification plane is behind a source camera")
    image = camera @ np.asarray(candidate.calibration, dtype=np.float64).T
    return image[:, :2] / image[:, 2:3]


def _rectified_fusion(
    observations: Sequence[ObservationEvidence], plane: PlaneFit, config: SignEvidenceConfig
) -> RectifiedFusion:
    import cv2

    points = np.concatenate(
        [item.points_world[item.plane.inlier_mask] for item in observations if item.points_world is not None and item.plane is not None],
        axis=0,
    )
    axis_u, axis_v, coordinates = _plane_basis(plane, points)
    u0, v0 = np.percentile(coordinates, 2.0, axis=0)
    u1, v1 = np.percentile(coordinates, 98.0, axis=0)
    if u1 <= u0 or v1 <= v0:
        raise SignEvidenceError("rectified sign bounds are degenerate")
    ranked = sorted(observations, key=lambda item: (-item.sharpness, item.candidate.candidate_id))
    best_height, best_width = ranked[0].candidate.crop_bgr.shape[:2]
    aspect = (u1 - u0) / (v1 - v0)
    if aspect >= 1.0:
        width = min(config.atlas_max_dimension, max(16, best_width))
        height = max(16, round(width / aspect))
    else:
        height = min(config.atlas_max_dimension, max(16, best_height))
        width = max(16, round(height * aspect))
    corners_world = np.asarray(
        [
            plane.center + u0 * axis_u + v0 * axis_v,
            plane.center + u1 * axis_u + v0 * axis_v,
            plane.center + u1 * axis_u + v1 * axis_v,
            plane.center + u0 * axis_u + v1 * axis_v,
        ],
        dtype=np.float64,
    )
    destination = np.asarray([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    atlas = np.zeros((height, width, 3), dtype=np.uint8)
    valid = np.zeros((height, width), dtype=bool)
    support = np.zeros((height, width), dtype=np.uint16)
    source_slot = np.full((height, width), -1, dtype=np.int16)
    for slot, item in enumerate(ranked):
        candidate = item.candidate
        image_corners = _project_world(candidate, corners_world)
        x0, y0, x1, y1 = candidate.box_xyxy
        crop_height, crop_width = candidate.crop_bgr.shape[:2]
        crop_corners = np.column_stack(
            (
                (image_corners[:, 0] - x0) * crop_width / (x1 - x0) - 0.5,
                (image_corners[:, 1] - y0) * crop_height / (y1 - y0) - 0.5,
            )
        ).astype(np.float32)
        transform = cv2.getPerspectiveTransform(crop_corners, destination)
        observed = (
            np.asarray(candidate.candidate_mask, dtype=bool)
            & (np.asarray(candidate.observed_mask, dtype=bool) if candidate.observed_mask is not None else True)
        ).astype(np.uint8)
        warped_mask = cv2.warpPerspective(
            observed,
            transform,
            (width, height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ) > 0
        warped = cv2.warpPerspective(
            candidate.crop_bgr,
            transform,
            (width, height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        support = np.minimum(np.iinfo(np.uint16).max, support.astype(np.uint32) + warped_mask).astype(np.uint16)
        fill = warped_mask & ~valid
        atlas[fill] = warped[fill]
        source_slot[fill] = slot
        valid |= warped_mask
    atlas[~valid] = 0
    return RectifiedFusion(
        bgr=atlas,
        valid_mask=valid,
        support_count=support,
        source_observation_slot=source_slot,
        observation_order=tuple(item.candidate.candidate_id for item in ranked),
        plane_bounds=(float(u0), float(v0), float(u1), float(v1)),
    )


def _build_track(
    track_index: int, cluster: Sequence[ObservationEvidence], config: SignEvidenceConfig
) -> SignTrackEvidence:
    views = _unique_best_views(cluster)
    reasons: list[str] = []
    if len(views) < config.minimum_views:
        reasons.append("fewer-than-three-unique-views")
    frame_indices = [item.candidate.frame_index for item in views]
    if not frame_indices or max(frame_indices) - min(frame_indices) < config.minimum_nonadjacent_gap:
        reasons.append("no-nonadjacent-view")
    median_scale = float(np.median([item.plane.scale for item in views])) if views else 1.0
    centers = np.asarray([item.plane.center for item in views], dtype=np.float64) if views else np.empty((0, 3))
    cameras = np.asarray([item.camera_center for item in views], dtype=np.float64) if views else np.empty((0, 3))
    if len(views) >= 2:
        pairwise_camera = np.linalg.norm(cameras[:, None, :] - cameras[None, :, :], axis=2)
        baseline_ratio = float(np.max(pairwise_camera) / median_scale)
        robust_center = np.median(centers, axis=0)
        centroid_dispersion = float(np.percentile(np.linalg.norm(centers - robust_center, axis=1), 95.0) / median_scale)
    else:
        baseline_ratio = 0.0
        centroid_dispersion = 0.0
    if baseline_ratio < config.minimum_camera_baseline_ratio:
        reasons.append("insufficient-camera-baseline")
    if centroid_dispersion > config.maximum_centroid_dispersion_ratio:
        reasons.append("inconsistent-sign-centroids")
    reference_normal = views[0].plane.normal if views else np.asarray([0.0, 0.0, 1.0])
    normal_angles = [
        math.degrees(math.acos(np.clip(abs(float(np.dot(reference_normal, item.plane.normal))), 0.0, 1.0)))
        for item in views
    ]
    normal_p95 = float(np.percentile(normal_angles, 95.0)) if normal_angles else 0.0
    if normal_p95 > config.maximum_normal_p95_degrees:
        reasons.append("inconsistent-sign-plane-normals")
    plane: PlaneFit | None = None
    fusion: RectifiedFusion | None = None
    if not reasons:
        try:
            points = np.concatenate([item.points_world for item in views if item.points_world is not None], axis=0)
            plane = _fit_plane(points, config.global_plane_threshold_ratio, config.global_plane_minimum_inlier_ratio)
            camera_mean = np.mean(cameras, axis=0)
            if float(np.dot(plane.normal, camera_mean - plane.center)) < 0:
                plane = dataclasses.replace(plane, normal=-plane.normal, offset=-plane.offset)
            fusion = _rectified_fusion(views, plane, config)
            if not np.any(fusion.valid_mask):
                raise SignEvidenceError("rectified fusion contains no observed pixels")
        except (SignEvidenceError, np.linalg.LinAlgError) as error:
            reasons.append("global-plane-or-fusion-failed:" + str(error))
            plane = None
            fusion = None
    state = GeometryState.GEOMETRY_VERIFIED if not reasons else GeometryState.UNVERIFIED
    return SignTrackEvidence(
        track_id=f"sign-track-{track_index:06d}",
        state=state,
        reasons=tuple(reasons),
        observation_ids=tuple(item.candidate.candidate_id for item in cluster),
        selected_observation_ids=tuple(item.candidate.candidate_id for item in views),
        plane=plane,
        camera_baseline_ratio=baseline_ratio,
        centroid_dispersion_ratio=centroid_dispersion,
        normal_p95_degrees=normal_p95,
        regulatory_class=_cross_view_claim(views, "regulatory_class", config),
        text=_cross_view_claim(views, "text", config),
        fusion=fusion,
    )


def build_sign_evidence(
    candidates: Sequence[SignCandidate],
    provenance: SignEvidenceProvenance,
    config: SignEvidenceConfig | None = None,
) -> SignEvidenceBundle:
    """Build deterministic sign tracks and fail-closed geometry evidence."""

    provenance.validate()
    active = config or SignEvidenceConfig()
    active.validate()
    if not candidates:
        raise SignEvidenceError("at least one sign candidate is required")
    identifiers = [candidate.candidate_id for candidate in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise SignEvidenceError("candidate identifiers must be unique")
    observations = tuple(evaluate_observation(candidate, active) for candidate in candidates)
    clusters = _cluster_observations(observations, active)
    clusters.sort(
        key=lambda cluster: min(
            (item.candidate.frame_index, item.candidate.frame_id, item.candidate.candidate_id)
            for item in cluster
        )
    )
    tracks = tuple(_build_track(index, cluster, active) for index, cluster in enumerate(clusters))
    # Promote only observations that participate in a geometry-verified track.
    verified_ids = {
        candidate_id
        for track in tracks
        if track.state is GeometryState.GEOMETRY_VERIFIED
        for candidate_id in track.selected_observation_ids
    }
    promoted = tuple(
        dataclasses.replace(item, state=GeometryState.GEOMETRY_VERIFIED)
        if item.candidate.candidate_id in verified_ids
        else item
        for item in observations
    )
    return SignEvidenceBundle(provenance, active, promoted, tracks)


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def write_sign_evidence(bundle: SignEvidenceBundle, output_directory: Path) -> Path:
    """Atomically publish a JSON manifest and lossless per-track atlas files."""

    import cv2

    output_directory = Path(output_directory)
    atlas_directory = output_directory / "sign-atlases"
    for track in bundle.tracks:
        if track.fusion is None:
            continue
        success, encoded = cv2.imencode(".png", track.fusion.bgr, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        if not success:
            raise SignEvidenceError(f"unable to encode atlas for {track.track_id}")
        _atomic_bytes(atlas_directory / f"{track.track_id}.png", encoded.tobytes())
        buffer_path = atlas_directory / f"{track.track_id}-evidence.npz"
        temporary = buffer_path.with_name(f".{buffer_path.name}.{uuid.uuid4().hex}.tmp")
        buffer_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open("wb") as stream:
                np.savez_compressed(
                    stream,
                    valid_mask=track.fusion.valid_mask,
                    support_count=track.fusion.support_count,
                    source_observation_slot=track.fusion.source_observation_slot,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, buffer_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
    manifest_path = output_directory / "sign-evidence.json"
    _atomic_bytes(manifest_path, _canonical_json(bundle.manifest()) + b"\n")
    return manifest_path


__all__ = [
    "CAMERA_CONVENTION",
    "ClaimState",
    "ExternalRecognition",
    "GeometryState",
    "PlaneFit",
    "RecognitionClaim",
    "RectifiedFusion",
    "SIGN_EVIDENCE_ALGORITHM",
    "SIGN_EVIDENCE_SCHEMA",
    "SignCandidate",
    "SignEvidenceBundle",
    "SignEvidenceConfig",
    "SignEvidenceError",
    "SignEvidenceProvenance",
    "SignTrackEvidence",
    "build_sign_evidence",
    "evaluate_observation",
    "write_sign_evidence",
]
