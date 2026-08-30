from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from cloud.control_api.app.main import app


def test_healthz_open() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_campaign_flow_over_http(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    baseline = Path(__file__).resolve().parents[1] / ".." / "demo" / "occluded_pedestrian" / "baseline" / "baseline.pt"
    if not baseline.exists():
        pytest.skip("trained baseline checkpoint not present")

    import os

    monkeypatch.setattr(
        "cloud.control_api.app.main.WORKSPACE_ROOT", tmp_path / "campaigns"
    )
    client = TestClient(app)

    created = client.post(
        "/v1/campaigns",
        json={"baseline_checkpoint_uri": str(baseline), "training_scenarios": 6,
              "diagnostician": "deterministic"},
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["campaign_id"]
    state = created.json()["state"]

    for _ in range(40):
        response = client.post(f"/v1/campaigns/{campaign_id}/step")
        assert response.status_code == 200, response.text
        if response.json()["terminal"]:
            break
    final = client.get(f"/v1/campaigns/{campaign_id}/state").json()
    assert final["terminal"] is True

    events = client.get(f"/v1/campaigns/{campaign_id}/events?after_sequence=0").json()
    assert len(events["events"]) >= 10
    sequences = [e["sequence"] for e in events["events"]]
    assert sequences == sorted(sequences)

    partial = client.get(f"/v1/campaigns/{campaign_id}/events?after_sequence={sequences[2]}").json()
    assert all(e["sequence"] > sequences[2] for e in partial["events"])


def test_unknown_campaign_returns_404() -> None:
    client = TestClient(app)
    response = client.get("/v1/campaigns/does-not-exist/state")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.headers["X-Request-ID"].startswith("req-")


def test_campaign_rejects_unknown_capability_before_persisting(tmp_path, monkeypatch) -> None:
    baseline = _baseline_path()
    if not baseline.exists():
        pytest.skip("trained baseline checkpoint not present")
    campaign_root = tmp_path / "campaigns"
    monkeypatch.setattr("cloud.control_api.app.main.WORKSPACE_ROOT", campaign_root)
    response = TestClient(app).post(
        "/v1/campaigns",
        json={
            "baseline_checkpoint_uri": str(baseline),
            "objective_capability": "not-registered/v1",
            "diagnostician": "deterministic",
        },
    )
    assert response.status_code == 400
    assert "unsupported objective capability" in response.json()["error"]["message"]
    assert not campaign_root.exists() or not any(campaign_root.iterdir())


def _baseline_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / ".." / "demo" / "occluded_pedestrian" / "baseline" / "baseline.pt"


def test_lifecycle_listing_idempotency_cancel_and_artifacts(tmp_path, monkeypatch) -> None:
    baseline = _baseline_path()
    if not baseline.exists():
        pytest.skip("trained baseline checkpoint not present")
    monkeypatch.setattr("cloud.control_api.app.main.WORKSPACE_ROOT", tmp_path / "campaigns")
    client = TestClient(app)

    body = {"baseline_checkpoint_uri": str(baseline), "diagnostician": "deterministic"}
    first = client.post("/v1/campaigns", json=body, headers={"Idempotency-Key": "create-one"})
    replay = client.post("/v1/campaigns", json=body, headers={"Idempotency-Key": "create-one"})
    assert first.status_code == 200
    assert replay.json() == first.json()
    campaign_id = first.json()["campaign_id"]

    conflict = client.post(
        "/v1/campaigns",
        json={**body, "training_epochs": 2},
        headers={"Idempotency-Key": "create-one"},
    )
    assert conflict.status_code == 409

    listing = client.get("/v1/campaigns").json()["campaigns"]
    assert [item["campaign_id"] for item in listing] == [campaign_id]
    assert listing[0]["resumable"] is True

    stepped = client.post(f"/v1/campaigns/{campaign_id}/step")
    assert stepped.status_code == 200
    # A fresh client reconstructs the engine from disk, proving API-process
    # restart does not lose the durable state.
    resumed = TestClient(app).get(f"/v1/campaigns/{campaign_id}/state").json()
    assert resumed["state"] == stepped.json()["state"]

    cancelled = client.post(
        f"/v1/campaigns/{campaign_id}/cancel",
        json={"reason": "test cancellation"},
        headers={"Idempotency-Key": "cancel-one"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    cancelled_again = client.post(
        f"/v1/campaigns/{campaign_id}/cancel",
        json={"reason": "test cancellation"},
        headers={"Idempotency-Key": "cancel-one"},
    )
    assert cancelled_again.json() == cancelled.json()

    artifacts = client.get(f"/v1/campaigns/{campaign_id}/artifacts").json()["artifacts"]
    campaign_record = next(item for item in artifacts if item["path"] == "campaign.json")
    downloaded = client.get(campaign_record["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.json()["campaign_id"] == campaign_id


def test_run_endpoint_executes_through_local_adk(tmp_path, monkeypatch) -> None:
    pytest.importorskip("google.adk")
    baseline = _baseline_path()
    if not baseline.exists():
        pytest.skip("trained baseline checkpoint not present")
    monkeypatch.setattr("cloud.control_api.app.main.WORKSPACE_ROOT", tmp_path / "campaigns")
    client = TestClient(app)
    created = client.post(
        "/v1/campaigns",
        json={
            "baseline_checkpoint_uri": str(baseline),
            "diagnostician": "deterministic",
            "training_scenarios": 6,
            "hidden_exam_size": 4,
            "protected_suite_size": 3,
            "training_epochs": 2,
        },
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["campaign_id"]

    completed = client.post(f"/v1/campaigns/{campaign_id}/run")
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["terminal"] is True
    assert result["orchestrator"].startswith("google-adk/")
    assert result["adk_event_count"] >= 12
    assert result["adk_session_id"].startswith("servo-")


def test_authentication_and_assistant_tool_catalog(tmp_path, monkeypatch) -> None:
    import cloud.control_api.app.main as api

    monkeypatch.setattr(api, "WORKSPACE_ROOT", tmp_path / "campaigns")
    monkeypatch.setattr(api, "API_TOKEN", "secret-token")
    client = TestClient(app)
    denied = client.get("/v1/campaigns")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"
    allowed = client.get(
        "/v1/assistant/tools", headers={"Authorization": "Bearer secret-token"}
    )
    assert allowed.status_code == 200
    names = {item["name"] for item in allowed.json()["tools"]}
    assert {
        "create_campaign",
        "start_campaign",
        "run_counterfactuals",
        "start_training",
        "run_hidden_exam",
        "cancel_campaign",
    }.issubset(names)


def test_explicit_assistant_tools_obey_workflow_gates(tmp_path, monkeypatch) -> None:
    baseline = _baseline_path()
    if not baseline.exists():
        pytest.skip("trained baseline checkpoint not present")
    monkeypatch.setattr("cloud.control_api.app.main.WORKSPACE_ROOT", tmp_path / "campaigns")
    client = TestClient(app)
    created = client.post(
        "/v1/assistant/tools/create_campaign",
        json={
            "arguments": {
                "baseline_checkpoint_uri": str(baseline),
                "diagnostician": "deterministic",
                "training_scenarios": 6,
                "training_epochs": 2,
            }
        },
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["result"]["campaign_id"]

    started = client.post(
        "/v1/assistant/tools/start_campaign", json={"campaign_id": campaign_id}
    )
    assert started.json()["result"]["state"] == "failure_triage"
    failure = client.post(
        "/v1/assistant/tools/explain_failure", json={"campaign_id": campaign_id}
    )
    assert failure.json()["result"]["event_type"] == "FAILURE_DETECTED"

    experiments = client.post(
        "/v1/assistant/tools/run_counterfactuals", json={"campaign_id": campaign_id}
    )
    assert experiments.json()["result"]["state"] == "curriculum_planning"
    training = client.post(
        "/v1/assistant/tools/start_training", json={"campaign_id": campaign_id}
    )
    assert training.json()["result"]["state"] == "hidden_exam"
    verified = client.post(
        "/v1/assistant/tools/run_hidden_exam", json={"campaign_id": campaign_id}
    )
    assert verified.json()["result"]["terminal"] is True

    comparison = client.post(
        "/v1/assistant/tools/show_checkpoint_comparison",
        json={"campaign_id": campaign_id},
    )
    types = {item["event_type"] for item in comparison.json()["result"]["records"]}
    assert "CHECKPOINT_READY" in types
    assert "HIDDEN_EXAM_COMPLETED" in types
    assert {"CHECKPOINT_PROMOTED", "CHECKPOINT_REJECTED"} & types


def test_ask_servo_weather_is_explicitly_inferred_and_adjustable(tmp_path, monkeypatch) -> None:
    import cloud.control_api.app.main as api

    monkeypatch.setattr(api, "SIMULATION_ROOT", tmp_path / "simulations")
    response = TestClient(app).post(
        "/v1/ask/tools/set_weather",
        json={
            "arguments": {
                "weather": "snow",
                "engine": "servo-inferred-surface",
                "snow_accumulation": 0.65,
            }
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["engine"] == "servo-inferred-surface"
    assert result["snow_accumulation"] == 0.65
    assert result["climatenerf_qualified"] is False
    assert result["metric_surface"] is False
    assert "65% accumulation" in response.json()["message"]


def test_ask_servo_unwired_tools_fail_closed(tmp_path, monkeypatch) -> None:
    import cloud.control_api.app.main as api

    monkeypatch.setattr(api, "SIMULATION_ROOT", tmp_path / "simulations")
    response = TestClient(app).post(
        "/v1/ask/tools/rename_world",
        json={"arguments": {"world_id": "example", "name": "renamed"}},
    )
    assert response.status_code == 501
    assert "not wired" in response.json()["error"]["message"]


def test_world_execution_candidates_prefer_camera_height_v2(tmp_path) -> None:
    import cloud.control_api.app.main as api

    world = tmp_path / "world"
    v1 = world / "execution" / "carla-v1" / "execution-manifest.json"
    v2 = world / "execution" / "carla-v2-camera-height" / "execution-manifest.json"
    v1.parent.mkdir(parents=True)
    v2.parent.mkdir(parents=True)
    v1.write_text("{}", encoding="utf-8")
    v2.write_text("{}", encoding="utf-8")
    assert api._world_execution_candidates(world)[:2] == [v2.resolve(), v1.resolve()]


def test_ask_servo_vehicle_summary_reports_policy_weather_and_physics() -> None:
    import cloud.control_api.app.main as api
    from tools.realityci.ask_servo.tools import AskToolName

    message = api._ask_result_message(
        AskToolName.GET_VEHICLE_METRICS,
        {
            "simulation_id": "sim-0123456789abcdef",
            "state": "completed",
            "evidence": {
                "metrics": {
                    "route_completion": 0.992,
                    "collision_count": 0,
                    "max_lateral_error_m": 0.472,
                },
                "policy": {"name": "Local DriveMA-2B"},
                "weather": "snow",
                "weather_receipt": {"physics": {"snow_accumulation": 0.9}},
            },
            "physics_evidence": {
                "gravity_reference_mps2": 9.81,
                "imu_initial_acceleration_norm_p50_mps2": 9.77,
                "ground_contact_pass": True,
            },
        },
    )

    assert "Local DriveMA-2B" in message
    assert "Snow accumulation: 90%" in message
    assert "9.81 m/s² reference" in message
    assert "ground-contact pass=true" in message
