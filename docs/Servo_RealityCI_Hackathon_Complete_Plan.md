# Servo / RealityCI — Complete Hackathon Build Plan

**Prepared:** 2026-08-23
**Submission deadline:** 2026-08-31, 5:00 PM Pacific
**Recommended track:** **The Taskmaster**
**Working product name:** **Servo — RealityCI for Physical AI**

---

## 1. Executive decision

Build **one complete, real, evidence-producing autonomous loop**, not a broader simulator and not another reconstruction-only iteration.

The submission should demonstrate this exact story:

> Give Servo a physical-AI policy, a world, and a capability objective. Servo runs the policy, detects a failure, uses Gemini to design and execute causal counterfactual experiments, identifies the failed capability, creates a targeted curriculum, launches an actual training job, evaluates the resulting checkpoint on hidden scenarios, checks regressions, promotes or rejects it, updates Reality Debt, and selects the next weakness without a human manually directing each step.

The end-to-end loop is:

```text
MODEL
  -> RUN
  -> FAILURE
  -> CAUSAL DIAGNOSIS
  -> TARGETED EXPERIENCE
  -> TRAIN
  -> HIDDEN EXAM
  -> REGRESSION TEST
  -> PROMOTE OR REJECT
  -> UPDATE REALITY DEBT
  -> SELECT NEXT WEAKNESS
  -> REPEAT
```

Gaussian reconstruction remains visually important, but it is **an evidence-backed appearance subsystem**, not the product and not the collision engine.

### The only viable hackathon scope

Implement one polished scenario:

- Ego vehicle follows the reconstructed Yosemite road.
- A pedestrian emerges from behind an occluding parked vehicle.
- The baseline policy detects the pedestrian too late and collides.
- The Diagnostician considers multiple hypotheses.
- Counterfactuals isolate the perception failure:
  - remove the occluder;
  - reveal the pedestrian earlier;
  - replace perception with oracle perception;
  - replace planning with an oracle planner.
- Gemini establishes the causal capability gap: **late pedestrian detection under partial occlusion**.
- Servo generates a bounded curriculum across occlusion, speed, crossing angle, contrast, and lighting.
- A real small PyTorch perception/policy model is retrained.
- A completely hidden scenario suite passes.
- Previously learned scenarios remain above their regression thresholds.
- The checkpoint is promoted and the capability changes from failed to verified.
- Servo automatically queues the next weakness.

That sequence is sufficiently broad to demonstrate a general architecture while remaining buildable in the remaining week.

---

## 2. What is already strong

Servo is not an empty hackathon shell. It already contains several unusually credible foundations:

1. A native Qt/QML desktop application with workspaces for world creation, runs, diagnosis, training, verification, and capabilities.
2. A durable, checkpointed media-to-Gaussian pipeline using FFmpeg, COLMAP, PyTorch, CUDA, gsplat, semantic masks, depth priors, quality gates, and immutable receipts.
3. A native Vulkan Gaussian viewer with SH3 rendering and diagnostic views.
4. Honest provenance and rejection logic instead of fabricated quality or safety claims.
5. A clear product concept: autonomous CI/CD for physical AI.

These foundations can score well on architecture and production readiness **only after the currently disabled agent workspaces become connected to real services**.

---

## 3. Current state: honest assessment

### 3.1 Public repository state

The public repository currently proves the reconstruction foundation, not the hackathon’s required autonomous agent system.

The visible UI contains the right concepts, but the central services are placeholders:

- `RunsWorkspace.qml`: `runnerAvailable: false`
- `DiagnoseWorkspace.qml`: `diagnosisServiceAvailable: false`
- `TrainWorkspace.qml`: `trainerAvailable: false`
- `VerifyWorkspace.qml`: `verifierAvailable: false`
- `CapabilitiesWorkspace.qml`: `acquisitionServiceAvailable: false`
- `Session.qml`: run, failure, experiment, training, checkpoint, and capability models default to `null`

The public tree also has no implemented Gemini, Google ADK, Vertex AI, Firestore, Pub/Sub, or Cloud Run control plane.

### 3.2 Public/local synchronization problem

The uploaded r12 handoff describes newer local work than public `main`:

- local r12 trainer/audit work exists;
- the public README still leads with r9 and historical r6;
- the public audit script still declares an older audit schema;
- the local worktree is dirty and contains unrelated UI edits.

This is a judge-facing risk. Before adding cloud work:

1. create a clean hackathon integration branch;
2. preserve all unrelated UI changes;
3. commit only verified r12 source/test changes and selected documentation;
4. never commit diagnostic outputs, models, videos that violate licensing, API keys, or local absolute paths;
5. update the README to accurately distinguish public r12 code from local-only artifacts.

### 3.3 Current r12 reconstruction quality

The r12 handoff reports real improvements, but it also proves that more blind training is not the answer:

- 1,465,378 retained Gaussians;
- held-out PSNR: 22.3845 dB;
- held-out SSIM: 0.73730, below the existing 0.75 release threshold;
- 54.53% of supported samples remain above 10% relative depth spread;
- worst-view sky alpha p95 remains approximately 0.9992;
- dynamic-region alpha p95 remains approximately 0.9999;
- no metric scale, collision surface, certified road topology, dynamic object layers, or exact r12 free-movement audit.

The world is useful as a visual background and measured reconstruction artifact. It is not yet valid collision geometry.

---

## 4. Track selection and positioning

## Recommended track: The Taskmaster

The Taskmaster rewards event-driven autonomous routing: the system watches for a change, determines what happens next, invokes tools, handles a multi-step workflow, and finishes without constant human guidance.

RealityCI maps directly:

