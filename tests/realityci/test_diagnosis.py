from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.realityci.diagnosis.base import ExperimentRequest
from tools.realityci.diagnosis.causal_gate import (
    GateArmOutcomes,
    evaluate_causal_gate,
)
from tools.realityci.diagnosis.deterministic import DeterministicDiagnostician
from tools.realityci.diagnosis.experiments import CounterfactualEngine, apply_intervention
from tools.realityci.diagnosis.gemini import (
    GeminiDiagnostician,
    UnsupportedInterventionError,
)
from tools.realityci.diagnosis.base import DiagnosisContext
from tools.realityci.failure import build_evidence_and_failure
from tools.realityci.pools import build_occluded_pool
from tools.realityci.policy.torch_perception import TorchOcclusionPerceptionAdapter
from tools.realityci.scenario.runner import OracleConfig, RunResult, ScenarioRunner
from tools.realityci.schemas.diagnosis import (
    DiagnosisStatus,
    ExperimentOutcome,
    HypothesisKind,
    InterventionName,
)
from tools.realityci.schemas.base import verify_seal

from test_runner import make_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "demo" / "occluded_pedestrian" / "baseline" / "baseline.pt"
requires_baseline = pytest.mark.skipif(
    not BASELINE.is_file(), reason="trained baseline checkpoint not present"
)


def test_intervention_derivations_are_immutable_and_recorded() -> None:
    parent = make_manifest()
    parent_hash = parent.compute_content_hash()

    derived = apply_intervention(parent, InterventionName.REMOVE_OCCLUDER, {})
    assert derived.occluder is None
    assert parent.occluder is not None
    assert derived.compute_content_hash() != parent_hash
    assert derived.derivation is not None
    assert derived.derivation.intervention == "remove_occluder"
    assert derived.parent_id == parent.record_id

    shifted = apply_intervention(
        parent, InterventionName.REVEAL_PEDESTRIAN_EARLIER, {"delta_seconds": 0.3}
    )
    assert shifted.pedestrian.emergence_s == pytest.approx(
        parent.pedestrian.emergence_s - 0.3, abs=1e-9
    )

    clamped = apply_intervention(
        parent, InterventionName.REVEAL_PEDESTRIAN_EARLIER, {"delta_seconds": 0.8}
    )
    assert clamped.pedestrian.emergence_s == 0.0

    with pytest.raises(ValueError):
        apply_intervention(parent, InterventionName.REVEAL_PEDESTRIAN_EARLIER, {"delta_seconds": 9.0})
    with pytest.raises(ValueError):
        apply_intervention(parent, InterventionName.VARY_EGO_SPEED, {"speed_mps": 0.5})


def test_engine_derives_deterministic_scenario_hashes() -> None:
    parent = make_manifest()
    engine = CounterfactualEngine(seeds_per_arm=2)
    request = ExperimentRequest(
        intervention=InterventionName.REMOVE_OCCLUDER,
        parameters={},
        hypothesis_ids=("H5",),
    )

    class NullPolicy:
        def reset(self, seed): ...
        def observe(self, packet): return 0.0

    first = engine.execute_request(parent, request, NullPolicy(), "fail-x")
    second = engine.execute_request(parent, request, NullPolicy(), "fail-x")

    hashes_a = [r.derived_scenario.compute_content_hash() for r in first]
    hashes_b = [r.derived_scenario.compute_content_hash() for r in second]
    assert hashes_a == hashes_b
    assert all(r.outcome == ExperimentOutcome.UNSAFE for r in first)


@requires_baseline
def test_full_causal_investigation_establishes_occlusion_root_cause() -> None:
    pool = build_occluded_pool(8_800_000, 16)
    policy = TorchOcclusionPerceptionAdapter(BASELINE)

    showcase = None
    for manifest in pool:
        outcome = ScenarioRunner(manifest, policy).run()
        if outcome.result == RunResult.COLLISION:
            showcase = manifest
            break
    assert showcase is not None, "expected at least one colliding occluded scenario"

    baseline_outcome = ScenarioRunner(showcase, policy).run()
    evidence, failure = build_evidence_and_failure(showcase, baseline_outcome, policy.descriptor.checkpoint_sha256)
    assert failure is not None

    proposal = DeterministicDiagnostician().propose(
        evidence, failure, DiagnosisContext(scenario_summary="occluded emergence")
    )
    assert any(h.kind == HypothesisKind.OCCLUSION_CAUSED_PERCEPTION_FAILURE for h in proposal.hypotheses)

    engine = CounterfactualEngine(seeds_per_arm=3)
    arms: dict[str, list[ExperimentOutcome]] = {
        "remove_occluder": [],
        "reveal_earlier": [],
        "oracle_perception": [],
        "oracle_planner": [],
    }
    experiment_ids: list[str] = []
    for request in proposal.requested_experiments:
        results = engine.execute_request(showcase, request, policy, failure.record_id)
        key = {
            InterventionName.REMOVE_OCCLUDER: "remove_occluder",
            InterventionName.ORACLE_PERCEPTION: "oracle_perception",
            InterventionName.ORACLE_PLANNER: "oracle_planner",
            InterventionName.REVEAL_PEDESTRIAN_EARLIER: "reveal_earlier",
        }[request.intervention]
        for r in results:
            verify_seal(r.experiment_record)
            arms[key].append(r.outcome)
            experiment_ids.append(r.experiment_record.record_id)

    gate, diagnosis = evaluate_causal_gate(
        arms=GateArmOutcomes(
            baseline=ExperimentOutcome.UNSAFE,
            remove_occluder=tuple(arms["remove_occluder"]),
            reveal_earlier=tuple(arms["reveal_earlier"]),
            oracle_perception=tuple(arms["oracle_perception"]),
            oracle_planner=tuple(arms["oracle_planner"]),
        ),
        total_seeds_per_arm=3,
        failure_record_id=failure.record_id,
        capability_id="occluded-pedestrian-crossing/v1",
        hypotheses=proposal.hypotheses,
        experiment_ids=tuple(experiment_ids),
    )

    assert gate.status == DiagnosisStatus.ESTABLISHED, (
        f"gate inconclusive: satisfied={gate.satisfied} missing={gate.missing} "
        f"arms={ {k: [o.value for o in v] for k, v in arms.items()} }"
    )
    assert diagnosis is not None
    verify_seal(diagnosis)
    assert diagnosis.established_by.rule_id in (
        "occluded_late_perception/v1",
        "planner_threshold_deficiency/v1",
        "late_perception_general/v1",
    )


