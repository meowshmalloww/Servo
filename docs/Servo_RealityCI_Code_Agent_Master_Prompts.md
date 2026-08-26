# Servo / RealityCI — Code-Agent Master Prompt Pack

Use these prompts **sequentially**. Do not paste all phase prompts into one agent run. Prompt 0 establishes the operating contract; then use the smallest phase prompt matching the current task. Require the agent to show evidence and stop at each acceptance gate.

Repository: `D:\Servo`
Public repository: `meowshmalloww/Servo`
Local reconstruction Python:

```text
C:\Users\wenje\AppData\Local\Servo\reconstruction\venv-py311-cu128\Scripts\python.exe
```

---

# Prompt 0 — Program-level operating contract

```text
You are the lead engineer for Servo, a native Qt/QML + C++/Vulkan application being submitted to the All Things Agentic Hackathon.

Read before changing anything:
- README.md
- docs/WORLD_RECONSTRUCTION_PLAN.md
- docs/WorldRec - Google Docs.pdf
- docs/WorldRec2 - Google Docs.pdf
- the latest r12 technical handoff supplied in this session
- tools/reconstruction/servo_worker.py
- tools/reconstruction/servo_train.py
- tools/reconstruction/servo_audit_world.py
- src/ui/Main.qml
- src/ui/Session.qml
- all QML workspaces for Runs, Diagnose, Train, Verify, and Capabilities
- tests relevant to every file you will touch

Product objective:
Build Servo as autonomous CI/CD for physical AI. The complete loop is:
MODEL -> RUN -> FAILURE -> CAUSAL DIAGNOSIS -> TARGETED EXPERIENCE -> TRAIN -> HIDDEN EXAM -> REGRESSION TEST -> PROMOTE/REJECT -> REALITY DEBT -> NEXT WEAKNESS.

The hackathon demo must use a real, small trainable policy and one occluded-pedestrian failure. Gemini proposes hypotheses and plans supported experiments. Code executes counterfactuals, establishes root cause from intervention outcomes, launches real training, runs hidden tests, protects old capabilities, and deterministically promotes or rejects the checkpoint. Gaussian splats provide appearance only; deterministic state provides collision and actor truth.

Global constraints:
1. Preserve all unrelated dirty-worktree changes, especially UI/theme/icon work.
2. Do not stage all files. Never commit diagnostics, generated worlds, model weights, secrets, local caches, or absolute local paths.
3. Use apply_patch for source edits where practical.
4. Do not mutate, rewrite, or forge existing checkpoint/configuration hashes.
5. Put every new diagnostic run in a new named directory.
6. Do not install packages or change the existing local reconstruction environment unless I explicitly approve it.
7. No Docker for the local desktop or reconstruction pipeline. Containerization is allowed only inside the isolated cloud/ job directories when Cloud Run requires it.
8. Do not claim metric depth, LiDAR, collision safety, autonomous-driving readiness, verified sign text, or complete unseen geometry without corresponding evidence.
9. Do not let an LLM calculate objective safety metrics or decide promotion. Collision, success, regression, and promotion gates must be deterministic code.
10. Hidden exam seeds and manifests must never be visible to the Trainer or Curriculum Planner.
11. Every external action must be idempotent and durable. Assume Pub/Sub can deliver duplicates.
12. Use versioned Pydantic/JSON schemas and content hashes for campaigns, events, scenarios, evidence, datasets, checkpoints, exams, and decisions.
13. Never fabricate progress, logs, metrics, model outputs, cloud execution, or UI data.
14. Verify current official Google ADK, Vertex AI, Gemini, Cloud Run, Firestore, Pub/Sub, and Cloud Storage APIs before writing integration code. Pin working versions and document them.
15. Prefer one complete path over broad abstractions. Do not add CARLA, MuJoCo, ROS2, 4DGS, a large VLA fine-tune, or a full map compiler before the core demo passes.

Required engineering behavior:
- Begin by reporting repository status, active processes, branch, HEAD, modified/untracked files, and exact source/runtime versions.
- State which facts are verified and which are assumptions.
- Before implementation, present a file-level plan and acceptance tests.
- Make bounded changes.
- Run the narrow tests first, then broader suites.
- Show commands, outputs, artifact paths, hashes, and remaining limitations.
- Stop when the prompt’s acceptance gate is met or when evidence shows the treatment should be rejected.
- Do not continue long training merely because it is available.

Output format after each phase:
1. Verified starting state
2. Changes made by file
3. Commands run
4. Test/audit results
5. Artifacts and hashes
6. Acceptance-gate verdict
7. Risks and exact next action
```

---

# Prompt 1 — Synchronize the repository without losing local work

```text
Follow Prompt 0. Perform a repository synchronization and safety audit only. Do not implement new features yet.

Objectives:
- Determine the exact difference between local D:\Servo and public main at commit 1bc62f956fb96f9c4fb1d1beaee64269e308963d or the current remote HEAD if it has changed.
- Separate r12 reconstruction changes from unrelated UI/theme/icon changes.
- Identify files described by the r12 handoff that are not publicly committed.
- Confirm whether tools/reconstruction/servo_audit_world.py is locally v3 while public main is older.
- Identify absolute paths, generated files, diagnostics, secrets, and large artifacts that must not be committed.
- Create a safe branch named hackathon/realityci-loop from the intended base without discarding local changes.

Procedure:
1. Record git status --short, branch, HEAD, remotes, submodules, ignored diagnostic directories, and running Servo/Python/CUDA processes.
2. Produce a categorized change inventory:
   A. r12 source/tests/docs
   B. unrelated UI/theme/icon work
   C. generated diagnostics/artifacts
   D. suspicious secrets/credentials/local paths
   E. unknown changes requiring human review
3. Verify existing checkpoint/configuration receipts and do not modify them.
4. Create patches or commits only for category A after tests pass. Preserve B in place or in a separate safe patch/branch. Exclude C and D.
5. Update .gitignore only when necessary and without hiding source files.
6. Produce docs/HACKATHON_REPO_STATE.md with the public/local discrepancy, current known artifact status, and exact safe next steps.

Acceptance gate:
- No local work lost.
- A clean, reviewable hackathon branch exists.
- r12 source changes are isolated from unrelated UI changes.
- No diagnostics, secrets, checkpoints, generated worlds, or absolute local paths are staged.
- The repo-state document is truthful and references exact commit hashes.

Stop after reporting the proposed commit set. Do not push or rewrite history without explicit approval.
```

