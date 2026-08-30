#!/usr/bin/env python3
"""Prepare a sealed 120-frame HorizonStream geometry preflight.

The tool copies no model weights and installs no dependencies.  It converts a
completed Servo T1 evidence-selection receipt into HorizonStream's supported
``data.image_paths`` configuration and records the exact external source
commit, input frames, and intended command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


SCHEMA = "servo.external-horizonstream-preflight/v1"
EXPECTED_SELECTION_SCHEMA = "servo.t1-video-evidence-selection/v1"
DEFAULT_FRAME_COUNT = 120
MAX_MODEL_BYTES = 10 * 1024**3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def link_or_copy(source: Path, target: Path) -> str:
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        shutil.copy2(source, target)
        return "copy"


def git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("HorizonStream root is not a readable Git checkout.")
    return result.stdout.strip()


def choose_contiguous_frames(
    frames: list[dict[str, Any]], count: int
) -> tuple[int, list[dict[str, Any]]]:
    if count < 3:
        raise RuntimeError("The preflight needs at least three frames.")
    if len(frames) < count:
        raise RuntimeError(
            f"The selection has {len(frames)} frames, fewer than requested {count}."
        )
    # A centered contiguous segment is deterministic and avoids selecting only
    # the start/end transient of the capture.  It also preserves the exact
    # temporal order needed by a streaming geometry model.
    start = (len(frames) - count) // 2
    return start, frames[start : start + count]


def prepare(
    *,
    selection_receipt: Path,
    horizonstream_root: Path,
    output_root: Path,
    frame_count: int = DEFAULT_FRAME_COUNT,
    checkpoint: Path | None = None,
) -> dict[str, Any]:
    selection_receipt = selection_receipt.resolve()
    horizonstream_root = horizonstream_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite output: {output_root}")
    if not (horizonstream_root / "infer.py").is_file():
        raise RuntimeError("HorizonStream infer.py is missing.")
    base_config = horizonstream_root / "configs" / "horizonstream_infer.yaml"
    if not base_config.is_file():
        raise RuntimeError("HorizonStream inference config is missing.")

    selection = json.loads(selection_receipt.read_text(encoding="utf-8"))
    if selection.get("schema") != EXPECTED_SELECTION_SCHEMA:
        raise RuntimeError("The T1 selection receipt schema is unsupported.")
    frames = selection.get("frames")
    if not isinstance(frames, list) or not frames:
        raise RuntimeError("The T1 selection receipt has no frames.")
    start, selected = choose_contiguous_frames(frames, frame_count)

    output_root.mkdir(parents=True)
    images = output_root / "input" / "images"
    images.mkdir(parents=True)
    prepared_frames: list[dict[str, Any]] = []
    transfer_methods: set[str] = set()
    selection_root = selection_receipt.parent
    for output_index, item in enumerate(selected):
        source = selection_root / "images" / str(item["image"])
        if not source.is_file():
            raise RuntimeError(f"Selected source frame is missing: {source}")
        target = images / f"{output_index:06d}.png"
        transfer = link_or_copy(source, target)
        transfer_methods.add(transfer)
        prepared_frames.append(
            {
                "preflightIndex": output_index,
                "selectionIndex": start + output_index,
                "sourceFrameIndex": int(item["sourceFrameIndex"]),
                "timestampSeconds": float(item["timestampSeconds"]),
                "regionalFocus": float(item["regionalFocus"]),
                "overlap": float(item["overlap"]),
                "path": str(target),
            }
        )

    config = yaml.safe_load(base_config.read_text(encoding="utf-8")) or {}
    config.setdefault("model", {})
    config.setdefault("data", {})
    config.setdefault("inference", {})
    config.setdefault("output", {})
    checkpoint = (
        checkpoint.resolve()
        if checkpoint is not None
        else horizonstream_root / "checkpoints" / "HorizonStream.pt"
    )
    if checkpoint.is_file() and checkpoint.stat().st_size > MAX_MODEL_BYTES:
        raise RuntimeError("The HorizonStream checkpoint exceeds Servo's 10 GiB limit.")
    config["model"]["checkpoint"] = str(checkpoint)
    config["model"].setdefault("hf", {})
    config["model"]["hf"].update(
        {"repo_id": None, "filename": None, "revision": None}
    )
    config["data"].update(
        {
            "format": "image_list",
            "img_path": None,
            "video_path": None,
            "image_paths": [item["path"] for item in prepared_frames],
            "image_scene_name": "yosemite_t1a_120",
            "max_frames": frame_count,
            "size": 518,
            "crop": True,
            "camera_preprocess": False,
        }
    )
    config["inference"].update(
        {
            "sliding_size": 1,
            "offload_outputs_to_cpu": True,
            "enable_offline_motion_averaging": False,
        }
    )
    run_output = output_root / "run"
    config["output"].update(
        {
            "root": str(run_output),
            "save_videos": True,
            "save_points": True,
            "save_depth": True,
            "save_depth_conf": True,
            "save_images": True,
            # The separate sky checkpoint is not part of this first preflight.
            "mask_sky": False,
            "point_mask_sky": False,
        }
    )
    config_path = output_root / "horizonstream-t1a-120.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    commit = git_commit(horizonstream_root)
    command = [
        "<horizonstream-python>",
        str(horizonstream_root / "infer.py"),
        "--config",
        str(config_path),
        "--checkpoint",
        str(checkpoint),
        "--output-root",
        str(run_output),
        "--sliding-size",
        "1",
        "--offload-outputs-to-cpu",
        "--max-frames",
        str(frame_count),
        "--no-loop",
        "--no-loop-auto-download",
    ]
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "prepared" if checkpoint.is_file() else "blocked-missing-checkpoint",
        "nonPublishableDiagnostic": True,
        "selectionReceipt": str(selection_receipt),
        "selectionReceiptSha256": sha256_file(selection_receipt),
        "selectionSourceVideoSha256": selection["input"]["sha256"],
        "frameCount": frame_count,
        "selectionStartIndex": start,
        "selectionEndIndexInclusive": start + frame_count - 1,
        "firstTimestampSeconds": prepared_frames[0]["timestampSeconds"],
        "lastTimestampSeconds": prepared_frames[-1]["timestampSeconds"],
        "transferMethods": sorted(transfer_methods),
        "horizonStream": {
            "root": str(horizonstream_root),
            "commit": commit,
            "sourceLicenseFilePresent": any(
                (horizonstream_root / name).is_file()
                for name in ("LICENSE", "LICENSE.txt", "COPYING")
            ),
            "modelRepository": "NicolasCC/HorizonStream",
            "modelCardDeclaredLicense": "apache-2.0",
            "checkpoint": str(checkpoint),
            "checkpointPresent": checkpoint.is_file(),
            "checkpointBytes": checkpoint.stat().st_size
            if checkpoint.is_file()
            else None,
            "checkpointSha256": sha256_file(checkpoint)
            if checkpoint.is_file()
            else None,
        },
        "configuration": str(config_path),
        "configurationSha256": sha256_file(config_path),
        "command": command,
        "frames": prepared_frames,
    }
    receipt_path = output_root / "preflight-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-receipt", type=Path, required=True)
    parser.add_argument("--horizonstream-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=DEFAULT_FRAME_COUNT)
    parser.add_argument("--checkpoint", type=Path)
    arguments = parser.parse_args()
    receipt = prepare(
        selection_receipt=arguments.selection_receipt,
        horizonstream_root=arguments.horizonstream_root,
        output_root=arguments.output_root,
        frame_count=arguments.frame_count,
        checkpoint=arguments.checkpoint,
    )
    print(json.dumps({key: receipt[key] for key in ("status", "frameCount", "configuration")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
