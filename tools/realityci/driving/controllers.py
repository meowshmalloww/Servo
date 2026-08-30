"""Deterministic pure-pursuit lateral and bounded PID longitudinal control."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..schemas.driving import DirectVehicleControl, TrajectoryAction


@dataclass(frozen=True)
class ControllerConfig:
    wheelbase_m: float = 2.85
    lookahead_m: float = 4.0
    maximum_steering_angle_rad: float = 0.70
    speed_kp: float = 0.35
    speed_ki: float = 0.05
    speed_kd: float = 0.02
    integral_limit: float = 4.0
    maximum_throttle: float = 0.45
    maximum_brake: float = 1.0


class PurePursuitPidController:
    VERSION = "servo-pure-pursuit-pid-carla-handedness/v2"

    def __init__(self, config: ControllerConfig = ControllerConfig()) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        self._integral = 0.0
        self._last_error = 0.0

    def control(self, trajectory: TrajectoryAction, speed_mps: float, delta_seconds: float) -> DirectVehicleControl:
        if delta_seconds <= 0 or not math.isfinite(delta_seconds):
            raise ValueError("controller delta_seconds must be finite and positive")
        waypoint = min(
            trajectory.waypoints,
            key=lambda point: abs(math.hypot(point.x_forward_m, point.y_left_m) - self.config.lookahead_m),
        )
        lookahead = max(0.5, math.hypot(waypoint.x_forward_m, waypoint.y_left_m))
        alpha = math.atan2(waypoint.y_left_m, max(0.05, waypoint.x_forward_m))
        steering_angle = math.atan2(2.0 * self.config.wheelbase_m * math.sin(alpha), lookahead)
        # TrajectoryAction is expressed in the conventional vehicle frame
        # (x forward, y left). CARLA/Unreal uses x forward, y right, and its
        # own manual-control implementation maps a left turn to negative
        # VehicleControl.steer. Convert at this single actuator boundary.
        steer = max(-1.0, min(1.0, -steering_angle / self.config.maximum_steering_angle_rad))
        error = trajectory.desired_speed_mps - speed_mps
        self._integral = max(-self.config.integral_limit, min(self.config.integral_limit, self._integral + error * delta_seconds))
        derivative = (error - self._last_error) / delta_seconds
        self._last_error = error
        command = self.config.speed_kp * error + self.config.speed_ki * self._integral + self.config.speed_kd * derivative
        # A DriveMA inference is held until the next policy tick. Bound the
        # actuator so a one-second inference interval cannot create the large
        # speed overshoot observed in sim-fb3b9f8f5f29491b.
        throttle = max(0.0, min(self.config.maximum_throttle, command))
        brake = max(0.0, min(self.config.maximum_brake, -command))
        return DirectVehicleControl(steer=steer, throttle=throttle, brake=brake)
