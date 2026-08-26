"""Causal diagnosis contracts.

Gemini (or the deterministic fallback) may only PROPOSE hypotheses.  A root
cause becomes ESTABLISHED exclusively through the deterministic causal gate
evaluating real counterfactual outcomes.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import RealityCIRecord


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNTESTED = "untested"


class HypothesisKind(str, Enum):
    NOT_DETECTED = "not_detected"
    DETECTED_TOO_LATE = "detected_too_late"
    PLANNER_FAILED = "planner_failed"
    CONTROLLER_FAILED = "controller_failed"
    OCCLUSION_CAUSED_PERCEPTION_FAILURE = "occlusion_caused_perception_failure"


class CausalHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hypothesis_id: str = Field(pattern=r"^H[0-9]+$")
    kind: HypothesisKind
    claim: str = Field(min_length=1)
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    supporting_evidence: tuple[str, ...] = ()
    contradicting_evidence: tuple[str, ...] = ()


class InterventionName(str, Enum):
    REMOVE_OCCLUDER = "remove_occluder"
    REVEAL_PEDESTRIAN_EARLIER = "reveal_pedestrian_earlier"
    ORACLE_PERCEPTION = "oracle_perception"
    ORACLE_PLANNER = "oracle_planner"
    ORACLE_CONTROLLER = "oracle_controller"
    VARY_EGO_SPEED = "vary_ego_speed"
    VARY_PEDESTRIAN_SPEED = "vary_pedestrian_speed"


class ExperimentStatus(str, Enum):
    REQUESTED = "requested"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExperimentOutcome(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    INVALID = "invalid"


class CounterfactualExperiment(RealityCIRecord):
    schema_name: str = "servo.realityci.counterfactual-experiment/v1"
    record_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    failure_record_id: str
    intervention: InterventionName
    parameters: dict[str, float] = Field(default_factory=dict)
    parent_scenario_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    derived_scenario_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    derived_scenario_id: str
    status: ExperimentStatus
    outcome: Optional[ExperimentOutcome] = None
    run_evidence_id: Optional[str] = None
    hypothesis_ids: tuple[str, ...] = ()
    cost_estimate_seconds: float = Field(ge=0.0)


class DiagnosisStatus(str, Enum):
    PROPOSED = "proposed"
    ESTABLISHED = "established"
    INCONCLUSIVE = "inconclusive"


class EstablishedPattern(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    satisfied_predicates: tuple[str, ...]


class CausalDiagnosis(RealityCIRecord):
    schema_name: str = "servo.realityci.causal-diagnosis/v1"
    record_id: str = Field(pattern=r"^diag-[0-9a-f]{16}$")
    failure_record_id: str
    capability_id: str
    hypotheses: tuple[CausalHypothesis, ...]
    experiment_ids: tuple[str, ...]
    status: DiagnosisStatus
    root_cause_kind: Optional[HypothesisKind] = None
    established_by: Optional[EstablishedPattern] = None
    summary: str = ""
    diagnostician: str
    prompt_template_version: Optional[str] = None
    model_id: Optional[str] = None
    response_sha256: Optional[str] = None
