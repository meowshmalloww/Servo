"""Versioned schemas for durable simulation sessions and executable worlds."""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .driving import (
    CameraSensorDescriptor,
    DrivingOutcome,
    DrivingPolicyDescriptor,
    ObservationSource,
    Pose,
    Vector3,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SimulationBackendKind(str, Enum):
    DETERMINISTIC_LITE = "deterministic-lite"
    CARLA = "carla"


class SimulationSessionState(str, Enum):
    CREATED = "created"
    PREFLIGHTING = "preflighting"
    LAUNCHING_SERVER = "launching_server"
    CONNECTING = "connecting"
    LOADING_WORLD = "loading_world"
    SPAWNING = "spawning"
    WARMING = "warming"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_SIMULATION_STATES = {
    SimulationSessionState.COMPLETED,
    SimulationSessionState.FAILED,
    SimulationSessionState.CANCELLED,
}


class CarlaRuntimeDescriptor(StrictModel):
    schema_name: Literal["servo.carla-runtime/v1"] = "servo.carla-runtime/v1"
    root: str
    executable: str
    executable_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    python_api_path: str
    python_api_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    client_version: str
    server_version: str | None = None
    expected_version: Literal["0.9.16"] = "0.9.16"
    rpc_port: int = Field(ge=1024, le=65535)
    traffic_manager_port: int = Field(ge=1024, le=65535)
    maps: tuple[str, ...] = ()
    agents_available: bool
    receipt_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class AppearanceDescriptor(StrictModel):
    kind: Literal["servo-gaussian"] = "servo-gaussian"
    ply_uri: str
    world_manifest_uri: str
    appearance_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class StructureDescriptor(StrictModel):
    opendrive_uri: str
    opendrive_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    road_surface_uri: str | None = None
    collision_mesh_uri: str | None = None
    structural_status: Literal["inferred", "measured", "imported"]


class ScaleDescriptor(StrictModel):
    status: Literal["measured", "inferred"]
    meters_per_servo_unit: float = Field(gt=0.0, le=1000.0)
    uncertainty_fraction: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=128)


class FrameTransformDescriptor(StrictModel):
    servo_frame: Literal["servo-world"] = "servo-world"
    carla_frame: Literal["carla-local"] = "carla-local"
    carla_from_servo_row_major: tuple[float, ...] = Field(min_length=16, max_length=16)
    servo_from_carla_row_major: tuple[float, ...] = Field(min_length=16, max_length=16)
    handedness_conversion: str = Field(min_length=1, max_length=256)
    round_trip_error_m: float = Field(ge=0.0, le=1e-3)

    @model_validator(mode="after")
    def finite(self) -> "FrameTransformDescriptor":
        if not all(math.isfinite(x) for x in (*self.carla_from_servo_row_major, *self.servo_from_carla_row_major)):
            raise ValueError("coordinate matrices must contain only finite values")
        return self


class RouteDescriptor(StrictModel):
    route_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    start_pose_carla: Pose
    goal_pose_carla: Pose
    centerline_carla: tuple[Vector3, ...] = Field(min_length=2, max_length=20000)
    length_m: float = Field(gt=0.0)
    route_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CaptureEnvelopeDescriptor(StrictModel):
    source: Literal["registered-camera-corridor"] = "registered-camera-corridor"
    maximum_supported_lateral_offset_m: float = Field(gt=0.0)
    maximum_supported_vertical_offset_m: float = Field(gt=0.0)
    maximum_supported_heading_difference_deg: float = Field(gt=0.0, le=90.0)


class WorldProvenance(StrictModel):
    appearance: Literal["observed-reconstruction"] = "observed-reconstruction"
    road_topology: Literal["inferred-from-camera-path", "imported-opendrive"]
    scale: Literal["inferred", "measured"]
    generated_content: tuple[str, ...] = ()
    camera_height_above_road_m: float | None = Field(default=None, ge=0.5, le=3.0)
    camera_height_source: Literal["explicit-inferred-capture-rig-prior"] | None = None
    road_endpoint_padding_m: float | None = Field(default=None, ge=3.0, le=20.0)


