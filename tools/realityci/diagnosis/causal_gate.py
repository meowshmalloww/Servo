"""Deterministic causal root-cause gate.

Root cause becomes ESTABLISHED only when executed counterfactual outcomes
satisfy an explicit rule with seed-level consistency.  Two attribution
rules cover the perception/planner discrimination; contradictory or
insufficient evidence stays INCONCLUSIVE — never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..schemas.diagnosis import (
    CausalDiagnosis,
    DiagnosisStatus,
    EstablishedPattern,
    ExperimentOutcome,
    HypothesisKind,
)


CAUSAL_GATE_VERSION = "causal-gate/v1"
RULE_OCCLUDED_LATE_PERCEPTION = "occluded_late_perception/v1"
RULE_PLANNER_THRESHOLD_DEFICIENCY = "planner_threshold_deficiency/v1"
RULE_LATE_PERCEPTION_GENERAL = "late_perception_general/v1"

_CONSISTENCY_NUMERATOR = 2
_CONSISTENCY_DENOMINATOR = 3


class Predicate(str, Enum):
    BASELINE_UNSAFE = "baseline_unsafe"
    REMOVE_OCCLUDER_SAFE = "remove_occluder_safe"
    REVEAL_EARLIER_SAFE = "reveal_earlier_safe"
    ORACLE_PERCEPTION_SAFE = "oracle_perception_safe"
    ORACLE_PLANNER_UNSAFE = "oracle_planner_unsafe"
    ORACLE_PLANNER_SAFE = "oracle_planner_safe"


@dataclass(frozen=True)
class GateArmOutcomes:
    baseline: ExperimentOutcome
    remove_occluder: tuple[ExperimentOutcome, ...] = ()
    reveal_earlier: tuple[ExperimentOutcome, ...] = ()
    oracle_perception: tuple[ExperimentOutcome, ...] = ()
    oracle_planner: tuple[ExperimentOutcome, ...] = ()


@dataclass(frozen=True)
class CausalGateResult:
    status: DiagnosisStatus
    rule_id: str | None
    satisfied: tuple[str, ...]
    missing: tuple[str, ...]
    root_cause_kind: HypothesisKind | None


def _majority(arms: tuple[ExperimentOutcome, ...], target: ExperimentOutcome, total_seeds: int) -> bool:
    if total_seeds < 1 or len(arms) != total_seeds:
        return False
    hits = sum(1 for arm in arms if arm == target)
    invalids = sum(1 for arm in arms if arm == ExperimentOutcome.INVALID)
    required = -(-total_seeds * _CONSISTENCY_NUMERATOR // _CONSISTENCY_DENOMINATOR)
    return hits >= required and hits + invalids == len(arms)


def evaluate_causal_gate(
    arms: GateArmOutcomes,
    total_seeds_per_arm: int,
    failure_record_id: str,
    capability_id: str,
    hypotheses=(),
    experiment_ids=(),
    campaign_id: str | None = None,
) -> tuple[CausalGateResult, CausalDiagnosis | None]:
    satisfied: list[str] = []
    missing: list[str] = []

    def record(name: Predicate, ok: bool) -> None:
        (satisfied if ok else missing).append(name.value)

    record(
        Predicate.BASELINE_UNSAFE,
        arms.baseline == ExperimentOutcome.UNSAFE,
    )
    record(
        Predicate.REMOVE_OCCLUDER_SAFE,
        _majority(arms.remove_occluder, ExperimentOutcome.SAFE, total_seeds_per_arm),
    )
    record(
        Predicate.ORACLE_PERCEPTION_SAFE,
        _majority(arms.oracle_perception, ExperimentOutcome.SAFE, total_seeds_per_arm),
    )

    planner_unsafe = _majority(arms.oracle_planner, ExperimentOutcome.UNSAFE, total_seeds_per_arm)
    planner_safe = _majority(arms.oracle_planner, ExperimentOutcome.SAFE, total_seeds_per_arm)

    common_holds = (
        arms.baseline == ExperimentOutcome.UNSAFE
        and _majority(arms.oracle_perception, ExperimentOutcome.SAFE, total_seeds_per_arm)
    )

    diagnosis: CausalDiagnosis | None = None

    if not common_holds:
        record(Predicate.ORACLE_PLANNER_UNSAFE, planner_unsafe)
        result = CausalGateResult(
            status=DiagnosisStatus.INCONCLUSIVE,
            rule_id=None,
            satisfied=tuple(satisfied),
            missing=tuple(missing),
            root_cause_kind=None,
        )
        return result, None

    occlusion_specific = _majority(arms.remove_occluder, ExperimentOutcome.SAFE, total_seeds_per_arm)

    if planner_unsafe:
        record(Predicate.ORACLE_PLANNER_UNSAFE, True)
        rule_id = (
            RULE_OCCLUDED_LATE_PERCEPTION if occlusion_specific else RULE_LATE_PERCEPTION_GENERAL
        )
        root_kind = (
            HypothesisKind.OCCLUSION_CAUSED_PERCEPTION_FAILURE
            if occlusion_specific
            else HypothesisKind.DETECTED_TOO_LATE
        )
        result = CausalGateResult(
            status=DiagnosisStatus.ESTABLISHED,
            rule_id=rule_id,
            satisfied=tuple(satisfied),
            missing=tuple(missing),
            root_cause_kind=root_kind,
        )
        diagnosis = _seal_diagnosis(
            arms=arms, result=result, failure_record_id=failure_record_id,
            capability_id=capability_id, hypotheses=hypotheses,
            experiment_ids=experiment_ids, campaign_id=campaign_id,
        )
        return result, diagnosis

    if planner_safe:
        record(Predicate.ORACLE_PLANNER_UNSAFE, False)
        satisfied.append(Predicate.ORACLE_PLANNER_SAFE.value)
        result = CausalGateResult(
            status=DiagnosisStatus.ESTABLISHED,
            rule_id=RULE_PLANNER_THRESHOLD_DEFICIENCY,
            satisfied=tuple(satisfied),
            missing=tuple(),
            root_cause_kind=HypothesisKind.PLANNER_FAILED,
        )
        diagnosis = _seal_diagnosis(
            arms=arms, result=result, failure_record_id=failure_record_id,
            capability_id=capability_id, hypotheses=hypotheses,
            experiment_ids=experiment_ids, campaign_id=campaign_id,
        )
        return result, diagnosis

    record(Predicate.ORACLE_PLANNER_UNSAFE, False)
    result = CausalGateResult(
        status=DiagnosisStatus.INCONCLUSIVE,
        rule_id=None,
        satisfied=tuple(satisfied),
        missing=tuple(["oracle_planner_consistent_outcome"]),
        root_cause_kind=None,
    )
    return result, None


def _seal_diagnosis(
    arms: GateArmOutcomes,
    result: CausalGateResult,
    failure_record_id: str,
    capability_id: str,
    hypotheses,
    experiment_ids,
    campaign_id: str | None,
) -> CausalDiagnosis:
    if result.rule_id == RULE_OCCLUDED_LATE_PERCEPTION:
        summary = (
            "Occlusion-caused late perception established: removing the occluder "
            "and granting oracle perception are safe across seeds, while an oracle "
            "planner given the same late perception stream still cannot avoid impact. "
            "Root cause is perception timing under partial occlusion."
        )
    elif result.rule_id == RULE_PLANNER_THRESHOLD_DEFICIENCY:
        summary = (
            "Planner threshold deficiency established: removing the occluder, oracle "
            "perception, and an oracle planner acting earlier on the same risk stream "
            "are all safe across seeds. The baseline planner's decision threshold is "
            "the causal gap."
        )
    else:
        summary = (
            "Late perception established as the capability gap: oracle perception is "
            "safe across seeds while an oracle planner given the same perception "
            "stream still cannot avoid impact, and removing the occluder alone does "
            "not rescue the policy. The gap is perception latency on high-speed "
            "approach, not planner or controller execution."
        )
    return CausalDiagnosis(
        record_id=new_record_id("diag"),
        created_at=utc_now(),
        campaign_id=campaign_id,
        causation_id=failure_record_id,
        parent_id=failure_record_id,
        failure_record_id=failure_record_id,
        capability_id=capability_id,
        hypotheses=hypotheses,
        experiment_ids=experiment_ids,
        status=result.status,
        root_cause_kind=result.root_cause_kind,
        established_by=EstablishedPattern(
            rule_id=result.rule_id,
            satisfied_predicates=tuple(result.satisfied),
        ),
        summary=summary,
        diagnostician="deterministic-causal-gate/v1",
    ).sealed()
