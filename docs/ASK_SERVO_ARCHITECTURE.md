# Servo AI Assistant — Full-Control AI Architecture

**Status:** local Gemini control path and bounded agent loop implemented and live-verified 2026-08-30
**Goal:** One AI world where a single model controls **everything** in Servo — runs, worlds, simulations, vehicles, build, settings, weather — through **structured tools and evidence**, not VLM pixel guessing. Every number comes from a durable record; every mutation is a bounded, hash-verified API call.

> Not VLM-first. VLM may assist for frame preview, but the primary control plane is **MCP / structured tools + event logs + error receipts**. This matches the hackathon's Taskmaster + Architecture scoring: event-driven, idempotent, deterministic gates.

## Verified implementation update

The desktop `Servo AI Assistant` workspace now sends natural-language goals to
`POST /v1/ask/agent`. Every turn performs four explicit phases: inspect the
current durable record, let Gemini select one bounded tool, execute it
through deterministic control-plane code, and verify the resulting state,
ordered events, and artifacts. The complete campaign tool executes the real
Google ADK 2.7.1 graph and returns its node trace. Each turn is persisted as a
hash-sealed `servo.ask-servo-agent-run/v1` receipt. The UI does not display a
separate synthetic success banner.

Live agent verification from 2026-08-30:

- Prompt: `Resume the selected campaign and run it through the complete
  agentic loop to a terminal state. Use run_to_completion.`
- Receipt: `askrun-0f577c2f7b7443e0`, content hash
  `sha256:0b63bbb6469d5df8a2075c5aed2aefcf97dd5933b33ddf2c6af6fa59fcdc7d61`.
- Gemini selected `run_to_completion` for campaign
  `cam-91c726ae91e94ccd`; Google ADK 2.7.1 executed 12 node events and the
  verifier re-read 21 ordered domain events plus 80 artifacts.
- Terminal result was `completed_rejected`. The promotion gate correctly
  rejected a candidate that did not satisfy the evidence contract.
- Gemini credentials are read only from the local environment; keys
  are never returned to the UI, logs, or repository.
- Unwired mutation tools return HTTP 501. They never report fake completion.
- In the agent endpoint, that same condition becomes a durable `BLOCKED`
  receipt and no postcondition is presented as successful.

World discovery, execution inspection, simulation listing/state/evidence,
CARLA status, policy listing, inferred weather control, settings inspection,
logs, and errors are wired. Cloud Run deployment remains a later deployment
step; the tested service is the identical local FastAPI application.

---

## 1. What you already built (so Ask Servo has something real to control)

**Desktop (Qt 6.11/QML, Vulkan):** `src/ui/Main.qml` exposes five primary workspaces — Create, Worlds, Runs, Assistant, Settings — plus hidden diagnostic shells sharing one `RealityCIController` model. `WorldLibraryModel` scans the configured reconstruction root for `servo.gaussian-world/v1` + `cameras.json` + PLY hashes. `GaussianSplatView` uses QRhi/Vulkan compute and radix sorting. `ReconstructionController` owns detached builds and durable `job.json` + `events.jsonl`. `SimulationController` polls decimated live records and replays synchronized CARLA evidence. The local DriveMA-2B checkpoint under `runtime/checkpoints/DriveMA-2B` is hash-verified and has completed real CARLA runs.

**Reconstruction:** the selected demo artifact is the accepted
`yosemite-t5-hybrid-full-route-v1-20260828`: 7,720,455 Gaussians, PSNR 24.318,
SSIM 0.798, and 10/12 visual-route checks. World discovery explicitly rejects
the lower-ranked Final v2 identity for Hybrid selection. The world is still
nonmetric, appearance-led, and `collisionValidated=false`; CARLA/OpenDRIVE owns
the separate physical surface.

