"""Capability memory and Reality Debt accounting.

Debt is a reproducible weighted score over capability states — never an
LLM opinion.  The next-weakness selector picks deterministically among
eligible capabilities; a ranking model may reorder but never invent or
force candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..schemas.base import verify_seal
from ..schemas.capability import (
    CapabilityDebtContribution,
    CapabilityRecord,
    CapabilityState,
    DebtFormula,
    RealityDebtSnapshot,
)
from ..schemas.verification import PromotionDecision


REALITY_DEBT_FORMULA_VERSION = "reality-debt/v1"

_STATE_WEIGHTS: dict[CapabilityState, float] = {
    CapabilityState.VERIFIED: 0.0,
    CapabilityState.CANDIDATE: 0.35,
    CapabilityState.TRAINING: 0.55,
    CapabilityState.DIAGNOSING: 0.65,
    CapabilityState.UNTESTED: 0.75,
    CapabilityState.UNKNOWN: 0.9,
    CapabilityState.FAILED: 1.0,
    CapabilityState.REGRESSED: 1.0,
    CapabilityState.BLOCKED_MISSING_REALITY: 0.5,
}

FRESHNESS_HALF_LIFE_S = 60 * 60 * 24 * 14


def _freshness_decay(age_s: float) -> float:
    if age_s <= 0:
        return 1.0
    return 0.5 ** (age_s / FRESHNESS_HALF_LIFE_S)


def _contribution(record: CapabilityRecord) -> float:
    base = _STATE_WEIGHTS.get(record.state, 1.0)
    confidence_discount = 1.0 - 0.3 * record.confidence
    coverage_factor = 1.0 if record.scenario_coverage_count > 0 else 1.15
    freshness = _freshness_decay(record.evidence_freshness_s)
    regression_penalty = 1.25 if not record.protected_regression_clean else 1.0
    missing_penalty = 1.2 if record.state == CapabilityState.BLOCKED_MISSING_REALITY else 1.0
    return (
        record.importance_weight
        * base
        * confidence_discount
        * coverage_factor
        * max(freshness, 0.4)
        * regression_penalty
        * missing_penalty
    )


@dataclass(frozen=True)
class RegisterState:
    capabilities: tuple[CapabilityRecord, ...]


class CapabilityRegister:
    def __init__(self, capabilities: list[CapabilityRecord]) -> None:
        self._capabilities = list(capabilities)

    def all(self) -> tuple[CapabilityRecord, ...]:
        return tuple(self._capabilities)

    def update_from_promotion(
        self,
        decision: PromotionDecision,
        capability_taxonomy_id: str,
        scenario_coverage_count: int,
        evidence_freshness_s: float = 0.0,
    ) -> CapabilityRecord:
        updated: list[CapabilityRecord] = []
        for record in self._capabilities:
            if record.taxonomy_id != capability_taxonomy_id:
                updated.append(record)
                continue
            new_state = (
                CapabilityState.VERIFIED
                if decision.decision.value == "promoted"
                else CapabilityState.FAILED
            )
            payload = record.model_dump()
            payload.pop("content_hash", None)
            payload.update(
                {
                    "state": new_state.value,
                    "scenario_coverage_count": scenario_coverage_count,
                    "evidence_freshness_s": evidence_freshness_s,
                    "confidence": 0.95 if new_state == CapabilityState.VERIFIED else record.confidence,
                    "last_verified_checkpoint_sha256": (
                        decision.candidate_checkpoint_sha256
                        if new_state == CapabilityState.VERIFIED
                        else record.last_verified_checkpoint_sha256
                    ),
                }
            )
            new_record = type(record).model_validate(payload)
            updated.append(new_record.sealed())
        self._capabilities = updated
        return self.find(capability_taxonomy_id)

    def find(self, taxonomy_id: str) -> CapabilityRecord:
        for record in self._capabilities:
            if record.taxonomy_id == taxonomy_id:
                return record
        raise KeyError(taxonomy_id)


def default_register() -> CapabilityRegister:
    now = utc_now()

    def make(seed_suffix: str, taxonomy_id: str, name: str, weight: float, state: CapabilityState) -> CapabilityRecord:
        return CapabilityRecord(
            record_id=f"cap-{seed_suffix}",
            created_at=now,
            taxonomy_id=taxonomy_id,
            taxonomy_version="taxonomy/v1",
            display_name=name,
            importance_weight=weight,
            state=state,
            evidence_freshness_s=0.0,
            scenario_coverage_count=0,
            confidence=0.0,
        ).sealed()

    return CapabilityRegister(
        [
            make("a1f0c2e45b67d890", "occluded-pedestrian-crossing/v1", "Occluded pedestrian crossing", 1.0, CapabilityState.UNTESTED),
            make("b2e1d3f4a5b6c7d8", "visible-pedestrian-crossing/v1", "Visible pedestrian crossing", 0.8, CapabilityState.UNTESTED),
            make("c3d4e5f6a7b8c9d0", "empty-road-cruise/v1", "Empty road cruise", 0.6, CapabilityState.UNTESTED),
            make("d4e5f6a7b8c9d0e1", "low-light-crossing/v1", "Low-light pedestrian crossing", 0.9, CapabilityState.BLOCKED_MISSING_REALITY),
            make("e5f6a7b8c9d0e1f2", "glare-approach/v1", "Sun-glare approach", 0.7, CapabilityState.BLOCKED_MISSING_REALITY),
        ]
    )


def compute_reality_debt(
    capabilities: tuple[CapabilityRecord, ...],
    campaign_id: str | None = None,
) -> RealityDebtSnapshot:
    contributions = []
    total = 0.0
    for record in capabilities:
        value = _contribution(record)
        total += value
        contributions.append(
            CapabilityDebtContribution(
                capability_id=record.record_id,
                taxonomy_id=record.taxonomy_id,
                contribution=round(value, 6),
            )
        )
    snapshot = RealityDebtSnapshot(
        record_id=new_record_id("debt"),
        created_at=utc_now(),
        campaign_id=campaign_id,
        total_debt=round(total, 6),
        formula=DebtFormula(
            formula_version=REALITY_DEBT_FORMULA_VERSION,
            description=(
                "sum over capabilities of importance_weight * state_weight * "
                "(1 - 0.3*confidence) * coverage_factor * freshness_decay(floor 0.4) "
                "* regression_penalty * missing_penalty"
            ),
        ),
        contributions=tuple(sorted(contributions, key=lambda c: c.contribution, reverse=True)),
    ).sealed()
    verify_seal(snapshot)
    return snapshot


def select_next_weakness(
    capabilities: tuple[CapabilityRecord, ...],
) -> CapabilityRecord | None:
    """Deterministic eligibility filter; highest debt-adjusted priority first.

    BLOCKED_MISSING_REALITY capabilities are selectable on purpose: the
    correct autonomous action for them is a capture mission, not training.
    """

    eligible = [
        r
        for r in capabilities
        if r.state
        in (
            CapabilityState.UNTESTED,
            CapabilityState.FAILED,
            CapabilityState.REGRESSED,
            CapabilityState.UNKNOWN,
            CapabilityState.BLOCKED_MISSING_REALITY,
        )
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda r: (_contribution(r), r.taxonomy_id), reverse=True)
    return eligible[0]
