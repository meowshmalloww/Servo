#!/usr/bin/env python3
"""Prepare a fresh, bounded Servo 3DGS fit over a HorizonStream camera dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pipeline_hash() -> str:
    digest = hashlib.sha256()
    for name in ("servo_train.py", "servo_colmap.py", "servo_gsplat_runtime.py"):
        path = Path(__file__).with_name(name)
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1500)
    parser.add_argument("--final-fit-steps", type=int, default=240)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--experiment-id", default="yosemite-t1a-horizon-rgb-3dgs-120")
    parser.add_argument("--pipeline-revision", default="t1a-horizonstream-rgb-3dgs-v1")
    parser.add_argument("--adaptive-budget", action="store_true")
    parser.add_argument("--target-gaussians", type=int, default=1_000_000)
    parser.add_argument("--max-gaussians", type=int, default=3_000_000)
    parser.add_argument("--checkpoint-every", type=int, default=300)
    parser.add_argument("--direct-footprint-radius", type=float)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to reuse output: {args.output}")
    if args.config_output.exists():
        raise FileExistsError(f"Refusing to overwrite config: {args.config_output}")
    receipt = args.dataset / "horizonstream-3dgs-dataset-receipt.json"
    if not receipt.is_file():
        raise FileNotFoundError(receipt)
    config = json.loads(args.base.read_text(encoding="utf-8"))
    dataset_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    evidence_root = Path(dataset_receipt["source"]["horizonOutput"])
    da3_receipt = evidence_root / "da3-depth-sequence-receipt.json"
    if args.pipeline_revision.startswith("t2-") and not da3_receipt.is_file():
        raise FileNotFoundError(
            "T2 configuration requires the hash-bound DA3 depth-sequence receipt."
        )
    for key in (
        "geometryRoot", "geometryPriorsMetricsSha256", "geometryPriorsSchema",
        "certifiedSkyEvidence", "initialScalePolicy", "frameOversampling",
        "appearanceFrameSelection", "coverageAwareDensification",
        "regionAwareDensification", "experimentConfigurationHash",
        "recoveryPolicy", "observedDirectionalEnvironment",
    ):
        config.pop(key, None)
    config.update(
        {
            "data": str(args.dataset.resolve()),
            "dataFactor": 1,
            "output": str(args.output.resolve()),
            "cancelPath": str((args.output / "cancel.request").resolve()),
            "jobId": args.experiment_id,
            "profile": (
                "da3-depth-seeded-full-resolution-rgb-3dgs"
                if args.pipeline_revision.startswith("t2-")
                else "horizonstream-geometry-seeded-rgb-3dgs"
            ),
            "pipelineRevision": args.pipeline_revision,
            "configurationHash": _sha256(receipt),
            "trainingInputHash": _sha256(receipt),
            "pipelineCodeHash": _pipeline_hash(),
            "seed": args.seed,
            "maxSteps": args.steps,
            "finalFitSteps": args.final_fit_steps,
            "refineScale2dStopIter": args.steps - args.final_fit_steps,
            "coarseSteps": min(200, max(0, args.steps - args.final_fit_steps - 1)),
            "checkpointEvery": args.checkpoint_every,
            "targetGaussians": 0 if args.adaptive_budget else args.target_gaussians,
            "maxGaussians": 0 if args.adaptive_budget else args.max_gaussians,
            "gaussianBudgetPolicy": (
                "vram-adaptive-preflight-v1" if args.adaptive_budget else "fixed-count-v1"
            ),
            "maxVramGiB": 11.0,
            "geometryPriors": False,
            "dualOpacityEnabled": False,
            "crossViewDepthConsistencyWeight": 0.0,
            "sparseDepthWeight": 0.0,
            "depthLayerVarianceWeight": 0.0,
            "drivingSurfaceVarianceWeight": 0.0,
            "surfaceAlignmentWeight": 0.0,
            "roadPlanarityWeight": 0.0,
            "denseRelativeDepthWeight": 0.0,
            "roadSurfaceDepthWeight": 0.0,
            "semanticSkyOpacityWeight": 0.0,
            "semanticSkyOpacityMethod": "",
            "semanticSkyOpacityTailWeight": 0.0,
            "contributorSkyCleanup": False,
            "backgroundSource": "fixed-observed-sky-mean-srgb-v1",
            "observedDetailWeight": 0.0,
            "semanticPriorityFullConfidenceLabels": [],
            "semanticPhotometricMaskMethod": "servo-oneformer-rigid-static-temporal-floor-preserved-nonrigid-v4",
            "semanticRigidStaticConfidenceFloor": 0.25,
            "semanticVegetationConfidenceFloor": 0.0,
            "semanticWaterConfidenceFloor": 0.0,
            "diagnosticProvenance": {
                "schema": "servo.diagnostic-training-provenance/v1",
                "nonPublishable": True,
                "experimentId": args.experiment_id,
                "purpose": (
                    "Full-resolution RGB 3DGS appearance fit; confidence-filtered "
                    "DA3 depth is initialization evidence only"
                    if args.pipeline_revision.startswith("t2-")
                    else "RGB 3DGS appearance fit; HorizonStream points are initialization only"
                ),
                "pointCloudIsPresentationWorld": False,
                "metricScaleValidated": False,
                "collisionValidated": False,
            },
        }
    )
    if da3_receipt.is_file():
        config["diagnosticProvenance"]["geometryEvidenceReceipt"] = str(
            da3_receipt.resolve()
        )
        config["diagnosticProvenance"]["geometryEvidenceReceiptSha256"] = _sha256(
            da3_receipt
        )
    if args.direct_footprint_radius is not None:
        if not args.pipeline_revision.startswith("t2-da3-"):
            raise RuntimeError("Direct footprint initialization is sealed to T2 DA3 diagnostics.")
        if args.direct_footprint_radius != 1.75:
            raise RuntimeError("The T2 direct footprint diagnostic is sealed to 1.75 pixels.")
        config["initialScalePolicy"] = {
            "schema": "servo.da3-projected-footprint-init/v1",
            "method": "colmap-track-projection-jacobian-direct-cap-v1",
            "targetRadiusPixels": 1.75,
            "maximumCappedFraction": 1.0,
            "minimumValidObservations": 3,
            "covariance": "isotropic",
            "generatedEvidence": False,
        }
    config["experimentConfigurationHash"] = "sha256:" + hashlib.sha256(_canonical(config)).hexdigest()
    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(args.config_output), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
