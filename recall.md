# Servo project recall

Last updated: 2026-08-31

Read this file first when preparing the hackathon submission, writing project
copy, recording the demo, or resuming implementation. It is a project-memory
document, not a secret store and not a substitute for evidence artifacts.

## Identity

- **Project:** Servo
- **Expanded name:** Simulation Engine for Real-world Vehicle Optimization
- **Repository:** https://github.com/meowshmalloww/Servo
- **Hackathon:** All Things Agentic Hackathon
- **Organization:** Individual submission; leave organization blank unless an
  organization is created before submission.
- **Elevator pitch:** An autonomous CI/CD engine for physical AI: reconstruct
  3D worlds, test driving policies, diagnose failures, retrain models, and
  deploy evidence-backed updates.

## What Servo is

Servo is a native Windows control center for continuously improving physical-AI
policies. The operator describes a capability goal to Servo AI Assistant. Servo
then coordinates a bounded, evidence-backed workflow:

```text
media / simulator evidence
  -> reconstruct and register a world
  -> run a policy in deterministic scenarios
  -> capture synchronized failure evidence
  -> ask Gemini for bounded hypotheses and experiment plans
  -> execute counterfactual experiments
  -> establish root cause with deterministic code
  -> create targeted training experience
  -> retrain a supported policy
  -> run hidden examination and regression gates
  -> promote or reject
  -> publish the evidence-backed artifact
```

The LLM may investigate, explain, and select allowed tools. It cannot override
promotion gates, invent evidence, modify hidden tests, or declare a pass.

## Problem

Physical-AI teams often have disconnected reconstruction, simulation,
diagnosis, training, evaluation, and deployment tools. A failure may be visible
without a reproducible causal record, and a newly trained checkpoint may fix
one case while silently regressing another.

Servo turns this into CI/CD: every world, scenario, observation, intervention,
checkpoint, hidden result, and decision is content-addressed and auditable.

## Main product surfaces

- **Worlds:** create, explore, organize, validate, and remove reconstructed
  Gaussian worlds.
- **Runs:** execute a connected driving policy and capture synchronized
  evidence.
- **Diagnose:** rank hypotheses and run measured counterfactual experiments.
- **Train:** construct targeted experiences and produce a changed checkpoint.
- **Verify:** hidden examination, regression protection, and deterministic
  promotion/rejection.
- **Capabilities / Reality Debt:** record what is proven, missing, inferred, or
  unsafe to claim.
- **Servo AI Assistant:** one conversational entry point for inspecting state,
  executing bounded ADK workflows, reading logs, and explaining results.

## Google technologies actually used

### Google Agent Development Kit

- Google ADK 2.7.1 executes Servo's resumable campaign graph.
- The campaign is a durable sequence of verified states rather than one large
  free-form prompt.
- ADK tool calls operate through explicit schemas and postcondition checks.

### Google Gen AI SDK and Gemini

- Gemini 3.7 Flash is the configured diagnostician/planner model.
- The Google Gen AI SDK provides structured model calls.
- Gemini proposes causal hypotheses, selects bounded Servo tools, summarizes
  evidence, and plans the next allowed action.
- Deterministic code remains the authority for causality and promotion.

### Vertex AI

- The cloud campaign job is configured to use Gemini through Vertex AI with
  its attached Google Cloud service identity.
- Local development can use the configured Gemini provider without committing
  credentials.

### Cloud Run

- A Firebase-authenticated control API and asynchronous complete-campaign
  Cloud Run Job are implemented and reproducibly scripted.
- A real `.run.app` deployment and Cloud Run execution receipt are still
  required before claiming live cloud deployment.

### Firebase Authentication

- Native Qt email/password sign-in uses Firebase Authentication's REST API.
- The backend uses Firebase Admin verification with revocation checking.
- ID and refresh tokens are held in memory; signing out clears them.
- No JavaScript Firebase SDK, npm package, or CDN script is used by the desktop.

### Cloud Firestore

- Stores bounded searchable campaign and artifact metadata.
- Stores state, provenance, hashes, timestamps, and `gs://` pointers.
- Never stores Gaussian PLYs, videos, textures, or checkpoint bodies.

