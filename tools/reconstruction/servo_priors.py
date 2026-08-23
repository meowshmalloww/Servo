#!/usr/bin/env python3
"""Build auditable depth, semantic, and road-surface priors for Servo.

This process runs after COLMAP undistortion and before Gaussian fitting.  It
uses the Apache-2.0 Video Depth Anything Small checkpoint for temporally
consistent *relative inverse depth* and the MIT OneFormer ADE20K Swin-tiny
checkpoint for broad safety semantics.  Relative depth is robustly aligned to
Servo's sparse SfM frame.  The result is still arbitrary-scale monocular
geometry: it is useful supervision, but it is never labelled LiDAR, metric
depth, or collision safe.

The model source and weights are provisioned separately and hash checked by
the worker.  No network access occurs while a reconstruction job is running.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence


PRIOR_SCHEMA = "servo.geometry-priors/v1"
ROAD_SCHEMA = "servo.road-surface/v1"
SIGN_SCHEMA = "servo.sign-observations/v1"
CERTIFIED_SKY_EVIDENCE_SCHEMA = "servo.certified-sky-evidence/v1"
CERTIFIED_SKY_EVIDENCE_METHOD = (
    "oneformer-rotation-only-temporal-consensus-v1"
)
CERTIFIED_SKY_EVIDENCE_ASSET = "sky-evidence.json"
CERTIFIED_SKY_EVIDENCE_DIRECTORY = "sky-evidence"
CERTIFIED_SKY_EVIDENCE_UNKNOWN = 0
CERTIFIED_SKY_EVIDENCE_SKY = 1
CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY = 2
CERTIFIED_SKY_EVIDENCE_MINIMUM_SUPPORTING_VIEWS = 2
CERTIFIED_SKY_EVIDENCE_NEIGHBOUR_WINDOW = 4
CERTIFIED_SKY_EVIDENCE_EROSION_RADIUS = 2
DEPTH_CHECKPOINT_SHA256 = (
    "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609"
)
ONEFORMER_CHECKPOINT_SHA256 = (
    "909b07dbf4129c2bbb8df4498e35dcd46f305e3ec45329d3ff6d4f0360de27f3"
)
VIDEO_DEPTH_COMMIT = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
VIDEO_DEPTH_SOURCE_MANIFEST_SHA256 = (
    "40d096e92b5000790416ac4cc519af64adc8cb74354490535ce73c56b39dc581"
)
ONEFORMER_SNAPSHOT_REVISION = "05f2812b1eccf9909b3897777450f8d68148cafc"
ONEFORMER_FILE_SHA256 = {
    "config.json": "091cbc7c980128ae63b2a15d882923f326f85926ef163adad00c24bd90228896",
    "preprocessor_config.json": "2c3c403d8414263e732996bb2ffeab80dd5ced0068ab11bfe5adf476ef75823c",
    "pytorch_model.bin": ONEFORMER_CHECKPOINT_SHA256,
    "merges.txt": "9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a",
    "vocab.json": "e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349",
    "tokenizer_config.json": "64dd88e64d791e3be4d38be62d7e77e0a24df9e79205ac740af505aa2e94c367",
    "special_tokens_map.json": "c4864a9376a8401918425bed71fc14fc0e81f9b59ec45c1cf96cccb2df508eac",
}


class PriorError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, canonical_json(value) + b"\n")


def atomic_npz(path: Path, **arrays: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, **arrays)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_png(path: Path, value: Any) -> None:
    """Encode a PNG completely before atomically replacing its destination."""

    import cv2
    import numpy as np

    image = np.asarray(value)
    encoded, payload = cv2.imencode(
        ".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 9]
    )
    if not encoded:
        raise PriorError(f"Unable to encode PNG evidence {path}")
    atomic_bytes(path, payload.tobytes())


def float16_depth_storage(
    value: Any,
    *,
    invalid_value: float,
) -> tuple[Any, int]:
    """Encode a depth field without silently overflowing into infinity."""

    import numpy as np

    source = np.asarray(value, dtype=np.float64)
    limit = float(np.finfo(np.float16).max)
    representable = np.isfinite(source) & (source >= 0.0) & (source <= limit)
    encoded = np.full(source.shape, invalid_value, dtype=np.float32)
    encoded[representable] = source[representable].astype(np.float32)
    outside_range = np.isfinite(source) & ~representable
    return encoded.astype(np.float16), int(np.count_nonzero(outside_range))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def emit(event: str, **fields: Any) -> None:
    print(
        canonical_json(
            {
                "schema": "servo.geometry-prior-event/v1",
                "event": event,
                **fields,
            }
        ).decode("utf-8"),
        flush=True,
    )


def normalized(value: Any, name: str) -> Any:
    import numpy as np

    vector = np.asarray(value, dtype=np.float64)
    length = float(np.linalg.norm(vector))
    if not np.isfinite(vector).all() or not math.isfinite(length) or length <= 1e-9:
        raise PriorError(f"{name} is degenerate")
    return vector / length


def resized_bgr(path: Path, maximum_dimension: int) -> Any:
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise PriorError(f"Unable to read {path}")
    height, width = image.shape[:2]
    scale = min(1.0, maximum_dimension / float(max(height, width)))
    if scale < 1.0:
        image = cv2.resize(
            image,
            (max(2, round(width * scale)), max(2, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return image


def verify_inputs(
    video_depth_root: Path,
    depth_checkpoint: Path,
    oneformer_root: Path,
) -> None:
    if not (video_depth_root / "video_depth_anything" / "video_depth.py").is_file():
        raise PriorError("The pinned Video Depth Anything source tree is missing")
    source_files = sorted((video_depth_root / "video_depth_anything").rglob("*.py"))
    source_files.extend(sorted((video_depth_root / "utils").rglob("*.py")))
    source_manifest = {
        path.relative_to(video_depth_root).as_posix(): sha256_file(path)
        for path in source_files
    }
    source_manifest_hash = hashlib.sha256(canonical_json(source_manifest)).hexdigest()
    if source_manifest_hash != VIDEO_DEPTH_SOURCE_MANIFEST_SHA256:
        raise PriorError("Video Depth Anything source manifest hash mismatch")
    if not depth_checkpoint.is_file() or sha256_file(depth_checkpoint) != DEPTH_CHECKPOINT_SHA256:
        raise PriorError("Video Depth Anything Small checkpoint hash mismatch")
    required = set(ONEFORMER_FILE_SHA256)
    missing = sorted(name for name in required if not (oneformer_root / name).is_file())
    if missing:
        raise PriorError("OneFormer snapshot is incomplete: " + ", ".join(missing))
    mismatched = sorted(
        name
        for name, expected in ONEFORMER_FILE_SHA256.items()
        if sha256_file(oneformer_root / name) != expected
    )
    if mismatched:
        raise PriorError("OneFormer snapshot hash mismatch: " + ", ".join(mismatched))


def load_depth_model(source_root: Path, checkpoint: Path) -> Any:
    import torch

    sys.path.insert(0, str(source_root))
    from video_depth_anything.video_depth import VideoDepthAnything

    model = VideoDepthAnything(
        encoder="vits",
        features=64,
        out_channels=[48, 96, 192, 384],
        metric=False,
    )
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    return model.cuda().eval()


def infer_relative_depths(
    records: list[Any],
    source_root: Path,
    checkpoint: Path,
    maximum_dimension: int,
    input_size: int,
) -> tuple[list[Any], list[str], dict[str, Any]]:
    import cv2
    import numpy as np
    import torch

    model = load_depth_model(source_root, checkpoint)
    groups: list[tuple[str, list[int]]] = []
    by_parent: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        parent = Path(record.name).parent.as_posix()
        if Path(parent).name.startswith("video-"):
            by_parent.setdefault(parent, []).append(index)
        else:
            groups.append((f"image:{record.name}", [index]))
    groups.extend((f"video:{parent}", indices) for parent, indices in sorted(by_parent.items()))
    outputs: list[Any | None] = [None] * len(records)
    group_ids: list[str | None] = [None] * len(records)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    completed = 0
    for group_number, (group_id, indices) in enumerate(groups, start=1):
        frames = np.stack(
            [
                cv2.cvtColor(
                    resized_bgr(records[index].path, maximum_dimension),
                    cv2.COLOR_BGR2RGB,
                )
                for index in indices
            ]
        )
        depths, _ = model.infer_video_depth(
            frames,
            target_fps=10,
            input_size=input_size,
            device="cuda",
            fp32=False,
        )
        if len(depths) != len(indices):
            raise PriorError("Video depth output count does not match registered cameras")
        for index, depth in zip(indices, depths, strict=True):
            value = np.asarray(depth, dtype=np.float32)
            if value.ndim != 2 or not np.isfinite(value).all() or float(value.max()) <= 0.0:
                raise PriorError(f"Video depth output is invalid for {records[index].name}")
            outputs[index] = value
            group_ids[index] = group_id
        completed += len(indices)
        emit(
            "depth_progress",
            completed=completed,
            total=len(records),
            group=group_number,
            groups=len(groups),
        )
        del frames, depths
    elapsed = time.perf_counter() - started
    result = [value for value in outputs if value is not None]
    resolved_group_ids = [value for value in group_ids if value is not None]
    if len(result) != len(records) or len(resolved_group_ids) != len(records):
        raise PriorError("Video depth did not cover every registered camera")
    metrics = {
        "frames": len(records),
        "seconds": elapsed,
        "framesPerSecond": len(records) / max(elapsed, 1e-9),
        "inputSize": input_size,
        "storedMaxDimension": maximum_dimension,
        "peakAllocatedGiB": torch.cuda.max_memory_allocated() / 2**30,
        "peakReservedGiB": torch.cuda.max_memory_reserved() / 2**30,
    }
    del model
    torch.cuda.empty_cache()
    return result, resolved_group_ids, metrics


def smooth_temporal_affine_parameters(
    base_scale: float,
    base_shift: float,
    local_scales: Any,
    local_shifts: Any,
) -> tuple[Any, Any, dict[str, Any]]:
    """Denoise local SfM alignments without permitting frame-wise depth jitter."""

    import numpy as np
    from scipy.ndimage import median_filter
    from scipy.signal import savgol_filter

    scales = np.asarray(local_scales, dtype=np.float64)
    shifts = np.asarray(local_shifts, dtype=np.float64)
    if scales.ndim != 1 or shifts.shape != scales.shape or len(scales) == 0:
        raise PriorError("Temporal affine parameters must be matching vectors")
    valid = (
        np.isfinite(scales)
        & (scales > 0.0)
        & np.isfinite(shifts)
    )
    if not np.any(valid):
        scales = np.full(len(scales), base_scale, dtype=np.float64)
        shifts = np.full(len(shifts), base_shift, dtype=np.float64)
    elif not np.all(valid):
        positions = np.arange(len(scales), dtype=np.float64)
        scales = np.interp(positions, positions[valid], scales[valid])
        shifts = np.interp(positions, positions[valid], shifts[valid])
    median_window = min(9, len(scales) if len(scales) % 2 else len(scales) - 1)
    if median_window >= 3:
        scales = median_filter(scales, size=median_window, mode="nearest")
        shifts = median_filter(shifts, size=median_window, mode="nearest")
    smooth_window = min(15, len(scales) if len(scales) % 2 else len(scales) - 1)
    if smooth_window >= 5:
        scales = savgol_filter(
            scales,
            window_length=smooth_window,
            polyorder=2,
            mode="interp",
        )
        shifts = savgol_filter(
            shifts,
            window_length=smooth_window,
            polyorder=2,
            mode="interp",
        )
    blend = 0.50
    corrected_scales = base_scale + blend * (scales - base_scale)
    corrected_shifts = base_shift + blend * (shifts - base_shift)
    corrected_scales = np.clip(
        corrected_scales,
        max(base_scale * 0.50, 1e-8),
        base_scale * 2.0,
    )
    return corrected_scales, corrected_shifts, {
        "method": "per-frame-robust-affine-median-savgol-half-blend-v1",
        "medianWindowFrames": median_window,
        "smoothWindowFrames": smooth_window,
        "blendWithLocal": blend,
        "baseScale": base_scale,
        "baseShift": base_shift,
        "correctedScaleMinimum": float(np.min(corrected_scales)),
        "correctedScaleMaximum": float(np.max(corrected_scales)),
        "correctedShiftMinimum": float(np.min(corrected_shifts)),
        "correctedShiftMaximum": float(np.max(corrected_shifts)),
    }


def sample_sparse_alignment(
    records: list[Any],
    depths: list[Any],
    group_ids: list[str],
    semantics: list[Any],
) -> tuple[list[Any | None], dict[str, Any]]:
    import numpy as np

    from servo_geometry import (
        DYNAMIC_LABELS,
        GeometryInputError,
        NON_FINITE_LABELS,
        align_relative_depth_to_sfm,
    )

    excluded_ids = np.asarray(
        sorted(int(label) for label in DYNAMIC_LABELS | NON_FINITE_LABELS),
        dtype=np.uint8,
    )

    grouped: dict[str, list[int]] = {}
    for index, group_id in enumerate(group_ids):
        grouped.setdefault(group_id, []).append(index)
    alignments: list[Any | None] = [None] * len(records)
    group_metrics: list[dict[str, Any]] = []
    total_samples = 0
    total_inliers = 0
    aligned_frames = 0
    for group_id, indices in sorted(grouped.items()):
        predictions: list[Any] = []
        targets: list[Any] = []
        frame_samples: dict[int, tuple[Any, Any]] = {}
        counts: list[int] = []
        for index in indices:
            record = records[index]
            relative = depths[index]
            if len(record.sparse_depths) == 0:
                counts.append(0)
                continue
            height, width = relative.shape
            pixels = np.asarray(record.sparse_pixels, dtype=np.float64)
            x = np.rint(
                (pixels[:, 0] + 0.5) * width / record.width - 0.5
            ).astype(np.int64)
            y = np.rint(
                (pixels[:, 1] + 0.5) * height / record.height - 0.5
            ).astype(np.int64)
            x = np.clip(x, 0, width - 1)
            y = np.clip(y, 0, height - 1)
            prediction = relative[y, x].astype(np.float64)
            sparse = np.asarray(record.sparse_depths, dtype=np.float64)
            semantic = np.asarray(semantics[index], dtype=np.uint8)
            semantic_x = np.rint(
                (pixels[:, 0] + 0.5) * semantic.shape[1] / record.width - 0.5
            ).astype(np.int64)
            semantic_y = np.rint(
                (pixels[:, 1] + 0.5) * semantic.shape[0] / record.height - 0.5
            ).astype(np.int64)
            semantic_x = np.clip(semantic_x, 0, semantic.shape[1] - 1)
            semantic_y = np.clip(semantic_y, 0, semantic.shape[0] - 1)
            finite_static = ~np.isin(semantic[semantic_y, semantic_x], excluded_ids)
            valid = (
                np.isfinite(prediction)
                & np.isfinite(sparse)
                & (prediction > 0.0)
                & (sparse > 0.0)
                & finite_static
            )
            frame_prediction = prediction[valid]
            frame_target = sparse[valid]
            # Prevent a highly textured frame from dominating the single
            # sequence transform while retaining enough evidence for a robust
            # local audit.
            if len(frame_prediction) > 2_000:
                selected = np.linspace(0, len(frame_prediction) - 1, 2_000).round().astype(
                    np.int64
                )
                frame_prediction = frame_prediction[selected]
                frame_target = frame_target[selected]
            predictions.append(frame_prediction)
            targets.append(frame_target)
            frame_samples[index] = (frame_prediction, frame_target)
            counts.append(len(frame_prediction))
        sample_count = sum(len(value) for value in predictions)
        if sample_count < 100:
            group_metrics.append(
                {
                    "groupId": group_id,
                    "frames": len(indices),
                    "aligned": False,
                    "sampleCount": sample_count,
                    "reason": "fewer-than-100-sparse-observations",
                }
            )
            continue
        prediction = np.concatenate(predictions)
        target = np.concatenate(targets)
        if len(prediction) > 250_000:
            selected = np.linspace(0, len(prediction) - 1, 250_000).round().astype(
                np.int64
            )
            prediction = prediction[selected]
            target = target[selected]
        alignment = align_relative_depth_to_sfm(
            prediction,
            target,
            representation="inverse-depth",
            min_samples=100,
        )
        inverse_targets = 1.0 / target
        target_span = float(
            np.percentile(inverse_targets, 95) - np.percentile(inverse_targets, 5)
        )
        target_scale = max(
            abs(target_span), float(np.max(np.abs(inverse_targets))) * 1e-9, 1e-9
        )

        local_scales: list[float] = []
        local_shifts: list[float] = []
        local_fit_failures = 0
        for record_index in indices:
            samples = frame_samples.get(record_index)
            if samples is None or len(samples[0]) < 32:
                local_scales.append(math.nan)
                local_shifts.append(math.nan)
                local_fit_failures += 1
                continue
            try:
                local_alignment = align_relative_depth_to_sfm(
                    samples[0],
                    samples[1],
                    representation="inverse-depth",
                    min_samples=32,
                )
            except GeometryInputError:
                local_scales.append(math.nan)
                local_shifts.append(math.nan)
                local_fit_failures += 1
                continue
            local_scales.append(local_alignment.scale)
            local_shifts.append(local_alignment.shift)
        corrected_scales, corrected_shifts, temporal_correction = (
            smooth_temporal_affine_parameters(
                alignment.scale,
                alignment.shift,
                local_scales,
                local_shifts,
            )
        )
        temporal_correction["localFitFailures"] = local_fit_failures
        frame_alignments: dict[int, Any] = {}
        for local_index, record_index in enumerate(indices):
            frame_alignment = dataclasses.replace(
                alignment,
                scale=float(corrected_scales[local_index]),
                shift=float(corrected_shifts[local_index]),
            )
            frame_alignments[record_index] = frame_alignment
            alignments[record_index] = frame_alignment

        def residual_summary(selected_indices: list[int]) -> dict[str, Any]:
            selected_residuals: list[Any] = []
            supported_frames = 0
            for selected_index in selected_indices:
                samples = frame_samples.get(selected_index)
                if samples is None or len(samples[0]) < 32:
                    continue
                frame_alignment = frame_alignments[selected_index]
                selected_residuals.append(
                    frame_alignment.scale * samples[0]
                    + frame_alignment.shift
                    - 1.0 / samples[1]
                )
                supported_frames += 1
            if not selected_residuals:
                return {
                    "supportedFrames": 0,
                    "sampleCount": 0,
                    "normalizedMedianBias": None,
                    "normalizedP95Residual": None,
                }
            residual = np.concatenate(selected_residuals)
            return {
                "supportedFrames": supported_frames,
                "sampleCount": int(len(residual)),
                "normalizedMedianBias": float(np.median(residual) / target_scale),
                "normalizedP95Residual": float(
                    np.percentile(np.abs(residual), 95) / target_scale
                ),
            }

        frame_residuals: list[dict[str, Any]] = []
        for local_index, record_index in enumerate(indices):
            summary = residual_summary([record_index])
            frame_residuals.append(
                {
                    "frameOffset": local_index,
                    "image": records[record_index].name,
                    **summary,
                }
            )
        window_residuals: list[dict[str, Any]] = []
        for start in range(0, len(indices), 22):
            window_indices = indices[start : min(start + 32, len(indices))]
            if not window_indices:
                continue
            summary = residual_summary(window_indices)
            window_residuals.append(
                {
                    "startFrameOffset": start,
                    "endFrameOffset": start + len(window_indices) - 1,
                    "frameCount": len(window_indices),
                    **summary,
                }
            )
        supported_frame_metrics = [
            value for value in frame_residuals if int(value["sampleCount"]) > 0
        ]
        supported_window_metrics = [
            value for value in window_residuals if int(value["supportedFrames"]) > 0
        ]
        from servo_geometry import NAVIGABLE_SURFACE_LABELS

        navigable_ids = np.asarray(
            sorted(int(label) for label in NAVIGABLE_SURFACE_LABELS), dtype=np.uint8
        )
        anchor_prediction = np.concatenate(
            [samples[0] for samples in frame_samples.values() if len(samples[0])]
        )
        anchor_low, anchor_high = np.percentile(anchor_prediction, [1, 99])
        dense_coverage: list[dict[str, Any]] = []
        for local_index, record_index in enumerate(indices):
            relative = np.asarray(depths[record_index], dtype=np.float64)
            frame_alignment = frame_alignments[record_index]
            finite_prediction = np.isfinite(relative) & (relative > 0.0)
            positive_domain = (
                finite_prediction
                & np.isfinite(
                    frame_alignment.scale * relative + frame_alignment.shift
                )
                & (
                    frame_alignment.scale * relative + frame_alignment.shift
                    > 0.0
                )
            )
            semantic = np.asarray(semantics[record_index], dtype=np.uint8)
            navigable = np.isin(semantic, navigable_ids) & finite_prediction
            dense_coverage.append(
                {
                    "frameOffset": local_index,
                    "image": records[record_index].name,
                    "alignedValidFraction": float(
                        np.count_nonzero(positive_domain)
                        / max(np.count_nonzero(finite_prediction), 1)
                    ),
                    "navigableAlignedValidFraction": float(
                        np.count_nonzero(positive_domain & navigable)
                        / max(np.count_nonzero(navigable), 1)
                    ),
                    "anchorRangeExtrapolatedFraction": float(
                        np.count_nonzero(
                            finite_prediction
                            & ((relative < anchor_low) | (relative > anchor_high))
                        )
                        / max(np.count_nonzero(finite_prediction), 1)
                    ),
                }
            )
        aligned_valid_values = [value["alignedValidFraction"] for value in dense_coverage]
        navigable_valid_values = [
            value["navigableAlignedValidFraction"] for value in dense_coverage
        ]
        corrected_residual = np.concatenate(
            [
                frame_alignments[record_index].scale * samples[0]
                + frame_alignments[record_index].shift
                - 1.0 / samples[1]
                for record_index, samples in frame_samples.items()
                if len(samples[0])
            ]
        )
        corrected_normalized_p95 = float(
            np.percentile(np.abs(corrected_residual), 95) / target_scale
        )
        aligned_frames += len(indices)
        total_samples += alignment.sample_count
        total_inliers += alignment.inlier_count
        group_metrics.append(
            {
                "groupId": group_id,
                "frames": len(indices),
                "aligned": True,
                "representation": alignment.representation,
                "scale": alignment.scale,
                "shift": alignment.shift,
                "baseAlignment": {
                    "scale": alignment.scale,
                    "shift": alignment.shift,
                    "normalizedP95Residual": alignment.normalized_p95_residual,
                },
                "temporalCorrection": temporal_correction,
                "sampleCount": alignment.sample_count,
                "inlierCount": alignment.inlier_count,
                "inlierRatio": alignment.inlier_ratio,
                "weightedRmse": alignment.weighted_rmse,
                "medianAbsoluteResidual": alignment.median_absolute_residual,
                "p95AbsoluteResidual": alignment.p95_absolute_residual,
                "normalizedP95Residual": corrected_normalized_p95,
                "conditionNumber": alignment.condition_number,
                "iterations": alignment.iterations,
                "converged": alignment.converged,
                "medianSparseSamplesPerFrame": float(np.median(counts)),
                "frameResiduals": frame_residuals,
                "windowResiduals": window_residuals,
                "denseCoverageFrames": dense_coverage,
                "residualAudit": {
                    "perFrameSampleCap": 2_000,
                    "minimumSamplesPerAuditedFrame": 32,
                    "windowLengthFrames": 32,
                    "windowStrideFrames": 22,
                    "supportedFrameRatio": len(supported_frame_metrics) / len(indices),
                    "supportedWindowRatio": len(supported_window_metrics)
                    / max(len(window_residuals), 1),
                    "frameNormalizedP95P90": float(
                        np.percentile(
                            [value["normalizedP95Residual"] for value in supported_frame_metrics],
                            90,
                        )
                    )
                    if supported_frame_metrics
                    else math.inf,
                    "maximumWindowNormalizedP95Residual": max(
                        (
                            float(value["normalizedP95Residual"])
                            for value in supported_window_metrics
                        ),
                        default=math.inf,
                    ),
                    "maximumWindowAbsoluteNormalizedBias": max(
                        (
                            abs(float(value["normalizedMedianBias"]))
                            for value in supported_window_metrics
                        ),
                        default=math.inf,
                    ),
                    "alignedValidFractionP10": float(
                        np.percentile(aligned_valid_values, 10)
                    ),
                    "navigableAlignedValidFractionP10": float(
                        np.percentile(navigable_valid_values, 10)
                    ),
                    "anchorPredictionP01": float(anchor_low),
                    "anchorPredictionP99": float(anchor_high),
                },
            }
        )
    if aligned_frames == 0:
        raise PriorError("No inference sequence has enough sparse support for depth alignment")
    aligned_groups = [value for value in group_metrics if value["aligned"]]
    metrics = {
        "strategy": "sequence-affine-plus-smooth-temporal-correction-v2",
        "representation": "inverse-depth",
        "groups": group_metrics,
        "groupCount": len(group_metrics),
        "alignedGroupCount": len(aligned_groups),
        "alignedFrameCount": aligned_frames,
        "alignedFrameRatio": aligned_frames / len(records),
        "sampleCount": total_samples,
        "inlierCount": total_inliers,
        "inlierRatio": total_inliers / max(total_samples, 1),
        "allAlignedGroupsConverged": all(value["converged"] for value in aligned_groups),
        "maximumNormalizedP95Residual": max(
            float(value["normalizedP95Residual"]) for value in aligned_groups
        ),
        "minimumSupportedFrameRatio": min(
            float(value["residualAudit"]["supportedFrameRatio"])
            for value in aligned_groups
        ),
        "minimumSupportedWindowRatio": min(
            float(value["residualAudit"]["supportedWindowRatio"])
            for value in aligned_groups
        ),
        "maximumFrameNormalizedP95P90": max(
            float(value["residualAudit"]["frameNormalizedP95P90"])
            for value in aligned_groups
        ),
        "maximumWindowNormalizedP95Residual": max(
            float(value["residualAudit"]["maximumWindowNormalizedP95Residual"])
            for value in aligned_groups
        ),
        "maximumWindowAbsoluteNormalizedBias": max(
            float(value["residualAudit"]["maximumWindowAbsoluteNormalizedBias"])
            for value in aligned_groups
        ),
        "minimumAlignedValidFractionP10": min(
            float(value["residualAudit"]["alignedValidFractionP10"])
            for value in aligned_groups
        ),
        "minimumNavigableAlignedValidFractionP10": min(
            float(value["residualAudit"]["navigableAlignedValidFractionP10"])
            for value in aligned_groups
        ),
    }
    return alignments, metrics


def servo_semantic_id(identifier: int) -> int:
    """Map the pinned ADE20K class IDs without substring ambiguity.

    This table is intentionally tied to the verified OneFormer checkpoint.
    Generic signboards and posters remain OTHER_STATIC; they are only broad
    candidates, never asserted to be regulatory traffic signs.
    """

    from servo_geometry import SemanticLabel

    mapping = {
        0: SemanticLabel.WALL,
        1: SemanticLabel.BUILDING,
        2: SemanticLabel.SKY,
        3: SemanticLabel.FLOOR,
        4: SemanticLabel.VEGETATION,
        6: SemanticLabel.ROAD,
        9: SemanticLabel.VEGETATION,
        11: SemanticLabel.SIDEWALK,
        12: SemanticLabel.PERSON,
        13: SemanticLabel.TERRAIN,
        16: SemanticLabel.TERRAIN,
        17: SemanticLabel.VEGETATION,
        20: SemanticLabel.VEHICLE,
        21: SemanticLabel.WATER,
        25: SemanticLabel.BUILDING,
        26: SemanticLabel.WATER,
        29: SemanticLabel.TERRAIN,
        32: SemanticLabel.FENCE,
        34: SemanticLabel.TERRAIN,
        38: SemanticLabel.GUARD_RAIL,
        42: SemanticLabel.POLE,
        46: SemanticLabel.TERRAIN,
        48: SemanticLabel.BUILDING,
        52: SemanticLabel.SIDEWALK,
        54: SemanticLabel.ROAD,
        60: SemanticLabel.WATER,
        66: SemanticLabel.VEGETATION,
        68: SemanticLabel.TERRAIN,
        72: SemanticLabel.VEGETATION,
        76: SemanticLabel.VEHICLE,
        80: SemanticLabel.VEHICLE,
        83: SemanticLabel.VEHICLE,
        87: SemanticLabel.POLE,
        90: SemanticLabel.VEHICLE,
        91: SemanticLabel.ROAD,
        93: SemanticLabel.POLE,
        94: SemanticLabel.TERRAIN,
        95: SemanticLabel.GUARD_RAIL,
        100: SemanticLabel.OTHER_STATIC,
        102: SemanticLabel.VEHICLE,
        103: SemanticLabel.VEHICLE,
        104: SemanticLabel.WATER,
        113: SemanticLabel.WATER,
        116: SemanticLabel.MOTORCYCLE,
        126: SemanticLabel.UNKNOWN,
        127: SemanticLabel.BICYCLE,
        128: SemanticLabel.WATER,
        136: SemanticLabel.TRAFFIC_LIGHT,
    }
    return int(mapping.get(int(identifier), SemanticLabel.OTHER_STATIC))


def exact_connected_component_crop(
    component_labels: Any,
    statistics: Any,
    component: int,
) -> tuple[int, int, int, int, int, Any]:
    """Extract one component without admitting neighbours in its bounding box."""

    import cv2
    import numpy as np

    labels = np.asarray(component_labels)
    stats = np.asarray(statistics)
    if labels.ndim != 2 or stats.ndim != 2 or stats.shape[1] < 5:
        raise PriorError("Connected-component evidence arrays are malformed")
    if component <= 0 or component >= len(stats):
        raise PriorError("Connected-component identifier is outside its statistics")
    x = int(stats[component, cv2.CC_STAT_LEFT])
    y = int(stats[component, cv2.CC_STAT_TOP])
    width = int(stats[component, cv2.CC_STAT_WIDTH])
    height = int(stats[component, cv2.CC_STAT_HEIGHT])
    area = int(stats[component, cv2.CC_STAT_AREA])
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > labels.shape[1]
        or y + height > labels.shape[0]
        or area <= 0
    ):
        raise PriorError("Connected-component statistics are outside the label raster")
    component_mask = (
        labels[y : y + height, x : x + width] == component
    ).astype(np.uint8)
    if int(np.count_nonzero(component_mask)) != area:
        raise PriorError("Exact connected-component mask disagrees with OpenCV area")
    return x, y, width, height, area, component_mask


def infer_semantics(
    records: list[Any],
    model_root: Path,
    output_root: Path,
    maximum_dimension: int,
) -> tuple[list[Any], dict[str, Any], list[dict[str, Any]]]:
    import cv2
    import numpy as np
    import torch
    import transformers
    from PIL import Image
    from transformers import OneFormerForUniversalSegmentation, OneFormerProcessor

    # Transformers 5 defaults to a torchvision processor whose resize path is
    # not numerically compatible with the official OneFormer golden logits.
    # The pinned checkpoint's PIL backend matches those reference logits.
    processor = OneFormerProcessor.from_pretrained(
        model_root,
        local_files_only=True,
        backend="pil",
    )
    model, loading_info = OneFormerForUniversalSegmentation.from_pretrained(
        model_root,
        local_files_only=True,
        output_loading_info=True,
    )
    model = model.cuda().eval()
    allowed_missing = {
        "model.pixel_level_module.encoder.swin.layernorm.weight",
        "model.pixel_level_module.encoder.swin.layernorm.bias",
    }
    missing = set(loading_info.get("missing_keys", ()))
    unexpected = set(loading_info.get("unexpected_keys", ()))
    expected_unexpected = {
        "model.pixel_level_module.encoder.swin.encoder.layers."
        f"{layer}.blocks.{block}.attention.self.relative_position_index"
        for layer, block_count in enumerate((2, 2, 6, 2))
        for block in range(block_count)
    }
    if (
        missing != allowed_missing
        or unexpected != expected_unexpected
        or loading_info.get("mismatched_keys")
        or loading_info.get("error_msgs")
    ):
        raise PriorError(
            "OneFormer checkpoint compatibility keys differ from the pinned contract"
        )
    # The converted HF checkpoint predates the backbone's final LayerNorm keys.
    # Transformers initializes the added normalization to identity.  Assert it
    # remains identity instead of silently accepting version-dependent weights.
    layernorm = model.model.pixel_level_module.encoder.swin.layernorm
    if not bool(torch.equal(layernorm.weight.detach().cpu(), torch.ones_like(layernorm.weight.detach().cpu()))):
        raise PriorError("OneFormer compatibility LayerNorm is not identity")
    if not bool(torch.equal(layernorm.bias.detach().cpu(), torch.zeros_like(layernorm.bias.detach().cpu()))):
        raise PriorError("OneFormer compatibility LayerNorm bias is not zero")
    id_map = {
        int(identifier): servo_semantic_id(int(identifier))
        for identifier in model.config.id2label
    }
    lookup = np.full(256, 0, dtype=np.uint8)
    for identifier, servo_id in id_map.items():
        if 0 <= identifier < len(lookup):
            lookup[identifier] = servo_id
    results: list[Any] = []
    sign_observations: list[dict[str, Any]] = []
    class_counts: dict[int, int] = {}
    sky_rgb_sum = np.zeros(3, dtype=np.float64)
    sky_rgb_count = 0
    started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    for index, record in enumerate(records):
        bgr = resized_bgr(record.path, maximum_dimension)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        inputs = processor(images=image, task_inputs=["semantic"], return_tensors="pt")
        inputs = {
            key: value.cuda(non_blocking=True) if hasattr(value, "cuda") else value
            for key, value in inputs.items()
        }
        with torch.inference_mode():
            output = model(**inputs)
        labels = processor.post_process_semantic_segmentation(
            output,
            target_sizes=[rgb.shape[:2]],
        )[0].to(dtype=torch.int64).cpu().numpy()
        if labels.min(initial=0) < 0 or labels.max(initial=0) >= len(lookup):
            raise PriorError(f"OneFormer returned an unsupported label for {record.name}")
        semantic = lookup[labels]
        results.append(semantic)
        sky = semantic == 17
        if np.any(sky):
            sky_rgb_sum += rgb[sky].astype(np.float64).sum(axis=0)
            sky_rgb_count += int(np.count_nonzero(sky))
        unique, counts = np.unique(semantic, return_counts=True)
        for label_id, count in zip(unique.tolist(), counts.tolist(), strict=True):
            class_counts[int(label_id)] = class_counts.get(int(label_id), 0) + int(count)
        # ADE20K class 43 is a broad signboard/sign region.  It does not prove
        # traffic-sign identity; preserve it only as a candidate observation.
        sign_mask = (labels == 43).astype(np.uint8)
        component_count, component_labels, statistics, _ = cv2.connectedComponentsWithStats(
            sign_mask, connectivity=8
        )
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        for component in range(1, component_count):
            x, y, width, height, area, component_mask = exact_connected_component_crop(
                component_labels,
                statistics,
                component,
            )
            if area < 16 or width < 3 or height < 3:
                continue
            mask_digest = hashlib.sha256()
            mask_digest.update(
                canonical_json(
                    {
                        "dtype": str(component_mask.dtype),
                        "shape": list(component_mask.shape),
                    }
                )
            )
            mask_digest.update(component_mask.tobytes())
            crop = gray[y : y + height, x : x + width]
            focus = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
            sign_observations.append(
                {
                    "candidateId": f"sign-proposal-{index:06d}-{component:04d}",
                    "image": record.name,
                    "frameIndex": index,
                    "boxPriorPixels": [x, y, width, height],
                    "priorSize": [semantic.shape[1], semantic.shape[0]],
                    "areaPixels": area,
                    "focus": focus,
                    "classification": "broad-signboard-candidate",
                    "sourceSemanticClass": {
                        "taxonomy": "ADE20K",
                        "id": 43,
                        "meaning": "signboard-broad-proposal-not-regulatory-identity",
                    },
                    "proposalMaskSha256": "sha256:" + mask_digest.hexdigest(),
                    "regulatoryTextVerified": False,
                    # Internal exact proposal support.  It is never serialized
                    # into JSON directly; integrate_sign_evidence writes a
                    # lossless mask artifact and preserves the digest above.
                    "_candidateMask": component_mask,
                }
            )
        output_path = output_root / "semantics" / Path(record.name).with_suffix(".png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output_path), semantic, [cv2.IMWRITE_PNG_COMPRESSION, 9]):
            raise PriorError(f"Unable to write semantic evidence {output_path}")
        emit("semantic_progress", completed=index + 1, total=len(records))
    elapsed = time.perf_counter() - started
    metrics = {
        "frames": len(records),
        "seconds": elapsed,
        "framesPerSecond": len(records) / max(elapsed, 1e-9),
        "storedMaxDimension": maximum_dimension,
        "peakAllocatedGiB": torch.cuda.max_memory_allocated() / 2**30,
        "peakReservedGiB": torch.cuda.max_memory_reserved() / 2**30,
        "transformersVersion": transformers.__version__,
        "processorBackend": "pil",
        "loadingCompatibility": {
            "missingIdentityLayerNormKeys": sorted(missing),
            "regeneratedRelativePositionIndexKeys": len(unexpected),
            "mismatchedKeys": 0,
            "errors": 0,
        },
        "pixelCounts": {str(key): value for key, value in sorted(class_counts.items())},
        "signCandidates": len(sign_observations),
        "skyColorSrgb": (
            (sky_rgb_sum / sky_rgb_count / 255.0).clip(0.0, 1.0).tolist()
            if sky_rgb_count
            else [0.0, 0.0, 0.0]
        ),
    }
    del model
    torch.cuda.empty_cache()
    return results, metrics, sign_observations


def calibrated_depth_correspondence(
    reference_record: Any,
    observation_record: Any,
    reference_relative_depth: Any,
    observation_relative_depth: Any,
    reference_alignment: Any,
    observation_alignment: Any,
) -> Any:
    """Map reference prior pixels into another calibrated registered view.

    The map is valid only when both per-frame relative-depth priors are aligned
    to the shared SfM frame and agree with the projected camera-Z depth.  A
    disagreement remains NaN instead of being coerced into a negative paint
    observation.
    """

    import cv2
    import numpy as np

    reference_depth = np.asarray(
        reference_alignment.apply(reference_relative_depth), dtype=np.float64
    )
    observation_depth = np.asarray(
        observation_alignment.apply(observation_relative_depth), dtype=np.float32
    )
    if reference_depth.ndim != 2 or observation_depth.ndim != 2:
        raise PriorError("Road-paint correspondence requires two-dimensional depth")
    height, width = reference_depth.shape
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    full_x = (grid_x.astype(np.float64) + 0.5) * reference_record.width / width - 0.5
    full_y = (grid_y.astype(np.float64) + 0.5) * reference_record.height / height - 0.5
    rays = np.stack(
        (
            (full_x - reference_record.calibration[0, 2])
            / reference_record.calibration[0, 0],
            (full_y - reference_record.calibration[1, 2])
            / reference_record.calibration[1, 1],
            np.ones_like(full_x),
        ),
        axis=-1,
    )
    reference_to_world = np.asarray(
        reference_record.camera_to_world, dtype=np.float64
    )
    world = (
        rays * reference_depth[..., None]
    ) @ reference_to_world[:3, :3].T + reference_to_world[:3, 3]
    observation_from_world = np.linalg.inv(
        np.asarray(observation_record.camera_to_world, dtype=np.float64)
    )
    camera = (
        world @ observation_from_world[:3, :3].T
        + observation_from_world[:3, 3]
    )
    camera_z = camera[..., 2]
    projected_x = (
        observation_record.calibration[0, 0]
        * camera[..., 0]
        / np.maximum(camera_z, 1.0e-9)
        + observation_record.calibration[0, 2]
    )
    projected_y = (
        observation_record.calibration[1, 1]
        * camera[..., 1]
        / np.maximum(camera_z, 1.0e-9)
        + observation_record.calibration[1, 2]
    )
    observation_height, observation_width = observation_depth.shape
    map_x = (
        (projected_x + 0.5) * observation_width / observation_record.width - 0.5
    ).astype(np.float32)
    map_y = (
        (projected_y + 0.5) * observation_height / observation_record.height - 0.5
    ).astype(np.float32)
    finite = (
        np.isfinite(reference_depth)
        & (reference_depth > 0.0)
        & np.isfinite(camera).all(axis=-1)
        & (camera_z > 1.0e-5)
        & np.isfinite(map_x)
        & np.isfinite(map_y)
        & (map_x >= -1.0e-4)
        & (map_x <= observation_width - 1.0 + 1.0e-4)
        & (map_y >= -1.0e-4)
        & (map_y <= observation_height - 1.0 + 1.0e-4)
    )
    safe_x = np.clip(
        np.where(finite, map_x, 0.0), 0.0, observation_width - 1.0
    ).astype(np.float32)
    safe_y = np.clip(
        np.where(finite, map_y, 0.0), 0.0, observation_height - 1.0
    ).astype(np.float32)
    sampled_depth = cv2.remap(
        observation_depth,
        safe_x,
        safe_y,
        interpolation=cv2.INTER_LINEAR,
        # Only finite pixel centres pass the bounds gate above.  REPLICATE
        # avoids OpenCV's bilinear border kernel mixing a valid last row or
        # column with a synthetic NaN sample outside the image.
        borderMode=cv2.BORDER_REPLICATE,
    )
    relative_disagreement = np.abs(sampled_depth - camera_z) / np.maximum(
        np.maximum(np.abs(sampled_depth), np.abs(camera_z)), 1.0e-6
    )
    # A surface measured materially closer in the observation view occludes
    # the projected reference point.  The broad symmetric tolerance below is
    # retained for monocular scale/shift noise, but it must never turn a
    # nearer car, barrier, sign, overpass deck, or other foreground layer into
    # corroborating road-paint evidence.
    closer_occlusion = sampled_depth < (camera_z * (1.0 - 0.08))
    finite &= (
        np.isfinite(sampled_depth)
        & (sampled_depth > 0.0)
        & np.isfinite(relative_disagreement)
        & (relative_disagreement <= 0.25)
        & ~closer_occlusion
    )
    result = np.stack((map_x, map_y), axis=-1)
    result[~finite] = np.nan
    return result.astype(np.float32)


def integrate_road_paint_evidence(
    records: list[Any],
    depths: list[Any],
    semantics: list[Any],
    alignments: list[Any | None],
    group_ids: list[str],
    output_root: Path,
    maximum_dimension: int,
) -> dict[str, Any]:
    """Promote only repeated observed white/yellow paint into stable semantics."""

    import cv2
    import numpy as np

    from servo_road_semantics import (
        RoadPaintEvidence,
        TemporalConsensusConfig,
        calibrated_multiframe_paint_consensus,
        extract_road_paint_evidence,
    )

    if not (
        len(records)
        == len(depths)
        == len(semantics)
        == len(alignments)
        == len(group_ids)
    ):
        raise PriorError("Road-paint evidence inputs do not cover every camera")
    grouped: dict[str, list[int]] = {}
    for index, group_id in enumerate(group_ids):
        grouped.setdefault(group_id, []).append(index)

    proposal_pixels = 0
    pre_suppression_proposal_pixels = 0
    suppressed_frames = 0
    accepted_pixels = 0
    rejected_pixels = 0
    unsupported_pixels = 0
    white_pixels = 0
    yellow_pixels = 0
    valid_warp_samples = 0
    per_frame: list[dict[str, Any] | None] = [None] * len(records)
    extraction_provenance: dict[str, Any] | None = None
    consensus_provenance: dict[str, Any] | None = None
    completed = 0
    for group_id in sorted(grouped):
        indices = grouped[group_id]
        cache: dict[int, RoadPaintEvidence] = {}

        def evidence_for(index: int) -> RoadPaintEvidence:
            nonlocal extraction_provenance
            nonlocal proposal_pixels
            nonlocal pre_suppression_proposal_pixels
            nonlocal suppressed_frames
            cached = cache.get(index)
            if cached is not None:
                return cached
            record = records[index]
            semantic = semantics[index]
            bgr = resized_bgr(record.path, maximum_dimension)
            road = np.isin(semantic, [1, 2, 5])
            extracted = extract_road_paint_evidence(
                bgr,
                road,
                target_size=(semantic.shape[1], semantic.shape[0]),
            )
            compact = RoadPaintEvidence(
                paint_class=extracted.paint_class,
                candidate_mask=extracted.candidate_mask,
                confidence=extracted.confidence.astype(np.float16),
                road_support=extracted.road_support,
                provenance=extracted.provenance,
                metrics=extracted.metrics,
            )
            cache[index] = compact
            proposal_pixels += int(extracted.metrics["candidatePixels"])
            pre_suppression_proposal_pixels += int(
                round(
                    float(extracted.metrics["preSuppressionPaintFractionOfRoad"])
                    * int(extracted.metrics["roadPixels"])
                )
            )
            suppressed_frames += int(bool(extracted.metrics["frameSuppressed"]))
            if extraction_provenance is None:
                extraction_provenance = extracted.provenance
            return compact

        for offset, index in enumerate(indices):
            record = records[index]
            extracted = evidence_for(index)
            adjacent = []
            if offset:
                adjacent.append(indices[offset - 1])
            if offset + 1 < len(indices):
                adjacent.append(indices[offset + 1])
            observation_indices = [
                value
                for value in adjacent
                if alignments[index] is not None and alignments[value] is not None
            ]
            observation_evidence = [evidence_for(value) for value in observation_indices]
            maps = [
                calibrated_depth_correspondence(
                    record,
                    records[value],
                    depths[index],
                    depths[value],
                    alignments[index],
                    alignments[value],
                )
                for value in observation_indices
            ]
            available_observations = 1 + len(observation_indices)
            minimum_observations = 3 if len(observation_indices) >= 2 else 2
            consensus = calibrated_multiframe_paint_consensus(
                extracted,
                observation_evidence,
                maps,
                config=TemporalConsensusConfig(
                    minimum_observations=minimum_observations,
                    minimum_agreeing_observations=2,
                    minimum_agreement_ratio=0.60,
                    minimum_source_proposal_confidence=0.20,
                    require_same_color=True,
                ),
            )
            accepted = consensus.accepted_mask
            updated = np.array(semantics[index], copy=True)
            updated[accepted] = 2
            semantics[index] = updated
            accepted_class = np.where(accepted, extracted.paint_class, 0).astype(np.uint8)
            confidence = np.rint(
                np.clip(consensus.confidence, 0.0, 1.0) * 255.0
            ).astype(np.uint8)
            atomic_png(
                output_root / "semantics" / Path(record.name).with_suffix(".png"),
                updated,
            )
            atomic_png(
                output_root
                / "road-paint"
                / "classes"
                / Path(record.name).with_suffix(".png"),
                accepted_class,
            )
            atomic_png(
                output_root
                / "road-paint"
                / "confidence"
                / Path(record.name).with_suffix(".png"),
                confidence,
            )
            frame_accepted = int(consensus.metrics["acceptedPixels"])
            frame_rejected = int(consensus.metrics["rejectedPixels"])
            frame_unsupported = int(consensus.metrics["unsupportedPixels"])
            accepted_pixels += frame_accepted
            rejected_pixels += frame_rejected
            unsupported_pixels += frame_unsupported
            valid_warp_samples += int(consensus.metrics["supportedWarpSamples"])
            white_pixels += int(np.count_nonzero(accepted_class == 1))
            yellow_pixels += int(np.count_nonzero(accepted_class == 2))
            consensus_provenance = consensus.provenance
            per_frame[index] = {
                "image": record.name,
                "neighbourViews": len(observation_indices),
                "availableObservations": available_observations,
                "proposedPixels": int(consensus.metrics["proposedPixels"]),
                "acceptedPixels": frame_accepted,
                "rejectedPixels": frame_rejected,
                "unsupportedPixels": frame_unsupported,
                "extractionSuppressed": bool(
                    extracted.metrics["frameSuppressed"]
                ),
            }
            completed += 1
            emit("road_paint_progress", completed=completed, total=len(records))
            keep = {index}
            if offset + 1 < len(indices):
                keep.add(indices[offset + 1])
            cache = {key: value for key, value in cache.items() if key in keep}
    longest_suppressed_run = 0
    current_run = 0
    for frame in per_frame:
        if frame is not None and bool(frame["extractionSuppressed"]):
            current_run += 1
            longest_suppressed_run = max(longest_suppressed_run, current_run)
        else:
            current_run = 0
    return {
        "schema": "servo.road-paint-consensus/v1",
        "method": (
            "road-gated-absolute-color-local-ridge-plus-calibrated-"
            "same-color-adjacent-depth-consensus-v2"
        ),
        "frames": len(records),
        "proposalPixels": proposal_pixels,
        "preSuppressionProposalPixels": pre_suppression_proposal_pixels,
        "suppressedFrames": suppressed_frames,
        "longestConsecutiveSuppressedFrames": longest_suppressed_run,
        "acceptedPixels": accepted_pixels,
        "rejectedPixels": rejected_pixels,
        "unsupportedPixels": unsupported_pixels,
        "acceptedFractionOfProposals": accepted_pixels / max(proposal_pixels, 1),
        "whitePixels": white_pixels,
        "yellowPixels": yellow_pixels,
        "supportedWarpSamples": valid_warp_samples,
        "correspondenceOcclusionPolicy": {
            "nearerObservationRelativeTolerance": 0.08,
            "maximumSymmetricRelativeDepthDisagreement": 0.25,
            "borderSampling": "finite-pixel-centres-only",
        },
        "pretrainedWeights": None,
        "metric": False,
        "collisionValidated": False,
        "extractionProvenance": extraction_provenance,
        "consensusProvenance": consensus_provenance,
        "maximumResidentEvidenceFrames": 3,
        "framesMetrics": [value for value in per_frame if value is not None],
        "limitations": [
            "Paint confidence is deterministic image evidence, not probability.",
            "Repeated monocular observations do not establish metric lane position.",
            "Unobserved or depth-inconsistent proposals remain unsupported.",
        ],
    }


def _resize_aligned_depth_for_sign_evidence(
    relative_depth: Any,
    alignment: Any | None,
    target_size: tuple[int, int],
) -> Any:
    """Return camera-Z depth at the sign-prior resolution without inventing support."""

    import cv2
    import numpy as np

    width, height = target_size
    if width <= 0 or height <= 0:
        raise PriorError("Sign-evidence target dimensions must be positive")
    if alignment is None:
        return np.full((height, width), np.nan, dtype=np.float32)
    source = np.asarray(alignment.apply(relative_depth), dtype=np.float32)
    if source.ndim != 2:
        raise PriorError("Sign evidence requires two-dimensional aligned depth")
    valid = np.isfinite(source) & (source > 0.0)
    if source.shape == (height, width):
        result = np.full(source.shape, np.nan, dtype=np.float32)
        result[valid] = source[valid]
        return result
    numerator = cv2.resize(
        np.where(valid, source, 0.0),
        (width, height),
        interpolation=cv2.INTER_LINEAR,
    )
    support = cv2.resize(
        valid.astype(np.float32),
        (width, height),
        interpolation=cv2.INTER_LINEAR,
    )
    # A resampled sign depth is admitted only when every contributing source
    # pixel was positive and finite.  Unsupported boundaries remain NaN.
    accepted = np.isfinite(numerator) & (support >= 1.0 - 1.0e-6)
    result = np.full((height, width), np.nan, dtype=np.float32)
    result[accepted] = numerator[accepted] / support[accepted]
    return result


def integrate_sign_evidence(
    records: list[Any],
    depths: list[Any],
    semantics: list[Any],
    alignments: list[Any | None],
    broad_observations: list[dict[str, Any]],
    output_root: Path,
    maximum_dimension: int,
    *,
    job_id: str,
    profile: str,
    pipeline_revision: str,
    configuration_hash: str,
) -> dict[str, Any]:
    """Build fail-closed calibrated sign-plane evidence from broad proposals.

    ADE20K class 43 is intentionally kept as a broad signboard proposal.  A
    repeated, planar observation may verify physical geometry only; it never
    establishes regulatory class or text.  Every atlas pixel is selected from
    an original undistorted source image by ``servo_sign_evidence``.
    """

    import cv2
    import numpy as np

    from servo_sign_evidence import (
        ClaimState,
        GeometryState,
        SignCandidate,
        SignEvidenceBundle,
        SignEvidenceConfig,
        SignEvidenceProvenance,
        build_sign_evidence,
        write_sign_evidence,
    )

    if not len(records) == len(depths) == len(semantics) == len(alignments):
        raise PriorError("Sign-evidence inputs do not cover every camera")
    identifiers = [str(value.get("candidateId", "")) for value in broad_observations]
    if any(not value for value in identifiers) or len(identifiers) != len(set(identifiers)):
        raise PriorError("Broad sign proposals require unique deterministic identifiers")
    provenance = SignEvidenceProvenance(
        sequence_id=job_id,
        coordinate_frame_id=f"colmap-undistorted:{job_id}",
        scale_provenance="sfm-arbitrary-scale",
        camera_source="COLMAP registered undistorted pinhole cameras",
        depth_source=(
            "Video Depth Anything Small camera-Z, per-sequence affine aligned "
            "to COLMAP sparse SfM depth"
        ),
        semantic_source=(
            "OneFormer ADE20K class-43 exact broad-signboard proposal support "
            "plus Servo stable safety semantics"
        ),
        candidate_source=(
            "OneFormer ADE20K class-43 connected components; broad signboard "
            "proposals only, not regulatory identity"
        ),
        source_hashes=(
            ("oneformer-checkpoint", "sha256:" + ONEFORMER_CHECKPOINT_SHA256),
            ("video-depth-checkpoint", "sha256:" + DEPTH_CHECKPOINT_SHA256),
        ),
    )
    config = SignEvidenceConfig()
    provenance.validate()
    config.validate()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for observation in broad_observations:
        frame_index = int(observation.get("frameIndex", -1))
        if frame_index < 0 or frame_index >= len(records):
            raise PriorError("Broad sign proposal references an invalid frame")
        if observation.get("image") != records[frame_index].name:
            raise PriorError("Broad sign proposal image/frame provenance mismatch")
        grouped.setdefault(frame_index, []).append(observation)

    candidates: list[SignCandidate] = []
    public_observations: list[dict[str, Any]] = []
    for frame_index in sorted(grouped):
        record = records[frame_index]
        semantic = np.asarray(semantics[frame_index], dtype=np.uint8)
        if semantic.ndim != 2:
            raise PriorError("Sign evidence requires two-dimensional semantics")
        height, width = semantic.shape
        bgr = resized_bgr(record.path, maximum_dimension)
        if bgr.shape[:2] != semantic.shape:
            raise PriorError("Sign proposal image and semantic dimensions disagree")
        aligned_depth = _resize_aligned_depth_for_sign_evidence(
            depths[frame_index],
            alignments[frame_index],
            (width, height),
        )
        for observation in sorted(
            grouped[frame_index], key=lambda value: str(value["candidateId"])
        ):
            box = observation.get("boxPriorPixels")
            prior_size = observation.get("priorSize")
            if (
                not isinstance(box, list)
                or len(box) != 4
                or not isinstance(prior_size, list)
                or prior_size != [width, height]
            ):
                raise PriorError("Broad sign proposal raster provenance is malformed")
            x, y, box_width, box_height = (int(value) for value in box)
            if (
                x < 0
                or y < 0
                or box_width <= 0
                or box_height <= 0
                or x + box_width > width
                or y + box_height > height
            ):
                raise PriorError("Broad sign proposal box is outside its prior raster")
            proposal_mask = np.asarray(
                observation.get("_candidateMask"), dtype=np.uint8
            )
            if proposal_mask.shape != (box_height, box_width):
                raise PriorError("Broad sign proposal mask does not match its box")
            proposal_mask = proposal_mask > 0
            if int(np.count_nonzero(proposal_mask)) != int(
                observation.get("areaPixels", -1)
            ):
                raise PriorError("Broad sign proposal area does not match its exact mask")
            mask_digest = hashlib.sha256()
            mask_digest.update(
                canonical_json(
                    {
                        "dtype": str(proposal_mask.astype(np.uint8).dtype),
                        "shape": list(proposal_mask.shape),
                    }
                )
            )
            mask_digest.update(proposal_mask.astype(np.uint8).tobytes())
            if observation.get("proposalMaskSha256") != (
                "sha256:" + mask_digest.hexdigest()
            ):
                raise PriorError("Broad sign proposal mask digest mismatch")
            candidate_id = str(observation["candidateId"])
            mask_path = Path("sign-proposals") / f"{candidate_id}.png"
            atomic_png(output_root / mask_path, proposal_mask.astype(np.uint8) * 255)

            semantic_crop = semantic[
                y : y + box_height, x : x + box_width
            ].copy()
            # This label exists only inside the evidence candidate passed to
            # the verifier.  The persisted scene semantic raster remains a
            # broad OTHER_STATIC region, so a signboard proposal is never
            # promoted to traffic-sign identity by one model observation.
            semantic_crop[proposal_mask] = 12
            x0 = x * float(record.width) / width
            y0 = y * float(record.height) / height
            x1 = (x + box_width) * float(record.width) / width
            y1 = (y + box_height) * float(record.height) / height
            candidates.append(
                SignCandidate(
                    candidate_id=candidate_id,
                    frame_id=record.name,
                    frame_index=frame_index,
                    box_xyxy=(x0, y0, x1, y1),
                    crop_bgr=bgr[
                        y : y + box_height, x : x + box_width
                    ].copy(),
                    candidate_mask=proposal_mask.copy(),
                    semantic_crop=semantic_crop,
                    depth_crop=aligned_depth[
                        y : y + box_height, x : x + box_width
                    ].copy(),
                    calibration=np.asarray(record.calibration, dtype=np.float64).copy(),
                    camera_to_world=np.asarray(
                        record.camera_to_world, dtype=np.float64
                    ).copy(),
                    observed_mask=np.ones(proposal_mask.shape, dtype=bool),
                    confidence_crop=None,
                    recognition=None,
                )
            )
            public = {
                key: value
                for key, value in observation.items()
                if not str(key).startswith("_")
            }
            public["proposalMask"] = mask_path.as_posix()
            public_observations.append(public)
        emit(
            "sign_evidence_candidate_progress",
            completed=frame_index + 1,
            total=len(records),
        )

    bundle = (
        build_sign_evidence(candidates, provenance, config)
        if candidates
        else SignEvidenceBundle(provenance, config, (), ())
    )
    manifest_path = write_sign_evidence(bundle, output_root)
    manifest = bundle.manifest()
    if manifest["safety"]["containsGeneratedPixels"] is not False:
        raise PriorError("Sign evidence unexpectedly contains generated pixels")
    for track in bundle.tracks:
        if (
            track.regulatory_class.state is not ClaimState.UNVERIFIED
            or track.text.state is not ClaimState.UNVERIFIED
        ):
            raise PriorError(
                "Sign regulatory claims require an external repeat-agreement stage"
            )
    states = {
        item.candidate.candidate_id: item for item in bundle.observations
    }
    for public in public_observations:
        evidence = states[str(public["candidateId"])]
        public["geometryState"] = evidence.state.value
        public["geometryReasons"] = list(evidence.reasons)
        public["geometryEvidenceSha256"] = evidence.evidence_sha256

    verified_tracks = [
        value
        for value in bundle.tracks
        if value.state is GeometryState.GEOMETRY_VERIFIED
    ]
    verified_observations = [
        value
        for value in bundle.observations
        if value.state is GeometryState.GEOMETRY_VERIFIED
    ]
    planar_observations = [
        value for value in bundle.observations if value.plane is not None
    ]
    atomic_json(
        output_root / "sign-observations.json",
        {
            "schema": SIGN_SCHEMA,
            "jobId": job_id,
            "profile": profile,
            "pipelineRevision": pipeline_revision,
            "configurationHash": configuration_hash,
            "classification": (
                "broad-semantic-proposals-with-separate-calibrated-geometry-evidence"
            ),
            "structuredEvidence": manifest_path.relative_to(output_root).as_posix(),
            "proposalSource": {
                "producer": "shi-labs/oneformer_ade20k_swin_tiny",
                "taxonomy": "ADE20K",
                "classId": 43,
                "meaning": "broad-signboard-candidate-not-regulatory-identity",
                "exactMasksPersisted": True,
                "independentSemanticConfirmation": False,
            },
            "observations": public_observations,
            "summary": {
                "proposalObservations": len(public_observations),
                "planarObservations": len(planar_observations),
                "geometryVerifiedObservations": len(verified_observations),
                "tracks": len(bundle.tracks),
                "geometryVerifiedTracks": len(verified_tracks),
                "regulatoryClassVerifiedTracks": 0,
                "textVerifiedTracks": 0,
            },
            "safety": {
                "collisionReady": False,
                "metricGeometry": False,
                "containsGeneratedPixels": False,
                "geometryDoesNotVerifyRegulatoryMeaning": True,
                "proposalAndSemanticSupportShareOneModel": True,
                "zeroVerifiedSignsIsValid": True,
            },
            "requirements": (
                "Regulatory text and class remain unverified until a separate "
                "external recognizer agrees across at least three calibrated views."
            ),
        },
    )
    return {
        "schema": manifest["schema"],
        "algorithm": manifest["algorithm"],
        "proposalObservations": len(public_observations),
        "planarObservations": len(planar_observations),
        "tracks": len(bundle.tracks),
        "geometryVerifiedObservations": len(verified_observations),
        "geometryVerifiedTracks": len(verified_tracks),
        "regulatoryClassVerifiedTracks": 0,
        "textVerifiedTracks": 0,
        "containsGeneratedPixels": False,
        "independentSemanticConfirmation": False,
        "metric": False,
        "collisionValidated": False,
        "zeroVerifiedSignsIsValid": True,
    }


def temporal_semantic_consistency(
    records: list[Any],
    depths: list[Any],
    semantics: list[Any],
    alignments: list[Any | None],
    group_ids: list[str],
) -> dict[str, Any]:
    """Validate adjacent masks after calibrated depth/camera reprojection."""

    import numpy as np

    from servo_geometry import ROAD_BOUNDARY_LABELS, ROAD_LABELS

    grouped: dict[str, list[int]] = {}
    for index, group_id in enumerate(group_ids):
        grouped.setdefault(group_id, []).append(index)
    total_candidates = 0
    total_overlap = 0
    sky_candidates = 0
    sky_overlap = 0
    total_agreement = 0
    unknown = 0
    pair_count = 0
    intersections = {"road": 0, "boundary": 0, "sky": 0}
    unions = {"road": 0, "boundary": 0, "sky": 0}
    road_ids = np.asarray(sorted(int(value) for value in ROAD_LABELS), dtype=np.uint8)
    boundary_ids = np.asarray(
        sorted(int(value) for value in ROAD_BOUNDARY_LABELS), dtype=np.uint8
    )
    for _, indices in sorted(grouped.items()):
        if len(indices) < 2:
            continue
        for first_index, second_index in zip(indices, indices[1:]):
            alignment = alignments[first_index]
            if alignment is None:
                continue
            first_record = records[first_index]
            second_record = records[second_index]
            first_semantic = semantics[first_index]
            second_semantic = semantics[second_index]
            height, width = first_semantic.shape
            grid_y, grid_x = np.mgrid[0:height:8, 0:width:8]
            x = grid_x.reshape(-1)
            y = grid_y.reshape(-1)
            total_candidates += len(x)
            depth = alignment.apply(depths[first_index])[y, x]
            full_x = (x.astype(np.float64) + 0.5) * first_record.width / width - 0.5
            full_y = (y.astype(np.float64) + 0.5) * first_record.height / height - 0.5
            rays = np.column_stack(
                (
                    (full_x - first_record.calibration[0, 2])
                    / first_record.calibration[0, 0],
                    (full_y - first_record.calibration[1, 2])
                    / first_record.calibration[1, 1],
                    np.ones_like(full_x),
                )
            )
            first_rotation = np.asarray(
                first_record.camera_to_world[:3, :3], dtype=np.float64
            )
            first_translation = np.asarray(
                first_record.camera_to_world[:3, 3], dtype=np.float64
            )
            world = rays * depth[:, None] @ first_rotation.T + first_translation
            second_from_world = np.linalg.inv(
                np.asarray(second_record.camera_to_world, dtype=np.float64)
            )

            def semantic_coordinates(camera_points: Any) -> tuple[Any, Any, Any]:
                projected_x = (
                    second_record.calibration[0, 0] * camera_points[:, 0]
                    / np.maximum(camera_points[:, 2], 1e-9)
                    + second_record.calibration[0, 2]
                )
                projected_y = (
                    second_record.calibration[1, 1] * camera_points[:, 1]
                    / np.maximum(camera_points[:, 2], 1e-9)
                    + second_record.calibration[1, 2]
                )
                x_float = (
                    (projected_x + 0.5) * second_semantic.shape[1]
                    / second_record.width
                    - 0.5
                )
                y_float = (
                    (projected_y + 0.5) * second_semantic.shape[0]
                    / second_record.height
                    - 0.5
                )
                finite = np.isfinite(x_float) & np.isfinite(y_float)
                mapped_x = np.rint(np.where(finite, x_float, -1.0)).astype(
                    np.int64
                )
                mapped_y = np.rint(np.where(finite, y_float, -1.0)).astype(
                    np.int64
                )
                return mapped_x, mapped_y, finite

            # Sky is effectively at infinity. Translating it by an inferred
            # finite monocular depth creates a false temporal-IoU failure, so
            # validate it with the calibrated rotation-only homography.
            sky_camera = rays @ first_rotation.T @ second_from_world[:3, :3].T
            sky_x, sky_y, finite_sky_projection = semantic_coordinates(sky_camera)
            valid_sky = (
                np.isfinite(sky_camera).all(axis=1)
                & (sky_camera[:, 2] > 1e-5)
                & finite_sky_projection
                & (sky_x >= 0)
                & (sky_x < second_semantic.shape[1])
                & (sky_y >= 0)
                & (sky_y < second_semantic.shape[0])
            )
            sky_candidates += len(x)
            sky_overlap += int(np.count_nonzero(valid_sky))
            if int(np.count_nonzero(valid_sky)) >= 64:
                first_sky = first_semantic[y[valid_sky], x[valid_sky]] == 17
                second_sky = second_semantic[
                    sky_y[valid_sky], sky_x[valid_sky]
                ] == 17
                intersections["sky"] += int(
                    np.count_nonzero(first_sky & second_sky)
                )
                unions["sky"] += int(np.count_nonzero(first_sky | second_sky))

            camera = (
                world @ second_from_world[:3, :3].T
                + second_from_world[:3, 3]
            )
            second_x, second_y, finite_projection = semantic_coordinates(camera)
            valid = (
                np.isfinite(depth)
                & (depth > 0.0)
                & np.isfinite(camera).all(axis=1)
                & (camera[:, 2] > 1e-5)
                & finite_projection
                & (second_x >= 0)
                & (second_x < second_semantic.shape[1])
                & (second_y >= 0)
                & (second_y < second_semantic.shape[0])
            )
            if int(np.count_nonzero(valid)) < 64:
                continue
            first_labels = first_semantic[y[valid], x[valid]]
            second_labels = second_semantic[second_y[valid], second_x[valid]]
            total_overlap += len(first_labels)
            total_agreement += int(np.count_nonzero(first_labels == second_labels))
            unknown += int(np.count_nonzero((first_labels == 0) | (second_labels == 0)))
            for name, first_mask, second_mask in (
                (
                    "road",
                    np.isin(first_labels, road_ids),
                    np.isin(second_labels, road_ids),
                ),
                (
                    "boundary",
                    np.isin(first_labels, boundary_ids),
                    np.isin(second_labels, boundary_ids),
                ),
            ):
                intersections[name] += int(np.count_nonzero(first_mask & second_mask))
                unions[name] += int(np.count_nonzero(first_mask | second_mask))
            pair_count += 1
    if pair_count == 0 or total_overlap == 0:
        raise PriorError("No adjacent semantic pair has valid geometric warp support")
    group_iou = {
        name: (
            intersections[name] / unions[name]
            if unions[name] > 0
            else None
        )
        for name in intersections
    }
    overlap_fraction = total_overlap / max(total_candidates, 1)
    agreement = total_agreement / total_overlap
    unknown_fraction = unknown / total_overlap
    failures: list[str] = []
    if overlap_fraction < 0.20:
        failures.append("semantic_warp_overlap_below_policy")
    if agreement < 0.75:
        failures.append("semantic_warp_agreement_below_policy")
    if group_iou["road"] is not None and group_iou["road"] < 0.65:
        failures.append("semantic_road_iou_below_policy")
    if group_iou["sky"] is not None and group_iou["sky"] < 0.70:
        failures.append("semantic_sky_iou_below_policy")
    if unknown_fraction > 0.20:
        failures.append("semantic_unknown_fraction_above_policy")
    return {
        "method": "adjacent-calibrated-depth-plus-infinite-sky-rotation-v2",
        "warpProvenance": (
            "VDA-relative-depth/per-sequence-SfM-affine/COLMAP-cameras;"
            "sky=rotation-only-infinite-depth"
        ),
        "pairCount": pair_count,
        "sampleCount": total_overlap,
        "overlapFraction": overlap_fraction,
        "skyRotationOverlapFraction": sky_overlap / max(sky_candidates, 1),
        "agreement": agreement,
        "unknownFraction": unknown_fraction,
        "groupIoU": group_iou,
        "passes": not failures,
        "failures": failures,
    }


def rotation_only_semantic_correspondence(
    source_record: Any,
    target_record: Any,
    source_shape: tuple[int, int],
    target_shape: tuple[int, int],
) -> tuple[Any, Any, Any]:
    """Project source pixels into a target semantic image at infinity.

    The mapping deliberately uses only calibrated camera rotations.  It is
    therefore valid evidence for a directional sky observation but must never
    be used to establish finite-road or obstacle correspondence.
    """

    import numpy as np

    source_height, source_width = source_shape
    target_height, target_width = target_shape
    if min(source_height, source_width, target_height, target_width) <= 0:
        raise PriorError("Sky-evidence semantic dimensions must be positive")
    source_calibration = np.asarray(source_record.calibration, dtype=np.float64)
    target_calibration = np.asarray(target_record.calibration, dtype=np.float64)
    source_camera = np.asarray(source_record.camera_to_world, dtype=np.float64)
    target_camera = np.asarray(target_record.camera_to_world, dtype=np.float64)
    if (
        source_calibration.shape != (3, 3)
        or target_calibration.shape != (3, 3)
        or source_camera.shape != (4, 4)
        or target_camera.shape != (4, 4)
        or not np.isfinite(source_calibration).all()
        or not np.isfinite(target_calibration).all()
        or not np.isfinite(source_camera).all()
        or not np.isfinite(target_camera).all()
        or source_calibration[0, 0] <= 0.0
        or source_calibration[1, 1] <= 0.0
        or target_calibration[0, 0] <= 0.0
        or target_calibration[1, 1] <= 0.0
    ):
        raise PriorError("Sky-evidence calibration or pose is invalid")
    grid_y, grid_x = np.mgrid[0:source_height, 0:source_width]
    full_x = (
        (grid_x.astype(np.float64) + 0.5) * source_record.width / source_width
        - 0.5
    )
    full_y = (
        (grid_y.astype(np.float64) + 0.5) * source_record.height / source_height
        - 0.5
    )
    rays = np.stack(
        (
            (full_x - source_calibration[0, 2]) / source_calibration[0, 0],
            (full_y - source_calibration[1, 2]) / source_calibration[1, 1],
            np.ones_like(full_x),
        ),
        axis=-1,
    )
    # Row-vector convention: world = camera @ R_source.T and camera_target
    # = world @ R_target. Translation must not enter an infinite-sky mapping.
    target_camera_points = (
        rays.reshape(-1, 3)
        @ source_camera[:3, :3].T
        @ target_camera[:3, :3]
    )
    target_z = target_camera_points[:, 2]
    projected_x = (
        target_calibration[0, 0] * target_camera_points[:, 0]
        / np.maximum(target_z, 1e-9)
        + target_calibration[0, 2]
    )
    projected_y = (
        target_calibration[1, 1] * target_camera_points[:, 1]
        / np.maximum(target_z, 1e-9)
        + target_calibration[1, 2]
    )
    semantic_x = (
        (projected_x + 0.5) * target_width / target_record.width - 0.5
    )
    semantic_y = (
        (projected_y + 0.5) * target_height / target_record.height - 0.5
    )
    finite = (
        np.isfinite(target_camera_points).all(axis=1)
        & (target_z > 1e-5)
        & np.isfinite(semantic_x)
        & np.isfinite(semantic_y)
    )
    mapped_x = np.rint(np.where(finite, semantic_x, -1.0)).astype(np.int64)
    mapped_y = np.rint(np.where(finite, semantic_y, -1.0)).astype(np.int64)
    valid = (
        finite
        & (mapped_x >= 0)
        & (mapped_x < target_width)
        & (mapped_y >= 0)
        & (mapped_y < target_height)
    )
    return (
        mapped_x.reshape(source_height, source_width),
        mapped_y.reshape(source_height, source_width),
        valid.reshape(source_height, source_width),
    )


def rotation_only_semantic_correspondence_points(
    source_record: Any,
    target_record: Any,
    source_shape: tuple[int, int],
    target_shape: tuple[int, int],
    source_x: Any,
    source_y: Any,
) -> tuple[Any, Any, Any]:
    """Map selected semantic pixels at infinity without materializing a grid.

    This is the same calibrated, translation-free correspondence as
    :func:`rotation_only_semantic_correspondence`, but temporal sky consensus
    only needs pixels that are already eroded source-sky candidates.  Avoiding
    full 960x960 grids for every neighbouring camera pair turns a prohibitively
    expensive prepass into evidence-proportional work.
    """

    import numpy as np

    source_height, source_width = source_shape
    target_height, target_width = target_shape
    x = np.asarray(source_x, dtype=np.int64).reshape(-1)
    y = np.asarray(source_y, dtype=np.int64).reshape(-1)
    if (
        min(source_height, source_width, target_height, target_width) <= 0
        or x.shape != y.shape
        or np.any(x < 0)
        or np.any(x >= source_width)
        or np.any(y < 0)
        or np.any(y >= source_height)
    ):
        raise PriorError("Sky-evidence candidate coordinates are invalid")
    source_calibration = np.asarray(source_record.calibration, dtype=np.float64)
    target_calibration = np.asarray(target_record.calibration, dtype=np.float64)
    source_camera = np.asarray(source_record.camera_to_world, dtype=np.float64)
    target_camera = np.asarray(target_record.camera_to_world, dtype=np.float64)
    if (
        source_calibration.shape != (3, 3)
        or target_calibration.shape != (3, 3)
        or source_camera.shape != (4, 4)
        or target_camera.shape != (4, 4)
        or not np.isfinite(source_calibration).all()
        or not np.isfinite(target_calibration).all()
        or not np.isfinite(source_camera).all()
        or not np.isfinite(target_camera).all()
        or source_calibration[0, 0] <= 0.0
        or source_calibration[1, 1] <= 0.0
        or target_calibration[0, 0] <= 0.0
        or target_calibration[1, 1] <= 0.0
    ):
        raise PriorError("Sky-evidence calibration or pose is invalid")
    full_x = (x.astype(np.float64) + 0.5) * source_record.width / source_width - 0.5
    full_y = (y.astype(np.float64) + 0.5) * source_record.height / source_height - 0.5
    rays = np.column_stack(
        (
            (full_x - source_calibration[0, 2]) / source_calibration[0, 0],
            (full_y - source_calibration[1, 2]) / source_calibration[1, 1],
            np.ones_like(full_x),
        )
    )
    target_camera_points = (
        rays @ source_camera[:3, :3].T @ target_camera[:3, :3]
    )
    target_z = target_camera_points[:, 2]
    projected_x = (
        target_calibration[0, 0] * target_camera_points[:, 0]
        / np.maximum(target_z, 1e-9)
        + target_calibration[0, 2]
    )
    projected_y = (
        target_calibration[1, 1] * target_camera_points[:, 1]
        / np.maximum(target_z, 1e-9)
        + target_calibration[1, 2]
    )
    semantic_x = (projected_x + 0.5) * target_width / target_record.width - 0.5
    semantic_y = (projected_y + 0.5) * target_height / target_record.height - 0.5
    finite = (
        np.isfinite(target_camera_points).all(axis=1)
        & (target_z > 1e-5)
        & np.isfinite(semantic_x)
        & np.isfinite(semantic_y)
    )
    mapped_x = np.rint(np.where(finite, semantic_x, -1.0)).astype(np.int64)
    mapped_y = np.rint(np.where(finite, semantic_y, -1.0)).astype(np.int64)
    valid = (
        finite
        & (mapped_x >= 0)
        & (mapped_x < target_width)
        & (mapped_y >= 0)
        & (mapped_y < target_height)
    )
    return mapped_x, mapped_y, valid


def certified_sky_evidence(
    records: Sequence[Any],
    semantics: Sequence[Any],
    group_ids: Sequence[str],
    *,
    minimum_supporting_views: int = CERTIFIED_SKY_EVIDENCE_MINIMUM_SUPPORTING_VIEWS,
    neighbour_window: int = CERTIFIED_SKY_EVIDENCE_NEIGHBOUR_WINDOW,
    erosion_radius: int = CERTIFIED_SKY_EVIDENCE_EROSION_RADIUS,
) -> tuple[list[Any], list[dict[str, int]]]:
    """Return tri-state, temporally confirmed sky evidence for every frame.

    ``1`` is the only value that permits a sky-opacity loss. ``2`` is an
    observed non-sky pixel and can later veto destructive cleanup. ``0`` means
    the sky label is ambiguous, unsupported, or unobserved; it deliberately
    produces neither a loss nor an inferred geometry target.
    """

    import cv2
    import numpy as np

    if not (
        len(records) == len(semantics) == len(group_ids)
        and records
    ):
        raise PriorError("Sky-evidence records, semantics, and groups must align")
    if (
        isinstance(minimum_supporting_views, bool)
        or isinstance(neighbour_window, bool)
        or isinstance(erosion_radius, bool)
        or minimum_supporting_views < 1
        or neighbour_window < 1
        or erosion_radius < 0
    ):
        raise PriorError("Sky-evidence consensus configuration is invalid")
    labels = [np.asarray(value, dtype=np.uint8) for value in semantics]
    if any(value.ndim != 2 or value.size == 0 for value in labels):
        raise PriorError("Sky-evidence semantic rasters must be non-empty uint8 images")
    kernel = np.ones((erosion_radius * 2 + 1, erosion_radius * 2 + 1), dtype=np.uint8)
    sky_interiors: list[Any] = []
    for semantic in labels:
        sky = (semantic == 17).astype(np.uint8)
        if erosion_radius:
            sky = cv2.erode(
                sky,
                kernel,
                borderType=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
        sky_interiors.append(sky.astype(bool))

    evidence: list[Any] = []
    frame_metrics: list[dict[str, int]] = []
    for index, (record, semantic, interior, group_id) in enumerate(
        zip(records, labels, sky_interiors, group_ids, strict=True)
    ):
        support = np.zeros(semantic.shape, dtype=np.uint8)
        conflict = np.zeros(semantic.shape, dtype=bool)
        candidate = interior
        candidate_y, candidate_x = np.nonzero(candidate)
        available = 0
        first = max(0, index - neighbour_window)
        last = min(len(records), index + neighbour_window + 1)
        for neighbour in range(first, last):
            if neighbour == index or group_ids[neighbour] != group_id:
                continue
            if candidate_x.size == 0:
                continue
            mapped_x, mapped_y, valid = rotation_only_semantic_correspondence_points(
                record,
                records[neighbour],
                semantic.shape,
                labels[neighbour].shape,
                candidate_x,
                candidate_y,
            )
            if not np.any(valid):
                continue
            available += 1
            selected_y = candidate_y[valid]
            selected_x = candidate_x[valid]
            target_labels = labels[neighbour][mapped_y[valid], mapped_x[valid]]
            agreeing = sky_interiors[neighbour][mapped_y[valid], mapped_x[valid]]
            support[selected_y[agreeing], selected_x[agreeing]] = np.minimum(
                support[selected_y[agreeing], selected_x[agreeing]] + 1,
                np.iinfo(np.uint8).max,
            )
            conflict[selected_y[target_labels != 17], selected_x[target_labels != 17]] = True
        certified = candidate & ~conflict & (support >= minimum_supporting_views)
        frame = np.full(
            semantic.shape,
            CERTIFIED_SKY_EVIDENCE_UNKNOWN,
            dtype=np.uint8,
        )
        frame[semantic != 17] = CERTIFIED_SKY_EVIDENCE_OBSERVED_NON_SKY
        frame[certified] = CERTIFIED_SKY_EVIDENCE_SKY
        evidence.append(frame)
        frame_metrics.append(
            {
                "rawSkyPixels": int(np.count_nonzero(semantic == 17)),
                "interiorSkyPixels": int(np.count_nonzero(candidate)),
                "certifiedSkyPixels": int(np.count_nonzero(certified)),
                "unconfirmedSkyPixels": int(
                    np.count_nonzero((semantic == 17) & ~certified)
                ),
                "observedNonSkyPixels": int(np.count_nonzero(semantic != 17)),
                "neighbourViews": available,
            }
        )
    return evidence, frame_metrics


def build_certified_sky_evidence(
    records: Sequence[Any],
    semantics: Sequence[Any],
    group_ids: Sequence[str],
    output_root: Path,
) -> dict[str, Any]:
    """Persist hash-bound temporal sky evidence next to geometry priors."""

    evidence, per_frame = certified_sky_evidence(records, semantics, group_ids)
    frames: list[dict[str, Any]] = []
    for record, mask, metrics in zip(records, evidence, per_frame, strict=True):
        relative = Path(CERTIFIED_SKY_EVIDENCE_DIRECTORY) / Path(record.name).with_suffix(
            ".png"
        )
        destination = output_root / relative
        atomic_png(destination, mask)
        frames.append(
            {
                "image": str(record.name).replace("\\", "/"),
                "asset": relative.as_posix(),
                "assetSha256": "sha256:" + sha256_file(destination),
                **metrics,
            }
        )
    descriptor = {
        "schema": CERTIFIED_SKY_EVIDENCE_SCHEMA,
        "method": CERTIFIED_SKY_EVIDENCE_METHOD,
        "storage": "uint8-tristate/0-unknown/1-certified-sky/2-observed-non-sky",
        "rotationOnlyInfiniteSky": True,
        "minimumSupportingViews": CERTIFIED_SKY_EVIDENCE_MINIMUM_SUPPORTING_VIEWS,
        "neighbourWindow": CERTIFIED_SKY_EVIDENCE_NEIGHBOUR_WINDOW,
        "erosionRadius": CERTIFIED_SKY_EVIDENCE_EROSION_RADIUS,
        "sourceSemanticLabel": 17,
        "source": "pinned-oneformer-ade20k-temporal-consensus",
        "frames": frames,
        "registeredImages": len(frames),
        "certifiedSkyPixels": sum(value["certifiedSkyPixels"] for value in frames),
        "unconfirmedSkyPixels": sum(value["unconfirmedSkyPixels"] for value in frames),
        "containsGeneratedPixels": False,
        "finiteGeometry": False,
        "metric": False,
    }
    manifest_path = output_root / CERTIFIED_SKY_EVIDENCE_ASSET
    atomic_json(manifest_path, descriptor)
    return {
        **descriptor,
        "manifest": CERTIFIED_SKY_EVIDENCE_ASSET,
        "manifestSha256": "sha256:" + sha256_file(manifest_path),
    }


def camera_basis(records: list[Any]) -> tuple[Any, Any, Any, Any, float]:
    import numpy as np

    centers = np.asarray([record.camera_to_world[:3, 3] for record in records], dtype=np.float64)
    origin = np.median(centers, axis=0)
    up = normalized(
        np.mean([-np.asarray(record.camera_to_world[:3, 1], dtype=np.float64) for record in records], axis=0),
        "navigation up",
    )
    travel = centers[-1] - centers[0]
    travel = travel - up * float(np.dot(travel, up))
    if float(np.linalg.norm(travel)) <= 1e-6:
        centered = centers - origin
        _, _, right_vectors = np.linalg.svd(centered, full_matrices=False)
        travel = right_vectors[0]
        travel -= up * float(np.dot(travel, up))
    forward = normalized(travel, "road forward")
    right = normalized(np.cross(up, forward), "road right")
    forward = normalized(np.cross(right, up), "orthogonal road forward")
    handedness = float(np.linalg.det(np.column_stack((forward, right, up))))
    if not math.isfinite(handedness) or handedness < 0.999:
        raise PriorError("Road coordinate basis is not right-handed")
    path_length = float(np.sum(np.linalg.norm(np.diff(centers, axis=0), axis=1)))
    return origin, forward, right, up, path_length


def path_frame_document(
    records: list[Any],
    origin: Any,
    forward: Any,
    right: Any,
    up: Any,
) -> dict[str, Any]:
    import numpy as np
    from scipy.ndimage import median_filter
    from scipy.signal import savgol_filter

    raw_centers = np.asarray(
        [record.camera_to_world[:3, 3] for record in records], dtype=np.float64
    )
    reference_axes = np.column_stack((forward, right))
    horizontal = (raw_centers - origin) @ reference_axes
    if len(horizontal) >= 7:
        filtered = np.column_stack(
            [
                median_filter(horizontal[:, axis], size=5, mode="nearest")
                for axis in range(2)
            ]
        )
        residual = np.linalg.norm(horizontal - filtered, axis=1)
        median = float(np.median(residual))
        mad = float(np.median(np.abs(residual - median)))
        threshold = median + max(4.0 * 1.4826 * mad, 1e-5)
        robust = horizontal.copy()
        robust[residual > threshold] = filtered[residual > threshold]
        window = min(15, len(robust) if len(robust) % 2 else len(robust) - 1)
        if window >= 7:
            smoothed = savgol_filter(
                robust,
                window_length=window,
                polyorder=3,
                axis=0,
                mode="interp",
            )
            # Preserve observed endpoints and ramp in the smoother.  Zero-padded
            # or fully weighted boundary filters can move the first road pose by
            # several real frame intervals, bending the surface exactly where
            # evidence is already one-sided.
            edge = max(1, window // 2)
            indices = np.arange(len(robust), dtype=np.float64)
            taper = np.minimum.reduce(
                (
                    np.ones(len(robust), dtype=np.float64),
                    indices / edge,
                    (len(robust) - 1.0 - indices) / edge,
                )
            )[:, None]
            horizontal = robust + taper * (smoothed - robust)
    vertical = (raw_centers - origin) @ up
    centers = (
        np.asarray(origin, dtype=np.float64)
        + horizontal @ reference_axes.T
        + np.outer(vertical, up)
    )
    smoothing_shift = np.linalg.norm(
        ((centers - raw_centers) @ reference_axes), axis=1
    )
    horizontal_steps = np.diff(centers, axis=0)
    horizontal_steps -= np.outer(horizontal_steps @ up, up)
    lengths = np.linalg.norm(horizontal_steps, axis=1)
    if int(np.count_nonzero(lengths > 1e-6)) < 2:
        raise PriorError("Camera path has insufficient horizontal motion")
    arc = np.concatenate(([0.0], np.cumsum(lengths)))
    median_step = float(np.median(lengths[lengths > 1e-6]))
    endpoint_extension = min(float(arc[-1]) * 0.20, median_step * 64.0)
    return {
        "coordinateModel": "ordered-camera-path-frenet-v1",
        "origin": np.asarray(origin, dtype=np.float64).tolist(),
        "referenceForward": np.asarray(forward, dtype=np.float64).tolist(),
        "referenceRight": np.asarray(right, dtype=np.float64).tolist(),
        "up": np.asarray(up, dtype=np.float64).tolist(),
        "centers": centers.tolist(),
        "rawCenters": raw_centers.tolist(),
        "arcLengths": arc.tolist(),
        "cameraImages": [record.name for record in records],
        "handedness": "right-handed",
        "segmentCandidateCount": 16,
        "localTieBreakRadius": 8,
        "associationTieDistanceFraction": 0.25,
        "associationVerticalWeight": 1.0,
        "endpointTangentExtension": endpoint_extension,
        "smoothing": {
            "method": "hampel-median-plus-local-cubic-savgol-v1",
            "windowFrames": min(15, len(centers) if len(centers) % 2 else len(centers) - 1),
            "horizontalShiftRms": float(np.sqrt(np.mean(smoothing_shift**2))),
            "horizontalShiftMax": float(np.max(smoothing_shift)),
            "rawPosesPreserved": True,
            "endpointsPinned": True,
        },
    }


def path_coordinates(
    points: Any,
    path_frame: dict[str, Any],
    hint_index: int,
    fixed_segments: Any | None = None,
) -> tuple[Any, Any, Any]:
    """Map world points to ordered path arc length, lateral offset, and height."""

    import numpy as np

    value = np.asarray(points, dtype=np.float64)
    centers = np.asarray(path_frame["centers"], dtype=np.float64)
    arc = np.asarray(path_frame["arcLengths"], dtype=np.float64)
    up = np.asarray(path_frame["up"], dtype=np.float64)
    origin = np.asarray(path_frame["origin"], dtype=np.float64)
    if value.ndim != 2 or value.shape[1] != 3:
        raise PriorError("Path coordinates require an N x 3 point array")

    def coordinates_for_segments(segments: Any) -> tuple[Any, Any, Any]:
        segment_ids = np.asarray(segments, dtype=np.int64)
        start = centers[segment_ids]
        delta = centers[segment_ids + 1] - start
        horizontal = delta - np.outer(delta @ up, up)
        length = np.linalg.norm(horizontal, axis=1)
        safe = length > 1e-8
        direction = np.zeros_like(horizontal)
        direction[safe] = horizontal[safe] / length[safe, None]
        point_delta = value - start
        along = np.sum(point_delta * direction, axis=1)
        fraction = np.zeros(len(value), dtype=np.float64)
        fraction[safe] = np.clip(along[safe] / length[safe], 0.0, 1.0)
        endpoint_extension = max(
            0.0, float(path_frame.get("endpointTangentExtension", 0.0))
        )
        first = safe & (segment_ids == 0) & (along < 0.0)
        last = safe & (segment_ids == len(centers) - 2) & (along > length)
        fraction[first] = np.maximum(
            along[first], -endpoint_extension
        ) / length[first]
        fraction[last] = np.minimum(
            along[last], length[last] + endpoint_extension
        ) / length[last]
        nearest = start + horizontal * fraction[:, None]
        residual = value - nearest
        horizontal_residual = residual - np.outer(residual @ up, up)
        distance_squared = np.sum(horizontal_residual * horizontal_residual, axis=1)
        path_nearest = start + delta * fraction[:, None]
        vertical_residual = np.sum((value - path_nearest) * up, axis=1)
        vertical_weight = max(
            0.0, float(path_frame.get("associationVerticalWeight", 1.0))
        )
        association_score_squared = (
            distance_squared + vertical_weight * vertical_residual * vertical_residual
        )
        right_axis = np.cross(np.broadcast_to(up, direction.shape), direction)
        lateral = np.sum(residual * right_axis, axis=1)
        longitudinal = arc[segment_ids] + fraction * length
        height = (value - origin) @ up
        local = np.column_stack((longitudinal, lateral, height))
        distance_squared[~safe] = np.inf
        association_score_squared[~safe] = np.inf
        return local, distance_squared, association_score_squared

    if fixed_segments is not None:
        segment_ids = np.asarray(fixed_segments, dtype=np.int64)
        local, distance_squared, _ = coordinates_for_segments(segment_ids)
        return local, segment_ids, np.sqrt(distance_squared)

    from scipy.spatial import cKDTree

    candidate_count = max(1, int(path_frame.get("segmentCandidateCount", 16)))
    local_radius = max(0, int(path_frame.get("localTieBreakRadius", 8)))
    reference = np.column_stack(
        (
            np.asarray(path_frame["referenceForward"], dtype=np.float64),
            np.asarray(path_frame["referenceRight"], dtype=np.float64),
        )
    )
    center_plane = (centers - origin) @ reference
    point_plane = (value - origin) @ reference
    segment_plane = 0.5 * (center_plane[:-1] + center_plane[1:])
    nearest = cKDTree(segment_plane).query(
        point_plane,
        k=min(candidate_count, len(segment_plane)),
        workers=-1,
    )[1]
    nearest = np.asarray(nearest, dtype=np.int64)
    if nearest.ndim == 1:
        nearest = nearest[:, None]
    local_candidates = np.arange(
        max(0, int(hint_index) - local_radius),
        min(len(centers) - 2, int(hint_index) + local_radius) + 1,
        dtype=np.int64,
    )
    if len(local_candidates):
        nearest = np.column_stack(
            (nearest, np.broadcast_to(local_candidates, (len(value), len(local_candidates))))
        )
    minimum_association_score = np.full(len(value), np.inf, dtype=np.float64)
    minimum_segments = np.zeros(len(value), dtype=np.int64)
    for column in range(nearest.shape[1]):
        segments = nearest[:, column]
        _, _, association_score_squared = coordinates_for_segments(segments)
        better = association_score_squared < minimum_association_score
        minimum_association_score[better] = association_score_squared[better]
        minimum_segments[better] = segments[better]

    nonzero_steps = np.diff(arc)
    nonzero_steps = nonzero_steps[nonzero_steps > 1.0e-8]
    median_step = float(np.median(nonzero_steps)) if nonzero_steps.size else 1.0
    tie_fraction = max(
        0.0, float(path_frame.get("associationTieDistanceFraction", 0.25))
    )
    tie_distance_squared = (tie_fraction * median_step) ** 2
    best_distance = np.full(len(value), np.inf, dtype=np.float64)
    best_association_score = np.full(len(value), np.inf, dtype=np.float64)
    best_station_delta = np.full(len(value), np.inf, dtype=np.float64)
    best_segments = np.zeros(len(value), dtype=np.int64)
    best_local = np.full((len(value), 3), np.nan, dtype=np.float64)
    clipped_hint_index = int(np.clip(int(hint_index), 0, len(centers) - 2))
    for column in range(nearest.shape[1]):
        segments = nearest[:, column]
        local, distance_squared, association_score_squared = (
            coordinates_for_segments(segments)
        )
        # Treat sub-step spatial differences as uncertain at a crossing and
        # use ordered capture topology to resolve them.  Candidates farther
        # than this bounded band remain purely geometric, so far-ahead visible
        # road is never pulled back to the current frame's local window.
        exact_spatial = association_score_squared <= (
            minimum_association_score + 1.0e-12
        )
        nonlocal_crossing = np.abs(segments - minimum_segments) > 1
        eligible = exact_spatial | (
            nonlocal_crossing
            & (
                association_score_squared
                <= minimum_association_score + tie_distance_squared
            )
        )
        station_delta = np.abs(segments - clipped_hint_index).astype(np.float64)
        choose = eligible & (
            (station_delta < best_station_delta - 1.0e-12)
            | (
                np.abs(station_delta - best_station_delta) <= 1.0e-12
            )
            & (association_score_squared < best_association_score)
        )
        best_station_delta[choose] = station_delta[choose]
        best_association_score[choose] = association_score_squared[choose]
        best_distance[choose] = distance_squared[choose]
        best_segments[choose] = segments[choose]
        best_local[choose] = local[choose]
    return best_local, best_segments, np.sqrt(best_distance)


def build_road_surface(
    records: list[Any],
    depths: list[Any],
    semantics: list[Any],
    alignments: list[Any | None],
    group_ids: list[str],
    training_root: Path,
) -> tuple[Any, dict[str, Any]]:
    import cv2
    import numpy as np

    from servo_geometry import (
        NAVIGABLE_SURFACE_LABELS,
        EvidenceBoundedRoadSurfaceFit,
        fit_observed_road_surface,
        fit_piecewise_road_surface,
    )

    road_ids = np.asarray(
        sorted(int(label) for label in NAVIGABLE_SURFACE_LABELS), dtype=np.uint8
    )
    group_support: dict[str, int] = {}
    for semantic, alignment, group_id in zip(
        semantics, alignments, group_ids, strict=True
    ):
        if alignment is not None:
            group_support[group_id] = group_support.get(group_id, 0) + int(
                np.count_nonzero(np.isin(semantic, road_ids))
            )
    if not group_support:
        raise PriorError("No aligned inference sequence contains navigable surface")
    surface_group = max(group_support, key=lambda value: (group_support[value], value))
    selected_records = [
        record
        for record, alignment, group_id in zip(
            records, alignments, group_ids, strict=True
        )
        if alignment is not None and group_id == surface_group
    ]
    if len(selected_records) < 4:
        raise PriorError("The primary navigable-surface sequence has fewer than four cameras")
    origin, forward, right, up, path_length = camera_basis(selected_records)
    path_frame = path_frame_document(
        selected_records, origin, forward, right, up
    )
    image_hints = {
        record.name: index for index, record in enumerate(selected_records)
    }
    samples: list[Any] = []
    weights: list[Any] = []
    sample_frames: list[Any] = []
    association_distances: list[Any] = []
    for frame_index, (record, relative, semantic, alignment, group_id) in enumerate(
        zip(records, depths, semantics, alignments, group_ids, strict=True)
    ):
        if alignment is None or group_id != surface_group:
            continue
        height, width = semantic.shape
        road = np.isin(semantic, road_ids)
        grid_y, grid_x = np.mgrid[0:height:10, 0:width:10]
        selected = road[grid_y, grid_x]
        if not np.any(selected):
            continue
        x = grid_x[selected]
        y = grid_y[selected]
        raw = relative[y, x]
        depth = alignment.apply(raw)
        full_x = (x.astype(np.float64) + 0.5) * record.width / width - 0.5
        full_y = (y.astype(np.float64) + 0.5) * record.height / height - 0.5
        ray = np.column_stack(
            (
                (full_x - record.calibration[0, 2]) / record.calibration[0, 0],
                (full_y - record.calibration[1, 2]) / record.calibration[1, 1],
                np.ones_like(full_x),
            )
        )
        camera_points = ray * depth[:, None]
        world = (
            camera_points @ np.asarray(record.camera_to_world[:3, :3], dtype=np.float64).T
            + np.asarray(record.camera_to_world[:3, 3], dtype=np.float64)
        )
        local, _, association_distance = path_coordinates(
            world, path_frame, image_hints[record.name]
        )
        mask_path = training_root / "masks" / record.name
        confidence_image = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if confidence_image is None:
            confidence = np.ones(len(local), dtype=np.float64)
        else:
            confidence = confidence_image[
                np.clip(np.rint(full_y).astype(np.int64), 0, confidence_image.shape[0] - 1),
                np.clip(np.rint(full_x).astype(np.int64), 0, confidence_image.shape[1] - 1),
            ].astype(np.float64) / 255.0
        finite = (
            np.isfinite(local).all(axis=1)
            & np.isfinite(association_distance)
            & np.isfinite(confidence)
            & (confidence > 0.05)
        )
        samples.append(local[finite])
        weights.append(confidence[finite])
        sample_frames.append(
            np.full(int(np.count_nonzero(finite)), frame_index, dtype=np.int64)
        )
        association_distances.append(association_distance[finite])
    if not samples:
        raise PriorError("No semantic road samples survive depth alignment")
    points = np.concatenate(samples)
    confidence = np.concatenate(weights)
    frame_ids = np.concatenate(sample_frames)
    path_distance = np.concatenate(association_distances)
    maximum_supported_distance = float(np.percentile(path_distance, 99.5))
    if len(points) > 250_000:
        selected = np.linspace(0, len(points) - 1, 250_000).round().astype(np.int64)
        points = points[selected]
        confidence = confidence[selected]
        frame_ids = frame_ids[selected]
        path_distance = path_distance[selected]

    station_low, station_high = np.percentile(points[:, 0], [1.0, 99.0])
    station_edges = np.linspace(float(station_low), float(station_high), 65)
    station_widths: list[float] = []
    for low, high in zip(station_edges[:-1], station_edges[1:], strict=True):
        selected_station = (points[:, 0] >= low) & (points[:, 0] < high)
        if int(np.count_nonzero(selected_station)) >= 20:
            station_widths.append(
                float(np.percentile(path_distance[selected_station], 95.0))
            )
    if station_widths:
        typical_width = float(np.median(station_widths))
        width_mad = float(
            np.median(np.abs(np.asarray(station_widths) - typical_width))
        )
        primary_supported_distance = max(
            float(np.percentile(path_distance, 85.0)),
            1.15 * typical_width,
            typical_width + 2.0 * 1.4826 * width_mad,
        )
    else:
        primary_supported_distance = float(np.percentile(path_distance, 95.0))
    primary_supported_distance = min(
        primary_supported_distance, maximum_supported_distance
    )
    primary_supported = path_distance <= primary_supported_distance
    if int(np.count_nonzero(primary_supported)) < 100:
        primary_supported_distance = float(np.percentile(path_distance, 99.0))
        primary_supported = path_distance <= primary_supported_distance

    primary_points = points[primary_supported]
    primary_confidence = confidence[primary_supported]
    road_extent = float(
        np.percentile(primary_points[:, 0], 99)
        - np.percentile(primary_points[:, 0], 1)
    )
    knot_spacing = max(0.04, path_length / 64.0, road_extent / 96.0)
    primary_fit = fit_piecewise_road_surface(
        primary_points,
        primary_confidence,
        knot_spacing=knot_spacing,
        min_points=100,
        min_support_per_knot=10,
        max_knots=128,
        smoothness=0.12,
    )
    observed_fit = fit_observed_road_surface(
        points,
        confidence,
        frame_ids,
        primary_surface=primary_fit,
        cell_size=max(0.005, 0.5 * knot_spacing),
        min_samples_per_cell=3,
        min_frames_per_cell=2,
        smoothness=0.08,
        max_iterations=256,
    )
    fit = EvidenceBoundedRoadSurfaceFit(primary_fit, observed_fit)
    document = {
        "schema": ROAD_SCHEMA,
        "surfaceKind": (
            "road"
            if any(np.any(value == 1) for value in semantics)
            else "interior-floor"
        ),
        "sourceSequence": surface_group,
        "sourceFrames": len(selected_records),
        "association": {
            "policy": (
                "global-3d-polyline-segment-plus-bounded-ordered-crossing-tiebreak-v2"
            ),
            "sampleCount": int(len(path_distance)),
            "distanceP50": float(np.percentile(path_distance, 50)),
            "distanceP95": float(np.percentile(path_distance, 95)),
            "distanceP99": float(np.percentile(path_distance, 99)),
            "maximumSupportedDistance": maximum_supported_distance,
            "primaryMaximumSupportedDistance": primary_supported_distance,
            "endpointTangentExtension": path_frame["endpointTangentExtension"],
        },
        "scaleProvenance": "sfm-arbitrary",
        "metric": False,
        "collisionValidated": False,
        "basis": {
            "origin": origin.tolist(),
            "forward": forward.tolist(),
            "right": right.tolist(),
            "up": up.tolist(),
            "handedness": "right-handed",
        },
        "pathFrame": path_frame,
        "surface": {
            "model": "piecewise-linear-elevation-and-bank-plus-observed-cell-graph-v1",
            "knots": primary_fit.knots.tolist(),
            "elevations": primary_fit.elevations.tolist(),
            "banks": primary_fit.banks.tolist(),
            "lateralOrigin": primary_fit.lateral_origin,
            "lateralMin": primary_fit.lateral_min,
            "lateralMax": primary_fit.lateral_max,
            "knotSpacing": knot_spacing,
            "supportPerKnot": primary_fit.support_per_knot.tolist(),
        },
        "observedSurface": {
            "model": "sparse-connected-road-cell-graph-v1",
            "solverPolicy": "adaptive-huber-with-cycle-midpoint-freeze-v1",
            "supportPolicy": (
                "multi-frame-semantic-road-cells-connected-to-primary-path; "
                "no convex-hull fill or out-of-cell extrapolation"
            ),
            "cellSize": observed_fit.cell_size,
            "gridOrigin": observed_fit.grid_origin.tolist(),
            "gridShape": list(observed_fit.grid_shape),
            "cellIndices": observed_fit.cell_indices.tolist(),
            "blockedCellKeys": observed_fit.blocked_cell_keys.tolist(),
            "heights": observed_fit.heights.tolist(),
            "slopes": observed_fit.slopes.tolist(),
            "supportCounts": observed_fit.support_counts.tolist(),
            "frameCounts": observed_fit.frame_counts.tolist(),
            "candidateCellCount": observed_fit.candidate_cell_count,
            "retainedCellCount": observed_fit.retained_cell_count,
            "componentCount": observed_fit.component_count,
            "retainedComponentCount": observed_fit.retained_component_count,
            "anchorCellCount": observed_fit.anchor_cell_count,
            "blockedCellCount": int(len(observed_fit.blocked_cell_keys)),
            "ambiguousCellCount": observed_fit.ambiguous_cell_count,
            "maximumCellP95Residual": observed_fit.maximum_cell_p95_residual,
            "p50AbsoluteResidual": observed_fit.p50_absolute_residual,
            "p95AbsoluteResidual": observed_fit.p95_absolute_residual,
            "maxAbsoluteResidual": observed_fit.max_absolute_residual,
            "inlierRatio": observed_fit.inlier_ratio,
            "iterations": observed_fit.iterations,
            "converged": observed_fit.converged,
            "huberScale": observed_fit.huber_scale,
            "huberScaleFrozen": observed_fit.huber_scale_frozen,
            "huberObjective": observed_fit.huber_objective,
            "relativeSolutionChange": observed_fit.relative_solution_change,
            "normalizedWeightChange": observed_fit.normalized_weight_change,
            "twoCycleSolutionChange": (
                observed_fit.two_cycle_solution_change
                if math.isfinite(observed_fit.two_cycle_solution_change)
                else None
            ),
            "twoCycleWeightChange": (
                observed_fit.two_cycle_weight_change
                if math.isfinite(observed_fit.two_cycle_weight_change)
                else None
            ),
            "firstOrderOptimality": observed_fit.first_order_optimality,
            "backtrackingSteps": observed_fit.backtracking_steps,
            "terminationReason": observed_fit.termination_reason,
        },
        "fit": {
            "sampleCount": primary_fit.sample_count,
            "inlierCount": primary_fit.inlier_count,
            "inlierRatio": primary_fit.inlier_ratio,
            "p50AbsoluteResidual": primary_fit.p50_absolute_residual,
            "p95AbsoluteResidual": primary_fit.p95_absolute_residual,
            "maxAbsoluteResidual": primary_fit.max_absolute_residual,
            "coveredKnotFraction": primary_fit.covered_knot_fraction,
            "conditionNumber": primary_fit.condition_number,
            "iterations": primary_fit.iterations,
            "converged": primary_fit.converged,
        },
        "limits": (
            "The primary surface is defined only inside its observed path corridor; "
            "branch support exists only in retained observed cells. It has arbitrary "
            "monocular scale and is not a collision mesh."
        ),
    }
    return fit, document


def road_surface_depth(
    record: Any,
    relative: Any,
    semantic: Any,
    alignment: Any | None,
    fit: Any,
    road_document: dict[str, Any],
    use_surface: bool,
) -> tuple[Any, Any]:
    import numpy as np

    from servo_geometry import NAVIGABLE_SURFACE_LABELS

    if alignment is None:
        return (
            np.full(relative.shape, np.nan, dtype=np.float32),
            np.zeros(relative.shape, dtype=np.float32),
        )
    aligned = alignment.apply(relative)
    road_result = np.zeros(relative.shape, dtype=np.float32)
    if not use_surface:
        return aligned.astype(np.float32), road_result
    road_ids = np.asarray(
        sorted(int(label) for label in NAVIGABLE_SURFACE_LABELS), dtype=np.uint8
    )
    road = np.isin(semantic, road_ids) & np.isfinite(aligned) & (aligned > 0.0)
    if not np.any(road):
        return aligned.astype(np.float32), road_result
    y, x = np.nonzero(road)
    height, width = relative.shape
    full_x = (x.astype(np.float64) + 0.5) * record.width / width - 0.5
    full_y = (y.astype(np.float64) + 0.5) * record.height / height - 0.5
    rays = np.column_stack(
        (
            (full_x - record.calibration[0, 2]) / record.calibration[0, 0],
            (full_y - record.calibration[1, 2]) / record.calibration[1, 1],
            np.ones_like(full_x),
        )
    )
    rotation = np.asarray(record.camera_to_world[:3, :3], dtype=np.float64)
    translation = np.asarray(record.camera_to_world[:3, 3], dtype=np.float64)
    path_frame = road_document["pathFrame"]
    try:
        hint_index = path_frame["cameraImages"].index(record.name)
    except ValueError:
        return aligned.astype(np.float32), road_result
    depth = aligned[y, x].astype(np.float64)
    initial_world = rays * depth[:, None] @ rotation.T + translation
    initial_local, segments, _ = path_coordinates(
        initial_world, path_frame, hint_index
    )
    initial_target = fit.predict(initial_local, allow_extrapolation=False)
    valid = (
        np.isfinite(initial_local).all(axis=1)
        & np.isfinite(initial_target)
    )
    for _ in range(8):
        world = rays * depth[:, None] @ rotation.T + translation
        local, _, _ = path_coordinates(
            world, path_frame, hint_index, fixed_segments=segments
        )
        target = fit.predict(local, allow_extrapolation=False)
        residual = local[:, 2] - target
        epsilon = np.maximum(1e-4, depth * 1e-3)
        plus_world = rays * (depth + epsilon)[:, None] @ rotation.T + translation
        plus_local, _, _ = path_coordinates(
            plus_world, path_frame, hint_index, fixed_segments=segments
        )
        plus_target = fit.predict(plus_local, allow_extrapolation=False)
        derivative = (plus_local[:, 2] - plus_target - residual) / epsilon
        update_valid = (
            np.isfinite(residual)
            & np.isfinite(derivative)
            & (np.abs(derivative) > 1e-5)
        )
        correction = np.zeros_like(depth)
        correction[update_valid] = -residual[update_valid] / derivative[update_valid]
        correction = np.clip(correction, -0.25 * depth, 0.25 * depth)
        depth += correction
        valid &= update_valid & np.isfinite(depth) & (depth > 0.0)
    final_world = rays * depth[:, None] @ rotation.T + translation
    final_local, _, _ = path_coordinates(
        final_world, path_frame, hint_index, fixed_segments=segments
    )
    final_target = fit.predict(final_local, allow_extrapolation=False)
    final_residual = np.abs(final_local[:, 2] - final_target)
    residual_limit = max(
        0.01,
        3.0 * float(road_document["fit"]["p95AbsoluteResidual"]),
        3.0
        * float(
            road_document.get("observedSurface", {}).get(
                "p95AbsoluteResidual", 0.0
            )
        ),
    )
    valid &= (
        np.isfinite(final_residual)
        & (final_residual <= residual_limit)
    )
    road_result[y[valid], x[valid]] = depth[valid].astype(np.float32)
    return aligned.astype(np.float32), road_result


def build(arguments: argparse.Namespace) -> int:
    import cv2
    import numpy as np
    import torch

    from servo_environment import build_observed_directional_environment
    from servo_train import ColmapDataset

    verify_inputs(
        arguments.video_depth_root,
        arguments.depth_checkpoint,
        arguments.oneformer_root,
    )
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dataset = ColmapDataset(
        arguments.data.resolve(),
        factor=1,
        require_static_masks=True,
    )
    records = dataset.records
    if not records:
        raise PriorError("No registered cameras are available for geometry priors")
    started = time.perf_counter()
    depths, depth_group_ids, depth_metrics = infer_relative_depths(
        records,
        arguments.video_depth_root,
        arguments.depth_checkpoint,
        arguments.maximum_dimension,
        arguments.depth_input_size,
    )
    semantics, semantic_metrics, sign_observations = infer_semantics(
        records,
        arguments.oneformer_root,
        output,
        arguments.maximum_dimension,
    )

    # A raw per-frame sky label is not enough evidence to erase finite scene
    # support near mountain, tree, or roof boundaries.  Persist an additional
    # fail-closed temporal receipt: only rotation-consistent, eroded sky pixels
    # across calibrated neighbouring cameras can supervise finite alpha.
    semantic_metrics["certifiedSkyEvidence"] = build_certified_sky_evidence(
        records,
        semantics,
        depth_group_ids,
        output,
    )

    # The distant sky must not be represented by finite scene Gaussians.  Build
    # one direction-indexed RGBA background from the same original RGB pixels
    # and OneFormer sky masks used by this stage.  The transparent texels are
    # intentionally left unknown: the renderer will use the documented mean
    # fallback there instead of manufacturing an unseen horizon or cloud.
    def semantic_rgb(index: int) -> Any:
        bgr = resized_bgr(records[index].path, arguments.maximum_dimension)
        if bgr.shape[:2] != semantics[index].shape:
            raise PriorError(
                "Directional environment RGB and semantic evidence dimensions disagree."
            )
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    semantic_metrics["observedDirectionalEnvironment"] = (
        build_observed_directional_environment(
            records,
            semantic_rgb,
            semantics,
            output,
        )
    )
    alignments, alignment_metrics = sample_sparse_alignment(
        records, depths, depth_group_ids, semantics
    )
    road_paint_metrics = integrate_road_paint_evidence(
        records,
        depths,
        semantics,
        alignments,
        depth_group_ids,
        output,
        arguments.maximum_dimension,
    )
    semantic_metrics["roadPaint"] = road_paint_metrics
    semantic_metrics["signEvidence"] = integrate_sign_evidence(
        records,
        depths,
        semantics,
        alignments,
        sign_observations,
        output,
        arguments.maximum_dimension,
        job_id=arguments.job_id,
        profile=arguments.profile,
        pipeline_revision=arguments.pipeline_revision,
        configuration_hash=arguments.configuration_hash,
    )
    # infer_semantics() records counts before conservative multi-view paint
    # promotion. Recompute them so provenance and downstream road coverage
    # describe the exact semantic rasters that are fitted and saved.
    updated_class_counts: dict[str, int] = {}
    for semantic in semantics:
        identifiers, counts = np.unique(semantic, return_counts=True)
        for identifier, count in zip(identifiers, counts, strict=True):
            key = str(int(identifier))
            updated_class_counts[key] = updated_class_counts.get(key, 0) + int(count)
    semantic_metrics["pixelCounts"] = updated_class_counts
    semantic_metrics["temporalConsistency"] = temporal_semantic_consistency(
        records,
        depths,
        semantics,
        alignments,
        depth_group_ids,
    )
    fit, road_document = build_road_surface(
        records,
        depths,
        semantics,
        alignments,
        depth_group_ids,
        arguments.data.resolve(),
    )
    road_document.update(
        {
            "jobId": arguments.job_id,
            "profile": arguments.profile,
            "pipelineRevision": arguments.pipeline_revision,
            "configurationHash": arguments.configuration_hash,
        }
    )
    atomic_json(output / "road-surface.json", road_document)
    aligned_depth_outside_float16 = 0
    road_depth_outside_float16 = 0
    for index, (record, relative, semantic, alignment, depth_group_id) in enumerate(
        zip(
            records,
            depths,
            semantics,
            alignments,
            depth_group_ids,
            strict=True,
        )
    ):
        aligned, road_depth = road_surface_depth(
            record,
            relative,
            semantic,
            alignment,
            fit,
            road_document,
            depth_group_id == road_document["sourceSequence"],
        )
        prior_path = output / "depth" / Path(record.name).with_suffix(".npz")
        aligned_storage, aligned_outside = float16_depth_storage(
            aligned,
            invalid_value=float("nan"),
        )
        road_storage, road_outside = float16_depth_storage(
            road_depth,
            invalid_value=0.0,
        )
        aligned_depth_outside_float16 += aligned_outside
        road_depth_outside_float16 += road_outside
        atomic_npz(
            prior_path,
            relative_inverse_depth=relative.astype(np.float16),
            aligned_depth=aligned_storage,
            road_surface_depth=road_storage,
            depth_group_id=np.asarray(depth_group_id),
            depth_group_aligned=np.asarray(alignment is not None, dtype=np.uint8),
        )
        emit("prior_write_progress", completed=index + 1, total=len(records))
    total_pixels = sum(int(value.size) for value in semantics)
    sky_pixels = sum(int(np.count_nonzero(value == 17)) for value in semantics)
    road_pixels = sum(int(np.count_nonzero(np.isin(value, [1, 2, 5]))) for value in semantics)
    floor_pixels = sum(int(np.count_nonzero(value == 25)) for value in semantics)
    dynamic_pixels = sum(int(np.count_nonzero(np.isin(value, [18, 19, 20, 21, 22]))) for value in semantics)
    metrics = {
        "schema": PRIOR_SCHEMA,
        "jobId": arguments.job_id,
        "profile": arguments.profile,
        "pipelineRevision": arguments.pipeline_revision,
        "configurationHash": arguments.configuration_hash,
        "registeredImages": len(records),
        "pipeline": "video-depth-anything-small-plus-oneformer-ade20k-tiny-road-surface-v1",
        "scaleProvenance": "sfm-arbitrary",
        "metric": False,
        "lidar": False,
        "temperature": False,
        "collisionValidated": False,
        "depth": {
            "producer": "DepthAnything/Video-Depth-Anything",
            "sourceCommit": VIDEO_DEPTH_COMMIT,
            "sourceManifestSha256": VIDEO_DEPTH_SOURCE_MANIFEST_SHA256,
            "checkpoint": "Video-Depth-Anything-Small",
            "checkpointSha256": DEPTH_CHECKPOINT_SHA256,
            "license": "Apache-2.0",
            **depth_metrics,
            "alignment": alignment_metrics,
            "storage": {
                "encoding": "float16-explicit-unknown-v1",
                "maximumFiniteValue": float(np.finfo(np.float16).max),
                "alignedDepthOutsideRangePixels": aligned_depth_outside_float16,
                "roadDepthOutsideRangePixels": road_depth_outside_float16,
                "overflowBecomesInfinity": False,
            },
        },
        "semantics": {
            "producer": "shi-labs/oneformer_ade20k_swin_tiny",
            "snapshotRevision": ONEFORMER_SNAPSHOT_REVISION,
            "checkpointSha256": ONEFORMER_CHECKPOINT_SHA256,
            "snapshotFileSha256": ONEFORMER_FILE_SHA256,
            "license": "MIT",
            **semantic_metrics,
            "roadFraction": road_pixels / max(total_pixels, 1),
            "floorFraction": floor_pixels / max(total_pixels, 1),
            "navigableSurfaceFraction": (road_pixels + floor_pixels)
            / max(total_pixels, 1),
            "skyFraction": sky_pixels / max(total_pixels, 1),
            "dynamicFraction": dynamic_pixels / max(total_pixels, 1),
        },
        "roadSurface": {
            **road_document["fit"],
            "model": road_document["surface"]["model"],
            "observedSurface": {
                "model": road_document["observedSurface"]["model"],
                "candidateCellCount": road_document["observedSurface"][
                    "candidateCellCount"
                ],
                "retainedCellCount": road_document["observedSurface"][
                    "retainedCellCount"
                ],
                "componentCount": road_document["observedSurface"][
                    "componentCount"
                ],
                "retainedComponentCount": road_document["observedSurface"][
                    "retainedComponentCount"
                ],
                "anchorCellCount": road_document["observedSurface"][
                    "anchorCellCount"
                ],
                "blockedCellCount": road_document["observedSurface"][
                    "blockedCellCount"
                ],
                "ambiguousCellCount": road_document["observedSurface"][
                    "ambiguousCellCount"
                ],
                "maximumCellP95Residual": road_document["observedSurface"][
                    "maximumCellP95Residual"
                ],
                "p50AbsoluteResidual": road_document["observedSurface"][
                    "p50AbsoluteResidual"
                ],
                "p95AbsoluteResidual": road_document["observedSurface"][
                    "p95AbsoluteResidual"
                ],
                "maxAbsoluteResidual": road_document["observedSurface"][
                    "maxAbsoluteResidual"
                ],
                "inlierRatio": road_document["observedSurface"]["inlierRatio"],
                "iterations": road_document["observedSurface"]["iterations"],
                "converged": road_document["observedSurface"]["converged"],
                "solverPolicy": road_document["observedSurface"]["solverPolicy"],
                "huberScale": road_document["observedSurface"]["huberScale"],
                "huberScaleFrozen": road_document["observedSurface"][
                    "huberScaleFrozen"
                ],
                "huberObjective": road_document["observedSurface"][
                    "huberObjective"
                ],
                "relativeSolutionChange": road_document["observedSurface"][
                    "relativeSolutionChange"
                ],
                "normalizedWeightChange": road_document["observedSurface"][
                    "normalizedWeightChange"
                ],
                "twoCycleSolutionChange": road_document["observedSurface"][
                    "twoCycleSolutionChange"
                ],
                "twoCycleWeightChange": road_document["observedSurface"][
                    "twoCycleWeightChange"
                ],
                "firstOrderOptimality": road_document["observedSurface"][
                    "firstOrderOptimality"
                ],
                "backtrackingSteps": road_document["observedSurface"][
                    "backtrackingSteps"
                ],
                "terminationReason": road_document["observedSurface"][
                    "terminationReason"
                ],
            },
        },
        "elapsedSeconds": time.perf_counter() - started,
        "cuda": {
            "torch": torch.__version__,
            "runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
        },
        "limitations": [
            "Monocular SfM scale is arbitrary without a measured anchor.",
            "Model-inferred depth and semantics are priors, not sensor measurements.",
            "Unobserved space remains unknown and receives no road collision surface.",
            "Broad signboard detections are not verified traffic-sign identities or text.",
        ],
    }
    metrics_path = output / "geometry-metrics.json"
    atomic_json(metrics_path, metrics)
    emit("geometry_priors_completed", metricsPath=str(metrics_path), **metrics)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)
    build_parser = subcommands.add_parser("build")
    build_parser.add_argument("--data", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--video-depth-root", type=Path, required=True)
    build_parser.add_argument("--depth-checkpoint", type=Path, required=True)
    build_parser.add_argument("--oneformer-root", type=Path, required=True)
    build_parser.add_argument("--maximum-dimension", type=int, default=960)
    build_parser.add_argument("--depth-input-size", type=int, default=518)
    build_parser.add_argument("--job-id", required=True)
    build_parser.add_argument("--profile", required=True)
    build_parser.add_argument("--pipeline-revision", required=True)
    build_parser.add_argument("--configuration-hash", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "build":
            return build(arguments)
    except Exception as error:
        emit("geometry_priors_failed", message=str(error))
        raise
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
