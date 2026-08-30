"""Write a fail-closed receipt for an official ClimateNeRF qualification run."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from PIL import Image


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--train-log", required=True, type=Path)
    parser.add_argument("--frames", required=True, type=Path)
    parser.add_argument("--dataset-manifest", required=True, type=Path)
    parser.add_argument("--container-qualification", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    log = args.train_log.read_text(encoding="utf-8", errors="replace")
    psnr_matches = re.findall(r"test/mean_PSNR:\s*([0-9.]+)", log)
    ssim_matches = re.findall(r"test/mean_SSIM:\s*([0-9.]+)", log)
    if not psnr_matches or not ssim_matches:
        raise RuntimeError("training log has no held-out PSNR/SSIM")
    psnr, ssim = float(psnr_matches[-1]), float(ssim_matches[-1])

    rgb = sorted(args.frames.glob("*-rgb.png"))
    depth = sorted(args.frames.glob("*-depth.png"))
    if len(rgb) != 47 or len(depth) != 47:
        raise RuntimeError(f"expected 47 RGB/depth pairs, got {len(rgb)}/{len(depth)}")
    with Image.open(rgb[0]) as image:
        width, height = image.size

    files = {
        path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in rgb + depth
    }
    accepted = psnr >= 20.0 and ssim >= 0.70
    receipt = {
        "schema_name": "servo.climatenerf-qualification/v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "effect": "smog",
        "engine": "official-climatenerf-reference",
        "training_scope": {
            "optimizer_steps": 1,
            "held_out_views": 47,
            "label": "runtime qualification only",
        },
        "validation": {
            "psnr_db": psnr,
            "ssim": ssim,
            "minimum_psnr_db": 20.0,
            "minimum_ssim": 0.70,
            "quality_accepted": accepted,
        },
        "checkpoint": {
            "path": str(args.checkpoint.resolve()),
            "sha256": _sha256(args.checkpoint),
            "bytes": args.checkpoint.stat().st_size,
        },
        "inputs": {
            "dataset_manifest": str(args.dataset_manifest.resolve()),
            "dataset_manifest_sha256": _sha256(args.dataset_manifest),
            "container_qualification": str(args.container_qualification.resolve()),
            "container_qualification_sha256": _sha256(args.container_qualification),
        },
        "outputs": {
            "frame_directory": str(args.frames.resolve()),
            "width": width,
            "height": height,
            "rgb_frames": len(rgb),
            "depth_frames": len(depth),
            "files": files,
        },
        "decision": "quality-accepted" if accepted else "quality-rejected",
        "limitations": [
            "One optimizer step is sufficient only to prove code execution.",
            "The rendered output is not eligible for Servo UI or driving evidence unless quality_accepted is true.",
            "ClimateNeRF does not implement rain.",
            "Flood requires a scene-qualified plane; snow requires its trained effect components.",
            "T5 scale remains relative and cannot support metric flood depth.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "decision": receipt["decision"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
