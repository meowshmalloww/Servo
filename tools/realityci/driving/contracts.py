"""Runtime policy contracts kept separate from durable Pydantic descriptors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..schemas.driving import (
    CameraIntrinsics,
    DirectVehicleControl,
    DrivingPolicyDescriptor,
    ObservationSource,
    RouteCommand,
    TrajectoryAction,
)


@dataclass(frozen=True)
class PolicyResetContext:
    seed: int
    vehicle: Any = None
    world: Any = None
    route: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True)
class DrivingObservation:
    frame_id: int
    simulation_time_s: float
    camera_rgb: dict[str, np.ndarray]
    ego_speed_mps: float
    ego_acceleration_mps2: float | None
    recent_ego_poses: tuple[tuple[float, ...], ...]
    route_target_ego_m: tuple[float, float, float]
    navigation_command: RouteCommand
    camera_intrinsics: dict[str, CameraIntrinsics]
    previous_action: DirectVehicleControl | TrajectoryAction | None
    source: ObservationSource
    source_provenance: tuple[str, ...]
    hidden_seed: None = None
    privileged_actor_state: None = None


class DrivingPolicyAdapter(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> DrivingPolicyDescriptor: ...

    @abstractmethod
    def reset(self, context: PolicyResetContext) -> None: ...

    @abstractmethod
    def infer(self, observation: DrivingObservation) -> DirectVehicleControl | TrajectoryAction: ...

    def close(self) -> None:
        return None
