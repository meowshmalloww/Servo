"""Idempotent cleanup limited to actors and server processes owned by one session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OwnedActors:
    session_id: str
    actors: list[Any] = field(default_factory=list)
    cleaned: bool = False

    def add(self, actor: Any) -> Any:
        self.actors.append(actor)
        return actor

    def cleanup(self) -> dict:
        if self.cleaned:
            return {"session_id": self.session_id, "already_clean": True, "destroyed": 0, "errors": []}
        destroyed = 0
        errors: list[str] = []
        for actor in reversed(self.actors):
            try:
                if hasattr(actor, "stop"):
                    actor.stop()
                actor.destroy()
                destroyed += 1
            except Exception as exc:
                errors.append(str(exc))
        self.actors.clear()
        self.cleaned = True
        return {"session_id": self.session_id, "already_clean": False, "destroyed": destroyed, "errors": errors}
