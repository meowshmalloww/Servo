# Servo — RealityCI submission overview (backend build)

> Status: **complete local agentic loop, verified**. Cloud deployment and the
> desktop client wiring are prepared but require external credentials / UI
> work as noted at the end.

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
& $py -m pytest tests\realityci -q                       # 79+ tests
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
| Vertex AI / Gemini | structured causal hypotheses + experiment selection via `diagnosis/gemini.py` |
| Google ADK | durable graph execution of the campaign (`adk_graph.py`) |
| Cloud Run | control API (`cloud/control_api`) + training/exam job containers |
| Firestore / Pub/Sub / GCS | state, ordered events, artifacts (interfaces implemented locally; cloud clients in cloud requirements) |

## Gates that cannot be gamed

- Hidden seeds are partitioned structurally (87M+) and sealed with SHA
  receipts before any training exists.
- Promotion requires: target success, Wilson lower bound, strict
  beats-baseline on hidden set, no protected regression beyond floors,
  checkpoint identity across exam/regression records, isolation receipt.
- LLM output is schema-validated and can only propose; every root cause is
  established from executed intervention outcomes by deterministic rules.

## Honest limitations

- Gemini live calls need `GEMINI_API_KEY` on this machine; until then the
  deterministic diagnostician runs so nothing is faked. The code path is
  complete and gated (`--diagnostician gemini`, or `auto` which upgrades
  itself when a key exists).
- Cloud deployment is scripted (`cloud/infra/deploy.ps1`) and the desktop
  client speaks to the same API, but a GCP project/credentials are required
  to execute it; locally the identical FastAPI service runs via uvicorn.
- Firestore/Pub/Sub are not wired yet: durable state is the sealed campaign
  workspace, mirrored to GCS when `SERVO_GCS_BUCKET` is set.
- Scenario world is a straight-road virtual scene with procedural or
  observed-frame backgrounds; collision truth is deterministic scenario
  state, never Gaussian geometry. No metric-scale or safety claims.
