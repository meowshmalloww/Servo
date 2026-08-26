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
        json={"baseline_checkpoint_uri": str(baseline), "training_scenarios": 6},
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
