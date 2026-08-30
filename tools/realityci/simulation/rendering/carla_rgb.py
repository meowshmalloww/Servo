"""Exact synchronized CARLA RGB observation adapter."""

from __future__ import annotations

import time

import numpy as np

from ...hashing import sha256_digest
from ...schemas.driving import ObservationSource
from .base import ObservationRenderRequest, ObservationRenderResult, ObservationRenderer


class CarlaRgbObservationRenderer(ObservationRenderer):
    def __init__(self, carla_version: str, map_hash: str, weather: str) -> None:
        self.carla_version = carla_version
        self.map_hash = map_hash
        self.weather = weather
        self._frames: dict[int, np.ndarray] = {}

    @property
    def source(self) -> ObservationSource:
        return ObservationSource.CARLA_RGB

    def supply_frame(self, frame_id: int, bgra_bytes: bytes, width: int, height: int) -> None:
        expected = width * height * 4
        if len(bgra_bytes) != expected:
            raise ValueError(f"CARLA RGB byte size mismatch: expected {expected}, got {len(bgra_bytes)}")
        bgra = np.frombuffer(bgra_bytes, dtype=np.uint8).reshape(height, width, 4)
        self._frames[frame_id] = bgra[:, :, :3][:, :, ::-1].copy()
        if len(self._frames) > 8:
            del self._frames[min(self._frames)]

    def render(self, request: ObservationRenderRequest) -> ObservationRenderResult:
        started = time.perf_counter()
        frame = self._frames.pop(request.frame_id, None)
        if frame is None:
            raise RuntimeError(f"exact CARLA RGB frame {request.frame_id} is unavailable")
        return ObservationRenderResult(
            frame_id=request.frame_id,
            rgb=frame,
            intrinsics=request.intrinsics,
            camera_pose=request.camera_pose_servo,
            source=self.source,
            source_hashes=(self.map_hash, sha256_digest(f"CARLA {self.carla_version}|{self.weather}".encode())),
            render_latency_ms=(time.perf_counter() - started) * 1000.0,
            coverage_score=1.0,
        )
