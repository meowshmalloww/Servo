"""Extract and validate a bounded road corridor from registered camera poses."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ExtractedCorridor:
    source_points_servo: np.ndarray
    centerline_carla: np.ndarray
    carla_from_servo: np.ndarray
    servo_from_carla: np.ndarray
    maximum_smoothing_deviation_m: float
    inferred_choices: tuple[str, ...]


def _segment_intersection(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> bool:
    def orientation(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> float:
        return float((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]))
    o1, o2, o3, o4 = orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b)
    return o1 * o2 < -1e-9 and o3 * o4 < -1e-9


def _resample(points: np.ndarray, interval_m: float) -> np.ndarray:
    segment = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segment)))
    if cumulative[-1] < max(2.0, interval_m * 2):
        raise ValueError("registered camera corridor is too short for a drivable route")
    distances = np.arange(0.0, cumulative[-1], interval_m)
    if not math.isclose(float(distances[-1]), float(cumulative[-1])):
        distances = np.append(distances, cumulative[-1])
    return np.column_stack([np.interp(distances, cumulative, points[:, axis]) for axis in range(3)])


def extract_camera_corridor(
    cameras_path: Path,
    meters_per_servo_unit: float,
    *,
    reverse: bool = False,
    camera_to_lane_center_offset_m: float = 0.0,
    smoothing_window: int = 5,
    resample_interval_m: float = 1.0,
    maximum_smoothing_deviation_m: float = 1.5,
) -> ExtractedCorridor:
    if not math.isfinite(meters_per_servo_unit) or meters_per_servo_unit <= 0:
        raise ValueError("an explicit positive metric scale anchor is required")
    payload = json.loads(cameras_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "servo.gaussian-cameras/v1":
        raise ValueError("unsupported or missing Servo camera schema")
    cameras = payload.get("cameras")
    if not isinstance(cameras, list) or len(cameras) < 3:
        raise ValueError("at least three registered camera poses are required")
    positions: list[list[float]] = []
    ups: list[np.ndarray] = []
    for index, camera in enumerate(cameras):
        matrix = np.asarray(camera.get("cameraToWorldNormalized"), dtype=np.float64)
        if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
            raise ValueError(f"camera {index} has an invalid cameraToWorldNormalized matrix")
        positions.append(matrix[:3, 3].tolist())
        up = -matrix[:3, 1]
        if ups and float(up @ ups[0]) < 0:
            up = -up
        ups.append(up / np.linalg.norm(up))
    source = np.asarray(positions, dtype=np.float64)
    if reverse:
        source = source[::-1].copy()
    up = np.mean(np.asarray(ups), axis=0)
    up /= np.linalg.norm(up)
    forward = source[min(len(source) - 1, max(2, len(source) // 12))] - source[0]
    forward -= up * float(forward @ up)
    if np.linalg.norm(forward) < 1e-9:
        raise ValueError("camera corridor has no stable forward direction")
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    up /= np.linalg.norm(up)
    origin = source[0]
    rotation = np.vstack((forward, right, up))
    carla_from_servo = np.eye(4, dtype=np.float64)
    carla_from_servo[:3, :3] = rotation * meters_per_servo_unit
    carla_from_servo[:3, 3] = -(rotation @ origin) * meters_per_servo_unit
    servo_from_carla = np.linalg.inv(carla_from_servo)
    road = np.column_stack(
        (
            (source - origin) @ forward,
            (source - origin) @ right,
            (source - origin) @ up,
        )
    ) * meters_per_servo_unit
    steps = np.linalg.norm(np.diff(road, axis=0), axis=1)
    nonzero = steps[steps > 1e-6]
    if nonzero.size < 2:
        raise ValueError("registered camera path contains insufficient movement")
    median = float(np.median(nonzero))
    if float(np.max(nonzero)) > max(10.0, median * 12.0):
        raise ValueError("registered camera path contains an impossible discontinuity")
    window = max(1, min(int(smoothing_window), len(road) // 2 * 2 + 1))
    if window % 2 == 0:
        window += 1
    padded = np.pad(road, ((window // 2, window // 2), (0, 0)), mode="edge")
    kernel = np.full(window, 1.0 / window)
    smooth = np.column_stack([np.convolve(padded[:, axis], kernel, mode="valid") for axis in range(3)])
    smooth[0], smooth[-1] = road[0], road[-1]
    deviation = float(np.max(np.linalg.norm(smooth - road, axis=1)))
    if deviation > maximum_smoothing_deviation_m:
        raise ValueError(
            f"path smoothing deviation {deviation:.3f} m exceeds configured maximum "
            f"{maximum_smoothing_deviation_m:.3f} m"
        )
    centerline = _resample(smooth, resample_interval_m)
    tangents = np.gradient(centerline[:, :2], axis=0)
    tangent_norm = np.linalg.norm(tangents, axis=1)
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0])) / tangent_norm[:, None]
    centerline[:, :2] += normals * camera_to_lane_center_offset_m
    for first in range(len(centerline) - 3):
        for second in range(first + 2, len(centerline) - 1):
            if _segment_intersection(centerline[first, :2], centerline[first + 1, :2], centerline[second, :2], centerline[second + 1, :2]):
                raise ValueError("camera path self-intersects; junction topology is not supported")
    headings = np.unwrap(np.arctan2(np.diff(centerline[:, 1]), np.diff(centerline[:, 0])))
    ds = np.maximum(np.linalg.norm(np.diff(centerline[:, :2], axis=0), axis=1), 1e-6)
    curvature = np.abs(np.diff(headings) / ds[1:]) if len(headings) > 1 else np.array([0.0])
    if curvature.size and float(curvature.max()) > 0.35:
        raise ValueError(f"corridor curvature {float(curvature.max()):.3f} 1/m exceeds safe bound 0.35")
    grade = np.abs(np.diff(centerline[:, 2]) / ds)
    if grade.size and float(grade.max()) > 0.20:
        raise ValueError(f"corridor grade {float(grade.max()):.3f} exceeds safe bound 0.20")
    return ExtractedCorridor(
        source_points_servo=source,
        centerline_carla=centerline,
        carla_from_servo=carla_from_servo,
        servo_from_carla=servo_from_carla,
        maximum_smoothing_deviation_m=deviation,
        inferred_choices=(
            "road topology inferred from registered camera order",
            "road-aligned frame uses initial corridor heading and mean camera up",
            f"camera path smoothed with window {window}",
            f"centerline resampled every {resample_interval_m:.3f} m",
        ),
    )
