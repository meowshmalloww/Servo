"""Authentication boundary for Servo's local and Firebase deployments.

Local development and cloud identity are deliberately separate modes.  A
Firebase deployment never falls back to the local shared token when token
verification is unavailable or misconfigured.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from typing import Any


class AuthenticationConfigurationError(RuntimeError):
    """The selected authentication mode cannot safely verify requests."""


class AuthenticationRejectedError(RuntimeError):
    """The supplied credential is missing, invalid, or unauthorized."""


def configured_auth_mode(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    explicit = values.get("SERVO_AUTH_MODE", "").strip().lower()
    if explicit:
        return explicit
    # Cloud Run sets K_SERVICE.  Defaulting that environment to Firebase keeps
    # a forgotten configuration variable from silently exposing the API.
    return "firebase" if values.get("K_SERVICE", "").strip() else "local"


def firebase_project_id(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    return (
        values.get("SERVO_FIREBASE_PROJECT_ID", "").strip()
        or values.get("GOOGLE_CLOUD_PROJECT", "").strip()
    )


def _bearer(authorization: str) -> str:
    scheme, separator, token = authorization.strip().partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationRejectedError("missing Firebase bearer token")
    return token.strip()


def verify_firebase_id_token(token: str, project_id: str) -> dict[str, Any]:
    """Verify signature, expiry, revocation, issuer and audience with Firebase Admin."""

    try:
        import firebase_admin
        from firebase_admin import auth
    except ImportError as exc:  # fail closed; never decode an unsigned JWT
        raise AuthenticationConfigurationError(
            "Firebase verification requires firebase-admin"
        ) from exc

    try:
        app_name = f"servo-{project_id}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(
                options={"projectId": project_id},
                name=app_name,
            )
        claims = auth.verify_id_token(token, app=app, check_revoked=True)
    except Exception as exc:
        raise AuthenticationRejectedError("invalid or expired Firebase ID token") from exc
    if not isinstance(claims, dict):
        raise AuthenticationRejectedError("invalid Firebase ID token claims")
    return claims


def verify_authorization(
    authorization: str,
    *,
    mode: str,
    local_token: str,
    project_id: str,
    required_claim: str = "",
    require_verified_email: bool = True,
    firebase_verifier: Callable[[str, str], dict[str, Any]] = verify_firebase_id_token,
) -> dict[str, Any]:
    """Return a sanitized principal or raise a fail-closed auth exception."""

    normalized_mode = mode.strip().lower()
    if normalized_mode == "local":
        if local_token:
            supplied = _bearer(authorization)
            if not secrets.compare_digest(supplied, local_token):
                raise AuthenticationRejectedError("invalid local development bearer token")
        return {
            "mode": "local",
            "subject": "local-developer",
            "email": "",
            "display_name": "Local developer",
        }

    if normalized_mode != "firebase":
        raise AuthenticationConfigurationError(
            "SERVO_AUTH_MODE must be 'local' or 'firebase'"
        )
    if not project_id:
        raise AuthenticationConfigurationError(
            "SERVO_FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required"
        )

    claims = firebase_verifier(_bearer(authorization), project_id)
    subject = str(claims.get("sub") or claims.get("user_id") or "").strip()
    if not subject:
        raise AuthenticationRejectedError("Firebase token has no user subject")
    email = str(claims.get("email") or "").strip()
    if require_verified_email and (not email or claims.get("email_verified") is not True):
        raise AuthenticationRejectedError("Firebase email address is not verified")
    claim_name = required_claim.strip()
    if claim_name and claims.get(claim_name) is not True:
        raise AuthenticationRejectedError(
            f"Firebase token is missing required claim '{claim_name}'"
        )
    return {
        "mode": "firebase",
        "subject": subject,
        "email": email,
        "display_name": str(claims.get("name") or "").strip(),
    }
