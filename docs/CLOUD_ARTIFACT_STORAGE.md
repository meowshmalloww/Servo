# Cloud storage for Servo worlds and models

Servo uses three different Google services for three different jobs:

- **Firebase Authentication** identifies the operator and supplies a short-lived ID token.
- **Cloud Storage** stores large immutable bytes: Gaussian PLYs, world bundles, camera files, model checkpoints, datasets, videos, and evidence.
- **Cloud Firestore** stores small searchable records: artifact ID, kind, byte count, hash, state, provenance, and the `gs://` pointer.

Do not store a PLY, checkpoint, texture archive, or video inside a Firestore document. Firestore is the catalog, not the object store.

## Firebase console setup

Registering **Servo** as a Firebase Web App is correct. The desktop is native Qt, but its login controller uses Firebase Authentication's REST API, for which the Web App API key and project ID are the correct public configuration. Servo does not embed the Firebase JavaScript SDK, so `npm install firebase` is neither required nor used.

1. In **Firebase console > Authentication > Sign-in method**, enable **Email/Password**.
2. In **Authentication > Users**, create the hackathon operator account and verify its email.
3. Upgrade to the Blaze plan before enabling Firebase Storage, if Firebase requests it.
4. Keep the web API key and project ID in the ignored local `.env`; never place an Admin SDK private key there.

The native desktop configuration is documented in [AUTHENTICATION.md](AUTHENTICATION.md).

## Deploy the authenticated control plane

After installing and authenticating the Google Cloud CLI:

```powershell
gcloud auth login
gcloud auth application-default login

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\cloud\infra\deploy.ps1 `
  -ProjectId servo-1f808 `
  -FirebaseProjectId servo-1f808 `
  -Region us-central1
```

The deployment creates a dedicated versioned bucket named
`servo-1f808-servo-artifacts` unless `-ArtifactBucket` is supplied. A dedicated
bucket is preferred over the Firebase default bucket because server-side
campaign artifacts use IAM and lifecycle/versioning rules rather than browser
Firebase Storage Rules.

After deployment, add the returned API URL to the ignored `.env` and switch modes:

```text
SERVO_AUTH_MODE=firebase
SERVO_FIREBASE_PROJECT_ID=servo-1f808
SERVO_FIREBASE_API_KEY=YOUR_WEB_APP_API_KEY
SERVO_API_URL=https://YOUR_SERVICE.run.app
```

Restart Servo and sign in. Do not enable Firebase mode against the local API;
the local server intentionally uses the separate local-development boundary.

## Publish a world or model

The publisher computes a SHA-256 manifest, performs a resumable Cloud Storage
upload through `gcloud storage`, and registers bounded metadata in Firestore:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\cloud\infra\publish-artifact.ps1 `
  -ProjectId servo-1f808 `
  -ArtifactBucket servo-1f808-servo-artifacts `
  -Kind world `
  -ArtifactId yosemite-t5-final-v2 `
  -Source "D:\path\to\the\published-world-bundle"
```

For a policy checkpoint, use `-Kind model` or `-Kind checkpoint`. Objects are
written beneath:

```text
gs://servo-1f808-servo-artifacts/artifacts/<kind>/<artifact-id>/payload/
gs://servo-1f808-servo-artifacts/artifacts/<kind>/<artifact-id>/manifest.json
```

Firestore receives `servo_artifacts/<artifact-id>` with the GCS URI, manifest
hash, type, file count, total bytes, and update time. Campaign workspaces are
already mirrored independently under `gs://.../campaigns/<campaign-id>/` and
indexed in `servo_campaigns`.

Publishing an artifact makes it durable and discoverable. It does not turn a
nonmetric Gaussian world into collision geometry and it does not deploy a
policy to a physical vehicle. Servo's deterministic promotion gate deploys a
verified candidate to the artifact release channel; physical-device rollout
requires a separate target-specific safety and signing integration.
