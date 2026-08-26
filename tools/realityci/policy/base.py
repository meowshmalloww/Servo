"""Policy adapter contracts.

A policy observes exactly what a real sensor stack would provide: camera
frames and ego speed.  Ground-truth actor state never reaches a non-oracle
policy.  Adapters are honest about trainability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..schemas.run import PolicyDescriptor


@dataclass(frozen=True)
class SensorPacket:
    time_s: float
    ego_speed_mps: float
    frame_rgb: np.ndarray | None


class PolicyAdapter(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> PolicyDescriptor: ...

    @abstractmethod
    def reset(self, seed: int) -> None: ...

    @abstractmethod
    def observe(self, packet: SensorPacket) -> float:
        """Return pedestrian hazard risk in [0, 1] for the current packet."""

    def close(self) -> None:
        return None
