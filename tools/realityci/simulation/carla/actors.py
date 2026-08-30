"""CARLA ego and sensor spawning with explicit validated ownership."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from ...schemas.driving import CameraSensorDescriptor
from ...schemas.simulation import VehicleDescriptor
from .cleanup import OwnedActors


@dataclass(frozen=True)
class PedestrianCrossingPlan:
    """Deterministic route-relative plan for one physical CARLA walker."""

    route_fraction: float
    activation_progress: float
    route_length_m: float
    crossing_center: tuple[float, float, float]
    spawn_position: tuple[float, float, float]
    direction: tuple[float, float, float]
    yaw_degrees: float
    lateral_offset_m: float
    speed_mps: float


@dataclass(frozen=True)
class SpawnedPedestrian:
    actor: Any
    plan: PedestrianCrossingPlan
    receipt: dict[str, Any]


def _route_xyz(point: Any) -> tuple[float, float, float]:
    if all(hasattr(point, name) for name in ("x", "y", "z")):
        xyz = (float(point.x), float(point.y), float(point.z))
    else:
        xyz = tuple(float(value) for value in point)
        if len(xyz) != 3:
            raise ValueError("route points must contain exactly three coordinates")
    if not all(math.isfinite(value) for value in xyz):
        raise ValueError("route points must be finite")
    return xyz


def plan_one_pedestrian_crossing(
    centerline: Sequence[Any],
    seed: int,
    *,
    route_fraction: float = 0.58,
    lateral_offset_m: float = 1.25,
    speed_mps: float = 1.4,
) -> PedestrianCrossingPlan:
    """Place a walker beside the observed route and aim it across the lane.

    The route fraction, lateral offset, and activation point are sealed by this
    function.  No world transform is changed after spawning; motion is applied
    only through CARLA's walker-control physics interface.
    """

    points = tuple(_route_xyz(point) for point in centerline)
    if len(points) < 2:
        raise ValueError("one-pedestrian requires at least two route points")
    if not 0.1 <= route_fraction <= 0.9:
        raise ValueError("pedestrian route fraction must stay inside the bounded route")
    if not math.isfinite(lateral_offset_m) or lateral_offset_m < 1.0:
        raise ValueError("pedestrian lateral offset must be finite and at least one metre")
    if not math.isfinite(speed_mps) or not 0.2 <= speed_mps <= 3.0:
        raise ValueError("pedestrian speed is outside the bounded walking range")

    lengths: list[float] = []
    total_length = 0.0
    for first, second in zip(points, points[1:]):
        length = math.hypot(second[0] - first[0], second[1] - first[1])
        lengths.append(length)
        total_length += length
    if total_length < 2.0:
        raise ValueError("one-pedestrian requires a route at least two metres long")

    target_length = total_length * route_fraction
    traversed = 0.0
    selected = None
    for index, length in enumerate(lengths):
        if length <= 1e-6:
            continue
        if traversed + length >= target_length or index == len(lengths) - 1:
            fraction = min(1.0, max(0.0, (target_length - traversed) / length))
            first, second = points[index], points[index + 1]
            selected = (first, second, length, fraction)
            break
        traversed += length
    if selected is None:
        raise ValueError("one-pedestrian route contains no usable horizontal segment")

    first, second, segment_length, fraction = selected
    tangent_x = (second[0] - first[0]) / segment_length
    tangent_y = (second[1] - first[1]) / segment_length
    normal_x, normal_y = -tangent_y, tangent_x
    # The manifest seed controls the roadside without introducing runtime
    # randomness.  Even seeds start left of travel and odd seeds start right.
    side = 1.0 if int(seed) % 2 == 0 else -1.0
    center = (
        first[0] + (second[0] - first[0]) * fraction,
        first[1] + (second[1] - first[1]) * fraction,
        first[2] + (second[2] - first[2]) * fraction,
    )
    direction = (-side * normal_x, -side * normal_y, 0.0)
    spawn = (
        center[0] + side * normal_x * lateral_offset_m,
        center[1] + side * normal_y * lateral_offset_m,
        center[2] + 0.25,
    )
    # Begin walking roughly one crossing-time before the ego reaches the
    # crossing.  The fraction is clamped so short and long routes remain
    # bounded and reproducible.
    lead_distance = lateral_offset_m / speed_mps * 3.0
    lead_fraction = min(0.15, max(0.04, lead_distance / total_length))
    activation_progress = max(0.05, route_fraction - lead_fraction)
    return PedestrianCrossingPlan(
        route_fraction=route_fraction,
        activation_progress=activation_progress,
        route_length_m=total_length,
        crossing_center=center,
        spawn_position=spawn,
        direction=direction,
        yaw_degrees=math.degrees(math.atan2(direction[1], direction[0])),
        lateral_offset_m=lateral_offset_m,
        speed_mps=speed_mps,
    )


def apply_pedestrian_motion(carla: Any, pedestrian: SpawnedPedestrian, *, active: bool) -> None:
    """Apply physical walker velocity without teleporting the actor."""

    control = carla.WalkerControl()
    control.direction = carla.Vector3D(
        x=pedestrian.plan.direction[0],
        y=pedestrian.plan.direction[1],
        z=pedestrian.plan.direction[2],
    )
    control.speed = pedestrian.plan.speed_mps if active else 0.0
    control.jump = False
    pedestrian.actor.apply_control(control)


def pedestrian_crossing_distance_m(pedestrian: SpawnedPedestrian) -> float:
    """Return signed horizontal travel along the sealed crossing direction."""

    actual_spawn = pedestrian.receipt["spawn_provenance"].get("actual_spawn_carla")
    if not isinstance(actual_spawn, dict):
        raise RuntimeError("pedestrian crossing distance requested before grounded spawn verification")
    transform = pedestrian.actor.get_transform()
    delta_x = float(transform.location.x) - float(actual_spawn["x"])
    delta_y = float(transform.location.y) - float(actual_spawn["y"])
    return (
        delta_x * pedestrian.plan.direction[0]
        + delta_y * pedestrian.plan.direction[1]
    )


def finalize_pedestrian_spawn_receipt(
    pedestrian: SpawnedPedestrian,
    *,
    maximum_horizontal_warmup_drift_m: float = 0.50,
    maximum_vertical_settle_m: float = 2.0,
) -> dict[str, Any]:
    """Verify the native walker remained at its requested road-side spawn.

    Generated OpenDRIVE maps may not support every actor physics mode. This
    post-warmup gate prevents a walker that fell through the surface from
    being represented as a valid dynamic scenario.
    """

    actual = pedestrian.actor.get_transform()
    position = actual.location
    actual_xyz = (float(position.x), float(position.y), float(position.z))
    if not all(math.isfinite(value) for value in actual_xyz):
        raise RuntimeError("CARLA pedestrian warmup produced a non-finite transform")
    requested = pedestrian.receipt["spawn_provenance"]["requested_spawn_carla"]
    delta_x = actual_xyz[0] - float(requested["x"])
    delta_y = actual_xyz[1] - float(requested["y"])
    delta_z = actual_xyz[2] - float(requested["z"])
    horizontal_drift = math.hypot(delta_x, delta_y)
    vertical_settle = abs(delta_z)
    drift = math.sqrt(delta_x**2 + delta_y**2 + delta_z**2)
    # A CARLA walker is spawned with clearance above the generated OpenDRIVE
    # surface, so a bounded vertical settle is expected. Horizontal motion is
    # not: the brake-held warm-up control has zero speed. Keep those two
    # physical facts separate so a normal gravity settle passes while a
    # falling/sideways actor (the previous -459 m defect) fails closed.
    if (
        horizontal_drift > maximum_horizontal_warmup_drift_m
        or vertical_settle > maximum_vertical_settle_m
    ):
        raise RuntimeError(
            "CARLA pedestrian left the supported road surface during warmup: "
            f"horizontal={horizontal_drift:.3f}m, vertical={vertical_settle:.3f}m, "
            f"requested={tuple(round(value, 3) for value in (float(requested['x']), float(requested['y']), float(requested['z'])))}; "
            f"actual={tuple(round(value, 3) for value in actual_xyz)}"
        )
    pedestrian.receipt["spawn_provenance"]["actual_spawn_carla"] = {
        "x": actual_xyz[0],
        "y": actual_xyz[1],
        "z": actual_xyz[2],
        "yaw_degrees": float(actual.rotation.yaw),
        "warmup_drift_m": drift,
        "warmup_horizontal_drift_m": horizontal_drift,
        "warmup_vertical_settle_m": vertical_settle,
    }
    pedestrian.receipt["spawn_provenance"]["warmup_surface_gate"] = {
        "maximum_horizontal_drift_m": maximum_horizontal_warmup_drift_m,
        "maximum_vertical_settle_m": maximum_vertical_settle_m,
    }
    pedestrian.receipt["spawn_provenance"]["warmup_surface_gate_pass"] = True
    return pedestrian.receipt


def spawn_one_pedestrian(
    world: Any,
    carla: Any,
    centerline: Sequence[Any],
    seed: int,
    owned: OwnedActors,
) -> SpawnedPedestrian:
    """Spawn one real CARLA pedestrian or fail the session closed."""

    plan = plan_one_pedestrian_crossing(centerline, seed)
    library = world.get_blueprint_library()
    blueprints = sorted(
        list(library.filter("walker.pedestrian.*")),
        key=lambda blueprint: str(getattr(blueprint, "id", "")),
    )
    if not blueprints:
        raise RuntimeError("CARLA one-pedestrian profile has no walker blueprints")
    blueprint = blueprints[int(seed) % len(blueprints)]
    if blueprint.has_attribute("is_invincible"):
        blueprint.set_attribute("is_invincible", "false")
    if blueprint.has_attribute("role_name"):
        blueprint.set_attribute("role_name", f"servo-{owned.session_id}")

    requested_x, requested_y, requested_z = plan.spawn_position
    actor = None
    requested_transform = None
    # These are deterministic spawn clearances, not in-run transforms.
    for vertical_clearance in (0.0, 0.25, 0.50):
        requested_transform = carla.Transform(
            carla.Location(
                x=requested_x,
                y=requested_y,
                z=requested_z + vertical_clearance,
            ),
            carla.Rotation(yaw=plan.yaw_degrees),
        )
        actor = world.try_spawn_actor(blueprint, requested_transform)
        if actor is not None:
            break
    if actor is None or requested_transform is None:
        raise RuntimeError("CARLA failed to spawn the deterministic route-relative pedestrian")
    owned.add(actor)
    try:
        spawned = SpawnedPedestrian(actor=actor, plan=plan, receipt={})
        apply_pedestrian_motion(carla, spawned, active=False)
    except Exception as exc:
        raise RuntimeError(f"CARLA pedestrian physics initialization failed: {exc}") from exc

    receipt = {
        "schema": "servo.carla-dynamic-actor/v1",
        "profile": "one-pedestrian",
        "actor_id": int(actor.id),
        "type_id": str(actor.type_id),
        "blueprint_id": str(getattr(blueprint, "id", actor.type_id)),
        "ownership": {
            "session_id": owned.session_id,
            "cleanup_registered": True,
        },
        "spawn_provenance": {
            "method": "deterministic-route-relative-crossing/v1",
            "seed": int(seed),
            "route_fraction": plan.route_fraction,
            "activation_progress": plan.activation_progress,
            "route_length_m": plan.route_length_m,
            "crossing_center_carla": {
                "x": plan.crossing_center[0], "y": plan.crossing_center[1], "z": plan.crossing_center[2]
            },
            "lateral_offset_m": plan.lateral_offset_m,
            "requested_spawn_carla": {
                "x": float(requested_transform.location.x),
                "y": float(requested_transform.location.y),
                "z": float(requested_transform.location.z),
                "yaw_degrees": plan.yaw_degrees,
            },
        },
        "motion": {
            "controller": "carla.WalkerControl",
            "movement_model": "carla-default-walker-character",
            "direction_carla": {
                "x": plan.direction[0], "y": plan.direction[1], "z": plan.direction[2]
            },
            "speed_mps": plan.speed_mps,
            # Both endpoints stay inside T5's sealed 3.5 m driving lane. The
            # earlier 3.25 m offset placed the actor outside the generated road
            # mesh; gravity then exposed that invalid spawn by dropping it.
            "bounded_crossing_distance_m": 2.0 * plan.lateral_offset_m,
            "initial_state": "stationary",
            "teleported_during_run": False,
            "simulate_physics_forced": False,
            "gravity_override": False,
        },
    }
    return SpawnedPedestrian(actor=actor, plan=plan, receipt=receipt)


def quaternion_to_carla_rotation(carla, quaternion):
    w, x, y, z = quaternion.w, quaternion.x, quaternion.y, quaternion.z
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.degrees(math.atan2(sinr_cosp, cosr_cosp))
    sinp = max(-1.0, min(1.0, 2 * (w * y - z * x)))
    pitch = math.degrees(math.asin(sinp))
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.degrees(math.atan2(siny_cosp, cosy_cosp))
    return carla.Rotation(pitch=pitch, yaw=yaw, roll=roll)


def spawn_ego(world, carla, vehicle: VehicleDescriptor, start_pose, owned: OwnedActors):
    library = world.get_blueprint_library()
    blueprint = library.find(vehicle.blueprint)
    if blueprint is None:
        raise RuntimeError(f"CARLA blueprint is unavailable: {vehicle.blueprint}")
    position = start_pose.position
    # Try the requested height, then fall back to higher clearances that match
    # the validation dry-run (1.0 m) for generated OpenDRIVE meshes.
    for offset in (vehicle.spawn_height_offset_m, 1.0, 0.6, 0.35):
        transform = carla.Transform(
            carla.Location(x=position.x, y=position.y, z=position.z + float(offset)),
            quaternion_to_carla_rotation(carla, start_pose.orientation),
        )
        actor = world.try_spawn_actor(blueprint, transform)
        if actor is not None:
            owned.add(actor)
            actor.set_autopilot(False)
            return actor
    raise RuntimeError(f"failed to spawn {vehicle.blueprint} at the validated route start")


def camera_blueprint(world, descriptor: CameraSensorDescriptor):
    kind = {
        "rgb": "sensor.camera.rgb",
        "depth": "sensor.camera.depth",
        "instance-segmentation": "sensor.camera.instance_segmentation",
    }[descriptor.kind]
    blueprint = world.get_blueprint_library().find(kind)
    blueprint.set_attribute("image_size_x", str(descriptor.intrinsics.width))
    blueprint.set_attribute("image_size_y", str(descriptor.intrinsics.height))
    blueprint.set_attribute("fov", str(descriptor.intrinsics.horizontal_fov_deg))
    blueprint.set_attribute("sensor_tick", str(descriptor.sensor_tick_seconds))
    return blueprint


def mount_transform(carla, descriptor: CameraSensorDescriptor):
    position = descriptor.mount_vehicle.position
    return carla.Transform(
        carla.Location(x=position.x, y=-position.y, z=position.z),
        quaternion_to_carla_rotation(carla, descriptor.mount_vehicle.orientation),
    )


def spawn_camera(world, carla, vehicle, descriptor: CameraSensorDescriptor, callback, owned: OwnedActors):
    sensor = world.spawn_actor(camera_blueprint(world, descriptor), mount_transform(carla, descriptor), attach_to=vehicle)
    owned.add(sensor)
    sensor.listen(callback)
    return sensor


def spawn_event_sensors(world, carla, vehicle, callbacks: dict[str, object], fixed_delta_seconds: float, owned: OwnedActors) -> dict[str, object]:
    sensors: dict[str, object] = {}
    definitions = {
        "collision": "sensor.other.collision",
        "lane-invasion": "sensor.other.lane_invasion",
        "imu": "sensor.other.imu",
        "gnss": "sensor.other.gnss",
    }
    for name, blueprint_id in definitions.items():
        blueprint = world.get_blueprint_library().find(blueprint_id)
        if blueprint.has_attribute("sensor_tick"):
            blueprint.set_attribute("sensor_tick", str(fixed_delta_seconds))
        sensor = world.spawn_actor(blueprint, carla.Transform(), attach_to=vehicle)
        owned.add(sensor)
        sensor.listen(callbacks[name])
        sensors[name] = sensor
    return sensors