### Cloud Storage

- Stores versioned campaign workspaces, event logs, checkpoints, examination
  results, decisions, world bundles, Gaussian PLYs, videos, and hash manifests.
- Generic publishing is implemented in `cloud/infra/publish-artifact.ps1`.

### Cloud Build, Artifact Registry, IAM, and Logging

- Cloud Build produces the API and campaign-job images.
- Artifact Registry stores versioned container images.
- Dedicated service identities separate API and job permissions.
- Cloud Logging is enabled by the deployment script.

## SDK and ADK evidence audit (2026-08-31)

This section is the submission-safe record of what Servo actually imports and
executes. **Implemented** means real runtime code exists. **Locally verified**
means a receipt or automated test exercised that code. **Cloud-proven** requires
a real deployed revision/job receipt; configuration or mocked tests alone do
not qualify.

| Technology | Exact use in Servo | Evidence | Honest status |
| --- | --- | --- | --- |
| Google Agent Development Kit `2.7.1` | A real `SequentialAgent` made from twelve `BaseAgent` state nodes runs through ADK `Runner` events. The graph resumes the deterministic RealityCI campaign and refuses to replace the engine's durable state. | `tools/realityci/adk_graph.py`; `tests/realityci/test_adk_graph.py`; live Ask Servo receipt below | Implemented and locally verified |
| Google Gen AI SDK `2.19.0` | Structured Gemini calls propose causal hypotheses and select one allowlisted Ask Servo action. Servo executes the tool, then re-reads state, events, and artifacts before reporting success. | `tools/realityci/diagnosis/gemini.py`; `tools/realityci/ask_servo/tools.py`; `tools/realityci/assistant_tools.py`; live receipt below | Implemented and locally live-verified |
| Firebase Admin SDK `7.5.0` | The Cloud Run API verifies Firebase ID tokens, including revocation checks. | `cloud/control_api/app/auth.py`; backend authentication tests; deployed API rejects missing tokens with HTTP 401 | Implemented, locally tested, and deployed; a real user sign-in receipt is still required |
| Cloud Storage client `>=3.4,<4` | Synchronizes versioned campaign workspaces and retrieves explicitly addressed checkpoints/artifacts. Large PLY, video, checkpoint, and evidence bytes belong here rather than in Firestore. | `cloud/control_api/app/object_store.py`; `cloud/campaign_job/main.py`; `gs://servo-1f808-servo-artifacts` | Implemented and deployed; a completed campaign artifact receipt is still required |
| Cloud Firestore client `>=2.21,<3` | Writes bounded campaign/artifact metadata, hashes, status, and `gs://` pointers; it does not store large artifact bodies. | `cloud/control_api/app/firestore_index.py`; `cloud/campaign_job/main.py`; Firestore `(default)` in `us-central1` | Implemented and deployed; a completed campaign metadata receipt is still required |
| Vertex AI access | Python agents can use Vertex AI through the Google Gen AI SDK with ADC/service identity. The native Qt assistant uses the Vertex/Gemini REST API directly, not the Python SDK. | Vertex mode in Gemini clients; `cloud/infra/deploy.ps1`; `src/ui/chat/AiChatController.cpp` | Implemented/configured; deployed Vertex execution not yet cloud-proven |

### Was ADK used well and fully?

**It is used meaningfully, not as a decorative dependency.** ADK owns the
executable orchestration graph, emits node events, carries session state, and is
covered by complete-run, no-op-rerun, and fresh-process-resume tests. Gemini is
also operational rather than cosmetic: it selects a bounded action and proposes
structured diagnoses that feed real experiments.

**It is not a fully managed production deployment.** ADK currently uses
`InMemorySessionService`; durable truth and resume are intentionally owned by
Servo's hash-addressed campaign workspace and idempotent engine. This is a
defensible safety design, but it is not a managed ADK session backend. Servo now
has a real Cloud Run API revision, ready background job, Firestore database, and
versioned GCS bucket; it has not yet produced a completed deployed campaign or
Vertex AI execution receipt. The graph uses deterministic
`BaseAgent` nodes around verified operations rather than making every state a
free-form `LlmAgent`.

