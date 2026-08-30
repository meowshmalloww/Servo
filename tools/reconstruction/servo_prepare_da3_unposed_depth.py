#!/usr/bin/env python3
"""Precompute temporally scale-aligned DA3 relative depth without COLMAP poses.

Each overlapping window lets DA3 estimate its own calibration.  Consecutive
windows are aligned by a robust median depth ratio over their shared images.
Only depth/confidence evidence is exported; DA3 point or Gaussian predictions
are never used as Servo's presentation world.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

from tools.reconstruction.servo_prepare_da3_depth_sequence import (
    atomic_json,
    discover_images,
    fuse_predictions,
    sha256_file,
    window_starts,
)


SCHEMA = "servo.da3-unposed-depth-sequence/v1"


def robust_overlap_scale(
    existing: list[list[np.ndarray]],
    start: int,
    current: np.ndarray,
) -> float:
    log_ratios: list[np.ndarray] = []
    for local, frame_index in enumerate(range(start, start + len(current))):
        if frame_index >= len(existing) or not existing[frame_index]:
            continue
        reference = np.nanmedian(np.stack(existing[frame_index]), axis=0)
        candidate = np.asarray(current[local])
        valid = (
            np.isfinite(reference)
            & (reference > 1e-6)
            & np.isfinite(candidate)
            & (candidate > 1e-6)
        )
        sampled = valid[::16, ::16]
        if not np.any(sampled):
            continue
        ratio = reference[::16, ::16][sampled] / candidate[::16, ::16][sampled]
        ratio = ratio[np.isfinite(ratio) & (ratio > 0.05) & (ratio < 20.0)]
        if ratio.size:
            log_ratios.append(np.log(ratio))
    if not log_ratios:
        return 1.0
    scale = float(np.exp(np.median(np.concatenate(log_ratios))))
    if not np.isfinite(scale) or scale <= 0.0:
        raise RuntimeError("DA3 overlap produced a nonfinite depth scale.")
    return scale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--da3-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--process-res", type=int, default=504)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--overlap", type=int, default=4)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite output: {output}")
    images = discover_images(args.frames.resolve())
    starts = window_starts(len(images), args.window, args.overlap)
    source_root = args.da3_root.resolve()
    model_root = args.model.resolve()
    if not (source_root / "src" / "depth_anything_3").is_dir():
        raise FileNotFoundError(f"DA3 source is incomplete: {source_root}")
    if not model_root.is_dir():
        raise FileNotFoundError(f"DA3 model is incomplete: {model_root}")

    (output / "depth" / "dpt").mkdir(parents=True)
    (output / "depth" / "conf").mkdir(parents=True)
    (output / "depth" / "spread").mkdir(parents=True)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "frames": str(args.frames.resolve()),
            "frameCount": len(images),
            "selectionReceiptSha256": (
                sha256_file(args.frames.resolve().parent / "selection-receipt.json")
                if (args.frames.resolve().parent / "selection-receipt.json").is_file()
                else None
            ),
        },
        "model": {
            "repository": "https://github.com/ByteDance-Seed/Depth-Anything-3",
            "modelId": "depth-anything/DA3-GIANT-1.1",
            "license": "CC-BY-NC-4.0",
            "distributionAllowed": False,
        },
        "settings": {
            "processResolution": args.process_res,
            "window": args.window,
            "overlap": args.overlap,
            "poseConditioning": "none-da3-window-estimated",
            "crossWindowScale": "robust-overlap-median-ratio/v1",
        },
        "completedWindows": [],
        "claims": {
            "usesColmap": False,
            "pointCloudIsPresentationWorld": False,
            "metricScaleValidated": False,
            "collisionValidated": False,
            "publishable": False,
        },
    }
    atomic_json(output / "da3-unposed-depth-receipt.json", receipt)

    sys.path.insert(0, str(source_root / "src"))
    import torch
    from depth_anything_3.api import DepthAnything3

    if not torch.cuda.is_available():
        raise RuntimeError("DA3 depth inference requires CUDA.")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = DepthAnything3.from_pretrained(str(model_root)).to("cuda").eval()
    loaded = time.perf_counter()
    depth_candidates: list[list[np.ndarray]] = [[] for _ in images]
    confidence_candidates: list[list[np.ndarray]] = [[] for _ in images]
    for ordinal, start in enumerate(starts):
        end = min(start + args.window, len(images))
        prediction = model.inference(
            [str(path) for path in images[start:end]],
            infer_gs=False,
            use_ray_pose=False,
            ref_view_strategy="saddle_balanced",
            process_res=args.process_res,
            process_res_method="upper_bound_resize",
        )
        depth_window = np.asarray(prediction.depth, dtype=np.float32)
        confidence_window = np.asarray(prediction.conf, dtype=np.float32)
        scale = robust_overlap_scale(depth_candidates, start, depth_window)
        depth_window *= scale
        for local, frame_index in enumerate(range(start, end)):
            depth_candidates[frame_index].append(depth_window[local])
            confidence_candidates[frame_index].append(confidence_window[local])
        receipt["completedWindows"].append(
            {
                "ordinal": ordinal,
                "start": start,
                "endExclusive": end,
                "overlapScale": scale,
                "elapsedSeconds": time.perf_counter() - started,
            }
        )
        atomic_json(output / "da3-unposed-depth-receipt.json", receipt)

    spread_medians: list[float] = []
    spread_p95s: list[float] = []
    for index, (depths, confidences) in enumerate(
        zip(depth_candidates, confidence_candidates, strict=True)
    ):
        depth, confidence, spread = fuse_predictions(depths, confidences)
        np.save(output / "depth" / "dpt" / f"frame_{index:06d}.npy", depth)
        np.save(output / "depth" / "conf" / f"frame_{index:06d}.npy", confidence)
        np.save(output / "depth" / "spread" / f"frame_{index:06d}.npy", spread)
        finite = spread[np.isfinite(spread)]
        spread_medians.append(float(np.median(finite)))
        spread_p95s.append(float(np.percentile(finite, 95)))

    receipt["status"] = "completed"
    receipt["completedAt"] = datetime.now(timezone.utc).isoformat()
    receipt["crossWindowRelativeDepthSpread"] = {
        "frameMedianP50": float(np.median(spread_medians)),
        "frameP95Maximum": float(np.max(spread_p95s)),
    }
    receipt["cuda"] = {
        "peakAllocatedGiB": float(torch.cuda.max_memory_allocated() / 1024**3),
        "peakReservedGiB": float(torch.cuda.max_memory_reserved() / 1024**3),
    }
    receipt["timingSeconds"] = {
        "modelLoad": loaded - started,
        "inferenceAndFusion": time.perf_counter() - loaded,
        "total": time.perf_counter() - started,
    }
    atomic_json(output / "da3-unposed-depth-receipt.json", receipt)
    print(json.dumps({
        "output": str(output),
        "frames": len(images),
        "windows": len(starts),
        "elapsedSeconds": receipt["timingSeconds"]["total"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
