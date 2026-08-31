"""Deterministic route geometry and driving outcome helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ...schemas.driving import DrivingOutcome, MINIMUM_SUCCESS_ROUTE_COMPLETION
from ...schemas.simulation import SimulationSessionState, TERMINAL_SIMULATION_STATES


@dataclass(frozen=True)
class RouteMetrics:
    progress: float
    lateral_error_m: float
    centerline_index: int


def terminal_route_validation(
    *,
    route_completion: float,
    frame_count: int,
    outcome: DrivingOutcome | str | None,
    session_state: SimulationSessionState | str,
) -> dict[str, object]:
    """Classify a route view and reject every incomplete success claim.

    A terminal simulation state only says that execution ended.  It is not a
    pass by itself.  This receipt keeps a 61% timeout visible as partial
    evidence and a zero-frame 0% worker failure as a starting-pose-only record,
    while making it impossible to serialize either one as a route pass.
    """

    completion = float(route_completion)
    if not math.isfinite(completion) or not 0.0 <= completion <= 1.0:
        raise ValueError("route completion must be finite and inside [0, 1]")
    if int(frame_count) < 0:
        raise ValueError("route frame count cannot be negative")
    normalized_state = SimulationSessionState(session_state)
    normalized_outcome = DrivingOutcome(outcome) if outcome is not None else None
    terminal = normalized_state in TERMINAL_SIMULATION_STATES
    starting_pose_only = completion <= 1e-9 and int(frame_count) == 0

    if terminal and normalized_outcome is None:
        raise ValueError("terminal route evidence requires an explicit outcome")
    if normalized_outcome == DrivingOutcome.SUCCESS:
        if normalized_state != SimulationSessionState.COMPLETED:
            raise ValueError("successful route evidence requires a completed session state")
        if int(frame_count) <= 0:
            raise ValueError("successful route evidence requires authoritative physics frames")
        if completion < MINIMUM_SUCCESS_ROUTE_COMPLETION:
            raise ValueError(
                "route success rejected: completion "
                f"{completion:.6f} is below {MINIMUM_SUCCESS_ROUTE_COMPLETION:.2f}"
            )

    route_pass = (
        terminal
        and normalized_outcome == DrivingOutcome.SUCCESS
        and completion >= MINIMUM_SUCCESS_ROUTE_COMPLETION
        and int(frame_count) > 0
    )
    if route_pass:
        classification = "pass"
    elif starting_pose_only:
        classification = "starting-pose-only"
    elif not terminal:
        classification = "in-progress"
    elif completion <= 1e-9:
        classification = "terminal-no-progress"
    else:
        classification = "terminal-partial-or-failed"
    return {
        "schema": "servo.carla-route-validation/v1",
        "session_state": normalized_state.value,
        "outcome": normalized_outcome.value if normalized_outcome is not None else None,
        "route_completion": completion,
        "required_completion": MINIMUM_SUCCESS_ROUTE_COMPLETION,
        "authoritative_frame_count": int(frame_count),
        "terminal_execution": terminal,
        "starting_pose_only": starting_pose_only,
        "accepted_as_route_pass": route_pass,
        "classification": classification,
    }


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
