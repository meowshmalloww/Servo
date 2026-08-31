"""Small Firestore index for RealityCI campaign metadata.

The durable campaign workspace and all large artifacts remain in Cloud Storage.
Firestore only stores queryable state, provenance, and GCS pointers so a cold
Cloud Run instance can discover campaigns without listing every object.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CAMPAIGN_ID = re.compile(r"cam-[0-9a-f]{16}")


def firestore_enabled() -> bool:
    return bool(os.environ.get("SERVO_FIRESTORE_DATABASE", "").strip())


def _client():
    if not firestore_enabled():
        return None
    try:
        from google.cloud import firestore
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "SERVO_FIRESTORE_DATABASE is set but google-cloud-firestore is not installed"
        ) from exc
    return firestore.Client(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
        database=os.environ["SERVO_FIRESTORE_DATABASE"],
    )


def _collection(client):
    name = os.environ.get("SERVO_FIRESTORE_COLLECTION", "servo_campaigns").strip()
    if not name or "/" in name:
        raise RuntimeError("SERVO_FIRESTORE_COLLECTION must be one collection name")
    return client.collection(name)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def campaign_index_payload(campaign_id: str, root: Path) -> dict[str, Any]:
    """Build a bounded metadata document; never include artifact bodies."""

    if not _CAMPAIGN_ID.fullmatch(campaign_id):
        raise ValueError("invalid campaign id")
    campaign = _read_json(root / "campaign.json")
    state = _read_json(root / "state.json")
    cloud = _read_json(root / "cloud-execution-receipt.json")
    prefix = os.environ.get("SERVO_GCS_PREFIX", "campaigns").strip("/")
    bucket = os.environ.get("SERVO_GCS_BUCKET", "").strip()
    objective = campaign.get("objective") if isinstance(campaign.get("objective"), dict) else {}
    config = campaign.get("config") if isinstance(campaign.get("config"), dict) else {}
    current_state = str(state.get("state") or cloud.get("terminal_state") or cloud.get("state") or "unknown")
    terminal = current_state in {"promoted", "rejected", "cancelled", "failed", "completed"}
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": "servo.firestore-campaign-index/v1",
        "campaign_id": campaign_id,
        "state": current_state,
        "terminal": terminal,
        "updated_at": str(state.get("updated_at") or cloud.get("updated_at") or now),
        "objective_capability": str(objective.get("capability_taxonomy_id", "")),
        "diagnostician": str(config.get("diagnostician", "")),
        "diagnostician_model": str(config.get("diagnostician_model", "")),
        "commit_sha": str(cloud.get("commit_sha") or os.environ.get("SERVO_COMMIT_SHA", "unknown")),
        "cloud_run_execution": str(cloud.get("cloud_run_execution", "")),
        "artifact_prefix": f"gs://{bucket}/{prefix}/{campaign_id}" if bucket else "",
        "storage_contract": "metadata-only; artifacts-in-gcs",
    }
    # Firestore is an index, never the authoritative evidence store.
    if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > 64 * 1024:
        raise RuntimeError("campaign index unexpectedly exceeds 64 KiB")
    return payload


def upsert_campaign_index(campaign_id: str, root: Path) -> None:
    client = _client()
    if client is None:
        return
    _collection(client).document(campaign_id).set(
        campaign_index_payload(campaign_id, root), merge=True
    )


def list_firestore_campaign_ids() -> tuple[str, ...]:
    client = _client()
    if client is None:
        return ()
    ids = {
        snapshot.id
        for snapshot in _collection(client).stream()
        if _CAMPAIGN_ID.fullmatch(snapshot.id)
    }
    return tuple(sorted(ids))
