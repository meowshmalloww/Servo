# Servo / RealityCI — Four-Minute Demo Script

**Hard limit:** 4:00
**Recommended final runtime:** 3:45–3:55
**Primary objective:** Prove autonomous action, not only explain architecture.

---

## One-line story

> Servo discovers why a vehicle policy fails, creates the missing experience, trains a candidate on Google Cloud, independently verifies it, blocks regressions, and promotes only an evidence-backed checkpoint.

---

# Shot-by-shot script

## 0:00–0:12 — Cold open: the failure

**On screen**

- Native Servo app in the Runs workspace.
- Vehicle approaches an occluded crossing.
- Pedestrian emerges from behind parked vehicle.
- Collision freezes at the exact frame.
- Small overlay: `Collision at 4.82 s · perception 0.72 s late`.

**Narration**

> “This policy passes ordinary pedestrian crossings, but here it sees the pedestrian seventy-two hundredths of a second too late and crashes.”

**Scoring proof**

- real visual failure;
- specific measured evidence;
- no introductory logo delay.

---

## 0:12–0:28 — What Servo is

**On screen**

- Fast animation or UI timeline:
  `RUN → DIAGNOSE → EXPERIMENT → TRAIN → EXAM → PROMOTE`.
- Title: `Servo — Autonomous CI/CD for Physical AI`.

**Narration**

> “Servo turns the entire physical-AI improvement cycle into an autonomous, evidence-driven workflow. It does not only generate a simulation. It decides what failed, proves why, creates the missing experience, trains a candidate, tests generalization and regressions, and decides whether the checkpoint is safe to promote.”

---

## 0:28–0:48 — World and truth layers

**On screen**

- Switch to Worlds/Explore.
- Show the reconstructed Yosemite Gaussian world.
- Briefly toggle Appearance, inferred Depth, Structure, Coverage.
- Switch separately to the uncomposited native CARLA evidence.
- Overlay labels:
  - `Gaussian world = camera appearance`
  - `Native CARLA = actors + collision truth`
  - `Current build: separate evidence views, not one unified scene`

**Narration**

> “The road appearance comes from Servo’s real video-to-Gaussian reconstruction and native Vulkan renderer. Native CARLA separately owns actor positions, motion, contact, and collision. This build links their route and evidence, but does not claim they are one spatially unified scene.”

**Do not say**

- “collision-ready Gaussian world”;
- “metric LiDAR depth”;
- “complete 360-degree reconstruction.”
- “the vehicle is physically driving inside the Gaussian world.”

---

## 0:48–1:08 — Failure evidence

**On screen**

- Return to Runs.
- Show synchronized frame, detection confidence, ego speed, brake request, and collision event.
- Highlight checkpoint and scenario hashes.
- Show `FAILURE_DETECTED` in activity timeline.

**Narration**

> “The runner publishes synchronized frames, policy outputs, trajectory, brake timing, collision state, and immutable scenario and checkpoint hashes. This becomes a durable failure record, not an unstructured video for a chatbot.”

---

## 1:08–1:38 — Gemini proposes, tools prove

**On screen**

- Diagnose workspace.
- Hypotheses appear:
  - not detected;
  - detected too late;
  - planner failed;
  - controller failed;
  - occlusion caused perception failure.
- Activity timeline shows Gemini 3.7 Flash structured response.
- Counterfactual experiments execute with a four-row result table:
  1. Remove occluder → safe
  2. Reveal 1.2 s earlier → safe
  3. Oracle perception → safe
  4. Oracle planner with late perception → still unsafe or correctly interpreted result
- Root cause changes from `PROPOSED` to `ESTABLISHED`.

**Narration**

> “Gemini does not simply announce a root cause. It proposes competing hypotheses and Google ADK routes supported counterfactual tools. Removing the occluder is safe. Revealing the pedestrian earlier is safe. Oracle perception is safe. The executed interventions establish the actual capability gap: late perception under partial occlusion.”

**Scoring proof**

- model reasoning;
- real tool action;
- causal evidence;
- deterministic gate.

---

## 1:38–2:08 — Autonomous curriculum and Cloud Run training

**On screen**

- Train workspace.
- Curriculum dimensions appear: occlusion, ego speed, pedestrian speed, angle, contrast.
- Training/hidden split shown; hidden manifest visibly sealed.
- Cloud Run Job dispatch: `TRAINING_REQUESTED`.
- Cut to Google Cloud Console or terminal showing actual Cloud Run Job execution.
- Show training metrics briefly.
- Baseline hash → candidate hash.

**Narration**

> “Servo creates an easy-to-hard curriculum around the measured weakness and reserves hidden scenarios before training. The authenticated API dispatches a real Cloud Run Job. The small PyTorch policy learns from oracle trajectories, and the model weights produce a new content-addressed checkpoint.”

**Visible proof required**

- Google Cloud project/service name;
- Cloud Run Job status or logs;
- real candidate hash different from baseline;
- no fake terminal output.

---

## 2:08–2:38 — Hidden exam

**On screen**

