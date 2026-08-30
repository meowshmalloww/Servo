"""Fail-closed DriveMA-2B service using the official two-turn contract.

Only the local DriveMA checkpoint and three ordered camera views are accepted.
There is deliberately no heuristic or base-Qwen driving fallback: a load,
inference, parse, or provenance failure returns an error so CARLA brakes.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    import uvicorn

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


CANDIDATE_ROOTS = (
    Path(r"D:\Servo\runtime\checkpoints\DriveMA-2B"),
    Path(r"D:\VheicleBrain\DriveMA-2B"),
    Path(r"D:\VehicleBrain\DriveMA-2B"),
    Path(r"D:\ServoExternal\models\DriveMA-2B"),
)
VIEW_KEYS = ("front_left", "front", "front_right")
REAL_MODEL_ROOT = next(
    (
        root
        for root in CANDIDATE_ROOTS
        if (root / "config.json").is_file()
        and (root / "model.safetensors").is_file()
    ),
    None,
)
REAL_MODEL = None
REAL_PROCESSOR = None
SCENE_MODEL_ROOT = next((root for root in (
    Path(r"D:\VheicleBrain\Qwen3.5-2B"),
    Path(r"D:\VehicleBrain\Qwen3.5-2B"),
) if (root / "config.json").is_file() and (root / "model.safetensors.index.json").is_file()), None)
SCENE_MODEL = None
SCENE_PROCESSOR = None
SCENE_MODEL_ERROR: str | None = None
SCENE_DEVICE = "cpu"
REAL_MODEL_ERROR: str | None = None
REAL_DEVICE = "cuda" if __import__("torch").cuda.is_available() else "cpu"
AUDIT_LOG = Path(os.environ.get(
    "SERVO_DRIVEMA_AUDIT_LOG",
    r"D:\Servo\simulations\runtime\t5\evidence\drivema\inference-audit.jsonl",
))

if REAL_MODEL_ROOT is not None:
    try:
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor

        dtype = torch.bfloat16 if REAL_DEVICE == "cuda" else torch.float32
        REAL_PROCESSOR = AutoProcessor.from_pretrained(
            str(REAL_MODEL_ROOT), trust_remote_code=True, local_files_only=True
        )
        REAL_MODEL = AutoModelForMultimodalLM.from_pretrained(
            str(REAL_MODEL_ROOT),
            dtype=dtype,
            device_map="auto" if REAL_DEVICE == "cuda" else None,
            trust_remote_code=True,
            local_files_only=True,
        )
        if REAL_DEVICE == "cpu":
            REAL_MODEL = REAL_MODEL.to(REAL_DEVICE)
        REAL_MODEL.eval()
        print(f"[DriveMA] Loaded {REAL_MODEL_ROOT} on {REAL_DEVICE}")
    except Exception as exc:  # noqa: BLE001
        REAL_MODEL_ERROR = str(exc)
        print(f"[DriveMA] Model load failed: {exc}")
        REAL_MODEL = None
        REAL_PROCESSOR = None
else:
    REAL_MODEL_ERROR = "DriveMA-2B checkpoint was not found"
    print(f"[DriveMA] {REAL_MODEL_ERROR}")


def _fmt_xy(value: list[float] | tuple[float, ...]) -> str:
    return f"[{float(value[0]):.2f}, {float(value[1]):.2f}]"


def _history(payload: dict[str, Any]) -> tuple[str, str, str]:
    poses = payload.get("recent_ego_poses") or ()
    xy = [
        [float(pose[0]), float(pose[2])]
        for pose in poses
        if isinstance(pose, (list, tuple)) and len(pose) >= 3
    ]
    if not xy:
        xy = [[0.0, 0.0]]
    origin = xy[-1]
    relative = [
        [point[0] - origin[0], -(point[1] - origin[1])]
        for point in xy[-16:]
    ]
    relative = [relative[0]] * (16 - len(relative)) + relative
    speed = float(payload.get("ego_speed_mps", 0.0))
    accel = float(payload.get("ego_acceleration_mps2", 0.0))
    past_traj = ", ".join(_fmt_xy(point) for point in relative)
    past_velocity = ", ".join(_fmt_xy([speed, 0.0]) for _ in range(16))
    past_accel = ", ".join(_fmt_xy([accel, 0.0]) for _ in range(16))
    return past_traj, past_accel, past_velocity


def _first_prompt(payload: dict[str, Any]) -> str:
    past_traj, past_accel, past_velocity = _history(payload)
    intent = str(payload.get("navigation_command", "follow_lane")).replace("_", " ")
    speed = float(payload.get("ego_speed_mps", 0.0))
    accel = float(payload.get("ego_acceleration_mps2", 0.0))
    return (
        "You are an expert driver.\n"
        "Input:\n"
        "- 1 frame of multi-view images collected from the ego-vehicle at the present timestep: "
        "front_left_view: <image>; front_view:<image>; front_right_view:<image>\n"
        f"- Current high-level intent:{intent}\n"
        f"- Current acceleration is [{accel:.2f}, 0.00]\n"
        f"- Current velocity is [{speed:.2f}, 0.00]\n"
        f"- 4-second past trajectory (16 steps at 4 Hz):{past_traj}\n"
        f"- 4-second past acceleration (16 steps at 4 Hz):{past_accel}\n"
        f"- 4-second past velocity (16 steps at 4 Hz):{past_velocity}\n"
        "Coordinate System Definition: X-axis: positive forward, negative backward; "
        "Y-axis: positive left, negative right.\n"
        "Task: Inspect the input and make the decision.\n"
        "Output format:\n"
        "longitudinal action: xx, lateral action: xx"
    )


SECOND_PROMPT = (
    "Task: Given the above information, predict the optimal 5-second future "
    "trajectory (5 steps at 1 Hz) of the ego vehicle.\n"
    "Output format:\n"
    "[x_1, y_1], [x_2, y_2], [x_3, y_3], [x_4, y_4], [x_5, y_5]"
)


def _decode_images(payload: dict[str, Any]):
    from PIL import Image

    frames = payload.get("camera_frames", {})
    if set(frames) != set(VIEW_KEYS):
        raise ValueError(f"DriveMA requires exactly these camera IDs: {VIEW_KEYS}")
    images = []
    for key in VIEW_KEYS:
        frame = frames[key]
        if frame.get("encoding") != "rgb8-base64":
            raise ValueError(f"unsupported {key} camera encoding")
        shape = frame.get("shape")
        if not isinstance(shape, list) or len(shape) != 3 or shape[2] != 3:
            raise ValueError(f"invalid {key} camera shape")
        raw = base64.b64decode(frame.get("data", ""), validate=True)
        expected = int(shape[0]) * int(shape[1]) * 3
        if len(raw) != expected:
            raise ValueError(f"{key} camera byte count does not match its shape")
        array = np.frombuffer(raw, dtype=np.uint8).reshape(shape).copy()
        images.append(Image.fromarray(array, mode="RGB"))
    return images


def _generate_with(model, processor, messages: list[dict[str, Any]], max_new_tokens: int) -> str:
    import torch

    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = {
        key: value.to(model.device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }
    input_length = inputs["input_ids"].shape[1]
    with torch.inference_mode():
        output = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False
        )
    return processor.batch_decode(
        output[:, input_length:], skip_special_tokens=True
    )[0].strip()


def _generate(messages: list[dict[str, Any]], max_new_tokens: int) -> str:
    return _generate_with(REAL_MODEL, REAL_PROCESSOR, messages, max_new_tokens)


def _real_inference(payload: dict[str, Any]) -> dict[str, Any]:
    if REAL_MODEL is None or REAL_PROCESSOR is None:
        raise RuntimeError(REAL_MODEL_ERROR or "DriveMA model is unavailable")
    images = _decode_images(payload)
    first_content = [
        *({"type": "image", "image": image} for image in images),
        {"type": "text", "text": _first_prompt(payload)},
    ]
    first_messages = [{"role": "user", "content": first_content}]
    meta_action = _generate(first_messages, max_new_tokens=48)
    if not re.fullmatch(
        r"(?:<decision>\s*)?longitudinal action:\s*[^,;\n]+[,;]\s*"
        r"lateral action:\s*[^<\n]+(?:\s*</decision>)?",
        meta_action,
        flags=re.IGNORECASE,
    ):
        raise ValueError(f"DriveMA returned an invalid meta-action: {meta_action!r}")
    second_messages = [
        *first_messages,
        {"role": "assistant", "content": meta_action},
        {"role": "user", "content": [{"type": "text", "text": SECOND_PROMPT}]},
    ]
    trajectory_text = _generate(second_messages, max_new_tokens=96)
    pairs = re.findall(
        r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
        trajectory_text,
    )
    if len(pairs) != 5:
        raise ValueError(
            f"DriveMA returned an invalid five-point trajectory: {trajectory_text!r}"
        )
    points = [(float(x), float(y)) for x, y in pairs]
    return {
        "waypoints": [
            {
                "time_offset_s": float(index),
                "x_forward_m": x,
                "y_left_m": y,
            }
            for index, (x, y) in enumerate(points, start=1)
        ],
        # The hackathon route is a short, nonmetric reconstructed corridor.
        # Keep DriveMA's geometry intact while enforcing a walking/jogging
        # speed envelope at the policy boundary (14.4 km/h maximum).
        "desired_speed_mps": max(0.0, min(4.0, points[-1][0] / 5.0)),
        "confidence": 0.85,
        "meta_action": meta_action,
        "trajectory_text": trajectory_text,
    }


def _scene_inference(payload: dict[str, Any]) -> str:
    _ensure_scene_model()
    if SCENE_MODEL is None or SCENE_PROCESSOR is None:
        raise RuntimeError(SCENE_MODEL_ERROR or "Qwen3.5-2B roadside detector is unavailable")
    images = _decode_images(payload)
    messages = [{"role": "user", "content": [
        *({"type": "image", "image": image} for image in images),
        {"type": "text", "text": (
            "Inspect these synchronized front-left, front, and front-right road views. "
            "Name visible roadside objects and driving hazards in plain words. "
            "Do not output coordinates, trajectories, or driving actions. "
            "Return one short comma-separated line, or none."
        )},
    ]}]
    text = _generate_with(SCENE_MODEL, SCENE_PROCESSOR, messages, max_new_tokens=64)
    if not text or len(text) > 512 or re.search(r"\[\s*-?\d+(?:\.\d+)?\s*,", text):
        raise ValueError("roadside detector did not return a valid object description")
    return text


def _ensure_scene_model() -> None:
    """Lazily load the optional roadside-description model.

    DriveMA owns the driving action.  The independent description model must
    not consume memory during policy qualification or make a valid DriveMA
    checkpoint unavailable when its own load fails.
    """
    global SCENE_MODEL, SCENE_PROCESSOR, SCENE_MODEL_ERROR
    if SCENE_MODEL is not None and SCENE_PROCESSOR is not None:
        return
    if SCENE_MODEL_ERROR is not None:
        raise RuntimeError(SCENE_MODEL_ERROR)
    if SCENE_MODEL_ROOT is None:
        SCENE_MODEL_ERROR = "Qwen3.5-2B roadside detector checkpoint was not found"
        raise RuntimeError(SCENE_MODEL_ERROR)
    try:
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor

        SCENE_PROCESSOR = AutoProcessor.from_pretrained(
            str(SCENE_MODEL_ROOT), trust_remote_code=True, local_files_only=True
        )
        SCENE_MODEL = AutoModelForMultimodalLM.from_pretrained(
            str(SCENE_MODEL_ROOT),
            dtype=torch.bfloat16,
            device_map=None,
            trust_remote_code=True,
            local_files_only=True,
        ).to(SCENE_DEVICE)
        SCENE_MODEL.eval()
        print(f"[DriveMA] Loaded roadside detector {SCENE_MODEL_ROOT} on {SCENE_DEVICE}")
    except Exception as exc:  # noqa: BLE001
        SCENE_MODEL = None
        SCENE_PROCESSOR = None
        SCENE_MODEL_ERROR = str(exc)
        raise RuntimeError(SCENE_MODEL_ERROR) from exc


if HAS_FASTAPI:
    app = FastAPI(title="servo-drivema-2b", version="2.0.0")

    @app.get("/healthz")
    def healthz():
        return {
            "status": "ok" if REAL_MODEL is not None else "unavailable",
            "model_root": str(REAL_MODEL_ROOT) if REAL_MODEL_ROOT else None,
            "real_model_loaded": REAL_MODEL is not None,
            "device": REAL_DEVICE,
            "error": REAL_MODEL_ERROR,
            "heuristic_fallback": False,
            "view_keys": VIEW_KEYS,
            "prompt_contract": "official-drivema-two-turn",
            "roadside_detection": "three-view-vlm-audited",
            "roadside_model_root": str(SCENE_MODEL_ROOT) if SCENE_MODEL_ROOT else None,
            "roadside_device": SCENE_DEVICE,
            "roadside_model_loaded": SCENE_MODEL is not None,
        }

    @app.post("/")
    @app.post("/predict")
    def predict(payload: dict[str, Any]):
        if payload.get("schema_name") != "servo.external-driving-request/v1":
            return JSONResponse(status_code=400, content={"error": "unsupported schema"})
        if REAL_MODEL is None:
            return JSONResponse(
                status_code=503,
                content={"error": REAL_MODEL_ERROR or "model unavailable"},
            )
        started = time.perf_counter()
        try:
            trajectory = _real_inference(payload)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=422, content={"error": str(exc)})
        audit = {
            "schema_name": "servo.drivema-inference/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "frame_id": payload.get("frame_id"),
            "model": str(REAL_MODEL_ROOT),
            "heuristic_fallback": False,
            "latency_ms": (time.perf_counter() - started) * 1000.0,
            "meta_action": trajectory["meta_action"],
            "trajectory_text": trajectory["trajectory_text"],
        }
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(audit, separators=(",", ":")) + "\n")
        return {
            "schema_name": "servo.external-driving-response/v1",
            "action": {
                "kind": "trajectory",
                "waypoints": trajectory["waypoints"],
                "desired_speed_mps": trajectory["desired_speed_mps"],
                "confidence": trajectory["confidence"],
            },
            "provenance": {
                "model": str(REAL_MODEL_ROOT),
                "real": True,
                "device": REAL_DEVICE,
                "heuristic_fallback": False,
                "prompt_contract": "official-drivema-two-turn",
                "meta_action": trajectory["meta_action"],
                "trajectory_text": trajectory["trajectory_text"],
            },
        }

    @app.post("/detect")
    def detect(payload: dict[str, Any]):
        if payload.get("schema_name") != "servo.external-driving-request/v1":
            return JSONResponse(status_code=400, content={"error": "unsupported schema"})
        try:
            observation = _scene_inference(payload)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return {
            "schema_name": "servo.roadside-detection/v1",
            "model": str(SCENE_MODEL_ROOT),
            "camera_ids": list(VIEW_KEYS),
            "observation": observation,
        }

    def main():
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, default=8002)
        parser.add_argument("--host", type=str, default="127.0.0.1")
        args = parser.parse_args()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")

    if __name__ == "__main__":
        main()
else:
    print("FastAPI is unavailable; DriveMA service cannot start")