| Taskmaster expectation | Servo proof |
|---|---|
| Event-driven trigger | `FAILURE_DETECTED` from a policy run |
| Autonomous routing | Scientist decides whether to diagnose, retrain, reject, or request reality |
| Multi-step workflow | run → diagnose → experiment → train → exam → regression → promotion |
| Real action | executes scenarios, starts a training job, writes checkpoints, changes durable state |
| Long-running state | Firestore campaign state and resumable ADK workflow |
| Failure handling | idempotent events, retries, checkpoint hashes, deterministic gates |
| Visible completion | capability status and Reality Debt update in the desktop app |

### Secondary prize targets

Prioritize, in this order:

1. **Taskmaster track prize**
2. **Best Architecture**
3. **Best Multimodal Experience / UX**, when offered in the submission form
4. **Individual or Hobbyist prize**, only when the entrant qualifies
5. **Startup Excellence**, only when an eligible incorporated organization and corporate email satisfy the rules

Do not switch to Collaborative Partner. Dialogue is not Servo’s core. Do not switch to Fortified Enterprise Fleet unless the managed enterprise-agent platform is genuinely implemented; adding superficial registry/security labels would weaken credibility.

---

## 5. Critical eligibility and submission checks

Treat these as blockers, not paperwork:

1. Confirm every entrant satisfies the published age-of-majority requirement in their jurisdiction.
2. Ensure the project’s qualifying work began within the hackathon period. The repository’s initial August 9 commit appears compatible, but disclose any pre-existing libraries, UI assets, or code reused from earlier projects.
3. Use Gemini 3.5 or newer.
4. Use at least one accepted Google agent framework. Use Google ADK as the primary framework.
5. Run meaningful backend work on Google Cloud and show visible proof in the four-minute demo.
6. Upload a required architecture diagram.
7. Provide reproducible README setup and testing instructions.
8. Keep the demonstration video at or below four minutes; judges may evaluate only the first four minutes.
9. Make the repository accessible to judges and test it in an incognito browser.
10. Do not change linked submission materials after the deadline.

---

## 6. Product definition

## 6.1 One-sentence pitch

**Servo is autonomous CI/CD for physical AI: it discovers what a robot or vehicle policy cannot do, proves why it failed, creates the missing experience, trains a candidate, independently tests generalization and regressions, and promotes only evidence-backed improvements.**

## 6.2 The problem

Physical-AI teams still manually:

- replay failures;
- inspect sensor frames and telemetry;
- guess root causes;
- choose new scenarios;
- launch training;
- evaluate checkpoints;
- detect regressions;
- decide what the model should learn next.

The bottleneck is not only simulation. It is **who autonomously controls the entire capability-closing development cycle**.

## 6.3 Product differentiator

Do not pitch “video to Gaussian world” or “automatic simulation training.” Those are crowded.

Pitch the following combined contract:

- policy-adapter interface rather than a claim to train every model;
- causal counterfactual diagnosis rather than LLM speculation;
- targeted curriculum creation;
- real checkpoint production;
- hidden generalization testing;
- protected regression suites;
- deterministic promotion or rejection;
- capability memory and Reality Debt;
- missing-reality detection and capture mission generation;
- evidence and provenance at every stage.

---

## 7. What not to build before submission

Do not spend the remaining week on any of these until the complete loop works:

- universal CARLA and MuJoCo integrations;
- ROS2 support;
- arbitrary customer models;
- full 4D Gaussian reconstruction;
- collision-valid metric reconstruction from the current monocular video;
- a full OpenDRIVE map;
- a production StopThePop renderer;
- NVIDIA ArtiFixer integration;
- TRELLIS asset generation;
- a large VLA fine-tune;
- a web marketplace or multi-tenant billing system;
- five half-working agents;
- a chatbot panel that only describes actions.

The winning demo is one complete causal learning loop with durable evidence.

---

## 8. Final architecture

## 8.1 Desktop plane

Keep the current application:

- Qt 6 + QML UI
- C++20 runtime
- Vulkan Gaussian viewer
- existing reconstruction worker and world library

Add a narrow client layer:

```text
src/ui/realityci/
  RealityCIClient.h/.cpp
  RealityCIEventModel.h/.cpp
  RunModel.h/.cpp
  FailureModel.h/.cpp
  ExperimentModel.h/.cpp
  TrainingJobModel.h/.cpp
  CheckpointModel.h/.cpp
  CapabilityModel.h/.cpp
```

Responsibilities:

- authenticate to the Cloud Run API;
- create a campaign;
- poll or stream ordered events;
- fetch artifact metadata and signed URLs;
- update the existing workspace models;
- never invent progress when the backend is unavailable;
- show explicit local/cloud connection state.

Use the current JSON Lines/event mindset. Do not embed agent logic in QML.

## 8.2 Google control plane

```text
cloud/control_api/
  app/main.py                 FastAPI service on Cloud Run
  realityci/workflow.py       ADK graph/workflow
  realityci/agents/
    scientist.py
    diagnostician.py
    curriculum_planner.py
    examiner.py
    world_scout.py
  realityci/tools/
    scenario_tools.py
    training_tools.py
    artifact_tools.py
    state_tools.py
  realityci/schemas/
    events.py
    campaigns.py
    failures.py
    experiments.py
    checkpoints.py
    capabilities.py
```

Use:

