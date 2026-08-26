"""Core event and artifact contracts.

DomainEvents form the per-campaign append-only history.  Each event carries a
monotonic sequence number, an idempotency key, a payload hash, and causal
links so that duplicate deliveries and replays are detectable.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import RealityCIRecord


class EventType(str, Enum):
    CAMPAIGN_CREATED = "CAMPAIGN_CREATED"
    BASELINE_RUN_REQUESTED = "BASELINE_RUN_REQUESTED"
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    FAILURE_DETECTED = "FAILURE_DETECTED"
    NO_FAILURE_FOUND = "NO_FAILURE_FOUND"
    DIAGNOSIS_REQUESTED = "DIAGNOSIS_REQUESTED"
    HYPOTHESES_PROPOSED = "HYPOTHESES_PROPOSED"
    EXPERIMENT_BATCH_REQUESTED = "EXPERIMENT_BATCH_REQUESTED"
    EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
    ROOT_CAUSE_ESTABLISHED = "ROOT_CAUSE_ESTABLISHED"
    ROOT_CAUSE_INCONCLUSIVE = "ROOT_CAUSE_INCONCLUSIVE"
    CURRICULUM_CREATED = "CURRICULUM_CREATED"
    HIDDEN_SEEDS_SEALED = "HIDDEN_SEEDS_SEALED"
    TRAINING_REQUESTED = "TRAINING_REQUESTED"
    TRAINING_STARTED = "TRAINING_STARTED"
    TRAINING_FAILED = "TRAINING_FAILED"
    CHECKPOINT_READY = "CHECKPOINT_READY"
    HIDDEN_EXAM_REQUESTED = "HIDDEN_EXAM_REQUESTED"
    HIDDEN_EXAM_COMPLETED = "HIDDEN_EXAM_COMPLETED"
    REGRESSION_REQUESTED = "REGRESSION_REQUESTED"
    REGRESSION_COMPLETED = "REGRESSION_COMPLETED"
    CHECKPOINT_PROMOTED = "CHECKPOINT_PROMOTED"
    CHECKPOINT_REJECTED = "CHECKPOINT_REJECTED"
    CAPABILITY_UPDATED = "CAPABILITY_UPDATED"
    REALITY_DEBT_UPDATED = "REALITY_DEBT_UPDATED"
    MISSING_REALITY_DETECTED = "MISSING_REALITY_DETECTED"
    CAPTURE_MISSION_CREATED = "CAPTURE_MISSION_CREATED"
    NEXT_WEAKNESS_SELECTED = "NEXT_WEAKNESS_SELECTED"
    CAMPAIGN_CANCELLED = "CAMPAIGN_CANCELLED"
    CAMPAIGN_FAILED = "CAMPAIGN_FAILED"
    CAMPAIGN_COMPLETED = "CAMPAIGN_COMPLETED"


class ArtifactKind(str, Enum):
    JSON = "json"
    FRAME = "frame"
    VIDEO = "video"
    TELEMETRY = "telemetry"
    CHECKPOINT = "checkpoint"
    MANIFEST = "manifest"
    REPORT = "report"


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ArtifactKind
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    label: str = ""


class DomainEvent(RealityCIRecord):
    schema_name: str = "servo.realityci.domain-event/v1"
    record_id: str = Field(pattern=r"^evt-[0-9a-f]{16}$")
    sequence: int = Field(ge=1)
    event_type: EventType
    idempotency_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    parent_event_id: Optional[str] = None
    artifact_refs: tuple[ArtifactRef, ...] = ()

    @field_validator("payload")
    @classmethod
    def _reject_non_finite(cls, value: dict[str, Any]) -> dict[str, Any]:
        from ..hashing import CanonicalizationError, canonical_json_bytes

        try:
            canonical_json_bytes(value)
        except CanonicalizationError as exc:
            raise ValueError(f"event payload must be canonically serializable: {exc}") from exc
        return value
