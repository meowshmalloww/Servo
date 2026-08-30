#!/usr/bin/env python3
"""Audit a HorizonStream output before it may seed Servo geometry."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from plyfile import PlyData


SCHEMA = "servo.horizonstream-geometry-audit/v1"


def percentile(values: np.ndarray, q: float) -> float | None:
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, q)) if finite.size else None


def load_rows(path: Path, columns: int) -> np.ndarray:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [float(value) for value in line.split()]
        if len(fields) != columns:
            raise RuntimeError(f"Malformed row in {path}: expected {columns} fields.")
        rows.append(fields)
    if not rows:
        raise RuntimeError(f"No data rows in {path}.")
    return np.asarray(rows, dtype=np.float64)


def pose_metrics(sequence: Path) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    pose_rows = load_rows(sequence / "poses" / "abs_pose.txt", 13)
    intri_rows = load_rows(sequence / "poses" / "intri.txt", 5)
    if pose_rows.shape[0] != intri_rows.shape[0]:
        raise RuntimeError("Pose and intrinsic frame counts differ.")
    rotations = pose_rows[:, 1:10].reshape(-1, 3, 3)
    translations = pose_rows[:, 10:13]
    w2c = np.concatenate([rotations, translations[:, :, None]], axis=2)
    centers = -np.einsum("nij,nj->ni", rotations.transpose(0, 2, 1), translations)
    steps = np.linalg.norm(np.diff(centers, axis=0), axis=1)
    relative = np.einsum(
        "nij,nkj->nik", rotations[1:], rotations[:-1]
    )
    cosines = np.clip((np.trace(relative, axis1=1, axis2=2) - 1.0) * 0.5, -1.0, 1.0)
    rotation_degrees = np.degrees(np.arccos(cosines))
    determinant_error = np.abs(np.linalg.det(rotations) - 1.0)
    orthogonal_error = np.linalg.norm(
        np.einsum("nij,nkj->nik", rotations, rotations) - np.eye(3)[None],
        axis=(1, 2),
    )
    step_median = percentile(steps, 50) or 0.0
    return (
        {
            "frames": int(w2c.shape[0]),
            "finite": bool(np.isfinite(w2c).all() and np.isfinite(intri_rows).all()),
            "rotationDeterminantErrorMax": float(determinant_error.max()),
            "rotationOrthogonalityErrorMax": float(orthogonal_error.max()),
            "translationStepP50": percentile(steps, 50),
            "translationStepP95": percentile(steps, 95),
            "translationStepP99": percentile(steps, 99),
            "translationStepMax": float(steps.max()),
            "translationStepP99OverP50": (
                float((percentile(steps, 99) or math.inf) / step_median)
                if step_median > 0
                else None
            ),
            "rotationStepDegreesP50": percentile(rotation_degrees, 50),
            "rotationStepDegreesP95": percentile(rotation_degrees, 95),
            "rotationStepDegreesP99": percentile(rotation_degrees, 99),
            "rotationStepDegreesMax": float(rotation_degrees.max()),
            "trajectoryExtent": np.ptp(centers, axis=0).tolist(),
        },
        w2c,
        intri_rows[:, 1:],
    )


def depth_metrics(sequence: Path, w2c: np.ndarray, intrinsics: np.ndarray) -> dict[str, Any]:
    depth_files = sorted((sequence / "depth" / "dpt").glob("*.npy"))
    confidence_files = sorted((sequence / "depth" / "conf").glob("*.npy"))
    if len(depth_files) != w2c.shape[0] or len(confidence_files) != w2c.shape[0]:
        raise RuntimeError("Depth/confidence counts do not match pose count.")
    depths = [np.asarray(np.load(path), dtype=np.float64).squeeze() for path in depth_files]
    confidences = [
        np.asarray(np.load(path), dtype=np.float64).squeeze()
        for path in confidence_files
    ]
    if any(depth.shape != depths[0].shape for depth in depths):
        raise RuntimeError("Depth map dimensions are inconsistent.")
    sampled_depth = np.concatenate([depth[::4, ::4].ravel() for depth in depths])
    sampled_conf = np.concatenate([conf[::4, ::4].ravel() for conf in confidences])
    reprojection_errors: list[np.ndarray] = []
    for index in range(len(depths) - 1):
        source = depths[index]
        target = depths[index + 1]
        source_conf = confidences[index]
        target_conf = confidences[index + 1]
        height, width = source.shape
        ys, xs = np.mgrid[0:height:8, 0:width:8]
        z = source[ys, xs]
        conf_cut = np.percentile(source_conf[np.isfinite(source_conf)], 50)
        valid = np.isfinite(z) & (z > 0) & (source_conf[ys, xs] >= conf_cut)
        fx, fy, cx, cy = intrinsics[index]
        source_points = np.stack(
            [
                (xs - cx) * z / fx,
                (ys - cy) * z / fy,
                z,
            ],
            axis=-1,
        )[valid]
        world = (w2c[index, :, :3].T @ (source_points - w2c[index, :, 3]).T).T
        target_points = (w2c[index + 1, :, :3] @ world.T).T + w2c[index + 1, :, 3]
        target_z = target_points[:, 2]
        tfx, tfy, tcx, tcy = intrinsics[index + 1]
        u = np.rint(tfx * target_points[:, 0] / target_z + tcx).astype(np.int64)
        v = np.rint(tfy * target_points[:, 1] / target_z + tcy).astype(np.int64)
        inside = (
            np.isfinite(target_z)
            & (target_z > 0)
            & (u >= 0)
            & (u < width)
            & (v >= 0)
            & (v < height)
        )
        if not np.any(inside):
            continue
        u = u[inside]
        v = v[inside]
        projected_z = target_z[inside]
        observed_z = target[v, u]
        target_cut = np.percentile(target_conf[np.isfinite(target_conf)], 50)
        trusted = (
            np.isfinite(observed_z)
            & (observed_z > 0)
            & (target_conf[v, u] >= target_cut)
        )
        if np.any(trusted):
            reprojection_errors.append(
                np.abs(np.log(projected_z[trusted] / observed_z[trusted]))
            )
    errors = (
        np.concatenate(reprojection_errors)
        if reprojection_errors
        else np.empty((0,), dtype=np.float64)
    )
    return {
        "frames": len(depths),
        "shape": list(depths[0].shape),
        "finiteDepthFraction": float(np.mean(np.isfinite(sampled_depth))),
        "positiveDepthFraction": float(np.mean(sampled_depth > 0)),
        "depthP01": percentile(sampled_depth, 1),
        "depthP50": percentile(sampled_depth, 50),
        "depthP99": percentile(sampled_depth, 99),
        "finiteConfidenceFraction": float(np.mean(np.isfinite(sampled_conf))),
        "confidenceP10": percentile(sampled_conf, 10),
        "confidenceP50": percentile(sampled_conf, 50),
        "confidenceP90": percentile(sampled_conf, 90),
        "adjacentHighConfidenceReprojectionSamples": int(errors.size),
        "adjacentLogDepthErrorP50": percentile(errors, 50),
        "adjacentLogDepthErrorP95": percentile(errors, 95),
        "adjacentWithin10PercentFraction": float(np.mean(errors <= math.log(1.10)))
        if errors.size
        else None,
    }


def point_metrics(sequence: Path) -> dict[str, Any]:
    path = sequence / "points" / "full.ply"
    data = PlyData.read(str(path))["vertex"].data
    xyz = np.column_stack([data[name] for name in ("x", "y", "z")]).astype(np.float64)
    finite = np.isfinite(xyz).all(axis=1)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "points": int(xyz.shape[0]),
        "finiteFraction": float(np.mean(finite)),
        "boundsMinimum": np.min(xyz[finite], axis=0).tolist(),
        "boundsMaximum": np.max(xyz[finite], axis=0).tolist(),
    }


def write_preview(sequence: Path, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = PlyData.read(str(sequence / "points" / "full.ply"))["vertex"].data
    xyz = np.column_stack([data[name] for name in ("x", "y", "z")]).astype(np.float64)
    names = set(data.dtype.names or ())
    rgb = (
        np.column_stack([data[name] for name in ("red", "green", "blue")]).astype(np.float64)
        / 255.0
        if {"red", "green", "blue"}.issubset(names)
        else np.full((xyz.shape[0], 3), 0.45)
    )
    finite = np.isfinite(xyz).all(axis=1)
    xyz = xyz[finite]
    rgb = rgb[finite]
    rng = np.random.default_rng(42)
    if xyz.shape[0] > 160_000:
        indices = rng.choice(xyz.shape[0], 160_000, replace=False)
        xyz = xyz[indices]
        rgb = rgb[indices]
    pose_rows = load_rows(sequence / "poses" / "abs_pose.txt", 13)
    rotations = pose_rows[:, 1:10].reshape(-1, 3, 3)
    translations = pose_rows[:, 10:13]
    centers = -np.einsum("nij,nj->ni", rotations.transpose(0, 2, 1), translations)

    figure, axes = plt.subplots(1, 3, figsize=(18, 6), dpi=140)
    for axis, first, second, title in (
        (axes[0], 0, 2, "X/Z"),
        (axes[1], 0, 1, "X/Y"),
        (axes[2], 2, 1, "Z/Y"),
    ):
        axis.scatter(xyz[:, first], xyz[:, second], c=rgb, s=0.12, alpha=0.35, linewidths=0)
        axis.plot(centers[:, first], centers[:, second], color="#ff365f", linewidth=1.6)
        axis.scatter(
            centers[0, first], centers[0, second], color="#00e5ff", s=22, label="start"
        )
        axis.scatter(
            centers[-1, first], centers[-1, second], color="#ffd166", s=22, label="end"
        )
        axis.set_title(title)
        axis.set_aspect("equal", adjustable="datalim")
        axis.grid(alpha=0.2)
    axes[0].legend(loc="best")
    figure.suptitle("HorizonStream T1 geometry preview — sampled points + camera path")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)


def audit(sequence: Path) -> dict[str, Any]:
    sequence = sequence.resolve()
    poses, w2c, intrinsics = pose_metrics(sequence)
    depth = depth_metrics(sequence, w2c, intrinsics)
    points = point_metrics(sequence)
    automatic_checks = {
        "poseFinite": poses["finite"],
        "rotationValid": poses["rotationDeterminantErrorMax"] <= 1e-3
        and poses["rotationOrthogonalityErrorMax"] <= 1e-3,
        "noLargeTranslationSpike": poses["translationStepP99OverP50"] is not None
        and poses["translationStepP99OverP50"] <= 5.0,
        "depthFinite": depth["finiteDepthFraction"] == 1.0
        and depth["positiveDepthFraction"] == 1.0,
        "pointCloudFinite": points["finiteFraction"] == 1.0,
        "adjacentDepthP50": depth["adjacentLogDepthErrorP50"] is not None
        and depth["adjacentLogDepthErrorP50"] <= math.log(1.10),
        "adjacentDepthP95": depth["adjacentLogDepthErrorP95"] is not None
        and depth["adjacentLogDepthErrorP95"] <= math.log(1.50),
    }
    return {
        "schema": SCHEMA,
        "sequence": str(sequence),
        "poses": poses,
        "depth": depth,
        "pointCloud": points,
        "automaticChecks": automatic_checks,
        "automaticPass": all(automatic_checks.values()),
        "visualFloatingLayerInspectionRequired": True,
        "metricScaleValidated": False,
        "collisionValidated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise RuntimeError(f"Refusing to overwrite output: {arguments.output}")
    result = audit(arguments.sequence)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if arguments.preview is not None:
        if arguments.preview.exists():
            raise RuntimeError(f"Refusing to overwrite preview: {arguments.preview}")
        write_preview(arguments.sequence.resolve(), arguments.preview.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["automaticPass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
