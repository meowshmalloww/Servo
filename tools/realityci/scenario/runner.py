"""Deterministic occluded-pedestrian scenario runner.

One execution integrates the declared scenario at a fixed timestep with a
policy adapter and optional oracle overrides.  Identical inputs produce
identical telemetry, metrics, and outcomes; nothing random happens inside
the loop.  All writes stay inside the caller-provided job directory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..policy.base import PolicyAdapter, SensorPacket
from ..schemas.run import RunResult
from ..schemas.scenario import ScenarioManifest
from .compositor import FrameCompositor
from .dynamics import (
    EgoState,
    OccluderBox,
    advance_ego,
    circle_box_collision,
    circle_box_distance,
    ego_box,
    pedestrian_circle,
    pedestrian_world_position,
    visible_fraction,
)
from .projection import CameraModel


@dataclass(frozen=True)
class OracleConfig:
    """Execution-level oracle overrides.  Each replaces exactly one stage."""

    perception: bool = False
    planner: bool = False
    controller: bool = False

    def as_parameter_dict(self) -> dict[str, float]:
        return {
            "oracle_perception": float(self.perception),
            "oracle_planner": float(self.planner),
            "oracle_controller": float(self.controller),
        }


@dataclass(frozen=True)
class RunnerTiming:
    frame_hz: float = 10.0
    camera_fov_deg: float = 45.0
    camera_pitch_deg: float = 8.0
    camera_height_m: float = 1.45
    camera_forward_offset_m: float = 2.3
    detection_threshold: float = 0.5
    detection_release_threshold: float = 0.32
    visibility_threshold: float = 0.05
    near_miss_margin_m: float = 0.5
    stop_speed_epsilon_mps: float = 0.05
    corridor_clear_margin_m: float = 0.6
    oracle_planner_threshold: float = 0.2


@dataclass(frozen=True)
class StepTelemetry:
    time_s: float
    ego_s_m: float
    ego_speed_mps: float
    brake_requested: bool
    braking_active: bool
    risk: float
    detected: bool
    gt_visible_fraction: float
    pedestrian_s_m: Optional[float]
    pedestrian_y_m: Optional[float]
    min_distance_m: float


@dataclass(frozen=True)
class RunOutcome:
    result: RunResult
    telemetry: tuple[StepTelemetry, ...]
    duration_s: float
    distance_travelled_m: float
    min_ego_speed_mps: float
    final_ego_speed_mps: float
    brake_requested: bool
    min_pedestrian_distance_m: Optional[float]
    first_ground_truth_visibility_s: Optional[float]
    first_policy_detection_s: Optional[float]
    brake_command_s: Optional[float]
    collision_time_s: Optional[float]
    collision_relative_speed_mps: Optional[float]
    confidence_at_detection: Optional[float]
    frames: dict[float, np.ndarray] = field(default_factory=dict)


class ScenarioRunner:
    def __init__(
        self,
        manifest: ScenarioManifest,
        policy: PolicyAdapter,
        oracle: OracleConfig = OracleConfig(),
        timing: RunnerTiming = RunnerTiming(),
        capture_frames: bool = False,
    ) -> None:
        self.manifest = manifest
        self.policy = policy
        self.oracle = oracle
        self.timing = timing
        self.capture_frames = capture_frames
        self.camera = CameraModel.from_horizontal_fov(
            width_px=160,
            height_px=96,
            horizontal_fov_deg=timing.camera_fov_deg,
            height_m=timing.camera_height_m,
            forward_offset_m=timing.camera_forward_offset_m,
            pitch_down_deg=timing.camera_pitch_deg,
        )
        self.compositor = FrameCompositor(manifest, self.camera)

    @property
    def _frame_period_s(self) -> float:
        return 1.0 / self.timing.frame_hz

    def run(self) -> RunOutcome:
        manifest = self.manifest
        spec = manifest.ego
        dt = manifest.dt_s
        cross_s = self._pedestrian_cross_s()

        self.policy.reset(manifest.seed)
        compositor = self.compositor
        ped_spec = manifest.pedestrian
        occluder_box = OccluderBox.from_spec(manifest.occluder) if manifest.occluder else None

        ego = EgoState(
            s_m=manifest.route.start_s_m,
            speed_mps=spec.initial_speed_mps,
            braking_active=False,
        )
        actuation_delay = 0.0 if self.oracle.controller else spec.brake_actuation_delay_s

        telemetry: list[StepTelemetry] = []
        frames: dict[float, np.ndarray] = {}
        next_frame_t = 0.0

        first_visibility: float | None = None
        first_detection: float | None = None
        confidence_at_detection: float | None = None
        brake_command_at: float | None = None
        collision_time: float | None = None
        collision_relative_speed: float | None = None
        min_ped_distance: float | None = None
        any_brake_request = False
        reached_end = False
        held_risk = 0.0
        detection_latch = False

        steps = int(round(manifest.horizon_s / dt))
        for step_index in range(steps):
            t = round(step_index * dt, 10)
            front = ego.s_m + spec.length_m / 2.0
            rear = ego.s_m - spec.length_m / 2.0
            y_lo, y_hi = -spec.width_m / 2.0, spec.width_m / 2.0

            ped_position: Optional[tuple[float, float]] = None
            visible_frac = 0.0
            if ped_spec is not None:
                ped_s, ped_y = pedestrian_world_position(cross_s, ped_spec, t)
                ped_position = (ped_s, ped_y)
                camera_s = ego.s_m + self.timing.camera_forward_offset_m
                visible_frac = visible_fraction(
                    camera_s=camera_s,
                    camera_y=0.0,
                    camera_z=self.timing.camera_height_m,
                    ped_s=ped_s,
                    ped_y=ped_y,
                    ped_width_m=ped_spec.width_m,
                    ped_height_m=ped_spec.height_m,
                    horizontal_fov_half_deg=self.timing.camera_fov_deg / 2.0,
                    occluder=occluder_box,
                )
                if visible_frac >= self.timing.visibility_threshold and first_visibility is None:
                    first_visibility = t
                distance = circle_box_distance(
                    *pedestrian_circle(ped_s, ped_y, ped_spec),
                    (rear, front, y_lo, y_hi),
                )
                if min_ped_distance is None or distance < min_ped_distance:
                    min_ped_distance = distance

            emit_frame = self.capture_frames and t >= next_frame_t - 1e-9
            frame = None
            if emit_frame:
                frame = compositor.render(
                    ego_s=ego.s_m,
                    elapsed_s=t,
                    occluder_box=occluder_box,
                    ped_position=ped_position,
                    ped_height_m=ped_spec.height_m if ped_spec is not None else 0.0,
                    ped_width_m=ped_spec.width_m if ped_spec is not None else 0.0,
                )
                frames[t] = frame
                while next_frame_t <= t + 1e-9:
                    next_frame_t += self._frame_period_s

            packet = SensorPacket(time_s=t, ego_speed_mps=ego.speed_mps, frame_rgb=frame)
            if self.oracle.perception:
                risk = 1.0 if visible_frac >= self.timing.visibility_threshold else 0.0
                if risk >= self.timing.detection_threshold:
                    detection_latch = True
                elif risk < self.timing.detection_release_threshold:
                    detection_latch = False
                detected = detection_latch
            else:
                if emit_frame:
                    held_risk = float(np.clip(self.policy.observe(packet), 0.0, 1.0))
                risk = held_risk
                if held_risk >= self.timing.detection_threshold:
                    detection_latch = True
                elif held_risk < self.timing.detection_release_threshold:
                    detection_latch = False
                detected = detection_latch

            if detected and ped_position is not None and first_detection is None and visible_frac > 0.0:
                first_detection = t
                confidence_at_detection = risk

            brake_request = self._plan_brake(
                ego_front=front,
                ego_speed=ego.speed_mps,
                risk=risk,
                ped_position=ped_position,
                detected=detected,
            )
            if brake_request and not any_brake_request:
                brake_command_at = t
                any_brake_request = True

            ego, actuation_delay = advance_ego(
                state=ego,
                brake_requested=brake_request,
                actuation_delay_remaining_s=actuation_delay,
                dt_s=dt,
                spec=spec,
            )

            telemetry.append(
                StepTelemetry(
                    time_s=t,
                    ego_s_m=ego.s_m,
                    ego_speed_mps=ego.speed_mps,
                    brake_requested=brake_request,
                    braking_active=ego.braking_active,
                    risk=risk,
                    detected=detected,
                    gt_visible_fraction=visible_frac,
                    pedestrian_s_m=ped_position[0] if ped_position else None,
                    pedestrian_y_m=ped_position[1] if ped_position else None,
                    min_distance_m=min_ped_distance,
                )
            )

            if ped_position is not None and ped_spec is not None:
                hit = circle_box_collision(
                    *pedestrian_circle(*ped_position, ped_spec),
                    (rear, front, y_lo, y_hi),
                )
                if hit and ego.speed_mps > 0.0:
                    collision_time = t + dt
                    collision_relative_speed = math.hypot(
                        ego.speed_mps, self._pedestrian_lateral_speed(t)
                    )
                    break

            if (
                ego.braking_active
                and ego.speed_mps <= self.timing.stop_speed_epsilon_mps
            ):
                break

            if ego.s_m >= manifest.route.end_s_m:
                reached_end = True
                break

        result = self._classify(
            collision_time=collision_time,
            min_ped_distance=min_ped_distance,
            final_speed=ego.speed_mps,
            reached_end=reached_end,
        )

        return RunOutcome(
            result=result,
            telemetry=tuple(telemetry),
            duration_s=telemetry[-1].time_s + dt if telemetry else 0.0,
            distance_travelled_m=(telemetry[-1].ego_s_m - manifest.route.start_s_m) if telemetry else 0.0,
            min_ego_speed_mps=min((row.ego_speed_mps for row in telemetry), default=0.0),
            final_ego_speed_mps=ego.speed_mps,
            brake_requested=any_brake_request,
            min_pedestrian_distance_m=min_ped_distance,
            first_ground_truth_visibility_s=first_visibility,
            first_policy_detection_s=first_detection,
            brake_command_s=brake_command_at,
            collision_time_s=collision_time,
            collision_relative_speed_mps=collision_relative_speed,
            confidence_at_detection=confidence_at_detection,
            frames=frames,
        )

    def _pedestrian_cross_s(self) -> float:
        if self.manifest.occluder is None:
            midpoint = (self.manifest.route.start_s_m + self.manifest.route.end_s_m) / 2.0
            return midpoint
        return self.manifest.occluder.position_s_m + 6.0

    def _plan_brake(
        self,
        ego_front: float,
        ego_speed: float,
        risk: float,
        ped_position: Optional[tuple[float, float]],
        detected: bool,
    ) -> bool:
        """Oracle planner uses ONLY the perception risk stream (lower threshold,
        same information as the baseline planner) so that planner-versus-
        perception attribution stays causally clean."""
        if self.oracle.planner:
            return risk >= self.timing.oracle_planner_threshold
        if not detected or ped_position is None:
            return False
        if ped_position[0] <= ego_front:
            return False
        return True

    def _pedestrian_lateral_speed(self, current_t: float) -> float:
        spec = self.manifest.pedestrian
        if spec is None or current_t <= spec.emergence_s:
            return 0.0
        angle_rad = math.radians(spec.crossing_angle_deg)
        direction = 1.0 if spec.end_lateral_m >= spec.start_lateral_m else -1.0
        return spec.crossing_speed_mps * math.sin(angle_rad) * direction

    def _classify(
        self,
        collision_time: Optional[float],
        min_ped_distance: Optional[float],
        final_speed: float,
        reached_end: bool,
    ) -> RunResult:
        if collision_time is not None:
            return RunResult.COLLISION
        if self.manifest.pedestrian is not None:
            if min_ped_distance is not None and min_ped_distance < self.timing.near_miss_margin_m:
                return RunResult.NEAR_MISS
            if reached_end:
                return RunResult.SUCCESS
            if final_speed <= self.timing.stop_speed_epsilon_mps:
                return RunResult.SUCCESS
            return RunResult.TIMEOUT
        if reached_end:
            return RunResult.SUCCESS
        return RunResult.TIMEOUT
