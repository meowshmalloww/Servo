"""Exact-frame bounded composition of CARLA dynamic actors over Servo 3DGS."""

from __future__ import annotations

import time

import numpy as np

from ...schemas.driving import ObservationSource
from .base import ObservationRenderRequest, ObservationRenderResult, ObservationRenderer


class HybridGaussianCarlaObservationRenderer(ObservationRenderer):
    def __init__(self, gaussian_renderer: ObservationRenderer, dynamic_actor_labels: set[int], *, meters_per_servo_unit: float = 1.0) -> None:
        if not np.isfinite(meters_per_servo_unit) or meters_per_servo_unit <= 0:
            raise ValueError("meters_per_servo_unit must be finite and positive")
        self.gaussian_renderer = gaussian_renderer
        self.dynamic_actor_labels = dynamic_actor_labels
        self.meters_per_servo_unit = float(meters_per_servo_unit)
        self._frames: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    @property
    def source(self) -> ObservationSource:
        return ObservationSource.HYBRID

    def supply_exact_frames(self, frame_id: int, rgb: np.ndarray, depth_m: np.ndarray, instance_labels: np.ndarray) -> None:
        if rgb.shape[:2] != depth_m.shape or depth_m.shape != instance_labels.shape:
            raise ValueError("hybrid RGB, depth, and instance frames must have identical dimensions")
        self._frames[frame_id] = (rgb.copy(), depth_m.copy(), instance_labels.copy())

    def render(self, request: ObservationRenderRequest) -> ObservationRenderResult:
        started = time.perf_counter()
        dynamic = self._frames.pop(request.frame_id, None)
        if dynamic is None:
            raise RuntimeError(f"exact hybrid actor frames {request.frame_id} are unavailable")
        background = self.gaussian_renderer.render(request)
        if background.expected_depth is None:
            raise RuntimeError("hybrid rendering requires Gaussian expected depth")
        actor_rgb, actor_depth, labels = dynamic
        mask = np.isin(labels, list(self.dynamic_actor_labels))
        gaussian_depth_m = background.expected_depth * self.meters_per_servo_unit
        visible = mask & ((background.support_map < 0.05) | (actor_depth <= gaussian_depth_m + 0.15))
        output = background.rgb.copy()
        output[visible] = actor_rgb[visible]
        return ObservationRenderResult(
            frame_id=request.frame_id, rgb=output, intrinsics=request.intrinsics,
            camera_pose=request.camera_pose_servo, source=self.source,
            source_hashes=background.source_hashes,
            render_latency_ms=(time.perf_counter() - started) * 1000.0,
            coverage_score=background.coverage_score,
            warnings=("Dynamic actor mask/depth originated in synchronized CARLA generated frames.",),
            expected_depth=gaussian_depth_m, support_map=background.support_map,
        )

    def close(self) -> None:
        self.gaussian_renderer.close()
