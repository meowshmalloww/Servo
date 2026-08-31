from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tools.realityci.schemas.driving import (
    DrivingOutcome,
    DrivingPolicyDescriptor,
    DrivingRunEvidence,
    DrivingRunMetrics,
    ObservationSource,
)
from tools.realityci.schemas.simulation import SimulationSessionState
from tools.realityci.simulation.carla.evaluator import terminal_route_validation
from tools.realityci.simulation.carla.runner import _evidence_artifact_names


_HASH = "sha256:" + "1" * 64


def _metrics(completion: float, *, frames: int = 20) -> DrivingRunMetrics:
    return DrivingRunMetrics(
        simulation_duration_s=1.0,
        fixed_delta_seconds=0.05,
        frame_count=frames,
        distance_traveled_m=2.0,
        route_completion=completion,
        min_speed_mps=0.0,
        max_speed_mps=2.0,
        final_speed_mps=0.0,
        mean_lateral_error_m=0.1,
        max_lateral_error_m=0.2,
        mean_policy_latency_ms=1.0,
        max_policy_latency_ms=2.0,
        deadline_misses=0,
        sensor_sync_failures=0,
        collision_count=0,
        lane_invasion_count=0,
        out_of_support_duration_s=0.0,
    )


def _evidence(completion: float, outcome: DrivingOutcome, *, frames: int = 20):
    return DrivingRunEvidence(
        session_id="sim-0123456789abcdef",
        executable_world_sha256=_HASH,
        opendrive_sha256=_HASH,
        appearance_sha256=_HASH,
        route_sha256=_HASH,
        carla_version="0.9.16",
        carla_executable_sha256=_HASH,
        carla_python_api_version="0.9.16",
        policy=DrivingPolicyDescriptor(
            adapter="carla-behavior-reference",
            name="route-validation-test",
            adapter_version="test/v1",
        ),
        controller_version="test-controller/v1",
        renderer_version="test-renderer/v1",
        observation_source=ObservationSource.SERVO_GAUSSIAN,
        seed=1,
        metrics=_metrics(completion, frames=frames),
        outcome=outcome,
        artifact_sha256={},
        created_at=datetime.now(timezone.utc),
    )


def test_zero_percent_is_starting_pose_only_and_never_a_pass() -> None:
    receipt = terminal_route_validation(
        route_completion=0.0,
        frame_count=0,
        outcome=DrivingOutcome.INFRASTRUCTURE_INVALID,
        session_state=SimulationSessionState.FAILED,
    )
    assert receipt["classification"] == "starting-pose-only"
    assert receipt["starting_pose_only"] is True
    assert receipt["terminal_execution"] is True
    assert receipt["accepted_as_route_pass"] is False


def test_partial_terminal_timeout_is_visible_but_cannot_pass() -> None:
    receipt = terminal_route_validation(
        route_completion=0.6186965293,
        frame_count=360,
        outcome=DrivingOutcome.TIMEOUT,
        session_state=SimulationSessionState.COMPLETED,
    )
    assert receipt["classification"] == "terminal-partial-or-failed"
    assert receipt["route_completion"] == pytest.approx(0.6186965293)
    assert receipt["accepted_as_route_pass"] is False


def test_terminal_route_validation_rejects_incomplete_success() -> None:
    with pytest.raises(ValueError, match="below 0.90"):
        terminal_route_validation(
            route_completion=0.61,
            frame_count=100,
            outcome=DrivingOutcome.SUCCESS,
            session_state=SimulationSessionState.COMPLETED,
        )
    with pytest.raises(ValueError, match="completed session state"):
        terminal_route_validation(
            route_completion=0.95,
            frame_count=100,
            outcome=DrivingOutcome.SUCCESS,
            session_state=SimulationSessionState.RUNNING,
        )


def test_terminal_route_validation_accepts_only_thresholded_success() -> None:
    receipt = terminal_route_validation(
        route_completion=0.90,
        frame_count=100,
        outcome=DrivingOutcome.SUCCESS,
        session_state=SimulationSessionState.COMPLETED,
    )
    assert receipt["accepted_as_route_pass"] is True
    assert receipt["classification"] == "pass"


def test_driving_evidence_schema_rejects_success_below_route_gate() -> None:
    with pytest.raises(ValidationError, match="route completion"):
        _evidence(0.899, DrivingOutcome.SUCCESS)
    with pytest.raises(ValidationError, match="authoritative physics frames"):
        _evidence(0.95, DrivingOutcome.SUCCESS, frames=0)
    assert _evidence(0.90, DrivingOutcome.SUCCESS).outcome == DrivingOutcome.SUCCESS
    partial = _evidence(0.61, DrivingOutcome.TIMEOUT)
    assert partial.metrics.route_completion == pytest.approx(0.61)


def test_route_validation_receipt_is_sealed_into_run_artifacts() -> None:
    assert "route-validation.json" in _evidence_artifact_names(("front",))