For the hackathon, this is already substantial ADK/Gen AI SDK usage. The best
next proof is a real signed-in Cloud Run campaign with stored receipts, not
adding unrelated Google SDKs merely to increase the technology count.

### Google Cloud deployment receipt (2026-08-31)

- Project: `servo-1f808` (`224961191633`), region `us-central1`.
- Cloud Run API: `servo-realityci-api`, ready revision
  `servo-realityci-api-00003-54z`, 100% traffic, maximum one instance.
- API URL: `https://servo-realityci-api-mfqkrzkvkq-uc.a.run.app`.
- Missing Firebase bearer tokens are rejected with HTTP 401 by Servo's API.
- Cloud Run job: `servo-campaign-job`, ready under the dedicated
  `servo-realityci-job` service account.
- Artifact Registry images: `servo-realityci-api:cpu` and
  `servo-campaign-job:cpu`.
- Storage: versioned `gs://servo-1f808-servo-artifacts`; noncurrent versions
  expire after 30 days.
- Metadata: Firestore `(default)`, Native mode, `us-central1`, deletion
  protection enabled.
- Authentication: Firebase Email/Password provider enabled. No operator account
  password is committed to the repository.
- Billing: linked to the user-selected Servo billing account. A $140 warning
  budget has 50%, 75%, 90%, and 100% thresholds. A budget is an alert, not a
  spending cap; charges can continue after promotional credits are exhausted.

### Live Gemini/ADK receipt

- Receipt: `campaigns/.ask-servo/runs/askrun-0f577c2f7b7443e0.json`
- Content hash:
  `sha256:0b63bbb6469d5df8a2075c5aed2aefcf97dd5933b33ddf2c6af6fa59fcdc7d61`
- Provider: `gemini`
- Campaign: `cam-91c726ae91e94ccd`
- Gemini inspected the active campaign and selected the allowlisted
  `run_to_completion` action.
- Google ADK `2.7.1` ran the campaign to `completed_rejected`.
- Servo then independently verified campaign state, ordered events, and
  artifacts before completing the assistant run.
- The deterministic promotion gate rejected the candidate. This is positive
  fail-closed evidence: neither Gemini nor ADK can declare a model promoted
  without the measured gate passing.

### Technologies not used and not claimable

Servo does **not** currently use Genkit, Antigravity SDK, Firebase JavaScript
SDK, `google-cloud-aiplatform`, Pub/Sub, Cloud SQL, GKE, Veo, Lyria, Gemma, or a
managed ADK/Agent Engine deployment. Gemini Robotics-ER is planning context,
not an executed integration. Do not select or name any of these in the
submission unless executable code and a reproducible receipt are added first.

## Reconstruction and simulation

- Media reconstruction uses FFmpeg, COLMAP/PyCOLMAP, PyTorch CUDA, and gsplat
  under a checksum-locked native Windows runtime.
- Servo owns the orchestration, training policy, manifests, audits, world
  library, Vulkan renderer, diagnostics, and publication gates.
- T5 is the strongest Yosemite hackathon visual candidate but remains
  nonmetric and `collisionValidated=false`.
- The Gaussian world is appearance evidence, not collision geometry.
- CARLA/OpenDRIVE owns simulation collision and road physics.
- The current corridor and scale are inferred from camera evidence.
- Off-axis Gaussian blur, gaps, and fiberglass artifacts remain an honest
  limitation of the captured forward monocular evidence.

## 3D asset format support

- **Servo Gaussian world:** a specialized 3DGS `.ply` inside a validated Servo
  world bundle with `world.json`, cameras, hashes, and provenance. An arbitrary
  mesh or point-cloud PLY is not automatically a valid Servo world.
- **Native vehicle overlay:** bundled `.glb` assets are rendered through Qt
  Quick 3D in the Gaussian view. The current accepted vehicle is an OpenX Volvo
  EX30 GLB.
- **OBJ:** currently generated for the inferred road debug/physics collider;
  it is not exposed as a general visual-world import workflow.
- **glTF/GLB/OBJ runtime import:** Qt's RuntimeLoader can support these formats,
  but Servo does not yet expose a user-facing arbitrary-model importer,
  validation gate, placement editor, or persisted asset registry.
