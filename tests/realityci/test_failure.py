from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.realityci.failure import (
    build_evidence_and_failure,
    classify_failure,
    write_job_outputs,
)
from tools.realityci.failure.evaluators import LATE_DETECTION_THRESHOLD_S
from tools.realityci.policy.base import SensorPacket
from tools.realityci.scenario.runner import OracleConfig, ScenarioRunner
from tools.realityci.schemas.base import verify_seal
from tools.realityci.schemas.core import ArtifactKind
from tools.realityci.schemas.run import (
    FailureClass,
    FailureSeverity,
    RunResult,
)

from test_runner import NeverBrake, make_manifest


BASELINE_SHA = "sha256:" + "4" * 64


def _run(manifest, oracle: OracleConfig = OracleConfig(), capture_frames: bool = False):
    runner = ScenarioRunner(manifest, NeverBrake(), oracle=oracle, capture_frames=capture_frames)
    return runner.run()


def test_collision_yields_sealed_evidence_and_critical_failure(tmp_path: Path) -> None:
    manifest = make_manifest()
    outcome = _run(manifest, capture_frames=True)
    assert outcome.result == RunResult.COLLISION

    evidence, failure = build_evidence_and_failure(manifest, outcome, BASELINE_SHA)
    verify_seal(evidence)
    assert failure is not None
    verify_seal(failure)
    assert failure.failure_class == FailureClass.COLLISION_WITH_PEDESTRIAN
    assert failure.severity == FailureSeverity.SAFETY_CRITICAL
    assert failure.run_evidence_id == evidence.record_id
    assert evidence.body.collision_s == outcome.collision_time_s
    assert evidence.body.scenario_hash == manifest.compute_content_hash()

    refs = write_job_outputs(tmp_path, manifest, outcome, evidence, failure, save_frames=True)
    assert len(refs) >= 4
    for ref in refs:
        if ref.kind == ArtifactKind.FRAME:
            continue
        assert Path(ref.uri).is_file()
        assert Path(ref.uri).stat().st_size == ref.size_bytes
    frames_dir = next(r for r in refs if r.kind == ArtifactKind.FRAME)
    assert "#files=" in frames_dir.uri


def test_success_run_has_no_failure_record(tmp_path: Path) -> None:
    manifest = make_manifest(occluder=None, pedestrian=None)
    outcome = _run(manifest)
    assert outcome.result == RunResult.SUCCESS
    evidence, failure = build_evidence_and_failure(manifest, outcome, BASELINE_SHA)
    verify_seal(evidence)
    assert failure is None
    refs = write_job_outputs(tmp_path, manifest, outcome, evidence, None)
    assert not (tmp_path / "failure-record.json").exists()
    assert len(refs) == 3


def test_oracle_perception_prevents_failure_record() -> None:
    manifest = make_manifest()
    outcome = _run(manifest, oracle=OracleConfig(perception=True))
    assert outcome.result in (RunResult.SUCCESS, RunResult.NEAR_MISS)
    _, failure = build_evidence_and_failure(manifest, outcome, BASELINE_SHA)
    if outcome.result == RunResult.SUCCESS:
        assert failure is None
    else:
        assert failure is not None
        assert failure.failure_class == FailureClass.LATE_DETECTION


def test_late_detection_threshold_boundary() -> None:
    at_threshold = classify_failure(
        result=RunResult.NEAR_MISS,
        detection_delay_s=LATE_DETECTION_THRESHOLD_S,
        planner_missed=False,
        controller_mismatch=False,
        had_pedestrian=True,
    )
    just_above = classify_failure(
        result=RunResult.NEAR_MISS,
        detection_delay_s=LATE_DETECTION_THRESHOLD_S + 0.001,
        planner_missed=False,
        controller_mismatch=False,
        had_pedestrian=True,
    )
    assert at_threshold == (None, None)
    assert just_above[0] == FailureClass.LATE_DETECTION


def test_timeout_classified_major() -> None:
    klass, severity = classify_failure(
        result=RunResult.TIMEOUT,
        detection_delay_s=None,
        planner_missed=False,
        controller_mismatch=False,
        had_pedestrian=True,
    )
    assert klass == FailureClass.TIMEOUT_STALL
    assert severity == FailureSeverity.MAJOR


def test_writer_rejects_escaping_paths(tmp_path: Path) -> None:
    manifest = make_manifest(pedestrian=None)
    outcome = _run(manifest)
    evidence, failure = build_evidence_and_failure(manifest, outcome, BASELINE_SHA)
    evil_dir = tmp_path / "job"
    evil_dir.mkdir()
    real_outside = tmp_path / "outside"
    real_outside.mkdir()

    original_resolve = Path.resolve

    def fake_resolve(self, strict=False):
        if self.name == "telemetry.jsonl":
            return real_outside / "telemetry.jsonl"
        return original_resolve(self, strict=strict)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(Path, "resolve", fake_resolve)
    try:
        with pytest.raises(ValueError):
            write_job_outputs(evil_dir, manifest, outcome, evidence, None)
    finally:
        monkey.undo()
    assert not (real_outside / "telemetry.jsonl").exists()


def test_telemetry_jsonl_is_valid_json_lines(tmp_path: Path) -> None:
    manifest = make_manifest()
    outcome = _run(manifest)
    evidence, failure = build_evidence_and_failure(manifest, outcome, BASELINE_SHA)
    assert failure is not None
    write_job_outputs(tmp_path, manifest, outcome, evidence, failure)
    lines = (tmp_path / "telemetry.jsonl").read_text().splitlines()
    assert len(lines) == len(outcome.telemetry)
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["time_s"] == 0.0
