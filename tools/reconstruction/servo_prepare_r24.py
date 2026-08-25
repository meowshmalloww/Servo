#!/usr/bin/env python3
"""Create matched, non-overwriting R24 control and PFD configurations."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tmp" / "r17-sky-hybrid-training-config.json"
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


def build(arm: str, seed: int) -> Path:
    if arm not in {"control", "pfd"}:
        raise RuntimeError(f"Unsupported R24 arm: {arm}")
    experiment_id = f"yosemite-r24-{arm}-seed{seed}-1500"
    destination = ROOT / "tmp" / f"r24-{arm}-seed{seed}-1500-config.json"
    output = ROOT / "diagnostics" / experiment_id / "train-1500"
    if destination.exists() or output.exists():
        raise RuntimeError(
            f"Refusing to overwrite R24 artifacts: {destination} or {output}"
        )

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    parent_configuration_hash = config["configurationHash"]
    current_pipeline_hash = pipeline_hash()
    config.update(
        {
            "jobId": experiment_id,
            "profile": f"fidelity-12gb-r24-{arm}-seed{seed}-1500",
            "output": str(output),
            "cancelPath": str(output.parent / "cancel.request"),
            "maxSteps": 1_500,
            "finalFitSteps": 500,
            "coarseSteps": 250,
            "targetGaussians": 750_000,
            "maxGaussians": 1_500_000,
            "refineStartIter": 100,
            "refineEvery": 100,
            "refineScale2dStopIter": 1_000,
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
        }
    )
    for key in (
        "surfelAblation",
        "coverageAwareDensification",
        "dualOpacityInitialization",
        "dualOpacityGeometryRgbWeight",
        "dualOpacityPrunePolicy",
        "dualOpacityResetPolicy",
    ):
        config.pop(key, None)
    if arm == "pfd":
        config["coverageAwareDensification"] = {
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
    config["diagnosticProvenance"] = {
        "schema": "servo.diagnostic-training-provenance/v1",
        "nonPublishable": True,
        "experimentId": experiment_id,
        "parent": "yosemite-r17-sky-l1-plus-tail-bce/train-7000",
        "parentConfigurationHash": parent_configuration_hash,
        "sourceCommit": source_commit(),
        "reconstructionWorkingTreeHash": current_pipeline_hash,
        "purpose": (
            "Matched early-refinement R22-A objective control."
            if arm == "control"
            else "R24 tile-footprint/depth-aware densification-only treatment."
        ),
        "claimLimit": (
            "Diagnostic tile-footprint approximation; not Pixel-GS parity, a "
            "publishable world, or collision/autonomy evidence."
        ),
    }
    config.pop("experimentConfigurationHash", None)
    config["experimentConfigurationHash"] = sha256(canonical(config))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical(config) + b"\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--arms", nargs="+", choices=("control", "pfd"), default=("control", "pfd")
    )
    args = parser.parse_args()
    if not 0 <= args.seed <= 0xFFFFFFFF:
        raise RuntimeError("Seed must be an unsigned 32-bit integer.")
    for arm in args.arms:
        print(build(arm, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
