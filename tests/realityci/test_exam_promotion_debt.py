from __future__ import annotations

import pytest

from tools.realityci.exam.promotion import PromotionGate, PromotionInputs
from tools.realityci.schemas.base import verify_seal
from tools.realityci.schemas.capability import CapabilityState
from tools.realityci.schemas.training import CurriculumStage
from tools.realityci.schemas.verification import (
    ArmResult,
    Decision,
    ExamStatus,
    HiddenExam,
    RegressionReport,
    ScenarioOutcomeCounts,
    SuiteComparison,
    ProtectedSuite,
    WilsonInterval,
)
from tools.realityci.curriculum.planner import CurriculumPlanner
from tools.realityci.curriculum.seed_vault import SeedVault
from tools.realityci.diagnosis.causal_gate import GateArmOutcomes, evaluate_causal_gate
from tools.realityci.schemas.diagnosis import (
    DiagnosisStatus,
    ExperimentOutcome,
)
from tools.realityci.capabilities import (
    compute_reality_debt,
    default_register,
    select_next_weakness,
)

from test_schemas import FIXED_TIME, make_campaign


def _counts(total: int, success: int) -> ScenarioOutcomeCounts:
    return ScenarioOutcomeCounts(
        total=total,
        success=success,
        collision=total - success - min(1, total - success),
        near_miss=min(1, total - success),
        timeout_or_other=0,
    )


def _exam(baseline_success: int, candidate_success: int, total: int = 10) -> HiddenExam:
    def arm(sha_tail: str, success: int) -> ArmResult:
        return ArmResult(
            checkpoint_sha256="sha256:" + sha_tail * 64,
            counts=_counts(total, success),
            mean_detection_delay_s=None,
        )

    if candidate_success == total:
        lower, upper = 0.9, 1.0
    else:
        lower, upper = 0.6, 0.95
    return HiddenExam(
        record_id="exam-" + "a" * 16,
        exam_id="exam-" + "a" * 16,
        created_at=FIXED_TIME,
        vault_id="vault-test",
        scenario_count=total,
        baseline=arm("b", baseline_success),
        candidate=arm("c", candidate_success),
        candidate_success_interval=WilsonInterval(lower=lower, upper=upper),
        isolation_receipt_sha256="sha256:" + "d" * 64,
        status=ExamStatus.COMPLETED,
    ).sealed()


def _regression(drops_pp: list[float]) -> RegressionReport:
    suites = tuple(
        SuiteComparison(
            suite=suite,
            scenario_count=5,
            baseline_success_rate=1.0,
            candidate_success_rate=max(0.0, 1.0 + drop / 100.0),
            delta_percentage_points=drop,
        )
        for suite, drop in zip(ProtectedSuite, drops_pp)
    )
    worst = min(drops_pp) if drops_pp else 0.0
    return RegressionReport(
        record_id="regr-" + "b" * 16,
        created_at=FIXED_TIME,
        candidate_checkpoint_sha256="sha256:" + "c" * 64,
        baseline_checkpoint_sha256="sha256:" + "b" * 64,
        suites=suites,
        severity_one_regressions=sum(1 for d in drops_pp if d <= -100.0),
        max_drop_percentage_points=worst,
    ).sealed()


BASE_SHA = "sha256:" + "b" * 64
CAND_SHA = "sha256:" + "c" * 64


def _inputs(exam: HiddenExam, regression: RegressionReport, **overrides) -> PromotionInputs:
    fields = dict(
        exam=exam,
        regression=regression,
        candidate_checkpoint_sha256=CAND_SHA,
        baseline_checkpoint_sha256=BASE_SHA,
        target_success_rate=0.9,
        min_lower_bound=0.5,
        max_regression_pp=3.0,
    )
    fields.update(overrides)
    return PromotionInputs(**fields)