- **Google ADK 2.x** for orchestration and resumable graph logic;
- **Gemini 3.7 Flash** for the main Scientist, causal reasoning, and curriculum planning;
- **Gemini 3.5 Flash-Lite** for inexpensive event classification and telemetry compression;
- optionally **Gemini Robotics-ER 2** as an independent physical/spatial second opinion over selected frames;
- **Vertex AI** for production Gemini access;
- **Cloud Run** for the API;
- **Firestore** for campaign state, event indexes, decisions, capability debt, and idempotency records;
- **Pub/Sub** for durable domain events;
- **Cloud Storage** for frames, telemetry bundles, scenario manifests, checkpoints, reports, and videos;
- **Cloud Run Jobs** for scenario batches, training, hidden exams, and regression runs.

## 8.3 Execution plane

For the hackathon, create a compact deterministic scenario runner in Python.

```text
tools/realityci/
  scenario_runner.py
  scenario_schema.py
  render_compositor.py
  collision.py
  oracle.py
  evidence_writer.py
  policy_adapters/
    base.py
    torch_perception.py
    onnx_inference.py
  trainer_adapters/
    base.py
    torch_behavior_cloning.py
  exam_runner.py
```

The runner should use:

- pre-rendered registered/off-axis background frames from the Gaussian world;
- explicit, provenance-tagged controllable actor layers;
- a deterministic kinematic state for ego, pedestrian, and occluder;
- a small image-based perception model plus deterministic planner/controller;
- seeded scenario variation;
- collision and near-miss calculations independent of Gaussian geometry.

This preserves the correct architecture: Gaussian splats render appearance; deterministic state owns physics and ground-truth actor positions.

---

## 9. The demo policy

## 9.1 Policy decomposition

Use a small real model that can retrain in seconds or minutes:

```text
Sensor frame stack (e.g. 3 x 96 x 160 RGB)
         + ego speed
         + optional previous brake
              |
        Small CNN encoder
              |
  pedestrian risk / TTC estimate
              |
   deterministic brake planner
              |
        brake command [0,1]
```

The baseline checkpoint is intentionally trained without sufficiently occluded pedestrians. It should pass ordinary crossings but fail the selected partial-occlusion range.

The target training adapter performs behavior cloning from oracle labels on generated curriculum scenarios. The model weights and checkpoint hash must actually change.

## 9.2 Why not use the full VLA in the demo

A large VLA adds long training time, uncertain integration, and a weak chance of producing a visible improvement by the deadline. Servo’s product claim is policy-adapter orchestration, not that one exact VLA is required.

Architect the interface so a VLA can be added later. Demonstrate:

- one trainable PyTorch adapter;
- one inference-only ONNX adapter that receives diagnosed failure sets and datasets but cannot be retrained by Servo.

This proves honest model-agnostic integration without claiming universal training support.

---

## 10. Scenario and evidence contracts

## 10.1 Scenario manifest

Every scenario should be immutable and content-addressed.

```json
{
  "schema": "servo.scenario/v1",
  "scenarioId": "occ-ped-hidden-0042",
  "seed": 42,
  "worldId": "yosemite-r12",
  "route": {"startS": 12.0, "endS": 58.0},
  "ego": {"initialSpeedMps": 13.4},
  "actors": [
    {
      "type": "pedestrian",
      "crossingSpeedMps": 1.6,
      "emergenceS": 41.5,
      "crossingAngleDeg": 87.0
    },
    {
      "type": "occluder_vehicle",
      "positionS": 39.0,
      "lateralOffsetM": 2.1
    }
  ],
  "appearance": {
    "brightness": 0.8,
    "contrast": 0.75,
    "weatherTag": "clear"
  },
  "provenance": {
    "background": "observed-gaussian-render",
    "actors": "synthetic-controllable",
    "collisionTruth": "deterministic-scenario-state"
  }
}
```

## 10.2 Run evidence bundle

```json
{
  "schema": "servo.run-evidence/v1",
  "runId": "run-...",
  "policyCheckpoint": "sha256:...",
  "scenarioHash": "sha256:...",
  "result": "collision",
  "collision": {
    "timeSeconds": 4.82,
    "relativeSpeedMps": 9.3
  },
  "firstGroundTruthVisibilityTime": 3.21,
  "firstPolicyDetectionTime": 3.93,
  "brakeCommandTime": 4.06,
  "artifacts": {
    "frames": "gs://...",
    "telemetry": "gs://...",
    "video": "gs://..."
  }
}
```

## 10.3 Causal hypothesis contract

Gemini may propose hypotheses, but the system may establish a root cause only from executed interventions.

```json
{
  "schema": "servo.causal-diagnosis/v1",
  "failureId": "failure-...",
  "hypotheses": [
    {"id": "H1", "claim": "pedestrian was never detected"},
    {"id": "H2", "claim": "pedestrian was detected too late"},
    {"id": "H3", "claim": "planner failed to brake"},
    {"id": "H4", "claim": "controller could not execute braking"},
    {"id": "H5", "claim": "partial occlusion caused the late detection"}
  ],
  "requiredExperiments": ["remove_occluder", "oracle_perception", "oracle_planner"],
  "status": "proposed"
}
```

A deterministic root-cause gate verifies that the expected experimental pattern exists before changing status to `established`.

## 10.4 Checkpoint promotion contract

Promotion must be deterministic and independent of the LLM.

Example gates:

- target hidden-exam success ≥ 90%;
- lower 95% confidence bound ≥ 80%;
- no protected capability decreases by more than 3 percentage points;
- no severity-1 safety scenario regresses;
- checkpoint and dataset hashes verified;
- hidden seeds were never exposed to the Trainer agent;
- all required artifacts exist.

---

## 11. ADK workflow

Use one durable graph rather than loosely chatting agents.

