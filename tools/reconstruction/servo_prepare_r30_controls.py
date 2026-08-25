#!/usr/bin/env python3
"""Create matched, non-overwriting R30 topology-allocation probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = ROOT / "tmp" / "r28-current-confidence-v4-control-1500-config.json"
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


def coverage_treatment() -> dict[str, Any]:
    return {
        "schema": "servo.diagnostic-coverage-densification/v1",
        "method": "gsplat-1.5.3-tile-footprint-depth-scaled-v1",
        "footprintSource": "tiles-per-gaussian",
        "maximumFootprintFraction": 0.02,
        "footprintPower": 1.0,
        "depthSource": "camera-space-z",
        "depthScaleFraction": 0.37,
        "depthPower": 2.0,
        "packedRequired": True,
        "surfelAllowed": False,
        "dualOpacityAllowed": False,
        "revisedOpacity": False,
        "lossesChanged": False,
        "opacityPolicyChanged": False,
        "pruningPolicyChanged": False,
    }


def region_treatment() -> dict[str, Any]:
    return {
        "schema": "servo.diagnostic-region-aware-densification/v1",
        "method": "gsplat-1.5.3-absgrad-tile-footprint-semantic-detail-v1",
        "maximumFootprintFraction": 0.02,
        "depthScaleFraction": 0.37,
        "depthPower": 2.0,
        "minimumStaticConfidence": 0.50,
        "minimumStaticFootprintFraction": 0.50,
        "minimumObservedViewsForBoost": 3,
        "semanticWeights": {
            "unknown": 0.0,
            "sky": 0.0,
            "dynamic": 0.0,
            "vegetation": 0.5,
            "water": 0.5,
            "rigidStatic": 1.0,
            "road": 1.15,
            "boundary": 1.75,
            "roadMarking": 2.5,
            "sign": 3.0,
        },
        "edgeBase": 0.50,
        "edgeScale": 0.08,
        "edgeMaximum": 1.50,
        "residualBase": 0.50,
        "residualScale": 0.15,
        "residualMaximum": 1.50,
        "priorityMinimum": 0.75,
        "priorityMaximum": 3.0,
        "lossesChanged": False,
        "opacityPolicyChanged": False,
        "pruningPolicyChanged": False,
        "generatedViewsUsed": False,
    }


def build_config(
    *,
    base: Path,
    treatment: str,
    steps: int,
    seed: int,
    output: Path,
) -> dict[str, Any]:
    if treatment not in {"footprint-control", "region-aware"}:
        raise RuntimeError(f"Unsupported R30 treatment: {treatment}")
    if steps not in {300, 750, 1_500}:
        raise RuntimeError("R30 steps must be one of 300, 750, or 1500.")
    config = json.loads(base.read_text(encoding="utf-8"))
    parent_configuration_hash = config["configurationHash"]
    experiment_id = f"r30-{'a0' if treatment == 'footprint-control' else 'a1'}-{treatment}-seed{seed}-{steps:04d}"
    current_pipeline_hash = pipeline_hash()
    config.update(
        {
            "jobId": experiment_id,
            "profile": f"fidelity-12gb-{experiment_id}",
            "output": str(output),
            "cancelPath": str(output.parent / f"{experiment_id}.cancel.request"),
            "maxSteps": steps,
            # Preserve two 100-step topology decisions in the 300-step probe,
            # then reserve a small, valid held-out/final-fit phase.
            "finalFitSteps": 50 if steps == 300 else min(250, steps // 3),
            "coarseSteps": min(50, max(1, steps // 6)),
            "targetGaussians": 300_000 if steps == 300 else 750_000,
            "maxGaussians": 600_000 if steps == 300 else 1_500_000,
            "refineStartIter": 100,
            "refineEvery": 100,
            "refineScale2dStopIter": (
                steps - (50 if steps == 300 else min(250, steps // 3))
            ),
            "checkpointEvery": 100,
            "maxVramGiB": 11.0,
            "packed": True,
            "absgrad": True,
            "growGrad2d": 0.0008,
            "dualOpacityEnabled": False,
            "crossViewDepthConsistencyWeight": 0.0,
            "surfaceAlignmentWeight": 0.0,
            "roadPlanarityWeight": 0.0,
            "seed": seed,
            "pipelineCodeHash": current_pipeline_hash,
            "coverageAwareDensification": coverage_treatment(),
        }
    )
    for key in (
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
    if treatment == "region-aware":
        config["regionAwareDensification"] = region_treatment()
    config["diagnosticProvenance"] = {
        "schema": "servo.diagnostic-training-provenance/v1",
        "nonPublishable": True,
        "experimentId": experiment_id,
        "parent": str(base),
        "parentConfigurationHash": parent_configuration_hash,
        "sourceCommit": source_commit(),
        "reconstructionWorkingTreeHash": current_pipeline_hash,
        "purpose": (
            "Matched footprint/depth-only R30-A0 topology control."
            if treatment == "footprint-control"
            else "R30-A1 region/detail-aware topology allocation treatment."
        ),
        "claimLimit": (
            "Nonpublishable diagnostic only; no generated views, metric geometry, "
            "collision readiness, or Pixel-GS parity claim."
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
        choices=("footprint-control", "region-aware"),
        required=True,
    )
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config-output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.seed <= 0xFFFFFFFF:
        raise RuntimeError("Seed must be an unsigned 32-bit integer.")
    if not args.base.is_file():
        raise RuntimeError(f"R30 base configuration does not exist: {args.base}")
    if args.config_output.exists() or args.output_root.exists():
        raise RuntimeError(
            "Refusing to overwrite R30 configuration or output: "
            f"{args.config_output} / {args.output_root}"
        )
    config = build_config(
        base=args.base,
        treatment=args.treatment,
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
