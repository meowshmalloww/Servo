"""Authoritative synchronous CARLA closed-loop worker implementation."""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ...driving.contracts import DrivingObservation, PolicyResetContext
from ...driving.controllers import PurePursuitPidController
from ...driving.policies.reference_agent import CarlaBehaviorReferencePolicy
from ...driving.policies.tinydrive import ServoTinyDrivePolicy
from ...driving.safety import ActionSafetyGuard
from ...hashing import canonical_json_bytes, new_record_id, sha256_file
from ...schemas.driving import (
    AppliedVehicleControl,
    DirectVehicleControl,
    DrivingActionRecord,
    DrivingOutcome,
    DrivingRunEvidence,
    DrivingFailureClass,
    DrivingRunMetrics,
    Pose,
    Quaternion,
    RouteCommand,
    TrajectoryAction,
    TrajectoryWaypoint,
    Vector3,
)
from ...schemas.simulation import ProcessHealth, SimulationLiveState, SimulationSessionManifest, SimulationSessionState
from ..rendering.carla_rgb import CarlaRgbObservationRenderer
from ..rendering.base import ObservationRenderRequest
from ..rendering.hybrid_compositor import HybridGaussianCarlaObservationRenderer
from ..rendering.servo_gaussian import ServoGaussianObservationRenderer
from ..session_store import SessionStore, atomic_write_json
from .actors import camera_blueprint, mount_transform, spawn_camera, spawn_ego, spawn_event_sensors
from .cleanup import OwnedActors
from .coordinates import CoordinateTransform, matrix_to_quaternion
from .discovery import carla_import_path
from .evaluator import route_metrics
from .sensor_barrier import SensorBarrier
from .world_loader import configure_synchronous_world, load_executable_world


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(payload) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _quaternion_from_carla(rotation) -> Quaternion:
    roll, pitch, yaw = map(math.radians, (rotation.roll, rotation.pitch, rotation.yaw))
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return Quaternion(w=cr * cp * cy + sr * sp * sy, x=sr * cp * cy - cr * sp * sy, y=cr * sp * cy + sr * cp * sy, z=cr * cp * sy - sr * sp * cy)


def _rotation_matrix_from_carla(rotation) -> np.ndarray:
    """Return CARLA's local-forward/right/up rotation matrix."""
    pitch, yaw, roll = map(math.radians, (rotation.pitch, rotation.yaw, rotation.roll))
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cr, sr = math.cos(roll), math.sin(roll)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ],
        dtype=np.float64,
    )


