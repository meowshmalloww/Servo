from __future__ import annotations

import pytest

from tools.realityci.assistant_tools import (
    AssistantPlanRequest,
    AssistantToolCall,
    AssistantToolName,
    deterministic_plan,
    plan_tool,
)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("create a campaign", AssistantToolName.CREATE_CAMPAIGN),
        ("start the campaign", AssistantToolName.START_CAMPAIGN),
        ("what is the campaign status", AssistantToolName.GET_CAMPAIGN_STATUS),
        ("explain the failure evidence", AssistantToolName.EXPLAIN_FAILURE),
        ("run counterfactual experiments", AssistantToolName.RUN_COUNTERFACTUALS),
        ("train the policy", AssistantToolName.START_TRAINING),
        ("run the hidden exam", AssistantToolName.RUN_HIDDEN_EXAM),
        ("compare candidate checkpoint", AssistantToolName.SHOW_CHECKPOINT_COMPARISON),
        ("cancel the campaign", AssistantToolName.CANCEL_CAMPAIGN),
        ("select the next weakness", AssistantToolName.SELECT_NEXT_WEAKNESS),
    ],
)
def test_deterministic_planner_is_bounded(prompt, expected) -> None:
    call = deterministic_plan(
        AssistantPlanRequest(
            prompt=prompt, provider="deterministic", campaign_id="cam-0123456789abcdef"
        )
    )
    assert call.tool == expected
    assert call.campaign_id == "cam-0123456789abcdef"


def test_explicit_deterministic_provider_never_touches_network(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-be-used")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    provider, call = plan_tool(
        AssistantPlanRequest(prompt="show status", provider="deterministic")
    )
    assert provider == "deterministic"
    assert call.tool == AssistantToolName.GET_CAMPAIGN_STATUS


def test_tool_contract_rejects_unknown_operations() -> None:
    with pytest.raises(ValueError):
        AssistantToolCall.model_validate(
            {"tool": "run_shell", "explanation": "unsafe", "arguments": {}}
        )
