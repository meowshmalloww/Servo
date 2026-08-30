#!/usr/bin/env python3
"""Apply a uniform world transform to a standard binary Gaussian PLY."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def transform_ply(source: Path, target: Path, matrix: np.ndarray) -> dict[str, object]:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite output: {target}")
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("transform must be a finite 4x4 matrix")
    linear = matrix[:3, :3]
    scales = np.linalg.norm(linear, axis=0)
    if not np.allclose(scales, scales[0], rtol=1e-6, atol=1e-9):
        raise ValueError("Gaussian PLY transform must use a uniform scale")
    scale = float(scales[0])
    rotation = linear / scale
    if not np.allclose(rotation, np.eye(3), rtol=1e-6, atol=1e-9):
        raise ValueError("this bounded converter currently accepts scale and translation only")
    if scale <= 0.0:
        raise ValueError("scale must be positive")

    with source.open("rb") as stream:
        header_lines: list[bytes] = []
        properties: list[str] = []
        vertex_count = None
        while True:
            line = stream.readline()
            if not line:
                raise ValueError("PLY header ended unexpectedly")
            header_lines.append(line)
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
        payload = stream.read()

    stride = 4 * len(properties)
    expected = vertex_count * stride
    if len(payload) != expected:
        raise ValueError(f"PLY vertex payload is {len(payload)} bytes; expected {expected}")
    values = np.frombuffer(payload, dtype="<f4").reshape(vertex_count, len(properties)).copy()
    indices = {name: properties.index(name) for name in ("x", "y", "z")}
    xyz = values[:, [indices["x"], indices["y"], indices["z"]]].astype(np.float64)
    xyz = xyz @ linear.T + matrix[:3, 3]
    values[:, [indices["x"], indices["y"], indices["z"]]] = xyz.astype(np.float32)
    log_scale_delta = math.log(scale)
    for name in ("scale_0", "scale_1", "scale_2"):
        if name not in properties:
            raise ValueError(f"PLY is missing {name}")
        values[:, properties.index(name)] += log_scale_delta

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        stream.writelines(header_lines)
        stream.write(values.astype("<f4", copy=False).tobytes())
    receipt = {
        "schema": "servo.gaussian-ply-transform/v1",
        "source": str(source),
        "target": str(target),
        "sourceSha256": f"sha256:{_sha256(source)}",
        "targetSha256": f"sha256:{_sha256(target)}",
        "vertexCount": vertex_count,
        "uniformScale": scale,
        "translation": matrix[:3, 3].tolist(),
        "scaleEncoding": "natural-log-linear-scale",
    }
    receipt_path = target.with_suffix(target.suffix + ".transform.json")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cameras", required=True, type=Path)
    args = parser.parse_args()
    camera_document = json.loads(args.cameras.read_text(encoding="utf-8"))
    matrix = camera_document.get("normalization", {}).get("colmapToNormalized")
    if matrix is None:
        parser.error("camera manifest is missing normalization.colmapToNormalized")
    receipt = transform_ply(args.source.resolve(), args.output.resolve(), np.asarray(matrix))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
