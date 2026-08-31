from __future__ import annotations

from fastapi.testclient import TestClient

import cloud.control_api.app.main as api


def test_campaign_stages_baseline_and_dispatches_once(tmp_path, monkeypatch) -> None:
    campaign_root = tmp_path / "campaigns"
    baseline = tmp_path / "baseline.pt"
    baseline.write_bytes(b"sealed-test-checkpoint")
    monkeypatch.setattr(api, "WORKSPACE_ROOT", campaign_root)
    monkeypatch.setattr(api, "AUTH_MODE", "local")
    monkeypatch.setattr(api, "API_TOKEN", "")
    monkeypatch.setattr(
        api,
        "dispatch_campaign_job",
        lambda campaign_id: {
            "campaign_id": campaign_id,
            "state": "queued",
            "operation_name": "projects/p/locations/r/operations/op-1",
            "job_resource": "projects/p/locations/r/jobs/servo-campaign-job",
            "backend": "google-cloud-run-jobs/v2",
        },
    )
    client = TestClient(api.app)
    created = client.post(
        "/v1/campaigns",
        json={
            "baseline_checkpoint_uri": str(baseline),
            "diagnostician": "deterministic",
            "training_scenarios": 6,
        },
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["campaign_id"]
    assert (campaign_root / campaign_id / "baseline-checkpoint.pt").read_bytes() == baseline.read_bytes()

    dispatched = client.post(
        f"/v1/campaigns/{campaign_id}/dispatch",
        headers={"Idempotency-Key": "dispatch-once"},
    )
    assert dispatched.status_code == 202, dispatched.text
    assert dispatched.json()["state"] == "queued"
    assert (campaign_root / campaign_id / "cloud-dispatch.json").is_file()

    duplicate = client.post(f"/v1/campaigns/{campaign_id}/dispatch")
    assert duplicate.status_code == 409

    local_step = client.post(f"/v1/campaigns/{campaign_id}/step")
    assert local_step.status_code == 409
    assert "executing in Cloud Run" in local_step.json()["error"]["message"]


def test_ask_servo_can_dispatch_cloud_campaign(tmp_path, monkeypatch) -> None:
    campaign_root = tmp_path / "campaigns"
    baseline = tmp_path / "baseline.pt"
    baseline.write_bytes(b"sealed-test-checkpoint")
    monkeypatch.setattr(api, "WORKSPACE_ROOT", campaign_root)
    monkeypatch.setattr(api, "AUTH_MODE", "local")
    monkeypatch.setattr(api, "API_TOKEN", "")
    monkeypatch.setattr(
        api,
        "dispatch_campaign_job",
        lambda campaign_id: {
            "campaign_id": campaign_id,
            "state": "queued",
            "operation_name": "projects/p/locations/r/operations/op-2",
            "job_resource": "projects/p/locations/r/jobs/servo-campaign-job",
            "backend": "google-cloud-run-jobs/v2",
        },
    )
    client = TestClient(api.app)
    created = client.post(
        "/v1/campaigns",
        json={
            "baseline_checkpoint_uri": str(baseline),
            "diagnostician": "deterministic",
            "training_scenarios": 6,
        },
    )
    campaign_id = created.json()["campaign_id"]

    response = client.post(
        "/v1/ask/tools/dispatch_campaign",
        json={
            "campaign_id": campaign_id,
            "arguments": {},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["state"] == "queued"
    assert "Cloud Run" in response.json()["message"]


def test_cloud_readiness_does_not_claim_unverified_deployment(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, "WORKSPACE_ROOT", tmp_path / "campaigns")
    monkeypatch.setattr(api, "AUTH_MODE", "local")
    monkeypatch.setattr(api, "API_TOKEN", "")
    monkeypatch.delenv("K_SERVICE", raising=False)
    response = TestClient(api.app).get("/v1/cloud/readiness")
    assert response.status_code == 200
    assert response.json()["deployment_proven"] is False
    assert response.json()["verified_cloud_campaigns"] == 0
