"""Capability register, Reality Debt, and capture mission contracts.

Reality Debt is computed by reproducible code from severity, evidence state,
coverage gap, confidence, and freshness.  It is never an LLM score.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import RealityCIRecord


class CapabilityState(str, Enum):
    UNKNOWN = "unknown"
    UNTESTED = "untested"
    FAILED = "failed"
    DIAGNOSING = "diagnosing"
    TRAINING = "training"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REGRESSED = "regressed"
    BLOCKED_MISSING_REALITY = "blocked_missing_reality"


class CapabilityRecord(RealityCIRecord):
    schema_name: str = "servo.realityci.capability/v1"
    record_id: str = Field(pattern=r"^cap-[0-9a-f]{16}$")
    taxonomy_id: str = Field(min_length=1)
    taxonomy_version: str
    display_name: str
    importance_weight: float = Field(gt=0.0)
    state: CapabilityState
    evidence_freshness_s: float = Field(ge=0.0)
    scenario_coverage_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    protected_regression_clean: bool = True
    last_verified_checkpoint_sha256: Optional[str] = None
    latest_failure_record_id: Optional[str] = None
    latest_diagnosis_id: Optional[str] = None
    missing_reality_requirement: Optional[str] = None


class DebtFormula(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_version: str
    description: str


class CapabilityDebtContribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    taxonomy_id: str
    contribution: float = Field(ge=0.0)


class RealityDebtSnapshot(RealityCIRecord):
    schema_name: str = "servo.realityci.reality-debt/v1"
    record_id: str = Field(pattern=r"^debt-[0-9a-f]{16}$")
    total_debt: float = Field(ge=0.0)
    formula: DebtFormula
    contributions: tuple[CapabilityDebtContribution, ...]


class CaptureMission(RealityCIRecord):
    schema_name: str = "servo.realityci.capture-mission/v1"
    record_id: str = Field(pattern=r"^miss-[0-9a-f]{16}$")
    capability_id: str
    reason: str
    environment: str
    actors: str
    sensor_placement: str
    motion_profile: str
    duration_minutes: tuple[int, int]
    minimum_samples: int = Field(gt=0)
    acceptance_checks: tuple[str, ...]
    privacy_constraints: tuple[str, ...]