- Verify workspace.
- Baseline and candidate hidden performance chart.
- Example hidden scenario replay: candidate brakes and stops before pedestrian.
- Hidden success changes, for example, `31% → 93%`.
- Confidence interval or number of scenarios visible.

**Narration**

> “The Trainer never sees these seeds. A separate Examiner runs the candidate on completely hidden scenarios. The baseline fails most difficult occlusions; the candidate succeeds on ninety-three percent.”

**Do not use exact numbers unless they are from the final verified campaign.**

---

## 2:38–2:58 — Regression protection and promotion

**On screen**

- Regression table for ordinary crossing, no pedestrian, visible pedestrian, braking control.
- All protected gates pass.
- Deterministic promotion panel changes to `PROMOTED`.
- Show decision rule and hash verification.

**Narration**

> “Servo also reruns every protected capability. An LLM cannot waive these gates. Deterministic code checks generalization, confidence, checkpoint integrity, and regression limits, then promotes or rejects the candidate.”

---

## 2:58–3:18 — Reality Debt and continuation

**On screen**

- Capabilities workspace.
- `Occluded pedestrian: FAILED → VERIFIED`.
- Reality Debt chart decreases.
- Agent selects next weakness, such as glare or low-light crossing.
- Optional WorldScout capture mission appears when evidence is absent.

**Narration**

> “The verified result updates Servo’s capability memory and reduces Reality Debt. No person chooses the next lesson. The agent selects the next uncovered weakness, and when the existing worlds cannot teach it, WorldScout creates a precise real-world capture mission instead of training forever.”

---

## 3:18–3:43 — Architecture proof

**On screen**

- Full architecture diagram, zoomed enough to read.
- Highlight in sequence:
  1. Qt/QML + Vulkan desktop
  2. Cloud Run API + Google ADK graph
  3. Vertex AI / Gemini 3.7 Flash
  4. Firestore
  5. Cloud Storage
  6. Cloud Run Jobs
  7. deterministic exam/promotion services

**Narration**

> “The native Qt and Vulkan desktop is the evidence workbench. Google ADK runs the workflow on Cloud Run. Gemini 3.7 Flash performs grounded diagnosis and curriculum planning. Firestore indexes workflow state, Cloud Storage keeps evidence and checkpoints, and Cloud Run Jobs execute campaigns.”

---

## 3:43–3:55 — Final line

**On screen**

- Return to the successful hidden scenario.
- Text: `Servo — RealityCI for Physical AI`.
- Small text: `Run. Fail. Understand. Learn. Prove. Continue.`

**Narration**

> “Servo does for learned physical systems what CI/CD did for software: continuously discover failures, fix them, prove the improvement, and prevent regressions.”

End immediately. Do not add a long credits screen.

---

# Required campaign evidence before recording

Replace all placeholders with one frozen campaign’s real values:

```text
Campaign ID:
World ID/hash:
Baseline checkpoint hash:
Candidate checkpoint hash:
Failure ID:
Diagnosis ID:
Counterfactual batch ID:
Training job execution ID:
Hidden exam ID:
Regression report ID:
Promotion decision ID:
Reality Debt before/after:
Cloud Run service/job names:
Gemini model ID:
ADK package/version:
Final test receipt:
```

Every value visible in the video must correspond to the same campaign or be clearly labeled as a separate reconstruction diagnostic.

---

# Editing rules

1. Keep the final timeline under 4:00.
2. Use cuts to remove waiting, but never imply false runtime.
3. When training is shortened in the edit, show start time, finish time, duration, and job receipt.
4. Use captions for every critical narration line.
5. Use 125–150% UI scaling or crop/zoom critical tables.
6. Do not show tiny terminal text for more than a few seconds.
7. Do not spend over 20 seconds on Gaussian reconstruction details.
8. Do not open with an architecture diagram.
9. Do not call a generated actor observed data.
10. Do not call relative depth metric or LiDAR.
11. Do not describe promotion as a Gemini decision.
12. Do not claim support for arbitrary trainable models.
13. Do not show local-only behavior without visible Google Cloud proof.
14. Do not use different campaign IDs in different shots unless explained.

---

# Backup plan for live-demo risk

Record these verified clips separately:

- baseline collision;
- diagnosis and counterfactual result table;
- Cloud Run training job start/completion;
- candidate hidden success;
- regression/promotion panel;
- Reality Debt update;
- architecture diagram;
- one continuous screen recording of the full campaign for provenance.

The final edited video can use the short clips, while the unedited run remains available in the repository or project page as supporting evidence.

---

# Reviewer comprehension test

Before upload, ask two people who have not worked on Servo to watch once and answer:

1. What problem does Servo solve?
2. What did Gemini decide?
3. What real actions did the system execute?
4. How was the root cause proven rather than guessed?
5. Did model weights actually change?
6. How was hidden generalization tested?
7. Who made the promotion decision?
8. What role did Google Cloud play?
9. What role did the Gaussian world play?
10. What happened automatically after promotion?

Revise the video if either reviewer cannot answer at least eight correctly.
