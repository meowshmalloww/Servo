"""Ask Servo — 36 bounded tools covering every Servo plane.

Each tool is Pydantic-validated, extra='forbid', frozen.
Implementations are pure Python over durable records; no arbitrary code exec.
LLM may only *select* a tool + arguments; control_plane validates & executes deterministically.

Domain order mirrors docs/ASK_SERVO_ARCHITECTURE.md §2.2.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------ tool names
class AskToolName(str, Enum):
    # Campaign / genetic loop (17)
    CREATE_CAMPAIGN = "create_campaign"
    STEP_CAMPAIGN = "step_campaign"
    RUN_TO_COMPLETION = "run_to_completion"
    DISPATCH_CAMPAIGN = "dispatch_campaign"
    CANCEL_CAMPAIGN = "cancel_campaign"
    LIST_CAMPAIGNS = "list_campaigns"
    GET_CAMPAIGN_STATE = "get_campaign_state"
    GET_CAMPAIGN_EVENTS = "get_campaign_events"
    GET_LATEST_PAYLOAD = "get_latest_payload"
    GET_ARTIFACTS = "get_artifacts"
    GET_ARTIFACT = "get_artifact"
    EXPLAIN_FAILURE = "explain_failure"
    RUN_COUNTERFACTUALS = "run_counterfactuals"
    ADVANCE_TO_ROOT_CAUSE = "advance_to_root_cause"
    CREATE_CURRICULUM = "create_curriculum"
    START_TRAINING = "start_training"
    RUN_HIDDEN_EXAM = "run_hidden_exam"
    SHOW_CHECKPOINT_COMPARISON = "show_checkpoint_comparison"
    SELECT_NEXT_WEAKNESS = "select_next_weakness"
    # Worlds (6)
    LIST_WORLDS = "list_worlds"
    GET_WORLD_DETAILS = "get_world_details"
    RENAME_WORLD = "rename_world"
    DELETE_WORLD = "delete_world"
    OPEN_WORLD_FOLDER = "open_world_folder"
    GET_WORLD_EXECUTION = "get_world_execution"
    # Build / Create World (6)
    GET_BUILD_STATUS = "get_build_status"
    ESTIMATE_BUILD_STORAGE = "estimate_build_storage"
    START_BUILD = "start_build"
    CANCEL_BUILD = "cancel_build"
    RETRY_BUILD = "retry_build"
    GET_BUILD_LOGS = "get_build_logs"
    # CARLA / Execution (6)
    GET_CARLA_STATUS = "get_carla_status"
    LAUNCH_CARLA = "launch_carla"
    STOP_CARLA = "stop_carla"
    PREFLIGHT_CARLA = "preflight_carla"
    PREPARE_WORLD_FOR_CARLA = "prepare_world_for_carla"
    # Simulation / Drive (9)
    LIST_SIMULATIONS = "list_simulations"
    CREATE_SIMULATION = "create_simulation"
    GET_SIMULATION_STATE = "get_simulation_state"
    GET_LIVE_STATE = "get_live_state"
    GET_SIMULATION_EVENTS = "get_simulation_events"
    GET_POLICY_FRAME = "get_policy_frame"
    GET_TELEMETRY = "get_telemetry"
    PAUSE_SIMULATION = "pause_simulation"
    RESUME_SIMULATION = "resume_simulation"
    STOP_SIMULATION = "stop_simulation"
    # Vehicle & Policy (4)
    LIST_POLICIES = "list_policies"
    GET_POLICY_DETAILS = "get_policy_details"
    CREATE_TINYDRIVE_CHECKPOINT = "create_tinydrive_checkpoint"
    GET_VEHICLE_METRICS = "get_vehicle_metrics"
    # Weather / Appearance (3)
    SET_WEATHER = "set_weather"
    GET_WEATHER_STATE = "get_weather_state"
    PREVIEW_WEATHER = "preview_weather"
    # System / Settings (4)
    GET_SETTINGS = "get_settings"
    UPDATE_SETTINGS = "update_settings"
    GET_SYSTEM_LOGS = "get_system_logs"
    GET_ERRORS = "get_errors"


TOOL_DESCRIPTIONS: dict[AskToolName, str] = {
    AskToolName.CREATE_CAMPAIGN: "Create a campaign from a baseline checkpoint. Requires baseline_checkpoint_uri.",
    AskToolName.STEP_CAMPAIGN: "Advance one durable handler (intake→baseline→triage→...→debt). Safe to retry.",
    AskToolName.RUN_TO_COMPLETION: "Run the campaign to terminal (completed_promoted/rejected/failed/cancelled).",
    AskToolName.DISPATCH_CAMPAIGN: "Queue one complete campaign on the configured Google Cloud Run Job. Requires a staged baseline and authenticated cloud dispatch.",
    AskToolName.CANCEL_CAMPAIGN: "Durably cancel an active campaign.",
    AskToolName.LIST_CAMPAIGNS: "List all campaigns with state and terminal flag.",
    AskToolName.GET_CAMPAIGN_STATE: "Read campaign.json, state.json, and last event for a campaign.",
    AskToolName.GET_CAMPAIGN_EVENTS: "Read ordered events after a sequence number.",
    AskToolName.GET_LATEST_PAYLOAD: "Read latest payload for an event type (e.g. FAILURE_DETECTED).",
    AskToolName.GET_ARTIFACTS: "List all artifacts in a campaign workspace with download URLs.",
    AskToolName.GET_ARTIFACT: "Fetch an artifact by artifact_id (hash-verified).",
    AskToolName.EXPLAIN_FAILURE: "Read sealed failure evidence. Never invent diagnosis.",
    AskToolName.RUN_COUNTERFACTUALS: "Execute registered counterfactual experiments until causal gate can resolve.",
    AskToolName.ADVANCE_TO_ROOT_CAUSE: "Run the deterministic causal gate over experiment outcomes.",
    AskToolName.CREATE_CURRICULUM: "Create targeted curriculum; hidden seeds sealed before training.",
    AskToolName.START_TRAINING: "Run real PyTorch BC training; candidate checkpoint hash must change.",
    AskToolName.RUN_HIDDEN_EXAM: "Run hidden exam + regression + promotion + debt + next weakness gates.",
    AskToolName.SHOW_CHECKPOINT_COMPARISON: "Read checkpoint, exam, regression, promotion records.",
    AskToolName.SELECT_NEXT_WEAKNESS: "Read or complete deterministic Reality Debt and next-weakness selection.",
    AskToolName.LIST_WORLDS: "List reconstructed worlds from WorldLibraryModel scan with quality metrics.",
    AskToolName.GET_WORLD_DETAILS: "Read world.json, cameras.json, hashes, depth/structure/coverage, scale, limitations.",
    AskToolName.RENAME_WORLD: "Rename a world (sanitized 1-80 chars).",
    AskToolName.DELETE_WORLD: "Delete a world and its job directory (irreversible).",
    AskToolName.OPEN_WORLD_FOLDER: "Return the filesystem path for a world (for open in explorer).",
    AskToolName.GET_WORLD_EXECUTION: "Read execution-manifest.json; check ready_for_carla.",
    AskToolName.GET_BUILD_STATUS: "Read FFmpeg/COLMAP/CUDA/gsplat status, VRAM/disk, profile caps, current stage.",
    AskToolName.ESTIMATE_BUILD_STORAGE: "Estimate storage for selected sources and profile.",
    AskToolName.START_BUILD: "Start a new reconstruction job (sources, profile, worldName).",
    AskToolName.CANCEL_BUILD: "Cancel active reconstruction job.",
    AskToolName.RETRY_BUILD: "Retry failed/cancelled job.",
    AskToolName.GET_BUILD_LOGS: "Tail events.jsonl and worker logs for a job.",
    AskToolName.GET_CARLA_STATUS: "Read discovery, server.json, preflight-receipt.",
    AskToolName.LAUNCH_CARLA: "Launch owned packaged CARLA 0.9.16 server.",
    AskToolName.STOP_CARLA: "Stop owned CARLA server.",
    AskToolName.PREFLIGHT_CARLA: "Run CARLA physics/RGB preflight (optional rendering).",
    AskToolName.PREPARE_WORLD_FOR_CARLA: "Prepare inferred corridor (meters_per_servo_unit, scale_status, lane_width, validate_in_carla).",
    AskToolName.LIST_SIMULATIONS: "List simulation sessions with state and worker liveness.",
    AskToolName.CREATE_SIMULATION: "Create a driving simulation (world_execution_manifest, policy, observation, scenario, timing).",
    AskToolName.GET_SIMULATION_STATE: "Read simulation state and ordered events.",
    AskToolName.GET_LIVE_STATE: "Read decimated live-state.json (100 ms poll).",
    AskToolName.GET_SIMULATION_EVENTS: "Read simulation events after sequence.",
    AskToolName.GET_POLICY_FRAME: "Fetch latest policy camera JPEG.",
    AskToolName.GET_TELEMETRY: "Read telemetry.jsonl tail and run-evidence.json.",
    AskToolName.PAUSE_SIMULATION: "Pause a running simulation.",
    AskToolName.RESUME_SIMULATION: "Resume a paused simulation.",
    AskToolName.STOP_SIMULATION: "Stop/cancel a simulation.",
    AskToolName.LIST_POLICIES: "List registered driving policies (behavior-reference, tinydrive, external-driving).",
    AskToolName.GET_POLICY_DETAILS: "Read a policy descriptor and checkpoint identity.",
    AskToolName.CREATE_TINYDRIVE_CHECKPOINT: "Create an initial ServoTinyDrive checkpoint (seeded).",
    AskToolName.GET_VEHICLE_METRICS: "Read live vehicle metrics (speed, acceleration, steering, throttle, brake, gear, route_completion, lateral_error, coverage, latency, collision counts, ego_pose, camera_pose).",
    AskToolName.SET_WEATHER: "Set clear weather, use Servo inferred-surface snow/smog with explicit nonmetric provenance, or activate snow/smog/flood from a hash-verified quality-accepted ClimateNeRF bundle.",
    AskToolName.GET_WEATHER_STATE: "Read weather engine, accumulation, provenance, and verified bundle receipt when applicable.",
    AskToolName.PREVIEW_WEATHER: "Return only hash-verified ClimateNeRF bundle outputs; never synthesize a preview.",
    AskToolName.GET_SETTINGS: "Read baseUrl, CARLA root, reconstruction root, api token presence.",
    AskToolName.UPDATE_SETTINGS: "Update validated settings (baseUrl, roots).",
    AskToolName.GET_SYSTEM_LOGS: "Tail control API and simulation logs.",
    AskToolName.GET_ERRORS: "Read lastError, worker-failure.json, and failure records.",
}


class AskToolCall(StrictTool):
    tool: AskToolName
    campaign_id: str | None = None
    simulation_id: str | None = None
    world_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(min_length=1, max_length=500)


class AskPlanRequest(StrictTool):
    prompt: str = Field(min_length=1, max_length=8000)
    provider: Literal["auto", "gemini", "openai", "deterministic"] = "auto"
    model: str | None = None
    campaign_id: str | None = None
    simulation_id: str | None = None
    world_id: str | None = None


class _GeminiToolSelection(BaseModel):
    """Gemini-compatible transport schema for a strict AskToolCall.

    Gemini structured output rejects JSON Schema `additionalProperties`,
    which Pydantic emits for the arbitrary argument dictionary and for
    extra='forbid'. Carry arguments as canonical JSON text, then parse and
    validate through the real strict model before execution.
    """
    tool: AskToolName
    campaign_id: str | None = None
    simulation_id: str | None = None
    world_id: str | None = None
    arguments_json: str = "{}"
    explanation: str


# ------------------------------------------------------------------ deterministic routing
def deterministic_plan(request: AskPlanRequest) -> AskToolCall:
    # Agent turns prepend a durable snapshot and planning constraints. Intent
    # routing must inspect the user's goal only, otherwise words in those
    # constraints (for example ``run_to_completion``) can select themselves.
    goal = request.prompt
    if goal.startswith("User goal: "):
        goal = goal[len("User goal: ") :].split(
            "\nDurable pre-action context:", 1
        )[0]
    t = goal.lower()
    # Campaign
    if (
        "campaign" in t
        and any(phrase in t for phrase in ("cloud", "background", "cloud run", "dispatch"))
        and any(phrase in t for phrase in ("run", "start", "queue", "dispatch", "complete"))
    ):
        return AskToolCall(
            tool=AskToolName.DISPATCH_CAMPAIGN,
            campaign_id=request.campaign_id,
            explanation="Queue the selected campaign on the authenticated Cloud Run campaign job.",
        )
    if any(
        phrase in t
        for phrase in (
            "agentic loop",
            "genetic loop",
            "taskmaster loop",
            "run to completion",
            "complete the campaign",
            "finish the campaign",
            "autonomous campaign",
        )
    ):
        return AskToolCall(
            tool=AskToolName.RUN_TO_COMPLETION,
            campaign_id=request.campaign_id,
            explanation="Run the selected campaign through the durable Google ADK graph.",
        )
    if "cancel" in t and "campaign" in t:
        return AskToolCall(tool=AskToolName.CANCEL_CAMPAIGN, campaign_id=request.campaign_id, explanation="Bounded cancel.")
    if "compare" in t or "checkpoint" in t or "promotion" in t:
        return AskToolCall(tool=AskToolName.SHOW_CHECKPOINT_COMPARISON, campaign_id=request.campaign_id, explanation="Bounded comparison.")
    if "next weakness" in t or "reality debt" in t:
        return AskToolCall(tool=AskToolName.SELECT_NEXT_WEAKNESS, campaign_id=request.campaign_id, explanation="Bounded next weakness.")
    if "hidden exam" in t or ("verify" in t and "simulation" not in t) or "regression" in t:
        return AskToolCall(tool=AskToolName.RUN_HIDDEN_EXAM, campaign_id=request.campaign_id, explanation="Bounded exam.")
    if "train" in t:
        return AskToolCall(tool=AskToolName.START_TRAINING, campaign_id=request.campaign_id, explanation="Bounded training.")
    if "curriculum" in t:
        return AskToolCall(tool=AskToolName.CREATE_CURRICULUM, campaign_id=request.campaign_id, explanation="Bounded curriculum.")
    if "root cause" in t or "causal" in t:
        return AskToolCall(tool=AskToolName.ADVANCE_TO_ROOT_CAUSE, campaign_id=request.campaign_id, explanation="Bounded gate.")
    if "counterfactual" in t or "experiment" in t:
        return AskToolCall(tool=AskToolName.RUN_COUNTERFACTUALS, campaign_id=request.campaign_id, explanation="Bounded experiments.")
    if "failure" in t or "what went wrong" in t:
        return AskToolCall(tool=AskToolName.EXPLAIN_FAILURE, campaign_id=request.campaign_id, explanation="Bounded failure.")
    if "create" in t and "campaign" in t:
        return AskToolCall(tool=AskToolName.CREATE_CAMPAIGN, explanation="Bounded create.")
    if "step" in t:
        return AskToolCall(tool=AskToolName.STEP_CAMPAIGN, campaign_id=request.campaign_id, explanation="Bounded step.")
    if "run" in t and "campaign" in t:
        return AskToolCall(tool=AskToolName.RUN_TO_COMPLETION, campaign_id=request.campaign_id, explanation="Bounded run.")
    if "list" in t and "campaign" in t:
        return AskToolCall(tool=AskToolName.LIST_CAMPAIGNS, explanation="Bounded list.")
    # Worlds
    if "world" in t and "detail" in t:
        return AskToolCall(tool=AskToolName.GET_WORLD_DETAILS, world_id=request.world_id, explanation="Bounded world details.")
    if "list" in t and "world" in t:
        return AskToolCall(tool=AskToolName.LIST_WORLDS, explanation="Bounded list worlds.")
    if "prepare" in t and "carla" in t:
        return AskToolCall(tool=AskToolName.PREPARE_WORLD_FOR_CARLA, world_id=request.world_id, explanation="Bounded prepare.")
    if "execution" in t and "world" in t:
        return AskToolCall(tool=AskToolName.GET_WORLD_EXECUTION, world_id=request.world_id, explanation="Bounded execution.")
    # Build
    if "build" in t and "status" in t:
        return AskToolCall(tool=AskToolName.GET_BUILD_STATUS, explanation="Bounded build status.")
    if "start" in t and "build" in t:
        return AskToolCall(tool=AskToolName.START_BUILD, explanation="Bounded start build.")
    # CARLA / Simulation
    if "list" in t and "simulation" in t:
        return AskToolCall(tool=AskToolName.LIST_SIMULATIONS, explanation="Bounded list sims.")
    if "carla" in t and "status" in t:
        return AskToolCall(tool=AskToolName.GET_CARLA_STATUS, explanation="Bounded carla status.")
    if "launch" in t and "carla" in t:
        return AskToolCall(tool=AskToolName.LAUNCH_CARLA, explanation="Bounded launch.")
    if "simulation" in t and "create" in t:
        return AskToolCall(tool=AskToolName.CREATE_SIMULATION, explanation="Bounded create sim.")
    if "live" in t or ("vehicle" in t and "metric" in t):
        return AskToolCall(tool=AskToolName.GET_VEHICLE_METRICS, simulation_id=request.simulation_id, explanation="Bounded metrics.")
    if "telemetry" in t:
        return AskToolCall(tool=AskToolName.GET_TELEMETRY, simulation_id=request.simulation_id, explanation="Bounded telemetry.")
    if "pause" in t:
        return AskToolCall(tool=AskToolName.PAUSE_SIMULATION, simulation_id=request.simulation_id, explanation="Bounded pause.")
    if "resume" in t:
        return AskToolCall(tool=AskToolName.RESUME_SIMULATION, simulation_id=request.simulation_id, explanation="Bounded resume.")
    if "stop" in t and "simulation" in t:
        return AskToolCall(tool=AskToolName.STOP_SIMULATION, simulation_id=request.simulation_id, explanation="Bounded stop.")
    # Weather
    if any(k in t for k in ("snow", "rain", "fog", "flood", "wet", "weather")):
        accumulation_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", t)
        accumulation = (
            max(0.0, min(float(accumulation_match.group(1)) / 100.0, 1.0))
            if accumulation_match
            else 0.9
        )
        weather = "snow" if "snow" in t else "smog" if any(k in t for k in ("fog", "smog")) else "clear"
        return AskToolCall(
            tool=AskToolName.SET_WEATHER,
            arguments={
                "weather": weather,
                "engine": "servo-inferred-surface" if weather != "clear" else "none",
                "snow_accumulation": accumulation if weather == "snow" else 0.0,
            },
            explanation="Bounded weather selection with explicit inferred-versus-verified provenance.",
        )
    # Policies
    if "list" in t and ("policy" in t or "polic" in t):
        return AskToolCall(tool=AskToolName.LIST_POLICIES, explanation="Bounded list policies.")
    if "policy" in t or "tinydrive" in t:
        return AskToolCall(tool=AskToolName.LIST_POLICIES, explanation="Bounded policies.")
    # System
    if "setting" in t:
        return AskToolCall(tool=AskToolName.GET_SETTINGS, explanation="Bounded settings.")
    if "error" in t or "log" in t:
        return AskToolCall(tool=AskToolName.GET_ERRORS, explanation="Bounded errors.")
    return AskToolCall(tool=AskToolName.GET_CAMPAIGN_STATE, campaign_id=request.campaign_id, explanation="Default state.")


def _planning_prompt(request: AskPlanRequest) -> str:
    catalog = "\n".join(f"- {n.value}: {d}" for n, d in TOOL_DESCRIPTIONS.items())
    return f"""You are Ask Servo, the full-control planner for a robotics validation workbench.