```text
Campaign Intake
      |
      v
Baseline Runner ----------------------------+
      |                                      |
      v                                      |
Failure Triage                               |
      | no failure                           |
      +------------------> Capability update |
      | failure                              |
      v                                      |
Diagnostician                                |
      |                                      |
      v                                      |
Experiment Planner                           |
      |                                      |
      v                                      |
Parallel Counterfactual Executors            |
      |                                      |
      v                                      |
Causal Root-Cause Gate                       |
      | insufficient evidence -> more tests -+
      | established
      v
Curriculum Planner
      |
      v
Training Job
      |
      v
Hidden Examiner
      |
      v
Regression Guardian
      |
      v
Promotion Gate
  | pass                 | fail
  v                      v
Promote              Reject / revise
  |                      |
  +----------+-----------+
             v
Reality Debt Updater
             |
             v
Next-Weakness Selector
```

### Agent roles

**Scientist / Orchestrator**

- owns long-term campaign objective;
- chooses the next workflow branch;
- cannot directly mark a capability learned;
- cannot modify evaluation code.

**Diagnostician**

- reads run evidence and selected images/video;
- produces ranked hypotheses and experiments;
- must state uncertainty and competing explanations.

**Experiment Planner**

- converts hypotheses into bounded interventions supported by the scenario runner;
- estimates cost and information gain;
- cannot invent unavailable simulator controls.

**Curriculum Planner**

- creates a scenario distribution around the established capability gap;
- reserves hidden seeds before training;
- limits compute budget and stops on plateau/regression.

**Examiner**

- runs on hidden scenarios never exposed to curriculum generation;
- may use a separate model or deterministic evaluator;
- publishes results but cannot promote.

**Regression Guardian**

- reruns protected capability sets;
- rejects checkpoints that cross configured degradation thresholds.

**WorldScout**

- searches authorized local/customer evidence metadata;
- when evidence is absent, emits a structured capture mission;
- does not scrape or generate unlicensed training data by default.

---

## 12. Event model and reliability

Use explicit events:

```text
CAMPAIGN_CREATED
BASELINE_RUN_REQUESTED
RUN_STARTED
RUN_COMPLETED
FAILURE_DETECTED
DIAGNOSIS_REQUESTED
HYPOTHESES_PROPOSED
EXPERIMENT_BATCH_REQUESTED
EXPERIMENT_COMPLETED
ROOT_CAUSE_ESTABLISHED
CURRICULUM_CREATED
TRAINING_REQUESTED
TRAINING_STARTED
CHECKPOINT_READY
HIDDEN_EXAM_REQUESTED
HIDDEN_EXAM_COMPLETED
REGRESSION_REQUESTED
REGRESSION_COMPLETED
CHECKPOINT_PROMOTED
CHECKPOINT_REJECTED
CAPABILITY_UPDATED
MISSING_REALITY_DETECTED
CAPTURE_MISSION_CREATED
CAMPAIGN_COMPLETED
```

Each event needs:

- stable `eventId`;
- `campaignId`;
- monotonically increasing sequence number;
- event schema/version;
- idempotency key;
- timestamp;
- producer;
- payload hash;
- parent event and causation ID;
- artifact references;
- retry count and terminal state.

Pub/Sub is at-least-once delivery. Every consumer must be idempotent. Store processed idempotency keys in Firestore before committing side effects.

---

## 13. Google AI model use

Use model roles because they are genuinely different, not only for bonus points.

### Gemini 3.7 Flash — main reasoning model

Use for:

- causal hypothesis generation;
- selecting informative counterfactuals;
- curriculum planning;
- explaining promotion/rejection evidence;
- multimodal inspection of selected frames and telemetry summaries.

Require structured JSON output validated with Pydantic. Never execute free-form commands returned by the model.

### Gemini 3.5 Flash-Lite — high-volume worker

Use for:

- classifying events;
- compressing long telemetry traces;
- extracting structured fields from logs;
- routing mundane cases;
- generating concise UI summaries from already verified records.

### Gemini Robotics-ER 2 — optional independent physical adjudicator

Use only after the core loop works. Give it selected frames and ask for an independent physical/spatial analysis such as visibility, occlusion, likely collision trajectory, and object relationship. Record this as a second opinion, not safety truth and not the final promotion authority.

### Anti-metric-gaming rules

- LLM agents cannot see hidden seeds.
- LLM agents cannot edit evaluators or thresholds during a campaign.
- deterministic services calculate success, collision, and regression metrics;
- the promotion gate is code, not a Gemini answer;
- all prompt/model/version IDs are stored in decision records;
- a second-opinion model cannot override failed objective gates.

---

## 14. Google Cloud deployment

## 14.1 Minimal services

1. `servo-realityci-api` — Cloud Run service
2. `servo-scenario-job` — Cloud Run Job
3. `servo-training-job` — Cloud Run Job
4. `servo-exam-job` — Cloud Run Job
5. Firestore database
6. Pub/Sub topics and subscriptions
7. Cloud Storage bucket
8. Vertex AI model access
9. Secret Manager for credentials
10. Cloud Logging and Error Reporting

## 14.2 Do not block on GPU quota

The tiny model should be able to train on Cloud Run CPU within the demo time. Add an optional GPU configuration only when quota and region availability are confirmed.

This gives two advantages:

- the final demo does not fail because a GPU quota request is pending;
- the system still shows a production extension point for larger policies.

## 14.3 Cost controls

- Cloud Run minimum instances: 0
- strict max instance count
- one active campaign for the demo
- per-campaign compute budget
- training wall-time limit
- artifact lifecycle cleanup
- budget alerts
- authenticated endpoints
- delete or stop resources after recording required proof

---

## 15. Connecting the existing Qt workspaces

Do not redesign all UI. Activate what already exists.

## Runs

Show:

