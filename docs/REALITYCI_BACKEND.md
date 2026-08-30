# RealityCI Backend Architecture

The autonomous improvement loop for physical-AI policies, implemented as
real, verified code under `tools/realityci/`, `tests/realityci/`, and
`cloud/`.  Every number in every artifact comes from executed code; nothing
is mocked, simulated as a stand-in for reality, or fabricated.

## The loop

```text
CAMPAIGN
  -> baseline run          (deterministic scenario runner + trained policy)
  -> FAILURE_DETECTED      (deterministic evaluators over measured telemetry)
  -> hypotheses            (Gemini structured diagnostician or deterministic fallback)
  -> counterfactuals       (immutable derived scenarios x seed arms)
  -> ROOT_CAUSE_ESTABLISHED (deterministic causal gate over outcomes only)
  -> curriculum            (targeted pools; hidden seeds sealed BEFORE training)
  -> candidate checkpoint  (real PyTorch fine-tune; hash must change)
  -> hidden exam           (sealed vault opened by examiner only)
  -> regression suites     (protected capabilities vs configured floors)
  -> promotion/rejection   (pure code; LLM cannot override)
  -> capability + debt     (reproducible formula) -> next weakness -> repeat
```

## State owners

| CampaignState | Owner (module:function) |
|---|---|
| pending | orchestrator.CampaignEngine._h_intake |
| baseline_running | _h_run_baseline |
| failure_triage | _h_triage |
| diagnosing | _h_diagnose |
| experimenting | _h_experiments |
| root_cause_gate | _h_root_cause |
| curriculum_planning | _h_curriculum |
| training | _h_train |
| hidden_exam | _h_hidden_exam |
| regression_check | _h_regression |
| promotion_gate | _h_promotion |
| reality_debt_update | _h_reality_debt |

Transitions are enforced by `tools/realityci/state_machine.py`
(`assert_transition`); unknown transitions and terminal-state writes raise.

## Module map

| Module | Responsibility |
|---|---|
| `hashing.py` | canonical JSON, SHA-256 content addressing, idempotency keys |
| `schemas/` | versioned Pydantic records (`extra="forbid"`, frozen, sealed) |
| `scenario/projection.py` | declared virtual pinhole camera |
| `scenario/dynamics.py` | kinematics, 3D sightline occlusion, collision truth |
| `scenario/compositor.py` | painter's-algorithm frames: observed background + synthetic actors |
| `scenario/runner.py` | fixed-dt integration, sensor-rate perception hold with hysteresis, oracle overrides |
| `pools.py` | deterministic scenario families (clear / occluded / empty / irrelevant) |
| `policy/torch_perception.py` | HazardCNN v2 (2-frame stack + ego speed), content-addressed checkpoints |
| `policy/onnx_inference.py` | inference-only adapter proving honest non-trainability |
| `trainers/dataset.py` | ground-truth hazard labels (never policy-derived) |
| `trainers/torch_behavior_cloning.py` | seeded BC trainer, early stop, weight-change proof |
| `evaluate.py` | suite evaluation harness and matrices |
| `failure/evaluators.py` | deterministic failure classification |
| `failure/evidence_writer.py` | durable evidence bundles, path containment, artifact hashes |
| `diagnosis/base.py` | Diagnostician contract: propose-only, never establish |
| `diagnosis/deterministic.py` | auditable rule-based hypothesis generator |
| `diagnosis/gemini.py` | google-genai structured-output client, schema-fail-closed |
| `diagnosis/experiments.py` | intervention registry; derived manifests are pure functions of parent+patch |
| `diagnosis/causal_gate.py` | attribution rules with seed-majority consistency |
| `curriculum/seed_vault.py` | structural seed-space partitioning; sealed hidden manifests |
| `curriculum/planner.py` | targeted curriculum (60% weakness-focused) + dataset manifest |
| `exam/examiner.py` | opens vault via authorized path only; Wilson intervals |
| `exam/regression.py` | protected-suite guardian |
| `exam/promotion.py` | truth-table gate; identity + isolation checks |
| `capabilities/register.py` | state machine per capability; debt formula; next-weakness selector |
| `capabilities/world_scout.py` | BLOCKED_MISSING_REALITY → sealed capture missions |
| `assistant_tools.py` | bounded Gemini/OpenAI tool planner; ten explicit campaign tools only |
| `adk_graph.py` | Google ADK 2.7 SequentialAgent over the 12 pipeline states; durable resume |
| `security_audit.py` | secret/path/license release gate → docs/SECURITY_AND_PROVENANCE.md |
| `orchestrator.py` | fsync'd event log, atomic state, idempotent resumable steps |
| `cli.py` | `train-baseline`, `evaluate`, `run-campaign` (+ PASS/FAIL receipt) |

## Guarantees enforced by code

1. **Determinism**: identical scenario inputs produce byte-identical runs;
   derived counterfactual IDs/hashes are pure functions of parent+patch.
2. **Causal hygiene**: hypotheses propose; only executed outcomes +
   `causal_gate` establish; oracle planner sees ONLY the perception stream.
