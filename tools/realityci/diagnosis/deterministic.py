"""Deterministic rule-based diagnostician.

This is a real, auditable hypothesis generator over measured evidence
features — labeled honestly as deterministic, never presented as Gemini
output.  It exists so the durable workflow is fully provable end to end;
the Gemini implementation in gemini.py slots into the same interface.
"""

from __future__ import annotations

from ..schemas.diagnosis import (
    CausalHypothesis,
    HypothesisKind,
    InterventionName,
)
from ..schemas.run import FailureClass, FailureRecord, RunEvidence
from .base import DiagnosisContext, DiagnosisProposal, Diagnostician, ExperimentRequest


DETERMINISTIC_DIAGNOSTICIAN_NAME = "deterministic-diagnostician/v1"


class DeterministicDiagnostician(Diagnostician):
    @property
    def name(self) -> str:
        return DETERMINISTIC_DIAGNOSTICIAN_NAME

    def propose(
        self,
        evidence: RunEvidence,
        failure: FailureRecord,
        context: DiagnosisContext,
    ) -> DiagnosisProposal:
        hypotheses: list[CausalHypothesis] = [
            CausalHypothesis(
                hypothesis_id="H1",
                kind=HypothesisKind.NOT_DETECTED,
                claim="The policy never raised hazard above threshold before impact.",
            ),
            CausalHypothesis(
                hypothesis_id="H2",
                kind=HypothesisKind.DETECTED_TOO_LATE,
                claim="Detection occurred later than the physics allows for stopping.",
            ),
            CausalHypothesis(
                hypothesis_id="H3",
                kind=HypothesisKind.PLANNER_FAILED,
                claim="Perception fired but no brake command was issued.",
            ),
            CausalHypothesis(
                hypothesis_id="H4",
                kind=HypothesisKind.CONTROLLER_FAILED,
                claim="A brake command was issued but actuation failed to engage.",
            ),
        ]
        occluded = "occluded" in context.scenario_summary or failure.failure_class in (
            FailureClass.COLLISION_WITH_PEDESTRIAN,
            FailureClass.LATE_DETECTION,
        )
        if occluded:
            hypotheses.append(
                CausalHypothesis(
                    hypothesis_id="H5",
                    kind=HypothesisKind.OCCLUSION_CAUSED_PERCEPTION_FAILURE,
                    claim="Partial occlusion delayed perception beyond the stoppable window.",
                )
            )

        requested: list[ExperimentRequest] = [
            ExperimentRequest(
                intervention=InterventionName.REMOVE_OCCLUDER,
                parameters={},
                hypothesis_ids=("H5",),
                estimated_cost_seconds=6.0,
            ),
            ExperimentRequest(
                intervention=InterventionName.ORACLE_PERCEPTION,
                parameters={},
                hypothesis_ids=("H1", "H2", "H5"),
                estimated_cost_seconds=6.0,
            ),
            ExperimentRequest(
                intervention=InterventionName.ORACLE_PLANNER,
                parameters={},
                hypothesis_ids=("H3", "H5"),
                estimated_cost_seconds=6.0,
            ),
            ExperimentRequest(
                intervention=InterventionName.REVEAL_PEDESTRIAN_EARLIER,
                parameters={"delta_seconds": 1.2},
                hypothesis_ids=("H2", "H5"),
                estimated_cost_seconds=6.0,
            ),
        ]
        allowed = set(context.available_interventions)
        requested = [r for r in requested if r.intervention in allowed]

        summary = (
            f"Failure {failure.failure_class.value} at t={evidence.body.collision_s}s; "
            f"detection delay {evidence.body.detection_delay_s}s. "
            "Requesting discriminating counterfactuals."
        )
        return DiagnosisProposal(
            hypotheses=tuple(hypotheses),
            requested_experiments=tuple(requested),
            summary=summary,
            diagnostician=self.name,
        )
