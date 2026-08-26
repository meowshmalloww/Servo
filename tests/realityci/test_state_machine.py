from __future__ import annotations

import pytest

from tools.realityci.state_machine import (
    TERMINAL_STATES,
    CampaignState,
    InvalidTransition,
    STATE_OWNERS,
    allowed_transitions,
    assert_transition,
)


def test_happy_path_promotion() -> None:
    path = [
        CampaignState.PENDING,
        CampaignState.BASELINE_RUNNING,
        CampaignState.FAILURE_TRIAGE,
        CampaignState.DIAGNOSING,
        CampaignState.EXPERIMENTING,
        CampaignState.ROOT_CAUSE_GATE,
        CampaignState.CURRICULUM_PLANNING,
        CampaignState.TRAINING,
        CampaignState.HIDDEN_EXAM,
        CampaignState.REGRESSION_CHECK,
        CampaignState.PROMOTION_GATE,
        CampaignState.REALITY_DEBT_UPDATE,
        CampaignState.COMPLETED_PROMOTED,
    ]
    for current, target in zip(path, path[1:]):
        assert_transition(current, target)


def test_rejection_and_no_failure_paths_are_reachable() -> None:
    assert_transition(CampaignState.PROMOTION_GATE, CampaignState.REALITY_DEBT_UPDATE)
    assert_transition(
        CampaignState.REALITY_DEBT_UPDATE, CampaignState.COMPLETED_REJECTED
    )
    assert_transition(CampaignState.FAILURE_TRIAGE, CampaignState.REALITY_DEBT_UPDATE)
    assert_transition(
        CampaignState.REALITY_DEBT_UPDATE, CampaignState.COMPLETED_NO_FAILURE
    )


def test_invalid_transitions_raise() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(CampaignState.PENDING, CampaignState.PROMOTION_GATE)
    with pytest.raises(InvalidTransition):
        assert_transition(CampaignState.HIDDEN_EXAM, CampaignState.DIAGNOSING)
    with pytest.raises(InvalidTransition):
        assert_transition(CampaignState.TRAINING, CampaignState.CURRICULUM_PLANNING)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in TERMINAL_STATES:
        assert allowed_transitions(state) == frozenset()


def test_every_nonterminal_state_has_owner_and_outgoing_edges() -> None:
    for state in CampaignState:
        if state in TERMINAL_STATES:
            continue
        assert state in STATE_OWNERS, f"missing owner for {state}"
        assert len(allowed_transitions(state)) >= 1


def test_failure_is_reachable_from_every_active_state() -> None:
    active = {s for s in CampaignState if s not in TERMINAL_STATES}
    active.discard(CampaignState.REALITY_DEBT_UPDATE)
    active.discard(CampaignState.PENDING)
    for state in sorted(active, key=lambda s: s.value):
        targets = allowed_transitions(state)
        assert CampaignState.FAILED in targets or CampaignState.CANCELLED in targets or state is CampaignState.REALITY_DEBT_UPDATE, (
            f"{state.value} cannot reach a terminal state"
        )


def test_cancel_path_exists_from_start() -> None:
    assert_transition(CampaignState.PENDING, CampaignState.CANCELLED)
