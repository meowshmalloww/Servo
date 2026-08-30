"""Detached Climate job records with measured progress and reattachment."""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .source_receipt import canonical_json


JOB_SCHEMA = "servo.climate-job/v1"
EVENT_SCHEMA = "servo.climate-event/v1"
RESULT_SCHEMA = "servo.climate-result/v1"
STATES = (
    "pending", "preflighting", "preparing_dataset", "training_scene",
    "validating_scene", "stylizing", "preparing_flood", "preparing_snow",
    "rendering", "validating_weather", "baking_native_assets", "publishing",
    "completed", "failed", "cancelled",
)
TERMINAL = {"completed", "failed", "cancelled"}
TRANSITIONS = {
    "pending": {"preflighting", "cancelled"},
    "preflighting": {"preparing_dataset", "failed", "cancelled"},
    "preparing_dataset": {"training_scene", "failed", "cancelled"},
    "training_scene": {"validating_scene", "failed", "cancelled"},
    "validating_scene": {"stylizing", "preparing_flood", "preparing_snow", "rendering", "failed", "cancelled"},
    "stylizing": {"preparing_flood", "preparing_snow", "rendering", "failed", "cancelled"},
    "preparing_flood": {"rendering", "failed", "cancelled"},
    "preparing_snow": {"rendering", "failed", "cancelled"},
    "rendering": {"validating_weather", "failed", "cancelled"},
    "validating_weather": {"baking_native_assets", "publishing", "failed", "cancelled"},
    "baking_native_assets": {"publishing", "failed", "cancelled"},
    "publishing": {"completed", "failed", "cancelled"},
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    os.replace(temporary, path)


class ClimateJob:
    def __init__(self, root: Path, job_id: str) -> None:
        self.root = root.resolve()
        self.job_id = job_id
        self.manifest_path = self.root / "job.json"
        self.events_path = self.root / "events.jsonl"
        self.cancel_path = self.root / "cancel.requested"

    @classmethod
    def create(cls, root: Path, manifest: dict[str, Any]) -> "ClimateJob":
        if root.exists():
            raise ValueError("job directory already exists")
        job_id = manifest.get("job_id") or str(uuid.uuid4())
        job = cls(root, job_id)
        value = dict(manifest, schema_name=JOB_SCHEMA, job_id=job_id, state="pending",
                     created_at=utc_now(), completed_units=0, total_units=None)
        atomic_json(job.manifest_path, value)
        job.append_event("created", state="pending", completed_units=0, total_units=None)
        return job

    @classmethod
    def reattach(cls, root: Path) -> "ClimateJob":
        value = json.loads((root / "job.json").read_text(encoding="utf-8"))
        if value.get("schema_name") != JOB_SCHEMA:
            raise ValueError("invalid climate job schema")
        return cls(root, value["job_id"])

    def read(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def append_event(self, event: str, **values: Any) -> None:
        sequence = 1
        if self.events_path.exists():
            with self.events_path.open("rb") as stream:
                sequence += sum(1 for line in stream if line.strip())
        record = dict(schema_name=EVENT_SCHEMA, job_id=self.job_id, sequence=sequence,
                      timestamp=utc_now(), event=event, **values)
        with self.events_path.open("ab") as stream:
            stream.write(canonical_json(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())

    def transition(self, state: str, *, completed_units: int = 0,
                   total_units: int | None = None, **values: Any) -> None:
        manifest = self.read()
        current = manifest["state"]
        if state not in TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid climate job transition {current} -> {state}")
        if completed_units < 0 or (total_units is not None and (total_units < 0 or completed_units > total_units)):
            raise ValueError("invalid measured progress")
        manifest.update(values, state=state, completed_units=completed_units,
                        total_units=total_units, updated_at=utc_now())
        atomic_json(self.manifest_path, manifest)
        self.append_event("state", state=state, completed_units=completed_units,
                          total_units=total_units, **values)

    def request_cancel(self) -> None:
        self.cancel_path.write_text(utc_now() + "\n", encoding="utf-8")
        self.append_event("cancellation-requested", state=self.read()["state"])

    def cancellation_requested(self) -> bool:
        return self.cancel_path.is_file()