---

# Prompt 2 — Mandatory r12 exact-PLY v3 audit

```text
Follow Prompt 0. Do not train or change the reconstruction algorithm. Run and validate the mandatory r12 exact serialized-PLY audit first.

Known diagnostic input:
D:\Servo\diagnostics\yosemite-r12-detail-geometry\train-7000

Required command baseline:
& 'C:\Users\wenje\AppData\Local\Servo\reconstruction\venv-py311-cu128\Scripts\python.exe' `
  'D:\Servo\tools\reconstruction\servo_audit_world.py' `
  --diagnostic-training-output 'D:\Servo\diagnostics\yosemite-r12-detail-geometry\train-7000' `
  --output 'D:\Servo\diagnostics\yosemite-r12-detail-geometry\train-7000\path-audit-r12-driving-v3' `
  --reference-images 'C:\Users\wenje\AppData\Local\Servo\reconstruction\jobs\yosemite-road-r7-quality-20260814\stages\pose\training\images' `
  --width 640 `
  --frames-per-segment 1 `
  --fps 30

Tasks:
1. Verify all input hashes, schema versions, source paths, free disk, GPU state, and absence of conflicting training processes.
2. Run the audit. If it fails, diagnose and make the smallest source fix with tests; do not alter r12 artifacts.
3. Compare the resulting v3 JSON directly against r11’s existing v3 JSON.
4. Inspect the MP4 and representative crops, not only aggregate metrics.
5. Report:
   - exact-PLY registered PSNR/SSIM;
   - overall, road, road-marking, curb/boundary detail retention;
   - lower-half and center support;
   - mixed-depth ambiguity;
   - aggregate and worst-view sky alpha;
   - sign evidence resolution;
   - consecutive degraded views;
   - popping/stretching between cameras;
   - dynamic actor and vegetation artifacts.
6. Produce a machine-readable comparison JSON and a concise Markdown report under the new audit directory.
7. Classify the dominant failure into one or more categories:
   INPUT_BLUR, POSE_OR_INTRINSICS, CANONICAL_APPEARANCE, THICK_GEOMETRY, SKY_FLOATERS, DYNAMIC_CONTENT, COVERAGE_LIMIT, VULKAN_SORTING, UNKNOWN.

Acceptance gate:
- Exact r12 PLY was audited without mutation.
- r11/r12 numerical and visual comparisons exist.
- One dominant measured failure is named with evidence.
- No new training has started.
```

---

# Prompt 3 — Navigation stress suite and renderer-vs-reconstruction classifier

```text
Follow Prompt 0 and use the completed r12 v3 audit as the baseline.

Objective:
Build a reproducible navigation stress suite that determines whether view-change corruption comes from the reconstructed artifact, the native Vulkan global sort, or both.

