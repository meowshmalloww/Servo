#!/usr/bin/env python3
"""Compare two exact-Ply audits before promoting an alternative reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _metric(document: dict[str, Any], name: str) -> float:
    appearance = document.get("appearance")
    if not isinstance(appearance, dict) or not isinstance(appearance.get(name), (int, float)):
        raise ValueError(f"Audit is missing appearance.{name}.")
    return float(appearance[name])


def _optional_metric(document: dict[str, Any], name: str) -> float | None:
    appearance = document.get("appearance")
    if not isinstance(appearance, dict):
        return None
    value = appearance.get(name)
    return float(value) if isinstance(value, (int, float)) else None


def compare(control: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, float] = {
        name: _metric(candidate, name) - _metric(control, name)
        for name in ("registeredPsnrMean", "registeredSsimMean")
    }
    heldout_available = True
    for name in ("heldoutPsnrMean", "heldoutSsimMean"):
        control_value = _optional_metric(control, name)
        candidate_value = _optional_metric(candidate, name)
        if control_value is None or candidate_value is None:
            heldout_available = False
            continue
        metrics[name] = candidate_value - control_value

    for name in ("registeredPsnrP10", "registeredSsimP10"):
        control_value = _optional_metric(control, name)
        candidate_value = _optional_metric(candidate, name)
        if control_value is not None and candidate_value is not None:
            metrics[name] = candidate_value - control_value
    # An external trainer must produce a visible, repeatable gain. Tiny metric
    # movement does not justify replacing Servo's known demo world.
    registered_passed = (
        metrics["registeredPsnrMean"] >= 0.50
        and metrics["registeredSsimMean"] >= 0.01
    )
    heldout_passed = (
        not heldout_available
        or (
            metrics["heldoutPsnrMean"] >= 0.20
            and metrics["heldoutSsimMean"] >= 0.005
        )
    )
    worst_view_passed = (
        metrics.get("registeredPsnrP10", 0.0) >= -0.20
        and metrics.get("registeredSsimP10", 0.0) >= -0.01
    )
    passed = registered_passed and heldout_passed and worst_view_passed
    return {
        "schema": "servo.external-reconstruction-comparison/v1",
        "decision": "candidate-beats-control" if passed else "keep-control",
        "passed": passed,
        "heldoutCompared": heldout_available,
        "deltas": metrics,
        "meaning": (
            "Appearance-only exact-Ply comparison. This does not validate metric geometry, "
            "free space, collision, or unobserved viewpoints."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite {args.output}")
    control = json.loads(args.control.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = compare(control, candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
