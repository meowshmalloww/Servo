# Servo authentication boundary

Servo has two deliberately separate authentication modes. Tokens and secrets
are runtime configuration; none are embedded in the executable or repository.

## Firebase mode (Cloud Run / production demo)

Set the API and desktop process environment:

```text
SERVO_AUTH_MODE=firebase
SERVO_FIREBASE_PROJECT_ID=your-firebase-project
SERVO_FIREBASE_API_KEY=your-firebase-web-api-key   # desktop only
SERVO_API_URL=https://your-servo-api.run.app      # desktop only
SERVO_FIREBASE_REQUIRED_CLAIM=servo_access        # optional
SERVO_FIREBASE_REQUIRE_VERIFIED_EMAIL=1
```

Cloud Run sets `K_SERVICE`; when `SERVO_AUTH_MODE` is absent, the API defaults
to Firebase mode and fails closed. The API never falls back to
`SERVO_API_TOKEN` while Firebase mode is selected. A missing project ID,
missing token, unavailable verification library, signature failure, wrong
audience/issuer, or expired token rejects the request.

The native login page uses Firebase Authentication's email/password REST
endpoint, keeps the refresh token only in process memory, and refreshes the
short-lived ID token before expiry. Before opening Servo, it calls
`GET /v1/auth/session`; only the API's verified, sanitized principal crosses
that boundary. The ID token is attached as `Authorization: Bearer ...` to
RealityCI and simulation requests. Signing out clears the in-memory tokens.

`SERVO_FIREBASE_REQUIRED_CLAIM` is an optional Boolean custom-claim gate. When
configured, an authenticated account is rejected unless that claim is exactly
`true`. This supports a restricted hackathon team without an email allowlist
in source.

Firebase's web API key is project configuration rather than an admin private
key, but Servo still receives it through environment configuration. Do not put
service-account JSON, refresh tokens, ID tokens, or Admin private keys in
`.env`, QML `Settings`, logs, or Git.

The server uses the official Firebase Admin SDK with revocation checking; it
verifies signature, expiry, issuer, project audience, and revoked sessions:

- [Firebase: Verify ID tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
- [Firebase Admin Python SDK](https://firebase.google.com/docs/reference/admin/python/firebase_admin.auth)

## Explicit local development mode

```text
SERVO_AUTH_MODE=local
SERVO_API_URL=http://127.0.0.1:8000
SERVO_API_TOKEN=a-random-local-token   # optional, recommended
```

With a local token set, both processes must receive the same value. An empty
token is permitted only in local mode for the offline development workflow.
Do not deploy an unauthenticated local-mode API publicly.

## Firebase console setup

1. Enable Firebase Authentication and the Email/Password provider.
2. Add only authorized hackathon users.
3. If using the claim gate, assign `servo_access: true` with trusted admin
   tooling and force users to refresh their ID token.
4. Configure Cloud Run with Firebase mode, project ID, and the optional claim.
5. Configure the desktop with the same project ID, web API key, and API URL.

Authentication identifies the operator. Deterministic promotion gates,
artifact provenance, and CARLA evidence validation remain separate controls.
