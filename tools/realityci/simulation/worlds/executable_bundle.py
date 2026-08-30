"""Publish content-addressed executable-world companions without fabricating validation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ...hashing import canonical_json_bytes, sha256_digest, sha256_file
from ...schemas.driving import Pose, Quaternion, Vector3
from ...schemas.simulation import ExecutableWorldDescriptor
from ..session_store import atomic_write_json
from .opendrive_generator import generate_single_corridor_opendrive
from .opendrive_validator import validate_opendrive
from .path_extractor import extract_camera_corridor


@dataclass(frozen=True)
class PreparationConfig:
    meters_per_servo_unit: float
    scale_status: str
    scale_source: str
    scale_uncertainty_fraction: float
    lane_width_m: float = 3.5
    shoulder_width_m: float = 0.5
    driving_side: str = "right"
    route_direction: str = "forward"
    camera_path_role: str = "vehicle-center"
    camera_to_lane_center_offset_m: float = 0.0
    camera_height_above_road_m: float = 1.4
    road_endpoint_padding_m: float = 6.0
    maximum_smoothing_deviation_m: float = 1.5
    include_opposing_lane: bool = False

    def validate(self) -> None:
        if self.scale_status not in {"measured", "inferred"}:
            raise ValueError("scale_status must be measured or inferred")
        if not self.scale_source.strip():
            raise ValueError("scale_source is required")
        if not math.isfinite(self.meters_per_servo_unit) or self.meters_per_servo_unit <= 0:
            raise ValueError("an explicit positive metric scale anchor is required")
        if not 0 <= self.scale_uncertainty_fraction <= 1:
            raise ValueError("scale uncertainty must be between zero and one")
        if self.route_direction not in {"forward", "reverse"}:
            raise ValueError("route_direction must be forward or reverse")
        if self.camera_path_role not in {"lane-center", "vehicle-center", "offset"}:
            raise ValueError("camera_path_role must be lane-center, vehicle-center, or offset")
        if not math.isfinite(self.camera_height_above_road_m) or not 0.5 <= self.camera_height_above_road_m <= 3.0:
            raise ValueError("camera_height_above_road_m must be between 0.5 and 3.0 meters")
        if not math.isfinite(self.road_endpoint_padding_m) or not 3.0 <= self.road_endpoint_padding_m <= 20.0:
            raise ValueError("road_endpoint_padding_m must be between 3 and 20 meters")


def _quaternion_for_heading(delta: np.ndarray) -> Quaternion:
    heading = math.atan2(float(delta[1]), float(delta[0]))
    return Quaternion(w=math.cos(heading / 2), x=0.0, y=0.0, z=math.sin(heading / 2))


def inferred_reference_offset_for_driving_lane(lane_width_m: float, driving_side: str) -> float:
    """Offset the OpenDRIVE reference opposite the driven lane.

    In CARLA's left-handed world +Y is physically right for a +X heading,
    while ``offset_reference_line_from_lane_center`` uses the mathematical
    ``(-dy, dx)`` normal (also +Y on that heading).  A right-hand lane thus
    requires a negative reference offset; lane -1 then returns to the observed
    camera/vehicle center.
    """
    if driving_side not in {"right", "left"}:
        raise ValueError("driving_side must be right or left")
    if not math.isfinite(lane_width_m) or not 2.5 <= lane_width_m <= 5.0:
        raise ValueError("lane width must be between 2.5 and 5.0 meters")
    return (-1.0 if driving_side == "right" else 1.0) * lane_width_m / 2.0


def _world_artifacts(world_root: Path) -> tuple[dict, Path, Path]:
    manifest_path = world_root / "world.json"
    if not manifest_path.is_file():
        raise ValueError(f"published Servo world manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "servo.gaussian-world/v1":
        raise ValueError("world.json is not servo.gaussian-world/v1")
    artifacts = manifest.get("artifacts", {})
    ply = (world_root / artifacts.get("ply", "")).resolve()
    cameras = (world_root / artifacts.get("cameras", "cameras.json")).resolve()
    for path, label in ((ply, "Gaussian PLY"), (cameras, "registered cameras")):
        try:
            path.relative_to(world_root.resolve())
        except ValueError as exc:
            raise ValueError(f"{label} escapes the published world root") from exc
        if not path.is_file():
            raise ValueError(f"{label} artifact is missing: {path}")
    return manifest, ply, cameras


def road_centerline_from_camera_path(
    camera_centerline_carla: np.ndarray,
    camera_height_above_road_m: float,
) -> np.ndarray:
    """Return an independent road line below a registered capture camera.

    The input remains untouched so the coordinate transform and Gaussian
    cameras continue to describe measured source poses.  Only the inferred
    OpenDRIVE companion receives the recorded-height offset.
    """
    centerline = np.asarray(camera_centerline_carla, dtype=np.float64)
    if centerline.ndim != 2 or centerline.shape[1] != 3 or len(centerline) < 2:
        raise ValueError("camera centerline must contain at least two XYZ points")
    if not np.all(np.isfinite(centerline)):
        raise ValueError("camera centerline contains non-finite values")
    if not math.isfinite(camera_height_above_road_m) or not 0.5 <= camera_height_above_road_m <= 3.0:
        raise ValueError("camera height above road must be between 0.5 and 3.0 meters")
    road = centerline.copy()
    road[:, 2] -= camera_height_above_road_m
    return road


def offset_reference_line_from_lane_center(
    lane_centerline: np.ndarray,
    camera_to_reference_offset_m: float,
) -> np.ndarray:
    """Create OpenDRIVE's reference line without redefining the driven route.

    OpenDRIVE lane -1 is laterally offset from the planView reference.  The
    registered camera path is evidence for the driven lane center, not for that
    abstract reference line.  Keeping both arrays prevents the controller and
    capture camera from being shifted sideways just to satisfy the road file.
    """
    centerline = np.asarray(lane_centerline, dtype=np.float64)
    if centerline.ndim != 2 or centerline.shape[1] != 3 or len(centerline) < 2:
        raise ValueError("lane centerline must contain at least two XYZ points")
    if not np.all(np.isfinite(centerline)) or not math.isfinite(camera_to_reference_offset_m):
        raise ValueError("lane centerline/reference offset contains non-finite values")
    if math.isclose(camera_to_reference_offset_m, 0.0, abs_tol=1e-12):
        return centerline.copy()
    tangents = np.gradient(centerline[:, :2], axis=0)
    norms = np.linalg.norm(tangents, axis=1)
    if np.any(norms < 1e-9):
        raise ValueError("lane centerline contains a zero-length tangent")
    left_normals = np.column_stack((-tangents[:, 1], tangents[:, 0])) / norms[:, None]
    reference = centerline.copy()
    reference[:, :2] += left_normals * camera_to_reference_offset_m
    return reference


def extend_road_reference_endpoints(reference: np.ndarray, padding_m: float) -> np.ndarray:
    """Add physical road beneath a full vehicle before/after observed poses."""
    points = np.asarray(reference, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.all(np.isfinite(points)):
        raise ValueError("road reference must contain at least two finite XYZ points")
    if not math.isfinite(padding_m) or padding_m < 3.0:
        raise ValueError("road endpoint padding must be at least 3 meters")

    def extended(point: np.ndarray, neighbor: np.ndarray, sign: float) -> np.ndarray:
        delta = neighbor - point
        horizontal = float(np.linalg.norm(delta[:2]))
        if horizontal < 1e-9:
            raise ValueError("road endpoint segment has no horizontal extent")
        direction_xy = delta[:2] / horizontal
        grade = float(delta[2] / horizontal)
        result = point.copy()
        result[:2] += sign * direction_xy * padding_m
        result[2] += sign * grade * padding_m
        return result

    before = extended(points[0], points[1], -1.0)
    after = extended(points[-1], points[-2], -1.0)
    return np.vstack((before, points, after))


def carla_centerline_to_opendrive(reference_carla: np.ndarray) -> np.ndarray:
    """Convert CARLA's left-handed +Y-right points to OpenDRIVE +Y-left."""
    points = np.asarray(reference_carla, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.all(np.isfinite(points)):
        raise ValueError("CARLA road reference must contain at least two finite XYZ points")
    converted = points.copy()
    converted[:, 1] *= -1.0
    return converted


def prepare_inferred_corridor(world_root: Path, output_root: Path, config: PreparationConfig, *, carla_validation: dict | None = None) -> ExecutableWorldDescriptor:
    config.validate()
    world_root = world_root.resolve()
    output_root = output_root.resolve()
    manifest, ply_path, cameras_path = _world_artifacts(world_root)
    camera_to_reference_offset_m = config.camera_to_lane_center_offset_m
    if config.camera_path_role in {"lane-center", "vehicle-center"} and math.isclose(
        camera_to_reference_offset_m, 0.0, abs_tol=1e-9
    ):
        # OpenDRIVE's planView is the road reference line, not the center of
        # lane -1. A right-hand driving lane is half a lane width to the right
        # of that reference. The registered dash-camera path represents the
        # driven lane, so move the reference left by half a lane. Without this
        # correction CARLA legitimately drives beside the T5 photographed lane.
        camera_to_reference_offset_m = inferred_reference_offset_for_driving_lane(
            config.lane_width_m,
            config.driving_side,
        )
    corridor = extract_camera_corridor(
        cameras_path,
        config.meters_per_servo_unit,
        reverse=config.route_direction == "reverse",
        # Validate and retain the observed vehicle/camera lane itself.  The
        # OpenDRIVE reference offset is a separate construction below.
        camera_to_lane_center_offset_m=0.0,
        maximum_smoothing_deviation_m=config.maximum_smoothing_deviation_m,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    xodr_path = output_root / "map.xodr"
    # Registered COLMAP poses describe the capture camera, not the tyre contact
    # patch.  The previous companion put OpenDRIVE directly through that camera
    # path.  A CARLA camera mounted on the Lincoln was therefore lifted a second
    # time and the physical car appeared above/beside the photographed road.
    # Keep the Servo<->CARLA transform anchored to the measured camera path and
    # place the inferred road beneath it by the explicitly recorded camera
    # height.  This remains inferred structure; it is not a metric road claim.
    centerline = road_centerline_from_camera_path(
        corridor.centerline_carla,
        config.camera_height_above_road_m,
    )
    reference_centerline = offset_reference_line_from_lane_center(
        centerline,
        camera_to_reference_offset_m,
    )
    padded_reference_centerline = extend_road_reference_endpoints(
        reference_centerline,
        config.road_endpoint_padding_m,
    )
    opendrive_reference_centerline = carla_centerline_to_opendrive(
        padded_reference_centerline,
    )
    generate_single_corridor_opendrive(
        opendrive_reference_centerline,
        xodr_path,
        lane_width_m=config.lane_width_m,
        shoulder_width_m=config.shoulder_width_m,
        driving_side=config.driving_side,
        include_opposing_lane=config.include_opposing_lane,
    )
    structural = validate_opendrive(xodr_path)
    if not structural.valid:
        raise ValueError("generated OpenDRIVE failed validation: " + "; ".join(structural.errors))
    length_m = float(np.linalg.norm(np.diff(centerline, axis=0), axis=1).sum())
    heading_start = _quaternion_for_heading(centerline[1] - centerline[0])
    heading_end = _quaternion_for_heading(centerline[-1] - centerline[-2])
    points = [Vector3(x=float(point[0]), y=float(point[1]), z=float(point[2])) for point in centerline]
    route_payload = {
        "schema_name": "servo.route/v1",
        "route_id": "primary",
        "centerline_carla": [point.model_dump(mode="json") for point in points],
        "length_m": length_m,
    }
    route_hash = sha256_digest(canonical_json_bytes(route_payload))
    route_payload["route_sha256"] = route_hash
    atomic_write_json(output_root / "route.json", route_payload)
    forward = tuple(float(value) for value in corridor.carla_from_servo.reshape(-1))
    inverse = tuple(float(value) for value in corridor.servo_from_carla.reshape(-1))
    alignment = {
        "schema_name": "servo.coordinate-alignment/v1",
        "carla_from_servo_row_major": forward,
        "servo_from_carla_row_major": inverse,
        "handedness_conversion": "Servo X-right/Y-up/-Z-forward to CARLA X-forward/Y-right/Z-up in a road-aligned local frame",
        "round_trip_error_m": float(np.max(np.abs(corridor.carla_from_servo @ corridor.servo_from_carla - np.eye(4)))),
        "inferred_choices": [
            *corridor.inferred_choices,
            "OpenDRIVE +Y-left converted explicitly from CARLA +Y-right",
            f"OpenDRIVE reference offset {camera_to_reference_offset_m:.3f} m from observed lane center",
            f"OpenDRIVE endpoint padding {config.road_endpoint_padding_m:.3f} m outside the observed route",
            f"road surface offset {config.camera_height_above_road_m:.3f} m below the registered capture camera path",
        ],
    }
    atomic_write_json(output_root / "alignment.json", alignment)
    carla_validated = bool(carla_validation and carla_validation.get("ready"))
    validated_at = datetime.now(timezone.utc)
    base = {
        "schema_name": "servo.world-execution/v1",
        "world_id": manifest["worldId"],
        "appearance": {
            "kind": "servo-gaussian",
            "ply_uri": str(ply_path),
            "world_manifest_uri": str(world_root / "world.json"),
            "appearance_sha256": sha256_file(str(ply_path)),
        },
        "structure": {
            "opendrive_uri": str(xodr_path),
            "opendrive_sha256": sha256_file(str(xodr_path)),
            "road_surface_uri": None,
            "collision_mesh_uri": None,
            "structural_status": "inferred",
        },
        "scale": {
            "status": config.scale_status,
            "meters_per_servo_unit": config.meters_per_servo_unit,
            "uncertainty_fraction": config.scale_uncertainty_fraction,
            "source": config.scale_source,
        },
        "frames": {key: alignment[key] for key in ("carla_from_servo_row_major", "servo_from_carla_row_major", "handedness_conversion", "round_trip_error_m")},
        "routes": [{
            "route_id": "primary",
            "start_pose_carla": Pose(position=points[0], orientation=heading_start).model_dump(mode="json"),
            "goal_pose_carla": Pose(position=points[-1], orientation=heading_end).model_dump(mode="json"),
            "centerline_carla": [point.model_dump(mode="json") for point in points],
            "length_m": length_m,
            "route_sha256": route_hash,
        }],
        "capture_envelope": {
            "source": "registered-camera-corridor",
            "maximum_supported_lateral_offset_m": max(0.5, config.lane_width_m / 2),
            "maximum_supported_vertical_offset_m": 0.75,
            "maximum_supported_heading_difference_deg": 20.0,
        },
        "provenance": {
            "appearance": "observed-reconstruction",
            "road_topology": "inferred-from-camera-path",
            "scale": config.scale_status,
            "generated_content": ("map.xodr", "route.json", "alignment.json"),
            "camera_height_above_road_m": config.camera_height_above_road_m,
            "camera_height_source": "explicit-inferred-capture-rig-prior",
            "road_endpoint_padding_m": config.road_endpoint_padding_m,
        },
        "validation": {
            "structurally_valid": True,
            "carla_validated": carla_validated,
            "ready_for_carla": carla_validated,
            "validated_at": validated_at.isoformat(),
            "validator_version": "servo-opendrive/v1",
            "warnings": () if carla_validated else ("CARLA dry-run has not been completed; Start Drive remains disabled.",),
        },
    }
    # Compute content_hash from the canonical descriptor dump (not the raw base dict)
    # so validation via ExecutableWorldDescriptor round-trip is stable (datetime -> Z).
    placeholder = dict(base)
    placeholder["content_hash"] = "sha256:" + "0" * 64
    descriptor = ExecutableWorldDescriptor.model_validate(placeholder)
    payload = descriptor.model_dump(mode="json")
    payload.pop("content_hash", None)
    content_hash = sha256_digest(canonical_json_bytes(payload))
    descriptor = descriptor.model_copy(update={"content_hash": content_hash})
    atomic_write_json(output_root / "execution-manifest.json", descriptor.model_dump(mode="json"))
    atomic_write_json(
        output_root / "validation-report.json",
        {
            "schema_name": "servo.opendrive-validation/v1",
            "structural": asdict(structural),
            "carla": carla_validation,
            "ready_for_carla": carla_validated,
            "validated_at": validated_at.isoformat(),
        },
    )
    return descriptor