- **USDZ:** not supported by Servo's runtime loading path.

For a Sketchfab asset intended as a vehicle or prop, prefer a self-contained
`.glb`. A 4K-texture GLB is the default hackathon balance; 8K should be used
only for a close-up hero asset after measuring GPU memory and frame time.

### Trainable road/world map formats

- **CARLA cooked `.umap` maps:** current full simulation-world format. These
  provide CARLA geometry, collision, lanes, spawn points, signals, actors, and
  sensor simulation when installed in the CARLA package.
- **OpenDRIVE `.xodr`:** current runtime road-network format. Servo can ask
  CARLA to generate a world from it, and executable Servo bundles already bind
  `map.xodr`, `route.json`, `alignment.json`, validation, and provenance.
- **OpenStreetMap `.osm`:** not directly importable in Servo's UI. CARLA's
  `Osm2Odr` converter can create `.xodr`, which Servo/CARLA can then run.
- **Custom photoreal CARLA map:** author visual geometry as `.fbx` plus road
  semantics as `.xodr`, then cook/package it with CARLA/Unreal into a CARLA
  map. This is the route for a trainable world with both visuals and physics.
- **3DGS `.ply`:** appearance layer only; it does not contain traffic rules,
  collision, or free-space truth.
- **GLB/glTF/OBJ:** visual vehicles and props only until an asset receives a
  collider, semantic class, transform, behavior/blueprint, and evidence record.
  A traffic-light GLB is not an operational traffic signal by itself.
- **USDZ:** unsupported.

## Real CARLA evidence

- CARLA 0.9.16 packaged-runtime discovery and owned process/session management
  are implemented.
- Synchronous explicit-control workers, inferred-corridor OpenDRIVE,
  CARLA/3DGS/hybrid observations, three DriveMA cameras, IMU, collision, lane,
  and terminal-stop evidence are implemented.
- Accepted T5/DriveMA snow evidence completed about 94.3% of its inferred route
  with zero collisions and one lane invasion.
- The evidence records 90% snow accumulation, a 9.81 m/s^2 CARLA gravity
  reference, approximately 9.76 m/s^2 median measured IMU magnitude, and
  passing ground contact.
- A separate pedestrian challenge produced a real collision failure. Servo
  classified it and preserved it as failure evidence; it is not presented as a
  pass.
- The rejected depth-aware CARLA/T5 composite is forensic evidence only and
  must not be used as submission imagery or described as unified geometry.

## Agentic campaign evidence

- Servo has executed the complete local campaign loop with durable ordered
  events and artifacts.
- A golden occluded-pedestrian campaign trained a changed PyTorch checkpoint,
  improved the hidden exam from 4/8 to 7/8, passed protected regression gates,
  and received a deterministic promotion decision.
- A separate live Gemini/ADK campaign inspected evidence and was correctly
  rejected by deterministic promotion gates.
- The result demonstrates that Servo does not simply approve whatever the
  assistant recommends.

## Verification baseline

- RealityCI test suite: **194 passed, 1 skipped**.
- Native Qt/C++ tests: **13/13 passed** on the documented build.
- Tests cover ADK graph execution and resume, structured Gemini boundaries,
  Firebase verification, Cloud Run dispatch contracts, training, hidden exams,
  regression and promotion, artifact durability, and fail-closed CARLA route
  validation.
- Unit tests are not represented as a live Cloud Run deployment or live drive.

## Cloud data architecture

```text
Firebase Authentication -> operator identity
Cloud Run API            -> authenticated control plane
Cloud Run Job            -> one durable campaign execution
Vertex AI / Gemini       -> bounded diagnosis and planning
Cloud Firestore          -> metadata, state, hashes, pointers
Cloud Storage            -> worlds, models, checkpoints, videos, evidence
Artifact Registry        -> API/job container images
Cloud Logging            -> operational logs
```

Firebase project `servo-1f808` and Google Cloud project `servo-1f808` are the
same underlying project. Firebase adds Firebase-specific configuration and
console experiences to the Google Cloud project; IAM, project ID, resources,
and billing are shared.

Detailed setup belongs in:

- `docs/AUTHENTICATION.md`
- `docs/CLOUD_ARTIFACT_STORAGE.md`
- `cloud/infra/README.md`

Do not put setup instructions or secrets into this recall file.

## Submission answers

### Tagline

**Autonomous CI/CD for physical AI—reconstruct worlds, test policies, diagnose
failures, retrain, and deploy evidence-backed updates.**

### Organization

Leave blank or select individual unless Servo is submitted through a real
organization.

### Reproducible testing instructions

Yes. The README contains fresh-environment commands, expected results, native
build/test commands, reconstruction runtime setup, and the boundary between
local verification and real cloud proof.

### Google SDKs

- Google Agent Development Kit 2.7.1
- Google Gen AI SDK
- Firebase Admin SDK
- Google Cloud Storage and Firestore server client libraries

Do not claim Genkit or Antigravity SDK; they are not part of the verified Servo
runtime.

### Google AI models

- Gemini 3.7 Flash through the Google Gen AI SDK / Vertex AI configuration.

The submission question means models executed by the project, not models used
only by developers while writing code. Do not list Veo, Lyria, or Gemma unless
Servo actually calls them and produces reproducible evidence before submission.

### Google Cloud services

- Vertex AI
- Cloud Run service and Job
- Cloud Build
- Artifact Registry
- Cloud Storage
- Cloud Firestore
- Firebase Authentication
- IAM service accounts
- Cloud Logging

Do not claim Pub/Sub, Cloud SQL, or Google Kubernetes Engine; Servo does not
need them for the bounded hackathon architecture and has not verified them.

## Four-minute demo story

1. Ask Servo to improve a driving capability.
2. Show the reconstructed T5 world and explicit reconstruction limitations.
3. Run the policy in real CARLA snow/pedestrian scenarios.
4. Open synchronized failure evidence and the diagnosis.
5. Let Gemini select bounded investigations through ADK.
6. Show targeted training producing a changed checkpoint hash.
7. Run hidden exam and protected regression gates.
8. Show deterministic promote or reject and the cloud artifact/evidence record.

Never spend the demo implying that a visual composite is physical geometry.

## Claims allowed

- Autonomous, evidence-backed CI/CD workflow for physical-AI policies.
- Video/media-to-Gaussian reconstruction with native exploration.
- Real CARLA execution and physical evidence for the documented sessions.
- Bounded Gemini/ADK orchestration with deterministic safety gates.
- Real PyTorch checkpoint training and hash-verified promotion/rejection.
- Reproducible Google Cloud deployment architecture.

## Claims prohibited until separately proven

- Collision-safe or autonomous-driving-ready Gaussian geometry.
- Metric or LiDAR-derived Yosemite reconstruction.
- Complete measured 360-degree reconstruction from the forward video.
- Unified CARLA collision geometry and Gaussian appearance.
- Production vehicle deployment.
- Live Google Cloud execution before a `.run.app` revision and job receipt exist.
- Pub/Sub, Cloud SQL, GKE, Genkit, Veo, Lyria, Gemma, or other unused services.

## Submission assets

- Thumbnail: `docs/assets/submission/servo-devpost-thumbnail.png`
- Real application evidence: `docs/assets/submission/servo-live-app-20260831.png`
- Reconstruction videos and previews: `docs/assets/reconstruction/`
- Demo script: `docs/Servo_RealityCI_4_Minute_Demo_Script.md`
- Submission overview: `docs/SUBMISSION_OVERVIEW.md`
- Architecture: `docs/ASK_SERVO_ARCHITECTURE.md`

## Next verified work

1. Enable Firebase Email/Password Authentication.
2. Link the hackathon Google Cloud billing account to project `servo-1f808`.
3. Create Firestore `(default)` and Cloud Storage in the chosen shared region.
4. Install/authenticate Google Cloud CLI only with explicit approval.
5. Run `cloud/infra/deploy.ps1` and capture the real revision/job receipt.
6. Test native Firebase sign-in against the real Cloud Run API.
7. Publish one T5 world and one promoted model with hash manifests.
8. Verify Firestore pointers and Cloud Storage objects.
9. Record the final four-minute evidence-first demo.