class WorldValidation(StrictModel):
    structurally_valid: bool
    carla_validated: bool
    ready_for_carla: bool
    validated_at: datetime
    validator_version: str
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def readiness_truth(self) -> "WorldValidation":
        if self.ready_for_carla and not (self.structurally_valid and self.carla_validated):
            raise ValueError("ready_for_carla requires structural and CARLA validation")
        return self


class ExecutableWorldDescriptor(StrictModel):
    schema_name: Literal["servo.world-execution/v1"] = "servo.world-execution/v1"
    world_id: str = Field(min_length=1, max_length=160)
    appearance: AppearanceDescriptor
    structure: StructureDescriptor
    scale: ScaleDescriptor
    frames: FrameTransformDescriptor
    routes: tuple[RouteDescriptor, ...] = Field(min_length=1)
    capture_envelope: CaptureEnvelopeDescriptor
    provenance: WorldProvenance
    validation: WorldValidation
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class VehicleDescriptor(StrictModel):
    blueprint: Literal["vehicle.lincoln.mkz_2020"] = "vehicle.lincoln.mkz_2020"
    physics_configuration: Literal["carla-default"] = "carla-default"
    spawn_height_offset_m: float = Field(ge=0.0, le=1.0, default=0.25)


class ObservationRendererDescriptor(StrictModel):
    source: ObservationSource
    renderer_version: str = "servo-observation/v1"
    camera: CameraSensorDescriptor
    additional_cameras: tuple[CameraSensorDescriptor, ...] = Field(default=(), max_length=7)
    record_policy_frames: bool = True

    @model_validator(mode="after")
    def unique_rgb_cameras(self) -> "ObservationRendererDescriptor":
        cameras = (self.camera, *self.additional_cameras)
        ids = [camera.sensor_id for camera in cameras]
        if len(ids) != len(set(ids)):
            raise ValueError("observation camera sensor IDs must be unique")
        if any(camera.kind != "rgb" for camera in cameras):
            raise ValueError("policy observation cameras must be RGB; hybrid depth/instance sensors are worker-owned")
        return self


class ControllerDescriptor(StrictModel):
    kind: Literal["direct", "pure-pursuit-pid"]
    version: str = "servo-controller/v1"


class TimingDescriptor(StrictModel):
    fixed_delta_seconds: float = Field(gt=0.0, le=0.1, default=0.05)
    policy_hz: int = Field(ge=1, le=100, default=10)
    sensor_hz: int = Field(ge=1, le=100, default=10)
    # Large local multimodal planners may run slower than wall-clock while the
    # authoritative CARLA world is paused in synchronous mode.
    policy_deadline_ms: float = Field(gt=0.0, le=30000.0, default=80.0)

    @model_validator(mode="after")
    def rates_align(self) -> "TimingDescriptor":
        physics_hz = 1.0 / self.fixed_delta_seconds
        for name, rate in (("policy_hz", self.policy_hz), ("sensor_hz", self.sensor_hz)):
            ratio = physics_hz / rate
            if abs(ratio - round(ratio)) > 1e-6:
                raise ValueError(f"{name} must divide the physics rate exactly")
        return self


class ScenarioDescriptor(StrictModel):
    seed: int
    maximum_duration_s: float = Field(gt=0.0, le=3600.0, default=60.0)
    # Snow is a deterministic simulation condition: CARLA receives reduced
    # tyre friction and the Gaussian renderer deposits visual snow only on
    # inferred up-facing surfaces.  It is explicitly not represented as a
    # qualified ClimateNeRF sensor product or observed geometry.
    weather: Literal["clear", "snow"] = "clear"
    snow_accumulation: float = Field(ge=0.0, le=1.0, default=0.90)
    dynamic_actor_profile: Literal["none", "one-pedestrian", "one-lead-vehicle"] = "none"