def test_gate_establishes_planner_deficiency_when_oracle_planner_saves() -> None:
    gate, diagnosis = evaluate_causal_gate(
        arms=GateArmOutcomes(
            baseline=ExperimentOutcome.UNSAFE,
            remove_occluder=(ExperimentOutcome.SAFE,) * 3,
            reveal_earlier=(ExperimentOutcome.SAFE,) * 3,
            oracle_perception=(ExperimentOutcome.SAFE,) * 3,
            oracle_planner=(ExperimentOutcome.SAFE,) * 3,
        ),
        total_seeds_per_arm=3,
        failure_record_id="fail-0000000000000000",
        capability_id="cap-test",
    )
    assert gate.status == DiagnosisStatus.ESTABLISHED
    assert diagnosis is not None
    assert diagnosis.root_cause_kind == HypothesisKind.PLANNER_FAILED
    assert diagnosis.established_by.rule_id == "planner_threshold_deficiency/v1"


def test_general_rule_establishes_when_occluder_removal_unsafe() -> None:
    mixed_safe = (ExperimentOutcome.SAFE, ExperimentOutcome.UNSAFE, ExperimentOutcome.INVALID)
    gate, diagnosis = evaluate_causal_gate(
        arms=GateArmOutcomes(
            baseline=ExperimentOutcome.UNSAFE,
            remove_occluder=mixed_safe,
            reveal_earlier=(ExperimentOutcome.SAFE,) * 3,
            oracle_perception=(ExperimentOutcome.SAFE,) * 3,
            oracle_planner=(ExperimentOutcome.UNSAFE,) * 3,
        ),
        total_seeds_per_arm=3,
        failure_record_id="fail-0000000000000000",
        capability_id="cap-test",
    )
    assert gate.status == DiagnosisStatus.ESTABLISHED
    assert diagnosis is not None
    assert diagnosis.established_by.rule_id == "late_perception_general/v1"
    assert diagnosis.root_cause_kind == HypothesisKind.DETECTED_TOO_LATE
    assert "remove_occluder_safe" in gate.missing


class _FakeModels:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        text = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        return type("R", (), {"text": text})()


VALID_RESPONSE = json.dumps(
    {
        "summary": "late perception under partial occlusion",
        "hypotheses": [
            {"hypothesis_id": "H1", "kind": "detected_too_late", "claim": "late"},
            {"hypothesis_id": "H2", "kind": "occlusion_caused_perception_failure", "claim": "occlusion"},
        ],
        "requested_experiments": [
            {"intervention": "remove_occluder", "parameters": {}, "hypothesis_ids": ["H2"]},
            {"intervention": "reveal_pedestrian_earlier", "parameters": {"delta_seconds": 0.8}, "hypothesis_ids": ["H2"]},
        ],
    }
)

BAD_INTERVENTION_RESPONSE = json.dumps(
    {
        "summary": "wants teleport portal",
        "hypotheses": [{"hypothesis_id": "H1", "kind": "detected_too_late", "claim": "x"}],
        "requested_experiments": [{"intervention": "open_portal", "parameters": {}}],
    }
)


def _run_gemini(responses: list[str]):
    client = type("C", (), {"models": _FakeModels(responses)})()
    diag = GeminiDiagnostician(client=client)
    return diag


def test_gemini_valid_response_converted_with_metadata() -> None:
    diag = _run_gemini([VALID_RESPONSE])
    manifest = make_manifest()
    evidence, failure = build_evidence_and_failure(manifest, ScenarioRunner(manifest, NeverProbe()).run(), "sha256:" + "4" * 64)
    proposal = diag.propose(evidence, failure, DiagnosisContext())
    from tools.realityci.diagnosis.gemini import DEFAULT_MODEL_ID

    assert proposal.model_id == DEFAULT_MODEL_ID == "gemini-3.7-flash"
    assert proposal.prompt_template_version is not None
    assert proposal.response_sha256.startswith("sha256:")
    assert len(proposal.requested_experiments) == 2


def test_gemini_rejects_unsupported_intervention_after_retry() -> None:
    client = type("C", (), {"models": _FakeModels([BAD_INTERVENTION_RESPONSE, BAD_INTERVENTION_RESPONSE])})()
    diag = GeminiDiagnostician(client=client)
    manifest = make_manifest()
    evidence, failure = build_evidence_and_failure(manifest, ScenarioRunner(manifest, NeverProbe()).run(), "sha256:" + "4" * 64)
    with pytest.raises(Exception):
        diag.propose(evidence, failure, DiagnosisContext())
    assert client.models.calls == 2


class NeverProbe:
    def reset(self, seed): ...
    def observe(self, packet):
        return 0.0
