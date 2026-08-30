"""Production-shaped Servo RealityCI control API.

The service wraps the durable :class:`CampaignEngine` with authenticated,
idempotent HTTP operations suitable for both the native desktop client and
Cloud Run.  Local filesystem state remains the source of truth when GCS is
disabled; every request reconstructs the engine from sealed campaign records,
which makes process restart and campaign resume deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import Any, Callable, Literal

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.climate.weather_bundle import PublicationError, verify_bundle


def _load_local_env() -> None:
    """Load only Servo's documented keys for direct local uvicorn launches."""

    allowed = {
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
        "SERVO_GOOGLE_API", "SERVO_GEMINI_MODEL", "SERVO_GEMINI_TOOL_MODEL",
        "SERVO_OPENAI_TOOL_MODEL", "SERVO_API_TOKEN", "SERVO_CAMPAIGN_ROOT",
    }
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in allowed or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[name] = value


_load_local_env()

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from tools.realityci.hashing import new_record_id
from tools.realityci.hashing import canonical_json_bytes, sha256_digest, sha256_file
from tools.realityci.capabilities.register import default_register
from tools.realityci.assistant_tools import (
    TOOL_DESCRIPTIONS,
    AssistantPlanRequest,
    AssistantToolCall,
    AssistantToolName,
    plan_tool,
)
from tools.realityci.ask_servo.tools import (
    TOOL_DESCRIPTIONS as ASK_TOOL_DESCRIPTIONS,
    AskPlanRequest,
    AskToolCall as AskToolCallFull,
    AskToolName,
    plan_tool as ask_plan_tool,
)
from tools.realityci.ask_servo.agent_loop import AskAgentRequest, run_agent_goal
from tools.realityci.orchestrator import CampaignEngine, load_events
from tools.realityci.schemas.campaign import Campaign
from tools.realityci.schemas.core import DomainEvent, EventType
from tools.realityci.state_machine import TERMINAL_STATES, CampaignState
from tools.realityci.schemas.simulation import (
    CarlaRuntimeDescriptor,
    ExecutableWorldDescriptor,
    SimulationCreateRequest,
    SimulationSessionState,
)
from tools.realityci.simulation.carla.client import connect_verified, full_runtime_preflight, validate_opendrive_dry_run
from tools.realityci.simulation.carla.discovery import discover_runtime, find_free_port, port_block_available
from tools.realityci.simulation.carla.process_manager import CarlaProcessManager, process_alive
from tools.realityci.simulation.session_store import SessionStore, atomic_write_json
from tools.realityci.simulation.worlds.executable_bundle import (
    PreparationConfig,
    prepare_inferred_corridor,
)

from .object_store import gcs_enabled, sync_from_gcs, sync_to_gcs

WORKSPACE_ROOT = Path(os.environ.get("SERVO_CAMPAIGN_ROOT", "./campaigns"))
SIMULATION_ROOT = Path(os.environ.get("SERVO_SIMULATION_ROOT", "./simulations"))
API_TOKEN = os.environ.get("SERVO_API_TOKEN", "")
_LOCKS_GUARD = threading.Lock()
_CAMPAIGN_LOCKS: dict[str, threading.RLock] = {}


def require_token(authorization: str = Header(default="")) -> None:
    """Require the configured bearer token while keeping local setup simple."""

    if not API_TOKEN:
        return
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


app = FastAPI(title="servo-realityci-api", version="1.0.0")


@app.middleware("http")
async def request_identity(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:16]}"
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def structured_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
    code = {
        400: "bad_request",
        401: "unauthorized",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
    }.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": detail, "request_id": request.state.request_id}},
    )


@app.exception_handler(RequestValidationError)
async def structured_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "request validation failed",
                "request_id": request.state.request_id,
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def structured_internal_error(request: Request, exc: Exception) -> JSONResponse:
    # The detailed exception remains in server logs; clients receive a stable
    # request ID without filesystem paths, credentials, or stack traces.
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "the campaign service could not complete the request",
                "request_id": request.state.request_id,
            }
        },
    )


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCampaignRequest(StrictRequest):
    baseline_checkpoint_uri: str = Field(min_length=1)
    objective_capability: str = "occluded-pedestrian-crossing/v1"
    diagnostician: Literal["deterministic", "gemini", "auto"] = "auto"
    diagnostician_model: str | None = None
    training_scenarios: int = Field(ge=4, default=24)
    hidden_exam_size: int = Field(ge=2, default=8)
    protected_suite_size: int = Field(ge=2, default=4)
    training_epochs: int = Field(ge=1, default=10)
    samples_per_scenario: int = Field(ge=4, default=12)
    promotion_target_success_rate: float = Field(ge=0.0, le=1.0, default=0.9)
    promotion_min_lower_bound: float = Field(ge=0.0, le=1.0, default=0.5)
    promotion_max_regression_pp: float = Field(gt=0.0, default=3.0)


class CancelCampaignRequest(StrictRequest):
    reason: str = Field(default="cancelled by operator", min_length=1, max_length=512)


class ExplicitToolRequest(StrictRequest):
    campaign_id: str | None = None
    arguments: dict = Field(default_factory=dict)


class CarlaRuntimeRequest(StrictRequest):
    carla_root: str | None = None
    rpc_port: int = Field(default=2000, ge=1024, le=65535)


class CarlaPreflightRequest(CarlaRuntimeRequest):
    full: bool = False
    rendering: bool = False


class CarlaLaunchRequest(CarlaRuntimeRequest):
    rendering: bool = False


class PrepareCarlaWorldRequest(StrictRequest):
    world_path: str
    meters_per_servo_unit: float = Field(gt=0.0, le=1000.0)
    scale_status: Literal["measured", "inferred"]
    scale_source: str = Field(min_length=1, max_length=128)
    scale_uncertainty_fraction: float = Field(ge=0.0, le=1.0)
    lane_width_m: float = Field(default=3.5, ge=2.5, le=5.0)
    shoulder_width_m: float = Field(default=0.5, ge=0.0, le=4.0)
    driving_side: Literal["right", "left"] = "right"
    route_direction: Literal["forward", "reverse"] = "forward"
    camera_path_role: Literal["lane-center", "vehicle-center", "offset"] = "vehicle-center"
    camera_to_lane_center_offset_m: float = Field(default=0.0, ge=-5.0, le=5.0)
    camera_height_above_road_m: float = Field(default=1.4, ge=0.5, le=3.0)
    maximum_smoothing_deviation_m: float = Field(default=1.5, gt=0.0, le=10.0)
    include_opposing_lane: bool = False
    validate_in_carla: bool = False


class SimulationCommandRequest(StrictRequest):
    reason: str = Field(default="operator request", min_length=1, max_length=256)


def _campaign_lock(campaign_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _CAMPAIGN_LOCKS.setdefault(campaign_id, threading.RLock())


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _world_roots() -> tuple[Path, ...]:
    configured = [Path(value) for value in os.environ.get("SERVO_WORLD_ROOTS", "").split(os.pathsep) if value]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        configured.append(Path(local) / "Servo" / "reconstruction" / "jobs")
    reconstruction_root = os.environ.get("SERVO_RECONSTRUCTION_ROOT")
    if reconstruction_root:
        configured.append(Path(reconstruction_root) / "jobs")
    # Default repo-local reconstruction jobs (used by D:\Servo\runtime\reconstruction)
    configured.append(REPO_ROOT / "runtime" / "reconstruction" / "jobs")
    configured.extend((REPO_ROOT, SIMULATION_ROOT))
    return tuple(path.resolve() for path in configured)


def _inside(candidate: Path, roots: tuple[Path, ...]) -> bool:
    resolved = candidate.resolve()
    return any(resolved == root or root in resolved.parents for root in roots)


def _validated_local_path(raw: str, *, file: bool = False, directory: bool = False) -> Path:
    candidate = Path(raw).expanduser().resolve()
    if not _inside(candidate, _world_roots()):
        raise HTTPException(status_code=400, detail="path is outside validated Servo roots")
    if file and not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"required file is missing: {candidate}")
    if directory and not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"required directory is missing: {candidate}")
    return candidate


def _runtime_record_path() -> Path:
    return SIMULATION_ROOT / "runtime" / "carla" / "server.json"


def _runtime_manager(root: str) -> CarlaProcessManager:
    return CarlaProcessManager(Path(root), _runtime_record_path())


def _persisted_carla_root() -> str | None:
    settings = SIMULATION_ROOT / "runtime" / "carla" / "settings.json"
    if not settings.is_file():
        return None
    try:
        return str(json.loads(settings.read_text(encoding="utf-8")).get("carla_root") or "") or None
    except (OSError, ValueError):
        return None


def _save_carla_root(root: str) -> None:
    atomic_write_json(
        SIMULATION_ROOT / "runtime" / "carla" / "settings.json",
        {"schema_name": "servo.carla-settings/v1", "carla_root": str(Path(root).resolve())},
    )


def _session_store(session_id: str) -> SessionStore:
    if not re.fullmatch(r"sim-[0-9a-f]{16}", session_id):
        raise HTTPException(status_code=404, detail="simulation session not found")
    store = SessionStore(SIMULATION_ROOT, session_id)
    if not store.session_root.is_dir():
        raise HTTPException(status_code=404, detail="simulation session not found")
    return store


def _verified_execution_manifest(path: Path) -> ExecutableWorldDescriptor:
    descriptor = ExecutableWorldDescriptor.model_validate_json(path.read_text(encoding="utf-8"))
    payload = descriptor.model_dump(mode="json")
    sealed = payload.pop("content_hash")
    computed = sha256_digest(canonical_json_bytes(payload))
    if sealed != computed:
        raise HTTPException(
            status_code=409,
            detail=f"execution manifest hash mismatch: sealed {sealed}, computed {computed}",
        )
    return descriptor


def _worker_alive(store: SessionStore) -> bool:
    if not store.pid_path.is_file():
        return False
    try:
        record = json.loads(store.pid_path.read_text(encoding="utf-8"))
        return process_alive(int(record.get("pid", 0)))
    except (OSError, ValueError):
        return False


