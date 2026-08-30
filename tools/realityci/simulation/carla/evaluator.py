"""Deterministic route geometry and driving outcome helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RouteMetrics:
    progress: float
    lateral_error_m: float
    centerline_index: int


def route_metrics(centerline: list[tuple[float, float, float]], position: tuple[float, float, float], previous_index: int = 0) -> RouteMetrics:
    if len(centerline) < 2:
        raise ValueError("route centerline requires at least two points")
    points_3d = np.asarray(centerline, dtype=np.float64)
    query_3d = np.asarray(position, dtype=np.float64)
    # Lane departure is planar. Generated OpenDRIVE meshes may resolve
    # elevation differently from the reconstruction route, so Z is not a
    # lateral error and must not reject an otherwise on-road CARLA actor.
    points = points_3d[:, :2]
    query = query_3d[:2]
    if not np.all(np.isfinite(points)) or not np.all(np.isfinite(query)):
        raise ValueError("route geometry must be finite")
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(segment_lengths.sum())
    if total <= 1e-9:
        raise ValueError("route has zero length")
    best_distance = math.inf
    best_progress = 0.0
    best_index = max(0, min(previous_index, len(points) - 2))
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    for index in range(best_index, len(points) - 1):
        delta = points[index + 1] - points[index]
        length_sq = float(delta @ delta)
        amount = max(0.0, min(1.0, float((query - points[index]) @ delta / length_sq)))
        projected = points[index] + amount * delta
        distance = float(np.linalg.norm(query - projected))
        if distance < best_distance:
            best_distance = distance
            best_progress = float((cumulative[index] + amount * segment_lengths[index]) / total)
            best_index = index
    return RouteMetrics(progress=max(0.0, min(1.0, best_progress)), lateral_error_m=best_distance, centerline_index=best_index)


def classify_infrastructure_invalid(reason: str) -> bool:
    normalized = reason.lower()
    return any(
        token in normalized
        for token in (
            "sensor desynchronization",
            "renderer out of support",
            "server crash",
            "invalid opendrive",
            "map alignment",
            "coordinate transform",
            "missing runtime",
        )
    )
