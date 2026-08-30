"""Strict contracts for closed-loop autonomous-driving observations and evidence."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Vector3(StrictModel):
    x: float
    y: float
    z: float


class Quaternion(StrictModel):
    w: float
    x: float
    y: float
    z: float


class Pose(StrictModel):
    position: Vector3
    orientation: Quaternion


class CameraIntrinsics(StrictModel):
    width: int = Field(ge=16, le=4096)
    height: int = Field(ge=16, le=4096)
    horizontal_fov_deg: float = Field(gt=1.0, lt=179.0)
    fx: float = Field(gt=0.0)
    fy: float = Field(gt=0.0)
    cx: float
    cy: float


class CameraSensorDescriptor(StrictModel):
    sensor_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    kind: Literal["rgb", "depth", "instance-segmentation"]
    mount_vehicle: Pose
    intrinsics: CameraIntrinsics
    sensor_tick_seconds: float = Field(gt=0.0, le=1.0)


class ObservationSource(str, Enum):
    CARLA_RGB = "carla-rgb"
    SERVO_GAUSSIAN = "servo-gaussian"
    HYBRID = "hybrid"


class RouteCommand(str, Enum):
    FOLLOW_LANE = "follow-lane"
    TURN_LEFT = "turn-left"
    TURN_RIGHT = "turn-right"
    STRAIGHT = "straight"
    STOP = "stop"


class DrivingPolicyDescriptor(StrictModel):
    adapter: Literal["carla-behavior-reference", "servo-tinydrive", "onnx-driving", "external-driving"]
    name: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=64)
    checkpoint_uri: str | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    oracle: bool = False
    uses_privileged_state: bool = False
    trainable: bool = False
    eligible_for_promotion: bool = True
    input_camera_ids: tuple[str, ...] = ("front",)
    uses_ego_speed: bool = True
    uses_ego_acceleration: bool = False
    uses_recent_ego_poses: bool = False
    uses_previous_action: bool = False

    @model_validator(mode="after")
    def validate_honesty(self) -> "DrivingPolicyDescriptor":
        if self.oracle and (not self.uses_privileged_state or self.eligible_for_promotion):
            raise ValueError("oracle policies must declare privileged state and cannot be promoted")
        if self.adapter == "servo-tinydrive" and not self.trainable:
            raise ValueError("ServoTinyDrive must be declared trainable")
        if self.adapter != "carla-behavior-reference" and self.uses_privileged_state:
            raise ValueError("non-reference policies may not use privileged state")
        if self.checkpoint_uri and not self.checkpoint_sha256:
            raise ValueError("checkpoint_sha256 is required when checkpoint_uri is set")
        return self


class DrivingObservationDescriptor(StrictModel):
    schema_name: Literal["servo.driving-observation/v1"] = "servo.driving-observation/v1"
    frame_id: int = Field(ge=0)
    simulation_time_s: float = Field(ge=0.0)
    source: ObservationSource
    camera_ids: tuple[str, ...]
    ego_speed_mps: float = Field(ge=0.0)
    ego_acceleration_mps2: float | None = None
    route_target_ego_m: Vector3
    navigation_command: RouteCommand
    camera_intrinsics: dict[str, CameraIntrinsics]
    frame_sha256: dict[str, str]
    previous_action_id: str | None = None
    source_provenance: tuple[str, ...]
    renderer_coverage: float = Field(ge=0.0, le=1.0)


class DirectVehicleControl(StrictModel):
    kind: Literal["direct-control"] = "direct-control"
    steer: float
    throttle: float
    brake: float
    hand_brake: bool = False
    reverse: bool = False


class TrajectoryWaypoint(StrictModel):
    time_offset_s: float = Field(gt=0.0, le=10.0)
    x_forward_m: float
    y_left_m: float


class TrajectoryAction(StrictModel):
    kind: Literal["trajectory"] = "trajectory"
    waypoints: tuple[TrajectoryWaypoint, ...] = Field(min_length=2, max_length=32)
    desired_speed_mps: float = Field(ge=0.0, le=50.0)
    confidence: float = Field(ge=0.0, le=1.0)


DrivingAction = Annotated[
    DirectVehicleControl | TrajectoryAction,
    Field(discriminator="kind"),
]


class DrivingActionRecord(StrictModel):
    schema_name: Literal["servo.driving-action/v1"] = "servo.driving-action/v1"
    action_id: str = Field(pattern=r"^act-[0-9a-f]{16}$")
    observation_frame_id: int = Field(ge=0)
    produced_at: datetime
    inference_latency_ms: float = Field(ge=0.0)
    raw_action: DrivingAction
    validation_ok: bool
    validation_errors: tuple[str, ...] = ()


class AppliedVehicleControl(StrictModel):
    schema_name: Literal["servo.applied-control/v1"] = "servo.applied-control/v1"
    simulation_frame_id: int = Field(ge=0)
    observation_frame_id: int = Field(ge=0)
    action_id: str = Field(pattern=r"^act-[0-9a-f]{16}$")
    steer: float = Field(ge=-1.0, le=1.0)
    throttle: float = Field(ge=0.0, le=1.0)
    brake: float = Field(ge=0.0, le=1.0)
    hand_brake: bool = False
    reverse: bool = False
    emergency_braking: bool = False


class DrivingOutcome(str, Enum):
    SUCCESS = "success"
    COLLISION = "collision"
    ROUTE_DEPARTURE = "route_departure"
    STUCK = "stuck"
    TIMEOUT = "timeout"
    POLICY_TIMEOUT = "policy_timeout"
    SENSOR_DESYNCHRONIZATION = "sensor_desynchronization"
    RENDERER_OUT_OF_SUPPORT = "renderer_out_of_support"
    INFRASTRUCTURE_INVALID = "infrastructure_invalid"
    CANCELLED = "cancelled"


class DrivingFailureClass(str, Enum):
    COLLISION_VEHICLE = "collision_vehicle"
    COLLISION_PEDESTRIAN = "collision_pedestrian"
    COLLISION_STATIC = "collision_static"
    ROUTE_DEPARTURE = "route_departure"
    LANE_KEEPING_FAILURE = "lane_keeping_failure"
    UNSAFE_FOLLOWING = "unsafe_following"
    RED_LIGHT_VIOLATION = "red_light_violation"
    POLICY_TIMEOUT = "policy_timeout"
    POLICY_INVALID_ACTION = "policy_invalid_action"
    CONTROLLER_TRACKING_FAILURE = "controller_tracking_failure"
    SENSOR_DESYNCHRONIZATION = "sensor_desynchronization"
    RENDERER_OUT_OF_SUPPORT = "renderer_out_of_support"
    VISUAL_DOMAIN_FAILURE = "visual_domain_failure"
    MAP_ALIGNMENT_FAILURE = "map_alignment_failure"
    PHYSICS_WORLD_INVALID = "physics_world_invalid"
    STUCK = "stuck"
    SIMULATION_TIMEOUT = "simulation_timeout"


class DrivingRunMetrics(StrictModel):
    simulation_duration_s: float = Field(ge=0.0)
    fixed_delta_seconds: float = Field(gt=0.0)
    frame_count: int = Field(ge=0)
    distance_traveled_m: float = Field(ge=0.0)
    route_completion: float = Field(ge=0.0, le=1.0)
    min_speed_mps: float = Field(ge=0.0)
    max_speed_mps: float = Field(ge=0.0)
    final_speed_mps: float = Field(ge=0.0)
    mean_lateral_error_m: float = Field(ge=0.0)
    max_lateral_error_m: float = Field(ge=0.0)
    mean_policy_latency_ms: float = Field(ge=0.0)
    max_policy_latency_ms: float = Field(ge=0.0)
    deadline_misses: int = Field(ge=0)
    sensor_sync_failures: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    lane_invasion_count: int = Field(ge=0)
    out_of_support_duration_s: float = Field(ge=0.0)


class DrivingRunEvidence(StrictModel):
    schema_name: Literal["servo.driving-run-evidence/v1"] = "servo.driving-run-evidence/v1"
    session_id: str = Field(pattern=r"^sim-[0-9a-f]{16}$")
    campaign_id: str | None = None
    executable_world_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    opendrive_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    appearance_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    carla_version: str
    carla_executable_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    carla_python_api_version: str
    policy: DrivingPolicyDescriptor
    controller_version: str
    renderer_version: str
    observation_source: ObservationSource
    seed: int
    weather: Literal["clear", "snow"] = "clear"
    weather_receipt: dict[str, Any] = Field(default_factory=dict)
    autopilot_enabled: Literal[False] = False
    metrics: DrivingRunMetrics
    outcome: DrivingOutcome
    failure_class: DrivingFailureClass | None = None
    infrastructure_invalid: bool = False
    artifact_sha256: dict[str, str]
    created_at: datetime
