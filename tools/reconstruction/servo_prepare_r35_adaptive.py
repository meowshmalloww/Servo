#!/usr/bin/env python3
"""Create the non-overwriting R35 VRAM-adaptive long-run configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = (
    ROOT
    / "tmp"
    / "r31-a0-nn-init-seed42-0900.json"
)
PIPELINE_SOURCES = (
    ROOT / "tools" / "reconstruction" / "servo_train.py",
    ROOT / "tools" / "reconstruction" / "servo_colmap.py",
    ROOT / "tools" / "reconstruction" / "servo_gsplat_runtime.py",
)
BUDGET_POLICY = "vram-adaptive-preflight-v1"


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
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_config(*, base: Path, output: Path, steps: int, seed: int) -> dict[str, Any]:
    if steps < 8_000:
        raise RuntimeError("R35 is a long-run diagnostic and requires at least 8,000 steps.")
    config = json.loads(base.read_text(encoding="utf-8"))
    parent_configuration_hash = config["configurationHash"]
    final_fit_steps = 2_000
    if final_fit_steps >= steps // 2:
        raise RuntimeError("R35 must reserve most steps for held-out main fitting.")
    experiment_id = f"yosemite-r35-vram-adaptive-seed{seed}-{steps}"
    config.update(
        {
            "jobId": experiment_id,
            "profile": f"fidelity-12gb-r35-vram-adaptive-{steps}",
            "output": str(output),
            "cancelPath": str(output.parent / "cancel.request"),
            "maxSteps": steps,
            "finalFitSteps": final_fit_steps,
            "coarseSteps": 500,
            "refineStartIter": 500,
            "refineEvery": 100,
            "refineScale2dStopIter": steps - final_fit_steps,
            "checkpointEvery": 1_000,
            "targetGaussians": 0,
            "maxGaussians": 0,
            "gaussianBudgetPolicy": BUDGET_POLICY,
            "maxVramGiB": 11.0,
            "seed": seed,
            "pipelineCodeHash": pipeline_hash(),
        }
    )
    for key in (
        "initialScalePolicy",
        "regionAwareDensification",
        "surfelAblation",
        "dualOpacityInitialization",
        "dualOpacityGeometryRgbWeight",
        "dualOpacityPrunePolicy",
        "dualOpacityResetPolicy",
    ):
        config.pop(key, None)
    config["diagnosticProvenance"] = {
        "schema": "servo.diagnostic-training-provenance/v1",
        "nonPublishable": True,
        "experimentId": experiment_id,
        "parent": str(base.resolve()),
        "parentConfigurationHash": parent_configuration_hash,
        "sourceCommit": source_commit(),
        "reconstructionWorkingTreeHash": config["pipelineCodeHash"],
        "purpose": (
            "Long R17-policy open-source gsplat run with no fixed Gaussian-count "
            "ceiling; growth is preflighted against the measured CUDA budget."
        ),
        "claimLimit": (
            "Diagnostic only until exact-Ply, motion, road, sign, sky, and resource "
            "audits beat preserved R17. Monocular arbitrary scale; not collision ready."
        ),
    }
    config.pop("experimentConfigurationHash", None)
    config["experimentConfigurationHash"] = sha256(canonical(config))
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config-output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=12_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not args.base.is_file():
        raise RuntimeError(f"R17-derived control configuration is missing: {args.base}")
    if args.output_root.exists() or args.config_output.exists():
        raise RuntimeError(
            f"Refusing to overwrite R35 artifacts: {args.output_root} / {args.config_output}"
        )
    config = build_config(
        base=args.base,
        output=args.output_root,
        steps=args.steps,
        seed=args.seed,
    )
    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_bytes(canonical(config) + b"\n")
    print(args.config_output.resolve())
    print(args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
