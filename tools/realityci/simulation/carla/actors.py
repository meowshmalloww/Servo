"""CARLA ego and sensor spawning with explicit validated ownership."""

from __future__ import annotations

import math

from ...schemas.driving import CameraSensorDescriptor
from ...schemas.simulation import VehicleDescriptor
from .cleanup import OwnedActors


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
