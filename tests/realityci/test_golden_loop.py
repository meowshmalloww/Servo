from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.realityci.diagnosis.base import ExperimentRequest
from tools.realityci.orchestrator import (
    CampaignEngine,
    _causal_gate_required_requests,
    load_events,
)
from tools.realityci.schemas.base import verify_seal
from tools.realityci.schemas.core import EventType
from tools.realityci.schemas.diagnosis import InterventionName
from tools.realityci.state_machine import CampaignState


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "demo" / "occluded_pedestrian" / "baseline" / "baseline.pt"
requires_baseline = pytest.mark.skipif(
    not BASELINE.is_file(), reason="trained baseline checkpoint not present"
)

EXPECTED_EVENT_CHAIN = [
    EventType.CAMPAIGN_CREATED,
    EventType.BASELINE_RUN_REQUESTED,
    EventType.RUN_STARTED,
    EventType.RUN_COMPLETED,
    EventType.FAILURE_DETECTED,
]


def test_model_experiment_subset_is_completed_with_real_gate_arms() -> None:
    model_request = ExperimentRequest(
        intervention=InterventionName.ORACLE_PERCEPTION,
        hypothesis_ids=("H1",),
    )

    completed = _causal_gate_required_requests([model_request])

    assert completed[0] is model_request
    assert [request.intervention for request in completed] == [
        InterventionName.ORACLE_PERCEPTION,
        InterventionName.REMOVE_OCCLUDER,
        InterventionName.REVEAL_PEDESTRIAN_EARLIER,
        InterventionName.ORACLE_PLANNER,
    ]
    reveal = next(
        request
        for request in completed
        if request.intervention == InterventionName.REVEAL_PEDESTRIAN_EARLIER
    )
    assert reveal.parameters == {"delta_seconds": 1.2}


@requires_baseline
def test_golden_fail_to_promote_loop(tmp_path: Path) -> None:
    engine = CampaignEngine(
        tmp_path / "campaign",
        baseline_checkpoint_path=BASELINE,
        training_scenarios=24,
        hidden_exam_size=8,
        protected_suite_size=4,
        training_epochs=10,
        samples_per_scenario=14,
        promotion_target_success_rate=0.85,
        promotion_min_lower_bound=0.3,
        promotion_max_regression_pp=5.0,
    )
    terminal = engine.run_to_completion()
    assert terminal == CampaignState.COMPLETED_PROMOTED, (
        f"terminal={terminal}, decision="
        f"{(tmp_path / 'campaign' / 'promotion-decision.json').read_text()[:400] if (tmp_path / 'campaign' / 'promotion-decision.json').exists() else 'missing'}"
    )

    root = tmp_path / "campaign"

    candidate = json.loads((root / "candidate.json").read_text())
    assert candidate["checkpoint_sha256"] != candidate["parent_checkpoint_sha256"]
    assert candidate["best_val_loss"] < 0.9

    exam = json.loads((root / "hidden-exam.json").read_text())
    assert exam["candidate"]["counts"]["success"] > exam["baseline"]["counts"]["success"]
    assert exam["isolation_receipt_sha256"].startswith("sha256:")

    decision = json.loads((root / "promotion-decision.json").read_text())
    assert decision["decision"] == "promoted"
    assert all(c["passed"] for c in decision["checks"])

    debt = json.loads((root / "reality-debt.json").read_text())
    assert debt["total_debt"] >= 0.0

    events = load_events(root / "events.jsonl")
    type_sequence = [e.event_type for e in events]
    for expected in EXPECTED_EVENT_CHAIN:
        assert expected in type_sequence
    assert type_sequence[0] == EventType.CAMPAIGN_CREATED
    assert type_sequence[-1] == EventType.CAMPAIGN_COMPLETED
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    keys = [e.idempotency_key for e in events]
    assert len(set(keys)) == len(keys)

    for record_file in ("hidden-exam.json", "regression-report.json", "promotion-decision.json"):
        payload = json.loads((root / record_file).read_text())
        expected_hash = payload.pop("content_hash")
        from tools.realityci.hashing import canonical_json_bytes, sha256_digest

        assert sha256_digest(canonical_json_bytes(payload)) == expected_hash

    # Resume must be a no-op: no new events, no state change.
    events_before = len(events)
    resumed = CampaignEngine(
        root,
        baseline_checkpoint_path=BASELINE,
        training_scenarios=24,
        hidden_exam_size=8,
        protected_suite_size=4,
        training_epochs=10,
        samples_per_scenario=14,
        promotion_target_success_rate=0.85,
        promotion_min_lower_bound=0.3,
        promotion_max_regression_pp=5.0,
    )
    assert resumed.run_to_completion() == CampaignState.COMPLETED_PROMOTED
    assert len(load_events(root / "events.jsonl")) == events_before


@requires_baseline
def test_campaign_without_failure_completes_cleanly(tmp_path: Path) -> None:
    engine = CampaignEngine(
        tmp_path / "no-failure",
        baseline_checkpoint_path=BASELINE,
        training_epochs=1,
    )
    # Force the showcase scan to find nothing by pointing the engine at an
    # empty occluded pool via monkeypatched scan bounds.
    import tools.realityci.orchestrator as orch

    original = orch.build_occluded_pool

    def empty_pool(seed_base: int, count: int):
        return original(seed_base, 0)

    orch.build_occluded_pool = empty_pool
    try:
        engine._showcase_scenario()
        terminal = engine.run_to_completion(max_steps=6)
    finally:
        orch.build_occluded_pool = original
    assert terminal == CampaignState.COMPLETED_NO_FAILURE
