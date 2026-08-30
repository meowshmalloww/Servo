#!/usr/bin/env python3
"""Audit a source video before an expensive camera solve.

The report is diagnostic: row-dependent optical-flow residuals can indicate
rolling shutter or stabilization distortion, but are not a calibrated sensor
readout-time measurement.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np


SCHEMA = "servo.camera-forensics/v1"


def _resize_gray(frame: np.ndarray, maximum_width: int) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if gray.shape[1] <= maximum_width:
        return gray
    scale = maximum_width / gray.shape[1]
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _row_motion_residual(previous: np.ndarray, current: np.ndarray) -> dict[str, float | int | bool]:
    points = cv2.goodFeaturesToTrack(
        previous, maxCorners=800, qualityLevel=0.01, minDistance=8, blockSize=7
    )
    empty = {
        "tracks": 0, "medianMotion": 0.0, "residualP95": 0.0,
        "rowSlopePixels": 0.0, "rowR2": 0.0, "suspected": False,
    }
    if points is None or len(points) < 20:
        return empty
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(
        previous, current, points, None,
        winSize=(21, 21), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if tracked is None or status is None:
        return empty
    keep = status.reshape(-1).astype(bool)
    source = points.reshape(-1, 2)[keep]
    target = tracked.reshape(-1, 2)[keep]
    finite = np.all(np.isfinite(source), axis=1) & np.all(np.isfinite(target), axis=1)
    source, target = source[finite], target[finite]
    if len(source) < 20:
        return empty
    affine, inliers = cv2.estimateAffinePartial2D(
        source, target, method=cv2.RANSAC, ransacReprojThreshold=2.0,
        maxIters=2000, confidence=0.995, refineIters=10,
    )
    if affine is None:
        return empty
    predicted = source @ affine[:, :2].T + affine[:, 2]
    residual = target - predicted
    residual_norm = np.linalg.norm(residual, axis=1)
    cutoff = float(np.quantile(residual_norm, 0.90))
    usable = residual_norm <= max(cutoff, 0.25)
    if inliers is not None:
        usable &= inliers.reshape(-1).astype(bool)
    if np.count_nonzero(usable) < 20:
        usable = residual_norm <= max(cutoff, 0.25)
    y = source[usable, 1]
    normalized_row = (y - np.mean(y)) / max(float(previous.shape[0]), 1.0)
    component_slopes: list[float] = []
    component_r2: list[float] = []
    for component in range(2):
        values = residual[usable, component]
        design = np.stack([normalized_row, np.ones_like(normalized_row)], axis=1)
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
        fitted = design @ coefficients
        denominator = float(np.sum((values - np.mean(values)) ** 2))
        r2 = 0.0 if denominator <= 1e-9 else 1.0 - float(np.sum((values - fitted) ** 2)) / denominator
        component_slopes.append(float(coefficients[0]))
        component_r2.append(max(0.0, r2))
    axis = int(np.argmax(np.abs(component_slopes)))
    slope = abs(component_slopes[axis])
    r2 = component_r2[axis]
    p95 = float(np.quantile(residual_norm, 0.95))
    return {
        "tracks": int(len(source)),
        "medianMotion": float(np.median(np.linalg.norm(target - source, axis=1))),
        "residualP95": p95,
        "rowSlopePixels": slope,
        "rowR2": r2,
        "suspected": bool(len(source) >= 60 and slope >= 0.75 and r2 >= 0.25 and p95 >= 1.0),
    }


def _select_indices(records: list[dict[str, float | int | bool]], count: int) -> list[int]:
    if count >= len(records):
        return list(range(len(records)))
    sharpness = np.array([float(record["sharpness"]) for record in records])
    median_sharpness = max(float(np.median(sharpness)), 1e-6)
    boundaries = np.linspace(0, len(records), count + 1, dtype=int)
    selected: list[int] = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        candidates = range(start, max(start + 1, end))
        def score(index: int) -> float:
            record = records[index]
            exposure_penalty = float(record["darkFraction"]) + float(record["brightFraction"])
            rs_penalty = 0.25 if bool(record["rollingShutterSuspected"]) else 0.0
            return math.log1p(float(record["sharpness"]) / median_sharpness) - 3.0 * exposure_penalty - rs_penalty
        selected.append(max(candidates, key=score))
    return selected


def analyze(video: Path, output: Path, *, maximum_width: int, selection_count: int) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    output.mkdir(parents=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"unable to open video: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    records: list[dict[str, float | int | bool]] = []
    previous: np.ndarray | None = None
    index = 0
    while True:
        okay, frame = capture.read()
        if not okay:
            break
        gray = _resize_gray(frame, maximum_width)
        motion = _row_motion_residual(previous, gray) if previous is not None else {
            "tracks": 0, "medianMotion": 0.0, "residualP95": 0.0,
            "rowSlopePixels": 0.0, "rowR2": 0.0, "suspected": False,
        }
        records.append({
            "frameIndex": index,
            "timestampSeconds": index / fps if fps > 0 else 0.0,
            "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F, ksize=3).var()),
            "meanLuma": float(np.mean(gray) / 255.0),
            "darkFraction": float(np.mean(gray <= 5)),
            "brightFraction": float(np.mean(gray >= 250)),
            "trackedFeatures": int(motion["tracks"]),
            "medianMotionPixels": float(motion["medianMotion"]),
            "globalResidualP95Pixels": float(motion["residualP95"]),
            "rowSlopePixels": float(motion["rowSlopePixels"]),
            "rowR2": float(motion["rowR2"]),
            "rollingShutterSuspected": bool(motion["suspected"]),
        })
        previous = gray
        index += 1
        if index == 1 or index % 120 == 0:
            print(json.dumps({"event": "camera_forensics_progress", "frames": index}), flush=True)
    capture.release()
    if not records:
        raise RuntimeError("video contains no decodable frames")
    selected = _select_indices(records, min(selection_count, len(records)))
    suspicious = [int(record["frameIndex"]) for record in records if record["rollingShutterSuspected"]]
    report = {
        "schema": SCHEMA,
        "video": str(video),
        "frameCount": len(records),
        "declaredFrameCount": declared_frames,
        "fps": fps,
        "width": width,
        "height": height,
        "analysisWidth": min(width, maximum_width),
        "selectionCount": len(selected),
        "selectedFrameIndices": selected,
        "rollingShutter": {
            "status": "suspected" if len(suspicious) >= max(20, int(0.08 * len(records))) else "not-established",
            "suspectedFrameCount": len(suspicious),
            "suspectedFraction": len(suspicious) / len(records),
            "frameIndices": suspicious,
            "meaning": "Row-dependent residual-motion diagnostic; not calibrated readout time.",
        },
        "sharpness": {
            "p10": float(np.quantile([record["sharpness"] for record in records], 0.10)),
            "p50": float(np.quantile([record["sharpness"] for record in records], 0.50)),
            "p90": float(np.quantile([record["sharpness"] for record in records], 0.90)),
        },
    }
    (output / "camera-forensics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (output / "frame-forensics.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    (output / "selected-frame-indices.txt").write_text(
        "\n".join(str(index) for index in selected) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum-width", type=int, default=640)
    parser.add_argument("--selection-count", type=int, default=180)
    args = parser.parse_args()
    if args.maximum_width < 160 or args.selection_count < 2:
        parser.error("maximum width must be >=160 and selection count >=2")
    print(json.dumps(analyze(
        args.video.resolve(), args.output.resolve(),
        maximum_width=args.maximum_width, selection_count=args.selection_count,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
