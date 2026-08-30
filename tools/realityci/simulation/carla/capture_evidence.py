"""Capture visual evidence from a Servo-owned packaged CARLA runtime."""

from __future__ import annotations

import argparse
import queue
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from ...hashing import sha256_file
from ..session_store import atomic_write_json
from .client import connect_verified
from .discovery import discover_runtime, find_free_port
from .process_manager import CarlaProcessManager


def capture(output: Path, *, carla_root: str | None = None, frames: int = 80) -> dict:
    discovery = discover_runtime(carla_root)
    if not discovery.ready or not discovery.root or not discovery.python_api_path:
        raise RuntimeError("packaged CARLA 0.9.16 runtime is not ready: " + "; ".join(discovery.errors))

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rpc_port = find_free_port()
    manager = CarlaProcessManager(Path(discovery.root), output / "server.json")
    manager.launch(
        discovery,
        require_rendering=True,
        rpc_port=rpc_port,
        traffic_manager_port=find_free_port(),
    )
    actors: list[object] = []
    world = None
    original_settings = None
    video_path = output / "servo-carla-managed-drive.mp4"
    image_path = output / "servo-carla-managed-drive.jpg"
    try:
        deadline = time.monotonic() + 90.0
        while True:
            try:
                carla, client, client_version, server_version = connect_verified(
                    discovery.python_api_path, "127.0.0.1", rpc_port, 2.0
                )
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("CARLA server did not become ready within 90 seconds")
                time.sleep(0.5)

        client.set_timeout(20.0)
        world = client.load_world("Town01")
        original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        settings.no_rendering_mode = False
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        world.apply_settings(settings)

        blueprints = world.get_blueprint_library()
        vehicle = world.spawn_actor(
            blueprints.find("vehicle.lincoln.mkz_2020"),
            world.get_map().get_spawn_points()[0],
        )
        actors.append(vehicle)
        camera_blueprint = blueprints.find("sensor.camera.rgb")
        width, height = 640, 360
        camera_blueprint.set_attribute("image_size_x", str(width))
        camera_blueprint.set_attribute("image_size_y", str(height))
        camera_blueprint.set_attribute("fov", "90")
        camera_blueprint.set_attribute("sensor_tick", "0.05")
        camera = world.spawn_actor(
            camera_blueprint,
            carla.Transform(carla.Location(x=1.4, z=1.5)),
            attach_to=vehicle,
        )
        actors.append(camera)
        images: queue.Queue[object] = queue.Queue(maxsize=8)
        camera.listen(lambda image: images.put_nowait(image) if not images.full() else None)

        for _ in range(12):
            vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
            world.tick()
        while not images.empty():
            images.get_nowait()

        start = vehicle.get_location()
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 20.0, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not create the CARLA evidence video")
        representative = None
        try:
            for index in range(frames):
                vehicle.apply_control(carla.VehicleControl(throttle=0.42, steer=0.0, brake=0.0))
                simulation_frame = int(world.tick())
                image = images.get(timeout=3.0)
                bgr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((height, width, 4))[:, :, :3].copy()
                speed = vehicle.get_velocity()
                speed_kmh = 3.6 * float((speed.x * speed.x + speed.y * speed.y + speed.z * speed.z) ** 0.5)
                cv2.rectangle(bgr, (0, 0), (width, 48), (0, 0, 0), thickness=-1)
                cv2.putText(
                    bgr,
                    f"Servo managed CARLA 0.9.16 | frame {simulation_frame} | {speed_kmh:.1f} km/h",
                    (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA,
                )
                writer.write(bgr)
                if index == frames // 2:
                    representative = bgr.copy()
        finally:
            writer.release()

        if representative is None or not cv2.imwrite(str(image_path), representative):
            raise RuntimeError("OpenCV could not create the CARLA evidence image")
        distance = float(start.distance(vehicle.get_location()))
        if distance <= 0.1:
            raise RuntimeError(f"CARLA evidence drive did not move: {distance:.3f} m")
        result = {
            "schema_name": "servo.carla-visual-evidence/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "managed_by_servo": True,
            "runtime_root": discovery.root,
            "client_version": client_version,
            "server_version": server_version,
            "map": world.get_map().name,
            "vehicle_blueprint": "vehicle.lincoln.mkz_2020",
            "autopilot": False,
            "rpc_port": rpc_port,
            "frame_count": frames,
            "resolution": [width, height],
            "distance_moved_m": distance,
            "image": str(image_path),
            "image_sha256": sha256_file(str(image_path)),
            "video": str(video_path),
            "video_sha256": sha256_file(str(video_path)),
            "carla_executable_sha256": discovery.executable_sha256,
            "carla_python_api_sha256": discovery.python_api_sha256,
        }
        atomic_write_json(output / "evidence.json", result)
        return result
    finally:
        for actor in reversed(actors):
            try:
                if hasattr(actor, "stop"):
                    actor.stop()
                actor.destroy()
            except Exception:
                pass
        if world is not None and original_settings is not None:
            try:
                world.apply_settings(original_settings)
            except Exception:
                pass
        manager.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("simulations/runtime/carla/evidence"))
    parser.add_argument("--carla-root")
    parser.add_argument("--frames", type=int, default=80)
    arguments = parser.parse_args()
    print(capture(arguments.output, carla_root=arguments.carla_root, frames=arguments.frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
