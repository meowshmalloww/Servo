# Servo — RealityCI submission overview (backend build)

> Status: **complete local agentic campaign loop, desktop Ask Servo, and a
> separate real CARLA vertical slice, verified locally**. These are not yet one
> end-to-end T5/CARLA training campaign. Cloud deployment remains a required
> submission step.

## 30-second explanation

Servo is autonomous CI/CD for physical AI. Give it a policy, a world and a
capability objective: it runs the policy until it fails, produces a sealed
evidence bundle, proposes competing hypotheses, executes real counterfactual
experiments, establishes root cause with a deterministic gate, generates a
targeted curriculum with hidden exams reserved *before* training, fine-tunes
a real PyTorch policy, evaluates on unseen seeds, protects prior
capabilities with regression suites, promotes or rejects by pure code, then
updates Reality Debt and picks the next weakness autonomously.

## What actually ran here (real artifacts, not claims)

- Accepted T5 visual route + separate DriveMA/CARLA snow session
  `sim-6291857fc6c84f13`: 94.26% route completion, zero collisions, one lane
  event, three policy cameras, measured gravity/contact pass, and a physically
  applied 12-frame full-brake terminal stop at 0.056 m/s. It is hash-bound to
  `yosemite-t5-hybrid-full-route-v1-20260828`, not Final v2.
- The former T5/CARLA depth-aware composite is rejected forensic evidence; it
  is not a spatially unified render and must not appear in submission footage.
- Accepted-T5-route pedestrian challenge `sim-40185a19d24e45a9`: a grounded,
  owned CARLA walker crossed the generated lane and DriveMA collided at 53.86%
  progress. Servo classified `collision_pedestrian`; cleanup destroyed all
  nine actors. This is a policy failure artifact, not a pass.
- Ask Servo live Gemini run `askrun-0f577c2f7b7443e0` inspected campaign
  `cam-91c726ae91e94ccd`, selected `run_to_completion`, executed Google ADK
  2.7.1, and verified 21 ordered events and 80 artifacts. The deterministic
  promotion gate rejected the candidate. Receipt hash:
  `sha256:0b63bbb6469d5df8a2075c5aed2aefcf97dd5933b33ddf2c6af6fa59fcdc7d61`.

- Trained baseline (`demo/occluded_pedestrian/baseline/baseline.pt`,
  sha256 `3d9785…`) passes ordinary crossings **100%** but drops to **62.5%**
  on the occluded band with ~2.8 s perception delay.
- Full campaign receipt:
  `demo/occluded_pedestrian/campaign-receipted/campaign-receipt.json`
  - status **PASS**, decision **promoted**
  - hidden exam `exam-5126e25d0909428b`: baseline 4/8 → candidate **7/8**
  - candidate checkpoint `sha256:120a7f…` ≠ parent `8b2af1…`
  - promotion decision `promo-8b20d94f838d433c`, all checks passed
  - Reality Debt snapshot `debt-46bbc7a27de64d93`
- Golden loop repeated 3× consecutively with identical structure.

## Reproduce

```powershell
$py = "<path to reconstruction venv>\python.exe"
& $py -m pytest tests\realityci -q                       # 170 passed, 1 optional skip
& $py -m tools.realityci.cli run-campaign `
    --output demo\occluded_pedestrian\campaign-x `
    --checkpoint demo\occluded_pedestrian\baseline\baseline.pt
```

One command; ends with `campaign-receipt.json` (PASS/FAIL) plus the complete
event log, evidence bundles, exam/regression/decision records.

## Architecture

See `assets/realityci-architecture.svg` and `REALITYCI_BACKEND.md`
(module map, state owners, guarantees). ADK execution path lives in
`tools/realityci/adk_graph.py` (Google ADK 2.7.1 SequentialAgent over the
12 verified pipeline states; session persistence; resumable).

## Google technologies

| Tech | Role |
|---|---|
| Gemini API / Vertex AI-compatible planner | structured causal hypotheses and bounded tool selection; current local credentials use the Gemini API path |
| Google ADK | durable graph execution of the campaign (`adk_graph.py`) |
| Cloud Run | Firebase-authenticated control API plus one asynchronous complete-campaign Job; deployment proof is still required |
| Vertex AI | ADC/service-account Gemini 3.7 Flash execution inside the campaign Job |
| Cloud Storage | versioned campaign workspace, ordered events, checkpoints, hidden exam, decision, and cloud execution receipt |
| Cloud Firestore | bounded campaign and artifact metadata index; large bytes remain in Cloud Storage |
| Firebase Authentication | native sign-in and server-side ID-token/revocation verification |

## Gates that cannot be gamed

- Hidden seeds are partitioned structurally (87M+) and sealed with SHA
  receipts before any training exists.
- Promotion requires: target success, Wilson lower bound, strict
  beats-baseline on hidden set, no protected regression beyond floors,
  checkpoint identity across exam/regression records, isolation receipt.
- LLM output is schema-validated and can only propose; every root cause is
  established from executed intervention outcomes by deterministic rules.

## Honest limitations

- Gemini live calls are configured and verified locally. Credentials remain
  environment-only and are not committed. The deterministic diagnostician is
  still the fail-closed fallback when a provider is unavailable.
- Cloud deployment is scripted and the desktop speaks to the same API, but the
  current verified run is local uvicorn + local CARLA/DriveMA; Cloud Run has
  not yet been claimed as deployed.
- Firestore is implemented as a metadata-only campaign/artifact index. Pub/Sub
  is not a runtime claim: the deadline path uses one Cloud Run Job per
  versioned GCS campaign workspace rather than an unverified queue layer.
- The CARLA corridor and scale are inferred from T5 camera evidence. Collision
  truth belongs to CARLA/OpenDRIVE, never Gaussian opacity. The Gaussian world
  still contains off-axis blur/fiberglass artifacts and is not metric,
  collision-validated, or autonomous-driving-ready.
