from __future__ import annotations

import json

from cloud.control_api.app.firestore_index import (
    campaign_index_payload,
    firestore_enabled,
    list_firestore_campaign_ids,
    upsert_campaign_index,
)


class _Snapshot:
    def __init__(self, document_id: str) -> None:
        self.id = document_id


class _Document:
    def __init__(self) -> None:
        self.value = None

    def set(self, value, *, merge):
        self.value = (value, merge)


class _Collection:
    def __init__(self) -> None:
        self.document_value = _Document()

    def document(self, _document_id):
        return self.document_value

    def stream(self):
        return [_Snapshot("cam-0123456789abcdef"), _Snapshot("not-a-campaign")]


class _Client:
    def __init__(self) -> None:
        self.collection_value = _Collection()

    def collection(self, _name):
        return self.collection_value


def test_campaign_index_is_small_metadata_with_gcs_pointer(tmp_path, monkeypatch) -> None:
    campaign_id = "cam-0123456789abcdef"
    root = tmp_path / campaign_id
    root.mkdir()
    (root / "campaign.json").write_text(
        json.dumps(
            {
                "objective": {"capability_taxonomy_id": "lane-following/v1"},
                "config": {
                    "diagnostician": "gemini",
                    "diagnostician_model": "gemini-3.7-flash",
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "state.json").write_text(
        json.dumps({"state": "training", "updated_at": "2026-08-31T00:00:00Z"}),
        encoding="utf-8",
    )
    # A large artifact beside the state must never be copied into Firestore.
    (root / "world.ply").write_bytes(b"x" * 2_000_000)
    monkeypatch.setenv("SERVO_GCS_BUCKET", "servo-artifacts")
    monkeypatch.setenv("SERVO_GCS_PREFIX", "campaigns")

    payload = campaign_index_payload(campaign_id, root)
    assert payload["artifact_prefix"] == (
        "gs://servo-artifacts/campaigns/cam-0123456789abcdef"
    )
    assert payload["diagnostician_model"] == "gemini-3.7-flash"
    assert "world.ply" not in json.dumps(payload)
    assert len(json.dumps(payload).encode("utf-8")) < 64 * 1024


def test_firestore_client_is_optional_and_campaign_ids_are_validated(monkeypatch) -> None:
    import cloud.control_api.app.firestore_index as index

    monkeypatch.delenv("SERVO_FIRESTORE_DATABASE", raising=False)
    assert firestore_enabled() is False
    upsert_campaign_index("cam-0123456789abcdef", None)  # type: ignore[arg-type]
    assert list_firestore_campaign_ids() == ()

    client = _Client()
    monkeypatch.setenv("SERVO_FIRESTORE_DATABASE", "(default)")
    monkeypatch.setattr(index, "_client", lambda: client)
    assert list_firestore_campaign_ids() == ("cam-0123456789abcdef",)
