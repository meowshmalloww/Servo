from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("google.adk", reason="google-adk not installed (use .venv-realityci)")

from tools.realityci.adk_graph import run_graph_async, PIPELINE
from tools.realityci.state_machine import CampaignState


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "demo" / "occluded_pedestrian" / "baseline" / "baseline.pt"
requires_baseline = pytest.mark.skipif(
    not BASELINE.is_file(), reason="trained baseline checkpoint not present"
)

SMALL = dict(
    training_scenarios=24,
    hidden_exam_size=8,
    protected_suite_size=4,
    training_epochs=4,
    samples_per_scenario=10,
    promotion_target_success_rate=0.7,
    promotion_min_lower_bound=0.3,
    promotion_max_regression_pp=5.0,
)


@requires_baseline
def test_full_campaign_executes_on_adk_graph(tmp_path: Path) -> None:
    kwargs = {"root": tmp_path / "campaign", "baseline_checkpoint_path": BASELINE, **SMALL}
    result = asyncio_run_wrapper(kwargs)

    assert result.terminal_state == CampaignState.COMPLETED_PROMOTED
    assert len(result.steps) == len(PIPELINE)
    assert [s["node"] for s in result.steps] == [
        f"step_{i:02d}_{state.value}" for i, state in enumerate(PIPELINE)
    ]
    assert result.adk_event_count >= len(PIPELINE)

    decision = json.loads(
        ((tmp_path / "campaign") / "promotion-decision.json").read_text(encoding="utf-8")
    )
    assert decision["decision"] == "promoted"


@requires_baseline
def test_adk_rerun_on_terminal_campaign_is_noop(tmp_path: Path) -> None:
    from google.adk.sessions import InMemorySessionService

    kwargs = {"root": tmp_path / "campaign", "baseline_checkpoint_path": BASELINE, **SMALL}
    service = InMemorySessionService()  # the durable store, shared across runs

    first = asyncio_run_wrapper(kwargs, session_service=service)
    workspace_events = (tmp_path / "campaign" / "events.jsonl").read_text()

    second = asyncio_run_wrapper(kwargs, session_service=service)
    assert second.terminal_state == CampaignState.COMPLETED_PROMOTED
    assert second.steps == first.steps
    # Engine-level idempotency: no new domain events, no state change.
    assert (
        tmp_path / "campaign" / "events.jsonl"
    ).read_text() == workspace_events


def asyncio_run_wrapper(kwargs, session_service=None):
    import asyncio

    from tools.realityci.adk_graph import run_graph_async

    return asyncio.run(
        run_graph_async(dict(kwargs), session_service=session_service, session_id="servo-test")
    )
