"""Create a real physical-driving session on the current T5 companion.

The reference mode is the fast integration proof: CARLA BehaviorAgent owns
the driving decision and CARLA owns physics.  DriveMA mode uses the local
official checkpoint through Servo's external policy service.  Both modes see
the same live, unsnapped T5 Gaussian camera poses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
import urllib.error
from pathlib import Path


DEFAULT_WORLD = Path(
    r"D:\Servo\runtime\reconstruction\jobs\yosemite-t5-hybrid-full-route-v1-20260828"
    r"\stages\publish\world\execution\carla-v2-camera-height\execution-manifest.json"
)
DEFAULT_MODEL_CANDIDATES = (
    Path(r"D:\Servo\runtime\checkpoints\DriveMA-2B\model.safetensors"),
    Path(r"D:\VheicleBrain\DriveMA-2B\model.safetensors"),
    Path(r"D:\VehicleBrain\DriveMA-2B\model.safetensors"),
)


def _default_model() -> Path:
    return next((path for path in DEFAULT_MODEL_CANDIDATES if path.is_file()), DEFAULT_MODEL_CANDIDATES[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _camera(sensor_id: str, yaw_deg: float) -> dict:
    half = math.radians(yaw_deg) / 2.0
    return {
        "sensor_id": sensor_id,
        "kind": "rgb",
        "mount_vehicle": {
            "position": {"x": 1.5, "y": 0.0, "z": 1.4},
            "orientation": {
                "w": math.cos(half),
                "x": 0.0,
                "y": 0.0,
                "z": math.sin(half),
            },
        },
        "intrinsics": {
            "width": 960,
            "height": 540,
            "horizontal_fov_deg": 90.0,
            "fx": 480.0,
            "fy": 480.0,
            "cx": 480.0,
            "cy": 270.0,
        },
        "sensor_tick_seconds": 0.05,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--campaign-id",
        default=None,
        help="Optional durable RealityCI campaign ID to bind this simulation session to.",
    )
    parser.add_argument(
        "--world",
        type=Path,
        default=DEFAULT_WORLD,
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=_default_model(),
    )
    parser.add_argument("--policy", choices=("behavior", "drivema"), default="behavior")
    parser.add_argument("--source", choices=("servo-gaussian", "carla-rgb"), default="servo-gaussian")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--policy-hz", type=int, default=None)
    parser.add_argument("--weather", choices=("clear", "snow"), default="clear")
    parser.add_argument("--snow-accumulation", type=float, default=0.90)
    parser.add_argument(
        "--dynamic-actor-profile",
        choices=("none", "one-pedestrian"),
        default="none",
        help="Optional bounded real-CARLA actor scenario.",
    )
    args = parser.parse_args()
    if not args.world.is_file():
        raise FileNotFoundError(args.world)
    if args.policy == "drivema" and not args.model.is_file():
        raise FileNotFoundError(args.model)
    if not 0.0 <= args.snow_accumulation <= 1.0:
        raise ValueError("--snow-accumulation must be in [0, 1]")

    if args.policy == "behavior":
        policy = {
            "adapter": "carla-behavior-reference",
            "name": "CARLA sealed-corridor reference",
            "adapter_version": "servo-carla-sealed-corridor-15kmh/v5",
            "checkpoint_uri": None,
            "checkpoint_sha256": None,
            "oracle": True,
            "uses_privileged_state": True,
            "trainable": False,
            "eligible_for_promotion": False,
            "input_camera_ids": ["front"],
            "uses_ego_speed": True,
            "uses_ego_acceleration": False,
            "uses_recent_ego_poses": False,
            "uses_previous_action": False,
        }
        additional_cameras: list[dict] = []
        policy_hz = args.policy_hz or 10
        deadline_ms = 1000.0
    else:
        policy = {
            "adapter": "external-driving",
            "name": "Local DriveMA-2B (Qwen3.5-2B)",
            "adapter_version": "official-drivema-two-turn/v1",
            "checkpoint_uri": str(args.model.resolve()),
            "checkpoint_sha256": _sha256(args.model),
            "oracle": False,
            "uses_privileged_state": False,
            "trainable": False,
            "eligible_for_promotion": False,
            "input_camera_ids": ["front_left", "front", "front_right"],
            "uses_ego_speed": True,
            "uses_ego_acceleration": True,
            "uses_recent_ego_poses": True,
            "uses_previous_action": True,
        }
        additional_cameras = [_camera("front_left", -15.0), _camera("front_right", 15.0)]
        policy_hz = args.policy_hz or 1
        # CARLA is paused in synchronous mode while the local VLM runs. Keep a
        # hard fail-closed deadline, but allow the validated schema maximum so
        # a T5 tile handoff does not masquerade as a disconnected policy.
        deadline_ms = 30000.0

    request_body = {
        "world_execution_manifest": str(args.world.resolve()),
        "route_id": "primary",
        "vehicle": {
            "blueprint": "vehicle.lincoln.mkz_2020",
            "physics_configuration": "carla-default",
            "spawn_height_offset_m": 0.25,
        },
        "policy": policy,
        "observation": {
            "source": args.source,
            "renderer_version": "servo-headless-gsplat-live-camera/v3" if args.source == "servo-gaussian" else "carla-rgb-0.9.16/v1",
            "camera": _camera("front", 0.0),
            "additional_cameras": additional_cameras,
            "record_policy_frames": True,
        },
        "scenario": {
            "seed": 42,
            "maximum_duration_s": args.duration,
            "weather": args.weather,
            "snow_accumulation": args.snow_accumulation,
            "dynamic_actor_profile": args.dynamic_actor_profile,
        },
        "timing": {
            "fixed_delta_seconds": 0.05,
            "policy_hz": policy_hz,
            "sensor_hz": 20,
            "policy_deadline_ms": deadline_ms,
        },
        "recording": {
            "save_policy_frames": True,
            "save_every_nth_frame": 1,
            "encode_preview_video": True,
            "maximum_saved_frames": 600,
            "run_roadside_detection": False,
        },
        "resource_profile": "balanced",
    }
    if args.campaign_id:
        request_body["campaign_id"] = args.campaign_id
    request = urllib.request.Request(
        args.api.rstrip("/") + "/v1/simulations",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", errors="replace")) from exc
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