- baseline and candidate runs;
- scenario/world/policy IDs;
- synchronized frame preview;
- speed, detection confidence, brake command, and ground-truth visibility;
- collision or success result;
- cloud execution receipt.

## Diagnose

Show:

- failure frame and timeline;
- ranked hypotheses;
- counterfactual experiment table;
- executed outcomes;
- established root cause and evidence threshold.

## Train

Show:

- curriculum summary;
- training adapter;
- dataset hashes and split counts;
- live job state;
- objective/validation curves;
- baseline and candidate checkpoint hashes.

## Verify

Show:

- hidden-exam results;
- baseline vs candidate success;
- protected regression suites;
- deterministic gate state;
- promote/reject decision and reason.

## Capabilities

Show:

- capability register;
- evidence state (`unknown`, `failed`, `training`, `verified`, `regressed`);
- Reality Debt contribution;
- last verified checkpoint;
- missing-reality requirement when no evidence exists.

## One new cross-workspace feature

Add a compact **Agent Activity Timeline** visible from every stage:

```text
14:02:11 Failure detected
14:02:14 Gemini proposed 5 hypotheses
14:02:17 4 counterfactuals scheduled
14:02:31 Root cause established: occlusion-late-detection
14:02:34 240 training / 60 hidden scenarios reserved
14:02:36 Cloud Run training job started
14:03:22 Candidate checkpoint created
14:03:48 Hidden exam passed: 93.3%
14:04:03 Regression suite passed
14:04:05 Checkpoint promoted
```

Every row must link to a real record or artifact.

---

## 16. Gaussian reconstruction: why the current result fails

The observed symptoms come from multiple failure classes. Treating all of them as “train longer” will waste time.

## 16.1 Insufficient coverage and parallax

A single forward-facing drive does not observe:

- backs of trees and vehicles;
- far sides of signs and poles;
- side streets;
- surfaces behind occluders;
- complete sky directions.

Tiny lateral or rotational camera changes reveal missing evidence. No reconstruction loss can recover truth that was never captured. Generated completion must remain a separate visual layer marked as generated.

## 16.2 Motion blur, rolling shutter, stabilization, and pose error

Road video combines:

- exposure-time camera motion;
- rolling-shutter row timing;
- autofocus or stabilization changes;
- compression;
- dynamic object motion;
- imperfect COLMAP poses and intrinsics.

When a blurred frame is modeled as a single pinhole pose, Gaussians stretch or duplicate to explain incompatible pixels. Small view changes then expose the wrong geometry.

## 16.3 Static model applied to dynamic content

Cars, pedestrians, leaves, branches, grass, shadows, clouds, and reflections change between frames. Static 3DGS can:

- smear them;
- duplicate them;
- make them disappear;
- bake them into the road or sky;
- create high-opacity floating layers.

Masking and object decomposition are required. A generic 4DGS conversion is not automatically better; many driving methods rely on LiDAR, synchronized cameras, boxes, or tracks that the current capture does not contain.

## 16.4 Thick volumetric geometry

Unconstrained 3D ellipsoids can represent the same road pixel with multiple incompatible depths. The r12 mixed-depth measurement confirms this remains severe. The road can look acceptable on the training path while collapsing under lateral motion.

Surface-oriented 2D Gaussians, depth distortion, normal consistency, and a separate road surface are more relevant than simply increasing Gaussian count.

## 16.5 Renderer ordering

The current Vulkan viewer uses one global center-depth order. This can produce popping and blending changes even when geometry is correct. The offline gsplat renderer and native Vulkan renderer must be compared at identical poses before blaming the reconstruction.

## 16.6 Sky representation

Sky should be an infinite environment, not finite scene geometry. r12’s aggregate sky improved, but localized nearly opaque floaters remain and directional environment coverage is only a small observed fraction. Target verified offender frames, preserve non-sky vetoes, and leave unobserved directions unknown.

## 16.7 Signs and markings are source-resolution limited

The handoff reports a typical sign atlas height of only about 16 pixels and no verified regulatory text. A loss cannot recreate unreadable text. Use multi-frame calibrated planar rectification, sharp-view selection, subpixel fusion, OCR/classification, and cross-view agreement. Any generative enhancement is visual-only.

## 16.8 Vegetation and grass are adversarial inputs

They are thin, translucent, repetitive, wind-driven, and often subpixel. The honest options are:

- capture with faster shutter and more viewpoints;
- classify and downweight nonrigid observations;
- separate dynamic vegetation layers;
- accept lower confidence and exclude it from collision truth.

---

## 17. Gaussian rescue program — exact order

## Phase G0 — mandatory r12 exact-PLY audit

Do this before any new training.

Produce:

- exact serialized-PLY registered-view metrics;
- observed-path video;
- reverse-path render;
- yaw perturbations: ±1°, ±3°, ±5°;
- pitch perturbations: ±1°, ±3°;
- lateral offsets: ±0.2 m, ±0.5 m, ±1.0 m in normalized/anchored coordinates;
- combined translation + yaw;
- per-region crops for road, markings, signs, sky, foliage;
- temporal popping/stretching score;
- side-by-side offline gsplat and Vulkan renders.

The immediate question is not “is r12 good?” It is:

> Which measured failure dominates: input/pose, representation geometry, canonical appearance, sky, dynamics, or Vulkan compositing?

## Phase G1 — canonical appearance distillation

Run only when the audit proves that per-frame gain/bias improved training-view fit but harmed the canonical exported artifact.

Treatment:

