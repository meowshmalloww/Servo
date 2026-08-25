#!/usr/bin/env python3
"""Audit COLMAP video evidence and select deterministic reconstruction keyframes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import cv2
import numpy as np

from servo_colmap import Reconstruction


SCHEMA = "servo.capture-health/v1"


class CaptureHealthError(RuntimeError):
    pass


def distribution(values: list[float]) -> dict[str, float | int | None]:
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=np.float64)
    if not finite.size:
        return {"count": 0, "minimum": None, "p25": None, "p50": None, "p75": None, "maximum": None}
    return {
        "count": int(finite.size),
        "minimum": float(np.min(finite)),
        "p25": float(np.percentile(finite, 25)),
        "p50": float(np.percentile(finite, 50)),
        "p75": float(np.percentile(finite, 75)),
        "maximum": float(np.max(finite)),
    }


def rotation_degrees(left: np.ndarray, right: np.ndarray) -> float:
    relative = left.T @ right
    cosine = float(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def image_metrics(path: Path) -> tuple[float, float, float]:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise CaptureHealthError(f"Unable to read registered image: {path}")
    scale = min(1.0, 960.0 / max(image.shape))
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(image, cv2.CV_64F).var())
    return sharpness, float(np.mean(image) / 255.0), float(np.std(image) / 255.0)


def track_grid_coverage(points: list[np.ndarray], width: int, height: int) -> float:
    occupied: set[tuple[int, int]] = set()
    for point in points:
        x, y = float(point[0]), float(point[1])
        if 0.0 <= x < width and 0.0 <= y < height:
            occupied.add((min(5, int(6.0 * x / width)), min(3, int(4.0 * y / height))))
    return len(occupied) / 24.0


def select_keyframes(frames: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    if not frames:
        return [], []
    sharp = distribution([float(frame["sharpness"]) for frame in frames])
    steps = distribution([float(frame["translationFromPrevious"]) for frame in frames[1:]])
    sharp_floor = max(1e-6, float(sharp["p25"] or 0.0))
    baseline = max(1e-8, float(steps["p50"] or 0.0))
    exposure_median = float(np.median([float(frame["luminanceMean"]) for frame in frames]))
    selected = [frames[0]["image"]]
    rejected: list[dict[str, Any]] = []
    accumulated_translation = 0.0
    for index, frame in enumerate(frames[1:-1], start=1):
        accumulated_translation += float(frame["translationFromPrevious"])
        reasons: list[str] = []
        if float(frame["sharpness"]) < sharp_floor:
            reasons.append("lower-sharpness-quartile")
        if abs(float(frame["luminanceMean"]) - exposure_median) > 0.18:
            reasons.append("large-luminance-shift")
        if int(frame["sparseTrackCount"]) < 64:
            reasons.append("too-few-sparse-tracks")
        if float(frame["trackGridCoverage"]) < 0.25:
            reasons.append("poor-image-space-track-coverage")
        useful_motion = (
            accumulated_translation >= 1.5 * baseline
            or float(frame["rotationFromPreviousDegrees"]) >= 1.0
        )
        if not useful_motion:
            reasons.append("redundant-low-baseline")
        hard_failure = any(reason != "redundant-low-baseline" for reason in reasons)
        if useful_motion and not hard_failure:
            selected.append(frame["image"])
            accumulated_translation = 0.0
        else:
            rejected.append({"image": frame["image"], "reasons": reasons})
    if len(frames) > 1:
        selected.append(frames[-1]["image"])
    return selected, rejected


def audit(data: Path) -> dict[str, Any]:
    data = data.resolve()
    model_root = data / "sparse"
    image_root = data / "images"
    reconstruction = Reconstruction(model_root)
    images = sorted(reconstruction.images.values(), key=lambda image: image.name)
    if not images:
        raise CaptureHealthError("COLMAP model has no registered images.")
    frames: list[dict[str, Any]] = []
    previous_c2w: np.ndarray | None = None
    previous_tracks: set[int] = set()
    positions: list[np.ndarray] = []
    rotations: list[np.ndarray] = []
    for image in images:
        camera = reconstruction.cameras[image.camera_id]
        path = image_root / image.name
        sharpness, luminance_mean, luminance_std = image_metrics(path)
        c2w = np.linalg.inv(np.vstack([image.cam_from_world().matrix(), [0.0, 0.0, 0.0, 1.0]]))
        tracks = {point.point3D_id for point in image.points2D if point.has_point3D()}
        points = [point.xy for point in image.points2D if point.has_point3D()]
        errors = [
            reconstruction.points3D[point_id].error
            for point_id in tracks
            if point_id in reconstruction.points3D
        ]
        translation = 0.0 if previous_c2w is None else float(np.linalg.norm(c2w[:3, 3] - previous_c2w[:3, 3]))
        rotation = 0.0 if previous_c2w is None else rotation_degrees(previous_c2w[:3, :3], c2w[:3, :3])
        shared = 0 if previous_c2w is None else len(tracks & previous_tracks)
        frames.append(
            {
                "image": image.name.replace("\\", "/"),
                "sharpness": sharpness,
                "luminanceMean": luminance_mean,
                "luminanceStd": luminance_std,
                "translationFromPrevious": translation,
                "rotationFromPreviousDegrees": rotation,
                "sparseTrackCount": len(tracks),
                "sharedTracksWithPrevious": shared,
                "trackGridCoverage": track_grid_coverage(points, camera.width, camera.height),
                "sparsePointReprojectionError": distribution(errors),
            }
        )
        positions.append(c2w[:3, 3])
        rotations.append(c2w[:3, :3])
        previous_c2w = c2w
        previous_tracks = tracks
    position_jerk = [
        float(np.linalg.norm(positions[index + 1] - 3 * positions[index] + 3 * positions[index - 1] - positions[index - 2]))
        for index in range(2, len(positions) - 1)
    ]
    orientation_jerk = [
        abs(rotation_degrees(rotations[index - 1], rotations[index]))
        for index in range(1, len(rotations))
    ]
    selected, rejected = select_keyframes(frames)
    return {
        "schema": SCHEMA,
        "source": {"data": str(data), "registeredFrames": len(frames)},
        "measurements": {
            "sharpness": distribution([float(frame["sharpness"]) for frame in frames]),
            "luminanceMean": distribution([float(frame["luminanceMean"]) for frame in frames]),
            "adjacentTranslation": distribution([float(frame["translationFromPrevious"]) for frame in frames[1:]]),
            "adjacentRotationDegrees": distribution([float(frame["rotationFromPreviousDegrees"]) for frame in frames[1:]]),
            "positionJerk": distribution(position_jerk),
            "orientationStepDegrees": distribution(orientation_jerk),
            "sparseTrackCount": distribution([float(frame["sparseTrackCount"]) for frame in frames]),
            "sharedTracksWithPrevious": distribution([float(frame["sharedTracksWithPrevious"]) for frame in frames[1:]]),
            "trackGridCoverage": distribution([float(frame["trackGridCoverage"]) for frame in frames]),
        },
        "rollingShutter": {
            "status": "not-measured",
            "reason": "A single global COLMAP pose per frame cannot independently identify row-time motion.",
        },
        "semanticFractions": {
            "status": "not-measured-by-this-receipt",
            "reason": "Static-confidence masks are not relabeled as semantic ground truth.",
        },
        "selection": {
            "method": "sharpness-exposure-track-coverage-accumulated-baseline/v1",
            "selectedCount": len(selected),
            "selectedFrames": selected,
            "rejectedCount": len(rejected),
            "rejectedFrames": rejected,
        },
        "frames": frames,
        "meaning": "Capture evidence and a deterministic keyframe recommendation; the source dataset is unchanged.",
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = audit(arguments.data)
        atomic_json(arguments.output, result)
    except (CaptureHealthError, OSError, ValueError) as error:
        print(json.dumps({"event": "capture_health_failed", "error": str(error)}, separators=(",", ":")))
        return 1
    digest = hashlib.sha256(arguments.output.read_bytes()).hexdigest()
    print(json.dumps({"event": "capture_health_complete", "output": str(arguments.output.resolve()), "sha256": "sha256:" + digest, "selectedFrames": result["selection"]["selectedCount"]}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
