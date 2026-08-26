"""Deterministic failure classification and durable evidence bundles.

The same evidence always yields the same failure classification.  Nothing
here consults an LLM.  Every written artifact is content-addressed and its
reference is embedded in the sealed RunEvidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from ..hashing import new_record_id, sha256_file
from ..schemas.base import utc_now
from ..scenario.runner import RunOutcome, RunnerTiming
from ..schemas.core import ArtifactKind, ArtifactRef
from ..schemas.run import (
    FailureRecord,
    FailureSeverity,
    RunEvidence,
    RunEvidenceBody,
    RunMetrics,
)
from ..schemas.scenario import ScenarioManifest
from .evaluators import classify_failure


EVALUATOR_VERSION = "deterministic-evaluators/v1"


def build_evidence_and_failure(
    manifest: ScenarioManifest,
    outcome: RunOutcome,
    policy_checkpoint_sha256: str,
    campaign_id: str | None = None,
) -> tuple[RunEvidence, FailureRecord | None]:
    detection_delay = _detection_delay(outcome)
    metrics = RunMetrics(
        duration_s=round(outcome.duration_s, 6),
        distance_travelled_m=round(outcome.distance_travelled_m, 6),
        min_ego_speed_mps=round(outcome.min_ego_speed_mps, 6),
        final_ego_speed_mps=round(outcome.final_ego_speed_mps, 6),
        brake_requested=outcome.brake_requested,
        min_pedestrian_distance_m=(
            round(outcome.min_pedestrian_distance_m, 6)
            if outcome.min_pedestrian_distance_m is not None
            else None
        ),
    )
    body = RunEvidenceBody(
        scenario_id=manifest.scenario_id,
        scenario_hash=manifest.compute_content_hash(),
        policy_checkpoint_sha256=policy_checkpoint_sha256,
        seed=manifest.seed,
        result=outcome.result,
        metrics=metrics,
        first_ground_truth_visibility_s=outcome.first_ground_truth_visibility_s,
        first_policy_detection_s=outcome.first_policy_detection_s,
        detection_delay_s=detection_delay,
        brake_command_s=outcome.brake_command_s,
        collision_s=outcome.collision_time_s,
        collision_relative_speed_mps=outcome.collision_relative_speed_mps,
        perception_confidence_at_detection=outcome.confidence_at_detection,
    )

    run_id = new_record_id("run")
    evidence = RunEvidence(
        record_id=run_id,
        run_id=run_id,
        created_at=utc_now(),
        campaign_id=campaign_id,
        body=body,
    ).sealed()

    failure_class, severity = classify_failure(
        result=outcome.result,
        detection_delay_s=detection_delay,
        planner_missed=_planner_missed_brake(manifest, outcome),
        controller_mismatch=False,
        had_pedestrian=manifest.pedestrian is not None,
    )
    failure: FailureRecord | None = None
    if failure_class is not None:
        failure_id = new_record_id("fail")
        failure = FailureRecord(
            record_id=failure_id,
            failure_id=failure_id,
            created_at=utc_now(),
            campaign_id=campaign_id,
            parent_id=evidence.record_id,
            causation_id=evidence.record_id,
            run_evidence_id=evidence.record_id,
            scenario_hash=body.scenario_hash,
            policy_checkpoint_sha256=policy_checkpoint_sha256,
            failure_class=failure_class,
            severity=severity or FailureSeverity.MINOR,
            detail=_detail_json(outcome),
            evaluator_version=EVALUATOR_VERSION,
        ).sealed()
    return evidence, failure


def _detection_delay(outcome: RunOutcome) -> float | None:
    if (
        outcome.first_policy_detection_s is None
        or outcome.first_ground_truth_visibility_s is None
    ):
        return None
    return round(outcome.first_policy_detection_s - outcome.first_ground_truth_visibility_s, 6)


def _planner_missed_brake(manifest: ScenarioManifest, outcome: RunOutcome) -> bool:
    """True iff a real hazard existed on some step but no brake was ever requested."""

    if outcome.brake_command_s is not None:
        return False
    if manifest.pedestrian is None:
        return False

    from ..trainers.dataset import hazard_label

    timing = RunnerTiming()
    cross_s = (
        manifest.occluder.position_s_m + 6.0
        if manifest.occluder
        else (manifest.route.start_s_m + manifest.route.end_s_m) / 2.0
    )
    for row in outcome.telemetry:
        if row.time_s >= outcome.duration_s - 1e-9 or row.time_s > 8.0:
            break
        front = row.ego_s_m + manifest.ego.length_m / 2.0
        if hazard_label(
            manifest=manifest,
            elapsed_s=row.time_s,
            ego_front_s=front,
            ego_speed_mps=row.ego_speed_mps,
            cross_s=cross_s,
            visible=row.gt_visible_fraction >= timing.visibility_threshold,
        ):
            return True
    return False


def _detail_json(outcome: RunOutcome) -> str:
    return json.dumps(
        {
            "result": outcome.result.value,
            "collision_time_s": outcome.collision_time_s,
            "relative_speed_mps": outcome.collision_relative_speed_mps,
            "min_ped_distance_m": outcome.min_pedestrian_distance_m,
            "brake_command_s": outcome.brake_command_s,
            "detection_delay_s": _detection_delay(outcome),
        }
    )


def write_job_outputs(
    job_dir: Path,
    manifest: ScenarioManifest,
    outcome: RunOutcome,
    evidence: RunEvidence,
    failure: FailureRecord | None,
    save_frames: bool = False,
) -> list[ArtifactRef]:
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    resolved_job = str(job_dir.resolve())

    def contained(path: Path) -> Path:
        resolved = path.resolve()
        if not str(resolved).startswith(resolved_job):
            raise ValueError(f"artifact path escapes job directory: {path}")
        return resolved

    refs: list[ArtifactRef] = []

    scenario_path = contained(job_dir / "scenario.json")
    scenario_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    refs.append(_ref(scenario_path, ArtifactKind.MANIFEST, "scenario-manifest"))

    telemetry_path = contained(job_dir / "telemetry.jsonl")
    with telemetry_path.open("w", encoding="utf-8") as handle:
        for row in outcome.telemetry:
            handle.write(json.dumps(asdict(row), allow_nan=False) + "\n")
    refs.append(_ref(telemetry_path, ArtifactKind.TELEMETRY, "run-telemetry"))

    if save_frames and outcome.frames:
        frames_dir = contained(job_dir / "frames")
        frames_dir.mkdir(exist_ok=True)
        import cv2

        for t, frame in sorted(outcome.frames.items()):
            name = f"frame-{int(round(t * 1000)):07d}.png"
            cv2.imwrite(str(frames_dir / name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        names_payload = json.dumps(sorted(p.name for p in frames_dir.iterdir())).encode()
        refs.append(
            ArtifactRef(
                kind=ArtifactKind.FRAME,
                uri=str(frames_dir) + f"#files={len(list(frames_dir.iterdir()))}",
                sha256="sha256:" + hashlib.sha256(names_payload).hexdigest(),
                size_bytes=sum(p.stat().st_size for p in frames_dir.iterdir()),
                label="captured-frames",
            )
        )

    evidence_path = contained(job_dir / "run-evidence.json")
    evidence_path.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    refs.append(_ref(evidence_path, ArtifactKind.JSON, "run-evidence"))

    if failure is not None:
        failure_path = contained(job_dir / "failure-record.json")
        failure_path.write_text(failure.model_dump_json(indent=2), encoding="utf-8")
        refs.append(_ref(failure_path, ArtifactKind.JSON, "failure-record"))

    return refs


def _ref(path: Path, kind: ArtifactKind, label: str) -> ArtifactRef:
    return ArtifactRef(
        kind=kind,
        uri=str(path),
        sha256=sha256_file(str(path)),
        size_bytes=path.stat().st_size,
        label=label,
    )
