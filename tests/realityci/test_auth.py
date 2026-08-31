from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloud.control_api.app.auth import (
    AuthenticationConfigurationError,
    AuthenticationRejectedError,
    configured_auth_mode,
    verify_authorization,
)


def test_cloud_run_defaults_to_firebase_and_desktop_defaults_to_local() -> None:
    assert configured_auth_mode({"K_SERVICE": "servo-api"}) == "firebase"
    assert configured_auth_mode({}) == "local"
    assert configured_auth_mode({"K_SERVICE": "servo-api", "SERVO_AUTH_MODE": "local"}) == "local"


def test_local_mode_preserves_optional_static_development_token() -> None:
    anonymous = verify_authorization(
        "", mode="local", local_token="", project_id=""
    )
    assert anonymous["subject"] == "local-developer"
    with pytest.raises(AuthenticationRejectedError):
        verify_authorization(
            "Bearer wrong", mode="local", local_token="secret", project_id=""
        )
    principal = verify_authorization(
        "Bearer secret", mode="local", local_token="secret", project_id=""
    )
    assert principal["mode"] == "local"


def test_firebase_mode_fails_closed_without_project_or_token() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        verify_authorization(
            "Bearer token", mode="firebase", local_token="secret", project_id=""
        )
    with pytest.raises(AuthenticationRejectedError):
        verify_authorization(
            "", mode="firebase", local_token="secret", project_id="servo-project"
        )


def test_firebase_mode_verifies_project_identity_and_required_claim() -> None:
    calls = []

    def verifier(token: str, project_id: str) -> dict:
        calls.append((token, project_id))
        return {
            "sub": "firebase-user-1",
            "email": "driver@example.com",
            "email_verified": True,
            "name": "Servo Driver",
            "servo_access": True,
        }

    principal = verify_authorization(
        "Bearer signed-id-token",
        mode="firebase",
        local_token="ignored-local-token",
        project_id="servo-project",
        required_claim="servo_access",
        firebase_verifier=verifier,
    )
    assert calls == [("signed-id-token", "servo-project")]
    assert principal == {
        "mode": "firebase",
        "subject": "firebase-user-1",
        "email": "driver@example.com",
        "display_name": "Servo Driver",
    }


def test_firebase_mode_rejects_unverified_email_and_missing_claim() -> None:
    with pytest.raises(AuthenticationRejectedError):
        verify_authorization(
            "Bearer token",
            mode="firebase",
            local_token="",
            project_id="servo-project",
            firebase_verifier=lambda *_: {
                "sub": "u1", "email": "user@example.com", "email_verified": False
            },
        )
    with pytest.raises(AuthenticationRejectedError):
        verify_authorization(
            "Bearer token",
            mode="firebase",
            local_token="",
            project_id="servo-project",
            firebase_verifier=lambda *_: {"sub": "u1"},
        )
    with pytest.raises(AuthenticationRejectedError):
        verify_authorization(
            "Bearer token",
            mode="firebase",
            local_token="",
            project_id="servo-project",
            required_claim="servo_access",
            firebase_verifier=lambda *_: {
                "sub": "u1", "email": "user@example.com", "email_verified": True
            },
        )


def test_authenticated_session_exposes_only_sanitized_principal(monkeypatch) -> None:
    import cloud.control_api.app.main as api

    expected = {
        "mode": "firebase",
        "subject": "u1",
        "email": "driver@example.com",
        "display_name": "Driver",
    }
    monkeypatch.setattr(api, "AUTH_MODE", "firebase")
    monkeypatch.setattr(api, "verify_authorization", lambda *args, **kwargs: expected)
    response = TestClient(api.app).get(
        "/v1/auth/session",
        headers={"Authorization": "Bearer verified-id-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "principal": expected}