- initialize from the verified r12 checkpoint in a new diagnostic directory;
- freeze or disable per-frame appearance parameters;
- optimize canonical SH and opacity for 500–1,000 steps;
- do not densify;
- retain geometry regularization;
- compare exact-PLY, held-out, and free-movement metrics;
- accept only when canonical detail improves without sky or geometry regression.

## Phase G2 — targeted sky cleanup

Use the known offender frames rather than global blind training.

- oversample only verified offender views;
- preserve certified observed-non-sky vetoes;
- strengthen high-opacity sky-tail correction in eroded sky interiors;
- keep horizon/tree boundaries on the weaker loss;
- maintain separate observed directional environment;
- audit worst-view p95, not only aggregate p95;
- reject any treatment that erases foliage/building boundaries.

## Phase G3 — blur/pose/rolling-shutter audit

For each source frame, calculate and store:

- Laplacian/sharpness score;
- optical-flow magnitude and direction;
- exposure metadata when available;
- rolling-shutter likelihood;
- COLMAP reprojection residual;
- local camera acceleration/rotation;
- semantic dynamic fraction.

Classify frames into:

- sharp static;
- shutter blur;
- rolling-shutter distortion;
- dynamic-object blur;
- defocus/compression;
- pose outlier.

Test bounded treatments:

- downweight or exclude severe frames;
- three exposure subposes only on blur-classified static frames;
- bounded pose refinement with strong priors;
- rolling-shutter camera model where evidence supports it.

Never average across a full frame-to-frame displacement as if it were one shutter interval.

## Phase G4 — fresh 2DGS / DN-Splatter A/B

This is the most promising structural A/B when mixed road depth remains dominant.

Build from the same SfM initialization, not by converting the final 3DGS checkpoint.

Test:

- gsplat native `rasterization_2dgs`;
- depth-distortion loss;
- rendered-normal versus depth-normal consistency;
- Pearson/correlation monocular-depth supervision;
- normal priors and smoothing;
- shortest-axis flattening;
- road/curb/marking-specific confidence;
- identical held-out and stress paths.

Important gate:

- do not publish a 2DGS PLY through the current 3D ellipsoid Vulkan viewer until offline/viewer parity is demonstrated.

## Phase G5 — dynamic decomposition

For the hackathon:

- remove vehicles/people from static photometric supervision;
- use deterministic controllable actor overlays;
- keep dynamic appearance provenance separate.

After the hackathon:

- track actors across frames;
- build per-object dynamic layers;
- reserve 4D/deformation for vehicles, people, cyclists, moving foliage, and temporal lighting;
- retain a stable static road/building/sign-support layer.

## Phase G6 — structural road and sign outputs

Build separate layers:

1. visual Gaussian appearance;
2. robust road/curb surface or TSDF/mesh;
3. vector lane/topology map;
4. evidence and uncertainty;
5. dynamic actors.

Metric claims require a scale anchor such as calibrated camera height, wheel odometry, GPS/IMU, stereo, or LiDAR.

## Phase G7 — renderer improvement

Only prioritize before submission when the offline/Vulkan comparison proves renderer ordering is a top visual failure.

A production path needs:

- tile binning;
- per-tile or per-pixel depth evaluation;
- local queues/resorting;
- visibility compaction;
- golden parity tests against gsplat;
- popping metric and frame-time gate.

Do not copy license-restricted implementations into Servo without a license review. A clean-room design inspired by papers is safer.

---

## 18. Gaussian acceptance matrix

A treatment is accepted only when it improves the target failure without breaking protected metrics.

| Area | Minimum hackathon gate | Production direction |
|---|---:|---:|
| Held-out SSIM | ≥ 0.75 | ≥ 0.80 preferred |
| Held-out PSNR | no regression > 0.2 dB | scene-specific higher target |
| Worst-view sky alpha p95 | < 0.25 | < 0.10 |
| Supported rays >10% depth spread | clear reduction from 54.53% | < 20% on drivable corridor |
| Road p95 ambiguity | improve from r12 | confidence-bounded surface gate |
| Consecutive degraded views | 0 severe runs | 0 |
| Lateral/yaw stress | no catastrophic tearing in declared envelope | bounded published camera envelope |
| Sign truth | no invented text | cross-view verified atlas/OCR |
| Vulkan parity | visually and numerically bounded | golden image suite |
| Collision readiness | explicitly false | only after metric structural layer |

Do not choose exact numeric production safety thresholds from the current monocular appearance artifact. Those require a proper structural validation program.

---

## 19. Eight-day execution schedule

## Day 0 — August 23: freeze scope and evidence

- confirm eligibility;
- create `hackathon/realityci-loop` branch;
- inventory dirty worktree and preserve unrelated UI changes;
- run the mandatory r12 exact-PLY audit;
- freeze the demo world and baseline policy scenario;
- write the campaign/event schemas;
- create GCP project, budget alert, Firestore, bucket, Pub/Sub, and Cloud Run skeleton;
- submit/verify cloud credit request before the August 28 cutoff.

**Exit gate:** one written demo contract and one measured r12 failure report.

## Day 1 — August 24: deterministic scenario and baseline failure

- implement scenario schema and seeded runner;
- create occluded-pedestrian actor/collision state;
- build image compositor using Gaussian background frames;
- implement baseline PyTorch perception model;
- produce a repeatable collision and evidence bundle;
- add unit tests for physics, collision, seeds, and hashes.

**Exit gate:** one command creates a real baseline failure with synchronized artifacts.

## Day 2 — August 25: cloud control plane

- deploy FastAPI to Cloud Run;
- create campaign CRUD and ordered event API;
- persist Firestore state and idempotency keys;
- publish/consume Pub/Sub events;
- store artifacts in Cloud Storage;
- run one scenario job through Cloud Run Jobs.

