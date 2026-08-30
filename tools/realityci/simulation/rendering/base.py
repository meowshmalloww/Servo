"""Renderer contract shared by CARLA, Servo Gaussian, and hybrid observations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ...hashing import sha256_digest
from ...schemas.driving import CameraIntrinsics, ObservationSource, Pose


@dataclass(frozen=True)
class ObservationRenderRequest:
    frame_id: int
    camera_pose_servo: Pose
    intrinsics: CameraIntrinsics
    sensor_id: str = "front"


@dataclass(frozen=True)
class ObservationRenderResult:
    frame_id: int
    rgb: np.ndarray
    intrinsics: CameraIntrinsics
    camera_pose: Pose
    source: ObservationSource
    source_hashes: tuple[str, ...]
    render_latency_ms: float
    coverage_score: float
    warnings: tuple[str, ...] = ()
    expected_depth: np.ndarray | None = None
    support_map: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.rgb.shape != (self.intrinsics.height, self.intrinsics.width, 3):
            raise ValueError("rendered RGB dimensions do not match declared intrinsics")
        if self.rgb.dtype != np.uint8:
            raise ValueError("rendered RGB must be uint8")
        if not 0.0 <= self.coverage_score <= 1.0:
            raise ValueError("coverage score must be in [0, 1]")

    @property
    def frame_sha256(self) -> str:
        return sha256_digest(self.rgb.tobytes(order="C"))


class ObservationRenderer(ABC):
    @property
    @abstractmethod
    def source(self) -> ObservationSource: ...

    @abstractmethod
    def render(self, request: ObservationRenderRequest) -> ObservationRenderResult: ...

    def close(self) -> None:
        return None
