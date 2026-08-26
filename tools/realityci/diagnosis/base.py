"""Diagnostician contract.

A diagnostician may only PROPOSE hypotheses and request experiments from
the supported registry.  Root cause is established exclusively by the
deterministic causal gate over real executed outcomes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..schemas.diagnosis import CausalHypothesis, InterventionName
from ..schemas.run import FailureRecord, RunEvidence


@dataclass(frozen=True)
class ExperimentRequest:
    intervention: InterventionName
    parameters: dict[str, float] = field(default_factory=dict)
    hypothesis_ids: tuple[str, ...] = ()
    estimated_cost_seconds: float = 0.0


@dataclass(frozen=True)
class DiagnosisContext:
    scenario_summary: str = ""
    available_interventions: tuple[InterventionName, ...] = tuple(i for i in InterventionName)


@dataclass(frozen=True)
class DiagnosisProposal:
    hypotheses: tuple[CausalHypothesis, ...]
    requested_experiments: tuple[ExperimentRequest, ...]
    summary: str
    diagnostician: str
    model_id: str | None = None
    prompt_template_version: str | None = None
    response_sha256: str | None = None


class Diagnostician(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def propose(
        self,
        evidence: RunEvidence,
        failure: FailureRecord,
        context: DiagnosisContext,
    ) -> DiagnosisProposal: ...