def test_promotion_truth_table() -> None:
    gate = PromotionGate()

    promoted = gate.decide(_inputs(_exam(4, 9), _regression([0.0, 0.0, -1.0, 0.0])))
    assert promoted.decision == Decision.PROMOTED
    verify_seal(promoted)

    rejected_target = gate.decide(_inputs(_exam(4, 6), _regression([0.0])))
    assert rejected_target.decision == Decision.REJECTED
    assert any("target" in r for r in rejected_target.reasons)

    rejected_regression = gate.decide(_inputs(_exam(4, 10), _regression([0.0, -5.0, 0.0, 0.0])))
    assert rejected_regression.decision == Decision.REJECTED
    assert any("protected" in r or "drop" in r for r in rejected_regression.reasons)

    rejected_identity = gate.decide(
        _inputs(_exam(4, 9), _regression([0.0]), candidate_checkpoint_sha256="sha256:" + "f" * 64)
    )
    assert rejected_identity.decision == Decision.REJECTED
    assert any("checkpoint hash" in r for r in rejected_identity.reasons)


def test_gate_deterministic_and_llm_free() -> None:
    gate = PromotionGate()
    inputs = _inputs(_exam(4, 9), _regression([0.0]))
    one = gate.decide(inputs)
    two = gate.decide(inputs)
    assert one.checks == two.checks
    assert one.decision == two.decision


def test_vault_seal_open_and_tamper(tmp_path) -> None:
    manifests = SeedVault.build_hidden_manifests(3, 0)
    vault = SeedVault(tmp_path)
    receipt_hash = vault.seal_hidden(manifests, campaign_id=None)
    opened, receipt = vault.open_for_examiner()
    assert len(opened) == 3
    assert receipt["sealed_sha256"] == receipt_hash
    assert [m.scenario_id for m in opened] == [m.scenario_id for m in manifests]

    sealed_blob = tmp_path / "sealed-manifests.json"
    tampered = sealed_blob.read_text().replace('"seed":', '"seed": 9', 1)
    assert tampered != sealed_blob.read_text()
    sealed_blob.write_text(tampered)
    with pytest.raises(ValueError):
        vault.open_for_examiner()


def test_planner_partitions_keep_hidden_isolated(tmp_path) -> None:
    diagnosis_stub = _make_diagnosis()
    planner = CurriculumPlanner(tmp_path / "vault")
    plan = planner.plan(diagnosis_stub, training_scenario_count=8, hidden_exam_count=4)
    assert plan.curriculum.total_scenarios == 8
    training_seeds = {s.seed for s in plan.training_scenarios}
    hidden, receipt = planner._vault.open_for_examiner()
    hidden_seeds = {m.seed for m in hidden}
    assert training_seeds.isdisjoint(hidden_seeds)
    assert receipt["scenario_count"] == 4
    assert plan.dataset_manifest.split_counts.train == 8


def _make_diagnosis():
    from tools.realityci.hashing import new_record_id

    _, diagnosis = evaluate_causal_gate(
        arms=GateArmOutcomes(
            baseline=ExperimentOutcome.UNSAFE,
            remove_occluder=(ExperimentOutcome.SAFE,) * 3,
            reveal_earlier=(ExperimentOutcome.SAFE,) * 3,
            oracle_perception=(ExperimentOutcome.SAFE,) * 3,
            oracle_planner=(ExperimentOutcome.UNSAFE,) * 3,
        ),
        total_seeds_per_arm=3,
        failure_record_id=new_record_id("fail"),
        capability_id="occluded-pedestrian-crossing/v1",
    )
    assert diagnosis is not None
    return diagnosis


def test_reality_debt_decreases_after_verification() -> None:
    register = default_register()
    before = compute_reality_debt(register.all())
    decision = PromotionGate().decide(_inputs(_exam(4, 9), _regression([0.0])))
    updated = register.update_from_promotion(
        decision, "occluded-pedestrian-crossing/v1", scenario_coverage_count=6
    )
    assert updated.state == CapabilityState.VERIFIED
    after = compute_reality_debt(register.all())
    assert after.total_debt < before.total_debt

    nxt = select_next_weakness(register.all())
    assert nxt is not None
    assert nxt.taxonomy_id != "occluded-pedestrian-crossing/v1"