**RealityCI genetic loop:** `REALITYCI_BACKEND.md:10` — `tools/realityci/orchestrator.py:344` 12-state durable workflow: `pending→baseline_running→failure_triage→diagnosing→experimenting→root_cause_gate→curriculum_planning→training→hidden_exam→regression_check→promotion_gate→reality_debt_update` → terminal. Every step append-only `events.jsonl` with monotonic sequence + idempotency key, content-hash sealed. Hidden seeds 41M+ vs 87M+ disjoint, sealed before training. Promotion is pure code (target+Wilson+beats-baseline+no-regression+hash identity). `adk_graph.py` Google ADK 2.7 SequentialAgent wraps same 12 states, session persistence. `campaign-receipted` demo promoted `7/8` vs `4/8`.

**CARLA:** `CARLA_INTEGRATION.md` packaged 0.9.16 external runtime, `EXECUTABLE_WORLD_BUNDLE.md` `map.xodr+route.json+alignment.json+execution-manifest.json` with `meters_per_servo_unit=12.0 inferred, 30.5m corridor, ready_for_carla true` (dry-run 10.74 m). `SimulationSessionManifest` + `DrivingPolicyDescriptor` + `SimulationLiveState` (speed, acceleration, steering/throttle/brake, gear, route_completion, lateral_error, renderer_coverage, policy_latency, collision counts) + `DrivingRunEvidence` durable.

**Climate:** `CLIMATE_WEATHER_BUNDLE.md` immutable sidecar `servo.climate-weather/v1`; an isolated official reference backend now executes, but its T5 one-step output is quality-rejected. The former Fast Preview shader was deleted.

**Assistant today:** `AiWorkspace.qml` routes prompts through the RealityCI control plane. Gemini 3.7 Flash can select bounded Ask Servo tools for campaigns, worlds, CARLA, simulations, policies, inferred weather, settings, logs, and errors. The UI records the real tool response in the chat model. Tools without an implementation fail closed instead of returning a placeholder success.

---

## 2. Ask Servo design — one bounded control plane

### 2.1 Principles

* **MCP first, VLM optional:** Every capability is a JSON Schema tool with `extra="forbid"` + deterministic HTTP endpoint. Images are preview only; decisions read `events.jsonl` / `run-evidence.json` / `live-state.json`.
* **Evidence before synthesis:** No invented progress, logs, or metrics. `hashing.py` canonical JSON + SHA-256 everywhere.
* **Idempotent + resumable:** Every mutating tool uses `Idempotency-Key` (`cloud/main.py:328`) and campaign `sequence`. Duplicate Pub/Sub delivery is safe.
* **Causal hygiene & safety:** `diagnosis/base.py` propose-only; `exam/promotion.py` deterministic gates LLM cannot override; assistant cannot edit its own tool registry or checkpoint hashes.
* **Three planes:** `Tools` (mutate), `Resources` (read durable state), `Prompts` (genetic loop recipes). Both MCP stdio and HTTP `/v1/ask/*` expose identical logic.

### 2.2 Tool registry — 36 tools in 8 domains (not LLM free-form)

