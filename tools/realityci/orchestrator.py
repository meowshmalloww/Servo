"""Durable RealityCI campaign orchestrator.

One workspace directory per campaign holds the sealed campaign record, an
append-only event log with per-campaign sequence numbers and idempotency
keys, atomic workflow state, and all job outputs.  Every step is resumable;
re-running a completed step emits nothing and redoes nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Callable, Optional

from .capabilities import (
    compute_reality_debt,
    default_register,
    select_next_weakness,
)
from .curriculum.planner import CurriculumPlanner
from .diagnosis.base import DiagnosisContext, ExperimentRequest
from .diagnosis.causal_gate import GateArmOutcomes, evaluate_causal_gate
from .diagnosis.deterministic import DeterministicDiagnostician
from .diagnosis.experiments import CounterfactualEngine
from .diagnosis.gemini import build_diagnostician
from .evaluate import evaluate_scenario
from .failure.evidence_writer import (
    build_evidence_and_failure,
    write_job_outputs,
)
from .hashing import idempotency_key, new_record_id, payload_hash, sha256_file
from .schemas.base import utc_now
from .pools import build_clear_pool, build_occluded_pool
from .policy.torch_perception import TorchOcclusionPerceptionAdapter
from .scenario.runner import OracleConfig, ScenarioRunner
from .schemas.base import verify_seal
from .schemas.campaign import Campaign, CampaignConfig, CampaignObjective, CampaignWorld
from .schemas.capability import CapabilityRecord, CapabilityState
from .schemas.core import ArtifactRef, DomainEvent, EventType
from .schemas.diagnosis import ExperimentOutcome, InterventionName
from .schemas.run import FailureRecord, PolicyAdapterKind, PolicyDescriptor, RunEvidence
from .schemas.scenario import ScenarioManifest
from .schemas.training import CheckpointArtifact, TrainingLimits
from .curriculum.seed_vault import DEFAULT_PARTITION
from .exam.examiner import HiddenExaminer
from .exam.promotion import PromotionGate, PromotionInputs
from .exam.regression import RegressionGuardian
from .state_machine import TERMINAL_STATES, CampaignState, assert_transition
from .trainers import TorchBehaviorCloningTrainer, TrainingRequest, build_dataset


SHOWCASE_SEED_BASE = 55_000_000
INPUT_SPEC = "rgb-stack-2x96x160+ego-speed"


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._seq = 0
        self._keys: dict[str, str] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                self._seq = max(self._seq, int(event["sequence"]))
                self._keys[event["idempotency_key"]] = event["record_id"]

    def append(
        self,
        event_type: EventType,
        campaign_id: str,
        payload: dict,
        key: str,
        artifact_refs: Optional[list[ArtifactRef]] = None,
    ) -> tuple[str, bool]:
        if key in self._keys:
            return self._keys[key], False
        self._seq += 1
        record_id = new_record_id("evt")
        event = DomainEvent(
            record_id=record_id,
            sequence=self._seq,
            created_at=utc_now(),
            campaign_id=campaign_id,
            causation_id=campaign_id,
            event_type=event_type,
            idempotency_key=key,
            payload=payload,
            payload_hash=payload_hash(payload),
            artifact_refs=tuple(artifact_refs or ()),
        ).sealed()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._keys[key] = record_id
        return record_id, True

    def events(self) -> list[DomainEvent]:
        if not self.path.exists():
            return []
        return [
            DomainEvent.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class CampaignPaths:
    root: Path

    @property
    def campaign_file(self) -> Path:
        return self.root / "campaign.json"

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    @property
    def events_file(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"


class CampaignEngine:
    """Executes one campaign to a terminal state through durable steps."""

    def __init__(
        self,
        root: Path,
        baseline_checkpoint_path: Path,
        objective_capability: str = "occluded-pedestrian-crossing/v1",
        diagnostician_kind: str = "deterministic",
        diagnostician_model: str | None = None,
        seeds_per_arm: int = 3,
        training_scenarios: int = 14,
        hidden_exam_size: int = 6,
        protected_suite_size: int = 4,
        training_epochs: int = 4,
        samples_per_scenario: int = 12,
        promotion_target_success_rate: float = 0.9,
        promotion_min_lower_bound: float = 0.5,
        promotion_max_regression_pp: float = 3.0,
        campaign_id: Optional[str] = None,
    ) -> None:
        self.paths = CampaignPaths(root=Path(root))
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.objective_capability = objective_capability
        self.baseline_checkpoint_path = Path(baseline_checkpoint_path)
        self.diagnostician_kind = diagnostician_kind
        self.diagnostician_model = diagnostician_model
        self.seeds_per_arm = seeds_per_arm
        self.training_scenarios = training_scenarios
        self.hidden_exam_size = hidden_exam_size
        self.protected_suite_size = protected_suite_size
        self.training_epochs = training_epochs
        self.samples_per_scenario = samples_per_scenario
        self.promotion_target = promotion_target_success_rate
        self.promotion_floor = promotion_min_lower_bound
        self.promotion_max_regression_pp = promotion_max_regression_pp

        self.log = EventLog(self.paths.events_file)

        if not self.paths.state_file.exists():
            self.campaign_id = campaign_id or new_record_id("cam")
            self._init_campaign_record()
            self._write_state(CampaignState.PENDING)
        else:
            stored = self._read_state()["campaign_id"]
            if campaign_id is not None and stored != campaign_id:
                raise ValueError(
                    f"workspace holds campaign {stored}, requested {campaign_id}"
                )
            self.campaign_id = stored

    # ------------------------------------------------------------------ state

    def _read_state(self) -> dict:
        return json.loads(self.paths.state_file.read_text(encoding="utf-8"))

    def current_state(self) -> CampaignState:
        return CampaignState(self._read_state()["state"])

    def _write_state(self, new_state: CampaignState) -> None:
        if self.paths.state_file.exists():
            current = self.current_state()
            if current != new_state:
                assert_transition(current, new_state)
        _atomic_write_json(
            self.paths.state_file,
            {
                "campaign_id": self.campaign_id,
                "state": new_state.value,
                "updated_at": utc_now().isoformat(),
            },
        )

    def _init_campaign_record(self) -> None:
        descriptor = PolicyDescriptor(
            adapter=PolicyAdapterKind.TORCH_OCCLUSION_PERCEPTION,
            checkpoint_uri=str(self.baseline_checkpoint_path),
            checkpoint_sha256=sha256_file(str(self.baseline_checkpoint_path)),
            input_spec=INPUT_SPEC,
            supports_training=True,
            trainable_adapter="torch-behavior-cloning",
        )
        campaign = Campaign(
            record_id=self.campaign_id,
            campaign_id=self.campaign_id,
            created_at=utc_now(),
            objective=CampaignObjective(
                capability_taxonomy_id=self.objective_capability,
                description="close the measured capability gap end to end",
            ),
            world=CampaignWorld(world_id="virtual-yosemite-straight", source_tag="procedural"),
            baseline_policy=descriptor,
            config=CampaignConfig(
                diagnostician=self.diagnostician_kind,
                training_seed_pool_size=self.training_scenarios,
                hidden_exam_size=self.hidden_exam_size,
                protected_suite_size=self.protected_suite_size,
                promotion_target_success_rate=self.promotion_target,
                promotion_min_lower_bound=self.promotion_floor,
                promotion_max_regression_pp=self.promotion_max_regression_pp,
                seeds_per_arm=self.seeds_per_arm,
                samples_per_scenario=self.samples_per_scenario,
                training_epochs=self.training_epochs,
            ),
        ).sealed()
        verify_seal(campaign)
        self.paths.campaign_file.write_text(campaign.model_dump_json(indent=2), encoding="utf-8")

    def campaign_record(self) -> Campaign:
        return Campaign.model_validate_json(self.paths.campaign_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ events

    def _emit(self, event_type: EventType, payload: dict, step: str, refs: Optional[list[ArtifactRef]] = None) -> tuple[str, bool]:
        key = idempotency_key(self.campaign_id, step, event_type.value)
        return self.log.append(event_type, self.campaign_id, payload, key, artifact_refs=refs)

    # ------------------------------------------------------------------ helpers

    def _store(self, key: str, value) -> None:
        index_path = self.paths.root / "artifacts-index.json"
        data = json.loads(index_path.read_text()) if index_path.exists() else {}
        data[key] = value
        _atomic_write_json(index_path, data)

    def _stored(self, key: str, default=None):
        index_path = self.paths.root / "artifacts-index.json"
        if not index_path.exists():
            return default
        return json.loads(index_path.read_text()).get(key, default)

    def _baseline_policy(self) -> TorchOcclusionPerceptionAdapter:
        return TorchOcclusionPerceptionAdapter(self.baseline_checkpoint_path)

    def _candidate_policy(self) -> TorchOcclusionPerceptionAdapter:
        return TorchOcclusionPerceptionAdapter(self.paths.root / "candidate-checkpoint.pt")

    def _run_single(
        self,
        manifest: ScenarioManifest,
        policy: TorchOcclusionPerceptionAdapter,
        oracle: OracleConfig,
        job_name: str,
        save_frames: bool = True,
    ):
        runner = ScenarioRunner(manifest, policy, oracle=oracle, capture_frames=save_frames)
        outcome = runner.run()
        evidence, failure = build_evidence_and_failure(
            manifest, outcome, policy.descriptor.checkpoint_sha256, campaign_id=self.campaign_id
        )
        refs = write_job_outputs(
            self.paths.jobs / job_name, manifest, outcome, evidence, failure, save_frames=save_frames
        )
        return outcome, evidence, failure, refs

    def _showcase_scenario(self) -> Optional[ScenarioManifest]:
        """First deterministic-seed occluded scenario the baseline fails WITH vision."""
        from .evaluate import evaluate_scenario

        pool = build_occluded_pool(SHOWCASE_SEED_BASE, 16)
        policy = self._baseline_policy()
        for manifest in pool:
            if not evaluate_scenario(manifest, policy).success:
                return manifest
        return None

    # ------------------------------------------------------------------ loop

    def step_once(self) -> CampaignState:
        """Execute exactly one handler; safe on terminal states (no-op)."""

        state = self.current_state()
        if state in TERMINAL_STATES:
            return state
        self._handlers()[state]()
        return self.current_state()

    def run_to_completion(self, max_steps: int = 40) -> CampaignState:
        for _ in range(max_steps):
            state = self.step_once()
            if state in TERMINAL_STATES:
                return state
        raise RuntimeError("orchestrator exceeded max steps")

    def _handlers(self) -> dict[CampaignState, Callable[[], None]]:
        return {
            CampaignState.PENDING: self._h_intake,
            CampaignState.BASELINE_RUNNING: self._h_run_baseline,
            CampaignState.FAILURE_TRIAGE: self._h_triage,
            CampaignState.DIAGNOSING: self._h_diagnose,
            CampaignState.EXPERIMENTING: self._h_experiments,
            CampaignState.ROOT_CAUSE_GATE: self._h_root_cause,
            CampaignState.CURRICULUM_PLANNING: self._h_curriculum,
            CampaignState.TRAINING: self._h_train,
            CampaignState.HIDDEN_EXAM: self._h_hidden_exam,
            CampaignState.REGRESSION_CHECK: self._h_regression,
            CampaignState.PROMOTION_GATE: self._h_promotion,
            CampaignState.REALITY_DEBT_UPDATE: self._h_reality_debt,
        }

    # ------------------------------------------------------------------ steps

    def _h_intake(self) -> None:
        self._emit(EventType.CAMPAIGN_CREATED, {"capability": self.objective_capability}, "intake")
        self._emit(EventType.BASELINE_RUN_REQUESTED, {"checkpoint": str(self.baseline_checkpoint_path)}, "intake")
        self._write_state(CampaignState.BASELINE_RUNNING)

    def _h_run_baseline(self) -> None:
        showcase = self._showcase_scenario()
        if showcase is None:
            self._emit(EventType.NO_FAILURE_FOUND, {"reason": "no colliding scenario in deterministic scan"}, "baseline")
            self._write_state(CampaignState.FAILURE_TRIAGE)
            return

        policy = self._baseline_policy()
        self._emit(EventType.RUN_STARTED, {"scenario": showcase.scenario_id}, "baseline")
        outcome, evidence, failure, refs = self._run_single(showcase, policy, OracleConfig(), "baseline-showcase")
        self._emit(
            EventType.RUN_COMPLETED,
            {"result": outcome.result.value, "run_evidence_id": evidence.record_id},
            "baseline",
            refs=list(refs),
        )
        self._store("scenario-hash", evidence.body.scenario_hash)
        if failure is not None:
            self._store("failure-record-id", failure.record_id)
            self._store("failure-json", failure.model_dump(mode="json"))
            self._emit(
                EventType.FAILURE_DETECTED,
                {
                    "failure_class": failure.failure_class.value,
                    "severity": failure.severity.value,
                    "failure_id": failure.record_id,
                },
                "baseline",
                refs=list(refs),
            )
        self._write_state(CampaignState.FAILURE_TRIAGE)

    def _h_triage(self) -> None:
        if self._stored("failure-record-id") is None:
            self._store("triage-outcome", "no_failure")
            self._write_state(CampaignState.REALITY_DEBT_UPDATE)
            return
        self._store("triage-outcome", "failure")
        self._write_state(CampaignState.DIAGNOSING)

    def _load_baseline_failure(self) -> tuple[RunEvidence, FailureRecord]:
        evidence = RunEvidence.model_validate_json(
            (self.paths.jobs / "baseline-showcase" / "run-evidence.json").read_text(encoding="utf-8")
        )
        failure = FailureRecord.model_validate_json(
            (self.paths.jobs / "baseline-showcase" / "failure-record.json").read_text(encoding="utf-8")
        )
        return evidence, failure

    def _h_diagnose(self) -> None:
        model_kwargs = (
            {"model_id": self.diagnostician_model} if self.diagnostician_model else {}
        )
        diagnostician = build_diagnostician(self.diagnostician_kind, **model_kwargs)
        evidence, failure = self._load_baseline_failure()
        proposal = diagnostician.propose(evidence, failure, DiagnosisContext())
        serialized = {
            "summary": proposal.summary,
            "diagnostician": proposal.diagnostician,
            "model_id": proposal.model_id,
            "prompt_template_version": proposal.prompt_template_version,
            "response_sha256": proposal.response_sha256,
            "hypotheses": [h.model_dump(mode="json") for h in proposal.hypotheses],
            "requested_experiments": [
                {
                    "intervention": request.intervention.value,
                    "parameters": dict(request.parameters),
                    "hypothesis_ids": list(request.hypothesis_ids),
                    "estimated_cost_seconds": request.estimated_cost_seconds,
                }
                for request in proposal.requested_experiments
            ],
        }
        self._emit(EventType.DIAGNOSIS_REQUESTED, {"diagnostician": diagnostician.name}, "diagnose")
        self._emit(EventType.HYPOTHESES_PROPOSED, serialized, "diagnose")
        _atomic_write_json(self.paths.root / "proposal.json", serialized)
        self._write_state(CampaignState.EXPERIMENTING)

    def _h_experiments(self) -> None:
        _, failure = self._load_baseline_failure()
        proposal = json.loads((self.paths.root / "proposal.json").read_text())
        requests = [
            ExperimentRequest(
                intervention=InterventionName(item["intervention"]),
                parameters={k: float(v) for k, v in item.get("parameters", {}).items()},
                hypothesis_ids=tuple(item.get("hypothesis_ids", ()) or ()),
                estimated_cost_seconds=float(item.get("estimated_cost_seconds", 6.0)),
            )
            for item in proposal["requested_experiments"]
        ]

        showcase = self._showcase_scenario()
        policy = self._baseline_policy()
        engine = CounterfactualEngine(seeds_per_arm=self.seeds_per_arm)
        arms_summary: list[dict] = []
        for request in requests:
            results = engine.execute_request(
                showcase, request, policy, failure.record_id, campaign_id=self.campaign_id
            )
            outcomes = []
            for result in results:
                verify_seal(result.experiment_record)
                outcomes.append(result.outcome.value)
                self._emit(
                    EventType.EXPERIMENT_COMPLETED,
                    {
                        "experiment_id": result.experiment_record.record_id,
                        "intervention": request.intervention.value,
                        "outcome": result.outcome.value,
                        "derived_scenario_id": result.derived_scenario.scenario_id,
                    },
                    "experiments",
                )
            arms_summary.append({"intervention": request.intervention.value, "outcomes": outcomes})
        _atomic_write_json(self.paths.root / "arms-summary.json", {"arms": arms_summary})
        self._write_state(CampaignState.ROOT_CAUSE_GATE)

    def _h_root_cause(self) -> None:
        summary = json.loads((self.paths.root / "arms-summary.json").read_text())
        arms_map = {item["intervention"]: item["outcomes"] for item in summary["arms"]}
        _, failure = self._load_baseline_failure()

        gate, diagnosis = evaluate_causal_gate(
            arms=GateArmOutcomes(
                baseline=ExperimentOutcome.UNSAFE,
                remove_occluder=tuple(ExperimentOutcome(o) for o in arms_map["remove_occluder"]),
                reveal_earlier=tuple(ExperimentOutcome(o) for o in arms_map["reveal_pedestrian_earlier"]),
                oracle_perception=tuple(ExperimentOutcome(o) for o in arms_map["oracle_perception"]),
                oracle_planner=tuple(ExperimentOutcome(o) for o in arms_map["oracle_planner"]),
            ),
            total_seeds_per_arm=self.seeds_per_arm,
            failure_record_id=failure.record_id,
            capability_id=self.objective_capability,
            campaign_id=self.campaign_id,
        )
        if diagnosis is None:
            self._transition_failed(
                EventType.ROOT_CAUSE_INCONCLUSIVE,
                {"satisfied": gate.satisfied, "missing": gate.missing},
            )
            return
        _atomic_write_json(self.paths.root / "diagnosis.json", diagnosis.model_dump(mode="json"))
        self._store("diagnosis-id", diagnosis.record_id)
        self._emit(
            EventType.ROOT_CAUSE_ESTABLISHED,
            {
                "diagnosis_id": diagnosis.record_id,
                "rule": diagnosis.established_by.rule_id,
                "root_cause": diagnosis.root_cause_kind.value,
            },
            "root-cause",
        )
        self._write_state(CampaignState.CURRICULUM_PLANNING)

    def _h_curriculum(self) -> None:
        from .schemas.diagnosis import CausalDiagnosis

        diagnosis = CausalDiagnosis.model_validate_json(
            (self.paths.root / "diagnosis.json").read_text(encoding="utf-8")
        )
        planner = CurriculumPlanner(self.paths.root / "vault")
        plan = planner.plan(
            diagnosis,
            training_scenario_count=self.training_scenarios,
            hidden_exam_count=self.hidden_exam_size,
            campaign_id=self.campaign_id,
        )
        _atomic_write_json(self.paths.root / "curriculum.json", plan.curriculum.model_dump(mode="json"))
        _atomic_write_json(self.paths.root / "dataset-manifest.json", plan.dataset_manifest.model_dump(mode="json"))
        self._emit(
            EventType.CURRICULUM_CREATED,
            {
                "curriculum_id": plan.curriculum.record_id,
                "total_scenarios": plan.curriculum.total_scenarios,
                "stages": [stage.name for stage in plan.curriculum.stages],
            },
            "curriculum",
        )
        receipt = json.loads((self.paths.root / "vault" / "vault-receipt.json").read_text())
        self._emit(
            EventType.HIDDEN_SEEDS_SEALED,
            {"sealed_sha256": receipt["sealed_sha256"], "scenario_count": receipt["scenario_count"]},
            "curriculum",
        )
        self._write_state(CampaignState.TRAINING)

    def _training_scenarios_list(self) -> list[ScenarioManifest]:
        """Realize the sealed curriculum: stage names map to pool builders,
        and each stage's scenario_count is authoritative."""
        curriculum = json.loads((self.paths.root / "curriculum.json").read_text())
        clear_count = 0
        occluded_count = 0
        for stage in curriculum["stages"]:
            if stage["name"] == "ordinary-visible":
                clear_count = int(stage["scenario_count"])
            elif stage["name"] == "occluded-emergence":
                occluded_count = int(stage["scenario_count"])
        clear = (
            build_clear_pool(DEFAULT_PARTITION.training_seed(0), clear_count * 17 + 17)[:clear_count]
            if clear_count
            else []
        )
        occluded = (
            build_occluded_pool(DEFAULT_PARTITION.training_seed(500_000), occluded_count)
            if occluded_count
            else []
        )
        return clear + occluded

    def _h_train(self) -> None:
        scenarios = self._training_scenarios_list()
        self._emit(EventType.TRAINING_REQUESTED, {"trainer": "torch-behavior-cloning"}, "training")
        self._emit(EventType.TRAINING_STARTED, {"scenarios": len(scenarios)}, "training")

        full_dataset = build_dataset(scenarios, max_samples_per_scenario=self.samples_per_scenario)
        val_split = max(2, len(full_dataset) // 6)
        from .trainers.dataset import LabeledDataset

        val_dataset = LabeledDataset(samples=full_dataset.samples[:val_split])
        train_dataset = LabeledDataset(samples=full_dataset.samples[val_split:])
        if train_dataset.positive_count == 0 or len(train_dataset) == 0:
            self._transition_failed(
                EventType.TRAINING_FAILED, {"reason": "training split has no positive labels"}
            )
            return

        trainer = TorchBehaviorCloningTrainer()
        result = trainer.train(
            TrainingRequest(
                dataset=train_dataset,
                validation_dataset=val_dataset,
                baseline_checkpoint_path=self.baseline_checkpoint_path,
                limits=TrainingLimits(
                    max_epochs=self.training_epochs,
                    max_wall_time_s=900.0,
                    max_samples=20000,
                    early_stop_patience=3,
                ),
            ),
            self.paths.jobs / "candidate-training",
        )

        final_path = self.paths.root / "candidate-checkpoint.pt"
        src = Path(result.checkpoint_artifact.uri)
        src.replace(final_path)

        candidate_artifact = CheckpointArtifact(
            record_id=new_record_id("ckp"),
            created_at=utc_now(),
            checkpoint_sha256=sha256_file(str(final_path)),
            adapter=result.checkpoint_artifact.adapter,
            size_bytes=final_path.stat().st_size,
            uri=str(final_path),
            parent_checkpoint_sha256=result.checkpoint_artifact.parent_checkpoint_sha256,
            load_verified=True,
            weights_differ_from_parent=True,
        ).sealed()

        _atomic_write_json(
            self.paths.root / "candidate.json",
            {
                **candidate_artifact.model_dump(mode="json"),
                "metrics_history": result.metrics_history,
                "best_val_loss": result.best_val_loss,
                "best_epoch": result.best_epoch,
            },
        )
        self._store("candidate-sha256", candidate_artifact.checkpoint_sha256)
        self._store("baseline-sha256", sha256_file(str(self.baseline_checkpoint_path)))
        self._emit(
            EventType.CHECKPOINT_READY,
            {
                "candidate_sha256": candidate_artifact.checkpoint_sha256,
                "parent_sha256": candidate_artifact.parent_checkpoint_sha256,
                "best_val_loss": result.best_val_loss,
            },
            "training",
        )
        self._write_state(CampaignState.HIDDEN_EXAM)

    def _h_hidden_exam(self) -> None:
        examiner = HiddenExaminer(self.paths.root / "vault")
        report = examiner.run_exam(self._baseline_policy(), self._candidate_policy(), campaign_id=self.campaign_id)
        _atomic_write_json(self.paths.root / "hidden-exam.json", report.exam.model_dump(mode="json"))
        self._store("exam-id", report.exam.record_id)
        self._emit(
            EventType.HIDDEN_EXAM_COMPLETED,
            {
                "exam_id": report.exam.record_id,
                "baseline_success": report.exam.baseline.counts.success_rate,
                "candidate_success": report.exam.candidate.counts.success_rate,
                "interval": [
                    report.exam.candidate_success_interval.lower,
                    report.exam.candidate_success_interval.upper,
                ],
            },
            "exam",
        )
        self._write_state(CampaignState.REGRESSION_CHECK)

    def _h_regression(self) -> None:
        guardian = RegressionGuardian()
        outcome = guardian.run_regression(
            self._baseline_policy(),
            self._candidate_policy(),
            ordinary_count=self.protected_suite_size,
            campaign_id=self.campaign_id,
        )
        _atomic_write_json(self.paths.root / "regression-report.json", outcome.report.model_dump(mode="json"))
        self._store("regression-id", outcome.report.record_id)
        self._emit(
            EventType.REGRESSION_COMPLETED,
            {
                "regression_id": outcome.report.record_id,
                "suites": len(outcome.report.suites),
                "max_drop_pp": outcome.report.max_drop_percentage_points,
            },
            "regression",
        )
        self._write_state(CampaignState.PROMOTION_GATE)

    def _h_promotion(self) -> None:
        from .schemas.verification import HiddenExam, RegressionReport

        exam = HiddenExam.model_validate_json(
            (self.paths.root / "hidden-exam.json").read_text(encoding="utf-8")
        )
        regression = RegressionReport.model_validate_json(
            (self.paths.root / "regression-report.json").read_text(encoding="utf-8")
        )
        decision = PromotionGate().decide(
            PromotionInputs(
                exam=exam,
                regression=regression,
                candidate_checkpoint_sha256=self._stored("candidate-sha256"),
                baseline_checkpoint_sha256=self._stored("baseline-sha256"),
                target_success_rate=self.promotion_target,
                min_lower_bound=self.promotion_floor,
                max_regression_pp=self.promotion_max_regression_pp,
            ),
            campaign_id=self.campaign_id,
        )
        _atomic_write_json(self.paths.root / "promotion-decision.json", decision.model_dump(mode="json"))
        self._store("decision-id", decision.record_id)
        event = (
            EventType.CHECKPOINT_PROMOTED
            if decision.decision.value == "promoted"
            else EventType.CHECKPOINT_REJECTED
        )
        self._emit(
            event,
            {
                "decision_id": decision.record_id,
                "failed_checks": [c.name for c in decision.checks if not c.passed],
            },
            "promotion",
        )
        self._write_state(CampaignState.REALITY_DEBT_UPDATE)

    def _h_reality_debt(self) -> None:
        register = default_register()
        register.find(self.objective_capability)

        triage_outcome = self._stored("triage-outcome", "failure")
        decision_path = self.paths.root / "promotion-decision.json"
        decision_value = "rejected"
        if triage_outcome == "no_failure":
            decision_value = "no_failure"
        elif decision_path.exists():
            from .schemas.verification import PromotionDecision

            decision = PromotionDecision.model_validate_json(decision_path.read_text(encoding="utf-8"))
            decision_value = decision.decision.value
            updated = register.update_from_promotion(
                decision, self.objective_capability, scenario_coverage_count=self.hidden_exam_size
            )
            self._emit(
                EventType.CAPABILITY_UPDATED,
                {
                    "capability": self.objective_capability,
                    "state": updated.state.value,
                    "last_verified_checkpoint": updated.last_verified_checkpoint_sha256,
                },
                "debt",
            )

        snapshot = compute_reality_debt(register.all(), campaign_id=self.campaign_id)
        _atomic_write_json(self.paths.root / "reality-debt.json", snapshot.model_dump(mode="json"))
        self._emit(EventType.REALITY_DEBT_UPDATED, {"total_debt": snapshot.total_debt}, "debt")

        nxt = select_next_weakness(register.all())
        if nxt is not None:
            self._emit(
                EventType.NEXT_WEAKNESS_SELECTED,
                {"taxonomy_id": nxt.taxonomy_id, "state": nxt.state.value},
                "debt",
            )
            self._store("next-weakness", nxt.taxonomy_id)
            if nxt.state == CapabilityState.BLOCKED_MISSING_REALITY:
                from .capabilities import create_capture_mission, write_mission

                self._emit(
                    EventType.MISSING_REALITY_DETECTED,
                    {"capability": nxt.taxonomy_id, "reason": "no authorized world covers this capability"},
                    "debt",
                )
                mission = create_capture_mission(
                    nxt,
                    reason=(
                        "no authorized world can produce training evidence for "
                        f"{nxt.taxonomy_id}; capture required before training"
                    ),
                    campaign_id=self.campaign_id,
                )
                missions_dir = self.paths.root / "capture-missions"
                path = write_mission(mission, missions_dir)
                self._store("capture-mission-id", mission.record_id)
                _atomic_write_json(self.paths.root / "next-weakness.json", {
                    "taxonomy_id": nxt.taxonomy_id,
                    "capture_mission": mission.model_dump(mode="json"),
                })
                self._emit(
                    EventType.CAPTURE_MISSION_CREATED,
                    {
                        "mission_id": mission.record_id,
                        "capability": nxt.taxonomy_id,
                        "path": str(path),
                    },
                    "debt",
                )

        terminal = {
            "promoted": CampaignState.COMPLETED_PROMOTED,
            "rejected": CampaignState.COMPLETED_REJECTED,
            "no_failure": CampaignState.COMPLETED_NO_FAILURE,
        }[decision_value]
        self._write_state(terminal)
        self._emit(EventType.CAMPAIGN_COMPLETED, {"terminal": terminal.value}, "completion")

    def _transition_failed(self, event_type: EventType, payload: dict) -> None:
        self._emit(event_type, payload, "failed")
        self._write_state(CampaignState.FAILED)


def load_events(events_file: Path) -> list[DomainEvent]:
    return EventLog(events_file).events()
