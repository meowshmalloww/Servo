# Servo / RealityCI — Eight-Day Execution Backlog

**Submission deadline:** 2026-08-31, 5:00 PM Pacific
**Internal freeze target:** 2026-08-30, 12:00 PM Pacific

Legend:

- **P0** = submission blocker
- **P1** = major score improvement after P0
- **P2** = stretch only
- **Evidence** = objective artifact proving completion

---

## P0 critical path

| ID | Work item | Depends on | Done when | Evidence |
|---|---|---|---|---|
| P0-01 | Confirm entrant/team eligibility | none | age-of-majority and team requirements verified | written eligibility check |
| P0-02 | Isolate clean hackathon branch | none | local r12 work separated from unrelated UI/diagnostics | git inventory + clean commit plan |
| P0-03 | Run r12 exact-PLY v3 audit | P0-02 | exact PLY, video, metrics, r11/r12 comparison complete | audit JSON, MP4, hashes |
| P0-04 | Freeze one demo world and camera envelope | P0-03 | background frames and declared limitations selected | world/scenario manifest |
| P0-05 | Create RealityCI schemas/state machine | P0-02 | schemas/hashes/transitions tested | schema unit tests |
| P0-06 | Build deterministic scenario runner | P0-04, P0-05 | one repeatable occluded-pedestrian collision | run evidence + video |
| P0-07 | Build trainable PyTorch policy adapter | P0-06 | baseline passes ordinary cases, fails target band | baseline checkpoint + matrix |
| P0-08 | Build deterministic failure evaluator | P0-06, P0-07 | collision/late detection produce failure record | FailureRecord JSON |
| P0-09 | Deploy Cloud Run/Firestore/PubSub/GCS skeleton | P0-05 | smoke campaign creates state/event/artifact | cloud logs + receipt |
| P0-10 | Implement ADK durable graph | P0-09 | fixture workflow resumes after restart | workflow tests |
| P0-11 | Add Gemini structured Diagnostician | P0-08, P0-10 | testable hypotheses and supported interventions produced | response receipt + schema |
| P0-12 | Execute counterfactual experiments | P0-06, P0-11 | remove-occluder/oracles run and publish outcomes | experiment records |
| P0-13 | Deterministic root-cause gate | P0-12 | perception/occlusion conclusion established from outcomes | CausalDiagnosis JSON |
| P0-14 | Curriculum + hidden seed isolation | P0-13 | train and hidden manifests created separately | isolation receipt |
| P0-15 | Real Cloud Run training job | P0-07, P0-14 | weights change; candidate checkpoint/hash created | job logs + checkpoint receipt |
| P0-16 | Hidden exam | P0-15 | baseline/candidate evaluated on unseen seeds | exam report |
| P0-17 | Regression suite | P0-15 | protected ordinary capabilities compared | regression report |
| P0-18 | Deterministic promotion gate | P0-16, P0-17 | candidate promoted or rejected by code | promotion decision |
| P0-19 | Reality Debt update/next weakness | P0-18 | capability state and debt change from evidence | capability/debt snapshot |
| P0-20 | Qt API client and data models | P0-09 | real ordered backend events populate C++ models | client integration tests |
| P0-21 | Activate Runs/Diagnose/Train/Verify/Capabilities | P0-20 | end-to-end campaign visible with no fake data | screen recording |
| P0-22 | Golden end-to-end test | P0-06–P0-21 | complete loop passes 3 consecutive runs | PASS receipts |
| P0-23 | Architecture/README/submission assets | P0-22 | judge can reproduce and understand stack | diagram + README |
| P0-24 | Four-minute video | P0-22, P0-23 | complete action loop and cloud proof inside 4:00 | final video |
| P0-25 | Final security/license/link audit | all | zero critical findings; all links accessible | final receipt |

---

## P1 score improvements

