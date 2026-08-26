"""Deterministic scenario execution: kinematics, visibility, collision truth."""

from __future__ import annotations

from .dynamics import (
    CollisionEvent,
    EgoState,
    OccluderBox,
    advance_ego,
    circle_box_collision,
    circle_box_distance,
    ego_box,
    pedestrian_circle,
    pedestrian_world_position,
    segment_intersects_axis_aligned_rect,
    visible_fraction,
)
from .projection import CameraModel, project_point
from .runner import OracleConfig, RunOutcome, RunnerTiming, ScenarioRunner, SensorPacket, StepTelemetry

__all__ = [
    "CollisionEvent",
    "EgoState",
    "OccluderBox",
    "advance_ego",
    "circle_box_collision",
    "circle_box_distance",
    "ego_box",
    "pedestrian_circle",
    "pedestrian_world_position",
    "segment_intersects_axis_aligned_rect",
    "visible_fraction",
    "OracleConfig",
    "CameraModel",
    "project_point",
    "RunOutcome",
    "RunnerTiming",
    "ScenarioRunner",
    "SensorPacket",
    "StepTelemetry",
]
