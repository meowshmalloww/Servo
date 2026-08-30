"""Deterministic validation and emergency braking between policy and CARLA."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..schemas.driving import DirectVehicleControl, TrajectoryAction


@dataclass(frozen=True)
class SafetyResult:
    valid: bool
    control: DirectVehicleControl
    errors: tuple[str, ...]
    emergency_braking: bool


class ActionSafetyGuard:
    def __init__(self, *, maximum_action_age_frames: int = 3, maximum_steering_slew_per_step: float = 0.35, emergency_brake: float = 1.0) -> None:
        self.maximum_action_age_frames = maximum_action_age_frames
        self.maximum_steering_slew_per_step = maximum_steering_slew_per_step
        self.emergency_brake = emergency_brake
        self._last_steer = 0.0

    def reset(self) -> None:
        self._last_steer = 0.0

    def emergency(self, reason: str) -> SafetyResult:
        return SafetyResult(False, DirectVehicleControl(steer=self._last_steer, throttle=0.0, brake=self.emergency_brake), (reason,), True)

    def validate_control(self, action: DirectVehicleControl, *, observation_frame: int, current_frame: int, inference_latency_ms: float, deadline_ms: float) -> SafetyResult:
        errors: list[str] = []
        values = (action.steer, action.throttle, action.brake)
        if not all(math.isfinite(value) for value in values):
            errors.append("control contains NaN or infinity")
        if not -1.0 <= action.steer <= 1.0:
            errors.append("steer is outside [-1, 1]")
        if not 0.0 <= action.throttle <= 1.0 or not 0.0 <= action.brake <= 1.0:
            errors.append("throttle or brake is outside [0, 1]")
        if current_frame - observation_frame > self.maximum_action_age_frames:
            errors.append("action is stale")
        if inference_latency_ms > deadline_ms:
            errors.append("policy deadline exceeded")
        if action.throttle > 0.25 and action.brake > 0.25:
            errors.append("simultaneous high throttle and brake")
        if errors:
            return self.emergency("; ".join(errors))
        steering_delta = action.steer - self._last_steer
        if abs(steering_delta) > self.maximum_steering_slew_per_step:
            # A finite fresh action with an abrupt steer is recoverable. Apply
            # a deterministic rate limit instead of parking the car for an
            # entire low-rate VLM interval. Truly invalid/stale/deadline-failed
            # controls still take the fail-closed path above.
            clamped_steer = self._last_steer + math.copysign(
                self.maximum_steering_slew_per_step, steering_delta
            )
            clamped = action.model_copy(update={"steer": clamped_steer})
            self._last_steer = clamped_steer
            return SafetyResult(
                True,
                clamped,
                ("steering slew clamped",),
                False,
            )
        self._last_steer = action.steer
        return SafetyResult(True, action, (), False)

    def validate_trajectory(self, action: TrajectoryAction) -> tuple[str, ...]:
        errors: list[str] = []
        previous_time = 0.0
        previous_x = -math.inf
        for waypoint in action.waypoints:
            if not all(math.isfinite(value) for value in (waypoint.time_offset_s, waypoint.x_forward_m, waypoint.y_left_m)):
                errors.append("trajectory contains NaN or infinity")
                break
            if waypoint.time_offset_s <= previous_time:
                errors.append("trajectory timestamps are not strictly ordered")
            if waypoint.x_forward_m < previous_x - 0.5:
                errors.append("trajectory reverses longitudinal ordering")
            previous_time, previous_x = waypoint.time_offset_s, waypoint.x_forward_m
        return tuple(errors)
