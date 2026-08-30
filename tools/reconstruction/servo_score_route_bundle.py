#!/usr/bin/env python3
"""Score a tiled appearance route without disguising structural failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _minimum(documents: list[dict[str, Any]], section: str, metric: str) -> float:
    return min(float(document[section][metric]) for document in documents)


def _mean(documents: list[dict[str, Any]], section: str, metric: str) -> float:
    values = [float(document[section][metric]) for document in documents]
    return sum(values) / len(values)


def _nav_min(documents: list[dict[str, Any]], group: str) -> float:
    return min(
        float(document["navigationStress"][group]["supportMinimum"])
        for document in documents
    )


def score(route: dict[str, Any], audits: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = [str(tile["tileId"]) for tile in route["tiles"]]
    if set(expected) != set(audits):
        raise ValueError("audit tile IDs do not exactly match the route receipt")
    documents = [audits[tile_id] for tile_id in expected]
    values = {
        "fullRouteCovered": bool(route.get("fullRouteCovered")),
        "minimumRegisteredPsnrMean": _minimum(documents, "appearance", "registeredPsnrMean"),
        "minimumRegisteredPsnrP10": _minimum(documents, "appearance", "registeredPsnrP10"),
        "meanRegisteredSsim": _mean(documents, "appearance", "registeredSsimMean"),
        "minimumRegisteredSsimP10": _minimum(documents, "appearance", "registeredSsimP10"),
        "minimumOverallSupport": _minimum(documents, "support", "overallMinimum"),
        "minimumLowerHalfSupport": _minimum(documents, "support", "lowerHalfMinimum"),
        "minimumLateralSupport": _nav_min(documents, "lateralOffsets"),
        "minimumRotationSupport": _nav_min(documents, "yawPitchPerturbations"),
        "minimumCombinedSupport": _nav_min(documents, "combinedTranslationRotation"),
        "maximumDepthSpreadP50": max(
            float(document["depthAmbiguity"]["relativeStdP50"])
            for document in documents
        ),
        "maximumDepthSpreadP95": max(
            float(document["depthAmbiguity"]["relativeStdP95"])
            for document in documents
        ),
    }
    checks = {
        "full-route-coverage": values["fullRouteCovered"],
        "observed-appearance-mean": values["minimumRegisteredPsnrMean"] >= 24.0,
        "observed-appearance-tail": values["minimumRegisteredPsnrP10"] >= 23.0,
        "structural-similarity-mean": values["meanRegisteredSsim"] >= 0.74,
        "structural-similarity-tail": values["minimumRegisteredSsimP10"] >= 0.65,
        "observed-support": values["minimumOverallSupport"] >= 0.90,
        "road-half-support": values["minimumLowerHalfSupport"] >= 0.95,
        "small-lateral-support": values["minimumLateralSupport"] >= 0.80,
        "small-rotation-support": values["minimumRotationSupport"] >= 0.80,
        "combined-small-motion-support": values["minimumCombinedSupport"] >= 0.80,
        "depth-layer-spread-median": values["maximumDepthSpreadP50"] <= 0.20,
        "depth-layer-spread-tail": values["maximumDepthSpreadP95"] <= 0.75,
    }
    mandatory = {
        name
        for name in (
            "full-route-coverage",
            "observed-appearance-mean",
            "observed-appearance-tail",
            "observed-support",
            "small-lateral-support",
            "small-rotation-support",
            "combined-small-motion-support",
        )
    }
    passed_count = sum(checks.values())
    visual_pass = passed_count / len(checks) >= 0.75 and all(checks[name] for name in mandatory)
    structural_pass = checks["depth-layer-spread-median"] and checks["depth-layer-spread-tail"]
    return {
        "schema": "servo.route-bundle-validation/v1",
        "decision": "visual-route-pass" if visual_pass else "reject-route",
        "visualRoutePassed": visual_pass,
        "structuralGeometryPassed": structural_pass,
        "collisionValidated": False,
        "passedChecks": passed_count,
        "totalChecks": len(checks),
        "passFraction": passed_count / len(checks),
        "checks": checks,
        "values": values,
        "meaning": (
            "A hackathon appearance-route gate. Passing does not establish metric depth, "
            "collision geometry, free space, or unseen side/rear reconstruction."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, type=Path)
    parser.add_argument(
        "--audit",
        action="append",
        required=True,
        help="TILE_ID=PATH_TO_OBSERVED_PATH_AUDIT_JSON",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    route = json.loads(args.route.read_text(encoding="utf-8"))
    audits: dict[str, dict[str, Any]] = {}
    audit_sources: dict[str, str] = {}
    for value in args.audit:
        tile_id, separator, raw_path = value.partition("=")
        if not separator or not tile_id or tile_id in audits:
            parser.error(f"invalid or duplicate audit binding: {value}")
        path = Path(raw_path).resolve()
        audits[tile_id] = json.loads(path.read_text(encoding="utf-8"))
        audit_sources[tile_id] = f"sha256:{_sha256(path)}"
    result = score(route, audits)
    result["routeReceipt"] = str(args.route.resolve())
    result["auditSha256"] = audit_sources
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["visualRoutePassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