Required paths:
- tools/reconstruction/servo_audit_world.py
- src/ui/rendering/GaussianSplatView.cpp/.h
- src/ui/rendering/shaders/*
- src/ui/rendering/README.md
- related tests

Implement a versioned stress manifest and renderer comparison that covers:
- reverse observed path;
- yaw: -5, -3, -1, +1, +3, +5 degrees;
- pitch: -3, -1, +1, +3 degrees;
- lateral offsets: -1.0, -0.5, -0.2, +0.2, +0.5, +1.0 in the world’s declared normalized or anchored coordinates;
- combined lateral + yaw;
- smooth continuous rotation and translation sequences.

For every pose:
1. Render with the producing gsplat/offline path.
2. Render the identical camera with the Vulkan viewer or a headless equivalent using the same PLY, SH basis, camera matrices, exposure/canonical appearance, background, and output color space.
3. Calculate bounded image differences and temporal metrics.
4. Save road, sign, sky, boundary, and vegetation crops.
5. Distinguish:
   - both renderers fail similarly -> reconstruction/coverage problem;
   - offline stable, Vulkan unstable -> sorting/compositing problem;
   - canonical registered views differ -> parity/color/camera problem.

Add tests for camera transform equivalence, SH coefficient layout, depth key semantics, background compositing, and deterministic pose generation.

Output:
- stress-manifest.json
- per-pose metrics JSON
- offline-vs-Vulkan contact sheet
- continuous MP4s
- classification report with confidence and concrete next treatment

Acceptance gate:
A future engineer can run one command and receive a deterministic diagnosis of renderer versus reconstruction failure. Do not implement a new renderer in this phase.
```

---

# Prompt 4 — Bounded canonical-appearance distillation A/B

```text
Follow Prompt 0. Execute this phase only if the stress audit proves that bounded per-frame appearance compensation improved fitted source views but degraded the canonical exported PLY.

Objective:
Test a bounded identity/canonical appearance distillation phase without changing geometry or manufacturing detail.

Requirements:
- Never mutate r12’s checkpoint or directory.
- Create a new non-publishable diagnostic configuration and output directory.
- Load the verified r12 checkpoint through its normal receipt validation.
- Freeze means, scales, quaternions, densification, and pruning unless the evidence requires a narrower explicitly approved choice.
- Freeze/disable per-frame log-gain and bias.
- Optimize only canonical SH coefficients and, only when justified, opacity for 500–1,000 steps.
- Retain static masks and relevant sky/geometry constraints.
- Use source evidence only; no generated targets.

A/B matrix:
A. r12 unchanged baseline
B. 500-step SH-only canonical distillation
C. 1,000-step SH-only canonical distillation
D. optional SH+bounded-opacity variant only if B/C expose alpha mismatch

For every arm, run:
- held-out metrics;
- exact serialized-PLY registered metrics;
- navigation stress suite;
- road/sign/sky/vegetation crops;
- worst-view sky and depth-spread checks.

Acceptance rule:
Accept a treatment only when canonical exact-PLY and free-view appearance improve materially, held-out PSNR does not regress more than 0.2 dB, held-out SSIM does not regress, and sky/depth ambiguity do not worsen. Otherwise reject the entire treatment and preserve the baseline.

Add configuration-contract and checkpoint-resume tests. Report exact runtime, VRAM, hashes, and why the winning arm was chosen.
```

---

# Prompt 5 — Targeted sky-floater repair

```text
Follow Prompt 0. Use the r12 audit’s exact offender list. Do not run a global sky retrain by default.

Known likely offender regions include frames near 94–100, 108, 116, 124, 228, 255, 265–276, especially frame 98. Re-derive rather than blindly trusting this list.

Objective:
Reduce worst-view finite sky opacity while preserving horizon, foliage, mountains, signs, poles, and building boundaries.

Implement a diagnostic-only targeted treatment:
1. Recompute per-view sky alpha p50/p95/p99 and high-alpha connected components.
2. Validate certified sky and observed-non-sky evidence at every offender.
3. Generate offender crops with semantic labels, certified evidence, alpha, RGB, depth spread, and contributor IDs when available.
4. Oversample only verified offender views with a hard cap.
5. Apply stronger high-opacity tail correction only inside eroded certified sky interiors.
6. Keep boundary pixels on the weaker mean-alpha term.
7. Preserve observed-non-sky vetoes.
8. Do not assign targets to unobserved sky directions.
9. Keep the separately observed directional environment and record its limited coverage.

Run a short screen, then a bounded confirmation only if the screen improves the correct metric.

Acceptance gate:
- worst-view sky alpha p95 falls below the configured diagnostic target;
- aggregate sky remains improved;
- no new holes or erosion appear on non-sky boundaries;
- held-out/canonical appearance and road detail stay within protected limits;
- treatment is rejected if it merely lowers the aggregate while leaving localized opaque floaters.
```

---

# Prompt 6 — Blur, rolling-shutter, and pose-quality audit

```text
Follow Prompt 0. This is a measurement and bounded-A/B phase, not an unrestricted bundle-adjustment rewrite.

Objective:
Determine how much of Servo’s blur/ghosting comes from shutter blur, rolling shutter, defocus/compression, dynamic-object motion, or camera-pose/intrinsic error.

For all 373 registered frames, publish a versioned frame-quality table containing:
- Laplacian variance and gradient energy;
- optical-flow magnitude/direction and local consistency;
- estimated camera angular/linear step;
- COLMAP reprojection residual and track support;
- dynamic semantic fraction;
- vegetation fraction;
- exposure/readout metadata when present;
- compression/defocus indicators;
- classification label and confidence.

Research and verify primary implementations/papers before adopting ideas from BAD-Gaussians, BARD-GS, 3dgs-deblur, Deblur-GS, or rolling-shutter-aware driving renderers. Record licenses and required inputs.

Run only bounded experiments:
A. downweight/exclude the worst verified frames;
B. use three exposure subposes on frames classified as static shutter blur;
C. bounded camera pose refinement with strong priors;
D. rolling-shutter model only when row-time evidence exists.

Never interpolate across a complete video-frame displacement as if it were exposure time.

Acceptance gate:
The report quantifies which camera/input failure class dominates, and at least one short A/B either improves stress/held-out metrics or is rejected with evidence. No long training until a short screen passes.
```

---

# Prompt 7 — Fresh native 2DGS + surface supervision A/B

```text
Follow Prompt 0. Execute only when r12 audits identify mixed-depth/thick road geometry as a dominant failure.

Objective:
Build a fresh, isolated native 2D Gaussian Splatting A/B from the same SfM inputs and compare it fairly with r12 3DGS.

Research and verify:
- official 2DGS paper/repository;
- gsplat 1.5.3 rasterization_2dgs and example trainer;
- DefaultStrategy gradient key required by 2DGS;
- depth distortion loss;
- rendered-normal/depth-normal consistency;
- DN-Splatter Pearson/correlation monocular-depth supervision;
- normal smoothing and surface flattening;
- PLY/export semantics;
- compatible licenses.

Implementation rules:
1. Do not convert the finished 3DGS checkpoint and call it 2DGS.
2. Start from the same confidence-filtered SfM initialization and camera split.
3. Preserve all evidence/provenance contracts.
4. Add a new representation type and schema; never let the current 3DGS Vulkan viewer silently load it as equivalent.
5. Keep output non-publishable until offline and viewer parity exists.
6. Run 300-step smoke, 2k screen, and 6k confirmation before any long fit.

A/B arms:
- 3DGS r12 control;
- native 2DGS baseline;
- 2DGS + depth distortion;
- 2DGS + depth distortion + normal consistency;
- optional DN-style Pearson depth/normal priors when source assumptions are valid.

Compare held-out appearance, road depth spread, road/marking/boundary detail, sky, stress paths, mesh/surface extractability, runtime, VRAM, and export parity.

Acceptance gate:
Select a representation only when the same declared camera envelope materially improves geometry/stability without unacceptable appearance regression. Otherwise retain 3DGS and document the rejection.
```

---

# Prompt 8 — RealityCI domain schemas and repository skeleton

```text
Follow Prompt 0. Build only the domain foundation; do not call Gemini or deploy cloud resources yet.

Create this structure, adapting to existing project conventions:

cloud/control_api/app/main.py
cloud/control_api/realityci/workflow.py
cloud/control_api/realityci/agents/
cloud/control_api/realityci/tools/
cloud/control_api/realityci/schemas/
cloud/training_job/
cloud/scenario_job/
cloud/exam_job/
cloud/infra/
tools/realityci/
tests/realityci/
demo/occluded_pedestrian/

Define versioned Pydantic schemas for:
- Campaign
- DomainEvent
- ScenarioManifest
- PolicyDescriptor
- PolicyRun
- RunEvidence
- FailureRecord
- CausalHypothesis
- CounterfactualExperiment
- CausalDiagnosis
- Curriculum
- DatasetManifest
- TrainingJob
- CheckpointArtifact
- HiddenExam
- RegressionReport
- PromotionDecision
- CapabilityRecord
- RealityDebtSnapshot
- CaptureMission

Required fields:
- stable ID;
- schema/version;
- created timestamp;
- producer/version;
- parent/causation IDs;
- content hash;
- provenance;
- artifact references;
- state enum;
- idempotency key where side effects exist.

Implement canonical JSON and SHA-256 helpers shared across local and cloud Python. Define a strict state-transition table. Reject unknown fields where appropriate and reject invalid transitions.

Add fixtures and exhaustive schema/state-machine tests.

Acceptance gate:
- all schemas round-trip deterministically;
- hashes are stable;
- invalid transitions and malformed evidence fail closed;
- no cloud dependency is required to run the schema tests locally;
- architecture documentation lists every state owner.
```

---

# Prompt 9 — Deterministic occluded-pedestrian scenario runner

```text
Follow Prompt 0 and Prompt 8.

Objective:
Implement one deterministic, reproducible physical-AI scenario runner that uses a Gaussian render as visual background but never treats splats as collision geometry.

Scenario:
- ego follows a bounded route through the Yosemite road world;
- parked vehicle acts as occluder;
- pedestrian crosses from behind it;
- baseline policy should fail within a targeted parameter band;
- normal visible pedestrian scenarios must remain solvable.

Implement:
- seeded scenario manifest;
- ego kinematics with position, speed, acceleration, brake limits;
- pedestrian trajectory;
- occluder geometry;
- ground-truth visibility/occlusion calculation;
- deterministic collision and near-miss calculation;
- frame compositor using pre-rendered Gaussian background frames and clearly tagged synthetic actors;
- synchronized telemetry and video/frame artifacts;
- oracle perception, planner, and controller toggles;
- batch runner for parameter grids;
- cancellation, timeout, and content-addressed outputs.

Do not require a collision mesh from the Gaussian PLY. Store provenance:
background=observed Gaussian render; actor=synthetic controllable; collisionTruth=deterministic scenario state.

Tests:
- same seed produces byte-identical manifest and equivalent metrics;
- actor trajectories and collision time are correct;
- oracle perception prevents the target failure when planner/controller are valid;
- invalid scenario ranges fail validation;
- no output is written outside the job directory;
- cancellation leaves a durable terminal receipt.

Acceptance gate:
One command produces a repeatable baseline collision, an MP4/frame bundle, telemetry, and a verified RunEvidence JSON.
```

---

# Prompt 10 — Policy and trainer adapter contracts

```text
Follow Prompt 0, Prompt 8, and Prompt 9.

Objective:
Implement honest policy interfaces and one small trainable image-based policy.

Interfaces:
PolicyAdapter:
- load(descriptor/checkpoint)
- reset(seed)
- infer(sensor_packet) -> policy_output
- describe_capabilities()
- supports_training()
- artifact_identity()

TrainerAdapter:
- validate_training_request()
- prepare_dataset()
- train()
- emit_metrics()
- produce_checkpoint()
- cancel()

Implement:
1. TorchOcclusionPerceptionAdapter
   - small CNN over a short RGB frame stack plus ego speed;
   - predicts pedestrian risk/TTC or brake probability;
   - deterministic inference mode;
   - content-addressed checkpoint.
2. TorchBehaviorCloningTrainer
   - oracle labels from scenario state;
   - bounded epochs/wall time;
   - train/validation split from explicit manifests;
   - deterministic seeds;
   - early stop;
   - checkpoint and metrics receipts.
3. ONNXInferenceOnlyAdapter
   - proves a distinct inference-only interface;
   - returns a diagnosed failure dataset instead of pretending Servo can train it.

Create a baseline checkpoint trained without sufficient high-occlusion examples. Verify it passes ordinary crossings and fails the intended hidden-pedestrian band.

Acceptance gate:
- model weights actually load and run;
- baseline behavior is reproducible;
- training changes the checkpoint hash;
- the adapter reports capabilities honestly;
- no claim is made that Servo trains arbitrary black-box models.
```

---

# Prompt 11 — Failure detector and evidence bundle

```text
Follow Prompt 0 and the completed scenario/policy work.

Objective:
Convert runner output into a durable, synchronized FailureRecord and evidence package.

Implement deterministic evaluators for:
- collision;
- near miss;
- route departure;
- late detection;
- brake-response delay;
- controller execution mismatch;
- timeout/stall.

For the demo failure, record:
- first ground-truth pedestrian visibility;
- first policy detection above threshold;
- planner brake-request time;
- controller brake-execution time;
- collision time and relative speed;
- policy logits/confidence;
- ego trajectory;
- scenario and checkpoint hashes;
- selected key frames and video URI;
- data provenance and evaluator version.

No Gemini call occurs in this phase. The same evidence must lead to the same deterministic failure classification.

Add tests for timestamp alignment, missing frames, non-finite telemetry, evaluator versioning, and hash mismatch.

Acceptance gate:
The baseline run automatically emits FAILURE_DETECTED and a complete evidence bundle that can be consumed without reading unstructured logs.
```

---

# Prompt 12 — Google Cloud infrastructure with cost and security controls

```text
Follow Prompt 0. Verify current official APIs and region availability before applying infrastructure.

Objective:
Create the minimum Google Cloud control plane for Servo using reproducible infrastructure definitions.

Required resources:
- Cloud Run service: servo-realityci-api
- Cloud Run Jobs: servo-scenario-job, servo-training-job, servo-exam-job
- Firestore database
- Cloud Storage bucket with lifecycle policy
- Pub/Sub domain-event topics and dead-letter handling
- service accounts with least privilege
- Secret Manager entries/references
- Cloud Logging/Error Reporting
- budget alert documentation

Constraints:
- min Cloud Run instances = 0;
- strict max instances;
- authenticated API, no unrestricted costly public endpoint;
- no secrets in source or images;
- separate dev/demo namespaces;
- idempotency and event-retention policies;
- CPU path must work without GPU quota;
- optional GPU job configuration isolated and disabled by default;
- containerization stays under cloud/* and does not restructure the native app.

Create:
- cloud/infra/README.md
- deployment scripts or Terraform/gcloud definitions appropriate to the current official service;
- .env.example containing names only, no values;
- preflight and teardown scripts;
- cost estimate for one demo campaign.

Acceptance gate:
A smoke endpoint runs on Cloud Run, writes a Firestore record, publishes/consumes a Pub/Sub test event exactly once semantically, stores a small artifact in GCS, and can be torn down safely. Capture CLI output and Cloud Console proof.
```

---

# Prompt 13 — FastAPI campaign/event/artifact control API

```text
Follow Prompt 0, Prompt 8, and Prompt 12.

Objective:
Implement the Cloud Run control API without agent reasoning yet.

Endpoints, adjusted to current best practices:
- POST /v1/campaigns
- GET /v1/campaigns/{id}
- POST /v1/campaigns/{id}/start
- POST /v1/campaigns/{id}/cancel
- GET /v1/campaigns/{id}/events?after_sequence=
- GET /v1/campaigns/{id}/artifacts
- GET /healthz
- GET /readyz

Implement:
- authentication/authorization appropriate for the demo;
- request IDs and structured logs;
- Firestore transactions for state transitions;
- monotonically ordered per-campaign event sequence;
- idempotency keys for every mutating endpoint;
- GCS artifact metadata and bounded signed access;
- cancellation tokens;
- error taxonomy;
- OpenAPI schema;
- local emulator/fake repository interfaces for tests.

Never accept arbitrary shell commands, filesystem paths, Python code, model prompts, or bucket URIs from the client without validation.

Acceptance gate:
API tests cover duplicate requests, concurrent transitions, invalid state, missing artifact, auth failure, cancellation, and restart. A deployed smoke campaign can be observed from the command line.
```

---

# Prompt 14 — Google ADK durable workflow graph

```text
Follow Prompt 0 and verify the current official Google ADK 2.x API/version before implementation.

Objective:
Implement a durable ADK workflow for the exact RealityCI state machine.

Graph:
Campaign Intake
-> Baseline Runner
-> Failure Triage
-> Diagnostician
-> Experiment Planner
-> Parallel Counterfactual Executors
-> Causal Root-Cause Gate
-> Curriculum Planner
-> Training Job
-> Hidden Examiner
-> Regression Guardian
-> Promotion Gate
-> Reality Debt Updater
-> Next-Weakness Selector

Requirements:
- persist workflow state in Firestore;
- use Pub/Sub/domain events rather than a busy polling loop internally;
- support retry with backoff;
- make every tool call idempotent;
- allow safe resume after process/service restart;
- record model/tool versions and decisions;
- set per-node timeout and retry policy;
- bound parallel counterfactual fan-out;
- deterministic code owns promotion and capability-state changes;
- add a human approval mechanism only for irreversible/expensive actions, not normal demo flow;
- no hidden exam data enters Trainer/Curriculum state.

Start with deterministic stub agents and real tools. Prove the graph and persistence before adding Gemini.

Acceptance gate:
A campaign can run through the graph with deterministic fixtures, survive a forced restart at three different nodes, and finish without duplicate jobs or events.
```

---

# Prompt 15 — Gemini causal diagnostician with structured output

```text
Follow Prompt 0 and use Gemini through Vertex AI. Verify the current stable model ID; use Gemini 3.7 Flash for the main role unless official availability requires an explicitly documented fallback.

Objective:
Add a grounded Diagnostician that proposes testable hypotheses from evidence, not a free-form verdict.

Inputs:
- RunEvidence JSON;
- bounded telemetry summary;
- selected key frames or short clip;
- policy adapter description;
- scenario controls available to the experiment tool registry;
- prior related failures, when available.

Structured output:
- concise failure summary;
- ranked hypotheses;
- evidence supporting and contradicting each hypothesis;
- uncertainty;
- requested counterfactual experiments selected only from the tool registry;
- expected discriminating outcome;
- stop condition;
- explicit statement of unavailable evidence.

Guardrails:
- validate output with strict Pydantic schema;
- reject unknown tools/interventions;
- cap token/media input;
- never expose credentials or hidden seeds;
- never execute model-generated code or shell commands;
- record prompt template version, model ID, safety settings, and response hash;
- use Flash-Lite only for pre-verified telemetry compression, not final causal establishment.

The model may propose H1–H5, but root cause remains status PROPOSED until the deterministic experiment gate evaluates real outcomes.

Acceptance gate:
For the baseline failure, Gemini reliably proposes at least the necessary perception/planner/controller/occlusion alternatives and a supported experiment set. Malformed or unsupported outputs fail closed and retry through a bounded repair path.
```

---

# Prompt 16 — Counterfactual experiment engine and causal gate

```text
Follow Prompt 0, Prompt 9, Prompt 11, and Prompt 15.

Objective:
Execute the Diagnostician’s supported interventions and establish causal root cause from outcomes.

Required interventions:
- remove_occluder
- reveal_pedestrian_earlier(delta_seconds)
- oracle_perception
- oracle_planner
- oracle_controller
- vary_ego_speed
- vary_pedestrian_speed

Every intervention must create a new immutable ScenarioManifest derived from the parent with a recorded patch and hash.

Implement:
- tool registry with typed bounded parameters;
- cost estimate and concurrency cap;
- Cloud Run scenario-job launcher;
- result collection and artifact validation;
- deterministic causal-pattern rules.

For example, establish perception/occlusion root cause only when evidence such as the following holds:
- baseline crashes;
- removing occluder or revealing earlier avoids collision;
- oracle perception avoids collision;
- oracle planner with original perception does not resolve late input, or its outcome is interpreted correctly;
- controller executes valid brake commands when commanded;
- repeated seeds meet a minimum consistency threshold.

Do not hardcode the final text conclusion to this one demo. Encode reusable hypothesis/intervention/result predicates.

Acceptance gate:
The baseline failure produces a CausalDiagnosis with status ESTABLISHED only after real counterfactual outcomes satisfy the rule. Contradictory or insufficient outcomes remain INCONCLUSIVE and schedule bounded additional evidence rather than hallucinating certainty.
```

---

# Prompt 17 — Curriculum planner and real Cloud Run training job

```text
Follow Prompt 0 and the established causal diagnosis.

Objective:
Generate a targeted scenario curriculum, reserve hidden evaluation, and produce a real candidate checkpoint.

Curriculum dimensions for occlusion failure:
- occlusion ratio/visibility time;
- ego speed;
- pedestrian speed;
- crossing angle;
- parked-vehicle geometry;
- contrast/brightness;
- background segment;
- ordinary non-occluded protected cases.

Rules:
1. Reserve hidden seeds and manifests in a separate service/module before exposing training scenarios.
2. Curriculum Planner receives only training-pool metadata.
3. Generate bounded easy-to-hard stages.
4. Store scenario distribution, oracle-label method, split, provenance, and hashes.
5. Launch a real Cloud Run Job using the TorchBehaviorCloningTrainer.
6. Enforce wall-time, epoch, data, and cost limits.
7. Stream structured metrics and create a content-addressed checkpoint.
8. Stop on plateau, non-finite loss, cancellation, or protected validation regression.
9. Verify candidate weights differ from baseline and can be loaded by the PolicyAdapter.

Acceptance gate:
A cloud execution receipt proves the training job ran, a new checkpoint hash exists, metrics are real, and the candidate improves the visible target validation set without accessing hidden exam data.
```

---

# Prompt 18 — Hidden examiner, regression guardian, and promotion gate

```text
Follow Prompt 0 and Prompt 17.

Objective:
Independently decide whether the candidate generalizes and preserves prior capabilities.

Hidden Examiner:
- fetches hidden manifests through a separate authorized path;
- runs baseline and candidate on identical hidden scenarios;
- reports success, collision, near miss, detection delay, and confidence intervals;
- never shares hidden seeds/frames with training agents before the decision.

Regression Guardian:
- runs protected ordinary crossing, visible pedestrian, no-pedestrian, and braking-control suites;
- compares baseline/candidate per capability;
- flags severity-1 regressions and threshold crossings.

Promotion Gate must be deterministic code. Example policy:
- target hidden success >= 90%;
- lower confidence bound >= configured floor;
- no protected capability drops > 3 percentage points;
- no new severity-1 failure;
- all hashes and artifacts verify;
- checkpoint loads and inference smoke passes;
- exam/training data isolation receipt passes.

The LLM may explain the decision but cannot change it.

Add exhaustive truth-table tests, including pass, target fail, confidence fail, regression fail, missing artifact, hash mismatch, and hidden-data leak.

Acceptance gate:
The demo candidate is promoted only by the gate, and a deliberately bad candidate is automatically rejected with a precise reason.
```

---

# Prompt 19 — Reality Debt and next-weakness selection

```text
Follow Prompt 0 and the completed promotion workflow.

Objective:
Implement a capability register and Reality Debt calculation grounded in versioned evidence.

Capability states:
UNKNOWN, UNTESTED, FAILED, DIAGNOSING, TRAINING, CANDIDATE, VERIFIED, REGRESSED, BLOCKED_MISSING_REALITY.

Each CapabilityRecord must contain:
- stable taxonomy ID and version;
- importance/severity weight;
- current state;
- evidence freshness;
- world/scenario coverage;
- latest baseline/candidate/exam records;
- confidence;
- protected regression status;
- last verified checkpoint;
- missing-reality requirement when applicable.

Define a transparent Reality Debt formula based on severity, evidence state, coverage gap, confidence, and freshness. It must be reproducible code, not an LLM score.

Next-Weakness Selector may use Gemini to rank candidates, but it can choose only from capabilities that pass deterministic eligibility/cost rules. Store reasons and alternatives.

Acceptance gate:
After promotion, the target capability changes to VERIFIED, Reality Debt decreases, and the system automatically selects one next eligible weakness without a user clicking a next-step button.
```

---

# Prompt 20 — WorldScout missing-reality and capture mission

```text
Follow Prompt 0. This is a stretch feature; do not begin until the complete fail-to-promote loop passes.

Objective:
When Servo cannot create valid training experience from current authorized worlds, produce a structured evidence requirement and capture mission.

Implement:
- search over authorized world/recording metadata only;
- capability-to-evidence requirements;
- coverage/confidence matching;
- reason that existing evidence is insufficient;
- capture mission with environment, actors, behavior, camera/sensor placement, motion, duration, calibration, weather/time, minimum samples, and acceptance checks;
- privacy/license constraints;
- BLOCKED_MISSING_REALITY capability state.

Example output for snow-hidden lane markings:
- multilane urban roadway;
- snow-covered markings;
- active snowfall;
- moving traffic;
- poor contrast;
- forward and side cameras;
- sufficient calibrated motion;
- 10–20 minutes;
- explicit evidence-quality gates.

Do not automatically scrape unlicensed media or claim generated data is observed reality.

Acceptance gate:
A capability unsupported by existing worlds triggers a clear capture mission instead of endless training or fabricated synthetic truth.
```

---

# Prompt 21 — Qt/C++ RealityCI client and live data models

```text
Follow Prompt 0. Preserve the current QML design and unrelated visual edits.

Objective:
Connect the native desktop application to the real Cloud Run API and populate the existing workspaces with durable backend state.

Create an appropriate C++ layer, for example:
- RealityCIClient
- RealityCIEventModel
- RunModel
- FailureModel
- ExperimentModel
- TrainingJobModel
- CheckpointModel
- CapabilityModel

Use Qt Network and the project’s architecture conventions. Do not put HTTP, JSON parsing, credentials, or agent logic in QML.

Requirements:
- authenticated endpoint configuration;
- create/start/cancel campaign;
- ordered event polling or streaming with resume sequence;
- reconnect and backoff;
- schema validation and clear incompatible-version error;
- artifact metadata and safe download/open behavior;
- explicit Local / Cloud / Offline status;
- no placeholder metrics;
- models update on the UI thread safely;
- cancellation and app shutdown do not orphan state.

Populate Session’s currently null models from the controller.

Tests:
- fake HTTP server;
- out-of-order/duplicate events;
- reconnect from last sequence;
- malformed JSON;
- expired auth;
- missing artifact;
- cancellation;
- model role mapping.

Acceptance gate:
The existing Runs, Diagnose, Train, Verify, and Capabilities workspaces display real campaign records without hardcoded demo data.
```

---

# Prompt 22 — Activate the five QML workspaces

```text
Follow Prompt 0 and Prompt 21. Do not redesign the entire frontend.

Objective:
Enable the existing UI controls and bind them to the real models/client.

Runs:
- start campaign/run;
- show run history, selected evidence, frame/video preview, detection confidence, speed, brake time, collision result.

Diagnose:
- show hypotheses, supporting/contradicting evidence, experiment status/outcomes, and established causal conclusion.

Train:
- show curriculum, dataset manifest, adapter, Cloud Run job state, metrics, and artifacts.

Verify:
- show hidden baseline/candidate results, regressions, deterministic gate, and promotion decision.

Capabilities:
- show capability state, evidence coverage, Reality Debt history, and missing-reality requirement.

Add one shared Agent Activity Timeline that links each event to its source artifact or record.

Rules:
- enable controls only when the backend advertises the capability and state permits it;
- never infer completion from elapsed time;
- label synthetic actors, inferred depth, observed Gaussian appearance, and deterministic collision truth accurately;
- display errors with actionable retry/status information;
- retain keyboard navigation and existing component system.

Acceptance gate:
A judge can follow the complete campaign across the five workspaces and every number shown is backed by an API record.
```

---

# Prompt 23 — End-to-end reliability, restart, and idempotency tests

```text
Follow Prompt 0. The complete loop must already work once before this phase.

Objective:
Prove the system is a long-running autonomous workflow rather than a fragile scripted demo.

Build an automated end-to-end test that:
1. creates a clean campaign namespace;
2. runs the baseline failure;
3. waits for causal diagnosis;
4. launches training;
5. runs hidden exam/regression;
6. reaches promotion or rejection;
7. validates event ordering, hashes, artifacts, and state.

Inject failures:
- restart Cloud Run/API after hypothesis generation;
- duplicate Pub/Sub messages;
- training job timeout then retry;
- artifact upload interruption;
- Gemini malformed structured output;
- client disconnect/reconnect;
- duplicate start request;
- cancellation during training;
- stale checkpoint receipt.

Verify:
- no duplicate scenario or training side effects;
- state resumes from durable records;
- terminal states are stable;
- dead letters are visible;
- UI reconnects from the last sequence;
- cost budget prevents runaway retries.

Create one golden-demo command that emits a final PASS/FAIL receipt. Run it three consecutive times before recording.

Acceptance gate:
All three runs pass, or every failure is precisely classified and fixed before demo recording.
```

---

# Prompt 24 — Security, provenance, privacy, and license audit

```text
Follow Prompt 0. Perform a release-blocking audit.

Check:
- no API keys, service-account JSON, tokens, signed URLs, private bucket names, or local usernames in git;
- Cloud Run endpoints require intended auth;
- service accounts are least privilege;
- GCS access and signed URL durations are bounded;
- no arbitrary command/code/path execution from Gemini or clients;
- model output is schema validated;
- uploaded archives cannot traverse paths;
- artifact hashes are checked;
- logs do not expose sensitive frames or credentials;
- demo footage/data is owned or clearly licensed;
- all third-party dependencies have recorded licenses;
- no code copied from research-only/noncommercial Gaussian repositories without permission;
- GPLv3 implications and Qt distribution obligations are accurately stated;
- generated content is tagged and excluded from measured/collision truth;
- Google AI/Cloud usage and privacy disclosures are accurate.

Run secret scanners and dependency/license reports available in the current environment. Do not install new software without approval.

Acceptance gate:
Produce SECURITY_AND_PROVENANCE.md with blockers, mitigations, and a release verdict. Zero unresolved critical findings.
```

---

# Prompt 25 — Judge-facing README, architecture, and submission assets

```text
Follow Prompt 0. The core demo must already pass.

Objective:
Rewrite the top-level README so judges understand the agent product before reconstruction history.

Required order:
1. Servo: Autonomous CI/CD for Physical AI
2. 30-second explanation
3. four-minute demo link/thumbnail placeholder
4. exact end-to-end loop
5. what happened in the recorded campaign with real IDs/metrics
6. architecture diagram
7. Google technologies and why each is used
8. reproduce the demo
9. tests
10. repository map
11. policy/trainer adapter contract
12. evidence, hidden exam, regression, and promotion gates
13. reconstruction foundation
14. honest limitations
15. license/data provenance

Update stale r9/r12 wording accurately. Do not erase historical evidence; move it below the current submission story.

Create:
- architecture SVG/PNG at submission-safe resolution;
- one-page technical architecture explanation;
- Devpost short description;
- Devpost detailed description;
- Google technology checklist;
- track justification;
- testing/reproduction instructions;
- public build article draft;
- qualifying social-post draft only if desired and compliant.

Acceptance gate:
A person unfamiliar with Servo can identify the problem, autonomous actions, Google stack, real evidence, and limitations within 60 seconds.
```

---

# Prompt 26 — Four-minute demo production

```text
Follow Prompt 0. Do not add features during recording preparation unless they fix a demo blocker.

Objective:
Produce a <=4:00 submission video whose first four minutes contain every critical scoring proof.

Sequence:
0:00–0:25 problem and one-sentence product
0:25–0:55 Gaussian world + selected policy/capability
0:55–1:25 real occluded-pedestrian failure and evidence
1:25–2:00 Gemini hypotheses + executed counterfactuals + causal conclusion
2:00–2:40 ADK/PubSub/Cloud Run training + changed checkpoint hash
2:40–3:20 hidden exam + regressions + deterministic promotion
3:20–3:40 Reality Debt + autonomous next weakness/capture requirement
3:40–4:00 architecture and explicit Google stack

Recording requirements:
- use a clean demo namespace;
- show actual Cloud Run job/log/Vertex or backend proof, not only local UI;
- magnify critical text;
- remove waiting time through edits while preserving truthful chronology;
- never fake terminal output or speed up a recording in a way that implies false runtime;
- state when a clip is prerecorded from the same verified campaign;
- include captions;
- avoid deep reconstruction metrics until after the agent payoff;
- end before four minutes.

Create a shot list, narration, expected on-screen artifact/event IDs, backup clips, and a final link-validation checklist.

Acceptance gate:
Two uninvolved reviewers can explain what the agent did, what changed, how the result was independently verified, and which Google technologies executed it.
```

---

# Prompt 27 — Final submission and release audit

```text
Follow Prompt 0. Freeze new feature work.

Objective:
Produce the final go/no-go submission receipt.

Verify:
- entrant/team eligibility;
- deadline/time zone;
- correct Taskmaster track;
- required Gemini version;
- Google ADK use visible in code and diagram;
- Google Cloud backend proof visible in video;
- repository accessible in incognito;
- setup and test instructions run from a clean checkout as far as practical;
- architecture diagram uploaded;
- video <=4:00 and public/unlisted as allowed;
- first four minutes show the complete loop;
- no broken links;
- no secrets or private data;
- commit/tag/hash recorded;
- third-party components disclosed;
- bonus article/social links valid if claimed;
- no planned post-deadline modification of linked materials.

Run:
- all C++/Qt tests;
- all Python tests;
- cloud API/workflow tests;
- golden end-to-end demo test three times;
- secret/license scan;
- artifact/link checker.

Produce FINAL_SUBMISSION_RECEIPT.md containing:
- commit/tag;
- architecture asset hashes;
- demo campaign ID;
- checkpoint before/after hashes;
- hidden exam and regression summary;
- Cloud Run execution references;
- exact test counts;
- known non-blocking limitations;
- GO or NO-GO verdict.

Do not declare GO with a mocked agent action, missing Google Cloud proof, failed hidden-data isolation, unresolved secret, or broken demo link.
```

---

# Compact emergency prompt — when only one day remains

```text
Read Prompt 0. We have one day left. Do not expand scope.

Deliver one end-to-end occluded-pedestrian RealityCI loop using the existing UI and reconstruction world:
1. deterministic seeded baseline collision;
2. RunEvidence + FailureRecord;
3. Gemini 3.7 Flash structured hypotheses;
4. executed remove-occluder, oracle-perception, and oracle-planner experiments;
5. deterministic root-cause gate;
6. small PyTorch behavior-cloning training job on Google Cloud;
7. changed checkpoint hash;
8. hidden exam and protected regression suite;
9. deterministic promotion/rejection;
10. Reality Debt update shown in Qt;
11. visible Google ADK + Cloud Run + Firestore/PubSub/GCS proof;
12. architecture diagram, README, tests, and four-minute video.

Use CPU training to avoid GPU quota. Skip WorldScout, 2DGS, 4DGS, CARLA, MuJoCo, ROS2, new renderer work, VLA integration, and UI redesign. Mocking is forbidden. Every UI value must originate from a durable record. Stop and report the first true blocker rather than hiding it.
```
