from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tools.realityci.hashing import idempotency_key, new_record_id, payload_hash
from tools.realityci.schemas import (
    Campaign,
    CampaignConfig,
    CampaignObjective,
    CampaignWorld,
    CausalDiagnosis,
    CausalHypothesis,
    CheckpointArtifact,
    DomainEvent,
    EventType,
    FailureClass,
    FailureRecord,
    FailureSeverity,
    HiddenExam,
    HypothesisKind,
    PolicyAdapterKind,
    PolicyDescriptor,
    RunEvidence,
    RunEvidenceBody,
    RunMetrics,
    RunResult,
    ScenarioManifest,
    ScenarioOutcomeCounts,
)
from tools.realityci.schemas.base import derived, verify_seal
from tools.realityci.schemas.scenario import EgoSpec

FIXED_TIME = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


def make_scenario(**overrides: object) -> ScenarioManifest:
    fields = dict(
        schema_name="servo.realityci.scenario/v1",
        record_id=new_record_id("scn"),
        created_at=FIXED_TIME,
        scenario_id="occ-ped-0001",
        seed=42,
        world_ref={"world_id": "yosemite-r7", "source_tag": "observed"},
        route={"start_s_m": 12.0, "end_s_m": 58.0, "speed_limit_mps": 15.0},
        ego={
            "initial_speed_mps": 13.4,
            "max_braking_mps2": 6.5,
            "brake_actuation_delay_s": 0.18,
            "lane_width_m": 3.5,
        },
        pedestrian={
            "crossing_speed_mps": 1.6,
            "emergence_s": 0.4,
            "crossing_angle_deg": 87.0,
            "start_lateral_m": -2.2,
            "end_lateral_m": 2.5,
        },
        occluder={"position_s_m": 41.5, "lateral_offset_m": 2.1},
        appearance={"brightness": 1.0, "contrast": 1.0, "weather_tag": "clear"},
        provenance={
            "background": "observed-gaussian-source-frames",
            "actors": "synthetic-controllable",
            "collision_truth": "deterministic-scenario-state",
        },
        horizon_s=10.0,
    )
    fields.update(overrides)
    return ScenarioManifest.model_validate(fields)


def make_campaign() -> Campaign:
    policy = PolicyDescriptor(
        adapter=PolicyAdapterKind.TORCH_OCCLUSION_PERCEPTION,
        checkpoint_uri="checkpoints/baseline.pt",
        checkpoint_sha256="sha256:" + "b" * 64,
        supports_training=True,
        trainable_adapter="torch-behavior-cloning",
    )
    return Campaign(
        record_id=new_record_id("cam"),
        created_at=FIXED_TIME,
        campaign_id=new_record_id("cam"),
        objective=CampaignObjective(capability_taxonomy_id="occluded-pedestrian-crossing/v1"),
        world=CampaignWorld(world_id="yosemite-r7", source_tag="observed"),
        baseline_policy=policy,
        config=CampaignConfig(
            training_seed_pool_size=240,
            hidden_exam_size=60,
            protected_suite_size=40,
            promotion_target_success_rate=0.9,
            promotion_min_lower_bound=0.8,
            promotion_max_regression_pp=3.0,
        ),
    )


def make_event() -> DomainEvent:
    payload = {"failure_class": "collision_with_pedestrian", "severity": 3}
    return DomainEvent(
        record_id=new_record_id("evt"),
        sequence=1,
        created_at=FIXED_TIME,
        event_type=EventType.FAILURE_DETECTED,
        idempotency_key=idempotency_key("evt", "one"),
        payload=payload,
        payload_hash=payload_hash(payload),
    ).sealed()


def test_scenario_roundtrip_and_seal() -> None:
    sealed = make_scenario().sealed()
    verify_seal(sealed)
    restored = ScenarioManifest.model_validate_json(sealed.model_dump_json())
    assert restored == sealed
    assert restored.compute_content_hash() == sealed.compute_content_hash()
    assert ScenarioManifest.model_validate_json(restored.model_dump_json()) == restored


def test_campaign_roundtrip_and_seal() -> None:
    sealed = make_campaign().sealed()
    verify_seal(sealed)
    restored = Campaign.model_validate_json(sealed.model_dump_json())
    assert restored == sealed


def test_records_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_scenario(totally_unknown_field=True)
    with pytest.raises(ValidationError):
        EgoSpec(initial_speed_mps=10.0, bogus_knob=1)


def test_scenario_rejects_bad_physics() -> None:
    with pytest.raises(ValidationError):
        make_scenario(
            pedestrian={
                "crossing_speed_mps": 1.6,
                "emergence_s": 0.4,
                "crossing_angle_deg": 87.0,
                "start_lateral_m": 1.0,
                "end_lateral_m": 1.0,
            }
        )
    with pytest.raises(ValidationError):
        make_scenario(route={"start_s_m": 50.0, "end_s_m": 20.0, "speed_limit_mps": 15.0})
    with pytest.raises(ValidationError):
        make_scenario(occluder={"position_s_m": 500.0, "lateral_offset_m": 2.1})


def test_seal_detects_tampering() -> None:
    sealed = make_scenario().sealed()
    verify_seal(sealed)
    tampered = sealed.model_copy(update={"seed": 43})
    from tools.realityci.hashing import HashMismatch

    with pytest.raises(HashMismatch):
        verify_seal(tampered)
    with pytest.raises(ValueError):
        sealed.sealed()


