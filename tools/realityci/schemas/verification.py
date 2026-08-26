"""Hidden exam, regression, and promotion contracts.

The hidden exam never stores hidden seeds here; it references the sealed
vault.  The PromotionDecision is produced by deterministic code only.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import RealityCIRecord


class ExamStatus(str, Enum):
    REQUESTED = "requested"
    COMPLETED = "completed"
    FAILED = "failed"


class ScenarioOutcomeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int = Field(gt=0)
    success: int = Field(ge=0)
    collision: int = Field(ge=0)
    near_miss: int = Field(ge=0)
    timeout_or_other: int = Field(ge=0)

    @property
    def success_rate(self) -> float:
        return self.success / self.total


class ArmResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    counts: ScenarioOutcomeCounts
    mean_detection_delay_s: Optional[float] = None


class WilsonInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)


class HiddenExam(RealityCIRecord):
    schema_name: str = "servo.realityci.hidden-exam/v1"
    record_id: str = Field(pattern=r"^exam-[0-9a-f]{16}$")
    exam_id: str = Field(pattern=r"^exam-[0-9a-f]{16}$")
    vault_id: str
    scenario_count: int = Field(gt=0)
    baseline: ArmResult
    candidate: ArmResult
    candidate_success_interval: WilsonInterval
    isolation_receipt_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: ExamStatus


class ProtectedSuite(str, Enum):
    ORDINARY_CROSSING = "ordinary_crossing"
    VISIBLE_PEDESTRIAN = "visible_pedestrian"
    NO_PEDESTRIAN = "no_pedestrian"
    BRAKING_CONTROL = "braking_control"


class SuiteComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: ProtectedSuite
    scenario_count: int = Field(gt=0)
    baseline_success_rate: float = Field(ge=0.0, le=1.0)
    candidate_success_rate: float = Field(ge=0.0, le=1.0)
    delta_percentage_points: float


class RegressionReport(RealityCIRecord):
    schema_name: str = "servo.realityci.regression-report/v1"
    record_id: str = Field(pattern=r"^regr-[0-9a-f]{16}$")
    candidate_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    baseline_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    suites: tuple[SuiteComparison, ...]
    severity_one_regressions: int = Field(ge=0)
    max_drop_percentage_points: float
    status: str = "completed"


class GateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    passed: bool
    detail: str


class Decision(str, Enum):
    PROMOTED = "promoted"
    REJECTED = "rejected"


class PromotionDecision(RealityCIRecord):
    schema_name: str = "servo.realityci.promotion-decision/v1"
    record_id: str = Field(pattern=r"^promo-[0-9a-f]{16}$")
    decision_id: str = Field(pattern=r"^promo-[0-9a-f]{16}$")
    decision: Decision
    candidate_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    baseline_checkpoint_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    checks: tuple[GateCheck, ...]
    reasons: tuple[str, ...]
    gate_version: str