| Domain | Tools | What it mutates/reads | Wired to |
|--------|-------|----------------------|----------|
| **Campaign / Genetic Loop** | `create_campaign`, `step_campaign`, `run_to_completion`, `cancel_campaign`, `list_campaigns`, `get_campaign_state`, `get_campaign_events`, `get_latest_payload`, `get_artifacts`, `explain_failure`, `run_counterfactuals`, `advance_to_root_cause`, `create_curriculum`, `start_training`, `run_hidden_exam`, `show_checkpoint_comparison`, `select_next_weakness` | `CampaignEngine` + `EventLog` + `artifacts-index.json` | `orchestrator.py:308`, `cloud/main.py:582` |
| **Worlds** | `list_worlds`, `get_world_details` (id, source, ply, cameras, depth/structure/coverage, metrics PSNR/SSIM/count/size, scale kind/seed, normalization, limitations), `rename_world`, `delete_world`, `open_world_folder`, `get_world_execution` | `WorldLibraryModel.cpp:672` scan + `world.json` | `simulation/worlds/executable_bundle.py` |
| **Build / Create World** | `get_build_status` (FFmpeg/COLMAP/CUDA/gsplat, VRAM/disk, profile caps 10.5/11 GiB), `estimate_build_storage`, `start_build`, `cancel_build`, `retry_build`, `get_build_logs` | `ReconstructionController.cpp:193` | `tools/reconstruction/servo_worker.py` |
| **CARLA / Execution** | `get_carla_status`, `launch_carla`, `stop_carla`, `preflight_carla`, `prepare_world_for_carla` (meters_per_servo_unit, scale_status, lane_width, driving_side, validate_in_carla), `get_world_execution` | `discovery.py`, `process_manager.py` | `cloud/main.py:747` |
| **Simulation / Drive** | `list_simulations`, `create_simulation` (vehicle, policy, observation source carla-rgb/servo-gaussian/hybrid, scenario seed/weather, timing), `get_simulation_state`, `get_live_state`, `get_simulation_events`, `get_policy_frame`, `get_telemetry`, `pause_simulation`, `resume_simulation`, `stop_simulation` | `SessionStore` + `CarlaSimulationRunner` | `cloud/main.py:929` |
| **Vehicle & Policy** | `list_policies`, `get_policy_details`, `create_tinydrive_checkpoint`, `get_vehicle_metrics` (speed, acceleration, steering, throttle, brake, gear, route_completion, lateral_error, renderer_coverage, policy_latency, collision/lane counts, ego_pose, camera_pose) | `driving/policies/*`, `SimulationLiveState` | `schemas/driving.py:66` |
| **Weather / Appearance** | `set_weather`, `get_weather_state`, `preview_weather` | CARLA physics receipt + inferred Gaussian surface state | clear/snow/smog are provenance-labelled; ClimateNeRF qualification remains separate and fail-closed |
| **System / Settings** | `get_settings` (baseUrl, carla root, reconstruction root, api token), `update_settings`, `get_system_logs`, `get_errors`, `get_metrics` (process CPU/RSS, Vulkan FPS) | `QSettings`, `RuntimeMetrics` | `FRONTEND.md:63` |

Each tool: `name`, `description`, `inputSchema` (Pydantic, `extra="forbid"`), `output` is a sealed record + `request_id`. No tool takes `world_path` outside `_inside()` validated roots.

### 2.3 Resources — what the brain reads without mutating

```
servo://campaign/{id}/events
servo://campaign/{id}/artifacts/{artifactId}
servo://campaign/{id}/diagnosis
servo://world/{id}                 // world.json + cameras.json + hashes
servo://world/{id}/execution       // execution-manifest.json + validation-report
servo://simulation/{id}/live       // 100 ms decimated live-state.json
servo://simulation/{id}/telemetry  // telemetry.jsonl tail
servo://simulation/{id}/evidence   // run-evidence.json hash-verified
servo://build/status               // ReconstructionController dependencies + freeSpace
servo://build/logs/{jobId}         // events.jsonl tail
servo://settings
servo://errors                     // lastError + worker-failure.json
```

Resources are **read-only snapshots** of durable files; the brain never guesses.

### 2.4 Genetic loop as a prompt recipe (self-healing Taskmaster)

```
MODEL -> RUN -> FAILURE -> CAUSAL DIAGNOSIS -> TARGETED EXPERIENCE -> TRAIN -> HIDDEN EXAM -> REGRESSION -> PROMOTE/REJECT -> REALITY DEBT -> NEXT WEAKNESS -> REPEAT
```

MCP prompt `genetic_loop` encodes:

1. `get_build_status` → if not ready, `estimate_build_storage` → `start_build` → poll `get_build_logs` until `worldPublished`
2. `get_world_details` → if not `ready_for_carla`, `prepare_world_for_carla(validate_in_carla=true)` → poll `get_world_execution`
3. `create_campaign(baseline_checkpoint_uri)` → `run_to_completion` or stepwise `step_campaign` + `get_campaign_events` after each transition
4. On `FAILURE_DETECTED`: `explain_failure` → `run_counterfactuals` → `advance_to_root_cause` → if `ROOT_CAUSE_INCONCLUSIVE`, loop with bounded additional experiments
5. `create_curriculum` → `start_training` → `run_hidden_exam` → `show_checkpoint_comparison` → deterministic promotion
6. `select_next_weakness` → if `BLOCKED_MISSING_REALITY`, emit `CaptureMission` resource; else repeat from #3 with next weakness
7. For weather robustness: activate a quality-accepted ClimateNeRF bundle → create a simulation with the same world → compare vehicle metrics; otherwise remain Clear.

