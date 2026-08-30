#!/usr/bin/env python3
"""Convert equirectangular evidence frames into a calibrated cubemap rig.

The source panorama remains the evidence master.  Six perspective images are
derived for reconstruction because treating a 2:1 panorama as a pinhole image
creates invalid rays, seams, and pole geometry.  This tool does not estimate
motion, depth, metric scale, or fill unobserved pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np


SCHEMA = "servo.equirectangular-cubemap-evidence/v1"
METHOD = "six-pinhole-shared-center-90-degree-v1"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

# Columns are the face camera's right, down, and forward axes expressed in
# the equirectangular camera frame (OpenCV convention: +X right, +Y down,
# +Z forward).  All six cameras share exactly one optical center.
FACE_CAMERA_TO_EQUIRECT = {
    "front": np.array(((1, 0, 0), (0, 1, 0), (0, 0, 1)), dtype=np.float64),
    "right": np.array(((0, 0, 1), (0, 1, 0), (-1, 0, 0)), dtype=np.float64),
    "back": np.array(((-1, 0, 0), (0, 1, 0), (0, 0, -1)), dtype=np.float64),
    "left": np.array(((0, 0, -1), (0, 1, 0), (1, 0, 0)), dtype=np.float64),
    "up": np.array(((1, 0, 0), (0, 0, -1), (0, 1, 0)), dtype=np.float64),
    "down": np.array(((1, 0, 0), (0, 0, 1), (0, -1, 0)), dtype=np.float64),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def face_directions(face: str, resolution: int) -> np.ndarray:
    """Return normalized equirectangular-frame rays for a cubemap face."""
    if face not in FACE_CAMERA_TO_EQUIRECT:
        raise ValueError(f"Unknown cubemap face: {face}")
    if resolution < 2:
        raise ValueError("Cubemap face resolution must be at least 2 pixels.")
    coordinates = (2.0 * (np.arange(resolution, dtype=np.float64) + 0.5) /
                   float(resolution)) - 1.0
    x, y = np.meshgrid(coordinates, coordinates)
    local = np.stack((x, y, np.ones_like(x)), axis=-1)
    directions = local @ FACE_CAMERA_TO_EQUIRECT[face].T
    directions /= np.linalg.norm(directions, axis=-1, keepdims=True)
    return directions


def equirectangular_remap(
    face: str, resolution: int, source_width: int, source_height: int
) -> tuple[np.ndarray, np.ndarray]:
    directions = face_directions(face, resolution)
    longitude = np.arctan2(directions[..., 0], directions[..., 2])
    latitude = np.arcsin(np.clip(directions[..., 1], -1.0, 1.0))
    map_x = ((longitude / (2.0 * math.pi) + 0.5) * source_width - 0.5)
    map_x = np.mod(map_x, source_width).astype(np.float32)
    map_y = ((latitude / math.pi + 0.5) * source_height - 0.5)
    map_y = np.clip(map_y, 0.0, source_height - 1.0).astype(np.float32)
    return map_x, map_y


def convert_frame(image: np.ndarray, resolution: int) -> dict[str, np.ndarray]:
    height, width = image.shape[:2]
    if width < 2 or height < 2:
        raise ValueError("Source panorama is too small.")
    aspect = width / float(height)
    if not 1.85 <= aspect <= 2.15:
        raise ValueError(
            f"Expected a 2:1 equirectangular panorama, got aspect {aspect:.3f}."
        )
    converted: dict[str, np.ndarray] = {}
    for face in FACE_CAMERA_TO_EQUIRECT:
        map_x, map_y = equirectangular_remap(face, resolution, width, height)
        converted[face] = cv2.remap(
            image,
            map_x,
            map_y,
            interpolation=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_WRAP,
        )
    return converted


def source_images(source: Path) -> list[Path]:
    if source.is_file():
        candidates = [source]
    elif source.is_dir():
        candidates = sorted(
            path for path in source.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    else:
        raise ValueError(f"Source does not exist: {source}")
    if not candidates:
        raise ValueError("No supported panorama images were found.")
    return candidates


def prepare(source: Path, output: Path, face_resolution: int | None) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Refusing to overwrite nonempty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    images = source_images(source)
    records: list[dict[str, Any]] = []
    resolved_resolution = face_resolution
    source_shape: tuple[int, int] | None = None
    for index, path in enumerate(images):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"OpenCV could not decode {path}")
        height, width = image.shape[:2]
        if source_shape is None:
            source_shape = (width, height)
            resolved_resolution = resolved_resolution or max(2, width // 4)
        elif source_shape != (width, height):
            raise ValueError("All panoramas in one capture must have identical dimensions.")
        assert resolved_resolution is not None
        faces = convert_frame(image, resolved_resolution)
        frame_record: dict[str, Any] = {
            "index": index,
            "source": str(path.resolve()),
            "sourceSha256": sha256_file(path),
            "faces": {},
        }
        for face, converted in faces.items():
            face_dir = output / "images" / face
            face_dir.mkdir(parents=True, exist_ok=True)
            destination = face_dir / f"frame_{index:06d}.png"
            if not cv2.imwrite(str(destination), converted, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                raise RuntimeError(f"Could not write {destination}")
            frame_record["faces"][face] = {
                "path": str(destination.resolve()),
                "sha256": sha256_file(destination),
            }
        records.append(frame_record)
    assert source_shape is not None and resolved_resolution is not None
    focal = resolved_resolution / 2.0
    cameras = {
        face: {
            "model": "PINHOLE",
            "width": resolved_resolution,
            "height": resolved_resolution,
            "fx": focal,
            "fy": focal,
            "cx": focal,
            "cy": focal,
            "cameraToEquirectangular": matrix.tolist(),
            "translation": [0.0, 0.0, 0.0],
        }
        for face, matrix in FACE_CAMERA_TO_EQUIRECT.items()
    }
    receipt = {
        "schema": SCHEMA,
        "method": METHOD,
        "sourceProjection": "equirectangular-360",
        "derivedProjection": "six-calibrated-pinhole-faces",
        "sourceIsEvidenceMaster": True,
        "generatedPixels": False,
        "metricScale": False,
        "sharedOpticalCenter": True,
        "sourceDimensions": {"width": source_shape[0], "height": source_shape[1]},
        "faceResolution": resolved_resolution,
        "fieldOfViewDegrees": 90.0,
        "cameras": cameras,
        "frames": records,
        "limitations": [
            "This conversion adds no observations and fills no missing pixels.",
            "Camera motion, depth, exposure consistency, and seams require downstream audits.",
            "The output is not metric and is not collision evidence.",
        ],
    }
    atomic_json(output / "receipt.json", receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--face-resolution", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = prepare(args.source.resolve(), args.output.resolve(), args.face_resolution)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps({
        "receipt": str((args.output.resolve() / "receipt.json")),
        "frames": len(receipt["frames"]),
        "facesPerFrame": 6,
        "faceResolution": receipt["faceResolution"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
