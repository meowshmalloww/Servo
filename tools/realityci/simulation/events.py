"""Append-only, monotonic simulation event log."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SimulationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str = "servo.simulation-event/v1"
    sequence: int = Field(ge=1)
    session_id: str
    event_type: str
    created_at: datetime
    payload: dict


class SimulationEventLog:
    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.session_id = session_id
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def events(self) -> list[SimulationEvent]:
        if not self.path.exists():
            return []
        result: list[SimulationEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                event = SimulationEvent.model_validate_json(line)
                expected = len(result) + 1
                if event.sequence != expected:
                    raise ValueError(
                        f"non-monotonic simulation event at line {line_number}: "
                        f"expected {expected}, got {event.sequence}"
                    )
                result.append(event)
        return result

    def append(self, event_type: str, payload: dict) -> SimulationEvent:
        with self._lock:
            sequence = len(self.events()) + 1
            event = SimulationEvent(
                sequence=sequence,
                session_id=self.session_id,
                event_type=event_type,
                created_at=datetime.now(timezone.utc),
                payload=payload,
            )
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event
