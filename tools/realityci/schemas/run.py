"""Run, evidence, and failure contracts.

RunEvidence carries the synchronized measured timeline of one policy run.
FailureRecord is produced only by deterministic evaluators; it never depends
on an LLM opinion.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import RealityCIRecord
from .core import ArtifactRef


class PolicyAdapterKind(str, Enum):
    TORCH_OCCLUSION_PERCEPTION = "torch-occlusion-perception"
    ONNX_INFERENCE_ONLY = "onnx-inference-only"


class PolicyDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: PolicyAdapterKind
    checkpoint_uri: str
    checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    input_spec: str = "rgb-stack-2x96x160+ego-speed"
    supports_training: bool
    trainable_adapter: Optional[str] = None


class RunResult(str, Enum):
    SUCCESS = "success"
    NEAR_MISS = "near_miss"
    COLLISION = "collision"
    ROUTE_DEPARTURE = "route_departure"
    TIMEOUT = "timeout"


class RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_s: float = Field(ge=0.0)
    distance_travelled_m: float = Field(ge=0.0)
    min_ego_speed_mps: float = Field(ge=0.0)
    final_ego_speed_mps: float = Field(ge=0.0)
    brake_requested: bool
    min_pedestrian_distance_m: Optional[float] = None


class RunEvidenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    scenario_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    seed: int
    result: RunResult
    metrics: RunMetrics
    first_ground_truth_visibility_s: Optional[float] = None
    first_policy_detection_s: Optional[float] = None
    detection_delay_s: Optional[float] = Field(default=None, ge=0.0)
    brake_command_s: Optional[float] = None
    collision_s: Optional[float] = None
    collision_relative_speed_mps: Optional[float] = Field(default=None, ge=0.0)
    perception_confidence_at_detection: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RunEvidence(RealityCIRecord):
    schema_name: str = "servo.realityci.run-evidence/v1"
    record_id: str = Field(pattern=r"^run-[0-9a-f]{16}$")
    run_id: str = Field(pattern=r"^run-[0-9a-f]{16}$")
    body: RunEvidenceBody
    artifacts: tuple[ArtifactRef, ...] = ()


class FailureClass(str, Enum):
    COLLISION_WITH_PEDESTRIAN = "collision_with_pedestrian"
    LATE_DETECTION = "late_detection"
    PLANNER_NO_BRAKE = "planner_no_brake"
    CONTROLLER_EXECUTION_MISMATCH = "controller_execution_mismatch"
    ROUTE_DEPARTURE = "route_departure"
    TIMEOUT_STALL = "timeout_stall"


class FailureSeverity(int, Enum):
    NONE = 0
    MINOR = 1
    MAJOR = 2
    SAFETY_CRITICAL = 3


class FailureRecord(RealityCIRecord):
    schema_name: str = "servo.realityci.failure/v1"
    record_id: str = Field(pattern=r"^fail-[0-9a-f]{16}$")
    failure_id: str = Field(pattern=r"^fail-[0-9a-f]{16}$")
    run_evidence_id: str
    scenario_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    failure_class: FailureClass
    severity: FailureSeverity
    detail: str = ""
    evaluator_version: str