**Exit gate:** Cloud Console and logs prove a real backend execution.

## Day 3 — August 26: ADK diagnosis and experiments

- implement ADK graph;
- add Gemini structured-output Diagnostician;
- implement supported counterfactual tool registry;
- execute experiments in parallel where safe;
- add deterministic causal root-cause gate;
- store prompts, model IDs, responses, and evidence hashes.

**Exit gate:** a collision autonomously becomes an established, experiment-backed root cause.

## Day 4 — August 27: training, hidden exam, regression, promotion

- curriculum planner reserves training and hidden seeds;
- Cloud Run Job trains the small model;
- create candidate checkpoint and hash;
- hidden Examiner runs unseen scenarios;
- Regression Guardian evaluates protected ordinary-crossing cases;
- deterministic gate promotes or rejects;
- Reality Debt updates.

**Exit gate:** one completely automated fail-to-promote loop.

## Day 5 — August 28: Qt integration and early submission shell

- connect all existing workspace models to the API;
- show event timeline and artifacts;
- add explicit Google Cloud/model/framework labels;
- update README with start, test, architecture, and demo instructions;
- upload an early Devpost draft before the recommended buffer;
- complete article/social bonus items only after the core is stable.

**Exit gate:** desktop demo works from start to promoted checkpoint without manually editing data.

## Day 6 — August 29: reliability and Gaussian showcase

- kill/restart workflow and prove resume/idempotency;
- verify no duplicate training job;
- run one bounded Gaussian treatment selected by the audit;
- produce before/after stress video and honest limitations;
- verify cloud cost controls and auth.

**Exit gate:** repeatable demo plus one measured reconstruction improvement or a clear evidence-backed rejection.

## Day 7 — August 30: final production assets

- record architecture walkthrough;
- rehearse four-minute demo;
- record clean cloud proof;
- create screenshots/GIFs;
- test README on a clean machine/account where possible;
- run full test suite;
- freeze commit and tag submission candidate.

## Deadline day — August 31

- upload final video early;
- verify first four minutes contain all scoring evidence;
- test links in incognito;
- submit several hours before 5:00 PM PT;
- do not modify linked materials after lock.

---

## 20. Testing strategy

## 20.1 Unit tests

- scenario determinism from seed;
- collision and TTC calculations;
- evidence serialization and hashes;
- policy adapter interface;
- trainer produces changed checkpoint hash;
- hidden seed isolation;
- regression threshold calculations;
- promotion gate truth table;
- Firestore state transitions;
- Pub/Sub duplicate event handling;
- Gemini schema validation and malformed-output rejection.

## 20.2 Integration tests

- baseline run → failure event;
- failure → counterfactual batch;
- experiment outcomes → established root cause;
- curriculum → training job;
- training → checkpoint;
- checkpoint → hidden exam/regression;
- pass → promote;
- fail → reject;
- process crash mid-workflow → resume without duplicate side effect;
- desktop reconnect → reconstruct complete ordered state.

## 20.3 Golden demo test

One script should:

```text
1. Reset a demo campaign namespace.
2. Verify required cloud services and credentials.
3. Start the baseline campaign.
4. Wait for terminal promotion/rejection.
5. Validate every required event exactly once semantically.
6. Download final report and artifacts.
7. Confirm checkpoint hash changed.
8. Confirm hidden exam and regression records exist.
9. Emit a concise PASS/FAIL receipt.
```

The video should be recorded only after this script passes three times consecutively.

---

## 21. Judging rubric strategy

## Innovation and operational utility — 40%

Show that Servo does more than scenario generation:

- causal experiments;
- autonomous training-method selection within supported adapters;
- hidden generalization exam;
- regression protection;
- checkpoint promotion/rejection;
- Reality Debt and next-weakness selection;
- missing-reality capture mission.

Target score with successful build: **4.6/5**.

## Architecture — 30%

Show:

- ADK graph, not a single prompt loop;
- durable event/state model;
- idempotent retries;
- deterministic gates outside the LLM;
- clear separation of appearance, physics, policy, training, and evidence;
- adapter boundaries;
- Google Cloud services with real roles;
- provenance and hidden-test isolation.

Target score: **4.4/5**.

## Demo and production readiness — 30%

Show:

- real native application;
- actual agent action and logs;
- actual model weight change;
- cloud job and console proof;
- resume/recovery;
- clear README and tests;
- honest claims and limits;
- tight four-minute narrative.

Target score: **4.2/5**.

Estimated weighted core score when executed cleanly: **approximately 4.4/5 before eligible bonus points**.

---

## 22. Honest winning-chance assessment

No one can credibly promise a 90% win in an open global hackathon. The number and quality of eligible final submissions are unknown, and judging is partly subjective.

Subjective planning bands:

| Delivery state | Taskmaster chance | Any major prize | Grand prize |
|---|---:|---:|---:|
| Current public state: reconstruction foundation, no live Gemini/ADK/cloud loop | effectively 0% | below 0.1% | near 0% |
| Thin LLM wrapper or mostly mocked workflow | below 1% | below 1% | near 0% |
| Real complete loop, average presentation | 1–4% | 2–8% | 0.2–1% |
| Exceptional complete loop, polished four-minute proof, reproducible repo | 2–6% | 5–12% | 0.5–2% |

These are judgment ranges, not measured probabilities. Servo’s concept is strong enough to be a serious finalist. Its outcome is now dominated by execution completeness, not idea quality.

---

## 23. Risk register

