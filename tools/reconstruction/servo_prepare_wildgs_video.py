#!/usr/bin/env python3
"""Create a dense, sharp, auditable RGB sequence for video-based GS/SLAM.

The selector divides the complete source video into equal temporal bins and
keeps the sharpest normally exposed frame from every bin.  It therefore adds
observations without clustering them around one easy/sharp part of the drive.
The output is lossless PNG plus a receipt that maps every output frame back to
the exact source frame and timestamp.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np


SCHEMA = "servo.wildgs-video-selection/v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def temporal_bins(frame_count: int, requested: int) -> list[tuple[int, int]]:
    if frame_count <= 0 or requested < 2 or requested > frame_count:
        raise ValueError("Frame count must be positive and 2 <= requested <= frame count.")
    edges = np.linspace(0, frame_count, requested + 1, dtype=np.int64)
    return [(int(edges[index]), int(edges[index + 1])) for index in range(requested)]


def _frame_metrics(frame: np.ndarray) -> tuple[float, float, float]:
    height, width = frame.shape[:2]
    scale = min(1.0, 640.0 / max(width, 1))
    if scale < 1.0:
        frame = cv2.resize(
            frame,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F, ksize=3).var())
    luminance = float(np.mean(gray) / 255.0)
    contrast = float(np.std(gray) / 255.0)
    return sharpness, luminance, contrast


def selection_score(sharpness: float, luminance: float, contrast: float) -> float:
    if not all(math.isfinite(value) for value in (sharpness, luminance, contrast)):
        return -math.inf
    exposure_penalty = 0.0
    if luminance < 0.08:
        exposure_penalty += (0.08 - luminance) * 20.0
    if luminance > 0.92:
        exposure_penalty += (luminance - 0.92) * 20.0
    if contrast < 0.035:
        exposure_penalty += (0.035 - contrast) * 20.0
    return math.log1p(max(sharpness, 0.0)) - exposure_penalty


def _open_video(path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open source video: {path}")
    return capture


def prepare(
    source: Path,
    output: Path,
    frame_count: int,
    explicit_indices: list[int] | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite output: {output}")

    capture = _open_video(source)
    total = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    if total <= 0 or fps <= 0.0 or width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Video metadata is incomplete.")

    if explicit_indices is not None:
        capture.release()
        if (len(explicit_indices) < 2 or explicit_indices != sorted(set(explicit_indices))
                or explicit_indices[0] < 0 or explicit_indices[-1] >= total):
            raise ValueError("Explicit frame indices must be sorted, unique, in range, and contain at least two frames.")
        frame_count = len(explicit_indices)
        selected: list[dict[str, Any] | None] = [
            {
                "sourceFrameIndex": index,
                "timestampSeconds": index / fps,
                "selectionSource": "camera-forensics",
            }
            for index in explicit_indices
        ]
    else:
        bins = temporal_bins(total, frame_count)
        selected = [None] * len(bins)
        bin_index = 0
        source_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            while bin_index + 1 < len(bins) and source_index >= bins[bin_index][1]:
                bin_index += 1
            start, end = bins[bin_index]
            if start <= source_index < end:
                sharpness, luminance, contrast = _frame_metrics(frame)
                score = selection_score(sharpness, luminance, contrast)
                current = selected[bin_index]
                if current is None or score > float(current["score"]):
                    selected[bin_index] = {
                        "sourceFrameIndex": source_index,
                        "timestampSeconds": source_index / fps,
                        "sharpness": sharpness,
                        "luminance": luminance,
                        "contrast": contrast,
                        "score": score,
                    }
            source_index += 1
        capture.release()
        if source_index != total:
            total = source_index
        if any(item is None for item in selected):
            raise RuntimeError("At least one temporal bin had no decoded video frame.")

    output.mkdir(parents=True, exist_ok=False)
    rgb_root = output / "rgb"
    rgb_root.mkdir()
    by_source = {
        int(item["sourceFrameIndex"]): ordinal
        for ordinal, item in enumerate(selected)
        if item is not None
    }
    capture = _open_video(source)
    source_index = 0
    written = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        ordinal = by_source.get(source_index)
        if ordinal is not None:
            sharpness, luminance, contrast = _frame_metrics(frame)
            target = rgb_root / f"frame_{ordinal:05d}.png"
            if not cv2.imwrite(str(target), frame, [cv2.IMWRITE_PNG_COMPRESSION, 1]):
                capture.release()
                raise RuntimeError(f"Unable to write selected frame: {target}")
            assert selected[ordinal] is not None
            selected[ordinal]["image"] = f"rgb/{target.name}"
            selected[ordinal]["sharpness"] = sharpness
            selected[ordinal]["luminance"] = luminance
            selected[ordinal]["contrast"] = contrast
            selected[ordinal]["score"] = selection_score(sharpness, luminance, contrast)
            written += 1
        source_index += 1
    capture.release()
    if written != frame_count:
        raise RuntimeError(f"Wrote {written} selected frames, expected {frame_count}.")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(source),
            "sha256": _sha256(source),
            "decodedFrameCount": total,
            "fps": fps,
            "width": width,
            "height": height,
        },
        "selection": {
            "method": (
                "camera-forensics-explicit-indices/v1"
                if explicit_indices is not None
                else "equal-temporal-bin-best-sharp-normal-exposure/v1"
            ),
            "requestedFrameCount": frame_count,
            "selectedFrameCount": written,
            "losslessPng": True,
            "frames": selected,
        },
        "claims": {
            "allSourceFramesUsed": False,
            "completeTemporalCoverage": True,
            "generatedFrames": False,
            "metricGeometry": False,
        },
    }
    (output / "selection-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=360)
    parser.add_argument("--indices-file", type=Path)
    args = parser.parse_args()
    explicit_indices = None
    if args.indices_file is not None:
        try:
            explicit_indices = [
                int(line.strip())
                for line in args.indices_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError) as error:
            print(f"error: invalid indices file: {error}", file=sys.stderr)
            return 1
    try:
        receipt = prepare(args.source, args.output, args.frames, explicit_indices)
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "output": str(args.output.resolve()),
        "selectedFrames": receipt["selection"]["selectedFrameCount"],
        "sourceFrames": receipt["source"]["decodedFrameCount"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
