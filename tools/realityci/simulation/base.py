"""Backend-neutral simulation lifecycle contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas.simulation import SimulationLiveState, SimulationSessionManifest


class SimulationBackend(ABC):
    @abstractmethod
    def preflight(self) -> dict: ...

    @abstractmethod
    def run(self, manifest: SimulationSessionManifest) -> SimulationLiveState: ...

    @abstractmethod
    def request_stop(self) -> None: ...
