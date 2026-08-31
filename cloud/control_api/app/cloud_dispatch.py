"""Authenticated Cloud Run Job dispatch for background ADK campaigns."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CloudCampaignJobConfig:
    project_id: str
    region: str
    job_name: str
    bucket: str
    prefix: str
    commit_sha: str

    @classmethod
    def from_environment(cls) -> "CloudCampaignJobConfig":
        values = {
            "project_id": os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip(),
            "region": os.environ.get("SERVO_GCP_REGION", "").strip(),
            "job_name": os.environ.get("SERVO_CAMPAIGN_JOB", "").strip(),
            "bucket": os.environ.get("SERVO_GCS_BUCKET", "").strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError(
                "cloud campaign dispatch is not configured: " + ", ".join(missing)
            )
        return cls(
            **values,
            prefix=os.environ.get("SERVO_GCS_PREFIX", "campaigns").strip("/"),
            commit_sha=os.environ.get("SERVO_COMMIT_SHA", "unknown").strip() or "unknown",
        )


def run_job_request(config: CloudCampaignJobConfig, campaign_id: str) -> dict[str, Any]:
    env = {
        "SERVO_CAMPAIGN_ID": campaign_id,
        "SERVO_GCS_BUCKET": config.bucket,
        "SERVO_GCS_PREFIX": config.prefix,
        "SERVO_COMMIT_SHA": config.commit_sha,
        "GOOGLE_CLOUD_PROJECT": config.project_id,
        "GOOGLE_CLOUD_LOCATION": config.region,
    }
    return {
        "overrides": {
            "containerOverrides": [
                {"env": [{"name": name, "value": value} for name, value in sorted(env.items())]}
            ],
            "taskCount": 1,
            "timeout": "3600s",
        }
    }


def dispatch_campaign_job(campaign_id: str) -> dict[str, Any]:
    config = CloudCampaignJobConfig.from_environment()
    try:
        import google.auth
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError("google-auth is required for Cloud Run Job dispatch") from exc

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    resource = (
        f"projects/{config.project_id}/locations/{config.region}/jobs/{config.job_name}"
    )
    url = f"https://run.googleapis.com/v2/{resource}:run"
    request = urllib.request.Request(
        url,
        data=json.dumps(run_job_request(config, campaign_id)).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
            "X-Servo-Campaign-ID": campaign_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Cloud Run Job dispatch failed ({exc.code}): {detail}") from exc
    if not isinstance(payload, dict) or not str(payload.get("name", "")).strip():
        raise RuntimeError("Cloud Run Jobs API returned no operation name")
    return {
        "campaign_id": campaign_id,
        "state": "queued",
        "operation_name": payload["name"],
        "job_resource": resource,
        "backend": "google-cloud-run-jobs/v2",
    }
