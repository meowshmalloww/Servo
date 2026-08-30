"""Physical CARLA reference controller for a sealed reconstructed corridor."""

from __future__ import annotations

import math

from ...schemas.driving import (
    DirectVehicleControl,
    DrivingPolicyDescriptor,
    TrajectoryAction,
    TrajectoryWaypoint,
)
from ..contracts import DrivingObservation, DrivingPolicyAdapter, PolicyResetContext
from ..controllers import ControllerConfig, PurePursuitPidController


class CarlaBehaviorReferencePolicy(DrivingPolicyAdapter):
    """Follow the hash-sealed world route with real CARLA vehicle physics.

    The legacy class name remains for manifest compatibility.  This policy no
    longer projects the reconstructed route through CARLA's sparse waypoint
    graph: that graph ended before T5's visual route and caused the vehicle to
    leave the observed Gaussian corridor.  It consumes the route supplied by
    the execution manifest and never embeds scene-specific coordinates.
    """

    VERSION = "servo-carla-sealed-corridor-15kmh/v5"

    def __init__(self, behavior: str = "cautious", target_speed_kmh: float = 15.0) -> None:
        self.behavior = behavior
        self.target_speed_kmh = target_speed_kmh
        self._vehicle = None
        self._route: tuple[tuple[float, float, float], ...] = ()
        self._route_index = 0
        self._controller = PurePursuitPidController(
            ControllerConfig(
                lookahead_m=2.5,
                speed_kp=0.32,
                speed_ki=0.04,
                speed_kd=0.015,
            )
        )
        self._descriptor = DrivingPolicyDescriptor(
            adapter="carla-behavior-reference", name="CARLA sealed-corridor reference",
            adapter_version=self.VERSION, oracle=True,
            uses_privileged_state=True, trainable=False, eligible_for_promotion=False,
        )

    @property
    def descriptor(self) -> DrivingPolicyDescriptor:
        return self._descriptor

    def reset(self, context: PolicyResetContext) -> None:
        if context.vehicle is None:
            raise ValueError("CARLA corridor reference requires a privileged vehicle handle")
        if len(context.route) < 2:
            raise ValueError("CARLA corridor reference requires a sealed route with at least two points")
        self._vehicle = context.vehicle
        self._route = tuple(tuple(float(value) for value in point) for point in context.route)
        self._route_index = 0
        self._controller.reset()

    def _trajectory(self) -> TrajectoryAction:
        if self._vehicle is None or not self._route:
            raise RuntimeError("CARLA corridor reference was not reset")
        transform = self._vehicle.get_transform()
        location = transform.location
        search_start = max(0, self._route_index - 2)
        self._route_index = min(
            range(search_start, len(self._route)),
            key=lambda index: (
                (self._route[index][0] - float(location.x)) ** 2
                + (self._route[index][1] - float(location.y)) ** 2
                + (self._route[index][2] - float(location.z)) ** 2
            ),
        )
        yaw = math.radians(float(transform.rotation.yaw))
        forward_x, forward_y = math.cos(yaw), math.sin(yaw)
        # CARLA/Unreal uses +Y to the vehicle's right. TrajectoryWaypoint is
        # explicitly y-left-positive, so negate CARLA's right basis here.
        left_x, left_y = forward_y, -forward_x
        route_points: list[TrajectoryWaypoint] = []
        for index in range(self._route_index + 1, min(len(self._route), self._route_index + 9)):
            point = self._route[index]
            delta_x = point[0] - float(location.x)
            delta_y = point[1] - float(location.y)
            x_forward = delta_x * forward_x + delta_y * forward_y
            y_left = delta_x * left_x + delta_y * left_y
            if x_forward < -0.25:
                continue
            route_points.append(
                TrajectoryWaypoint(
                    time_offset_s=0.2 * (len(route_points) + 1),
                    x_forward_m=x_forward,
                    y_left_m=y_left,
                )
            )
        if len(route_points) < 2:
            # The simulation terminates before this final hold is normally
            # consumed.  Keeping a valid stationary trajectory makes endpoint
            # behavior fail closed instead of dereferencing a missing CARLA
            # waypoint as the stock BehaviorAgent did.
            route_points = [
                TrajectoryWaypoint(time_offset_s=0.2, x_forward_m=0.25, y_left_m=0.0),
                TrajectoryWaypoint(time_offset_s=0.4, x_forward_m=0.50, y_left_m=0.0),
            ]
            desired_speed = 0.0
        else:
            desired_speed = self.target_speed_kmh / 3.6
        return TrajectoryAction(
            waypoints=tuple(route_points),
            desired_speed_mps=desired_speed,
            confidence=1.0,
        )

    def infer(self, observation: DrivingObservation) -> DirectVehicleControl:
        trajectory = self._trajectory()
        control = self._controller.control(trajectory, observation.ego_speed_mps, 0.05)
        return DirectVehicleControl(
            steer=max(-0.8, min(0.8, float(control.steer))),
            throttle=min(0.60, float(control.throttle)),
            brake=min(0.55, float(control.brake)),
            hand_brake=False,
            reverse=False,
        )
