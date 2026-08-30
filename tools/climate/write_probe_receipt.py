"""Record auditable intermediate ClimateNeRF renders without accepting product quality."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from PIL import Image


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _render_set(path: Path) -> dict[str, object]:
    rgb = sorted((path / "frames").glob("*-rgb.png"))
    depth = sorted((path / "frames").glob("*-depth.png"))
    if not rgb or len(rgb) != len(depth):
        raise RuntimeError(f"expected matched RGB/depth frames in {path}")
    with Image.open(rgb[0]) as image:
        width, height = image.size
    return {
        "directory": str(path.resolve()),
        "rgb_frames": len(rgb),
        "depth_frames": len(depth),
        "width": width,
        "height": height,
        "rgb_sha256": {item.name: _sha256(item) for item in rgb},
        "depth_sha256": {item.name: _sha256(item) for item in depth},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--clear", required=True, type=Path)
    parser.add_argument("--smog", required=True, type=Path)
    parser.add_argument("--dataset-manifest", required=True, type=Path)
    parser.add_argument("--container-qualification", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--completed-epochs", required=True, type=int)
    args = parser.parse_args()

    receipt = {
        "schema_name": "servo.climatenerf-training-probe/v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine": "official-climatenerf-reference",
        "dataset": "Yosemite T5 COLMAP",
        "training": {
            "completed_epochs": args.completed_epochs,
            "target_epochs": 80,
            "status": "in-progress",
        },
        "checkpoint": {
            "path": str(args.checkpoint.resolve()),
            "bytes": args.checkpoint.stat().st_size,
            "sha256": _sha256(args.checkpoint),
        },
        "inputs": {
            "dataset_manifest": str(args.dataset_manifest.resolve()),
            "dataset_manifest_sha256": _sha256(args.dataset_manifest),
            "container_qualification": str(args.container_qualification.resolve()),
            "container_qualification_sha256": _sha256(args.container_qualification),
        },
        "renders": {
            "clear": _render_set(args.clear),
            "smog": _render_set(args.smog),
        },
        "decision": "visual-probe-passed-quality-gate-pending",
        "limitations": [
            "These renders prove recognizable T5 reconstruction and official smog execution only.",
            "Final held-out metrics and the 80-epoch checkpoint are still required for product activation.",
            "ClimateNeRF calls this atmospheric effect smog and does not implement rain.",
            "Flood and snow are not enabled by this receipt.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "decision": receipt["decision"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
