"""Bounded Ask Servo agent loop over the verified control-plane tools.

The language model is a planner, never the authority.  A run always reads a
durable snapshot first, asks the configured planner for one allow-listed tool,
executes that tool through the existing deterministic control plane, and then
reads the relevant durable records again.  Campaign ``run_to_completion`` is
one tool call whose implementation is the Google ADK graph; its individual
ADK nodes are preserved in the execution receipt.

This module deliberately contains no filesystem, HTTP, subprocess, or model
client code.  Those authorities are injected by the FastAPI layer, making the
loop small enough to test without fabricating external work.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field

from .tools import AskPlanRequest, AskToolCall, AskToolName, StrictTool


class AskAgentRequest(AskPlanRequest):
    """A goal executed by the bounded inspect/plan/execute/verify loop."""

    verify: bool = True


class AgentTraceEntry(StrictTool):
    sequence: int = Field(ge=1)
    phase: Literal["inspect", "plan", "execute", "verify"]
    status: Literal["completed", "blocked", "failed"]
    tool: AskToolName | None = None
    message: str = Field(min_length=1, max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)


Planner = Callable[[AskPlanRequest], tuple[str, AskToolCall]]
Executor = Callable[[AskToolCall], dict[str, Any]]


_CAMPAIGN_TOOLS = frozenset(
    {
        AskToolName.CREATE_CAMPAIGN,
        AskToolName.STEP_CAMPAIGN,
        AskToolName.RUN_TO_COMPLETION,
        AskToolName.CANCEL_CAMPAIGN,
        AskToolName.GET_CAMPAIGN_STATE,
        AskToolName.GET_CAMPAIGN_EVENTS,
        AskToolName.GET_LATEST_PAYLOAD,
        AskToolName.GET_ARTIFACTS,
        AskToolName.GET_ARTIFACT,
        AskToolName.EXPLAIN_FAILURE,
        AskToolName.RUN_COUNTERFACTUALS,
        AskToolName.ADVANCE_TO_ROOT_CAUSE,
        AskToolName.CREATE_CURRICULUM,
        AskToolName.START_TRAINING,
        AskToolName.RUN_HIDDEN_EXAM,
        AskToolName.SHOW_CHECKPOINT_COMPARISON,
        AskToolName.SELECT_NEXT_WEAKNESS,
    }
)

_SIMULATION_TOOLS = frozenset(
    {
        AskToolName.GET_SIMULATION_STATE,
        AskToolName.GET_LIVE_STATE,
        AskToolName.GET_SIMULATION_EVENTS,
        AskToolName.GET_POLICY_FRAME,
        AskToolName.GET_TELEMETRY,
        AskToolName.PAUSE_SIMULATION,
        AskToolName.RESUME_SIMULATION,
        AskToolName.STOP_SIMULATION,
        AskToolName.GET_VEHICLE_METRICS,
    }
)


def _redact_goal(value: str) -> str:
    """Avoid persisting common API-token forms if pasted into a prompt."""

    redacted = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "[REDACTED_GOOGLE_KEY]", value)
    redacted = re.sub(r"\bsk-[0-9A-Za-z_-]{12,}\b", "[REDACTED_OPENAI_KEY]", redacted)
    redacted = re.sub(
        r"(?i)\b(bearer|api[_ -]?key|token)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        redacted,
    )
    return redacted


def _result(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("result")
    return value if isinstance(value, dict) else {}


def _inspection_call(request: AskAgentRequest) -> AskToolCall:
    if request.campaign_id:
        return AskToolCall(
            tool=AskToolName.GET_CAMPAIGN_STATE,
            campaign_id=request.campaign_id,
            explanation="Inspect the selected durable campaign before planning.",
        )
    if request.simulation_id:
        return AskToolCall(
            tool=AskToolName.GET_SIMULATION_STATE,
            simulation_id=request.simulation_id,
            explanation="Inspect the selected durable simulation before planning.",
        )
    if request.world_id:
        return AskToolCall(
            tool=AskToolName.GET_WORLD_DETAILS,
            world_id=request.world_id,
            explanation="Inspect the selected world manifest before planning.",
        )
    return AskToolCall(
        tool=AskToolName.LIST_CAMPAIGNS,
        explanation="Inspect available durable campaigns before planning.",
    )


def _summary(response: dict[str, Any]) -> dict[str, Any]:
    """Return bounded evidence identifiers, never a duplicate artifact body."""

    result = _result(response)
    summary: dict[str, Any] = {}
    for key in (
        "campaign_id",
        "simulation_id",
        "world_id",
        "state",
        "terminal",
        "resumable",
        "event_count",
        "artifact_count",
        "adk_event_count",
        "adk_session_id",
        "orchestrator",
        "weather",
        "engine",
        "snow_accumulation",
        "climatenerf_qualified",
        "metric_surface",
    ):
        if key in result:
            summary[key] = result[key]
    if isinstance(result.get("latest_event"), dict):
        latest = result["latest_event"]
        summary["latest_event"] = {
            key: latest[key]
            for key in ("event_type", "sequence", "record_id")
            if key in latest
        }
    if isinstance(result.get("events"), list):
        events = result["events"]
        summary["event_count"] = len(events)
        if events:
            latest = events[-1]
            if isinstance(latest, dict):
                summary["latest_event"] = {
                    key: latest[key]
                    for key in ("event_type", "sequence", "record_id", "content_hash")
                    if key in latest
                }
    if isinstance(result.get("artifacts"), list):
        summary["artifact_count"] = len(result["artifacts"])
    if isinstance(result.get("campaigns"), list):
        summary["campaign_count"] = len(result["campaigns"])
    if isinstance(result.get("adk_steps"), list):
        summary["adk_steps"] = result["adk_steps"]
    return summary


def _detail(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    return str(detail if detail is not None else exc)[:1800]


def _context_prompt(goal: str, inspection: dict[str, Any]) -> str:
    context = _summary(inspection)
    return (
        f"User goal: {_redact_goal(goal)}\n"
        f"Durable pre-action context: {context!r}\n"
        "Choose the one bounded tool call whose scope fulfills this goal. "
        "For an explicit request to run, finish, or complete the campaign or "
        "agentic loop, choose run_to_completion; it executes the durable Google "
        "ADK workflow. Use step_campaign only when the user explicitly asks for "
        "one step. "
        "Do not claim success; execution and verification happen after planning."
    )


def _with_context_ids(call: AskToolCall, request: AskAgentRequest) -> AskToolCall:
    updates: dict[str, Any] = {}
    if call.campaign_id is None and request.campaign_id:
        updates["campaign_id"] = request.campaign_id
    if call.simulation_id is None and request.simulation_id:
        updates["simulation_id"] = request.simulation_id
    if call.world_id is None and request.world_id:
        updates["world_id"] = request.world_id
    return call.model_copy(update=updates) if updates else call


def _created_campaign_id(response: dict[str, Any]) -> str | None:
    result = _result(response)
    value = result.get("campaign_id")
    return str(value) if value else None


def _verification_calls(
    call: AskToolCall,
    execution: dict[str, Any],
    request: AskAgentRequest,
) -> list[AskToolCall]:
    if call.tool in _CAMPAIGN_TOOLS:
        campaign_id = call.campaign_id or _created_campaign_id(execution) or request.campaign_id
        if not campaign_id:
            return []
        return [
            AskToolCall(
                tool=AskToolName.GET_CAMPAIGN_STATE,
                campaign_id=campaign_id,
                explanation="Verify the durable campaign state after execution.",
            ),
            AskToolCall(
                tool=AskToolName.GET_CAMPAIGN_EVENTS,
                campaign_id=campaign_id,
                arguments={"after_sequence": 0},
                explanation="Verify the ordered event evidence after execution.",
            ),
            AskToolCall(
                tool=AskToolName.GET_ARTIFACTS,
                campaign_id=campaign_id,
                explanation="Verify persisted campaign artifacts after execution.",
            ),
        ]
    if call.tool in _SIMULATION_TOOLS:
        simulation_id = call.simulation_id or request.simulation_id
        if simulation_id:
            return [
                AskToolCall(
                    tool=AskToolName.GET_SIMULATION_STATE,
                    simulation_id=simulation_id,
                    explanation="Verify the durable simulation state after execution.",
                )
            ]
    if call.tool == AskToolName.SET_WEATHER:
        return [
            AskToolCall(
                tool=AskToolName.GET_WEATHER_STATE,
                explanation="Verify the persisted weather receipt after execution.",
            )
        ]
    return []


def run_agent_goal(
    request: AskAgentRequest,
    *,
    run_id: str,
    planner: Planner,
    executor: Executor,
) -> dict[str, Any]:
    """Execute a bounded, evidence-producing agent turn.

    Tool failures become ``blocked`` receipts.  They are not swallowed as a
    successful action and no follow-on verification is attempted.
    """

    trace: list[AgentTraceEntry] = []
    safe_goal = _redact_goal(request.prompt)

    inspection_call = _inspection_call(request)
    try:
        inspection = executor(inspection_call)
    except Exception as exc:  # fail closed before the model sees guessed state
        trace.append(
            AgentTraceEntry(
                sequence=1,
                phase="inspect",
                status="blocked",
                tool=inspection_call.tool,
                message=f"Durable-state inspection failed: {_detail(exc)}",
            )
        )
        return {
            "run_id": run_id,
            "goal": safe_goal,
            "status": "blocked",
            "provider": "none",
            "plan": [],
            "trace": [entry.model_dump(mode="json") for entry in trace],
            "message": "Servo stopped before planning because durable state could not be read.",
        }

    trace.append(
        AgentTraceEntry(
            sequence=1,
            phase="inspect",
            status="completed",
            tool=inspection_call.tool,
            message=str(inspection.get("message") or "Durable state inspected."),
            evidence=_summary(inspection),
        )
    )

    plan_request = request.model_copy(
        update={"prompt": _context_prompt(request.prompt, inspection)}
    )
    provider, selected = planner(plan_request)
    selected = _with_context_ids(selected, request)
    plan = [
        "Inspect durable state",
        f"Execute allow-listed tool: {selected.tool.value}",
        "Verify durable state, ordered events, and artifacts" if request.verify else "Return the durable tool result",
    ]
    trace.append(
        AgentTraceEntry(
            sequence=2,
            phase="plan",
            status="completed",
            tool=selected.tool,
            message=f"{provider} selected {selected.tool.value}: {selected.explanation}",
        )
    )

    try:
        execution = executor(selected)
    except Exception as exc:
        trace.append(
            AgentTraceEntry(
                sequence=3,
                phase="execute",
                status="blocked",
                tool=selected.tool,
                message=f"Execution blocked: {_detail(exc)}",
            )
        )
        return {
            "run_id": run_id,
            "goal": safe_goal,
            "status": "blocked",
            "provider": provider,
            "call": selected.model_dump(mode="json"),
            "plan": plan,
            "trace": [entry.model_dump(mode="json") for entry in trace],
            "message": (
                f"Servo planned {selected.tool.value}, but the verified control plane blocked it: "
                f"{_detail(exc)}"
            ),
        }

    trace.append(
        AgentTraceEntry(
            sequence=3,
            phase="execute",
            status="completed",
            tool=selected.tool,
            message=str(execution.get("message") or f"{selected.tool.value} executed."),
            evidence=_summary(execution),
        )
    )

    verification: list[dict[str, Any]] = []
    if request.verify:
        for verification_call in _verification_calls(selected, execution, request):
            try:
                response = executor(verification_call)
            except Exception as exc:
                trace.append(
                    AgentTraceEntry(
                        sequence=len(trace) + 1,
                        phase="verify",
                        status="failed",
                        tool=verification_call.tool,
                        message=f"Postcondition verification failed: {_detail(exc)}",
                    )
                )
                return {
                    "run_id": run_id,
                    "goal": safe_goal,
                    "status": "failed",
                    "provider": provider,
                    "call": selected.model_dump(mode="json"),
                    "plan": plan,
                    "trace": [entry.model_dump(mode="json") for entry in trace],
                    "result": execution,
                    "verification": verification,
                    "message": (
                        f"{selected.tool.value} returned, but Servo could not verify its durable postcondition. "
                        "The action is not reported as complete."
                    ),
                }
            verification.append(response)
            trace.append(
                AgentTraceEntry(
                    sequence=len(trace) + 1,
                    phase="verify",
                    status="completed",
                    tool=verification_call.tool,
                    message=str(response.get("message") or "Postcondition verified."),
                    evidence=_summary(response),
                )
            )

    final_evidence = _summary(execution)
    for response in verification:
        final_evidence.update(_summary(response))
    final_message = str(execution.get("message") or f"Completed {selected.tool.value}.")
    if request.verify and verification:
        final_message += " Durable postconditions were verified from state, events, and artifacts."
    return {
        "run_id": run_id,
        "goal": safe_goal,
        "status": "completed",
        "provider": provider,
        "call": selected.model_dump(mode="json"),
        "plan": plan,
        "trace": [entry.model_dump(mode="json") for entry in trace],
        "result": execution,
        "verification": verification,
        "evidence": final_evidence,
        "message": final_message,
    }