def test_domain_event_payload_hash_covers_payload() -> None:
    event = make_event()
    verify_seal(event)
    tampered_payload = dict(event.payload)
    tampered_payload["severity"] = 1
    rebuilt = event.model_copy(update={"payload": tampered_payload})
    assert rebuilt.payload_hash != payload_hash(rebuilt.payload)


def test_run_evidence_and_failure_records() -> None:
    run_id = new_record_id("run")
    evidence_body = RunEvidenceBody(
        scenario_id="occ-ped-0001",
        scenario_hash="sha256:" + "a" * 64,
        policy_checkpoint_sha256="sha256:" + "b" * 64,
        seed=42,
        result=RunResult.COLLISION,
        metrics=RunMetrics(
            duration_s=4.82,
            distance_travelled_m=61.7,
            min_ego_speed_mps=8.9,
            final_ego_speed_mps=0.0,
            brake_requested=True,
            min_pedestrian_distance_m=0.0,
        ),
        first_ground_truth_visibility_s=3.21,
        first_policy_detection_s=3.93,
        detection_delay_s=0.72,
        brake_command_s=4.06,
        collision_s=4.82,
        collision_relative_speed_mps=9.3,
    )
    evidence = RunEvidence(
        record_id=run_id,
        run_id=run_id,
        created_at=FIXED_TIME,
        body=evidence_body,
    ).sealed()
    verify_seal(evidence)

    failure = FailureRecord(
        record_id=new_record_id("fail"),
        failure_id=new_record_id("fail"),
        created_at=FIXED_TIME,
        run_evidence_id=evidence.record_id,
        scenario_hash=evidence.body.scenario_hash,
        policy_checkpoint_sha256=evidence.body.policy_checkpoint_sha256,
        failure_class=FailureClass.COLLISION_WITH_PEDESTRIAN,
        severity=FailureSeverity.SAFETY_CRITICAL,
        evaluator_version="deterministic-evaluators/v1",
    ).sealed()
    verify_seal(failure)


def test_checkpoint_lineage_rules() -> None:
    trained = CheckpointArtifact(
        record_id=new_record_id("ckp"),
        created_at=FIXED_TIME,
        checkpoint_sha256="sha256:" + "c" * 64,
        adapter="torch-occlusion-perception",
        size_bytes=1024,
        uri="artifacts/ckp.pt",
        parent_checkpoint_sha256="sha256:" + "b" * 64,
        training_job_id=new_record_id("trn"),
        load_verified=True,
        weights_differ_from_parent=True,
    )
    verify_seal(trained.sealed())
    with pytest.raises(ValidationError):
        CheckpointArtifact(
            record_id=new_record_id("ckp"),
            created_at=FIXED_TIME,
            checkpoint_sha256="sha256:" + "c" * 64,
            adapter="torch-occlusion-perception",
            size_bytes=1024,
            uri="artifacts/ckp.pt",
            training_job_id=new_record_id("trn"),
            load_verified=True,
            weights_differ_from_parent=False,
        )


def test_diagnosis_proposed_then_established_with_pattern() -> None:
    proposed = CausalDiagnosis(
        record_id=new_record_id("diag"),
        created_at=FIXED_TIME,
        failure_record_id=new_record_id("fail"),
        capability_id="occluded-pedestrian-crossing/v1",
        hypotheses=(
            CausalHypothesis(
                hypothesis_id="H1",
                kind=HypothesisKind.DETECTED_TOO_LATE,
                claim="detected late",
            ),
        ),
        experiment_ids=(new_record_id("exp"),),
        status="proposed",
        diagnostician="deterministic-diagnostician/v1",
    ).sealed()
    verify_seal(proposed)
    assert proposed.root_cause_kind is None
    established = derived(
        proposed,
        status="established",
        root_cause_kind=HypothesisKind.OCCLUSION_CAUSED_PERCEPTION_FAILURE,
        established_by={
            "rule_id": "perception_occlusion/v1",
            "satisfied_predicates": ("baseline_unsafe", "remove_occluder_safe"),
        },
    ).sealed()
    verify_seal(established)
    assert established.status.value == "established"


def test_hidden_exam_counts_consistency() -> None:
    counts = ScenarioOutcomeCounts(total=30, success=28, collision=1, near_miss=1, timeout_or_other=0)
    assert abs(counts.success_rate - 28 / 30) < 1e-12
    exam = HiddenExam(
        record_id=new_record_id("exam"),
        exam_id=new_record_id("exam"),
        created_at=FIXED_TIME,
        vault_id=new_record_id("vault"),
        scenario_count=counts.total,
        baseline={
            "checkpoint_sha256": "sha256:" + "b" * 64,
            "counts": counts.model_dump(),
            "mean_detection_delay_s": 0.71,
        },
        candidate={
            "checkpoint_sha256": "sha256:" + "c" * 64,
            "counts": {
                "total": 30,
                "success": 29,
                "collision": 0,
                "near_miss": 1,
                "timeout_or_other": 0,
            },
        },
        candidate_success_interval={"lower": 0.85, "upper": 0.99},
        isolation_receipt_sha256="sha256:" + "d" * 64,
        status="completed",
    ).sealed()
    verify_seal(exam)


def test_policy_descriptor_honesty() -> None:
    onnx = PolicyDescriptor(
        adapter=PolicyAdapterKind.ONNX_INFERENCE_ONLY,
        checkpoint_uri="models/policy.onnx",
        checkpoint_sha256="sha256:" + "e" * 64,
        supports_training=False,
        trainable_adapter=None,
    )
    assert onnx.supports_training is False
