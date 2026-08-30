"""Deterministic CARLA-driving campaign gates over executed run evidence.

This module deliberately does not simulate outcomes.  It consumes only sealed
``DrivingRunEvidence`` produced by physical simulation workers and creates the
bounded counterfactual/curriculum records needed by the durable orchestrator.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..hashing import canonical_json_bytes, sha256_digest
from ..schemas.driving import DrivingOutcome, DrivingRunEvidence
from ..simulation.session_store import atomic_write_json


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CounterfactualArm(_Strict):
    name: str
    intervention: dict[str, str | int | float | bool]
    required_repetitions: int = Field(ge=1, le=20, default=3)


class DrivingPromotionDecision(_Strict):
    decision: str
    baseline_success_rate: float
    candidate_success_rate: float
    maximum_protected_regression_pp: float
    checks: dict[str, bool]
    candidate_checkpoint_sha256: str
    content_hash: str


def required_counterfactual_arms(repetitions: int = 3) -> tuple[CounterfactualArm, ...]:
    """Return the mandatory executed interventions; these are requests, not results."""

    definitions = (
        ("oracle-reference", {"policy": "carla-behavior-reference"}),
        ("carla-rgb", {"observation_source": "carla-rgb"}),
        ("servo-gaussian", {"observation_source": "servo-gaussian"}),
        ("zero-policy-latency", {"added_policy_latency_ms": 0.0}),
        ("oracle-controller", {"controller": "oracle-trajectory-controller"}),
        ("clear-weather", {"weather": "clear"}),
        ("no-dynamic-actors", {"dynamic_actor_profile": "none"}),
    )
    return tuple(CounterfactualArm(name=name, intervention=value, required_repetitions=repetitions) for name, value in definitions)


def require_policy_valid_evidence(evidence: DrivingRunEvidence) -> None:
    if evidence.infrastructure_invalid or evidence.outcome == DrivingOutcome.INFRASTRUCTURE_INVALID:
        raise ValueError("infrastructure-invalid evidence cannot establish a policy failure")
    if evidence.metrics.frame_count <= 0:
        raise ValueError("policy evidence must contain authoritative simulation frames")


def seal_recovery_curriculum(
    output: Path,
    *,
    established_cause: str,
    training_seeds: list[int],
    hidden_seeds: list[int],
    route_sha256: str,
) -> dict:
    overlap = set(training_seeds) & set(hidden_seeds)
    if overlap:
        raise ValueError(f"hidden seeds leaked into driving curriculum: {sorted(overlap)}")
    payload = {
        "schema_name": "servo.driving-curriculum/v1",
        "established_cause": established_cause,
        "training_seeds": sorted(training_seeds),
        "hidden_seed_receipt": sha256_digest(canonical_json_bytes(sorted(hidden_seeds))),
        "route_sha256": route_sha256,
        "stages": [
            {"name": "centerline-baseline", "lateral_offset_m": 0.0, "heading_offset_deg": 0.0},
            {"name": "lateral-recovery", "lateral_offset_m": 0.75, "heading_offset_deg": 0.0},
            {"name": "heading-recovery", "lateral_offset_m": 0.25, "heading_offset_deg": 8.0},
        ],
    }
    payload["content_hash"] = sha256_digest(canonical_json_bytes(payload))
    atomic_write_json(output, payload)
    return payload


def deterministic_promotion_decision(
    baseline_hidden: list[DrivingRunEvidence],
    candidate_hidden: list[DrivingRunEvidence],
    protected_pairs: list[tuple[DrivingRunEvidence, DrivingRunEvidence]],
    *,
    target_success_rate: float,
    maximum_regression_pp: float,
) -> DrivingPromotionDecision:
    if not baseline_hidden or len(baseline_hidden) != len(candidate_hidden):
        raise ValueError("baseline and candidate hidden evidence must be non-empty and paired")
    for evidence in (*baseline_hidden, *candidate_hidden, *(item for pair in protected_pairs for item in pair)):
        require_policy_valid_evidence(evidence)
    candidate_hashes = {evidence.policy.checkpoint_sha256 for evidence in candidate_hidden}
    if len(candidate_hashes) != 1 or None in candidate_hashes:
        raise ValueError("hidden candidate runs must use one explicit checkpoint identity")
    success = lambda values: sum(e.outcome == DrivingOutcome.SUCCESS for e in values) / len(values)
    baseline_rate, candidate_rate = success(baseline_hidden), success(candidate_hidden)
    regressions = [(success([before]) - success([after])) * 100.0 for before, after in protected_pairs]
    maximum_regression = max(regressions, default=0.0)
    checks = {
        "target-success": candidate_rate >= target_success_rate,
        "improves-baseline": candidate_rate > baseline_rate,
        "protected-regression": maximum_regression <= maximum_regression_pp,
        "checkpoint-identity": next(iter(candidate_hashes)) != baseline_hidden[0].policy.checkpoint_sha256,
    }
    base = {
        "decision": "promoted" if all(checks.values()) else "rejected",
        "baseline_success_rate": baseline_rate,
        "candidate_success_rate": candidate_rate,
        "maximum_protected_regression_pp": maximum_regression,
        "checks": checks,
        "candidate_checkpoint_sha256": next(iter(candidate_hashes)),
    }
    return DrivingPromotionDecision(**base, content_hash=sha256_digest(canonical_json_bytes(base)))