Choose exactly one allowed tool. Never invent IDs, paths, hashes, metrics, or tool names.
Promotion/rejection is deterministic code. Every world_path/simulation_id must be validated.
Use supplied campaign_id/simulation_id/world_id when needed.
Match the requested scope: when the user asks to run, finish, or complete a
campaign or agentic loop, select run_to_completion. Select step_campaign only
when the user explicitly requests one durable step.

Allowed tools:
{catalog}

Current campaign_id: {request.campaign_id or 'none'} simulation_id: {request.simulation_id or 'none'} world_id: {request.world_id or 'none'}
User request: {request.prompt}
"""


def _gemini_plan(request: AskPlanRequest) -> AskToolCall:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Gemini credentials are not configured")
    model = request.model or os.environ.get("SERVO_GEMINI_TOOL_MODEL", "gemini-3.7-flash")
    google_api = os.environ.get("SERVO_GOOGLE_API", "").strip().lower()
    use_vertex = (
        google_api in {"vertex", "vertex-ai", "aiplatform"}
        or os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    # Vertex AI express mode accepts a Google Cloud API key through the Gen AI
    # SDK. This is distinct from the Developer API endpoint; a key restricted
    # to aiplatform.googleapis.com correctly receives 403 from
    # generativelanguage.googleapis.com.
    client = (
        genai.Client(vertexai=True, api_key=api_key)
        if use_vertex else genai.Client(api_key=api_key)
    )
    response = client.models.generate_content(
        model=model,
        contents=_planning_prompt(request),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_GeminiToolSelection,
            temperature=0,
        ),
    )
    if getattr(response, "parsed", None) is not None:
        selection = _GeminiToolSelection.model_validate(response.parsed)
    else:
        selection = _GeminiToolSelection.model_validate_json(response.text)
    try:
        arguments = json.loads(selection.arguments_json or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini returned invalid tool arguments JSON") from exc
    if not isinstance(arguments, dict):
        raise RuntimeError("Gemini tool arguments must decode to an object")
    return AskToolCall(
        tool=selection.tool,
        campaign_id=selection.campaign_id or request.campaign_id,
        simulation_id=selection.simulation_id or request.simulation_id,
        world_id=selection.world_id or request.world_id,
        arguments=arguments,
        explanation=selection.explanation,
    )


def _openai_plan(request: AskPlanRequest) -> AskToolCall:
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI credentials are not configured")
    model = request.model or os.environ.get("SERVO_OPENAI_TOOL_MODEL", "gpt-5.6-terra")
    response = OpenAI(api_key=api_key).responses.parse(model=model, input=_planning_prompt(request), text_format=AskToolCall, store=False)
    if response.output_parsed is None:
        raise RuntimeError("OpenAI returned no structured tool call")
    return AskToolCall.model_validate(response.output_parsed)


def plan_tool(request: AskPlanRequest) -> tuple[str, AskToolCall]:
    provider = request.provider
    if provider == "auto":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "gemini"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = "deterministic"
    if provider == "gemini":
        return provider, _gemini_plan(request)
    if provider == "openai":
        return provider, _openai_plan(request)
    return "deterministic", deterministic_plan(request)