def _terminal_stop_verified(session_root: Path) -> bool:
    """Return true only for a bounded run with a durable terminal brake event."""

    path = session_root / "route-terminal.jsonl"
    try:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            return False
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            event = json.loads(line)
            return (
                event.get("schema") == "servo.route-terminal-braking/v1"
                and event.get("event") == "terminal-stop-verified"
                and int(event.get("terminal_control_applied_frames", 0)) >= 1
                and float(event.get("brake", 0.0)) >= 0.99
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return False


def _dynamic_actor_evidence_verified(session_root: Path, profile: str) -> bool:
    """Verify dynamic actors stayed on the supported physical surface."""

    if profile == "none":
        return True
    if profile != "one-pedestrian":
        return False
    actors_path = session_root / "dynamic-actors.json"
    events_path = session_root / "dynamic-actor-events.jsonl"
    try:
        if (
            not actors_path.is_file()
            or not events_path.is_file()
            or actors_path.stat().st_size > 1024 * 1024
            or events_path.stat().st_size > 1024 * 1024
        ):
            return False
        actors = json.loads(actors_path.read_text(encoding="utf-8")).get("actors", [])
        if not actors or any(
            actor.get("spawn_provenance", {}).get("warmup_surface_gate_pass") is not True
            for actor in actors
        ):
            return False
        for line in reversed(events_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") != "terminal-physics-snapshot":
                continue
            return (
                event.get("surface_gate_pass") is True
                and float(event.get("vertical_drift_from_grounded_spawn_m", float("inf")))
                <= 0.50
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return False


def _request_cache_path(scope: str, key: str) -> Path:
    digest = hashlib.sha256(f"{scope}\0{key}".encode("utf-8")).hexdigest()
    return WORKSPACE_ROOT / ".requests" / f"{digest}.json"


def _idempotent(scope: str, key: str | None, fingerprint: str, operation: Callable[[], dict]) -> dict:
    if not key:
        return operation()
    if len(key) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key is too long")
    path = _request_cache_path(scope, key)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("fingerprint") != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency-Key was reused with a different request")
        return cached["response"]
    response = operation()
    _atomic_json(path, {"fingerprint": fingerprint, "response": response})
    return response


def _engine_for(campaign_id: str) -> CampaignEngine:
    root = WORKSPACE_ROOT / campaign_id
    if gcs_enabled():
        sync_from_gcs(campaign_id, root)
    if not root.exists() or not (root / "campaign.json").is_file():
        raise HTTPException(status_code=404, detail="campaign not found")
    campaign = Campaign.model_validate_json((root / "campaign.json").read_text(encoding="utf-8"))
    return CampaignEngine(
        root,
        **_campaign_engine_kwargs(campaign),
    )


def _campaign_engine_kwargs(campaign: Campaign) -> dict:
    return {
        "baseline_checkpoint_path": Path(campaign.baseline_policy.checkpoint_uri),
        "objective_capability": campaign.objective.capability_taxonomy_id,
        "diagnostician_kind": campaign.config.diagnostician,
        "diagnostician_model": campaign.config.diagnostician_model,
        "seeds_per_arm": campaign.config.seeds_per_arm,
        "training_scenarios": campaign.config.training_seed_pool_size,
        "hidden_exam_size": campaign.config.hidden_exam_size,
        "protected_suite_size": campaign.config.protected_suite_size,
        "training_epochs": campaign.config.training_epochs,
        "samples_per_scenario": campaign.config.samples_per_scenario,
        "promotion_target_success_rate": campaign.config.promotion_target_success_rate,
        "promotion_min_lower_bound": campaign.config.promotion_min_lower_bound,
        "promotion_max_regression_pp": campaign.config.promotion_max_regression_pp,
    }


def _persist(campaign_id: str) -> None:
    if gcs_enabled():
        sync_to_gcs(campaign_id, WORKSPACE_ROOT / campaign_id)


def _state_response(engine: CampaignEngine) -> dict:
    state = engine.current_state()
    return {
        "campaign_id": engine.campaign_id,
        "state": state.value,
        "terminal": state in TERMINAL_STATES,
        "resumable": state not in TERMINAL_STATES,
    }


def _artifact_files(campaign_id: str) -> list[tuple[str, Path]]:
    root = (WORKSPACE_ROOT / campaign_id).resolve()
    if not root.exists():
        raise HTTPException(status_code=404, detail="campaign not found")
    files: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        artifact_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
        files.append((artifact_id, path))
    return files


def _advance_until(engine: CampaignEngine, stop_states: set[CampaignState], max_steps: int = 40) -> dict:
    for _ in range(max_steps):
        state = engine.current_state()
        if state in stop_states or state in TERMINAL_STATES:
            return _state_response(engine)
        engine.step_once()
    raise HTTPException(status_code=409, detail="campaign did not reach the requested gate")


def _latest_event_payload(engine: CampaignEngine, names: set[str]) -> dict:
    for event in reversed(load_events(engine.paths.events_file)):
        if event.event_type.value in names:
            return {
                "event_type": event.event_type.value,
                "sequence": event.sequence,
                "record_id": event.record_id,
                "payload": event.payload,
                "artifact_refs": [ref.model_dump(mode="json") for ref in event.artifact_refs],
            }
    return {}


def _execute_tool(call: AssistantToolCall) -> dict:
    tool = call.tool
    if tool == AssistantToolName.CREATE_CAMPAIGN:
        checkpoint = str(call.arguments.get("baseline_checkpoint_uri", "")).strip()
        if not checkpoint:
            raise HTTPException(status_code=400, detail="create_campaign requires baseline_checkpoint_uri")
        request = CreateCampaignRequest(
            baseline_checkpoint_uri=checkpoint,
            diagnostician=str(call.arguments.get("diagnostician", "auto")),
            training_scenarios=int(call.arguments.get("training_scenarios", 24)),
            hidden_exam_size=int(call.arguments.get("hidden_exam_size", 8)),
            protected_suite_size=int(call.arguments.get("protected_suite_size", 4)),
            training_epochs=int(call.arguments.get("training_epochs", 10)),
        )
        result = create_campaign(request, None)
        return {"tool": tool.value, "message": "Campaign created.", "result": result}

    campaign_id = (call.campaign_id or "").strip()
    if not campaign_id:
        raise HTTPException(status_code=400, detail=f"{tool.value} requires campaign_id")

    if tool == AssistantToolName.GET_CAMPAIGN_STATUS:
        engine = _engine_for(campaign_id)
        result = _state_response(engine)
        result["latest_event"] = _latest_event_payload(engine, {event.value for event in EventType})
        return {"tool": tool.value, "message": "Campaign status loaded.", "result": result}

    if tool == AssistantToolName.EXPLAIN_FAILURE:
        engine = _engine_for(campaign_id)
        failure = _latest_event_payload(engine, {"FAILURE_DETECTED", "NO_FAILURE_FOUND"})
        if not failure:
            raise HTTPException(status_code=409, detail="the campaign has not produced failure evidence yet")
        return {"tool": tool.value, "message": "Failure evidence loaded; no unsupported cause was invented.", "result": failure}

    if tool == AssistantToolName.SHOW_CHECKPOINT_COMPARISON:
        engine = _engine_for(campaign_id)
        names = {
            "CHECKPOINT_READY",
            "HIDDEN_EXAM_COMPLETED",
            "REGRESSION_COMPLETED",
            "CHECKPOINT_PROMOTED",
            "CHECKPOINT_REJECTED",
        }
        records = [
            {
                "event_type": event.event_type.value,
                "sequence": event.sequence,
                "payload": event.payload,
            }
            for event in load_events(engine.paths.events_file)
            if event.event_type.value in names
        ]
        return {"tool": tool.value, "message": "Checkpoint evidence loaded.", "result": {"records": records}}

    def mutate(engine: CampaignEngine) -> dict:
        if tool == AssistantToolName.CANCEL_CAMPAIGN:
            engine.cancel(str(call.arguments.get("reason", "cancelled by Servo Assistant")))
            return _state_response(engine)
        if tool == AssistantToolName.START_CAMPAIGN:
            return _advance_until(engine, {CampaignState.FAILURE_TRIAGE})
        if tool == AssistantToolName.RUN_COUNTERFACTUALS:
            return _advance_until(engine, {CampaignState.CURRICULUM_PLANNING})
        if tool == AssistantToolName.START_TRAINING:
            return _advance_until(engine, {CampaignState.HIDDEN_EXAM})
        if tool == AssistantToolName.RUN_HIDDEN_EXAM:
            return _advance_until(engine, set())
        if tool == AssistantToolName.SELECT_NEXT_WEAKNESS:
            result = _advance_until(engine, set())
            result["next_weakness"] = _latest_event_payload(
                engine, {"NEXT_WEAKNESS_SELECTED", "MISSING_REALITY_DETECTED"}
            )
            result["reality_debt"] = _latest_event_payload(engine, {"REALITY_DEBT_UPDATED"})
            return result
        raise HTTPException(status_code=400, detail="unsupported assistant tool")

    result = _mutate_campaign(campaign_id, mutate)
    return {"tool": tool.value, "message": f"{tool.value} completed through deterministic workflow gates.", "result": result}


@app.get("/healthz")
def healthz() -> dict:
    # Preserve the tiny health contract for load balancers and older desktop
    # clients.  Detailed capability information lives at /v1/system.
    return {"status": "ok"}


@app.get("/v1/system", dependencies=[Depends(require_token)])
def system_status() -> dict:
    return {
        "status": "ok",
        "service": "servo-realityci-api",
        "version": app.version,
        "authentication_required": bool(API_TOKEN),
        "persistence": "gcs" if gcs_enabled() else "filesystem",
    }


@app.get("/v1/assistant/tools", dependencies=[Depends(require_token)])
def assistant_tool_catalog() -> dict:
    return {
        "tools": [
            {"name": name.value, "description": description}
            for name, description in TOOL_DESCRIPTIONS.items()
        ],
        "promotion_authority": "deterministic-code-only",
    }


@app.post("/v1/assistant/plan", dependencies=[Depends(require_token)])
def plan_assistant_tool(request: AssistantPlanRequest) -> dict:
    try:
        provider, call = plan_tool(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"assistant planning failed: {exc}") from exc
    return {"provider": provider, "call": call.model_dump(mode="json")}


@app.post("/v1/assistant/execute", dependencies=[Depends(require_token)])
def execute_assistant_plan(
    request: AssistantPlanRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    try:
        provider, call = plan_tool(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"assistant planning failed: {exc}") from exc

    def execute() -> dict:
        result = _execute_tool(call)
        result["provider"] = provider
        result["call"] = call.model_dump(mode="json")
        return result

    fingerprint = request.model_dump_json()
    return _idempotent("assistant-execute", idempotency_key, fingerprint, execute)


@app.post("/v1/assistant/tools/{tool_name}", dependencies=[Depends(require_token)])
def execute_explicit_tool(
    tool_name: AssistantToolName,
    request: ExplicitToolRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    call = AssistantToolCall(
        tool=tool_name,
        campaign_id=request.campaign_id,
        arguments=request.arguments,
        explanation="Explicit bounded tool invocation.",
    )
    return _idempotent(
        f"assistant-tool:{tool_name.value}",
        idempotency_key,
        request.model_dump_json(),
        lambda: _execute_tool(call),
    )


# ------------------------------------------------------------------ Ask Servo full-control plane
def _world_execution_candidates(world_dir: Path) -> list[Path]:
    """Return execution manifests in product preference order.

    World bundles evolved from ``carla-v1`` to the camera-height-corrected
    ``carla-v2-camera-height`` contract.  Asking Servo about a world must not
    silently report it as unprepared merely because it uses the newer layout.
    """

    execution_root = (world_dir / "execution").resolve()
    if not execution_root.is_dir() or not _inside(execution_root, (world_dir.resolve(),)):
        return []
    preferred = (
        execution_root / "carla-v2-camera-height" / "execution-manifest.json",
        execution_root / "carla-v1" / "execution-manifest.json",
    )
    candidates: list[Path] = [path for path in preferred if path.is_file()]
    for path in sorted(execution_root.glob("*/execution-manifest.json")):
        resolved = path.resolve()
        if resolved not in candidates and _inside(resolved, (execution_root,)):
            candidates.append(resolved)
    return candidates


def _ask_list_worlds() -> list[dict]:
    worlds: list[dict] = []
    for root in _world_roots():
        if not root.is_dir():
            continue
        # Search both direct and jobs/ hierarchy
        for world_json in root.rglob("world.json"):
            try:
                # Heuristic: world.json must be under stages/publish/world
                if "stages/publish/world" not in world_json.as_posix():
                    continue
                data = json.loads(world_json.read_text(encoding="utf-8"))
                if data.get("schema") != "servo.gaussian-world/v1":
                    continue
                world_id = data.get("worldId", world_json.parent.name)
                # Compute metrics
                artifacts = data.get("artifacts", {})
                ply_rel = artifacts.get("ply", "")
                cam_rel = artifacts.get("cameras", "cameras.json")
                ply_path = (world_json.parent / ply_rel).resolve() if ply_rel else None
                cam_path = (world_json.parent / cam_rel).resolve() if cam_rel else None
                ply_size = ply_path.stat().st_size if ply_path and ply_path.is_file() else 0
                # hashes already in world.json
                # Try to find execution manifest
                execution_candidates = _world_execution_candidates(world_json.parent)
                exec_manifest = execution_candidates[0] if execution_candidates else None
                ready = False
                if exec_manifest is not None:
                    try:
                        exec_data = json.loads(exec_manifest.read_text(encoding="utf-8"))
                        ready = bool(exec_data.get("validation", {}).get("ready_for_carla"))
                    except Exception:
                        ready = False
                worlds.append({
                    "world_id": world_id,
                    "display_name": data.get("name", world_id),
                    "schema": data.get("schema"),
                    "ply_uri": str(ply_path) if ply_path else "",
                    "ply_size_bytes": ply_size,
                    "cameras_uri": str(cam_path) if cam_path else "",
                    "hashes": data.get("hashes", {}),
                    "limitations": data.get("limitations", []),
                    "quality": data.get("quality", {}),
                    "world_json_uri": str(world_json),
                    "ready_for_carla": ready,
                    "execution_manifest_uri": str(exec_manifest) if exec_manifest is not None else None,
                })
            except Exception:
                continue
    # Deduplicate by world_id
    seen: dict[str, dict] = {}
    for w in worlds:
        if w["world_id"] not in seen:
            seen[w["world_id"]] = w
    return sorted(seen.values(), key=lambda x: x["world_id"])


def _ask_get_world_details(world_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", world_id):
        raise HTTPException(status_code=404, detail="world not found")
    for w in _ask_list_worlds():
        if w["world_id"] == world_id:
            # Enrich with cameras + depth/structure/coverage if available
            try:
                cam_path = Path(w["cameras_uri"])
                cams = json.loads(cam_path.read_text(encoding="utf-8")) if cam_path.is_file() else {}
                w["camera_count"] = len(cams.get("cameras", []))
                w["normalization"] = cams.get("normalization", {})
                w["validation_images"] = cams.get("validationImages", [])[:5]
            except Exception:
                w["camera_count"] = 0
            # Try to read route-bundle if present
            try:
                world_dir = Path(w["world_json_uri"]).parent
                route_bundle = world_dir / "route-bundle.json"
                if route_bundle.is_file():
                    w["route_bundle"] = json.loads(route_bundle.read_text(encoding="utf-8"))
            except Exception:
                pass
            return w
    raise HTTPException(status_code=404, detail="world not found")


def _ask_get_build_status() -> dict:
    # Reuse preflight logic from reconstruction: check tool versions, free space, etc.
    # For now return filesystem-derived status
    runtime_root = Path(os.environ.get("SERVO_RECONSTRUCTION_ROOT", str(REPO_ROOT / "runtime" / "reconstruction")))
    jobs_root = runtime_root / "jobs"
    active_job = runtime_root / "active-job.json"
    status: dict[str, Any] = {
        "runtime_root": str(runtime_root),
        "jobs_root": str(jobs_root),
        "jobs_count": 0,
        "active_job": None,
        "free_space_bytes": 0,
        "profiles": ["balanced-12gb", "fidelity-12gb", "recovery-12gb"],
        "dependencies": {
            "ffmpeg": "unknown",
            "colmap": "unknown",
            "cuda": "unknown",
            "gsplat": "unknown",
            "pytorch": "unknown",
        },
    }
    try:
        if jobs_root.is_dir():
            status["jobs_count"] = len([p for p in jobs_root.iterdir() if p.is_dir()])
        import shutil
        status["free_space_bytes"] = shutil.disk_usage(str(runtime_root if runtime_root.exists() else REPO_ROOT)).free
    except Exception:
        pass
    if active_job.is_file():
        try:
            status["active_job"] = json.loads(active_job.read_text(encoding="utf-8"))
        except Exception:
            status["active_job"] = {"raw": active_job.read_text(encoding="utf-8")[:500]}
    # Try to read last job events
    try:
        # Find most recent job
        if jobs_root.is_dir():
            job_dirs = sorted([p for p in jobs_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
            if job_dirs:
                events_path = job_dirs[0] / "events.jsonl"
                if events_path.is_file():
                    lines = events_path.read_text(encoding="utf-8").splitlines()[-5:]
                    status["last_events"] = [json.loads(l) for l in lines if l.strip()]
                    status["last_job_id"] = job_dirs[0].name
    except Exception:
        pass
    return status


def _ask_get_vehicle_metrics(simulation_id: str) -> dict:
    store = _session_store(simulation_id)
    live = None
    try:
        live = store.live().model_dump(mode="json") if store.live_path.is_file() else None
    except Exception:
        live = None
    evidence = None
    try:
        ev_path = store.session_root / "run-evidence.json"
        if ev_path.is_file():
            evidence = json.loads(ev_path.read_text(encoding="utf-8"))
    except Exception:
        evidence = None
    physics_evidence = None
    try:
        physics_path = store.session_root / "physics-evidence.json"
        if physics_path.is_file():
            physics_evidence = json.loads(physics_path.read_text(encoding="utf-8"))
    except Exception:
        physics_evidence = None
    # Telemetry tail
    telemetry_tail: list[dict] = []
    try:
        tel_path = store.session_root / "telemetry.jsonl"
        if tel_path.is_file():
            lines = tel_path.read_text(encoding="utf-8").splitlines()[-20:]
            telemetry_tail = [json.loads(l) for l in lines if l.strip()]
    except Exception:
        pass
    return {
        "simulation_id": simulation_id,
        "state": json.loads(store.state_path.read_text(encoding="utf-8")).get("state") if store.state_path.is_file() else "unknown",
        "live": live,
        "evidence": evidence,
        "physics_evidence": physics_evidence,
        "telemetry_tail": telemetry_tail,
        "worker_alive": _worker_alive(store),
    }


def _ask_result_message(tool: AskToolName, result: dict[str, Any]) -> str:
    """Create a concise UI message from the record that was actually read.

    This is deliberately deterministic.  Gemini chooses the bounded tool; it
    does not get a second opportunity to invent an execution result.
    """

    if tool == AskToolName.LIST_WORLDS:
        worlds = list(result.get("worlds", []))
        ready = [world for world in worlds if world.get("ready_for_carla")]
        t5 = next(
            (world for world in worlds if "t5-hybrid-full-route-v1" in str(world.get("world_id", ""))),
            None,
        )
        message = f"Found {len(worlds)} reconstructed worlds; {len(ready)} are CARLA-ready."
        if t5:
            message += (
                f" Accepted T5 Hybrid is {t5.get('display_name', t5.get('world_id'))}"
                f" and ready_for_carla={str(bool(t5.get('ready_for_carla'))).lower()}."
            )
        return message
    if tool == AskToolName.GET_WORLD_EXECUTION:
        execution = result.get("execution", {})
        validation = execution.get("validation", {})
        routes = execution.get("routes", [])
        route_length = routes[0].get("length_m") if routes else None
        suffix = f", route {route_length:.2f} m" if isinstance(route_length, (int, float)) else ""
        return (
            f"World execution is ready_for_carla={str(bool(validation.get('ready_for_carla'))).lower()}"
            f" and carla_validated={str(bool(validation.get('carla_validated'))).lower()}{suffix}."
        )
    if tool == AskToolName.LIST_SIMULATIONS:
        simulations = list(result.get("simulations", []))
        if not simulations:
            return "No simulation sessions were found."
        latest = simulations[0]
        return (
            f"Found {len(simulations)} simulation sessions. Latest is "
            f"{latest.get('session_id')} in state {latest.get('state')}"
            f" with outcome {latest.get('outcome') or 'pending'}."
        )
    if tool in {AskToolName.GET_VEHICLE_METRICS, AskToolName.GET_TELEMETRY}:
        evidence = result.get("evidence") or {}
        metrics = evidence.get("metrics") or {}
        if metrics:
            message = (
                f"Simulation {result.get('simulation_id')} is {result.get('state')}: "
                f"route {float(metrics.get('route_completion', 0.0)) * 100.0:.1f}%, "
                f"collisions {int(metrics.get('collision_count', 0))}, "
                f"max lateral error {float(metrics.get('max_lateral_error_m', 0.0)):.3f} m."
            )
            policy = evidence.get("policy") or {}
            if policy.get("name"):
                message += f" Policy: {policy['name']}."
            weather = evidence.get("weather")
            receipt = evidence.get("weather_receipt") or {}
            snow = (receipt.get("physics") or {}).get("snow_accumulation")
            if weather == "snow" and isinstance(snow, (int, float)):
                message += f" Snow accumulation: {float(snow) * 100.0:.0f}%."
            physics = result.get("physics_evidence") or {}
            gravity = physics.get("gravity_reference_mps2")
            measured = physics.get("imu_initial_acceleration_norm_p50_mps2")
            if isinstance(gravity, (int, float)) and isinstance(measured, (int, float)):
                message += (
                    f" Gravity: {float(gravity):.2f} m/s² reference, "
                    f"{float(measured):.2f} m/s² measured IMU; "
                    f"ground-contact pass={str(bool(physics.get('ground_contact_pass'))).lower()}."
                )
            return message
        return f"Simulation {result.get('simulation_id')} is {result.get('state')}; live telemetry is attached."
    if tool == AskToolName.SET_WEATHER:
        accumulation = result.get("snow_accumulation")
        amount = f" at {float(accumulation) * 100.0:.0f}% accumulation" if isinstance(accumulation, (int, float)) else ""
        return (
            f"Weather set to {result.get('weather')} using {result.get('engine')}{amount}. "
            f"ClimateNeRF-qualified={str(bool(result.get('climatenerf_qualified', result.get('bundle_sha256')))).lower()}."
        )
    if tool == AskToolName.GET_WEATHER_STATE:
        return f"Weather is {result.get('weather', 'clear')} using {result.get('engine', 'none')}."
    if tool == AskToolName.GET_CARLA_STATUS:
        return f"CARLA discovery state: {'ready' if result.get('ready') else 'not ready'}."
    if tool == AskToolName.LIST_CAMPAIGNS:
        campaigns = list(result.get("campaigns", []))
        return f"Found {len(campaigns)} durable RealityCI campaigns."
    if tool == AskToolName.GET_SYSTEM_LOGS:
        return f"Read {len(result.get('logs', []))} bounded log files."

    scalars = [
        f"{key}={value}"
        for key, value in result.items()
        if isinstance(value, (str, int, float, bool)) and key not in {"content_hash"}
    ][:5]
    return f"Completed {tool.value}." + (" " + ", ".join(scalars) + "." if scalars else "")


def _ask_execute_with_message(call: AskToolCallFull) -> dict:
    response = _ask_execute_tool(call)
    response["message"] = _ask_result_message(call.tool, response.get("result", {}))
    return response


def _ask_execute_tool(call: AskToolCallFull) -> dict:
    tool = call.tool
    args = call.arguments or {}
    cid = call.campaign_id or args.get("campaign_id") or args.get("campaignId")
    sid = call.simulation_id or args.get("simulation_id")
    wid = call.world_id or args.get("world_id") or args.get("worldId")
    # Campaign domain — delegate to existing _execute_tool where possible
    campaign_tools = {
        AskToolName.CREATE_CAMPAIGN, AskToolName.STEP_CAMPAIGN, AskToolName.RUN_TO_COMPLETION,
        AskToolName.GET_CAMPAIGN_STATE,
        AskToolName.EXPLAIN_FAILURE, AskToolName.RUN_COUNTERFACTUALS, AskToolName.START_TRAINING,
        AskToolName.RUN_HIDDEN_EXAM, AskToolName.SHOW_CHECKPOINT_COMPARISON, AskToolName.CANCEL_CAMPAIGN,
        AskToolName.SELECT_NEXT_WEAKNESS,
    }
    if tool in {AskToolName.STEP_CAMPAIGN, AskToolName.RUN_TO_COMPLETION}:
        if not cid:
            raise HTTPException(status_code=400, detail=f"{tool.value} requires campaign_id")
        if tool == AskToolName.RUN_TO_COMPLETION:
            # The complete campaign is a real Google ADK graph, not a direct
            # while-loop hidden behind an assistant success message.
            return {"tool": tool.value, "result": _run_campaign_with_adk(cid)}

        def mutate(engine: CampaignEngine) -> dict:
            engine.step_once()
            return _state_response(engine)
        result = _mutate_campaign(cid, mutate)
        return {"tool": tool.value, "result": result}
    if tool in campaign_tools:
        # Map Ask names to assistant names where they overlap
        mapping = {
            AskToolName.CREATE_CAMPAIGN: AssistantToolName.CREATE_CAMPAIGN,
            AskToolName.GET_CAMPAIGN_STATE: AssistantToolName.GET_CAMPAIGN_STATUS,
            AskToolName.EXPLAIN_FAILURE: AssistantToolName.EXPLAIN_FAILURE,
            AskToolName.RUN_COUNTERFACTUALS: AssistantToolName.RUN_COUNTERFACTUALS,
            AskToolName.START_TRAINING: AssistantToolName.START_TRAINING,
            AskToolName.RUN_HIDDEN_EXAM: AssistantToolName.RUN_HIDDEN_EXAM,
            AskToolName.SHOW_CHECKPOINT_COMPARISON: AssistantToolName.SHOW_CHECKPOINT_COMPARISON,
            AskToolName.CANCEL_CAMPAIGN: AssistantToolName.CANCEL_CAMPAIGN,
            AskToolName.SELECT_NEXT_WEAKNESS: AssistantToolName.SELECT_NEXT_WEAKNESS,
        }
        assistant_tool = mapping.get(tool)
        if assistant_tool:
            from tools.realityci.assistant_tools import AssistantToolCall as OrigCall
            orig = OrigCall(tool=assistant_tool, campaign_id=cid, arguments=args, explanation=call.explanation)
            return _execute_tool(orig)
    if tool == AskToolName.LIST_CAMPAIGNS:
        return {"tool": tool.value, "result": list_campaigns()}
    if tool == AskToolName.GET_CAMPAIGN_EVENTS:
        if not cid:
            raise HTTPException(status_code=400, detail="get_campaign_events requires campaign_id")
        after_sequence = int(args.get("after_sequence", 0))
        if after_sequence < 0:
            raise HTTPException(status_code=400, detail="after_sequence must be nonnegative")
        return {"tool": tool.value, "result": campaign_events(cid, after_sequence)}
    if tool == AskToolName.GET_ARTIFACTS:
        if not cid:
            raise HTTPException(status_code=400, detail="get_artifacts requires campaign_id")
        return {"tool": tool.value, "result": campaign_artifacts(cid)}
    if tool == AskToolName.GET_ARTIFACT:
        if not cid:
            raise HTTPException(status_code=400, detail="get_artifact requires campaign_id")
        artifact_id = str(args.get("artifact_id", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", artifact_id):
            raise HTTPException(status_code=400, detail="get_artifact requires a SHA-256 artifact_id")
        for current_id, path in _artifact_files(cid):
            if current_id == artifact_id:
                return {
                    "tool": tool.value,
                    "result": {
                        "artifact_id": current_id,
                        "path": str(path),
                        "size_bytes": path.stat().st_size,
                        "sha256": "sha256:" + current_id,
                    },
                }
        raise HTTPException(status_code=404, detail="artifact not found")
    if tool == AskToolName.GET_LATEST_PAYLOAD:
        if not cid:
            raise HTTPException(status_code=400, detail="get_latest_payload requires campaign_id")
        requested_type = str(args.get("event_type", "")).strip()
        if not requested_type:
            raise HTTPException(status_code=400, detail="get_latest_payload requires event_type")
        engine = _engine_for(cid)
        matching = [
            event for event in load_events(engine.paths.events_file)
            if event.event_type.value == requested_type
        ]
        if not matching:
            raise HTTPException(status_code=404, detail=f"campaign event not found: {requested_type}")
        return {"tool": tool.value, "result": matching[-1].model_dump(mode="json")}
    # World domain
    if tool == AskToolName.LIST_WORLDS:
        return {"tool": tool.value, "result": {"worlds": _ask_list_worlds()}}
    if tool == AskToolName.GET_WORLD_DETAILS:
        if not wid:
            raise HTTPException(status_code=400, detail="get_world_details requires world_id")
        return {"tool": tool.value, "result": _ask_get_world_details(wid)}
    if tool == AskToolName.GET_WORLD_EXECUTION:
        if not wid:
            raise HTTPException(status_code=400, detail="get_world_execution requires world_id")
        # Reuse existing endpoint logic
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", wid):
            raise HTTPException(status_code=404, detail="world execution bundle not found")
        world = _ask_get_world_details(wid)
        candidates = _world_execution_candidates(Path(world["world_json_uri"]).parent)
        if not candidates:
            raise HTTPException(status_code=404, detail="world execution bundle not found")
        descriptor = _verified_execution_manifest(candidates[0])
        return {"tool": tool.value, "result": {"manifest_uri": str(candidates[0]), "execution": descriptor.model_dump(mode="json")}}
    if tool == AskToolName.GET_BUILD_STATUS or tool == AskToolName.ESTIMATE_BUILD_STORAGE:
        return {"tool": tool.value, "result": _ask_get_build_status()}
    if tool == AskToolName.GET_CARLA_STATUS:
        discovery = discover_runtime(persisted_root=_persisted_carla_root())
        payload = discovery.payload()
        record_path = _runtime_record_path()
        payload["server"] = None
        if record_path.is_file():
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record["process_alive"] = process_alive(int(record.get("pid", 0)), record.get("executable"))
                payload["server"] = record
            except Exception:
                payload["server"] = {"state": "invalid-record"}
        receipt = SIMULATION_ROOT / "runtime" / "carla" / "preflight-receipt.json"
        payload["full_preflight"] = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else None
        return {"tool": tool.value, "result": payload}
    if tool == AskToolName.PREFLIGHT_CARLA:
        request = CarlaPreflightRequest.model_validate(args)
        return {"tool": tool.value, "result": carla_preflight(request)}
    if tool == AskToolName.LAUNCH_CARLA:
        request = CarlaLaunchRequest.model_validate(args)
        return {"tool": tool.value, "result": launch_carla(request)}
    if tool == AskToolName.STOP_CARLA:
        return {"tool": tool.value, "result": stop_carla()}
    if tool == AskToolName.PREPARE_WORLD_FOR_CARLA:
        if wid and "world_path" not in args:
            args = dict(args)
            args["world_path"] = str(Path(_ask_get_world_details(wid)["world_json_uri"]).parent)
        request = PrepareCarlaWorldRequest.model_validate(args)
        return {"tool": tool.value, "result": prepare_carla_world(request)}
    if tool == AskToolName.LIST_SIMULATIONS:
        return {"tool": tool.value, "result": list_simulations()}
    if tool == AskToolName.CREATE_SIMULATION:
        request = SimulationCreateRequest.model_validate(args)
        return {"tool": tool.value, "result": _create_simulation(request)}
    if tool == AskToolName.GET_SIMULATION_STATE:
        if not sid:
            raise HTTPException(status_code=400, detail="get_simulation_state requires simulation_id")
        return {"tool": tool.value, "result": simulation_state(sid)}
    if tool == AskToolName.GET_LIVE_STATE:
        if not sid:
            raise HTTPException(status_code=400, detail="get_live_state requires simulation_id")
        return {"tool": tool.value, "result": simulation_live(sid)}
    if tool == AskToolName.GET_SIMULATION_EVENTS:
        if not sid:
            raise HTTPException(status_code=400, detail="get_simulation_events requires simulation_id")
        after_sequence = int(args.get("after_sequence", 0))
        if after_sequence < 0:
            raise HTTPException(status_code=400, detail="after_sequence must be nonnegative")
        return {"tool": tool.value, "result": simulation_events(sid, after_sequence)}
    if tool == AskToolName.GET_POLICY_FRAME:
        if not sid:
            raise HTTPException(status_code=400, detail="get_policy_frame requires simulation_id")
        path = _session_store(sid).session_root / "previews" / "latest-policy-frame.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="policy frame is not available")
        return {"tool": tool.value, "result": {"path": str(path), "size_bytes": path.stat().st_size}}
    if tool == AskToolName.GET_VEHICLE_METRICS:
        if not sid:
            raise HTTPException(status_code=400, detail="get_vehicle_metrics requires simulation_id")
        return {"tool": tool.value, "result": _ask_get_vehicle_metrics(sid)}
    if tool == AskToolName.GET_TELEMETRY:
        if not sid:
            raise HTTPException(status_code=400, detail="get_telemetry requires simulation_id")
        return {"tool": tool.value, "result": _ask_get_vehicle_metrics(sid)}
    if tool in {AskToolName.PAUSE_SIMULATION, AskToolName.RESUME_SIMULATION, AskToolName.STOP_SIMULATION}:
        if not sid:
            raise HTTPException(status_code=400, detail=f"{tool.value} requires simulation_id")
        command = {
            AskToolName.PAUSE_SIMULATION: "pause",
            AskToolName.RESUME_SIMULATION: "resume",
            AskToolName.STOP_SIMULATION: "stop",
        }[tool]
        return {"tool": tool.value, "result": _simulation_command(sid, command)}
    if tool == AskToolName.LIST_POLICIES:
        return {"tool": tool.value, "result": {"policies": [
            {"adapter": "carla-behavior-reference", "name": "BehaviorAgent Reference", "oracle": True, "trainable": False, "eligible_for_promotion": False},
            {"adapter": "servo-tinydrive", "name": "ServoTinyDrive", "oracle": False, "trainable": True, "eligible_for_promotion": True},
            {"adapter": "external-driving", "name": "DriveMA-2B (external)", "oracle": False, "trainable": False, "eligible_for_promotion": False, "requires": "D:\\VehicleBrain checkpoint + loopback http://127.0.0.1"},
        ]}}
    if tool == AskToolName.SET_WEATHER:
        weather = args.get("weather", "clear")
        if weather not in ("clear", "smog", "snow", "flood"):
            raise HTTPException(status_code=400, detail="unsupported weather")
        weather_path = SIMULATION_ROOT / "weather-state.json"
        if weather == "clear":
            payload = {"weather": "clear", "engine": "none", "updated_at": datetime.now(timezone.utc).isoformat()}
            atomic_write_json(weather_path, payload)
            return {"tool": tool.value, "result": payload}
        engine = str(args.get("engine", "climatenerf")).strip().lower()
        if engine in {"servo", "servo-inferred", "servo-inferred-surface"}:
            if weather not in {"snow", "smog"}:
                raise HTTPException(
                    status_code=409,
                    detail="Servo inferred-surface weather currently supports snow and smog only",
                )
            accumulation = float(args.get("snow_accumulation", 0.9 if weather == "snow" else 0.0))
            if accumulation < 0.0 or accumulation > 1.0:
                raise HTTPException(status_code=400, detail="snow_accumulation must be between 0 and 1")
            payload = {
                "weather": weather,
                "engine": "servo-inferred-surface",
                "snow_accumulation": accumulation,
                "climatenerf_qualified": False,
                "metric_surface": False,
                "visual_provenance": "inferred-weather-overlay",
                "physics": "applied by authoritative CARLA scenario at simulation creation",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_write_json(weather_path, payload)
            return {"tool": tool.value, "result": payload}
        if engine not in {"climatenerf", "climate-nerf"}:
            raise HTTPException(status_code=400, detail="unsupported weather engine")
        bundle_path = args.get("bundle_path")
        if not bundle_path:
            raise HTTPException(status_code=409, detail="non-clear weather requires bundle_path to a verified ClimateNeRF bundle")
        try:
            manifest = verify_bundle(Path(bundle_path).resolve())
        except PublicationError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if manifest["effect"] != weather:
            raise HTTPException(status_code=409, detail="ClimateNeRF bundle effect does not match requested weather")
        if manifest.get("validation", {}).get("quality_accepted") is not True:
            raise HTTPException(status_code=409, detail="ClimateNeRF bundle is not quality accepted")
        payload = {
            "weather": weather,
            "engine": manifest["engine"],
            "bundle_path": str(Path(bundle_path).resolve()),
            "bundle_sha256": manifest["bundle_sha256"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(weather_path, payload)
        return {"tool": tool.value, "result": payload}
    if tool == AskToolName.GET_WEATHER_STATE:
        weather_path = SIMULATION_ROOT / "weather-state.json"
        if weather_path.is_file():
            return {"tool": tool.value, "result": json.loads(weather_path.read_text(encoding="utf-8"))}
        return {"tool": tool.value, "result": {"weather": "clear"}}
    if tool == AskToolName.GET_SETTINGS:
        return {"tool": tool.value, "result": {
            "baseUrl": f"http://127.0.0.1:{os.environ.get('SERVO_API_PORT','8000')}",
            "campaign_root": str(WORKSPACE_ROOT.resolve()),
            "simulation_root": str(SIMULATION_ROOT.resolve()),
            "reconstruction_root": os.environ.get("SERVO_RECONSTRUCTION_ROOT", ""),
            "carla_root": _persisted_carla_root(),
            "api_token_configured": bool(API_TOKEN),
        }}
    if tool == AskToolName.GET_SYSTEM_LOGS:
        maximum_lines = max(1, min(int(args.get("maximum_lines", 120)), 500))
        requested_session = sid or args.get("simulation_id")
        records: list[dict[str, Any]] = []
        roots: list[Path] = []
        if requested_session:
            roots.append(_session_store(str(requested_session)).session_root / "logs")
        else:
            sessions = [path for path in SIMULATION_ROOT.glob("sim-*") if path.is_dir()]
            sessions.sort(key=lambda value: value.stat().st_mtime, reverse=True)
            roots.extend(path / "logs" for path in sessions[:3])
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.log")):
                if not _inside(path, (root.resolve(),)):
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-maximum_lines:]
                records.append({"path": str(path), "lines": lines})
        return {"tool": tool.value, "result": {"logs": records}}
    if tool == AskToolName.GET_ERRORS:
        # Last error proxy: scan most recent campaign and simulation failures
        errors: list[dict] = []
        try:
            for root in sorted(WORKSPACE_ROOT.iterdir(), reverse=True):
                if not root.is_dir() or root.name.startswith("."):
                    continue
                failure = root / "worker-failure.json"
                if failure.is_file():
                    errors.append(json.loads(failure.read_text(encoding="utf-8")))
                    break
        except Exception:
            pass
        return {"tool": tool.value, "result": {"errors": errors}}
    # Never report a catalog entry as successfully executed when the control
    # plane has no implementation for it.  This is intentionally fail-closed:
    # the assistant may describe the limitation, but cannot fabricate work.
    raise HTTPException(status_code=501, detail=f"Ask Servo tool is not wired: {tool.value}")


@app.get("/v1/ask/tools", dependencies=[Depends(require_token)])
def ask_tool_catalog() -> dict:
    return {
        "tools": [{"name": n.value, "description": ASK_TOOL_DESCRIPTIONS[n]} for n in AskToolName],
        "resources": [{"uriTemplate": k, "description": v} for k, v in __import__("tools.realityci.ask_servo.resources", fromlist=["RESOURCE_TEMPLATES"]).RESOURCE_TEMPLATES.items()],
        "prompts": __import__("tools.realityci.ask_servo.prompts", fromlist=["PROMPTS"]).PROMPTS,
        "promotion_authority": "deterministic-code-only",
    }


@app.post("/v1/ask/plan", dependencies=[Depends(require_token)])
def ask_plan(request: AskPlanRequest) -> dict:
    try:
        provider, call = ask_plan_tool(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"ask planning failed: {exc}") from exc
    return {"provider": provider, "call": call.model_dump(mode="json")}


@app.post("/v1/ask/execute", dependencies=[Depends(require_token)])
def ask_execute(
    request: AskPlanRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    try:
        provider, call = ask_plan_tool(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"ask planning failed: {exc}") from exc

    def execute() -> dict:
        result = _ask_execute_with_message(call)
        result["provider"] = provider
        result["call"] = call.model_dump(mode="json")
        return result

    fingerprint = request.model_dump_json()
    return _idempotent("ask-execute", idempotency_key, fingerprint, execute)


def _agent_run_path(run_id: str) -> Path:
    if not re.fullmatch(r"askrun-[0-9a-f]{16}", run_id):
        raise HTTPException(status_code=404, detail="Ask Servo agent run not found")
    return WORKSPACE_ROOT / ".ask-servo" / "runs" / f"{run_id}.json"


def _agent_run_message(result: dict[str, Any], receipt_hash: str) -> str:
    status = str(result.get("status", "unknown")).upper()
    lines = [f"ASK SERVO AGENT RUN {result.get('run_id')} — {status}", "", "Plan"]
    for index, item in enumerate(result.get("plan", []), start=1):
        lines.append(f"{index}. {item}")
    lines.extend(("", "Progress"))
    marker = {"completed": "PASS", "blocked": "BLOCKED", "failed": "FAILED"}
    for entry in result.get("trace", []):
        phase = str(entry.get("phase", "step")).upper()
        state = marker.get(str(entry.get("status")), "UNKNOWN")
        tool = entry.get("tool")
        label = f" [{tool}]" if tool else ""
        lines.append(f"{state} {phase}{label}: {entry.get('message', '')}")
    evidence = result.get("evidence") or {}
    if evidence:
        lines.extend(("", "Verified evidence"))
        for key in (
            "campaign_id", "simulation_id", "world_id", "state", "terminal",
            "event_count", "artifact_count", "orchestrator", "adk_event_count",
            "adk_session_id", "weather", "engine", "snow_accumulation",
            "climatenerf_qualified", "metric_surface",
        ):
            if key in evidence:
                lines.append(f"{key}: {evidence[key]}")
        latest = evidence.get("latest_event")
        if isinstance(latest, dict) and latest:
            lines.append(
                "latest_event: "
                + ", ".join(f"{key}={value}" for key, value in latest.items())
            )
        adk_steps = evidence.get("adk_steps")
        if isinstance(adk_steps, list) and adk_steps:
            lines.append("ADK node trace:")
            for step in adk_steps:
                if isinstance(step, dict):
                    lines.append(
                        f"- {step.get('node', 'unknown')} -> {step.get('to', 'unknown')}"
                    )
    lines.extend(("", str(result.get("message", "")), f"Receipt: {receipt_hash}"))
    return "\n".join(lines)


def _persist_agent_run(result: dict[str, Any]) -> tuple[Path, str]:
    payload = {
        "schema": "servo.ask-servo-agent-run/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    receipt_hash = sha256_digest(canonical_json_bytes(payload))
    payload["content_hash"] = receipt_hash
    path = _agent_run_path(str(result["run_id"]))
    _atomic_json(path, payload)
    return path, receipt_hash


@app.post("/v1/ask/agent", dependencies=[Depends(require_token)])
def ask_agent(
    request: AskAgentRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """Run one real inspect/plan/execute/verify agent turn.

    The selected model sees only the bounded pre-action snapshot.  All state
    mutation and postcondition checks remain in deterministic control-plane
    tools.  Unsupported tools return a sealed ``blocked`` receipt.
    """

    def execute() -> dict:
        run_id = new_record_id("askrun")
        try:
            result = run_agent_goal(
                request,
                run_id=run_id,
                planner=ask_plan_tool,
                executor=_ask_execute_with_message,
            )
        except Exception as exc:
            # Planner failures happen before a tool call.  Preserve the
            # existing HTTP error semantics instead of falling back to a
            # different provider and pretending the requested model ran.
            raise HTTPException(status_code=400, detail=f"Ask Servo agent planning failed: {exc}") from exc
        receipt_path, receipt_hash = _persist_agent_run(result)
        result["receipt"] = {
            "schema": "servo.ask-servo-agent-run/v1",
            "content_hash": receipt_hash,
            "path": str(receipt_path),
        }
        result["message"] = _agent_run_message(result, receipt_hash)
        return result

    return _idempotent(
        "ask-agent",
        idempotency_key,
        request.model_dump_json(),
        execute,
    )


@app.get("/v1/ask/agent-runs/{run_id}", dependencies=[Depends(require_token)])
def get_ask_agent_run(run_id: str) -> dict:
    path = _agent_run_path(run_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Ask Servo agent run not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    sealed = str(payload.pop("content_hash", ""))
    computed = sha256_digest(canonical_json_bytes(payload))
    if sealed != computed:
        raise HTTPException(status_code=409, detail="Ask Servo agent receipt hash mismatch")
    payload["content_hash"] = sealed
    return payload


@app.post("/v1/ask/tools/{tool_name}", dependencies=[Depends(require_token)])
def ask_execute_explicit(
    tool_name: AskToolName,
    request: ExplicitToolRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    call = AskToolCallFull(tool=tool_name, campaign_id=request.campaign_id, arguments=request.arguments, explanation="Explicit Ask tool invocation.")
    # Allow world_id/simulation_id via arguments for ask tools
    if "world_id" in request.arguments and not call.world_id:
        call = call.model_copy(update={"world_id": request.arguments["world_id"]})
    if "simulation_id" in request.arguments and not call.simulation_id:
        call = call.model_copy(update={"simulation_id": request.arguments["simulation_id"]})
    return _idempotent(
        f"ask-tool:{tool_name.value}",
        idempotency_key,
        request.model_dump_json(),
        lambda: _ask_execute_with_message(call),
    )


@app.get("/v1/campaigns", dependencies=[Depends(require_token)])
def list_campaigns() -> dict:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    campaigns: list[dict] = []
    for root in sorted(WORKSPACE_ROOT.iterdir()):
        if not root.is_dir() or root.name.startswith("."):
            continue
        try:
            engine = _engine_for(root.name)
            campaign = engine.campaign_record()
            state = engine._read_state()  # durable control-plane summary
            campaigns.append(
                {
                    "campaign_id": engine.campaign_id,
                    "state": engine.current_state().value,
                    "terminal": engine.current_state() in TERMINAL_STATES,
                    "resumable": engine.current_state() not in TERMINAL_STATES,
                    "updated_at": state.get("updated_at"),
                    "objective_capability": campaign.objective.capability_taxonomy_id,
                    "diagnostician": campaign.config.diagnostician,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    campaigns.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {"campaigns": campaigns}


@app.post("/v1/campaigns", dependencies=[Depends(require_token)])
def create_campaign(
    request: CreateCampaignRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    checkpoint = Path(request.baseline_checkpoint_uri)
    if not checkpoint.is_file():
        raise HTTPException(status_code=400, detail="baseline checkpoint does not exist")
    try:
        default_register().find(request.objective_capability)
    except KeyError as error:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported objective capability: {request.objective_capability}",
        ) from error

    def create() -> dict:
        campaign_id = new_record_id("cam")
        engine = CampaignEngine(
            WORKSPACE_ROOT / campaign_id,
            baseline_checkpoint_path=checkpoint,
            objective_capability=request.objective_capability,
            diagnostician_kind=request.diagnostician,
            diagnostician_model=request.diagnostician_model,
            training_scenarios=request.training_scenarios,
            hidden_exam_size=request.hidden_exam_size,
            protected_suite_size=request.protected_suite_size,
            training_epochs=request.training_epochs,
            samples_per_scenario=request.samples_per_scenario,
            promotion_target_success_rate=request.promotion_target_success_rate,
            promotion_min_lower_bound=request.promotion_min_lower_bound,
            promotion_max_regression_pp=request.promotion_max_regression_pp,
            campaign_id=campaign_id,
        )
        _persist(campaign_id)
        return _state_response(engine)

    return _idempotent("create-campaign", idempotency_key, request.model_dump_json(), create)


def _mutate_campaign(campaign_id: str, operation: Callable[[CampaignEngine], dict]) -> dict:
    with _campaign_lock(campaign_id):
        engine = _engine_for(campaign_id)
        response = operation(engine)
        _persist(campaign_id)
        return response


@app.post("/v1/campaigns/{campaign_id}/step", dependencies=[Depends(require_token)])
def step_campaign(
    campaign_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    return _idempotent(
        f"{campaign_id}:step",
        idempotency_key,
        "step",
        lambda: _mutate_campaign(campaign_id, lambda engine: (_state_after_step(engine))),
    )


def _state_after_step(engine: CampaignEngine) -> dict:
    engine.step_once()
    return _state_response(engine)


def _run_campaign_with_adk(campaign_id: str) -> dict:
    """Run the durable workflow through the installed local Google ADK graph."""

    with _campaign_lock(campaign_id):
        engine = _engine_for(campaign_id)
        campaign = engine.campaign_record()
        from tools.realityci.adk_graph import ADK_VERSION_INSTALLED, run_campaign_on_adk

        result = run_campaign_on_adk(
            engine.paths.root,
            Path(campaign.baseline_policy.checkpoint_uri),
            **{
                key: value
                for key, value in _campaign_engine_kwargs(campaign).items()
                if key != "baseline_checkpoint_path"
            },
        )
        response = _state_response(_engine_for(campaign_id))
        response.update(
            {
                "orchestrator": ADK_VERSION_INSTALLED,
                "adk_event_count": result.adk_event_count,
                "adk_session_id": result.session_id,
                "adk_steps": result.steps,
            }
        )
        _persist(campaign_id)
        return response


@app.post("/v1/campaigns/{campaign_id}/run", dependencies=[Depends(require_token)])
@app.post("/v1/campaigns/{campaign_id}/resume", dependencies=[Depends(require_token)])
def run_campaign(
    campaign_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    return _idempotent(
        f"{campaign_id}:run",
        idempotency_key,
        "run-to-terminal",
        lambda: _run_campaign_with_adk(campaign_id),
    )


@app.post("/v1/campaigns/{campaign_id}/cancel", dependencies=[Depends(require_token)])
def cancel_campaign(
    campaign_id: str,
    request: CancelCampaignRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    def cancel(engine: CampaignEngine) -> dict:
        engine.cancel(request.reason)
        return _state_response(engine)

    return _idempotent(
        f"{campaign_id}:cancel",
        idempotency_key,
        request.model_dump_json(),
        lambda: _mutate_campaign(campaign_id, cancel),
    )


@app.get("/v1/campaigns/{campaign_id}/state", dependencies=[Depends(require_token)])
def campaign_state(campaign_id: str) -> dict:
    return _state_response(_engine_for(campaign_id))


@app.get("/v1/campaigns/{campaign_id}/events", dependencies=[Depends(require_token)])
def campaign_events(campaign_id: str, after_sequence: int = 0) -> dict:
    engine = _engine_for(campaign_id)
    events: list[DomainEvent] = [
        event for event in load_events(engine.paths.events_file) if event.sequence > after_sequence
    ]
    return {
        "campaign_id": campaign_id,
        "events": [event.model_dump(mode="json") for event in events],
    }


@app.get("/v1/campaigns/{campaign_id}/artifacts", dependencies=[Depends(require_token)])
def campaign_artifacts(campaign_id: str) -> dict:
    artifacts = []
    root = (WORKSPACE_ROOT / campaign_id).resolve()
    for artifact_id, path in _artifact_files(campaign_id):
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "download_url": f"/v1/campaigns/{campaign_id}/artifacts/{artifact_id}",
            }
        )
    return {"campaign_id": campaign_id, "artifacts": artifacts}


@app.get("/v1/campaigns/{campaign_id}/artifacts/{artifact_id}", dependencies=[Depends(require_token)])
def download_campaign_artifact(campaign_id: str, artifact_id: str):
    for current_id, path in _artifact_files(campaign_id):
        if current_id == artifact_id:
            return FileResponse(path, filename=path.name)
    raise HTTPException(status_code=404, detail="artifact not found")


@app.get("/v1/carla/status", dependencies=[Depends(require_token)])
def carla_status() -> dict:
    discovery = discover_runtime(persisted_root=_persisted_carla_root())
    payload = discovery.payload()
    record_path = _runtime_record_path()
    payload["server"] = None
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["process_alive"] = process_alive(int(record.get("pid", 0)), record.get("executable"))
            payload["server"] = record
        except (OSError, ValueError):
            payload["server"] = {"state": "invalid-record"}
    receipt = SIMULATION_ROOT / "runtime" / "carla" / "preflight-receipt.json"
    payload["full_preflight"] = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else None
    return payload


@app.post("/v1/carla/preflight", dependencies=[Depends(require_token)])
def carla_preflight(request: CarlaPreflightRequest) -> dict:
    rpc_port = request.rpc_port if port_block_available(request.rpc_port, 3) else find_free_port()
    discovery = discover_runtime(
        request.carla_root,
        persisted_root=_persisted_carla_root(),
        rpc_port=rpc_port,
    )
    if request.carla_root and discovery.root:
        _save_carla_root(discovery.root)
    payload = discovery.payload()
    payload["selected_rpc_port"] = rpc_port
    if not request.full or not discovery.ready:
        return payload
    manager = _runtime_manager(discovery.root or "")
    owned = False
    try:
        if not manager.verify_record():
            manager.launch(
                discovery,
                require_rendering=request.rendering,
                rpc_port=rpc_port,
                traffic_manager_port=find_free_port(),
            )
            owned = True
        deadline = time.monotonic() + 90.0
        last_error = "CARLA server did not become ready"
        while time.monotonic() < deadline:
            try:
                connect_verified(discovery.python_api_path or "", "127.0.0.1", rpc_port, 2.0)
                break
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5)
        else:
            raise HTTPException(status_code=409, detail=last_error)
        # World loading is destructive native state. Execute it exactly once
        # after the version handshake says the server is ready.
        result = full_runtime_preflight(
            discovery.python_api_path or "",
            "127.0.0.1",
            rpc_port,
            rendering=request.rendering,
        )
        receipt_payload = {
            "schema_name": "servo.carla-preflight-receipt/v1",
            "integration_version": discovery.integration_version,
            "root": discovery.root,
            "executable_sha256": discovery.executable_sha256,
            "python_api_sha256": discovery.python_api_sha256,
            "rendering": request.rendering,
            "result": result,
            "content_hash": sha256_digest(canonical_json_bytes(result)),
        }
        atomic_write_json(SIMULATION_ROOT / "runtime" / "carla" / "preflight-receipt.json", receipt_payload)
        payload["full_preflight"] = receipt_payload
        return payload
    finally:
        if owned:
            manager.stop()


@app.post("/v1/carla/launch", dependencies=[Depends(require_token)])
def launch_carla(request: CarlaLaunchRequest) -> dict:
    discovery = discover_runtime(request.carla_root, persisted_root=_persisted_carla_root(), rpc_port=request.rpc_port)
    if not discovery.ready or not discovery.root:
        raise HTTPException(status_code=409, detail="CARLA runtime is not ready: " + "; ".join(discovery.errors))
    _save_carla_root(discovery.root)
    return _runtime_manager(discovery.root).launch(
        discovery,
        require_rendering=request.rendering,
        rpc_port=request.rpc_port,
        traffic_manager_port=find_free_port(),
    )


@app.post("/v1/carla/stop", dependencies=[Depends(require_token)])
def stop_carla() -> dict:
    record = json.loads(_runtime_record_path().read_text(encoding="utf-8")) if _runtime_record_path().is_file() else None
    if not record:
        return {"state": "not-running"}
    root = str(Path(record["executable"]).resolve().parent)
    _runtime_manager(root).stop()
    return {"state": "stopped", "pid": record.get("pid")}


@app.post("/v1/worlds/prepare-carla", dependencies=[Depends(require_token)])
def prepare_carla_world(request: PrepareCarlaWorldRequest) -> dict:
    world_root = _validated_local_path(request.world_path, directory=True)
    output = world_root / "execution" / "carla-v2-camera-height"
    config = PreparationConfig(
        meters_per_servo_unit=request.meters_per_servo_unit,
        scale_status=request.scale_status,
        scale_source=request.scale_source,
        scale_uncertainty_fraction=request.scale_uncertainty_fraction,
        lane_width_m=request.lane_width_m,
        shoulder_width_m=request.shoulder_width_m,
        driving_side=request.driving_side,
        route_direction=request.route_direction,
        camera_path_role=request.camera_path_role,
        camera_to_lane_center_offset_m=request.camera_to_lane_center_offset_m,
        camera_height_above_road_m=request.camera_height_above_road_m,
        maximum_smoothing_deviation_m=request.maximum_smoothing_deviation_m,
        include_opposing_lane=request.include_opposing_lane,
    )
    descriptor = prepare_inferred_corridor(world_root, output, config)
    if request.validate_in_carla:
        discovery = discover_runtime(persisted_root=_persisted_carla_root())
        if not discovery.ready or not discovery.root:
            raise HTTPException(status_code=409, detail="CARLA runtime is not ready for generated-world validation")
        manager = _runtime_manager(discovery.root)
        existing = manager.read_record() if manager.verify_record() else None
        rpc_port = int(existing["rpc_port"]) if existing else (2000 if port_block_available(2000, 3) else find_free_port())
        owned = False
        try:
            if not existing:
                manager.launch(discovery, require_rendering=False, rpc_port=rpc_port, traffic_manager_port=find_free_port())
                owned = True
            deadline = time.monotonic() + 90.0
            last_error = "CARLA generated-world validation did not become ready"
            while time.monotonic() < deadline:
                try:
                    connect_verified(discovery.python_api_path or "", "127.0.0.1", rpc_port, 2.0)
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(0.5)
            else:
                raise HTTPException(status_code=409, detail=last_error)
            carla_validation = validate_opendrive_dry_run(
                discovery.python_api_path or "", "127.0.0.1", rpc_port, output / "map.xodr"
            )
        finally:
            if owned:
                manager.stop()
        descriptor = prepare_inferred_corridor(
            world_root, output, config, carla_validation=carla_validation
        )
    return {
        "world_id": descriptor.world_id,
        "execution_manifest": str(output / "execution-manifest.json"),
        "structurally_valid": descriptor.validation.structurally_valid,
        "carla_validated": descriptor.validation.carla_validated,
        "ready_for_carla": descriptor.validation.ready_for_carla,
        "warnings": descriptor.validation.warnings,
    }


@app.get("/v1/worlds/{world_id}/execution", dependencies=[Depends(require_token)])
def world_execution(world_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", world_id):
        raise HTTPException(status_code=404, detail="world execution bundle not found")
    matches: list[Path] = []
    for root in _world_roots():
        if not root.is_dir():
            continue
        patterns = (
            f"{world_id}/stages/publish/world/execution/carla-v2-camera-height/execution-manifest.json",
            f"{world_id}/stages/publish/world/execution/carla-v1/execution-manifest.json",
        )
        for pattern in patterns:
            for path in root.glob(pattern):
                if _inside(path, (root,)):
                    matches.append(path)
            if matches:
                break
    if not matches:
        raise HTTPException(status_code=404, detail="world execution bundle not found")
    descriptor = _verified_execution_manifest(matches[0])
    return {"manifest_uri": str(matches[0]), "execution": descriptor.model_dump(mode="json")}


@app.get("/v1/simulations", dependencies=[Depends(require_token)])
def list_simulations() -> dict:
    SIMULATION_ROOT.mkdir(parents=True, exist_ok=True)
    result: list[dict] = []
    for path in sorted(SIMULATION_ROOT.glob("sim-*"), key=lambda value: value.stat().st_mtime, reverse=True):
        if not path.is_dir() or not re.fullmatch(r"sim-[0-9a-f]{16}", path.name):
            continue
        store = SessionStore(SIMULATION_ROOT, path.name)
        try:
            manifest = store.load_manifest()
            outcome = None
            evidence_path = store.session_root / "run-evidence.json"
            if evidence_path.is_file():
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                outcome = evidence.get("outcome")
            terminal_stop_verified = _terminal_stop_verified(store.session_root)
            dynamic_actor_evidence_verified = _dynamic_actor_evidence_verified(
                store.session_root, manifest.scenario.dynamic_actor_profile
            )
            result.append({
                "session_id": path.name,
                "state": store.state().value,
                "outcome": outcome,
                "world_id": manifest.executable_world.world_id,
                "route_id": manifest.route_id,
                "policy_name": manifest.policy.name,
                "observation_source": manifest.observation.source,
                "weather": manifest.scenario.weather,
                "snow_accumulation": manifest.scenario.snow_accumulation,
                "dynamic_actor_profile": manifest.scenario.dynamic_actor_profile,
                "worker_alive": _worker_alive(store),
                "terminal_stop_verified": terminal_stop_verified,
                "dynamic_actor_evidence_verified": dynamic_actor_evidence_verified,
                "session_evidence_verified": (
                    terminal_stop_verified and dynamic_actor_evidence_verified
                ),
                "manifest_uri": str(store.manifest_path),
            })
        except (OSError, ValueError):
            continue
    return {"simulations": result}


@app.post("/v1/simulations", dependencies=[Depends(require_token)])
def create_simulation(
    request: SimulationCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    return _idempotent(
        "create-simulation",
        idempotency_key,
        request.model_dump_json(),
        lambda: _create_simulation(request),
    )


def _create_simulation(request: SimulationCreateRequest) -> dict:
    manifest_path = _validated_local_path(request.world_execution_manifest, file=True)
    execution = _verified_execution_manifest(manifest_path)
    if not execution.validation.ready_for_carla:
        raise HTTPException(
            status_code=409,
            detail="executable world is not ready: structural validation alone does not satisfy the CARLA dry-run gate",
        )
    route = next((item for item in execution.routes if item.route_id == request.route_id), None)
    if route is None:
        raise HTTPException(status_code=400, detail=f"unknown route: {request.route_id}")
    discovery = discover_runtime(persisted_root=_persisted_carla_root())
    if not discovery.ready or not discovery.root:
        raise HTTPException(status_code=409, detail="CARLA runtime is not ready: " + "; ".join(discovery.errors))
    if request.policy.checkpoint_uri:
        checkpoint = _validated_local_path(request.policy.checkpoint_uri, file=True)
        if sha256_file(str(checkpoint)) != request.policy.checkpoint_sha256:
            raise HTTPException(status_code=409, detail="policy checkpoint hash mismatch")
    manager = _runtime_manager(discovery.root)
    server_record = manager.read_record() if manager.verify_record() else None
    rpc_port = int(server_record["rpc_port"]) if server_record else find_free_port()
    traffic_port = int(server_record["traffic_manager_port"]) if server_record else find_free_port()
    while traffic_port == rpc_port:
        traffic_port = find_free_port()
    runtime = CarlaRuntimeDescriptor(
        root=discovery.root,
        executable=discovery.executable or "",
        executable_sha256=discovery.executable_sha256 or "",
        python_api_path=discovery.python_api_path or "",
        python_api_sha256=discovery.python_api_sha256 or "",
        client_version=discovery.client_version or "",
        server_version=(server_record or {}).get("last_health_result", {}).get("server_version") if server_record else None,
        rpc_port=rpc_port,
        traffic_manager_port=traffic_port,
        maps=discovery.maps,
        agents_available=discovery.agents_available,
    )
    session_id = new_record_id("sim")
    store = SessionStore(SIMULATION_ROOT, session_id)
    store.initialize({
        "schema_name": "servo.simulation-session/v1",
        "session_id": session_id,
        # Preserve the optional RealityCI parent so CARLA evidence is born
        # inside the same provenance chain that requested the drive.  The
        # worker copies this field into run-evidence.json; an unbound manual
        # drive remains explicitly null.
        "campaign_id": request.campaign_id,
        "backend": "carla",
        "backend_version": "0.9.16",
        "runtime": runtime.model_dump(mode="json"),
        "executable_world": execution.model_dump(mode="json"),
        "executable_world_manifest_uri": str(manifest_path),
        "route_id": request.route_id,
        "vehicle": request.vehicle.model_dump(mode="json"),
        "sensors": [
            camera.model_dump(mode="json")
            for camera in (request.observation.camera, *request.observation.additional_cameras)
        ],
        "policy": request.policy.model_dump(mode="json"),
        "observation": request.observation.model_dump(mode="json"),
        "controller": {"kind": "direct" if request.policy.adapter == "carla-behavior-reference" else "pure-pursuit-pid", "version": "servo-controller/v1"},
        "scenario": request.scenario.model_dump(mode="json"),
        "timing": request.timing.model_dump(mode="json"),
        "recording": request.recording.model_dump(mode="json"),
        "resource_profile": request.resource_profile,
        "termination_rules": ["collision", "route-departure", "stuck", "timeout", "policy-timeout", "sensor-desynchronization", "renderer-out-of-support", "stop", "route-completion"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    stdout_path = store.session_root / "logs" / "worker.stdout.log"
    stderr_path = store.session_root / "logs" / "worker.stderr.log"
    simulation_python = Path(os.environ.get("SERVO_SIMULATION_PYTHON", sys.executable)).resolve()
    if not simulation_python.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"simulation Python runtime is missing: {simulation_python}",
        )
    argv = [str(simulation_python), "-m", "tools.realityci.simulation.carla.worker", "--manifest", str(store.manifest_path)]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            argv,
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
            shell=False,
        )
    store.record_worker(process.pid, argv)
    return {
        "session_id": session_id,
        "state": "created",
        "worker_pid": process.pid,
        "world_id": execution.world_id,
    }


@app.get("/v1/simulations/{session_id}/state", dependencies=[Depends(require_token)])
def simulation_state(session_id: str) -> dict:
    store = _session_store(session_id)
    payload = json.loads(store.state_path.read_text(encoding="utf-8"))
    payload["worker_alive"] = _worker_alive(store)
    return payload


@app.get("/v1/simulations/{session_id}/live", dependencies=[Depends(require_token)])
def simulation_live(session_id: str) -> dict:
    store = _session_store(session_id)
    if not store.live_path.is_file():
        raise HTTPException(status_code=409, detail="simulation has not published live state yet")
    return store.live().model_dump(mode="json")


@app.get("/v1/simulations/{session_id}/events", dependencies=[Depends(require_token)])
def simulation_events(session_id: str, after_sequence: int = 0) -> dict:
    events = [event.model_dump(mode="json") for event in _session_store(session_id).events.events() if event.sequence > after_sequence]
    return {"session_id": session_id, "events": events}


@app.get("/v1/simulations/{session_id}/policy-frame", dependencies=[Depends(require_token)])
def simulation_policy_frame(session_id: str):
    path = _session_store(session_id).session_root / "previews" / "latest-policy-frame.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="policy frame is not available")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get(
    "/v1/simulations/{session_id}/policy-frame/{camera_id}",
    dependencies=[Depends(require_token)],
)
def simulation_policy_camera_frame(session_id: str, camera_id: str):
    if camera_id not in {"front", "front_left", "front_right"}:
        raise HTTPException(status_code=404, detail="policy camera is not available")
    store = _session_store(session_id)
    manifest = store.load_manifest()
    if camera_id not in manifest.policy.input_camera_ids:
        raise HTTPException(status_code=404, detail="policy camera is not part of this session")
    path = store.session_root / "previews" / f"latest-policy-{camera_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="policy camera frame is not available")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/v1/simulations/{session_id}/integrated-frame", dependencies=[Depends(require_token)])
def simulation_integrated_frame(session_id: str):
    session_root = _session_store(session_id).session_root
    rejection = session_root / "evidence-rejected.json"
    if rejection.is_file():
        raise HTTPException(status_code=409, detail=json.loads(rejection.read_text(encoding="utf-8")))
    path = session_root / "previews" / "latest-servo-t5-carla-lincoln-fixed.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="integrated T5/CARLA frame is not available")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/v1/simulations/{session_id}/evidence", dependencies=[Depends(require_token)])
def simulation_evidence(session_id: str) -> dict:
    store = _session_store(session_id)
    evidence_path = store.session_root / "run-evidence.json"
    if not evidence_path.is_file():
        raise HTTPException(status_code=404, detail="simulation evidence is not available")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    artifact_paths: dict[str, str] = {}
    for relative, expected_hash in evidence.get("artifact_sha256", {}).items():
        candidate = (store.session_root / relative).resolve()
        if not _inside(candidate, (store.session_root.resolve(),)) or not candidate.is_file():
            raise HTTPException(status_code=409, detail=f"evidence artifact is missing or unsafe: {relative}")
        if sha256_file(str(candidate)) != expected_hash:
            raise HTTPException(status_code=409, detail=f"evidence artifact hash mismatch: {relative}")
        artifact_paths[relative] = str(candidate)
    return {"run_evidence_uri": str(evidence_path), "evidence": evidence, "artifact_paths": artifact_paths}


def _simulation_command(session_id: str, command: str) -> dict:
    store = _session_store(session_id)
    state = store.state()
    if state in {SimulationSessionState.COMPLETED, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED}:
        raise HTTPException(status_code=409, detail=f"simulation is terminal: {state.value}")
    store.command(command)
    return {"session_id": session_id, "state": state.value, "command": command}


@app.post("/v1/simulations/{session_id}/pause", dependencies=[Depends(require_token)])
def pause_simulation(session_id: str, request: SimulationCommandRequest = SimulationCommandRequest()) -> dict:
    return _simulation_command(session_id, "pause")


@app.post("/v1/simulations/{session_id}/resume", dependencies=[Depends(require_token)])
def resume_simulation(session_id: str, request: SimulationCommandRequest = SimulationCommandRequest()) -> dict:
    return _simulation_command(session_id, "resume")


@app.post("/v1/simulations/{session_id}/stop", dependencies=[Depends(require_token)])
def stop_simulation(session_id: str, request: SimulationCommandRequest = SimulationCommandRequest()) -> dict:
    return _simulation_command(session_id, "stop")
