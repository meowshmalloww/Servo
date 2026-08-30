#!/usr/bin/env python3
"""Merge overlapping route tiles into one review PLY without duplicate corridors."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_ply(path: Path) -> tuple[list[bytes], list[str], np.ndarray]:
    with path.open("rb") as stream:
        header: list[bytes] = []
        properties: list[str] = []
        count = None
        while True:
            line = stream.readline()
            if not line:
                raise ValueError(f"PLY header ended unexpectedly: {path}")
            header.append(line)
            decoded = line.decode("ascii").strip()
            if decoded.startswith("element vertex "):
                count = int(decoded.rsplit(" ", 1)[1])
            elif decoded.startswith("property "):
                fields = decoded.split()
                if len(fields) != 3 or fields[1] != "float":
                    raise ValueError("route merger requires float32 scalar properties")
                properties.append(fields[2])
            elif decoded == "end_header":
                break
        payload = stream.read()
    if count is None or len(payload) != count * len(properties) * 4:
        raise ValueError(f"invalid PLY payload: {path}")
    values = np.frombuffer(payload, dtype="<f4").reshape(count, len(properties))
    return header, properties, values


def _ownership_ranges(tiles: list[dict[str, Any]], camera_count: int) -> list[tuple[int, int]]:
    boundaries = [0]
    for left, right in zip(tiles, tiles[1:]):
        boundary = (int(left["cameraEndExclusive"]) + int(right["cameraStart"])) // 2
        boundaries.append(boundary)
    boundaries.append(camera_count)
    return list(zip(boundaries, boundaries[1:]))


def merge(
    route: dict[str, Any],
    camera_document: dict[str, Any],
    ply_bindings: dict[str, Path],
    output: Path,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    tiles = route["tiles"]
    expected_ids = {str(tile["tileId"]) for tile in tiles}
    if set(ply_bindings) != expected_ids:
        raise ValueError("PLY tile IDs do not exactly match the route receipt")
    cameras = camera_document["cameras"]
    centers = np.asarray(
        [np.asarray(camera["cameraToWorldNormalized"], dtype=np.float64)[:3, 3] for camera in cameras]
    )
    ownership = _ownership_ranges(tiles, len(cameras))
    retained: list[np.ndarray] = []
    tile_receipts: list[dict[str, Any]] = []
    common_header = None
    common_properties = None

    for tile, (owner_start, owner_end) in zip(tiles, ownership):
        tile_id = str(tile["tileId"])
        path = ply_bindings[tile_id]
        header, properties, values = _read_ply(path)
        if common_properties is None:
            common_header, common_properties = header, properties
        elif properties != common_properties:
            raise ValueError("tile PLY property layouts differ")
        xyz_indices = [properties.index(name) for name in ("x", "y", "z")]
        mask_parts: list[np.ndarray] = []
        for start in range(0, len(values), 16_384):
            xyz = values[start : start + 16_384, xyz_indices].astype(np.float64)
            distances = np.sum(np.square(xyz[:, None, :] - centers[None, :, :]), axis=2)
            nearest = np.argmin(distances, axis=1)
            mask_parts.append((nearest >= owner_start) & (nearest < owner_end))
        mask = np.concatenate(mask_parts) if mask_parts else np.zeros(0, dtype=bool)
        selected = values[mask].copy()
        retained.append(selected)
        tile_receipts.append({
            "tileId": tile_id,
            "sourcePly": str(path),
            "sourceSha256": f"sha256:{_sha256(path)}",
            "sourceGaussians": len(values),
            "retainedGaussians": len(selected),
            "ownerCameraStart": owner_start,
            "ownerCameraEndExclusive": owner_end,
        })

    assert common_header is not None and common_properties is not None
    merged = np.concatenate(retained, axis=0)
    rewritten_header = []
    for line in common_header:
        decoded = line.decode("ascii")
        if decoded.startswith("element vertex "):
            line = f"element vertex {len(merged)}\n".encode("ascii")
        rewritten_header.append(line)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        stream.writelines(rewritten_header)
        stream.write(merged.astype("<f4", copy=False).tobytes())
    receipt = {
        "schema": "servo.merged-route-gaussians/v1",
        "method": "nearest-global-camera-exclusive-overlap-ownership-v1",
        "fullRouteCovered": bool(route["fullRouteCovered"]),
        "cameraCount": len(cameras),
        "tileCount": len(tiles),
        "gaussianCount": len(merged),
        "output": str(output),
        "outputSha256": f"sha256:{_sha256(output)}",
        "tiles": tile_receipts,
    }
    output.with_suffix(output.suffix + ".merge.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, type=Path)
    parser.add_argument("--cameras", required=True, type=Path)
    parser.add_argument("--ply", required=True, action="append", help="TILE_ID=PLY_PATH")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bindings: dict[str, Path] = {}
    for value in args.ply:
        tile_id, separator, raw_path = value.partition("=")
        if not separator or not tile_id or tile_id in bindings:
            parser.error(f"invalid or duplicate PLY binding: {value}")
        bindings[tile_id] = Path(raw_path).resolve()
    receipt = merge(
        json.loads(args.route.read_text(encoding="utf-8")),
        json.loads(args.cameras.read_text(encoding="utf-8")),
        bindings,
        args.output.resolve(),
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
