# Servo setup recall

Last updated: 2026-08-31

This file is the durable checklist for finishing Servo's Firebase and Google
Cloud connection. It intentionally contains no passwords, API keys, ID tokens,
refresh tokens, or service-account private keys.

## Current verified state

- Firebase project: `servo-1f808`
- Firebase Web App: `Servo`
- The Web App registration is correct for the native Qt desktop.
- The ignored local `.env` contains the Firebase project ID and Web API key.
- Servo already implements a native Firebase email/password login controller.
- The backend verifies Firebase ID tokens with the Firebase Admin SDK and
  revocation checking.
- Firestore campaign metadata indexing is implemented.
- Large campaign artifacts already have a versioned Cloud Storage path.
- Generic world/model/checkpoint publishing is implemented in
  `cloud/infra/publish-artifact.ps1`.
- Local RealityCI verification: 194 passed, 1 skipped.
- Cloud Run, Firestore, and Cloud Storage have not yet been deployed from this
  machine because Google Cloud CLI is not installed.

## What to select on Firebase's Add SDK page

Select **Config**.

Do not select npm or CDN for the Servo desktop:

- **npm** is for a JavaScript application using a bundler.
- **CDN** is for a browser page loading Firebase JavaScript with script tags.
- **Config** shows the public project identifiers needed by Servo's native Qt
  Firebase Authentication REST client.

The Web API key is project configuration, not a Firebase Admin private key.
Do not commit it, but do not create or download a service-account JSON file for
the desktop either.

## Firebase console checklist

### 1. Keep the existing Web App

Firebase console > Project settings > General > Your apps:

- Keep the existing `Servo` Web App.
- Do not register another app.
- Do not run `npm install firebase`.

### 2. Enable authentication

Firebase console > Build > Authentication:

1. Select **Get started** if shown.
2. Open **Sign-in method**.
3. Select **Email/Password**.
4. Enable **Email/Password**.
5. Leave passwordless email-link sign-in disabled for the hackathon.
6. Save.
7. Open **Users** and add the authorized Servo operator account.
8. Verify the account email before enabling Servo's production Firebase mode.

### 3. Create Firestore

Firebase console > Build > Firestore Database:

1. Select **Create database**.
2. Choose **Production mode**. Servo's browser/client does not write campaign
   records directly; Cloud Run uses IAM through its service account.
3. Use the same region planned for Cloud Run, currently `us-central1`.
4. Keep the database ID `(default)`.

Firestore stores only metadata and pointers:

- `servo_campaigns/<campaign-id>`
- `servo_artifacts/<artifact-id>`

Do not upload PLYs, ZIP bundles, checkpoints, videos, or textures into a
Firestore document.

### 4. Create object storage

Firebase console > Build > Storage:

1. Select **Get started**.
2. Upgrade to Blaze if Firebase requires it.
3. Choose `us-central1` when available so compute and storage remain colocated.
4. Start with restrictive/production rules.

The default bucket will be `servo-1f808.firebasestorage.app`. Servo may use
that bucket, but the recommended deployment creates a dedicated versioned
bucket named `servo-1f808-servo-artifacts` for server-owned CI/CD evidence.

Cloud Storage contains:

- Gaussian PLYs and world bundles
- Cameras, textures, environment maps, and validation videos
- Policy checkpoints and training receipts
- Campaign event logs and evidence bundles
- Hash manifests

Firestore contains the corresponding searchable record and `gs://` URI.

## Local versus cloud authentication

Keep Servo in local mode until the Cloud Run URL exists:

```text
SERVO_AUTH_MODE=local
SERVO_API_URL=http://127.0.0.1:8000
```

After a real Cloud Run deployment, switch the ignored `.env` to:

```text
SERVO_AUTH_MODE=firebase
SERVO_FIREBASE_PROJECT_ID=servo-1f808
SERVO_FIREBASE_API_KEY=YOUR_EXISTING_WEB_APP_API_KEY
SERVO_API_URL=https://YOUR_REAL_CLOUD_RUN_SERVICE.run.app
```

Never commit `.env`. Never store a Firebase Admin private key, refresh token,
ID token, password, or Google service-account JSON in the repository.

## Google Cloud deployment (next machine setup step)

Google Cloud CLI must be installed before these commands are available. Servo
will not install it automatically or claim deployment without a real Cloud Run
revision and execution receipt.

```powershell
gcloud auth login
gcloud auth application-default login

Set-Location D:\Servo
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\cloud\infra\deploy.ps1 `
  -ProjectId servo-1f808 `
  -FirebaseProjectId servo-1f808 `
  -Region us-central1
```

The script enables required APIs, creates service identities, creates or reuses
Firestore, creates a versioned artifact bucket, builds the Cloud Run API and
campaign Job, grants least-purpose IAM roles, and prints the real API URL.

## Publish a world after deployment

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\cloud\infra\publish-artifact.ps1 `
  -ProjectId servo-1f808 `
  -ArtifactBucket servo-1f808-servo-artifacts `
  -Kind world `
  -ArtifactId yosemite-t5-final-v2 `
  -Source "D:\path\to\published-world-bundle"
```

The publisher refuses accidental reuse of an artifact ID, computes file
SHA-256 values, uploads through resumable Cloud Storage commands, publishes a
manifest, and registers bounded metadata in Firestore.

## Honest completion boundary

Servo currently implements:

`reconstruct -> test -> diagnose -> create experience -> retrain -> hidden exam -> promote/reject -> publish artifact`

Publishing a promoted checkpoint to the cloud release channel is implemented.
Installing that checkpoint on a real physical vehicle is a separate,
target-specific safety/signing integration and is not claimed by the current
hackathon build.

## Continue from here

When resuming, read this file first, then:

1. Confirm Authentication Email/Password is enabled.
2. Confirm Firestore `(default)` exists in `us-central1`.
3. Confirm Storage is enabled or choose the dedicated deployment bucket.
4. Install/authenticate Google Cloud CLI only with user approval.
5. Run `cloud/infra/deploy.ps1`.
6. Record the Cloud Run URL and deployment receipt.
7. Switch `.env` to Firebase mode and test native sign-in.
8. Publish one T5 world and one candidate checkpoint.
9. Verify the Firestore records and GCS hashes.
