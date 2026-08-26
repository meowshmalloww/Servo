"""Curriculum, dataset, training, and checkpoint contracts."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import RealityCIRecord
from .core import ArtifactRef


class CurriculumDimension(str, Enum):
    OCCLUSION_RATIO = "occlusion_ratio"
    EGO_SPEED = "ego_speed"
    PEDESTRIAN_SPEED = "pedestrian_speed"
    CROSSING_ANGLE = "crossing_angle"
    CONTRAST = "contrast"


class CurriculumStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_index: int = Field(ge=0)
    name: str
    difficulty: float = Field(ge=0.0, le=1.0)
    scenario_count: int = Field(gt=0)
    dimension_ranges: dict[str, tuple[float, float]]
    seed_low: int
    seed_high: int


class DatasetSplitCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    train: int = Field(ge=0)
    validation: int = Field(ge=0)


class Curriculum(RealityCIRecord):
    schema_name: str = "servo.realityci.curriculum/v1"
    record_id: str = Field(pattern=r"^curr-[0-9a-f]{16}$")
    objective_capability: str
    stages: tuple[CurriculumStage, ...]
    total_scenarios: int = Field(gt=0)
    provenance: str


class DatasetManifest(RealityCIRecord):
    schema_name: str = "servo.realityci.dataset/v1"
    record_id: str = Field(pattern=r"^ds-[0-9a-f]{16}$")
    purpose: str
    split_counts: DatasetSplitCounts
    scenario_hashes: tuple[str, ...]
    oracle_label_method: str
    seed_range_lo: int
    seed_range_hi: int

    @model_validator(mode="after")
    def _hashes_unique(self) -> "DatasetManifest":
        if len(set(self.scenario_hashes)) != len(self.scenario_hashes):
            raise ValueError("dataset manifest contains duplicate scenario hashes")
        return self


class TrainingJobStatus(str, Enum):
    REQUESTED = "requested"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrainingLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_epochs: int = Field(gt=0)
    max_wall_time_s: float = Field(gt=0.0)
    max_samples: int = Field(gt=0)
    early_stop_patience: int = Field(ge=1)


class TrainingMetricsPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    epoch: int = Field(ge=0)
    train_loss: float
    val_loss: float
    val_accuracy: float = Field(ge=0.0, le=1.0)
    learning_rate: float = Field(ge=0.0)


class TrainingJob(RealityCIRecord):
    schema_name: str = "servo.realityci.training-job/v1"
    record_id: str = Field(pattern=r"^trn-[0-9a-f]{16}$")
    job_id: str = Field(pattern=r"^trn-[0-9a-f]{16}$")
    trainer_adapter: str
    curriculum_id: str
    dataset_manifest_id: str
    dataset_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    baseline_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    limits: TrainingLimits
    hyperparameters: dict[str, float]
    status: TrainingJobStatus
    metrics_history_ref: Optional[ArtifactRef] = None
    failure_reason: Optional[str] = None


class CheckpointArtifact(RealityCIRecord):
    schema_name: str = "servo.realityci.checkpoint/v1"
    record_id: str = Field(pattern=r"^ckp-[0-9a-f]{16}$")
    checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    adapter: str
    format: str = "torch-state-dict/v1"
    size_bytes: int = Field(gt=0)
    uri: str
    parent_checkpoint_sha256: Optional[str] = None
    training_job_id: Optional[str] = None
    load_verified: bool = False
    weights_differ_from_parent: bool = False

    @model_validator(mode="after")
    def _lineage(self) -> "CheckpointArtifact":
        if self.training_job_id is not None and self.parent_checkpoint_sha256 is None:
            raise ValueError("trained checkpoint must declare its parent checkpoint")
        if self.load_verified and not self.weights_differ_from_parent and self.training_job_id is not None:
            raise ValueError("a trained candidate must differ in weights from its parent")
        return self
