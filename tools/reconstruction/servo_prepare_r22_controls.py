#!/usr/bin/env python3
"""Create matched, non-overwriting R22 controls from the preserved R17 policy."""

from __future__ import annotations

import hashlib
import json
import argparse
import re
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


def build(
    seed: int,
    series: str = "r22-a-control",
    treatment: str = "control",
) -> Path:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", series) is None:
        raise RuntimeError("The experiment series must be a lowercase safe slug.")
    experiment_id = f"yosemite-{series}-seed{seed}-1500"
    destination = ROOT / "tmp" / f"{series}-seed{seed}-1500-config.json"
    output = ROOT / "diagnostics" / experiment_id / "train-1500"
    if destination.exists() or output.exists():
        raise RuntimeError(
            f"Refusing to overwrite the R22 control for seed {seed}: "
            f"{destination} or {output} already exists."
        )

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    parent_configuration_hash = config["configurationHash"]
    current_pipeline_hash = pipeline_hash()
    config.update(
        {
            "jobId": experiment_id,
            "profile": f"fidelity-12gb-{series}-seed{seed}-1500",
            "output": str(output),
            "cancelPath": str(output.parent / "cancel.request"),
            "maxSteps": 1_500,
            "finalFitSteps": 500,
            "coarseSteps": 250,
            "targetGaussians": 750_000,
            "maxGaussians": 1_500_000,
            "refineScale2dStopIter": 1_000,
            "checkpointEvery": 500,
            "maxVramGiB": 11.0,
            "dualOpacityEnabled": False,
            "crossViewDepthConsistencyWeight": 0.0,
            "surfaceAlignmentWeight": 0.0,
            "roadPlanarityWeight": 0.0,
            "seed": seed,
            "pipelineCodeHash": current_pipeline_hash,
        }
    )
    if treatment == "surfel":
        config["surfelAblation"] = {
            "schema": "servo.diagnostic-surfel-ablation/v1",
            "method": "gsplat-1.5.3-rasterization-2dgs-surfel-v1",
            "depthDistortionWeight": 0.001,
            "normalConsistencyWeight": 0.01,
            "normalConsistencyStart": 600,
        }
    elif treatment == "sparse-track":
        config.update(
            {
                "crossViewDepthMode": (
                    "sparse-colmap-shared-track-camera-z-v1"
                ),
                "crossViewDepthConsistencyWeight": 0.005,
                "crossViewDepthConsistencyStart": 250,
                "crossViewDepthConsistencyEvery": 4,
                "crossViewMinimumValidTracksPerStep": 64,
            }
        )
    elif treatment != "control":
        raise RuntimeError(f"Unsupported R22 treatment: {treatment}")
    config["diagnosticProvenance"] = {
        "schema": "servo.diagnostic-training-provenance/v1",
        "nonPublishable": True,
        "experimentId": experiment_id,
        "parent": "yosemite-r17-sky-l1-plus-tail-bce/train-7000",
        "parentConfigurationHash": parent_configuration_hash,
        "sourceCommit": source_commit(),
        "reconstructionWorkingTreeHash": current_pipeline_hash,
        "purpose": (
            "Matched 1500-step gsplat 2DGS/surfel geometry diagnostic."
            if treatment == "surfel"
            else (
                "Matched 1500-step COLMAP shared-track camera-Z diagnostic."
                if treatment == "sparse-track"
                else "Matched 1500-step R17-policy short-run control."
            )
        ),
        "claimLimit": (
            "Short-run variance and treatment comparison only; not a "
            "publishable world or collision/autonomy result."
        ),
    }
    config.pop("experimentConfigurationHash", None)
    config["experimentConfigurationHash"] = sha256(canonical(config))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical(config) + b"\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create provenance-bound matched R22 control configurations."
    )
    parser.add_argument("--series", default="r22-a-control")
    parser.add_argument("--seeds", nargs="+", type=int, default=(42, 43))
    parser.add_argument(
        "--treatment",
        choices=("control", "surfel", "sparse-track"),
        default="control",
    )
    args = parser.parse_args()
    for seed in args.seeds:
        if not 0 <= seed <= 0xFFFFFFFF:
            raise RuntimeError("Seeds must be unsigned 32-bit integers.")
        print(build(seed, args.series, args.treatment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
