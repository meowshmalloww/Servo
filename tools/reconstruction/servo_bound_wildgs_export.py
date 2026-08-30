"""Create an export-parity WildGS PLY with bounded finite log scales."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from plyfile import PlyData


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--minimum-log-scale", type=float, default=-12.0)
    parser.add_argument("--maximum-log-scale", type=float, default=0.0)
    args = parser.parse_args()

    for destination in (args.output, args.receipt):
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite {destination}")
    if args.minimum_log_scale >= args.maximum_log_scale:
        raise ValueError("minimum log scale must be below maximum log scale")

    ply = PlyData.read(args.input)
    vertex = ply["vertex"].data
    scale_names = sorted(
        (name for name in vertex.dtype.names or () if name.startswith("scale_")),
        key=lambda value: int(value.rsplit("_", 1)[1]),
    )
    if scale_names != ["scale_0", "scale_1", "scale_2"]:
        raise ValueError(f"expected three Gaussian log-scale fields, got {scale_names}")

    before = np.stack([vertex[name].astype(np.float64) for name in scale_names], axis=1)
    if not np.isfinite(before).all():
        raise ValueError("input PLY contains nonfinite log scales")
    bounded = np.clip(before, args.minimum_log_scale, args.maximum_log_scale)
    changed = np.any(bounded != before, axis=1)
    for index, name in enumerate(scale_names):
        vertex[name] = bounded[:, index].astype(vertex.dtype[name])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    PlyData(ply.elements, text=ply.text, byte_order=ply.byte_order).write(args.output)
    receipt = {
        "schema": "servo.wildgs-bounded-export/v1",
        "sourcePly": str(args.input.resolve()),
        "sourceSha256": sha256(args.input),
        "outputPly": str(args.output.resolve()),
        "outputSha256": sha256(args.output),
        "gaussianCount": int(len(vertex)),
        "minimumLogScale": args.minimum_log_scale,
        "maximumLogScale": args.maximum_log_scale,
        "changedGaussianCount": int(changed.sum()),
        "sourceMaximumLogScale": float(before.max()),
        "outputMaximumLogScale": float(bounded.max()),
        "generatedEvidence": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
