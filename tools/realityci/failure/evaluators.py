"""Deterministic run-outcome classifiers.

Pure functions over measured evidence: identical inputs always produce the
identical failure class and severity.
"""

from __future__ import annotations

from typing import Optional

from ..scenario.runner import RunResult
from ..schemas.run import FailureClass, FailureSeverity


LATE_DETECTION_THRESHOLD_S = 0.30
CONTROLLER_MISMATCH_WINDOW_S = 0.20


def classify_failure(
    *,
    result: RunResult,
    detection_delay_s: Optional[float],
    planner_missed: bool,
    controller_mismatch: bool,
    had_pedestrian: bool,
) -> tuple[Optional[FailureClass], Optional[FailureSeverity]]:
    """Return (class, severity) for a completed run, or (None, None) on success.

    Priority order encodes safety review practice: physical contact first,
    then missed actuation, then perception latency, then stall.
    """

    if result == RunResult.COLLISION:
        return FailureClass.COLLISION_WITH_PEDESTRIAN, FailureSeverity.SAFETY_CRITICAL
    if result == RunResult.ROUTE_DEPARTURE:
        return FailureClass.ROUTE_DEPARTURE, FailureSeverity.MAJOR
    if result == RunResult.TIMEOUT:
        return FailureClass.TIMEOUT_STALL, FailureSeverity.MAJOR
    if not had_pedestrian:
        return None, None

    if controller_mismatch:
        return FailureClass.CONTROLLER_EXECUTION_MISMATCH, FailureSeverity.MAJOR

    if (
        detection_delay_s is not None
        and detection_delay_s > LATE_DETECTION_THRESHOLD_S
        and result in (RunResult.NEAR_MISS,)
    ):
        return FailureClass.LATE_DETECTION, FailureSeverity.MAJOR

    if planner_missed and result == RunResult.NEAR_MISS:
        return FailureClass.PLANNER_NO_BRAKE, FailureSeverity.MAJOR

    return None, None


def is_failure(result: RunResult) -> bool:
    return result in (RunResult.COLLISION, RunResult.TIMEOUT)
