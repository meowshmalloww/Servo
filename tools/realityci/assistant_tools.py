"""Bounded assistant planning for RealityCI control-plane tools.

Language models may select one operation from this registry, but they never
execute arbitrary code, edit campaign gates, or decide promotion.  The HTTP
control plane validates the returned call and deterministic workflow code
performs every mutation.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantToolName(str, Enum):
    CREATE_CAMPAIGN = "create_campaign"
    START_CAMPAIGN = "start_campaign"
    GET_CAMPAIGN_STATUS = "get_campaign_status"
    EXPLAIN_FAILURE = "explain_failure"
    RUN_COUNTERFACTUALS = "run_counterfactuals"
    START_TRAINING = "start_training"
    RUN_HIDDEN_EXAM = "run_hidden_exam"
    SHOW_CHECKPOINT_COMPARISON = "show_checkpoint_comparison"
    CANCEL_CAMPAIGN = "cancel_campaign"
    SELECT_NEXT_WEAKNESS = "select_next_weakness"


class AssistantToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: AssistantToolName
    campaign_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(min_length=1, max_length=500)


class AssistantPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=8000)
    provider: Literal["auto", "gemini", "deterministic"] = "auto"
    model: str | None = None
    campaign_id: str | None = None


TOOL_DESCRIPTIONS = {
    AssistantToolName.CREATE_CAMPAIGN: "Create a campaign from a baseline checkpoint. Requires baseline_checkpoint_uri.",
    AssistantToolName.START_CAMPAIGN: "Start or resume the current campaign through its next meaningful gate.",
    AssistantToolName.GET_CAMPAIGN_STATUS: "Read campaign state and its latest durable events.",
    AssistantToolName.EXPLAIN_FAILURE: "Read the sealed failure evidence. Never invent a diagnosis.",
    AssistantToolName.RUN_COUNTERFACTUALS: "Advance diagnosis and execute registered experiments until the causal gate resolves.",
    AssistantToolName.START_TRAINING: "Advance an established root cause through curriculum creation and real training.",
    AssistantToolName.RUN_HIDDEN_EXAM: "Run hidden evaluation, regression, promotion, debt, and next-weakness gates.",
    AssistantToolName.SHOW_CHECKPOINT_COMPARISON: "Read checkpoint, exam, regression, and promotion records.",
    AssistantToolName.CANCEL_CAMPAIGN: "Durably cancel an active campaign.",
    AssistantToolName.SELECT_NEXT_WEAKNESS: "Read or complete deterministic Reality Debt and next-weakness selection.",
}


def deterministic_plan(request: AssistantPlanRequest) -> AssistantToolCall:
    text = request.prompt.lower()
    tool = AssistantToolName.GET_CAMPAIGN_STATUS
    if "cancel" in text or "stop campaign" in text:
        tool = AssistantToolName.CANCEL_CAMPAIGN
    elif "checkpoint" in text or "compare" in text or "promotion" in text:
        tool = AssistantToolName.SHOW_CHECKPOINT_COMPARISON
    elif "next weakness" in text or "reality debt" in text:
        tool = AssistantToolName.SELECT_NEXT_WEAKNESS
    elif "hidden exam" in text or "verify" in text or "regression" in text:
        tool = AssistantToolName.RUN_HIDDEN_EXAM
    elif "train" in text or "curriculum" in text:
        tool = AssistantToolName.START_TRAINING
    elif "counterfactual" in text or "experiment" in text or "root cause" in text or "diagnos" in text:
        tool = AssistantToolName.RUN_COUNTERFACTUALS
    elif "failure" in text or "what went wrong" in text:
        tool = AssistantToolName.EXPLAIN_FAILURE
    elif "create" in text and "campaign" in text:
        tool = AssistantToolName.CREATE_CAMPAIGN
    elif "start" in text or "resume" in text or "run campaign" in text:
        tool = AssistantToolName.START_CAMPAIGN
    return AssistantToolCall(
        tool=tool,
        campaign_id=request.campaign_id,
        arguments={},
        explanation=f"Selected the bounded {tool.value} operation from the request.",
    )


def _planning_prompt(request: AssistantPlanRequest) -> str:
    catalog = "\n".join(f"- {name.value}: {description}" for name, description in TOOL_DESCRIPTIONS.items())
    return f"""You are Servo's RealityCI control-plane planner.
Choose exactly one allowed tool. Never invent campaign results, paths, IDs, metrics, or tool names.
Promotion/rejection is deterministic code and cannot be overridden.
Use the supplied campaign_id when an operation needs an existing campaign.

Allowed tools:
{catalog}

Current campaign_id: {request.campaign_id or 'none'}
User request: {request.prompt}
"""


def _gemini_plan(request: AssistantPlanRequest) -> AssistantToolCall:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Gemini credentials are not configured")
    model = request.model or os.environ.get("SERVO_GEMINI_TOOL_MODEL", "gemini-3.7-flash")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=_planning_prompt(request),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AssistantToolCall,
            temperature=0,
        ),
    )
    if getattr(response, "parsed", None) is not None:
        return AssistantToolCall.model_validate(response.parsed)
    return AssistantToolCall.model_validate_json(response.text)


def plan_tool(request: AssistantPlanRequest) -> tuple[str, AssistantToolCall]:
    provider = request.provider
    if provider == "auto":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "gemini"
        else:
            provider = "deterministic"
    if provider == "gemini":
        return provider, _gemini_plan(request)
    return "deterministic", deterministic_plan(request)
