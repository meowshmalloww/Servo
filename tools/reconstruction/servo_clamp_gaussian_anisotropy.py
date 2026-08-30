#!/usr/bin/env python3
"""Create a provenance-bound Gaussian PLY with extreme covariance axes capped.

The operation preserves every Gaussian and changes only log-scale values whose
largest-to-smallest linear scale ratio exceeds the requested limit.  It is an
appearance cleanup diagnostic, never a collision-geometry repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def clamp(source: Path, output: Path, maximum_anisotropy: float) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    if not math.isfinite(maximum_anisotropy) or maximum_anisotropy <= 1.0:
        raise ValueError("maximum anisotropy must be finite and greater than one")

    with source.open("rb") as stream:
        header: list[bytes] = []
        properties: list[str] = []
        vertex_count: int | None = None
        while True:
            line = stream.readline()
            if not line:
                raise ValueError("PLY header ended unexpectedly")
            header.append(line)
            decoded = line.decode("ascii").strip()
            if decoded.startswith("format ") and decoded != "format binary_little_endian 1.0":
                raise ValueError("only binary little-endian PLY is supported")
            if decoded.startswith("element vertex "):
                vertex_count = int(decoded.rsplit(" ", 1)[1])
            elif decoded.startswith("property "):
                fields = decoded.split()
                if len(fields) != 3 or fields[1] != "float":
                    raise ValueError("vertex properties must all be float32 scalars")
                properties.append(fields[2])
            elif decoded == "end_header":
                break
        if vertex_count is None:
            raise ValueError("PLY does not declare vertex count")
        scale_indices = [properties.index(f"scale_{axis}") for axis in range(3)]
        stride = len(properties) * 4
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        modified = 0
        maximum_before = 1.0
        with temporary.open("wb") as target:
            target.writelines(header)
            remaining = vertex_count
            while remaining:
                count = min(remaining, 131_072)
                payload = stream.read(count * stride)
                if len(payload) != count * stride:
                    raise ValueError("PLY vertex payload is truncated")
                values = np.frombuffer(payload, dtype="<f4").reshape(count, len(properties)).copy()
                log_scales = values[:, scale_indices]
                minimum = log_scales.min(axis=1)
                maximum = log_scales.max(axis=1)
                ratio = np.exp(np.minimum(maximum - minimum, 80.0))
                maximum_before = max(maximum_before, float(ratio.max(initial=1.0)))
                mask = ratio > maximum_anisotropy
                if np.any(mask):
                    limit = minimum[mask, None] + math.log(maximum_anisotropy)
                    log_scales[mask] = np.minimum(log_scales[mask], limit)
                    values[:, scale_indices] = log_scales
                    modified += int(mask.sum())
                target.write(values.astype("<f4", copy=False).tobytes())
                remaining -= count
            if stream.read(1):
                raise ValueError("PLY has unexpected trailing payload")
        os.replace(temporary, output)

    receipt = {
        "schema": "servo.gaussian-anisotropy-clamp/v1",
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "sourceSha256": sha256(source),
        "outputSha256": sha256(output),
        "gaussianCount": vertex_count,
        "modifiedGaussians": modified,
        "modifiedFraction": modified / max(1, vertex_count),
        "maximumAnisotropyBefore": maximum_before,
        "maximumAnisotropyAfter": maximum_anisotropy,
        "preservedGaussianCount": True,
        "collisionValidated": False,
    }
    receipt_path = output.with_suffix(output.suffix + ".anisotropy-clamp.json")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-world", type=Path)
    parser.add_argument("--output-world", type=Path)
    parser.add_argument("--maximum-anisotropy", type=float, default=128.0)
    args = parser.parse_args()
    direct = args.source is not None or args.output is not None
    world = args.source_world is not None or args.output_world is not None
    if direct == world or (direct and (args.source is None or args.output is None)) \
            or (world and (args.source_world is None or args.output_world is None)):
        parser.error("provide either --source/--output or --source-world/--output-world")
    if direct:
        result = clamp(args.source.resolve(), args.output.resolve(), args.maximum_anisotropy)
    else:
        source_world = args.source_world.resolve()
        output_world = args.output_world.resolve()
        if output_world.exists():
            raise FileExistsError(f"Refusing to overwrite {output_world}")
        manifest = json.loads((source_world / "world.json").read_text(encoding="utf-8-sig"))
        source_ply = source_world / manifest.get("artifacts", {}).get("ply", "world.ply")
        output_world.mkdir(parents=True)
        result = clamp(source_ply, output_world / "world.ply", args.maximum_anisotropy)
        for name in ("cameras.json", "appearance.json", "environment.json"):
            source_asset = source_world / name
            if source_asset.is_file():
                shutil.copy2(source_asset, output_world / name)
        manifest["worldId"] = str(manifest.get("worldId", "world")) + f"-aniso{args.maximum_anisotropy:g}"
        manifest["name"] = str(manifest.get("name", "World")) + f" — fiberglass cap {args.maximum_anisotropy:g}×"
        manifest["profile"] = str(manifest.get("profile", "")) + "-anisotropy-clamped"
        manifest.setdefault("artifacts", {})["ply"] = "world.ply"
        manifest.setdefault("hashes", {})["world.ply"] = result["outputSha256"]
        cleanup = manifest.setdefault("quality", {}).setdefault("cleanup", {})
        cleanup["anisotropyClamp"] = {
            "schema": result["schema"],
            "maximum": args.maximum_anisotropy,
            "modifiedGaussians": result["modifiedGaussians"],
            "modifiedFraction": result["modifiedFraction"],
            "sourcePlySha256": result["sourceSha256"],
        }
        manifest.setdefault("usage", {})["collisionValidated"] = False
        manifest.setdefault("limitations", []).append(
            "Extreme covariance axes were capped for visual fiberglass review; this is not structural repair."
        )
        temporary_manifest = output_world / "world.json.tmp"
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary_manifest, output_world / "world.json")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
