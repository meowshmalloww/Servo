#!/usr/bin/env python3
"""Create matched, non-overwriting R31 initialization probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = ROOT / "tmp" / "r30-a0-footprint-control-seed42-0750.json"
PIPELINE_SOURCES = (
    ROOT / "tools" / "reconstruction" / "servo_train.py",
    ROOT / "tools" / "reconstruction" / "servo_colmap.py",
    ROOT / "tools" / "reconstruction" / "servo_gsplat_runtime.py",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def pipeline_hash() -> str:
    digest = hashlib.sha256()
    for path in PIPELINE_SOURCES:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def source_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def build_config(
    *,
    base: Path,
    treatment: str,
    calibration_quantile: float,
    steps: int,
    seed: int,
    output: Path,
) -> dict[str, Any]:
    if treatment not in {"control", "projected-footprint"}:
        raise RuntimeError(f"Unsupported R31 treatment: {treatment}")
    if steps not in {900, 1_500}:
        raise RuntimeError(
            "R31 steps must be 900 or 1500; this dataset requires a complete "
            "513-slot main epoch and a 373-camera final-fit pass."
        )
    if treatment == "projected-footprint" and calibration_quantile != 0.90:
        raise RuntimeError("R31 is sealed to a 90th-percentile tail cap.")
    config = json.loads(base.read_text(encoding="utf-8"))
    final_fit_steps = 373 if steps == 900 else 500
    parent_configuration_hash = config["configurationHash"]
    arm = "a0-nn-init" if treatment == "control" else "a1-footprint-tail-p90"
    experiment_id = f"r31-{arm}-seed{seed}-{steps:04d}"
    current_pipeline_hash = pipeline_hash()
    config.update(
        {
            "jobId": experiment_id,
            "profile": f"fidelity-12gb-{experiment_id}",
            "output": str(output),
            "cancelPath": str(output.parent / f"{experiment_id}.cancel.request"),
            "maxSteps": steps,
            "finalFitSteps": final_fit_steps,
            "coarseSteps": 50,
            "targetGaussians": 750_000,
            "maxGaussians": 1_500_000,
            "refineStartIter": 100,
            "refineEvery": 100,
            "refineScale2dStopIter": steps - final_fit_steps,
            "checkpointEvery": 100,
            "maxVramGiB": 11.0,
            "packed": True,
            "absgrad": True,
            "growGrad2d": 0.0008,
            "dualOpacityEnabled": False,
            "crossViewDepthConsistencyWeight": 0.0,
            "surfaceAlignmentWeight": 0.0,
            "roadPlanarityWeight": 0.0,
            "denseGeometryStart": 100,
            "depthLayerVarianceStart": 100,
            "observedDetailStart": 100,
            "surfaceAlignmentStart": 100,
            "seed": seed,
            "pipelineCodeHash": current_pipeline_hash,
        }
    )
    for key in (
        "initialScalePolicy",
        "regionAwareDensification",
        "surfelAblation",
        "semanticPriorityFullConfidenceLabels",
        "frameOversampling",
        "dualOpacityInitialization",
        "dualOpacityGeometryRgbWeight",
        "dualOpacityPrunePolicy",
        "dualOpacityResetPolicy",
    ):
        config.pop(key, None)
    if treatment == "projected-footprint":
        config["initialScalePolicy"] = {
            "schema": "servo.diagnostic-projected-footprint-init/v1",
            "method": "colmap-track-projection-jacobian-tail-cap-v1",
            "calibrationQuantile": calibration_quantile,
            "maximumCappedFraction": 0.11,
            "minimumValidObservations": 3,
            "covariance": "isotropic",
            "generatedEvidence": False,
        }
    config["diagnosticProvenance"] = {
        "schema": "servo.diagnostic-training-provenance/v1",
        "nonPublishable": True,
        "experimentId": experiment_id,
        "parent": str(base),
        "parentConfigurationHash": parent_configuration_hash,
        "sourceCommit": source_commit(),
        "reconstructionWorkingTreeHash": current_pipeline_hash,
        "purpose": (
            "Matched R31-A0 nearest-neighbor initialization control."
            if treatment == "control"
            else "R31-A1 calibrated track-footprint isotropic scale-cap treatment."
        ),
        "claimLimit": (
            "Nonpublishable diagnostic only; arbitrary SfM scale, no generated "
            "views, metric geometry, collision readiness, or Pixel-GS parity claim."
        ),
    }
    config.pop("experimentConfigurationHash", None)
    config["experimentConfigurationHash"] = sha256(canonical(config))
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument(
        "--treatment",
        choices=("control", "projected-footprint"),
        required=True,
    )
    parser.add_argument("--calibration-quantile", type=float, default=0.90)
    parser.add_argument("--steps", type=int, default=900)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config-output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.seed <= 0xFFFFFFFF:
        raise RuntimeError("Seed must be an unsigned 32-bit integer.")
    if not args.base.is_file():
        raise RuntimeError(f"R31 base configuration does not exist: {args.base}")
    if args.config_output.exists() or args.output_root.exists():
        raise RuntimeError(
            "Refusing to overwrite R31 configuration or output: "
            f"{args.config_output} / {args.output_root}"
        )
    config = build_config(
        base=args.base,
        treatment=args.treatment,
        calibration_quantile=args.calibration_quantile,
        steps=args.steps,
        seed=args.seed,
        output=args.output_root,
    )
    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_bytes(canonical(config) + b"\n")
    print(args.config_output)
    print(args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
