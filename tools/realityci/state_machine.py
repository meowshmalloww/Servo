"""Strict campaign state machine.

Every campaign moves through an explicit transition table.  Unknown
transitions raise InvalidTransition; terminal states accept no further
transitions.  Each state has exactly one owning module (the durable
orchestrator step) recorded in STATE_OWNERS.
"""

from __future__ import annotations

from enum import Enum


class CampaignState(str, Enum):
    PENDING = "pending"
    BASELINE_RUNNING = "baseline_running"
    FAILURE_TRIAGE = "failure_triage"
    DIAGNOSING = "diagnosing"
    EXPERIMENTING = "experimenting"
    ROOT_CAUSE_GATE = "root_cause_gate"
    CURRICULUM_PLANNING = "curriculum_planning"
    TRAINING = "training"
    HIDDEN_EXAM = "hidden_exam"
    REGRESSION_CHECK = "regression_check"
    PROMOTION_GATE = "promotion_gate"
    REALITY_DEBT_UPDATE = "reality_debt_update"
    COMPLETED_PROMOTED = "completed_promoted"
    COMPLETED_REJECTED = "completed_rejected"
    COMPLETED_NO_FAILURE = "completed_no_failure"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {
        CampaignState.COMPLETED_PROMOTED,
        CampaignState.COMPLETED_REJECTED,
        CampaignState.COMPLETED_NO_FAILURE,
        CampaignState.FAILED,
        CampaignState.CANCELLED,
    }
)


_TRANSITIONS: dict[CampaignState, frozenset[CampaignState]] = {
    CampaignState.PENDING: frozenset({CampaignState.BASELINE_RUNNING, CampaignState.CANCELLED}),
    CampaignState.BASELINE_RUNNING: frozenset(
        {CampaignState.FAILURE_TRIAGE, CampaignState.FAILED, CampaignState.CANCELLED}
    ),
    CampaignState.FAILURE_TRIAGE: frozenset(
        {CampaignState.DIAGNOSING, CampaignState.REALITY_DEBT_UPDATE, CampaignState.FAILED}
    ),
    CampaignState.DIAGNOSING: frozenset({CampaignState.EXPERIMENTING, CampaignState.FAILED}),
    CampaignState.EXPERIMENTING: frozenset(
        {CampaignState.ROOT_CAUSE_GATE, CampaignState.EXPERIMENTING, CampaignState.FAILED}
    ),
    CampaignState.ROOT_CAUSE_GATE: frozenset(
        {CampaignState.EXPERIMENTING, CampaignState.CURRICULUM_PLANNING, CampaignState.FAILED}
    ),
    CampaignState.CURRICULUM_PLANNING: frozenset({CampaignState.TRAINING, CampaignState.FAILED}),
    CampaignState.TRAINING: frozenset(
        {CampaignState.HIDDEN_EXAM, CampaignState.REALITY_DEBT_UPDATE, CampaignState.FAILED}
    ),
    CampaignState.HIDDEN_EXAM: frozenset({CampaignState.REGRESSION_CHECK, CampaignState.FAILED}),
    CampaignState.REGRESSION_CHECK: frozenset({CampaignState.PROMOTION_GATE, CampaignState.FAILED}),
    CampaignState.PROMOTION_GATE: frozenset(
        {CampaignState.REALITY_DEBT_UPDATE, CampaignState.FAILED}
    ),
    CampaignState.REALITY_DEBT_UPDATE: frozenset(
        {
            CampaignState.COMPLETED_PROMOTED,
            CampaignState.COMPLETED_REJECTED,
            CampaignState.COMPLETED_NO_FAILURE,
        }
    ),
}

# Cancellation is a control-plane transition, not a workflow-owned step.  A
# user must be able to stop any non-terminal campaign, including while a
# resumed API process is between durable steps.  Keep this policy centralized
# so the orchestrator, ADK adapter, and HTTP API cannot disagree.
for _state in tuple(_TRANSITIONS):
    _TRANSITIONS[_state] = frozenset((*_TRANSITIONS[_state], CampaignState.CANCELLED))


class InvalidTransition(ValueError):
    def __init__(self, current: CampaignState, target: CampaignState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid campaign transition: {current.value} -> {target.value}")


def assert_transition(current: CampaignState, target: CampaignState) -> None:
    if current not in _TRANSITIONS:
        raise InvalidTransition(current, target)
    if target not in _TRANSITIONS[current]:
        raise InvalidTransition(current, target)


def allowed_transitions(current: CampaignState) -> frozenset[CampaignState]:
    return _TRANSITIONS.get(current, frozenset())


STATE_OWNERS = {
    CampaignState.PENDING: "tools.realityci.orchestrator:intake",
    CampaignState.BASELINE_RUNNING: "tools.realityci.orchestrator:baseline_runner",
    CampaignState.FAILURE_TRIAGE: "tools.realityci.failure.triage",
    CampaignState.DIAGNOSING: "tools.realityci.diagnosis.base:propose",
    CampaignState.EXPERIMENTING: "tools.realityci.diagnosis.experiments:execute_batch",
    CampaignState.ROOT_CAUSE_GATE: "tools.realityci.diagnosis.causal_gate:evaluate",
    CampaignState.CURRICULUM_PLANNING: "tools.realityci.curriculum.planner:plan",
    CampaignState.TRAINING: "tools.realityci.trainers.torch_behavior_cloning:train",
    CampaignState.HIDDEN_EXAM: "tools.realityci.exam.examiner:run_exam",
    CampaignState.REGRESSION_CHECK: "tools.realityci.exam.regression:run_regression",
    CampaignState.PROMOTION_GATE: "tools.realityci.promotion.gate:decide",
    CampaignState.REALITY_DEBT_UPDATE: "tools.realityci.capabilities.register:update_from_campaign",
}