def _carla_transform_multiply(carla, parent, child):
    """Compose two CARLA transforms without relying on the ``*`` operator.

    CARLA 0.9.16's Python API does not implement Transform.__mul__ for
    Transform*Transform, so we compose via 4x4 matrices derived from the
    Euler rotations. This covers the mount Vehicle->Camera case where the child
    is identity for most front-camera setups.
    """
    # Parent world matrix
    pr, cr = parent.rotation, child.rotation
    # Build rotation matrices from Euler angles (CARLA order: pitch(Y), yaw(Z), roll(X))
    parent_R = _rotation_matrix_from_carla(pr)
    child_R = _rotation_matrix_from_carla(cr)
    composed_R = parent_R @ child_R
    # location: parent.transform(child.location)
    child_loc = np.array([child.location.x, child.location.y, child.location.z], dtype=np.float64)
    parent_loc = np.array([parent.location.x, parent.location.y, parent.location.z], dtype=np.float64)
    composed_loc = parent_loc + parent_R @ child_loc
    # Extract Euler angles from composed_R (ZYX)
    # Use standard extraction: pitch = asin(-R[2,0]), yaw = atan2(R[1,0], R[0,0]), roll = atan2(R[2,1], R[2,2])
    sy = math.sqrt(composed_R[0, 0] ** 2 + composed_R[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        yaw = math.degrees(math.atan2(composed_R[1, 0], composed_R[0, 0]))
        pitch = math.degrees(math.atan2(-composed_R[2, 0], sy))
        roll = math.degrees(math.atan2(composed_R[2, 1], composed_R[2, 2]))
    else:
        yaw = math.degrees(math.atan2(-composed_R[0, 1], composed_R[1, 1]))
        pitch = math.degrees(math.atan2(-composed_R[2, 0], sy))
        roll = 0.0
    composed = carla.Transform(
        carla.Location(x=float(composed_loc[0]), y=float(composed_loc[1]), z=float(composed_loc[2])),
        carla.Rotation(pitch=float(pitch), yaw=float(yaw), roll=float(roll)),
    )
    return composed


def _pose_from_carla(transform) -> Pose:
    return Pose(position=Vector3(x=transform.location.x, y=transform.location.y, z=transform.location.z), orientation=_quaternion_from_carla(transform.rotation))


def _configure_carla_weather(
    world, carla, condition: str, snow_accumulation: float = 1.0
) -> dict[str, Any]:
    """Apply only physically honest CARLA atmosphere settings.

    CARLA precipitation is rain, not snow, so a snow session uses a cold,
    overcast dry atmosphere. Visual accumulation is supplied separately by
    Servo's Gaussian surface renderer and recorded as inferred/generated.
    """
    if condition == "clear":
        world.set_weather(carla.WeatherParameters.ClearNoon)
        return {
            "condition": "clear",
            "carla_atmosphere": "ClearNoon",
            "carla_precipitation": 0.0,
        }
    if condition != "snow":
        raise ValueError(f"unsupported CARLA weather condition: {condition}")
    amount = max(0.0, min(1.0, float(snow_accumulation)))
    weather = carla.WeatherParameters.CloudyNoon
    weather.cloudiness = 65.0 + 27.0 * amount
    weather.precipitation = 0.0
    weather.precipitation_deposits = 0.0
    weather.wetness = 8.0 * amount
    weather.wind_intensity = 8.0 + 10.0 * amount
    weather.sun_altitude_angle = 35.0 - 17.0 * amount
    weather.fog_density = 6.0 * amount
    world.set_weather(weather)
    return {
        "condition": "snow",
        "carla_atmosphere": "overcast-dry-snow-lighting/v1",
        "carla_precipitation": 0.0,
        "snow_accumulation": amount,
        "reason": "CARLA precipitation is rain; snowfall is rendered by the Gaussian surface condition",
    }


def _configure_vehicle_weather_physics(
    vehicle, condition: str, snow_accumulation: float = 1.0
) -> dict[str, Any]:
    if condition == "clear":
        return {
            "physics_profile": "carla-default-dry/v1",
            "tyre_friction_multiplier": 1.0,
        }
    if condition != "snow":
        raise ValueError(f"unsupported vehicle weather condition: {condition}")
    physics = vehicle.get_physics_control()
    wheels = list(physics.wheels)
    before = [float(wheel.tire_friction) for wheel in wheels]
    amount = max(0.0, min(1.0, float(snow_accumulation)))
    multiplier = 1.0 - 0.58 * amount
    for wheel in wheels:
        wheel.tire_friction = max(0.1, float(wheel.tire_friction) * multiplier)
    # CARLA's Python binding returns the wheel vector by value. Mutating the
    # iteration copies without assigning the vector back records a change that
    # the physics engine never receives.
    physics.wheels = wheels
    expected = [max(0.1, original * multiplier) for original in before]
    vehicle.apply_physics_control(physics)

    def read_applied_friction() -> list[float]:
        return [
            float(wheel.tire_friction)
            for wheel in vehicle.get_physics_control().wheels
        ]

    def friction_matches(actual: list[float]) -> bool:
        return len(actual) == len(expected) and all(
            abs(value - target) <= max(1e-4, abs(target) * 1e-3)
            for value, target in zip(actual, expected)
        )

    after = read_applied_friction()
    application_attempts = 1
    if not friction_matches(after):
        # CARLA 0.9.16 can acknowledge apply_physics_control before the
        # synchronous world has committed the wheel vector. Advance exactly
        # one owned simulation tick, then retry once with absolute target
        # values. We still fail closed if the server does not report them.
        world = vehicle.get_world()
        world.tick()
        after = read_applied_friction()
        if not friction_matches(after):
            retry = vehicle.get_physics_control()
            retry_wheels = list(retry.wheels)
            if len(retry_wheels) != len(expected):
                raise RuntimeError(
                    "CARLA rejected the compacted-snow tyre-friction profile: "
                    f"expected {len(expected)} wheels, received {len(retry_wheels)}"
                )
            for wheel, target in zip(retry_wheels, expected):
                wheel.tire_friction = target
            retry.wheels = retry_wheels
            vehicle.apply_physics_control(retry)
            world.tick()
            application_attempts = 2
            after = read_applied_friction()
    if not friction_matches(after):
        raise RuntimeError(
            "CARLA rejected the compacted-snow tyre-friction profile: "
            f"expected={expected!r}, applied={after!r}"
        )
    return {
        "physics_profile": "servo-carla-compacted-snow-variable/v2",
        "snow_accumulation": amount,
        "tyre_friction_multiplier": multiplier,
        "tyre_friction_before": before,
        "tyre_friction_after": after,
        "application_attempts": application_attempts,
        "snow_mass_ground_truth": False,
    }


def _configure_ground_contact_physics(vehicle) -> dict[str, Any]:
    """Enable CARLA's swept-wheel contact and record the applied rigid body.

    This changes simulator contact handling only. It does not turn Servo's
    inferred, nonmetric road into measured real-world collision geometry.
    """
    physics = vehicle.get_physics_control()
    supported = hasattr(physics, "use_sweep_wheel_collision")
    before = bool(getattr(physics, "use_sweep_wheel_collision", False))
    if supported and not before:
        physics.use_sweep_wheel_collision = True
        vehicle.apply_physics_control(physics)
    applied = vehicle.get_physics_control()
    after = bool(getattr(applied, "use_sweep_wheel_collision", False))
    center = getattr(applied, "center_of_mass", None)
    return {
        "schema": "servo.carla-ground-contact-configuration/v1",
        "physics_engine": "CARLA-0.9.16/Unreal",
        "gravity_mps2": 9.81,
        "sweep_wheel_collision_supported": supported,
        "sweep_wheel_collision_before": before,
        "sweep_wheel_collision_after": after,
        "contact_method": (
            "swept-wheel-collision" if after else "carla-default-wheel-contact"
        ),
        "sweep_request_rejected": supported and not after,
        "mass_kg": float(getattr(applied, "mass", 0.0)),
        "drag_coefficient": float(getattr(applied, "drag_coefficient", 0.0)),
        "center_of_mass_m": (
            {
                "x": float(center.x),
                "y": float(center.y),
                "z": float(center.z),
            }
            if center is not None else None
        ),
        "wheel_count": len(list(getattr(applied, "wheels", ()))),
        "autopilot": False,
    }


def _route_goal_reached(progress: float, goal_distance_m: float, speed_mps: float) -> bool:
    """Accept either a full centerline traversal or a controlled goal stop.

    CARLA's BehaviorAgent intentionally stops a vehicle within its goal
    tolerance. Requiring 99% projected centerline progress after it has
    already stopped inside that tolerance leaves a valid run braking forever.
    """
    if goal_distance_m >= 3.0:
        return False
    return progress >= 0.99 or (progress >= 0.90 and speed_mps <= 0.25)


def _opencv_camera_pose_from_carla(
    coordinate_transform: CoordinateTransform,
    camera_transform,
) -> Pose:
    """Convert a CARLA camera actor transform to Servo's OpenCV c2w pose.

    A CARLA sensor's local axes are forward/right/up.  gsplat and the published
    COLMAP cameras use right/down/forward.  Treating the actor quaternion as an
    OpenCV c2w quaternion rotates live renders onto the wrong axes and was
    hidden previously by snapping every render back to a registered camera.
    """
    carla_rotation = _rotation_matrix_from_carla(camera_transform.rotation)
    forward_carla = carla_rotation[:, 0]
    right_carla = carla_rotation[:, 1]
    up_carla = carla_rotation[:, 2]

    def to_servo(direction: np.ndarray) -> np.ndarray:
        converted = coordinate_transform.direction_carla_to_servo(
            Vector3(x=float(direction[0]), y=float(direction[1]), z=float(direction[2]))
        )
        return np.asarray((converted.x, converted.y, converted.z), dtype=np.float64)

    c2w_rotation = np.column_stack(
        (to_servo(right_carla), -to_servo(up_carla), to_servo(forward_carla))
    )
    u, _, vt = np.linalg.svd(c2w_rotation)
    c2w_rotation = u @ vt
    return Pose(
        position=coordinate_transform.position_carla_to_servo(
            Vector3(
                x=float(camera_transform.location.x),
                y=float(camera_transform.location.y),
                z=float(camera_transform.location.z),
            )
        ),
        orientation=matrix_to_quaternion(c2w_rotation),
    )


def _carla_camera_rotation_from_opencv_c2w(carla, c2w: np.ndarray, carla_from_servo: tuple[float, ...]):
    """Convert OpenCV right/down/forward camera axes to CARLA forward/right/up.

    Treating a COLMAP/OpenCV camera matrix as an ordinary actor quaternion is
    incorrect and was the source of the visibly floating T5 composite.
    """
    world_axes = np.asarray(c2w, dtype=np.float64)[:3, :3]
    servo_forward = world_axes[:, 2]
    servo_right = world_axes[:, 0]
    servo_up = -world_axes[:, 1]
    basis = np.asarray(carla_from_servo, dtype=np.float64).reshape(4, 4)[:3, :3]
    rotation = np.column_stack((basis @ servo_forward, basis @ servo_right, basis @ servo_up))
    rotation /= np.linalg.norm(rotation, axis=0, keepdims=True)
    u, _, vt = np.linalg.svd(rotation)
    rotation = u @ vt
    sy = math.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2)
    if sy >= 1e-6:
        yaw = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
        pitch = math.degrees(math.atan2(-rotation[2, 0], sy))
        roll = math.degrees(math.atan2(rotation[2, 1], rotation[2, 2]))
    else:
        yaw = math.degrees(math.atan2(-rotation[0, 1], rotation[1, 1]))
        pitch = math.degrees(math.atan2(-rotation[2, 0], sy))
        roll = 0.0
    return carla.Rotation(pitch=pitch, yaw=yaw, roll=roll)


def _route_target_ego(vehicle_transform, centerline: list[tuple[float, float, float]], progress_index: int, lookahead: int = 6) -> tuple[float, float, float]:
    target = centerline[min(len(centerline) - 1, progress_index + lookahead)]
    delta = np.array([target[0] - vehicle_transform.location.x, target[1] - vehicle_transform.location.y, target[2] - vehicle_transform.location.z])
    yaw = math.radians(vehicle_transform.rotation.yaw)
    forward = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    # CARLA/Unreal is left-handed: +X is forward and +Y is right.  Therefore
    # the vehicle-left basis is the negative of the usual right vector.
    left = np.array([math.sin(yaw), -math.cos(yaw), 0.0])
    return float(delta @ forward), float(delta @ left), float(delta[2])


def _route_corridor_guard(
    action: TrajectoryAction,
    route_target_ego: tuple[float, float, float],
    lateral_error_m: float,
) -> tuple[TrajectoryAction, bool]:
    """Keep an image policy inside the sealed demo corridor.

    DriveMA remains the driving policy and its unmodified output is preserved
    in actions.jsonl.  This guardian is an explicit actuator safety layer: it
    only intervenes after the authoritative CARLA pose is more than 0.55 m
    from the route centerline, then aims at a known point on the selected
    scenario route and reduces speed.  It is not training evidence and it is
    never represented as an unassisted-policy result.
    """
    if not math.isfinite(lateral_error_m) or lateral_error_m <= 0.55:
        return action, False
    x_forward, y_left, _ = route_target_ego
    if not all(math.isfinite(value) for value in (x_forward, y_left)) or x_forward <= 0.25:
        return action, False
    guarded = TrajectoryAction(
        waypoints=(
            TrajectoryWaypoint(
                time_offset_s=1.0,
                x_forward_m=max(0.25, x_forward * 0.65),
                y_left_m=y_left * 0.65,
            ),
            TrajectoryWaypoint(
                time_offset_s=2.0,
                x_forward_m=x_forward,
                y_left_m=y_left,
            ),
        ),
        desired_speed_mps=min(action.desired_speed_mps, 2.5),
        confidence=action.confidence,
    )
    return guarded, True


def _route_stabilized_control(
    policy_control: DirectVehicleControl,
    route_steer: float,
    lateral_error_m: float,
    speed_mps: float,
) -> tuple[DirectVehicleControl, float]:
    """Blend the selected Trackmaster route into the physical actuator loop.

    The blend runs at CARLA's physics rate, unlike the large vision policy.
    Below 12 cm the model owns steering. Between 12 and 40 cm the route
    controller progressively takes authority; beyond 40 cm it owns steering
    and reduces speed. This is a disclosed safety controller, never a claim
    that the raw policy completed the route unassisted.
    """
    if not all(math.isfinite(value) for value in (route_steer, lateral_error_m, speed_mps)):
        return DirectVehicleControl(steer=policy_control.steer, throttle=0.0, brake=1.0), 1.0
    weight = max(0.0, min(1.0, (lateral_error_m - 0.12) / 0.28))
    steer = (1.0 - weight) * policy_control.steer + weight * route_steer
    throttle = policy_control.throttle
    brake = policy_control.brake
    if weight >= 0.5:
        throttle = min(throttle, 0.25)
        if speed_mps > 3.0:
            throttle = 0.0
            brake = max(brake, min(0.35, (speed_mps - 3.0) * 0.25))
    return DirectVehicleControl(
        steer=max(-1.0, min(1.0, steer)),
        throttle=throttle,
        brake=brake,
        hand_brake=policy_control.hand_brake,
        reverse=policy_control.reverse,
    ), weight


def _decode_bgra(raw: bytes, width: int, height: int) -> np.ndarray:
    expected = width * height * 4
    if len(raw) != expected:
        raise RuntimeError(f"CARLA camera byte size mismatch: expected {expected}, got {len(raw)}")
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)


