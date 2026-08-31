# Servo Google Cloud deployment

This is the reproducible hackathon deployment for Servo's agentic RealityCI
loop. It does not move the Windows CARLA simulator or GPU Gaussian
reconstruction into Cloud Run.

## Deployed path

```text
Firebase login
  -> Firebase ID token
  -> Cloud Run FastAPI control plane (token verified on every /v1 request)
  -> Cloud Run Jobs v2 dispatch
  -> Google ADK 2.7.1 campaign graph
  -> Gemini 3.7 Flash on Vertex AI
  -> Firestore queryable campaign state + GCS sealed evidence and checkpoints
  -> desktop polls the same authenticated API
```

Google Cloud components actually wired by this tree:

- Cloud Run service: authenticated application control plane.
- Cloud Run Job: one asynchronous ADK campaign per execution.
- Vertex AI: ADC/service-account Gemini transport for diagnosis and tool choice.
- Cloud Storage: versioned campaign workspaces and durable evidence.
- Firestore: small queryable campaign-state, execution, provenance, and GCS
  pointer documents. It never stores Gaussian PLYs, video, or checkpoints.
- Firebase Authentication: end-user identity; the backend verifies the Firebase
  ID token and never decodes an unsigned token.
- Cloud Build and Artifact Registry: reproducible images.
- Cloud Logging: structured stdout/stderr and Cloud Run execution logs.

Pub/Sub is deliberately not claimed by the current runtime. Firestore is a
metadata index; Cloud Storage remains the authoritative large-artifact and
evidence store.

## Why Cloud Run ingress is public

Firebase end-user authentication happens at the application boundary. Cloud
Run therefore permits the HTTPS request to reach FastAPI, but every `/v1`
endpoint verifies the Firebase ID token's signature, expiry, issuer and
audience. `/healthz` is the only open health endpoint. A missing or invalid
token fails closed.

## Deploy

Prerequisites are an authenticated `gcloud` CLI, a Google Cloud project with
billing, and Firebase Authentication enabled for the same project. Nothing in
this script installs Docker locally; Cloud Build builds the images remotely.

```powershell
Set-Location D:\Servo
gcloud auth login
gcloud auth application-default login

.\cloud\infra\deploy.ps1 `
  -ProjectId YOUR_PROJECT `
  -Region us-central1 `
  -FirebaseProjectId YOUR_FIREBASE_PROJECT
```

The script creates dedicated API/job service accounts, a Firestore Native-mode
metadata database, versioned GCS storage, least-privilege Firestore/bucket/job
permissions, the API revision and the campaign Job.
It prints the `.run.app` URL that must be recorded in the demo.

## Start a real cloud campaign

Upload the small RealityCI baseline once:

```powershell
gcloud storage cp `
  .\demo\occluded_pedestrian\baseline\baseline.pt `
  gs://YOUR_PROJECT-servo-artifacts/inputs/occluded-pedestrian-baseline.pt
```

After signing in, create a campaign with:

```json
{
  "baseline_checkpoint_uri": "gs://YOUR_PROJECT-servo-artifacts/inputs/occluded-pedestrian-baseline.pt",
  "diagnostician": "gemini",
  "diagnostician_model": "gemini-3.7-flash",
  "training_scenarios": 24,
  "hidden_exam_size": 8,
  "protected_suite_size": 4,
  "training_epochs": 10
}
```

Then call `POST /v1/campaigns/{campaign_id}/dispatch` with an
`Idempotency-Key`. The API returns HTTP 202 plus the Cloud Run long-running
operation name. The Job downloads the sealed workspace, executes the real ADK
graph, and uploads `cloud-execution-receipt.json` and all campaign artifacts.
The endpoint rejects a second active dispatch.

The same bounded operation is available through Servo AI Assistant. With the campaign
selected, use: `Run this campaign in the Google Cloud background`. The agent
may select `dispatch_campaign`; deterministic API code still validates the
campaign, staged checkpoint, deployment configuration, identity, and duplicate
execution state before Cloud Run receives anything.

## Required proof before claiming cloud completion

- Cloud Run service URL and revision.
- Cloud Build ID and image digest for the same Git commit.
- One Cloud Run Job execution ID.
- Vertex/Gemini model ID in logs.
- ADK node trace and ordered campaign events.
- GCS `cloud-execution-receipt.json` content hash.
- Firestore `servo_campaigns/{campaign_id}` metadata document pointing at the
  same GCS prefix.
- Desktop/API view of the same terminal decision.

Without these receipts, the code is deployment-ready but the deployment is not
verified. CARLA evidence remains local and must never be described as a Cloud
Run execution.
