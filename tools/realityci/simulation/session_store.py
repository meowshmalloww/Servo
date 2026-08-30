"""Atomic durable session state and detached-worker control files."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..hashing import canonical_json_bytes, sha256_digest
from ..schemas.simulation import (
    SimulationLiveState,
    SimulationSessionManifest,
    SimulationSessionState,
)
from .events import SimulationEventLog


class SimulationTransitionError(ValueError):
    pass


LEGAL_TRANSITIONS: dict[SimulationSessionState, set[SimulationSessionState]] = {
    SimulationSessionState.CREATED: {SimulationSessionState.PREFLIGHTING, SimulationSessionState.CANCELLED},
    SimulationSessionState.PREFLIGHTING: {SimulationSessionState.LAUNCHING_SERVER, SimulationSessionState.CONNECTING, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.LAUNCHING_SERVER: {SimulationSessionState.CONNECTING, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.CONNECTING: {SimulationSessionState.LOADING_WORLD, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.LOADING_WORLD: {SimulationSessionState.SPAWNING, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.SPAWNING: {SimulationSessionState.WARMING, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.WARMING: {SimulationSessionState.RUNNING, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.RUNNING: {SimulationSessionState.PAUSED, SimulationSessionState.STOPPING, SimulationSessionState.COMPLETED, SimulationSessionState.FAILED, SimulationSessionState.CANCELLED},
    SimulationSessionState.PAUSED: {SimulationSessionState.RUNNING, SimulationSessionState.STOPPING, SimulationSessionState.CANCELLED, SimulationSessionState.FAILED},
    SimulationSessionState.STOPPING: {SimulationSessionState.COMPLETED, SimulationSessionState.CANCELLED, SimulationSessionState.FAILED},
    SimulationSessionState.COMPLETED: set(),
    SimulationSessionState.FAILED: set(),
    SimulationSessionState.CANCELLED: set(),
}


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write(path, canonical_json_bytes(payload) + b"\n")


class SessionStore:
    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root.resolve()
        self.session_id = session_id
        self.session_root = self.root / session_id
        self.manifest_path = self.session_root / "session-manifest.json"
        self.state_path = self.session_root / "state.json"
        self.live_path = self.session_root / "live-state.json"
        self.control_path = self.session_root / "control.json"
        self.pid_path = self.session_root / "worker.json"
        self.events = SimulationEventLog(self.session_root / "events.jsonl", session_id)

    def initialize(self, manifest_payload: dict) -> SimulationSessionManifest:
        if self.session_root.exists() and any(self.session_root.iterdir()):
            raise FileExistsError(f"session already exists: {self.session_id}")
        self.session_root.mkdir(parents=True, exist_ok=True)
        for relative in ("logs", "sensors/front-rgb", "previews"):
            (self.session_root / relative).mkdir(parents=True, exist_ok=True)
        payload = dict(manifest_payload)
        payload.pop("content_hash", None)
        payload["content_hash"] = "sha256:" + "0" * 64
        manifest = SimulationSessionManifest.model_validate(payload)
        dumped = manifest.model_dump(mode="json")
        dumped.pop("content_hash", None)
        content_hash = sha256_digest(canonical_json_bytes(dumped))
        manifest = manifest.model_copy(update={"content_hash": content_hash})
        atomic_write_json(self.manifest_path, manifest.model_dump(mode="json"))
        self._write_state(SimulationSessionState.CREATED, "session created")
        atomic_write_json(self.control_path, {"command": "run", "sequence": 0})
        self.events.append("state-transition", {"from": None, "to": "created"})
        return manifest

    def load_manifest(self) -> SimulationSessionManifest:
        manifest = SimulationSessionManifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))
        payload = manifest.model_dump(mode="json")
        sealed = payload.pop("content_hash")
        computed = sha256_digest(canonical_json_bytes(payload))
        if sealed != computed:
            raise ValueError(f"session manifest hash mismatch: expected {sealed}, computed {computed}")
        return manifest

    def _write_state(self, state: SimulationSessionState, detail: str = "") -> None:
        atomic_write_json(
            self.state_path,
            {
                "schema_name": "servo.simulation-state/v1",
                "session_id": self.session_id,
                "state": state.value,
                "detail": detail,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def state(self) -> SimulationSessionState:
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return SimulationSessionState(payload["state"])

    def transition(self, target: SimulationSessionState, detail: str = "") -> None:
        current = self.state()
        if target not in LEGAL_TRANSITIONS[current]:
            raise SimulationTransitionError(f"illegal simulation transition: {current.value} -> {target.value}")
        self._write_state(target, detail)
        self.events.append("state-transition", {"from": current.value, "to": target.value, "detail": detail})

    def publish_live(self, state: SimulationLiveState) -> None:
        if state.session_id != self.session_id:
            raise ValueError("live-state session id does not match store")
        atomic_write_json(self.live_path, state.model_dump(mode="json"))

    def live(self) -> SimulationLiveState:
        return SimulationLiveState.model_validate_json(self.live_path.read_text(encoding="utf-8"))

    def command(self, name: str) -> None:
        if name not in {"run", "pause", "resume", "stop", "cancel"}:
            raise ValueError(f"unsupported simulation command: {name}")
        sequence = 1
        if self.control_path.exists():
            sequence = int(json.loads(self.control_path.read_text(encoding="utf-8")).get("sequence", 0)) + 1
        atomic_write_json(self.control_path, {"command": name, "sequence": sequence})

    def read_command(self) -> dict:
        if not self.control_path.exists():
            return {"command": "run", "sequence": 0}
        return json.loads(self.control_path.read_text(encoding="utf-8"))

    def record_worker(self, pid: int, argv: list[str]) -> None:
        atomic_write_json(
            self.pid_path,
            {
                "schema_name": "servo.simulation-worker/v1",
                "pid": pid,
                "argv": argv,
                "launched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