3. **Hidden isolation**: training seeds (41M+) and hidden seeds (87M+) are
   disjoint by construction; hidden manifests are sealed with a SHA receipt
   the trainer side never receives.
4. **Promotion is code**: gate checks target success, Wilson lower bound,
   beats-baseline, protected regressions, checkpoint identity across exam
   and regression records, and isolation receipt presence.
5. **Idempotency/resume**: events carry monotonic sequence + idempotency
   key; re-running a terminal campaign emits nothing.
6. **Safe assistant boundary**: Gemini/OpenAI may select an allowlisted tool,
   but only deterministic campaign code changes state or decides promotion.
7. **Local API lifecycle**: token authentication (when configured), persistent
   request idempotency, structured errors, cancellation, artifact retrieval,
   campaign listing, restart/resume, reconnecting clients, and a PID-guarded
   single local API process.

## Honest limitations (current build)

- Gemini diagnostician requires `GEMINI_API_KEY`/Vertex credentials; without
  them the deterministic diagnostician runs (clearly labeled as such).
- Model parity with the desktop AI Chat
  (`src/ui/chat/AiChatController.cpp`): same credential path
  (`GOOGLE_API_KEY` / `GEMINI_API_KEY` → `x-goog-api-key` on the
  Generative Language API) and same catalog — `gemini-3.7-flash`
  (diagnostician default), `gemini-3.5-flash` (telemetry compression),
  `gemini-2.5-pro` (second opinion). Override per campaign with
  `run-campaign --gemini-model <id>`.
- Cloud deployment needs GCP credentials; see `cloud/infra/README.md`.
- `google-adk` 2.7.1 (latest) is installed in the overlay env
  `.venv-realityci` (`--system-site-packages` over the locked reconstruction
  venv); run ADK tests with that interpreter.
- Scenario world is a straight-road virtual scene with procedural or
  observed-frame backgrounds; collision truth is deterministic scenario
  state, never Gaussian geometry.

## Run it

```powershell
$py = 'C:\Users\wenje\AppData\Local\Servo\reconstruction\venv-py311-cu128\Scripts\python.exe'

# full test suite
& $py -m pytest tests\realityci -q

# one-command autonomous campaign (fail -> diagnose -> train -> verify -> promote)
& $py -m tools.realityci.cli run-campaign `
    --output D:\Servo\demo\occluded_pedestrian\campaign-01 `
    --checkpoint D:\Servo\demo\occluded_pedestrian\baseline\baseline.pt

# re-train the baseline from scratch if desired
& $py -m tools.realityci.cli train-baseline --output D:\Servo\demo\occluded_pedestrian\baseline --count 96 --epochs 40
```

## Desktop client and control API (wired)

The Qt desktop app ships a real HTTP client singleton
(`src/ui/realityci/RealityCIController.{h,cpp}`). The primary Runs workspace
now presents one campaign journey: Failure, Diagnosis, Experiments, Training,
Verification, Decision, Reality Debt, and Next action. The disconnected
Diagnose / Train / Verify / Capabilities workbench shells are not primary
navigation. It never invents campaign data: every record comes from the API's
durable event log.

```powershell
# serve the API locally (no credentials needed)
& $py -m uvicorn cloud.control_api.app.main:app --port 8000

# then in Servo: Runs -> API URL http://127.0.0.1:8000 -> Connect ->
# Create Campaign -> Start Run. The Assistant can also invoke the same bounded
# tools using Gemini or OpenAI. Point at Cloud Run later; only the URL changes.
```

Control API surface:

- `GET /v1/campaigns`, `GET /v1/campaigns/{id}/state`, and `/events`
- `POST /v1/campaigns/{id}/run`, `/resume`, `/step`, and `/cancel`
- `GET /v1/campaigns/{id}/artifacts` and hash-bound artifact download
- `GET /v1/assistant/tools`, `POST /v1/assistant/plan`, and `/execute`
- explicit tool execution for create/start/status/explain/counterfactuals/
  training/hidden-exam/comparison/cancel/next-weakness

`Start-Servo.ps1` owns `tmp/local-control-api/api.pid`, reuses a healthy local
listener, removes stale ownership, and refuses to launch a second unhealthy
recorded process.

## Verification receipt (2026-08-27)

- RealityCI Python suite: **110 passed, 2 optional skips**.
- Google ADK environment: **3 passed**, including fresh-process resume,
  byte-stable terminal replay, no duplicate idempotency keys, and recovery
  from an interrupted campaign.
- Native Qt/QML build: successful; CTest: **10/10 passed**.
- Live HTTP smoke: one local API listener; a campaign traversed the complete
  loop and ended `completed_rejected` through the deterministic safety gate;
  80 artifacts were retrievable.

The Gemini and OpenAI structured providers are implemented and schema-tested.
The receipt above does not claim that a paid external model request was made;
its live assistant smoke used the deterministic planner so verification was
repeatable and cost-free.

Campaign gates and sizes are stored in the sealed `campaign.json` record at
create time and are reconstructed from it on every resumed step, so strict
and relaxed gate configurations both round-trip exactly (verified live:
strict 0.90/0.50 rejects, golden 0.85/0.30 promotes).