class RecordingDescriptor(StrictModel):
    save_policy_frames: bool = True
    save_every_nth_frame: int = Field(ge=1, le=100, default=2)
    encode_preview_video: bool = True
    maximum_saved_frames: int = Field(ge=1, le=10000, default=1200)
    # Roadside VLM analysis is a separate evidence pass. Keeping it opt-in
    # prevents a completed physical drive from blocking on a second large
    # model (often CPU-bound on the 12 GB development laptop).
    run_roadside_detection: bool = False


class SimulationCreateRequest(StrictModel):
    campaign_id: str | None = Field(default=None, pattern=r"^cam-[0-9a-f]{16}$")
    world_execution_manifest: str
    route_id: str = "primary"
    vehicle: VehicleDescriptor = Field(default_factory=VehicleDescriptor)
    policy: DrivingPolicyDescriptor
    observation: ObservationRendererDescriptor
    scenario: ScenarioDescriptor
    timing: TimingDescriptor = Field(default_factory=TimingDescriptor)
    recording: RecordingDescriptor = Field(default_factory=RecordingDescriptor)
    resource_profile: Literal["balanced", "carla-visual", "hybrid"] = "balanced"


class SimulationSessionManifest(StrictModel):
    schema_name: Literal["servo.simulation-session/v1"] = "servo.simulation-session/v1"
    session_id: str = Field(pattern=r"^sim-[0-9a-f]{16}$")
    campaign_id: str | None = None
    backend: Literal[SimulationBackendKind.CARLA] = SimulationBackendKind.CARLA
    backend_version: Literal["0.9.16"] = "0.9.16"
    runtime: CarlaRuntimeDescriptor
    executable_world: ExecutableWorldDescriptor
    executable_world_manifest_uri: str
    route_id: str
    vehicle: VehicleDescriptor
    sensors: tuple[CameraSensorDescriptor, ...]
    policy: DrivingPolicyDescriptor
    observation: ObservationRendererDescriptor
    controller: ControllerDescriptor
    scenario: ScenarioDescriptor
    timing: TimingDescriptor
    recording: RecordingDescriptor
    resource_profile: Literal["balanced", "carla-visual", "hybrid"]
    termination_rules: tuple[str, ...]
    created_at: datetime
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ProcessHealth(StrictModel):
    worker_pid: int | None = Field(default=None, ge=1)
    worker_alive: bool = False
    carla_server_pid: int | None = Field(default=None, ge=1)
    carla_server_alive: bool = False
    heartbeat_age_s: float | None = Field(default=None, ge=0.0)


class SimulationLiveState(StrictModel):
    schema_name: Literal["servo.simulation-live-state/v1"] = "servo.simulation-live-state/v1"
    sequence: int = Field(ge=0)
    session_id: str = Field(pattern=r"^sim-[0-9a-f]{16}$")
    session_state: SimulationSessionState
    authoritative_frame: int = Field(ge=0)
    simulation_time_s: float = Field(ge=0.0)
    wall_clock_updated_at: datetime
    ego_pose_carla: Pose
    ego_pose_servo: Pose
    policy_camera_pose_servo: Pose
    speed_mps: float = Field(ge=0.0)
    acceleration_mps2: float
    steering: float = Field(ge=-1.0, le=1.0)
    throttle: float = Field(ge=0.0, le=1.0)
    brake: float = Field(ge=0.0, le=1.0)
    gear: int
    target_speed_mps: float = Field(ge=0.0)
    route_completion: float = Field(ge=0.0, le=1.0)
    lateral_error_m: float = Field(ge=0.0)
    renderer_coverage: float = Field(ge=0.0, le=1.0)
    policy_latency_ms: float = Field(ge=0.0)
    policy_frame_id: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    lane_invasion_count: int = Field(ge=0)
    deadline_miss_count: int = Field(ge=0)
    current_result: DrivingOutcome | None = None
    last_failure: str = ""
    process_health: ProcessHealth = Field(default_factory=ProcessHealth)


class SimulationTickRecord(StrictModel):
    schema_name: Literal["servo.simulation-tick/v1"] = "servo.simulation-tick/v1"
    frame_id: int = Field(ge=0)
    simulation_time_s: float = Field(ge=0.0)
    observation_frame_id: int = Field(ge=0)
    applied_action_id: str
    live: SimulationLiveState
