"""Execute and receipt the strict local DriveMA two-turn adapter."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--views", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    from tools.realityci.driving.policies import drivema_service as service

    if service.REAL_MODEL is None or service.REAL_MODEL_ROOT is None:
        raise RuntimeError(service.REAL_MODEL_ERROR or "DriveMA failed to load")
    frames = {}
    hashes = {}
    for key in service.VIEW_KEYS:
        path = args.views / f"{key}.jpg"
        array = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
        frames[key] = {
            "encoding": "rgb8-base64",
            "shape": list(array.shape),
            "data": base64.b64encode(array.tobytes(order="C")).decode("ascii"),
        }
        hashes[path.name] = _sha256(path)
    payload = {
        "schema_name": "servo.external-driving-request/v1",
        "navigation_command": "follow_lane",
        "ego_speed_mps": 2.0,
        "ego_acceleration_mps2": 0.0,
        "recent_ego_poses": [[float(index) * 0.5, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0] for index in range(16)],
        "camera_frames": frames,
    }
    started = time.perf_counter()
    result = service._real_inference(payload)
    elapsed = time.perf_counter() - started
    model_weight = service.REAL_MODEL_ROOT / "model.safetensors"
    receipt = {
        "schema_name": "servo.drivema-local-qualification/v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "qualified": True,
        "model_root": str(service.REAL_MODEL_ROOT.resolve()),
        "model_weight_sha256": _sha256(model_weight),
        "base_architecture": "Qwen3.5-2B",
        "device": service.REAL_DEVICE,
        "heuristic_fallback": False,
        "prompt_contract": "official-drivema-three-view-two-turn",
        "view_hashes": hashes,
        "inference_seconds": elapsed,
        "meta_action": result["meta_action"],
        "trajectory_text": result["trajectory_text"],
        "action": {
            "waypoints": result["waypoints"],
            "desired_speed_mps": result["desired_speed_mps"],
            "confidence": result["confidence"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
