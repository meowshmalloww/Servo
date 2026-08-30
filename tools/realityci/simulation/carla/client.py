"""CARLA client connection, version verification, and runtime smoke preflight."""

from __future__ import annotations

import queue
import time
from pathlib import Path

from . import SUPPORTED_CARLA_VERSION
from .discovery import import_carla


class CarlaVersionMismatch(RuntimeError):
    pass


def connect_verified(python_api_path: str, host: str, port: int, timeout_s: float = 10.0):
    carla, _ = import_carla(Path(python_api_path))
    client = carla.Client(host, port)
    client.set_timeout(timeout_s)
    client_version = str(client.get_client_version())
    server_version = str(client.get_server_version())
    if client_version != SUPPORTED_CARLA_VERSION or server_version != SUPPORTED_CARLA_VERSION:
        raise CarlaVersionMismatch(
            f"CARLA version mismatch: client={client_version}, server={server_version}, "
            f"expected={SUPPORTED_CARLA_VERSION}. Register and launch CARLA 0.9.16."
        )
    return carla, client, client_version, server_version


def full_runtime_preflight(python_api_path: str, host: str, port: int, *, rendering: bool) -> dict:
    carla, client, client_version, server_version = connect_verified(python_api_path, host, port, 20.0)
    actors: list[object] = []
    original_settings = None
    frame_bytes = 0
    moved_m = 0.0
    try:
        world = client.load_world("Town01")
        original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        settings.no_rendering_mode = not rendering
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        world.apply_settings(settings)
        blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2020")
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("Town01 did not provide a spawn point")
        vehicle = world.try_spawn_actor(blueprint, spawn_points[0])
        if vehicle is None:
            raise RuntimeError("failed to spawn vehicle.lincoln.mkz_2020 in Town01")
        actors.append(vehicle)
        # A freshly spawned CARLA vehicle is manual-control by default. Do not
        # call set_autopilot(False): that API still opens a Traffic Manager
        # connection and CARLA 0.9.16 can abort when no TM is serving a
        # generated OpenDRIVE world. Servo proves manual mode by exclusively
        # applying VehicleControl below and never registering this ego with TM.
        frames: queue.Queue[bytes] = queue.Queue(maxsize=4)
        if rendering:
            camera_blueprint = world.get_blueprint_library().find("sensor.camera.rgb")
            camera_blueprint.set_attribute("image_size_x", "160")
            camera_blueprint.set_attribute("image_size_y", "90")
            camera_blueprint.set_attribute("sensor_tick", "0.05")
            camera = world.spawn_actor(camera_blueprint, carla.Transform(carla.Location(x=1.5, z=1.4)), attach_to=vehicle)
            actors.append(camera)
            camera.listen(lambda image: frames.put_nowait(bytes(image.raw_data)) if not frames.full() else None)
        for _ in range(10):
            vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
            world.tick()
        start = vehicle.get_location()
        for _ in range(30):
            vehicle.apply_control(carla.VehicleControl(throttle=0.35, steer=0.0, brake=0.0))
            world.tick()
        end = vehicle.get_location()
        moved_m = float(start.distance(end))
        if moved_m <= 0.1:
            raise RuntimeError(f"physics movement preflight failed: distance={moved_m:.3f} m")
        if rendering:
            deadline = time.monotonic() + 2.0
            while frames.empty() and time.monotonic() < deadline:
                world.tick()
            if frames.empty():
                raise RuntimeError("CARLA camera did not produce a frame")
            frame_bytes = len(frames.get())
            if frame_bytes == 0:
                raise RuntimeError("CARLA camera produced an empty frame")
        return {
            "ready": True,
            "client_version": client_version,
            "server_version": server_version,
            "map": world.get_map().name,
            "vehicle_blueprint": "vehicle.lincoln.mkz_2020",
            "autopilot": False,
            "distance_moved_m": moved_m,
            "sensor_frame_bytes": frame_bytes,
        }
    finally:
        for actor in reversed(actors):
            try:
                if hasattr(actor, "stop"):
                    actor.stop()
                actor.destroy()
            except Exception:
                pass
        if original_settings is not None:
            try:
                world.apply_settings(original_settings)
            except Exception:
                pass


def validate_opendrive_dry_run(python_api_path: str, host: str, port: int, xodr_path: Path) -> dict:
    """Generate a Servo corridor, spawn the supported ego, and prove physics movement."""
    carla, client, client_version, server_version = connect_verified(python_api_path, host, port, 20.0)
    actors: list[object] = []
    original_settings = None
    world = None
    try:
        parameters = carla.OpendriveGenerationParameters(
            vertex_distance=2.0,
            max_road_length=50.0,
            wall_height=0.5,
            additional_width=0.6,
            smooth_junctions=False,
            enable_mesh_visibility=False,
        )
        world = client.generate_opendrive_world(xodr_path.read_text(encoding="utf-8"), parameters)
        if world is None or world.get_map() is None:
            raise RuntimeError("CARLA did not create a map from the generated OpenDRIVE")
        original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        settings.no_rendering_mode = True
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        world.apply_settings(settings)
        # CARLA cooks generated procedural-mesh collision asynchronously.
        # Advance the new world before placing a physics actor on that mesh.
        for _ in range(20):
            world.tick()
        waypoints = world.get_map().generate_waypoints(2.0)
        if not waypoints:
            raise RuntimeError("generated OpenDRIVE has no CARLA waypoints")
        # Do not straddle the open road boundary with the vehicle's wheelbase.
        # Spawn one quarter into the corridor, leaving stopping room ahead.
        road_length = max(float(getattr(waypoint, "s", 0.0)) for waypoint in waypoints)
        spawn_waypoint = min(waypoints, key=lambda waypoint: abs(float(getattr(waypoint, "s", 0.0)) - road_length * 0.25))
        spawn = spawn_waypoint.transform
        # Generated OpenDRIVE waypoint transforms sit on the road surface.
        # Give the full vehicle bounding box clearance, then let suspension
        # settle under braking before applying throttle.
        spawn.location.z += 1.0
        blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2020")
        vehicle = world.try_spawn_actor(blueprint, spawn)
        if vehicle is None:
            raise RuntimeError("CARLA dry-run could not spawn vehicle.lincoln.mkz_2020 on the route")
        actors.append(vehicle)
        # Keep the default manual-control state; see full_runtime_preflight.
        for _ in range(40):
            vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
            world.tick()
        start = vehicle.get_location()
        for _ in range(100):
            vehicle.apply_control(carla.VehicleControl(throttle=0.6, steer=0.0, brake=0.0))
            world.tick()
        moved = float(start.distance(vehicle.get_location()))
        if moved <= 0.5:
            raise RuntimeError(f"generated-world physics dry-run moved only {moved:.3f} m")
        return {
            "ready": True,
            "client_version": client_version,
            "server_version": server_version,
            "waypoint_count": len(waypoints),
            "vehicle_blueprint": "vehicle.lincoln.mkz_2020",
            "autopilot": False,
            "distance_moved_m": moved,
        }
    finally:
        for actor in reversed(actors):
            try:
                actor.destroy()
            except Exception:
                pass
        if world is not None and original_settings is not None:
            try:
                world.apply_settings(original_settings)
            except Exception:
                pass