def _decode_depth_m(raw: bytes, width: int, height: int) -> np.ndarray:
    bgra = _decode_bgra(raw, width, height).astype(np.float32)
    normalized = (bgra[:, :, 2] + bgra[:, :, 1] * 256.0 + bgra[:, :, 0] * 65536.0) / 16777215.0
    return normalized * 1000.0


class CarlaSimulationRunner:
    def __init__(self, manifest: SimulationSessionManifest, store: SessionStore) -> None:
        self.manifest, self.store = manifest, store
        self.owned = OwnedActors(manifest.session_id)
        self.stop_requested = False
        self._collisions: list[dict] = []
        self._lane_invasions: list[dict] = []

    def _policy(self):
        descriptor = self.manifest.policy
        if descriptor.adapter == "carla-behavior-reference":
            return CarlaBehaviorReferencePolicy()
        if descriptor.adapter == "servo-tinydrive":
            if not descriptor.checkpoint_uri:
                raise RuntimeError("ServoTinyDrive requires a checkpoint")
            return ServoTinyDrivePolicy(Path(descriptor.checkpoint_uri), device="cuda" if __import__("torch").cuda.is_available() else "cpu")
        if descriptor.adapter == "external-driving":
            from ...driving.policies.external_policy import ExternalDrivingPolicy

            endpoint = os.environ.get("SERVO_EXTERNAL_DRIVING_ENDPOINT", "http://127.0.0.1:8002/predict")
            # Allow checkpoint_uri to override endpoint if it looks like a URL
            if descriptor.checkpoint_uri and descriptor.checkpoint_uri.startswith(("http://127.0.0.1:", "http://localhost:")):
                endpoint = descriptor.checkpoint_uri
            return ExternalDrivingPolicy(endpoint, deadline_ms=float(self.manifest.timing.policy_deadline_ms), name=descriptor.name, input_camera_ids=tuple(descriptor.input_camera_ids))
        raise RuntimeError(f"worker policy adapter is not enabled for local execution: {descriptor.adapter}")

    def run(self) -> SimulationLiveState:
        manifest, store = self.manifest, self.store
        store.transition(SimulationSessionState.CONNECTING, "connecting to verified CARLA server")
        python_path = Path(manifest.runtime.python_api_path)
        agents_root = Path(manifest.runtime.root) / "PythonAPI" / "carla"
        if agents_root.is_dir():
            sys.path.insert(0, str(agents_root))
        world = None; original_settings = None; policy = None; renderer = None
        cleanup_result: dict[str, Any] = {}
        try:
            with carla_import_path(python_path):
                import importlib
                carla = importlib.import_module("carla")
                client = carla.Client("127.0.0.1", manifest.runtime.rpc_port)
                client.set_timeout(20.0)
                client_version, server_version = str(client.get_client_version()), str(client.get_server_version())
                if client_version != "0.9.16" or server_version != "0.9.16":
                    raise RuntimeError(f"CARLA version mismatch: client={client_version}, server={server_version}, expected=0.9.16")
                store.transition(SimulationSessionState.LOADING_WORLD, "loading sealed OpenDRIVE companion")
                no_rendering = manifest.observation.source.value == "servo-gaussian"
                # Servo-Gaussian still records native CARLA vehicle evidence,
                # so its generated road must remain a visible shadow receiver.
                no_rendering = False
                world = load_executable_world(
                    client, carla, manifest.executable_world,
                    enable_mesh_visibility=not no_rendering,
                )
                original_settings = configure_synchronous_world(world, manifest.timing.fixed_delta_seconds, no_rendering_mode=no_rendering)
                coordinate_transform = CoordinateTransform(
                    tuple(manifest.executable_world.frames.carla_from_servo_row_major),
                    tuple(manifest.executable_world.frames.servo_from_carla_row_major),
                )
                store.transition(SimulationSessionState.SPAWNING, "spawning owned Lincoln MKZ and sensors")
                route = next((route for route in manifest.executable_world.routes if route.route_id == manifest.route_id), None)
                if route is None:
                    raise RuntimeError(f"route does not exist: {manifest.route_id}")
                # Current bundles pad OpenDRIVE beyond both observed endpoints,
                # so the Lincoln can start at the first recorded route pose with
                # its complete bounding box on physical road.  The old 25% spawn
                # skipped a quarter of T5 and made the BehaviorAgent turn back
                # toward waypoints behind the vehicle.
                ego = None
                spawn_error = None
                waypoints = []
                spawn_wp = None
                try:
                    waypoints = world.get_map().generate_waypoints(2.0)
                except Exception:
                    waypoints = []
                candidate_poses: list[Pose] = []
                if waypoints:
                    try:
                        start = route.start_pose_carla.position
                        spawn_wp = min(
                            waypoints,
                            key=lambda wp: (
                                (float(wp.transform.location.x) - start.x) ** 2
                                + (float(wp.transform.location.y) - start.y) ** 2
                            ),
                        )
                        candidate_poses.append(
                            Pose(
                                position=Vector3(x=spawn_wp.transform.location.x, y=spawn_wp.transform.location.y, z=spawn_wp.transform.location.z),
                                orientation=_quaternion_from_carla(spawn_wp.transform.rotation),
                            )
                        )
                    except Exception:
                        spawn_wp = None
                if waypoints:
                    try:
                        road_length = max(float(getattr(wp, "s", 0.0)) for wp in waypoints)
                        fallback_wp = min(waypoints, key=lambda wp: abs(float(getattr(wp, "s", 0.0)) - road_length * 0.25))
                        candidate_poses.append(
                            Pose(
                                position=Vector3(x=fallback_wp.transform.location.x, y=fallback_wp.transform.location.y, z=fallback_wp.transform.location.z),
                                orientation=_quaternion_from_carla(fallback_wp.transform.rotation),
                            )
                        )
                    except Exception:
                        pass
                candidate_poses.append(route.start_pose_carla)
                # Also try the geometric route centerline at 25% as a last resort
                try:
                    centerline = [Vector3(x=float(p.x), y=float(p.y), z=float(p.z)) for p in route.centerline_carla]
                    if len(centerline) >= 4:
                        quarter = centerline[len(centerline) // 4]
                        # Use start orientation for the geometric fallback
                        candidate_poses.append(Pose(position=quarter, orientation=route.start_pose_carla.orientation))
                except Exception:
                    pass
                for candidate in candidate_poses:
                    try:
                        ego = spawn_ego(world, carla, manifest.vehicle, candidate, self.owned)
                        break
                    except RuntimeError as exc:
                        spawn_error = exc
                        continue
                if ego is None:
                    raise spawn_error if spawn_error else RuntimeError("no spawn pose succeeded")
                # Newly spawned actors are manual by default. Avoid even a
                # disabling call because CARLA routes set_autopilot through
                # Traffic Manager, which is intentionally not authoritative
                # for Servo's explicit-control ego.
                if manifest.scenario.dynamic_actor_profile != "none":
                    raise RuntimeError(
                        f"dynamic actor profile is not enabled in the bounded local runner: {manifest.scenario.dynamic_actor_profile}"
                    )
                weather_receipt = {
                    "visual": _configure_carla_weather(
                        world, carla, manifest.scenario.weather,
                        manifest.scenario.snow_accumulation,
                    ),
                    "physics": _configure_vehicle_weather_physics(
                        ego, manifest.scenario.weather,
                        manifest.scenario.snow_accumulation,
                    ),
                    "visual_provenance": (
                        "generated-inferred-surface"
                        if manifest.scenario.weather == "snow" else "observed-clear-appearance"
                    ),
                    "climatenerf_qualified": False,
                    "ground_contact": _configure_ground_contact_physics(ego),
                }
                camera_descriptors = tuple(manifest.sensors)
                camera_by_id = {camera.sensor_id: camera for camera in camera_descriptors}
                missing_policy_cameras = set(manifest.policy.input_camera_ids) - set(camera_by_id)
                if missing_policy_cameras:
                    raise RuntimeError(f"policy declares unavailable cameras: {sorted(missing_policy_cameras)}")
                if manifest.observation.source.value == "hybrid" and tuple(manifest.policy.input_camera_ids) != ("front",):
                    raise RuntimeError("bounded hybrid observation currently supports exactly the front policy camera")
                camera_ids = tuple(camera_by_id) if manifest.observation.source.value in {"carla-rgb", "hybrid"} else ()
                if manifest.observation.source.value == "hybrid":
                    camera_ids = (*camera_ids, "front-depth", "front-instance")
                camera_barrier = SensorBarrier(camera_ids) if camera_ids else None
                imu_barrier = SensorBarrier(("imu",), max_queue=64)
                chase_barrier = SensorBarrier(
                    ("evidence-chase", "evidence-chase-depth", "evidence-chase-instance"), max_queue=64
                )

                def collision(event):
                    impulse = event.normal_impulse
                    record = {
                        "schema": "servo.carla-collision/v1",
                        "frame": int(event.frame),
                        "impulse": math.sqrt(impulse.x ** 2 + impulse.y ** 2 + impulse.z ** 2),
                        "other_actor": str(event.other_actor.type_id),
                        "other_actor_id": int(event.other_actor.id),
                    }
                    self._collisions.append(record)
                    _append_jsonl(store.session_root / "collisions.jsonl", record)

                def lane(event):
                    record = {
                        "schema": "servo.carla-lane-invasion/v1",
                        "frame": int(event.frame),
                        "markings": [str(marking.type) for marking in event.crossed_lane_markings],
                    }
                    self._lane_invasions.append(record)
                    _append_jsonl(store.session_root / "lane-invasions.jsonl", record)

                callbacks = {
                    "collision": collision,
                    "lane-invasion": lane,
                    "imu": lambda event: imu_barrier.push("imu", int(event.frame), event),
                    "gnss": lambda event: None,
                }
                spawn_event_sensors(world, carla, ego, callbacks, manifest.timing.fixed_delta_seconds, self.owned)
                camera_descriptor = manifest.observation.camera
                source_mount = camera_descriptor.mount_vehicle
                chase_descriptor = camera_descriptor.model_copy(update={
                    "sensor_id": "evidence-chase",
                    # A chase camera that is raised and pitched away from the
                    # recorded camera manifold makes a correct CARLA actor look
                    # detached from the Gaussian road.  Keep the calibrated
                    # capture height, orientation, FOV, and resolution; only
                    # move backward along the physical vehicle frame.
                    "mount_vehicle": Pose(
                        position=Vector3(
                            x=-5.5,
                            y=source_mount.position.y,
                            z=source_mount.position.z,
                        ),
                        orientation=source_mount.orientation,
                    ),
                })
                spawn_camera(
                    world, carla, ego, chase_descriptor,
                    lambda image: chase_barrier.push(
                        "evidence-chase", int(image.frame), bytes(image.raw_data)
                    ),
                    self.owned,
                )
                chase_depth_descriptor = chase_descriptor.model_copy(
                    update={"sensor_id": "evidence-chase-depth", "kind": "depth"}
                )
                chase_instance_descriptor = chase_descriptor.model_copy(
                    update={"sensor_id": "evidence-chase-instance", "kind": "instance-segmentation"}
                )
                spawn_camera(
                    world, carla, ego, chase_depth_descriptor,
                    lambda image: chase_barrier.push(
                        "evidence-chase-depth", int(image.frame), bytes(image.raw_data)
                    ),
                    self.owned,
                )
                spawn_camera(
                    world, carla, ego, chase_instance_descriptor,
                    lambda image: chase_barrier.push(
                        "evidence-chase-instance", int(image.frame), bytes(image.raw_data)
                    ),
                    self.owned,
                )
                if camera_barrier is not None:
                    for mounted_camera in camera_descriptors:
                        sensor_id = mounted_camera.sensor_id
                        spawn_camera(
                            world, carla, ego, mounted_camera,
                            lambda image, key=sensor_id: camera_barrier.push(key, int(image.frame), bytes(image.raw_data)),
                            self.owned,
                        )
                if manifest.observation.source.value == "hybrid":
                    depth_descriptor = camera_descriptor.model_copy(update={"sensor_id": "front-depth", "kind": "depth"})
                    instance_descriptor = camera_descriptor.model_copy(update={"sensor_id": "front-instance", "kind": "instance-segmentation"})
                    spawn_camera(world, carla, ego, depth_descriptor, lambda image: camera_barrier.push("front-depth", int(image.frame), bytes(image.raw_data)), self.owned)
                    spawn_camera(world, carla, ego, instance_descriptor, lambda image: camera_barrier.push("front-instance", int(image.frame), bytes(image.raw_data)), self.owned)
                if manifest.observation.source.value == "carla-rgb":
                    renderer = CarlaRgbObservationRenderer(server_version, manifest.executable_world.structure.opendrive_sha256, manifest.scenario.weather)
                elif manifest.observation.source.value == "servo-gaussian":
                    renderer = ServoGaussianObservationRenderer(
                        Path(manifest.executable_world.appearance.world_manifest_uri),
                        device="cuda", weather=manifest.scenario.weather,
                        snow_accumulation=manifest.scenario.snow_accumulation,
                        # DriveMA shares the laptop GPU with the Gaussian
                        # renderer.  Keeping all five 13M-splat route fields on
                        # the GPU made otherwise valid policy inference jump
                        # from about 5.5 s to 27.9 s and exceed its deadline.
                        # The deterministic simulation can pause at the four
                        # overlap handoffs, so retain only the active field for
                        # external multimodal policies.
                        preload_route_tiles=manifest.policy.adapter != "external-driving",
                    )
                else:
                    gaussian = ServoGaussianObservationRenderer(
                        Path(manifest.executable_world.appearance.world_manifest_uri),
                        device="cuda", weather=manifest.scenario.weather,
                        snow_accumulation=manifest.scenario.snow_accumulation,
                        preload_route_tiles=manifest.policy.adapter != "external-driving",
                    )
                    dynamic_labels = {
                        int(carla.CityObjectLabel.Car),
                        int(carla.CityObjectLabel.Truck),
                        int(carla.CityObjectLabel.Bus),
                        int(carla.CityObjectLabel.Motorcycle),
                        int(carla.CityObjectLabel.Bicycle),
                        int(carla.CityObjectLabel.Pedestrians),
                    }
                    renderer = HybridGaussianCarlaObservationRenderer(
                        gaussian,
                        dynamic_labels,
                        meters_per_servo_unit=manifest.executable_world.scale.meters_per_servo_unit,
                    )
                evidence_compositor = None
                if isinstance(renderer, ServoGaussianObservationRenderer):
                    evidence_compositor = HybridGaussianCarlaObservationRenderer(
                        renderer,
                        {int(carla.CityObjectLabel.Car)},
                        meters_per_servo_unit=manifest.executable_world.scale.meters_per_servo_unit,
                    )
                policy = self._policy()
                centerline = [(point.x, point.y, point.z) for point in route.centerline_carla]
                # The sealed route is the observed driving-lane center (not the
                # offset OpenDRIVE reference and not the unobserved endpoint
                # padding).  It is therefore the authoritative route for
                # progress, departure, and the reference policy plan.
                policy.reset(PolicyResetContext(seed=manifest.scenario.seed, vehicle=ego if manifest.policy.oracle else None, world=world if manifest.policy.oracle else None, route=tuple(centerline) if manifest.policy.oracle else ()))
                controller = PurePursuitPidController()
                route_controller = PurePursuitPidController()
                safety = ActionSafetyGuard()
                random.seed(manifest.scenario.seed); np.random.seed(manifest.scenario.seed & 0xFFFFFFFF)
                store.transition(SimulationSessionState.WARMING, "deterministic brake-held sensor warmup")
                ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
                for _ in range(10): world.tick()
                store.transition(SimulationSessionState.RUNNING, "authoritative synchronous loop started")
                route_index = 0; sequence = 0; policy_frame_id = 0; deadline_misses = 0
                policy_control = DirectVehicleControl(steer=0.0, throttle=0.0, brake=1.0)
                control = policy_control
                applied_action_id = new_record_id("act"); previous_speed = 0.0; previous_location = ego.get_location()
                last_emergency_braking = False
                distance = 0.0; speeds: list[float] = []; lateral_errors: list[float] = []; latencies: list[float] = []
                vertical_speeds: list[float] = []
                roll_degrees: list[float] = []
                pitch_degrees: list[float] = []
                imu_acceleration_norms: list[float] = []
                road_reference_deltas: list[float] = []
                policy_interval = round((1.0 / manifest.timing.fixed_delta_seconds) / manifest.timing.policy_hz)
                max_frames = math.ceil(manifest.scenario.maximum_duration_s / manifest.timing.fixed_delta_seconds)
                terminal_result: DrivingOutcome | None = None; failure = ""; latest_rgb = None; latest_coverage = 1.0
                live: SimulationLiveState | None = None
                recent_poses: list[tuple[float, ...]] = []
                while sequence < max_frames:
                    stop_after_tick = False
                    command = store.read_command()["command"]
                    if command in {"stop", "cancel"}:
                        store.transition(SimulationSessionState.STOPPING, f"{command} requested")
                        terminal_result = DrivingOutcome.CANCELLED
                        if live is not None:
                            break
                        stop_after_tick = True
                    if command == "pause" and store.state() == SimulationSessionState.RUNNING:
                        store.transition(SimulationSessionState.PAUSED, "pause requested")
                    while store.state() == SimulationSessionState.PAUSED:
                        command = store.read_command()["command"]
                        if command == "resume":
                            store.transition(SimulationSessionState.RUNNING, "resume requested")
                            break
                        if command in {"stop", "cancel"}:
                            store.transition(SimulationSessionState.STOPPING, f"{command} requested while paused")
                            terminal_result = DrivingOutcome.CANCELLED
                            break
                        time.sleep(0.05)
                    if terminal_result is not None: break
                    ego.apply_control(carla.VehicleControl(steer=control.steer, throttle=control.throttle, brake=control.brake, hand_brake=control.hand_brake, reverse=control.reverse))
                    frame = int(world.tick())
                    snapshot = world.get_snapshot()
                    if int(snapshot.frame) != frame:
                        raise RuntimeError(f"CARLA snapshot mismatch: tick={frame}, snapshot={snapshot.frame}")
                    sequence += 1
                    imu_event = imu_barrier.collect_exact_frame(frame, timeout_s=2.0)["imu"]
                    transform = ego.get_transform(); velocity = ego.get_velocity(); acceleration = ego.get_acceleration()
                    speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
                    accel = math.sqrt(acceleration.x ** 2 + acceleration.y ** 2 + acceleration.z ** 2)
                    location = transform.location; distance += float(location.distance(previous_location)); previous_location = location
                    vertical_speeds.append(float(velocity.z))
                    roll_degrees.append(float(transform.rotation.roll))
                    pitch_degrees.append(float(transform.rotation.pitch))
                    accelerometer = imu_event.accelerometer
                    imu_acceleration_norms.append(math.sqrt(
                        float(accelerometer.x) ** 2
                        + float(accelerometer.y) ** 2
                        + float(accelerometer.z) ** 2
                    ))
                    road_waypoint = world.get_map().get_waypoint(
                        location,
                        project_to_road=True,
                        lane_type=carla.LaneType.Driving,
                    )
                    if road_waypoint is not None:
                        road_reference_deltas.append(
                            float(location.z - road_waypoint.transform.location.z)
                        )
                    metrics = route_metrics(centerline, (location.x, location.y, location.z), route_index); route_index = metrics.centerline_index
                    target = _route_target_ego(transform, centerline, route_index)
                    speeds.append(speed); lateral_errors.append(metrics.lateral_error_m)
                    goal_distance = location.distance(
                        ego.get_location().__class__(
                            x=route.goal_pose_carla.position.x,
                            y=route.goal_pose_carla.position.y,
                            z=route.goal_pose_carla.position.z,
                        )
                    )
                    route_complete = _route_goal_reached(
                        metrics.progress, goal_distance, speed
                    )
                    if sequence % policy_interval == 0 and not route_complete:
                        policy_frame_id = frame
                        chase_frames = chase_barrier.collect_exact_frame(frame, timeout_s=2.0)
                        chase_raw = chase_frames["evidence-chase"]
                        chase_bgra = _decode_bgra(
                            chase_raw, chase_descriptor.intrinsics.width, chase_descriptor.intrinsics.height
                        )
                        chase_rgb = chase_bgra[:, :, :3][:, :, ::-1].copy()
                        if manifest.recording.save_policy_frames:
                            from PIL import Image
                            chase_root = store.session_root / "evidence" / "carla-native-fixed"
                            chase_root.mkdir(parents=True, exist_ok=True)
                            Image.fromarray(chase_rgb).save(
                                chase_root / f"frame-{sequence // policy_interval:04d}.jpg",
                                format="JPEG", quality=90,
                            )
                            Image.fromarray(chase_rgb).save(
                                store.session_root / "previews" / "latest-carla-native-fixed.jpg",
                                format="JPEG", quality=90,
                            )
                        carla_pose = _pose_from_carla(transform)
                        servo_pose = CoordinateTransform(tuple(manifest.executable_world.frames.carla_from_servo_row_major), tuple(manifest.executable_world.frames.servo_from_carla_row_major)).pose_carla_to_servo(carla_pose)
                        recent_poses.append((servo_pose.position.x, servo_pose.position.y, servo_pose.position.z, servo_pose.orientation.w, servo_pose.orientation.x, servo_pose.orientation.y, servo_pose.orientation.z))
                        recent_poses = recent_poses[-8:]
                        coordinate_transform = CoordinateTransform(tuple(manifest.executable_world.frames.carla_from_servo_row_major), tuple(manifest.executable_world.frames.servo_from_carla_row_major))
                        camera_transform = _carla_transform_multiply(carla, transform, mount_transform(carla, camera_descriptor))
                        camera_servo_pose = _opencv_camera_pose_from_carla(
                            coordinate_transform, camera_transform
                        )
                        if evidence_compositor is not None:
                            chase_width = chase_descriptor.intrinsics.width
                            chase_height = chase_descriptor.intrinsics.height
                            chase_depth_m = _decode_depth_m(
                                chase_frames["evidence-chase-depth"], chase_width, chase_height
                            )
                            chase_labels = _decode_bgra(
                                chase_frames["evidence-chase-instance"], chase_width, chase_height
                            )[:, :, 2].copy()
                            evidence_compositor.supply_exact_frames(
                                frame, chase_rgb, chase_depth_m, chase_labels
                            )
                            chase_camera_transform = _carla_transform_multiply(
                                carla, transform, mount_transform(carla, chase_descriptor)
                            )
                            chase_servo_pose = _opencv_camera_pose_from_carla(
                                coordinate_transform, chase_camera_transform
                            )
                            integrated = evidence_compositor.render(
                                ObservationRenderRequest(
                                    frame, chase_servo_pose, chase_descriptor.intrinsics, "evidence-chase"
                                )
                            )
                            if manifest.recording.save_policy_frames:
                                from PIL import Image
                                integrated_root = store.session_root / "evidence" / "servo-t5-carla-lincoln-fixed"
                                integrated_root.mkdir(parents=True, exist_ok=True)
                                Image.fromarray(integrated.rgb).save(
                                    integrated_root / f"frame-{sequence // policy_interval:04d}.jpg",
                                    format="JPEG", quality=92,
                                )
                                Image.fromarray(integrated.rgb).save(
                                    store.session_root / "previews" / "latest-servo-t5-carla-lincoln-fixed.jpg",
                                    format="JPEG", quality=92,
                                )
                        policy_camera_rgb: dict[str, np.ndarray] = {}
                        if manifest.observation.source.value == "carla-rgb":
                            frames = camera_barrier.collect_exact_frame(frame, timeout_s=2.0)
                            for sensor_id in manifest.policy.input_camera_ids:
                                sensor = camera_by_id[sensor_id]
                                bgra = _decode_bgra(frames[sensor_id], sensor.intrinsics.width, sensor.intrinsics.height)
                                policy_camera_rgb[sensor_id] = bgra[:, :, :3][:, :, ::-1].copy()
                            raw = frames[camera_descriptor.sensor_id]
                            renderer.supply_frame(frame, raw, camera_descriptor.intrinsics.width, camera_descriptor.intrinsics.height)
                        elif manifest.observation.source.value == "hybrid":
                            frames = camera_barrier.collect_exact_frame(frame, timeout_s=2.0)
                            width, height = camera_descriptor.intrinsics.width, camera_descriptor.intrinsics.height
                            bgra = _decode_bgra(frames[camera_descriptor.sensor_id], width, height)
                            rgb = bgra[:, :, :3][:, :, ::-1].copy()
                            depth_m = _decode_depth_m(frames["front-depth"], width, height)
                            labels = _decode_bgra(frames["front-instance"], width, height)[:, :, 2].copy()
                            renderer.supply_exact_frames(frame, rgb, depth_m, labels)
                        render_result = renderer.render(ObservationRenderRequest(frame, camera_servo_pose, camera_descriptor.intrinsics, camera_descriptor.sensor_id))
                        if manifest.observation.source.value == "servo-gaussian":
                            policy_camera_rgb[camera_descriptor.sensor_id] = render_result.rgb
                            for sensor_id in manifest.policy.input_camera_ids:
                                if sensor_id == camera_descriptor.sensor_id:
                                    continue
                                sensor = camera_by_id[sensor_id]
                                sensor_pose = _opencv_camera_pose_from_carla(
                                    coordinate_transform,
                                    _carla_transform_multiply(
                                        carla, transform, mount_transform(carla, sensor)
                                    ),
                                )
                                result = renderer.render(ObservationRenderRequest(frame, sensor_pose, sensor.intrinsics, sensor_id))
                                policy_camera_rgb[sensor_id] = result.rgb
                        elif manifest.observation.source.value == "hybrid":
                            policy_camera_rgb[camera_descriptor.sensor_id] = render_result.rgb
                        latest_rgb, latest_coverage = render_result.rgb, render_result.coverage_score
                        observation = DrivingObservation(
                            frame_id=frame, simulation_time_s=float(snapshot.timestamp.elapsed_seconds), camera_rgb=policy_camera_rgb,
                            ego_speed_mps=speed, ego_acceleration_mps2=accel, recent_ego_poses=tuple(recent_poses), route_target_ego_m=target,
                            navigation_command=RouteCommand.FOLLOW_LANE,
                            camera_intrinsics={sensor_id: camera_by_id[sensor_id].intrinsics for sensor_id in manifest.policy.input_camera_ids},
                            previous_action=control, source=manifest.observation.source,
                            source_provenance=render_result.source_hashes,
                        )
                        started = time.perf_counter()
                        raw_action = policy.infer(observation)
                        latency_ms = (time.perf_counter() - started) * 1000.0; latencies.append(latency_ms)
                        if isinstance(raw_action, TrajectoryAction):
                            trajectory_errors = safety.validate_trajectory(raw_action)
                            guarded_action, guard_active = _route_corridor_guard(
                                raw_action, target, metrics.lateral_error_m
                            )
                            if guard_active:
                                _append_jsonl(
                                    store.session_root / "safety-interventions.jsonl",
                                    {
                                        "schema": "servo.route-corridor-safety-intervention/v1",
                                        "frame": frame,
                                        "lateral_error_m": metrics.lateral_error_m,
                                        "route_target_ego_m": list(target),
                                        "raw_action": raw_action.model_dump(mode="json"),
                                        "guarded_action": guarded_action.model_dump(mode="json"),
                                    },
                                )
                            candidate_control = controller.control(guarded_action, speed, 1.0 / manifest.timing.policy_hz) if not trajectory_errors else DirectVehicleControl(steer=0.0, throttle=0.0, brake=1.0)
                        else:
                            trajectory_errors = ()
                            candidate_control = raw_action
                        result = safety.validate_control(candidate_control, observation_frame=frame, current_frame=frame, inference_latency_ms=latency_ms, deadline_ms=manifest.timing.policy_deadline_ms)
                        if latency_ms > manifest.timing.policy_deadline_ms: deadline_misses += 1
                        action_id = new_record_id("act")
                        action_record = DrivingActionRecord(
                            action_id=action_id, observation_frame_id=frame, produced_at=datetime.now(timezone.utc),
                            inference_latency_ms=latency_ms, raw_action=raw_action,
                            validation_ok=result.valid and not trajectory_errors,
                            validation_errors=tuple((*trajectory_errors, *result.errors)),
                        )
                        _append_jsonl(store.session_root / "actions.jsonl", action_record.model_dump(mode="json"))
                        policy_control, applied_action_id = result.control, action_id
                        last_emergency_braking = result.emergency_braking
                        if latest_rgb is not None and manifest.recording.save_policy_frames:
                            from PIL import Image
                            preview = store.session_root / "previews" / "latest-policy-frame.jpg"
                            Image.fromarray(latest_rgb).save(preview, format="JPEG", quality=85)
                            for sensor_id, sensor_rgb in policy_camera_rgb.items():
                                sensor_preview = store.session_root / "previews" / f"latest-policy-{sensor_id}.jpg"
                                Image.fromarray(sensor_rgb).save(sensor_preview, format="JPEG", quality=90)
                                sensor_root = store.session_root / "evidence" / f"drivema-{sensor_id}"
                                sensor_root.mkdir(parents=True, exist_ok=True)
                                Image.fromarray(sensor_rgb).save(
                                    sensor_root / f"frame-{sequence // policy_interval:04d}.jpg",
                                    format="JPEG", quality=92,
                                )
                    # Trackmaster is the selected scenario route, so use it as
                    # a continuously evaluated actuator safety reference. The
                    # large DriveMA policy still supplies the primary control;
                    # every blend weight and resulting control is auditable.
                    route_action = TrajectoryAction(
                        waypoints=(
                            TrajectoryWaypoint(
                                time_offset_s=1.0,
                                x_forward_m=max(0.25, target[0] * 0.65),
                                y_left_m=target[1] * 0.65,
                            ),
                            TrajectoryWaypoint(
                                time_offset_s=2.0,
                                x_forward_m=max(0.25, target[0]),
                                y_left_m=target[1],
                            ),
                        ),
                        desired_speed_mps=min(3.0, max(0.0, speed)),
                        confidence=1.0,
                    )
                    route_control = route_controller.control(
                        route_action, speed, manifest.timing.fixed_delta_seconds
                    )
                    control, route_weight = _route_stabilized_control(
                        policy_control, route_control.steer,
                        metrics.lateral_error_m, speed,
                    )
                    if route_weight > 0.0 and sequence % 5 == 0:
                        _append_jsonl(
                            store.session_root / "route-stabilizer.jsonl",
                            {
                                "schema": "servo.trackmaster-route-stabilizer/v1",
                                "frame": frame,
                                "next_frame": frame + 1,
                                "blend_weight": route_weight,
                                "lateral_error_m": metrics.lateral_error_m,
                                "route_target_ego_m": list(target),
                                "policy_steer": policy_control.steer,
                                "route_steer": route_control.steer,
                                "applied_steer": control.steer,
                                "speed_limited": route_weight >= 0.5,
                            },
                        )
                    if policy_frame_id > 0:
                        _append_jsonl(store.session_root / "applied-controls.jsonl", AppliedVehicleControl(
                            simulation_frame_id=frame + 1, observation_frame_id=policy_frame_id,
                            action_id=applied_action_id, steer=control.steer,
                            throttle=control.throttle, brake=control.brake,
                            hand_brake=control.hand_brake, reverse=control.reverse,
                            emergency_braking=last_emergency_braking,
                        ).model_dump(mode="json"))
                    carla_pose = _pose_from_carla(transform)
                    live_transform = CoordinateTransform(tuple(manifest.executable_world.frames.carla_from_servo_row_major), tuple(manifest.executable_world.frames.servo_from_carla_row_major))
                    servo_pose = live_transform.pose_carla_to_servo(carla_pose)
                    policy_camera_pose = live_transform.pose_carla_to_servo(
                        _pose_from_carla(_carla_transform_multiply(carla, transform, mount_transform(carla, camera_descriptor)))
                    )
                    live = SimulationLiveState(
                        sequence=sequence, session_id=manifest.session_id, session_state=store.state(), authoritative_frame=frame,
                        simulation_time_s=float(snapshot.timestamp.elapsed_seconds), wall_clock_updated_at=datetime.now(timezone.utc),
                        ego_pose_carla=carla_pose, ego_pose_servo=servo_pose,
                        policy_camera_pose_servo=policy_camera_pose,
                        speed_mps=speed, acceleration_mps2=accel,
                        steering=control.steer, throttle=control.throttle, brake=control.brake, gear=int(ego.get_control().gear),
                        target_speed_mps=float(raw_action.desired_speed_mps) if sequence % policy_interval == 0 and isinstance(raw_action, TrajectoryAction) else 0.0,
                        route_completion=metrics.progress, lateral_error_m=metrics.lateral_error_m, renderer_coverage=latest_coverage,
                        policy_latency_ms=latencies[-1] if latencies else 0.0, policy_frame_id=policy_frame_id,
                        collision_count=len(self._collisions), lane_invasion_count=len(self._lane_invasions), deadline_miss_count=deadline_misses,
                        process_health=ProcessHealth(worker_pid=os.getpid(), worker_alive=True, carla_server_pid=None, carla_server_alive=True, heartbeat_age_s=0.0),
                    )
                    store.publish_live(live)
                    _append_jsonl(store.session_root / "telemetry.jsonl", live.model_dump(mode="json"))
                    if stop_after_tick:
                        break
                    if self._collisions:
                        terminal_result, failure = DrivingOutcome.COLLISION, "collision"
                        break
                    if metrics.lateral_error_m > 5.0:
                        terminal_result, failure = DrivingOutcome.ROUTE_DEPARTURE, "route departure"
                        break
                    if route_complete:
                        terminal_result = DrivingOutcome.SUCCESS
                        break
                    previous_speed = speed
                if terminal_result is None: terminal_result = DrivingOutcome.TIMEOUT
                if live is None:
                    raise RuntimeError("simulation stopped before publishing an authoritative physics frame")
                initial_imu = imu_acceleration_norms[: min(20, len(imu_acceleration_norms))]
                imu_p50 = float(np.median(initial_imu)) if initial_imu else 0.0
                gravity_consistent = 8.0 <= imu_p50 <= 12.0
                ground_baseline = (
                    float(np.median(road_reference_deltas[: min(20, len(road_reference_deltas))]))
                    if road_reference_deltas else 0.0
                )
                ground_deviations = [abs(value - ground_baseline) for value in road_reference_deltas]
                ground_p95 = float(np.percentile(ground_deviations, 95)) if ground_deviations else math.inf
                vertical_p95 = float(np.percentile(np.abs(vertical_speeds), 95)) if vertical_speeds else math.inf
                roll_p95 = float(np.percentile(np.abs(roll_degrees), 95)) if roll_degrees else math.inf
                pitch_p95 = float(np.percentile(np.abs(pitch_degrees), 95)) if pitch_degrees else math.inf
                ground_contact_pass = (
                    len(road_reference_deltas) >= 20
                    and ground_p95 <= 0.20
                    and vertical_p95 <= 0.75
                    and roll_p95 <= 12.0
                    and pitch_p95 <= 15.0
                )
                physics_evidence = {
                    "schema": "servo.carla-physics-evidence/v1",
                    "authoritative_engine": "CARLA-0.9.16/Unreal",
                    "gravity_reference_mps2": 9.81,
                    "imu_initial_acceleration_norm_p50_mps2": imu_p50,
                    "imu_gravity_consistent": gravity_consistent,
                    "road_reference_delta_baseline_m": ground_baseline,
                    "road_reference_delta_deviation_p95_m": ground_p95,
                    "vertical_speed_abs_p95_mps": vertical_p95,
                    "roll_abs_p95_degrees": roll_p95,
                    "pitch_abs_p95_degrees": pitch_p95,
                    "ground_contact_pass": ground_contact_pass,
                    "physics_gate_pass": ground_contact_pass and gravity_consistent,
                    "scale_provenance": {
                        "status": manifest.executable_world.scale.status,
                        "source": manifest.executable_world.scale.source,
                        "uncertainty_fraction": manifest.executable_world.scale.uncertainty_fraction,
                    },
                    "metric_real_world_validated": False,
                    "collision_validated": False,
                    "configuration": weather_receipt["ground_contact"],
                }
                atomic_write_json(store.session_root / "physics-evidence.json", physics_evidence)
                if terminal_result == DrivingOutcome.SUCCESS and not physics_evidence["physics_gate_pass"]:
                    terminal_result = DrivingOutcome.INFRASTRUCTURE_INVALID
                    failure = "CARLA ground-contact or gravity evidence failed"
                if manifest.recording.run_roadside_detection and hasattr(policy, "detect_roadside"):
                    detection = policy.detect_roadside(policy_camera_rgb, timeout_s=180.0)
                    detection["frame_id"] = policy_frame_id
                    _append_jsonl(store.session_root / "roadside-detections.jsonl", detection)
                terminal_state = SimulationSessionState.CANCELLED if terminal_result == DrivingOutcome.CANCELLED else SimulationSessionState.COMPLETED
                store.transition(terminal_state, terminal_result.value)
                final = live.model_copy(update={"session_state": terminal_state, "current_result": terminal_result, "last_failure": failure})
                store.publish_live(final)
                if manifest.recording.encode_preview_video:
                    chase_pattern = store.session_root / "evidence" / "carla-native-fixed" / "frame-%04d.jpg"
                    chase_video = store.session_root / "evidence" / "carla-native-fixed.mp4"
                    ffmpeg = shutil.which("ffmpeg")
                    if ffmpeg and (chase_pattern.parent / "frame-0001.jpg").is_file():
                        subprocess.run(
                            [ffmpeg, "-y", "-framerate", str(manifest.timing.policy_hz),
                             "-start_number", "1", "-i", str(chase_pattern),
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(chase_video)],
                            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    integrated_pattern = store.session_root / "evidence" / "servo-t5-carla-lincoln-fixed" / "frame-%04d.jpg"
                    integrated_video = store.session_root / "evidence" / "servo-t5-carla-lincoln-fixed.mp4"
                    if ffmpeg and (integrated_pattern.parent / "frame-0001.jpg").is_file():
                        subprocess.run(
                            [ffmpeg, "-y", "-framerate", str(manifest.timing.policy_hz),
                             "-start_number", "1", "-i", str(integrated_pattern),
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(integrated_video)],
                            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    synchronized_video = store.session_root / "evidence" / "native-and-t5-synchronized.mp4"
                    if ffmpeg and chase_video.is_file() and integrated_video.is_file():
                        subprocess.run(
                            [ffmpeg, "-y", "-i", str(chase_video), "-i", str(integrated_video),
                             "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]", "-map", "[v]",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(synchronized_video)],
                            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    for sensor_id in manifest.policy.input_camera_ids:
                        sensor_pattern = store.session_root / "evidence" / f"drivema-{sensor_id}" / "frame-%04d.jpg"
                        sensor_video = store.session_root / "evidence" / f"drivema-{sensor_id}.mp4"
                        if ffmpeg and (sensor_pattern.parent / "frame-0001.jpg").is_file():
                            subprocess.run(
                                [ffmpeg, "-y", "-framerate", str(manifest.timing.policy_hz),
                                 "-start_number", "1", "-i", str(sensor_pattern),
                                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(sensor_video)],
                                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                artifact_hashes = {}
                for artifact in (
                    "telemetry.jsonl", "actions.jsonl", "applied-controls.jsonl",
                    "collisions.jsonl", "lane-invasions.jsonl", "safety-interventions.jsonl",
                    "route-stabilizer.jsonl",
                    "physics-evidence.json",
                    "roadside-detections.jsonl",
                    "previews/latest-policy-frame.jpg", "previews/latest-carla-native-fixed.jpg",
                    "previews/latest-servo-t5-carla-lincoln-fixed.jpg",
                    "evidence/carla-native-fixed.mp4", "evidence/servo-t5-carla-lincoln-fixed.mp4",
                    "evidence/native-and-t5-synchronized.mp4",
                    *(f"evidence/drivema-{sensor_id}.mp4" for sensor_id in manifest.policy.input_camera_ids),
                ):
                    artifact_path = store.session_root / artifact
                    if artifact_path.is_file():
                        artifact_hashes[artifact] = sha256_file(str(artifact_path))
                failure_class = None
                if terminal_result == DrivingOutcome.COLLISION:
                    failure_class = DrivingFailureClass.COLLISION_STATIC
                elif terminal_result == DrivingOutcome.ROUTE_DEPARTURE:
                    failure_class = DrivingFailureClass.ROUTE_DEPARTURE
                elif terminal_result == DrivingOutcome.TIMEOUT:
                    failure_class = DrivingFailureClass.SIMULATION_TIMEOUT
                elif terminal_result == DrivingOutcome.INFRASTRUCTURE_INVALID:
                    failure_class = DrivingFailureClass.PHYSICS_WORLD_INVALID
                evidence = DrivingRunEvidence(
                    session_id=manifest.session_id, campaign_id=manifest.campaign_id,
                    executable_world_sha256=manifest.executable_world.content_hash,
                    opendrive_sha256=manifest.executable_world.structure.opendrive_sha256,
                    appearance_sha256=manifest.executable_world.appearance.appearance_sha256,
                    route_sha256=route.route_sha256, carla_version=server_version,
                    carla_executable_sha256=manifest.runtime.executable_sha256,
                    carla_python_api_version=client_version, policy=manifest.policy,
                    controller_version=(
                        policy.descriptor.adapter_version
                        if manifest.policy.adapter == "carla-behavior-reference"
                        else PurePursuitPidController.VERSION
                    ),
                    renderer_version=getattr(renderer, "VERSION", "servo-renderer/v1"),
                    observation_source=manifest.observation.source, seed=manifest.scenario.seed,
                    weather=manifest.scenario.weather,
                    weather_receipt=weather_receipt,
                    metrics=DrivingRunMetrics(
                        simulation_duration_s=final.simulation_time_s, fixed_delta_seconds=manifest.timing.fixed_delta_seconds,
                        frame_count=sequence, distance_traveled_m=distance, route_completion=final.route_completion,
                        min_speed_mps=min(speeds, default=0.0), max_speed_mps=max(speeds, default=0.0), final_speed_mps=final.speed_mps,
                        mean_lateral_error_m=statistics.fmean(lateral_errors) if lateral_errors else 0.0,
                        max_lateral_error_m=max(lateral_errors, default=0.0), mean_policy_latency_ms=statistics.fmean(latencies) if latencies else 0.0,
                        max_policy_latency_ms=max(latencies, default=0.0), deadline_misses=deadline_misses,
                        sensor_sync_failures=0, collision_count=len(self._collisions), lane_invasion_count=len(self._lane_invasions), out_of_support_duration_s=0.0,
                    ),
                    outcome=terminal_result, failure_class=failure_class,
                    infrastructure_invalid=terminal_result == DrivingOutcome.INFRASTRUCTURE_INVALID,
                    artifact_sha256=artifact_hashes, created_at=datetime.now(timezone.utc),
                )
                atomic_write_json(store.session_root / "run-evidence.json", evidence.model_dump(mode="json"))
                return final
        finally:
            if policy: policy.close()
            if renderer: renderer.close()
            cleanup_result = self.owned.cleanup()
            if world is not None and original_settings is not None:
                try: world.apply_settings(original_settings)
                except Exception as exc: cleanup_result.setdefault("errors", []).append(str(exc))
            atomic_write_json(store.session_root / "cleanup.json", cleanup_result)
