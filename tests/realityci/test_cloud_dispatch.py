from __future__ import annotations

import pytest

from cloud.control_api.app.cloud_dispatch import (
    CloudCampaignJobConfig,
    run_job_request,
)


def test_cloud_campaign_configuration_fails_closed(monkeypatch) -> None:
    for name in (
        "GOOGLE_CLOUD_PROJECT",
        "SERVO_GCP_REGION",
        "SERVO_CAMPAIGN_JOB",
        "SERVO_GCS_BUCKET",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        CloudCampaignJobConfig.from_environment()


def test_cloud_run_job_override_is_explicit_and_bounded() -> None:
    config = CloudCampaignJobConfig(
        project_id="servo-project",
        region="us-central1",
        job_name="servo-campaign-job",
        bucket="servo-artifacts",
        prefix="campaigns",
        commit_sha="abc123",
    )
    payload = run_job_request(config, "cam-0123456789abcdef")
    overrides = payload["overrides"]
    assert overrides["taskCount"] == 1
    assert overrides["timeout"] == "3600s"
    env = {item["name"]: item["value"] for item in overrides["containerOverrides"][0]["env"]}
    assert env["SERVO_CAMPAIGN_ID"] == "cam-0123456789abcdef"
    assert env["SERVO_GCS_BUCKET"] == "servo-artifacts"
    assert env["SERVO_COMMIT_SHA"] == "abc123"