| Risk | Probability | Damage | Mitigation |
|---|---:|---:|---|
| Agent loop remains placeholder | High | Fatal | Freeze all non-loop feature work immediately |
| GPU quota unavailable | Medium | High | Tiny CPU-trainable model; GPU is optional |
| Gemini gives unsupported diagnosis | Medium | High | Tool registry + executed counterfactual gate |
| Hidden test leaks | Medium | High | seed vault service; Trainer never receives hidden manifests |
| Duplicate Pub/Sub actions | High | High | idempotency records and transactional state transition |
| Gaussian visuals remain poor | High | Medium | use bounded observed-path background; show diagnostics honestly; do not make reconstruction the product |
| Public repo differs from local work | High | High | clean integration branch and README synchronization |
| Four-minute video too technical | Medium | High | narrate one failure-to-promotion story; architecture only after visual payoff |
| Eligibility issue | Unknown | Fatal | verify age-of-majority and team rules now |
| License conflict from research code | Medium | High | use concepts or permissive components; record license review |
| Overclaiming autonomous-driving safety | Medium | Fatal to trust | explicit appearance-only and deterministic-physics labels |

---

## 24. Final four-minute demo sequence

### 0:00–0:25 — problem and product

- “Physical-AI teams manually replay failures, guess root causes, create scenarios, retrain, and check regressions.”
- “Servo turns that cycle into autonomous CI/CD.”

### 0:25–0:55 — current world and policy

- Open the Yosemite Gaussian world in native Vulkan.
- Show that appearance, inferred depth, structure, and coverage are separated.
- Select baseline checkpoint and capability: occluded pedestrian.

### 0:55–1:25 — real failure

- Start campaign.
- Vehicle drives; pedestrian emerges behind occluder; collision.
- Show synchronized detection confidence, speed, brake timing, and evidence receipt.

### 1:25–2:00 — agent diagnosis through action

- Gemini proposes hypotheses.
- ADK routes four counterfactual experiments.
- Outcomes establish late perception under partial occlusion.
- Emphasize that the conclusion came from interventions, not only text reasoning.

### 2:00–2:40 — training

- Servo creates curriculum and reserves hidden scenarios.
- Pub/Sub launches Cloud Run training job.
- Show Cloud Console/job log and candidate checkpoint hash changing.

### 2:40–3:20 — independent verification

- Hidden exam succeeds.
- Regression suite protects ordinary crossings.
- Deterministic gate promotes the checkpoint.
- Reality Debt changes from failed to verified.

### 3:20–3:40 — autonomous continuation

- Agent chooses the next uncovered capability.
- Show missing-reality/capture mission as a stretch result.

### 3:40–4:00 — architecture and required tech

- Display architecture diagram.
- State clearly: Gemini 3.7 Flash, Google ADK, Vertex AI, Cloud Run, Firestore, Pub/Sub, Cloud Storage.
- End with: “Servo does for learned physical systems what CI/CD did for software.”

---

## 25. README structure for judges

```text
# Servo — Autonomous CI/CD for Physical AI

## 30-second explanation
## Four-minute demo
## What the agent actually does
## End-to-end evidence from the demo campaign
## Architecture diagram
## Google technologies used
## Reproduce the demo
## Run tests
## Repository map
## Policy/trainer adapter contract
## Evidence and promotion gates
## Gaussian reconstruction foundation
## Honest limitations
## Licensing and dataset provenance
```

Place the complete agent demo above the long reconstruction history. Judges should not need to scroll through r6/r9/r12 details before understanding the submission.

---

## 26. Definition of done

The project is submission-ready only when all statements below are true:

- [ ] A policy run fails without manual data editing.
- [ ] The failure produces a durable evidence bundle.
- [ ] Gemini produces structured hypotheses.
- [ ] Supported counterfactual experiments execute.
- [ ] Code establishes root cause from outcomes.
- [ ] A curriculum is created and hidden seeds are isolated.
- [ ] A real Cloud Run training job changes model weights.
- [ ] A candidate checkpoint is content-addressed.
- [ ] Hidden exam runs on unseen scenarios.
- [ ] Regression suite executes.
- [ ] Deterministic gate promotes or rejects.
- [ ] Reality Debt changes from verified evidence.
- [ ] Desktop UI reflects every stage from real backend state.
- [ ] Cloud Console/log proof appears in the video.
- [ ] ADK and Gemini model names are stated clearly.
- [ ] Architecture diagram is uploaded.
- [ ] README spin-up and testing instructions work.
- [ ] No secrets, local absolute paths, or diagnostic data are committed.
- [ ] Claims remain within the evidence boundary.

---

## 27. Research directions after submission

After the complete loop is stable:

1. Native 2DGS/surface representation with viewer parity.
2. Blur- and rolling-shutter-aware camera optimization.
3. Metric road surface through scale anchors and sensor fusion.
4. Vector lane/sign topology and uncertainty.
5. Dynamic actor tracking and per-object 4D layers.
6. More policy adapters, including the intended VLA.
7. Real customer recording library search and acquisition missions.
8. Clean-room tile/per-pixel Vulkan Gaussian rasterizer.
9. Generated visual completion stored separately from measured truth.
10. Continuous cloud/local training infrastructure for larger physical-AI models.

---

## 28. Final directive

The correct priority order is:

```text
1. Audit and freeze the visual world.
2. Build the deterministic baseline failure.
3. Build the durable Google ADK control loop.
4. Execute causal experiments.
5. Actually train a small policy.
6. Run hidden exams and regressions.
7. Promote/reject and update Reality Debt.
8. Connect the existing Qt workspaces.
9. Record undeniable Google Cloud proof.
10. Only then improve one measured Gaussian failure.
```

Do not trade a complete autonomous loop for another week of Gaussian tuning. The reconstruction is the stage; RealityCI is the product.