| ID | Work item | Start only after | Done when | Evidence |
|---|---|---|---|---|
| P1-01 | Agent activity timeline | P0-21 | every step links to a durable record | UI test/screens |
| P1-02 | Forced restart/idempotency demonstration | P0-22 | no duplicate job after service restart/message replay | recovery video/log |
| P1-03 | Gemini Robotics-ER 2 second opinion | P0-22 | independent physical analysis stored, never overrides gates | adjudication record |
| P1-04 | Flash-Lite telemetry compression | P0-22 | cost/latency reduction with semantic equivalence tests | benchmark |
| P1-05 | WorldScout capture mission | P0-22 | missing evidence produces structured mission | CaptureMission JSON |
| P1-06 | One bounded Gaussian repair | P0-03 and P0-22 | measured failure improves without protected regression | before/after audit |
| P1-07 | Build article and social bonus | P0-22 | public materials accurately document build | valid links |

---

## P2 post-core stretch

| ID | Work item | Reason to defer |
|---|---|---|
| P2-01 | Native 2DGS/DN-Splatter confirmation | representation and viewer parity work can consume days |
| P2-02 | StopThePop-style Vulkan compute rasterizer | large clean-room renderer project |
| P2-03 | Dynamic object/4D Gaussian layers | needs tracking and careful input assumptions |
| P2-04 | Metric road mesh and OpenDRIVE topology | requires scale anchor and structural validation |
| P2-05 | VLA-JEPA adapter/training | large integration and training uncertainty |
| P2-06 | CARLA/MuJoCo/ROS2 adapters | broadens demo without strengthening core loop |
| P2-07 | ArtiFixer/generated completion | large GPU and provenance/licensing burden |

---

# Daily schedule

## August 23 — Scope, repository, audit, cloud bootstrap

- P0-01, P0-02, P0-03, P0-04, P0-05
- create GCP project/resources skeleton
- target: measured reconstruction report + schema tests

## August 24 — Runner, policy, failure

- P0-06, P0-07, P0-08
- target: one command produces the baseline collision and FailureRecord

## August 25 — Cloud control plane

- P0-09, begin P0-10, begin P0-20
- target: a real Cloud Run campaign with Firestore/PubSub/GCS evidence

## August 26 — ADK diagnosis and causal experiments

- finish P0-10; P0-11, P0-12, P0-13
- target: collision becomes experiment-backed root cause

## August 27 — Training and verification

- P0-14, P0-15, P0-16, P0-17, P0-18, P0-19
- target: fail-to-promote loop works without Qt

## August 28 — Qt integration and early Devpost draft

- finish P0-20; P0-21; begin P0-22, P0-23
- verify cloud credits/request cutoff
- target: full loop visible in desktop app

## August 29 — Reliability and one visual improvement

- finish P0-22
- P1-01, P1-02, optionally P1-06
- target: three consecutive golden passes and restart proof

## August 30 — Freeze and record

- P0-23, P0-24, P0-25
- no new features after noon unless a demo blocker

## August 31 — Submit early

- verify links/incognito/first four minutes
- submit hours before 5:00 PM PT
- do not modify linked materials after submission lock

---

# Stop rules

Stop a workstream immediately when any condition is true:

1. It does not contribute to the fail-to-promote loop or required submission evidence.
2. It requires new sensors/data that are unavailable before the deadline.
3. A 300-step or short smoke test regresses protected metrics.
4. It depends on pending GPU quota when a CPU path can satisfy the demo.
5. It replaces real backend state with hardcoded UI data.
6. It requires copying code with incompatible or unclear licensing.
7. It risks losing the dirty local worktree.
8. It creates a safety claim unsupported by the current monocular artifact.

---

# Final go/no-go gates

## GO only when

- all P0-01 through P0-25 are complete;
- complete loop passes three consecutive times;
- checkpoint hash changes after real training;
- hidden seeds remain isolated;
- deterministic promotion gate passes/rejects correctly;
- Cloud Run/Google ADK/Gemini execution is visibly proven;
- repository and video links work in incognito;
- no secrets or critical license/security issues exist.

## NO-GO until fixed when

- any major action is mocked;
- Gemini only explains but does not cause tool execution;
- training does not change weights;
- hidden exam reuses training scenarios;
- promotion is an LLM opinion;
- UI displays fabricated progress;
- public repo does not match the demonstrated build;
- eligibility is unresolved.