Every branch checks `infrastructure_invalid` vs `policy failure` (`REALITYCI_CARLA_CAMPAIGN.md:3`) — infrastructure failures are never diagnosed as policy gaps.

### 2.5 Connection & architecture — implemented and fail-closed boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│ Qt Desktop (Main.qml)                                           │
│  AiWorkspace.qml ── AiChatController (QAbstractListModel)       │
│        │ runLocalAction (r17/snow/rain) + sendMessage           │
│        │  ┌─────────────────────────────────┐                    │
│        └──│ RealityCIController (singleton)│                    │
│           │ SimulationController           │◄── QML bindings    │
│           │ WorldLibraryModel              │    (events, live)  │
│           │ ReconstructionController       │                    │
│           └──────────────┬─────────────────┘                    │
│                          │ Qt Network (Bearer + Idempotency-Key)│
└──────────────────────────┼─────────────────────────────────────┘
                           │ HTTP + GCS optional
┌──────────────────────────▼─────────────────────────────────────┐
│ cloud/control_api/app/main.py (FastAPI, uvicorn / Cloud Run)   │
│  /v1/campaigns, /v1/worlds/*, /v1/simulations/*, /v1/carla/*  │
│  /v1/assistant/* (plan/execute) + /v1/ask/* (expanded Ask)    │
│  GCS mirror, PID-guarded single API, structured errors         │
└──────────────┬──────────────────┬──────────────────────────────┘
               │                  │ stdio JSON-RPC
┌──────────────▼──────┐  ┌────────▼────────────────────────┐
│ tools/realityci/    │  │ tools/realityci/ask_servo/      │
│  orchestrator.py    │  │  mcp_server.py (MCP)            │
│  simulation/*       │◄─┤  tools.py (36 tools)            │
│  driving/*          │  │  resources.py (7 resource roots)│
│  schemas/*          │  │  prompts.py (genetic_loop)      │
└─────────────────────┘  └─────────────────────────────┬───┘
                         ┌─────────────────────────────▼───┐
                         │ Gemini 3.7 Flash /              │
                         │ deterministic fallback (same    │
                         │  SHA, never invents)            │
                         └─────────────────────────────────┘
```

*Desktop wiring:* `Session.qml` already auto-connects `RealityCIController.connectToServer()` + `SimulationController.connectToServer()` on startup (`Main.qml:67`). New: `AiChatController.isCampaignPrompt` extended to route **any** Ask prompt through `RealityCIController.executeAssistantPrompt` → `assistant_tools.plan_tool` → `_execute_tool` (deterministic gates). No VLM image upload required; camera frames are `resources` if needed.

*MCP transport:* `tools/realityci/ask_servo/mcp_server.py` runs as `python -m tools.realityci.ask_servo.mcp_server` (stdio). Desktop `Start-Servo.ps1` can launch it alongside `uvicorn` on `SERVO_MCP_ENABLED=1`. Claude/Cursor/Windsurf connect via `mcp.json` pointing to same Python. Both transports call identical `ask_servo/tools.py` implementations — no duplication.

*Agent-turn desktop path:* `AiWorkspace.qml` routes operational goals through
`RealityCIController.executeAskPrompt` to `/v1/ask/agent`. The returned chat
bubble contains the plan, every completed/blocked phase, evidence IDs, ADK
identity when applicable, and the sealed receipt hash. Camera frames remain
optional read-only resources; decisions come from durable records.

*AI cannot control itself:* `assistant_tools` never exposes `update_tool_registry`, `edit_checkpoint_hash`, `modify_promotion_gate`, or `change_api_token`. `SECURITY_AND_PROVENANCE.md` audit blocks path escape, command injection, and credential leakage.

### 2.6 Vehicle metrics — complete

`SimulationLiveState` (`schemas/simulation.py:263`) already emits for every 100 ms `live-state.json`:

`sequence, authoritative_frame, simulation_time_s, ego_pose_carla/servo, policy_camera_pose_servo, speed_mps, acceleration_mps2, steering, throttle, brake, gear, target_speed_mps, route_completion, lateral_error_m, renderer_coverage, policy_latency_ms, policy_frame_id, collision_count, lane_invasion_count, deadline_miss_count, current_result, last_failure, process_health`

`DrivingRunEvidence` adds `distance_traveled_m, route_completion, mean/max lateral_error, mean/max latency, collision/lane counts, out_of_support_duration` + full `policy` descriptor + `route_sha256`.

Ask's `get_vehicle_metrics` aggregates both plus policy identity, weather receipt, gravity/contact evidence, and source provenance. The DriveMA 2B external-driving adapter uses the hash-bound local checkpoint and loopback model service; the verified T5 snow run completed without an oracle or privileged state.

Build page metrics: `ReconstructionController` `dependencies` (FFmpeg/COLMAP/CUDA/gsplat kernel), `freeSpaceText`, `capacityReady`, `progress` stage + `events.jsonl` tail.

---

## 3. How to use

```powershell
# 1. Local API + MCP together
$env:SERVO_RECONSTRUCTION_ROOT="D:\Servo\runtime\reconstruction"
powershell -File .\Start-Servo.ps1   # starts uvicorn on 8000 + optional MCP if SERVO_MCP_ENABLED=1

# 2. List tools (both transports)
curl http://127.0.0.1:8000/v1/ask/tools
# or MCP: tools/list over stdio

# 3. Run a verified agent turn. Use provider=gemini for the configured Vertex
# path, provider=gemini, or deterministic for a repeatable offline
# test. Never place credentials in the JSON body.
curl -X POST http://127.0.0.1:8000/v1/ask/agent -H "Content-Type: application/json" -H "Idempotency-Key: demo-agent-01" -d '{"prompt":"Run the selected campaign through the agentic loop","provider":"gemini","campaign_id":"cam-...","verify":true}'

# 4. Read the hash-sealed receipt returned by the previous call.
curl http://127.0.0.1:8000/v1/ask/agent-runs/askrun-...

# 5. MCP config (Claude/Cursor)
#  .mcp.json → { "mcpServers": { "ask-servo": { "command": "python", "args": ["-m","tools.realityci.ask_servo.mcp_server"], "env": {"SERVO_RECONSTRUCTION_ROOT":"..."} } } }
```

All `POST` mutating calls accept `Idempotency-Key: <uuid>` and return `request_id` for log correlation.

In the desktop, open **Servo AI Assistant**, select Gemini 3.7 Flash, and ask:
`Run the selected campaign through the agentic loop`. Select a campaign in
Runs first. If no campaign is selected, Servo stops with a `BLOCKED` receipt
instead of choosing an unrelated campaign. `New` clears only the chat; it does
not delete campaign records or agent receipts.

---

## 4. Remaining work after the verified local build

* Produce one same-campaign T5 Hybrid → CARLA failure → diagnosis → training → hidden-exam receipt; the current physical and training proofs are separate.
* Add `per-step training curves` streaming from `tools/realityci/trainers/*` into `TrainWorkspace.qml` (currently placeholder)
* Qualify a full ClimateNeRF semantic snow checkpoint; current snow is explicitly generated/inferred, not ClimateNeRF-qualified.
* Add traffic actors and traffic-light scenarios to the real CARLA campaign.
* Acquire metric scale and independently validated collision structure for autonomous-driving claims.
* Deploy the already-tested FastAPI/ADK control plane to the hackathon cloud project.

This document is the control-plane spec. Implementation lives in `tools/realityci/ask_servo/*` + expanded `cloud/control_api/app/main.py:ask/*`.
