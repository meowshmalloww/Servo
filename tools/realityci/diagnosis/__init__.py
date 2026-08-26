"""Diagnosis: hypothesis proposal, counterfactual execution, causal gating."""

from __future__ import annotations

from .base import DiagnosisProposal, Diagnostician
from .deterministic import DETERMINISTIC_DIAGNOSTICIAN_NAME, DeterministicDiagnostician
from .experiments import (
    EXPERIMENT_ENGINE_VERSION,
    CounterfactualEngine,
    InterventionApplier,
    apply_intervention,
)
from .causal_gate import (
    CAUSAL_GATE_VERSION,
    RULE_OCCLUDED_LATE_PERCEPTION,
    RULE_PLANNER_THRESHOLD_DEFICIENCY,
    RULE_LATE_PERCEPTION_GENERAL,
    CausalGateResult,
    evaluate_causal_gate,
)

__all__ = [
    "DiagnosisProposal",
    "Diagnostician",
    "DETERMINISTIC_DIAGNOSTICIAN_NAME",
    "DeterministicDiagnostician",
    "EXPERIMENT_ENGINE_VERSION",
    "CounterfactualEngine",
    "InterventionApplier",
    "apply_intervention",
    "CAUSAL_GATE_VERSION",
    "RULE_OCCLUDED_LATE_PERCEPTION",
    "RULE_PLANNER_THRESHOLD_DEFICIENCY",
    "CausalGateResult",
    "evaluate_causal_gate",
]
