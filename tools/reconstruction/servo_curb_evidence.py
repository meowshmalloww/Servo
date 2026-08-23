#!/usr/bin/env python3
"""Deterministic, evidence-only curb and road-edge geometry.

This clean-room module consumes *already calibrated* cross-road profiles from
multiple undistorted frames.  Each profile carries broad road semantics,
SfM-frame points and normals, source-pixel coordinates, and an observed-pixel
mask.  It never runs a detector, fills an occlusion, hallucinates geometry, or
turns a semantic curb proposal into a geometric curb by itself.

The contract deliberately separates three concepts used by ASAM OpenDRIVE:

* ``road-edge`` is a repeated boundary without a supported raised face;
* ``shoulder`` is a repeated soft transition away from the drivable surface;
* ``curb`` requires a repeated height step, a near-vertical face, an upper
  surface, spatial continuity, and agreement from separated calibrated views.

Unknown, occluded, layered, or geometrically inconsistent evidence fails
closed.  Heights remain in reconstruction units unless provenance contains an
explicit metric scale anchor.  A geometric label is not collision validation.

The design is informed by ASAM OpenDRIVE 1.9, COLMAP's geometric-consistency
and fusion contracts, and published curb extraction methods that combine
elevation difference, gradient/normal orientation, and temporal continuity.
No source code or pretrained weights from those projects are copied here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from enum import Enum
from typing import Literal, Sequence

import numpy as np


CURB_EVIDENCE_SCHEMA = "servo.curb-evidence/v1"
CURB_EVIDENCE_ALGORITHM = "servo-curb-road-edge-cleanroom/1.0.0"
CAMERA_CONVENTION = "camera-to-world; camera +x right, +y down, +z forward"
RESEARCH_REFERENCES = (
    "https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/"
    "ASAM_OpenDRIVE_Specification/latest/specification/11_lanes/"
    "11_07_lane_properties.html",
    "https://colmap.github.io/format.html#dense-reconstruction",
    "https://colmap.github.io/pycolmap/pycolmap.html",
    "https://doi.org/10.1109/ICIP.2012.6466890",
    "https://www.ri.cmu.edu/app/uploads/2019/06/FINAL-VERSION-TITS2018.pdf",
    "https://arxiv.org/abs/1610.04673",
    "https://doi.org/10.1016/j.optlaseng.2018.03.017",
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class CurbEvidenceError(ValueError):
    """Raised when evidence is malformed rather than merely insufficient."""


class BoundaryClass(str, Enum):
    """Conservative physical interpretation of an observed road boundary."""

    UNKNOWN = "unknown"
    ROAD_EDGE = "road-edge"
    SHOULDER = "shoulder"
    CURB = "curb"


@dataclasses.dataclass(frozen=True)
class CurbEvidenceProvenance:
    """Required provenance for one multi-view boundary sequence.

    ``sfm-arbitrary-scale`` permits scale-invariant curb classification, but
    never a metric height.  ``metric-anchored`` requires both an auditable
    anchor description and the number of world units per metre.
    """

    sequence_id: str
    coordinate_frame_id: str
    scale_provenance: Literal["sfm-arbitrary-scale", "metric-anchored"]
    camera_source: str
    depth_source: str
    normal_source: str
    semantic_source: str
    profile_source: str
    distortion_state: Literal["undistorted"] = "undistorted"
    geometry_alignment: Literal[
        "sfm-world-points-and-normals"
    ] = "sfm-world-points-and-normals"
    contains_generated_pixels: bool = False
    world_units_per_metre: float | None = None
    scale_anchor_source: str | None = None
    source_hashes: tuple[tuple[str, str], ...] = ()

    def validate(self) -> None:
        for name in (
            "sequence_id",
            "coordinate_frame_id",
            "camera_source",
            "depth_source",
            "normal_source",
            "semantic_source",
            "profile_source",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise CurbEvidenceError(f"provenance {name} must not be empty")
        if self.scale_provenance not in {
            "sfm-arbitrary-scale",
            "metric-anchored",
        }:
            raise CurbEvidenceError("unsupported scale provenance")
        if self.distortion_state != "undistorted":
            raise CurbEvidenceError("curb evidence requires undistorted imagery")
        if self.geometry_alignment != "sfm-world-points-and-normals":
            raise CurbEvidenceError(
                "points and normals must be aligned to the SfM world frame"
            )
        if self.contains_generated_pixels:
            raise CurbEvidenceError("generated pixels cannot be curb evidence")
        if self.scale_provenance == "sfm-arbitrary-scale":
            if (
                self.world_units_per_metre is not None
                or self.scale_anchor_source is not None
            ):
                raise CurbEvidenceError(
                    "arbitrary-scale evidence cannot carry a metric scale claim"
                )
        else:
            if (
                self.world_units_per_metre is None
                or isinstance(self.world_units_per_metre, bool)
                or not math.isfinite(float(self.world_units_per_metre))
                or float(self.world_units_per_metre) <= 0.0
                or not isinstance(self.scale_anchor_source, str)
                or not self.scale_anchor_source.strip()
            ):
                raise CurbEvidenceError(
                    "metric scale requires positive world_units_per_metre and an anchor"
                )
        if len({name for name, _ in self.source_hashes}) != len(
            self.source_hashes
        ):
            raise CurbEvidenceError("source hash names must be unique")
        for name, digest in self.source_hashes:
            if not name.strip() or _SHA256.fullmatch(digest) is None:
                raise CurbEvidenceError(
                    "source hashes must be named lowercase sha256 digests"
                )

    def manifest(self) -> dict[str, object]:
        return {
            "sequenceId": self.sequence_id,
            "coordinateFrameId": self.coordinate_frame_id,
            "scaleProvenance": self.scale_provenance,
            "cameraSource": self.camera_source,
            "depthSource": self.depth_source,
            "normalSource": self.normal_source,
            "semanticSource": self.semantic_source,
            "profileSource": self.profile_source,
            "distortionState": self.distortion_state,
            "geometryAlignment": self.geometry_alignment,
            "containsGeneratedPixels": False,
            "worldUnitsPerMetre": self.world_units_per_metre,
            "scaleAnchorSource": self.scale_anchor_source,
            "sourceHashes": {
                name: digest for name, digest in sorted(self.source_hashes)
            },
        }


@dataclasses.dataclass(frozen=True)
class CurbEvidenceConfig:
    """Scale-invariant, fail-closed evidence thresholds."""

    minimum_views: int = 3
    minimum_nonadjacent_frame_gap: int = 2
    minimum_profiles_per_view: int = 5
    minimum_supported_profile_fraction: float = 0.60
    minimum_class_agreement_fraction: float = 0.70
    minimum_continuity_fraction: float = 0.60
    minimum_road_samples: int = 3
    minimum_exterior_samples: int = 3
    minimum_vertical_face_samples: int = 2
    minimum_sample_confidence: float = 0.50
    minimum_road_normal_up_alignment: float = 0.85
    minimum_top_normal_up_alignment: float = 0.75
    maximum_vertical_face_up_alignment: float = 0.35
    minimum_vertical_face_outward_alignment: float = 0.65
    minimum_face_height_fraction: float = 0.30
    maximum_face_thickness_to_height: float = 0.75
    minimum_step_to_sampling_ratio: float = 1.00
    maximum_step_to_sampling_ratio: float = 8.00
    maximum_flat_step_to_sampling_ratio: float = 0.45
    minimum_shoulder_normal_up_alignment: float = 0.60
    maximum_shoulder_grade: float = 0.75
    minimum_camera_baseline_to_edge_span: float = 0.03
    maximum_view_edge_dispersion_to_span: float = 0.12
    maximum_step_relative_mad: float = 0.25
    maximum_step_relative_deviation: float = 0.40
    maximum_reprojection_error_pixels: float = 1.50
    maximum_consecutive_edge_gap_ratio: float = 3.00
    road_labels: tuple[int, ...] = (1, 2, 5)
    soft_shoulder_labels: tuple[int, ...] = (6,)

    def validate(self) -> None:
        if self.minimum_views < 3:
            raise CurbEvidenceError("minimum_views cannot be below three")
        if self.minimum_nonadjacent_frame_gap < 1:
            raise CurbEvidenceError("frame gap must be positive")
        if self.minimum_profiles_per_view < 3:
            raise CurbEvidenceError("at least three profiles per view are required")
        if self.minimum_road_samples < 2 or self.minimum_exterior_samples < 2:
            raise CurbEvidenceError("surface windows require at least two samples")
        if self.minimum_vertical_face_samples < 2:
            raise CurbEvidenceError("vertical-face support requires two samples")
        for name in (
            "minimum_supported_profile_fraction",
            "minimum_class_agreement_fraction",
            "minimum_continuity_fraction",
            "minimum_sample_confidence",
            "minimum_road_normal_up_alignment",
            "minimum_top_normal_up_alignment",
            "maximum_vertical_face_up_alignment",
            "minimum_vertical_face_outward_alignment",
            "minimum_face_height_fraction",
            "minimum_shoulder_normal_up_alignment",
            "minimum_camera_baseline_to_edge_span",
            "maximum_view_edge_dispersion_to_span",
            "maximum_step_relative_mad",
            "maximum_step_relative_deviation",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise CurbEvidenceError(f"{name} must be finite and in [0, 1]")
        for name in (
            "maximum_face_thickness_to_height",
            "minimum_step_to_sampling_ratio",
            "maximum_step_to_sampling_ratio",
            "maximum_flat_step_to_sampling_ratio",
            "maximum_shoulder_grade",
            "maximum_reprojection_error_pixels",
            "maximum_consecutive_edge_gap_ratio",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise CurbEvidenceError(f"{name} must be finite and nonnegative")
        if self.maximum_step_to_sampling_ratio <= self.minimum_step_to_sampling_ratio:
            raise CurbEvidenceError("step-ratio bounds are invalid")
        if self.maximum_flat_step_to_sampling_ratio >= self.minimum_step_to_sampling_ratio:
            raise CurbEvidenceError("flat-edge and raised-step bounds must not overlap")
        if self.maximum_consecutive_edge_gap_ratio < 1.0:
            raise CurbEvidenceError("consecutive edge-gap ratio cannot be below one")
        if (
            self.maximum_vertical_face_up_alignment
            >= self.minimum_road_normal_up_alignment
            or self.maximum_vertical_face_up_alignment
            >= self.minimum_top_normal_up_alignment
            or self.maximum_vertical_face_up_alignment
            >= self.minimum_shoulder_normal_up_alignment
        ):
            raise CurbEvidenceError("surface and vertical-face normal gates overlap")
        if not self.road_labels or len(set(self.road_labels)) != len(self.road_labels):
            raise CurbEvidenceError("road labels must be unique and nonempty")
        if set(self.road_labels) & set(self.soft_shoulder_labels):
            raise CurbEvidenceError("road and soft-shoulder labels must be disjoint")

    def manifest(self) -> dict[str, object]:
        record = dataclasses.asdict(self)
        record["road_labels"] = list(self.road_labels)
        record["soft_shoulder_labels"] = list(self.soft_shoulder_labels)
        return record


@dataclasses.dataclass(frozen=True)
class CalibratedBoundaryFrame:
    """Observed cross-road profiles from one calibrated frame.

    Profiles are ordered along the road.  Samples within each profile are
    ordered from road interior toward the candidate exterior.  Points and
    normals are already in the shared SfM world frame.  ``source_pixels_xy``
    records the original undistorted pixel centre for every sample.
    """

    frame_id: str
    frame_index: int
    image_size: tuple[int, int]
    calibration: np.ndarray = dataclasses.field(repr=False)
    camera_to_world: np.ndarray = dataclasses.field(repr=False)
    profile_points_world: np.ndarray = dataclasses.field(repr=False)
    profile_normals_world: np.ndarray = dataclasses.field(repr=False)
    semantic_labels: np.ndarray = dataclasses.field(repr=False)
    observed_mask: np.ndarray = dataclasses.field(repr=False)
    source_pixels_xy: np.ndarray = dataclasses.field(repr=False)
    confidence: np.ndarray | None = dataclasses.field(default=None, repr=False)


def frame_from_camera_z_depth(
    *,
    frame_id: str,
    frame_index: int,
    image_size: tuple[int, int],
    calibration: np.ndarray,
    camera_to_world: np.ndarray,
    profile_depth_camera_z: np.ndarray,
    profile_normals_camera: np.ndarray,
    semantic_labels: np.ndarray,
    observed_mask: np.ndarray,
    source_pixels_xy: np.ndarray,
    confidence: np.ndarray | None = None,
) -> CalibratedBoundaryFrame:
    """Unproject observed camera-Z samples into the shared SfM world frame.

    This is a coordinate conversion only.  It does not resample depth, estimate
    normals, close holes, or create pixels.  Unobserved values may be NaN.
    """

    depth = np.asarray(profile_depth_camera_z, dtype=np.float64)
    normals_camera = np.asarray(profile_normals_camera, dtype=np.float64)
    observed = np.asarray(observed_mask, dtype=bool)
    pixels = np.asarray(source_pixels_xy, dtype=np.float64)
    calibration_array = np.asarray(calibration, dtype=np.float64)
    camera_transform = np.asarray(camera_to_world, dtype=np.float64)
    if depth.ndim != 2 or observed.shape != depth.shape:
        raise CurbEvidenceError("camera-Z depth and observed mask must be matching PxS arrays")
    if normals_camera.shape != (*depth.shape, 3):
        raise CurbEvidenceError("camera normals must be PxSx3")
    if pixels.shape != (*depth.shape, 2):
        raise CurbEvidenceError("source pixels must be PxSx2")
    if calibration_array.shape != (3, 3) or not np.all(
        np.isfinite(calibration_array)
    ):
        raise CurbEvidenceError("calibration must be a finite 3x3 matrix")
    if camera_transform.shape != (4, 4) or not np.all(np.isfinite(camera_transform)):
        raise CurbEvidenceError("camera_to_world must be a finite 4x4 matrix")
    if np.any(~np.isfinite(depth[observed])) or np.any(depth[observed] <= 0.0):
        raise CurbEvidenceError("observed camera-Z depth must be finite and positive")
    if np.any(~np.isfinite(normals_camera[observed])):
        raise CurbEvidenceError("observed camera normals must be finite")
    try:
        inverse_calibration = np.linalg.inv(calibration_array)
    except np.linalg.LinAlgError as error:
        raise CurbEvidenceError("calibration must be invertible") from error
    homogeneous_pixels = np.concatenate(
        (pixels, np.ones((*depth.shape, 1), dtype=np.float64)), axis=2
    )
    rays = homogeneous_pixels @ inverse_calibration.T
    ray_z = rays[..., 2]
    if np.any(~np.isfinite(ray_z[observed])) or np.any(
        np.abs(ray_z[observed]) <= 1.0e-12
    ):
        raise CurbEvidenceError("source pixels do not define finite camera rays")
    points_camera = np.full((*depth.shape, 3), np.nan, dtype=np.float64)
    points_camera[observed] = (
        rays[observed]
        * (depth[observed] / ray_z[observed])[:, None]
    )
    rotation = camera_transform[:3, :3]
    translation = camera_transform[:3, 3]
    points_world = np.full_like(points_camera, np.nan)
    normals_world = np.full_like(normals_camera, np.nan)
    points_world[observed] = points_camera[observed] @ rotation.T + translation
    normals_world[observed] = normals_camera[observed] @ rotation.T
    return CalibratedBoundaryFrame(
        frame_id=frame_id,
        frame_index=frame_index,
        image_size=image_size,
        calibration=calibration_array,
        camera_to_world=camera_transform,
        profile_points_world=points_world,
        profile_normals_world=normals_world,
        semantic_labels=np.asarray(semantic_labels),
        observed_mask=observed,
        source_pixels_xy=pixels,
        confidence=confidence,
    )


@dataclasses.dataclass(frozen=True)
class ProfileEvidence:
    profile_index: int
    classification: BoundaryClass
    reason: str
    lower_point_world: tuple[float, float, float] | None
    upper_point_world: tuple[float, float, float] | None
    lower_source_pixel: tuple[float, float] | None
    upper_source_pixel: tuple[float, float] | None
    step_height_world_units: float | None
    sampling_scale_world_units: float | None
    face_sample_count: int


@dataclasses.dataclass(frozen=True)
class ViewEvidence:
    frame_id: str
    frame_index: int
    classification: BoundaryClass
    reasons: tuple[str, ...]
    profiles: tuple[ProfileEvidence, ...]
    supported_profiles: int
    continuity_fraction: float
    camera_center_world: tuple[float, float, float]
    evidence_sha256: str


@dataclasses.dataclass(frozen=True)
class CurbEvidenceBundle:
    boundary_id: str
    classification: BoundaryClass
    reasons: tuple[str, ...]
    views: tuple[ViewEvidence, ...]
    selected_frame_ids: tuple[str, ...]
    step_height_world_units: float | None
    step_height_metres: float | None
    edge_evidence_points_world: tuple[tuple[float, float, float], ...]
    provenance: CurbEvidenceProvenance
    config: CurbEvidenceConfig
    forward_axis_world: tuple[float, float, float]
    outward_axis_world: tuple[float, float, float]
    up_axis_world: tuple[float, float, float]

    def metrics(self) -> dict[str, object]:
        profile_counts = {state.value: 0 for state in BoundaryClass}
        for view in self.views:
            for profile in view.profiles:
                profile_counts[profile.classification.value] += 1
        return {
            "schema": CURB_EVIDENCE_SCHEMA,
            "algorithm": CURB_EVIDENCE_ALGORITHM,
            "classification": self.classification.value,
            "reasons": list(self.reasons),
            "inputViews": len(self.views),
            "selectedViews": len(self.selected_frame_ids),
            "profileClassCounts": profile_counts,
            "edgeEvidencePointCount": len(self.edge_evidence_points_world),
            "stepHeightWorldUnits": self.step_height_world_units,
            "stepHeightMetres": self.step_height_metres,
            "scaleProvenance": self.provenance.scale_provenance,
            "metricHeightClaim": self.step_height_metres is not None,
            "containsGeneratedPixels": False,
            "collisionValidated": False,
        }

    def manifest(self) -> dict[str, object]:
        return {
            "schema": CURB_EVIDENCE_SCHEMA,
            "algorithm": CURB_EVIDENCE_ALGORITHM,
            "boundaryId": self.boundary_id,
            "cameraConvention": CAMERA_CONVENTION,
            "researchReferences": list(RESEARCH_REFERENCES),
            "provenance": self.provenance.manifest(),
            "config": self.config.manifest(),
            "axesWorld": {
                "forward": list(self.forward_axis_world),
                "outward": list(self.outward_axis_world),
                "up": list(self.up_axis_world),
            },
            "summary": self.metrics(),
            "selectedFrameIds": list(self.selected_frame_ids),
            "views": [_view_manifest(view) for view in self.views],
            "edgeEvidencePointsWorld": [
                list(point) for point in self.edge_evidence_points_world
            ],
            "safety": {
                "collisionReady": False,
                "containsGeneratedPixels": False,
                "unknownIsNotTraversable": True,
                "semanticBoundaryDoesNotVerifyCurb": True,
                "metricHeightRequiresScaleAnchor": True,
            },
        }

    def canonical_manifest_json(self) -> str:
        return json.dumps(
            self.manifest(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def manifest_sha256(self) -> str:
        return "sha256:" + hashlib.sha256(
            self.canonical_manifest_json().encode("utf-8")
        ).hexdigest()


def _view_manifest(view: ViewEvidence) -> dict[str, object]:
    return {
        "frameId": view.frame_id,
        "frameIndex": view.frame_index,
        "classification": view.classification.value,
        "reasons": list(view.reasons),
        "supportedProfiles": view.supported_profiles,
        "continuityFraction": view.continuity_fraction,
        "cameraCenterWorld": list(view.camera_center_world),
        "evidenceSha256": view.evidence_sha256,
        "profiles": [
            {
                "profileIndex": profile.profile_index,
                "classification": profile.classification.value,
                "reason": profile.reason,
                "lowerPointWorld": (
                    None
                    if profile.lower_point_world is None
                    else list(profile.lower_point_world)
                ),
                "upperPointWorld": (
                    None
                    if profile.upper_point_world is None
                    else list(profile.upper_point_world)
                ),
                "lowerSourcePixel": (
                    None
                    if profile.lower_source_pixel is None
                    else list(profile.lower_source_pixel)
                ),
                "upperSourcePixel": (
                    None
                    if profile.upper_source_pixel is None
                    else list(profile.upper_source_pixel)
                ),
                "stepHeightWorldUnits": profile.step_height_world_units,
                "samplingScaleWorldUnits": profile.sampling_scale_world_units,
                "faceSampleCount": profile.face_sample_count,
            }
            for profile in view.profiles
        ],
    }


def _axis(value: Sequence[float], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise CurbEvidenceError(f"{name} must be a finite three-vector")
    norm = float(np.linalg.norm(result))
    if norm <= np.finfo(np.float64).eps:
        raise CurbEvidenceError(f"{name} must be nonzero")
    return result / norm


def _validate_axes(
    forward: Sequence[float], outward: Sequence[float], up: Sequence[float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    forward_axis = _axis(forward, "forward_axis_world")
    outward_axis = _axis(outward, "outward_axis_world")
    up_axis = _axis(up, "up_axis_world")
    if max(
        abs(float(np.dot(forward_axis, outward_axis))),
        abs(float(np.dot(forward_axis, up_axis))),
        abs(float(np.dot(outward_axis, up_axis))),
    ) > 1.0e-5:
        raise CurbEvidenceError("road axes must be mutually orthogonal")
    return forward_axis, outward_axis, up_axis


def _frame_arrays(
    frame: CalibratedBoundaryFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    points = np.asarray(frame.profile_points_world, dtype=np.float64)
    normals = np.asarray(frame.profile_normals_world, dtype=np.float64)
    labels = np.asarray(frame.semantic_labels)
    observed = np.asarray(frame.observed_mask, dtype=bool)
    pixels = np.asarray(frame.source_pixels_xy, dtype=np.float64)
    confidence = (
        np.ones(observed.shape, dtype=np.float64)
        if frame.confidence is None
        else np.asarray(frame.confidence, dtype=np.float64)
    )
    if points.ndim != 3 or points.shape[2] != 3:
        raise CurbEvidenceError("profile_points_world must be PxSx3")
    if normals.shape != points.shape:
        raise CurbEvidenceError("profile normals must match profile points")
    shape = points.shape[:2]
    if labels.shape != shape or observed.shape != shape or confidence.shape != shape:
        raise CurbEvidenceError("profile labels, masks, and confidence must be PxS")
    if pixels.shape != (*shape, 2):
        raise CurbEvidenceError("source_pixels_xy must be PxSx2")
    return points, normals, labels, observed, pixels, confidence


def _validate_frame(
    frame: CalibratedBoundaryFrame,
    config: CurbEvidenceConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(frame.frame_id, str) or not frame.frame_id.strip():
        raise CurbEvidenceError("frame_id must not be empty")
    if (
        isinstance(frame.frame_index, bool)
        or not isinstance(frame.frame_index, int)
        or frame.frame_index < 0
    ):
        raise CurbEvidenceError("frame_index must be a nonnegative integer")
    if not isinstance(frame.image_size, tuple) or len(frame.image_size) != 2:
        raise CurbEvidenceError("image_size must be a (width, height) tuple")
    width, height = frame.image_size
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise CurbEvidenceError("image dimensions must be positive")
    calibration = np.asarray(frame.calibration, dtype=np.float64)
    if (
        calibration.shape != (3, 3)
        or not np.all(np.isfinite(calibration))
        or calibration[0, 0] <= 0.0
        or calibration[1, 1] <= 0.0
        or not np.allclose(calibration[2], (0.0, 0.0, 1.0), atol=1.0e-9)
    ):
        raise CurbEvidenceError("calibration must be a finite pinhole matrix")
    camera_to_world = np.asarray(frame.camera_to_world, dtype=np.float64)
    if (
        camera_to_world.shape != (4, 4)
        or not np.all(np.isfinite(camera_to_world))
        or not np.allclose(camera_to_world[3], (0.0, 0.0, 0.0, 1.0), atol=1e-9)
    ):
        raise CurbEvidenceError("camera_to_world must be a finite rigid transform")
    rotation = camera_to_world[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1.0e-6) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, rel_tol=0.0, abs_tol=1.0e-6
    ):
        raise CurbEvidenceError("camera_to_world rotation must be right-handed")
    arrays = _frame_arrays(frame)
    points, normals, labels, observed, pixels, confidence = arrays
    if points.shape[0] < config.minimum_profiles_per_view:
        raise CurbEvidenceError("frame has fewer profiles than the configured minimum")
    if points.shape[1] < config.minimum_road_samples + config.minimum_exterior_samples:
        raise CurbEvidenceError("profiles have too few cross-road samples")
    if not np.issubdtype(labels.dtype, np.integer):
        raise CurbEvidenceError("semantic_labels must be integer class identifiers")
    usable = observed
    if np.any(~np.isfinite(confidence[usable])) or np.any(
        (confidence[usable] < 0.0) | (confidence[usable] > 1.0)
    ):
        raise CurbEvidenceError("observed confidence must be finite and in [0, 1]")
    if np.any(~np.isfinite(points[usable])) or np.any(~np.isfinite(normals[usable])):
        raise CurbEvidenceError("observed points and normals must be finite")
    normal_length = np.linalg.norm(normals[usable], axis=1)
    if np.any(normal_length <= 1.0e-9):
        raise CurbEvidenceError("observed normals must be nonzero")
    if np.any(~np.isfinite(pixels[usable])):
        raise CurbEvidenceError("observed source pixels must be finite")
    x = pixels[..., 0][usable]
    y = pixels[..., 1][usable]
    if np.any(x < 0.0) or np.any(x >= width) or np.any(y < 0.0) or np.any(y >= height):
        raise CurbEvidenceError("observed source pixels must lie inside the image")
    world_to_camera_rotation = rotation.T
    camera_center = camera_to_world[:3, 3]
    camera_points = (
        world_to_camera_rotation @ (points[usable] - camera_center).T
    ).T
    if np.any(camera_points[:, 2] <= 1.0e-9):
        raise CurbEvidenceError("observed profile points must be in front of the camera")
    homogeneous = (calibration @ camera_points.T).T
    projected = homogeneous[:, :2] / homogeneous[:, 2, None]
    reprojection_error = np.linalg.norm(projected - pixels[usable], axis=1)
    if np.any(reprojection_error > config.maximum_reprojection_error_pixels):
        raise CurbEvidenceError(
            "profile points do not reproject to their claimed observed pixels"
        )
    return arrays


def _frame_digest(frame: CalibratedBoundaryFrame) -> str:
    points, normals, labels, observed, pixels, confidence = _frame_arrays(frame)
    digest = hashlib.sha256()
    metadata = json.dumps(
        {
            "frameId": frame.frame_id,
            "frameIndex": frame.frame_index,
            "imageSize": list(frame.image_size),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest.update(metadata)
    for value, dtype in (
        (frame.calibration, "<f8"),
        (frame.camera_to_world, "<f8"),
        (points, "<f8"),
        (normals, "<f8"),
        (labels, "<i8"),
        (observed, "u1"),
        (pixels, "<f8"),
        (confidence, "<f8"),
    ):
        array = np.ascontiguousarray(np.asarray(value).astype(dtype, copy=False))
        digest.update(str(array.shape).encode("ascii"))
        digest.update(array.tobytes(order="C"))
    return "sha256:" + digest.hexdigest()


def _profile_unknown(index: int, reason: str) -> ProfileEvidence:
    return ProfileEvidence(
        profile_index=index,
        classification=BoundaryClass.UNKNOWN,
        reason=reason,
        lower_point_world=None,
        upper_point_world=None,
        lower_source_pixel=None,
        upper_source_pixel=None,
        step_height_world_units=None,
        sampling_scale_world_units=None,
        face_sample_count=0,
    )


def _profile_evidence(
    index: int,
    points: np.ndarray,
    normals: np.ndarray,
    labels: np.ndarray,
    observed: np.ndarray,
    pixels: np.ndarray,
    confidence: np.ndarray,
    outward_axis: np.ndarray,
    up_axis: np.ndarray,
    config: CurbEvidenceConfig,
) -> ProfileEvidence:
    finite = (
        observed
        & np.isfinite(confidence)
        & (confidence >= config.minimum_sample_confidence)
        & np.all(np.isfinite(points), axis=1)
        & np.all(np.isfinite(normals), axis=1)
    )
    road = np.isin(labels, np.asarray(config.road_labels))
    transitions = np.flatnonzero(finite[:-1] & finite[1:] & road[:-1] & ~road[1:])
    if len(transitions) != 1:
        return _profile_unknown(index, "missing-or-ambiguous-road-transition")
    transition = int(transitions[0])
    if np.any(finite[transition + 1 :] & road[transition + 1 :]):
        return _profile_unknown(index, "stacked-road-or-multiple-road-runs")
    road_start = transition - config.minimum_road_samples + 1
    if road_start < 0:
        return _profile_unknown(index, "insufficient-road-interior-support")
    road_indices = np.arange(road_start, transition + 1)
    if not np.all(finite[road_indices] & road[road_indices]):
        return _profile_unknown(index, "occluded-road-interior")
    exterior_stop = transition + 1 + max(
        config.minimum_exterior_samples + config.minimum_vertical_face_samples,
        config.minimum_exterior_samples,
    )
    exterior_stop = min(len(points), exterior_stop)
    if exterior_stop - (transition + 1) < config.minimum_exterior_samples:
        return _profile_unknown(index, "insufficient-exterior-support")

    norm_length = np.linalg.norm(normals, axis=1)
    unit_normals = np.zeros_like(normals)
    nonzero = norm_length > 1.0e-9
    unit_normals[nonzero] = normals[nonzero] / norm_length[nonzero, None]
    up_alignment = np.abs(unit_normals @ up_axis)
    if np.median(up_alignment[road_indices]) < config.minimum_road_normal_up_alignment:
        return _profile_unknown(index, "road-normal-is-not-surface-like")

    interior = np.flatnonzero(finite[: transition + 1] & road[: transition + 1])
    differences = np.linalg.norm(np.diff(points[interior], axis=0), axis=1)
    differences = differences[np.isfinite(differences) & (differences > 1.0e-9)]
    if not len(differences):
        return _profile_unknown(index, "road-sampling-scale-is-undefined")
    sampling_scale = float(np.median(differences))

    usable_indices = np.flatnonzero(finite)
    outward = points @ outward_axis
    outward_delta = np.diff(outward[usable_indices])
    if np.any(outward_delta < -0.20 * sampling_scale):
        return _profile_unknown(index, "profile-order-reverses-outward")

    first_exterior = transition + 1
    face_indices: list[int] = []
    cursor = first_exterior
    while (
        cursor < len(points)
        and finite[cursor]
        and not road[cursor]
        and up_alignment[cursor] <= config.maximum_vertical_face_up_alignment
    ):
        face_indices.append(cursor)
        cursor += 1

    lower_index = transition
    road_height = float(np.median(points[road_indices] @ up_axis))
    lower_point = tuple(float(value) for value in points[lower_index])
    lower_pixel = tuple(float(value) for value in pixels[lower_index])

    if len(face_indices) >= config.minimum_vertical_face_samples:
        top_stop = cursor + config.minimum_exterior_samples
        if top_stop > len(points):
            return _profile_unknown(index, "curb-has-no-observed-upper-surface")
        top_indices = np.arange(cursor, top_stop)
        if (
            not np.all(finite[top_indices] & ~road[top_indices])
            or np.median(up_alignment[top_indices])
            < config.minimum_top_normal_up_alignment
        ):
            return _profile_unknown(index, "curb-has-no-supported-upper-surface")
        top_height = float(np.median(points[top_indices] @ up_axis))
        step_height = top_height - road_height
        ratio = step_height / sampling_scale
        face_height = points[face_indices] @ up_axis
        face_height_span = float(np.max(face_height) - np.min(face_height))
        face_outward = points[face_indices] @ outward_axis
        face_thickness = float(np.max(face_outward) - np.min(face_outward))
        face_outward_alignment = float(
            np.median(np.abs(unit_normals[face_indices] @ outward_axis))
        )
        if (
            not config.minimum_step_to_sampling_ratio
            <= ratio
            <= config.maximum_step_to_sampling_ratio
            or face_height_span < config.minimum_face_height_fraction * step_height
            or face_thickness
            > config.maximum_face_thickness_to_height * step_height
            or face_outward_alignment
            < config.minimum_vertical_face_outward_alignment
        ):
            return _profile_unknown(index, "raised-face-geometry-is-not-curb-like")
        upper_index = int(top_indices[0])
        return ProfileEvidence(
            profile_index=index,
            classification=BoundaryClass.CURB,
            reason="repeated-step-face-candidate",
            lower_point_world=lower_point,
            upper_point_world=tuple(float(value) for value in points[upper_index]),
            lower_source_pixel=lower_pixel,
            upper_source_pixel=tuple(float(value) for value in pixels[upper_index]),
            step_height_world_units=float(step_height),
            sampling_scale_world_units=sampling_scale,
            face_sample_count=len(face_indices),
        )

    exterior_indices = np.arange(
        first_exterior, first_exterior + config.minimum_exterior_samples
    )
    if not np.all(finite[exterior_indices] & ~road[exterior_indices]):
        return _profile_unknown(index, "occluded-exterior-surface")
    exterior_height = points[exterior_indices] @ up_axis
    height_change = float(np.median(exterior_height) - road_height)
    adjacent = np.diff(points[np.concatenate(([lower_index], exterior_indices))], axis=0)
    vertical = np.abs(adjacent @ up_axis)
    horizontal = np.linalg.norm(adjacent - (adjacent @ up_axis)[:, None] * up_axis, axis=1)
    grade = float(np.max(vertical / np.maximum(horizontal, 1.0e-9)))
    soft_fraction = float(
        np.mean(np.isin(labels[exterior_indices], config.soft_shoulder_labels))
    )
    if (
        soft_fraction >= 0.5
        and np.min(up_alignment[exterior_indices])
        >= config.minimum_shoulder_normal_up_alignment
        and grade <= config.maximum_shoulder_grade
    ):
        classification = BoundaryClass.SHOULDER
        reason = "soft-continuous-road-transition"
    elif (
        abs(height_change) / sampling_scale
        <= config.maximum_flat_step_to_sampling_ratio
        and np.median(up_alignment[exterior_indices])
        >= config.minimum_top_normal_up_alignment
    ):
        classification = BoundaryClass.ROAD_EDGE
        reason = "flat-boundary-without-raised-face"
    else:
        return _profile_unknown(index, "boundary-has-no-supported-curb-or-edge-model")
    upper_index = int(exterior_indices[0])
    return ProfileEvidence(
        profile_index=index,
        classification=classification,
        reason=reason,
        lower_point_world=lower_point,
        upper_point_world=tuple(float(value) for value in points[upper_index]),
        lower_source_pixel=lower_pixel,
        upper_source_pixel=tuple(float(value) for value in pixels[upper_index]),
        step_height_world_units=None,
        sampling_scale_world_units=sampling_scale,
        face_sample_count=0,
    )


def _longest_supported_run(profiles: Sequence[ProfileEvidence]) -> int:
    longest = 0
    current = 0
    for profile in profiles:
        if profile.classification is BoundaryClass.UNKNOWN:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _view_evidence(
    frame: CalibratedBoundaryFrame,
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    forward_axis: np.ndarray,
    outward_axis: np.ndarray,
    up_axis: np.ndarray,
    config: CurbEvidenceConfig,
) -> ViewEvidence:
    points, normals, labels, observed, pixels, confidence = arrays
    profiles = tuple(
        _profile_evidence(
            index,
            points[index],
            normals[index],
            labels[index],
            observed[index],
            pixels[index],
            confidence[index],
            outward_axis,
            up_axis,
            config,
        )
        for index in range(points.shape[0])
    )
    supported = [
        profile
        for profile in profiles
        if profile.classification is not BoundaryClass.UNKNOWN
    ]
    continuity = _longest_supported_run(profiles) / len(profiles)
    reasons: list[str] = []
    classification = BoundaryClass.UNKNOWN
    if len(supported) < config.minimum_profiles_per_view or (
        len(supported) / len(profiles)
        < config.minimum_supported_profile_fraction
    ):
        reasons.append("insufficient-supported-profiles")
    elif continuity < config.minimum_continuity_fraction:
        reasons.append("boundary-support-is-discontinuous")
    else:
        counts = {
            state: sum(item.classification is state for item in supported)
            for state in (
                BoundaryClass.ROAD_EDGE,
                BoundaryClass.SHOULDER,
                BoundaryClass.CURB,
            )
        }
        winner = max(counts, key=counts.get)
        if counts[winner] / len(supported) < config.minimum_class_agreement_fraction:
            reasons.append("profile-classes-disagree")
        else:
            winning_profiles = [
                profile
                for profile in supported
                if profile.classification is winner
                and profile.lower_point_world is not None
            ]
            edge_points = np.asarray(
                [profile.lower_point_world for profile in winning_profiles],
                dtype=np.float64,
            )
            edge_delta = np.diff(edge_points, axis=0)
            edge_gap = np.linalg.norm(edge_delta, axis=1)
            positive_gap = edge_gap[edge_gap > 1.0e-9]
            along_delta = edge_delta @ forward_axis
            if not len(positive_gap) or np.max(edge_gap) > (
                config.maximum_consecutive_edge_gap_ratio
                * float(np.median(positive_gap))
            ):
                reasons.append("boundary-world-geometry-is-discontinuous")
            elif np.any(along_delta < -0.20 * float(np.median(positive_gap))):
                reasons.append("boundary-profile-order-reverses")
            else:
                classification = winner
    camera_center = np.asarray(frame.camera_to_world, dtype=np.float64)[:3, 3]
    return ViewEvidence(
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        classification=classification,
        reasons=tuple(reasons),
        profiles=profiles,
        supported_profiles=len(supported),
        continuity_fraction=float(continuity),
        camera_center_world=tuple(float(value) for value in camera_center),
        evidence_sha256=_frame_digest(frame),
    )


def _select_nonadjacent_views(
    views: Sequence[ViewEvidence], gap: int
) -> list[ViewEvidence]:
    result: list[ViewEvidence] = []
    for view in sorted(views, key=lambda item: (item.frame_index, item.frame_id)):
        if not result or view.frame_index - result[-1].frame_index >= gap:
            result.append(view)
    return result


def _unknown_bundle(
    *,
    boundary_id: str,
    reasons: Sequence[str],
    views: Sequence[ViewEvidence],
    provenance: CurbEvidenceProvenance,
    config: CurbEvidenceConfig,
    axes: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> CurbEvidenceBundle:
    forward, outward, up = axes
    return CurbEvidenceBundle(
        boundary_id=boundary_id,
        classification=BoundaryClass.UNKNOWN,
        reasons=tuple(dict.fromkeys(reasons)),
        views=tuple(views),
        selected_frame_ids=(),
        step_height_world_units=None,
        step_height_metres=None,
        edge_evidence_points_world=(),
        provenance=provenance,
        config=config,
        forward_axis_world=tuple(float(value) for value in forward),
        outward_axis_world=tuple(float(value) for value in outward),
        up_axis_world=tuple(float(value) for value in up),
    )


def build_curb_evidence(
    frames: Sequence[CalibratedBoundaryFrame],
    provenance: CurbEvidenceProvenance,
    *,
    boundary_id: str,
    forward_axis_world: Sequence[float],
    outward_axis_world: Sequence[float],
    up_axis_world: Sequence[float],
    config: CurbEvidenceConfig | None = None,
) -> CurbEvidenceBundle:
    """Classify one observed road-boundary track from separated views.

    Malformed calibration/provenance raises :class:`CurbEvidenceError`.
    Missing, occluded, layered, or disagreeing physical evidence returns an
    explicit ``unknown`` bundle with reasons.
    """

    active_config = config or CurbEvidenceConfig()
    active_config.validate()
    provenance.validate()
    if (
        not isinstance(boundary_id, str)
        or not boundary_id.strip()
        or any(character in boundary_id for character in ("/", "\\", ":"))
    ):
        raise CurbEvidenceError("boundary_id must be a non-path identifier")
    axes = _validate_axes(
        forward_axis_world, outward_axis_world, up_axis_world
    )
    forward, outward, up = axes
    if not frames:
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("no-calibrated-views",),
            views=(),
            provenance=provenance,
            config=active_config,
            axes=axes,
        )
    frame_ids = [frame.frame_id for frame in frames]
    frame_indices = [frame.frame_index for frame in frames]
    if len(set(frame_ids)) != len(frame_ids) or len(set(frame_indices)) != len(
        frame_indices
    ):
        raise CurbEvidenceError("frame identifiers and indices must be unique")

    views = []
    for frame in sorted(frames, key=lambda item: (item.frame_index, item.frame_id)):
        arrays = _validate_frame(frame, active_config)
        views.append(
            _view_evidence(frame, arrays, forward, outward, up, active_config)
        )
    if any(
        profile.reason == "stacked-road-or-multiple-road-runs"
        for view in views
        for profile in view.profiles
    ):
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("stacked-road-evidence",),
            views=views,
            provenance=provenance,
            config=active_config,
            axes=axes,
        )

    eligible = [
        view
        for view in views
        if view.classification is not BoundaryClass.UNKNOWN
    ]
    selected = _select_nonadjacent_views(
        eligible, active_config.minimum_nonadjacent_frame_gap
    )
    if len(selected) < active_config.minimum_views:
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("insufficient-separated-views",),
            views=views,
            provenance=provenance,
            config=active_config,
            axes=axes,
        )
    classes = {view.classification for view in eligible}
    if len(classes) != 1:
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("separated-views-disagree",),
            views=views,
            provenance=provenance,
            config=active_config,
            axes=axes,
        )
    classification = next(iter(classes))
    selected_profiles = [
        profile
        for view in selected
        for profile in view.profiles
        if profile.classification is classification
        and profile.lower_point_world is not None
    ]
    edge_points = np.asarray(
        [profile.lower_point_world for profile in selected_profiles],
        dtype=np.float64,
    )
    along = edge_points @ forward
    edge_span = float(np.max(along) - np.min(along))
    sampling = np.asarray(
        [profile.sampling_scale_world_units for profile in selected_profiles],
        dtype=np.float64,
    )
    sampling_scale = float(np.median(sampling))
    if not math.isfinite(edge_span) or edge_span < 2.0 * sampling_scale:
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("boundary-has-insufficient-world-space-continuity",),
            views=views,
            provenance=provenance,
            config=active_config,
            axes=axes,
        )

    camera_centers = np.asarray(
        [view.camera_center_world for view in selected], dtype=np.float64
    )
    baseline = min(
        float(np.linalg.norm(camera_centers[first] - camera_centers[second]))
        for first in range(len(camera_centers))
        for second in range(first + 1, len(camera_centers))
    )
    if baseline / edge_span < active_config.minimum_camera_baseline_to_edge_span:
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("calibrated-view-baseline-is-insufficient",),
            views=views,
            provenance=provenance,
            config=active_config,
            axes=axes,
        )

    view_centroids = np.asarray(
        [
            np.median(
                np.asarray(
                    [
                        profile.lower_point_world
                        for profile in view.profiles
                        if profile.classification is classification
                        and profile.lower_point_world is not None
                    ],
                    dtype=np.float64,
                ),
                axis=0,
            )
            for view in selected
        ]
    )
    center = np.median(view_centroids, axis=0)
    dispersion = float(np.max(np.linalg.norm(view_centroids - center, axis=1)))
    if dispersion / edge_span > active_config.maximum_view_edge_dispersion_to_span:
        return _unknown_bundle(
            boundary_id=boundary_id,
            reasons=("multi-view-edge-location-is-inconsistent",),
            views=views,
            provenance=provenance,
            config=active_config,
            axes=axes,
        )

    step_height: float | None = None
    step_metres: float | None = None
    if classification is BoundaryClass.CURB:
        per_view_steps = np.asarray(
            [
                np.median(
                    [
                        profile.step_height_world_units
                        for profile in view.profiles
                        if profile.classification is BoundaryClass.CURB
                        and profile.step_height_world_units is not None
                    ]
                )
                for view in selected
            ],
            dtype=np.float64,
        )
        step_height = float(np.median(per_view_steps))
        relative_mad = float(
            np.median(np.abs(per_view_steps - step_height))
            / max(step_height, np.finfo(np.float64).eps)
        )
        relative_deviation = float(
            np.max(np.abs(per_view_steps - step_height))
            / max(step_height, np.finfo(np.float64).eps)
        )
        if (
            relative_mad > active_config.maximum_step_relative_mad
            or relative_deviation
            > active_config.maximum_step_relative_deviation
        ):
            return _unknown_bundle(
                boundary_id=boundary_id,
                reasons=("multi-view-step-height-is-inconsistent",),
                views=views,
                provenance=provenance,
                config=active_config,
                axes=axes,
            )
        if provenance.scale_provenance == "metric-anchored":
            assert provenance.world_units_per_metre is not None
            step_metres = step_height / float(provenance.world_units_per_metre)

    ordered_evidence = tuple(
        tuple(float(value) for value in point)
        for point in edge_points[np.argsort(along, kind="stable")]
    )
    return CurbEvidenceBundle(
        boundary_id=boundary_id,
        classification=classification,
        reasons=(),
        views=tuple(views),
        selected_frame_ids=tuple(view.frame_id for view in selected),
        step_height_world_units=step_height,
        step_height_metres=step_metres,
        edge_evidence_points_world=ordered_evidence,
        provenance=provenance,
        config=active_config,
        forward_axis_world=tuple(float(value) for value in forward),
        outward_axis_world=tuple(float(value) for value in outward),
        up_axis_world=tuple(float(value) for value in up),
    )
