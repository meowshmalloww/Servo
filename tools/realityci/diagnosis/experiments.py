"""Counterfactual experiment engine.

Every intervention derives a NEW immutable scenario manifest from the parent
via a recorded patch (or toggles an oracle execution flag recorded in the
experiment parameters).  Nothing mutates the parent scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..hashing import new_record_id
from ..pools import derive_manifest
from ..schemas.base import utc_now
from ..policy.base import PolicyAdapter
from ..scenario.runner import OracleConfig, RunResult, ScenarioRunner
from ..schemas.diagnosis import (
    ExperimentOutcome,
    ExperimentStatus,
    InterventionName,
)
from ..schemas.run import RunEvidence
from ..schemas.scenario import ScenarioManifest


EXPERIMENT_ENGINE_VERSION = "counterfactual-engine/v1"


def _shadow_hidden_duration(manifest: ScenarioManifest) -> float:
    """Seconds the pedestrian spends walking INSIDE the occluder's lateral band.

    Removing the occluder must reveal the full walk, so the derived scenario
    starts the visible walk this many seconds earlier.
    """

    import math

    from ..scenario.dynamics import OccluderBox

    occluder = manifest.occluder
    ped = manifest.pedestrian
    if occluder is None or ped is None:
        return 0.0
    box_y_lo = occluder.lateral_offset_m - occluder.width_m / 2.0
    box_y_hi = occluder.lateral_offset_m + occluder.width_m / 2.0
    direction = 1.0 if ped.end_lateral_m >= ped.start_lateral_m else -1.0
    vy = ped.crossing_speed_mps * math.sin(math.radians(ped.crossing_angle_deg))
    if direction > 0:
        exit_edge = box_y_hi
        distance_inside = exit_edge - ped.start_lateral_m
    else:
        exit_edge = box_y_lo
        distance_inside = ped.start_lateral_m - exit_edge
    if distance_inside <= 0.0 or vy <= 1e-9:
        return 0.0
    return min(distance_inside / vy, ped.emergence_s)


def _apply_remove_occluder(manifest: ScenarioManifest, params: dict[str, float]) -> ScenarioManifest:
    hidden_s = _shadow_hidden_duration(manifest)
    return derive_manifest(
        manifest,
        InterventionName.REMOVE_OCCLUDER.value,
        {**params, "revealed_shadow_seconds": round(hidden_s, 6)},
        drop_occluder=True,
        emergence_shift_s=-hidden_s,
    )


def _apply_reveal_earlier(manifest: ScenarioManifest, params: dict[str, float]) -> ScenarioManifest:
    delta = float(params.get("delta_seconds", 0.0))
    if delta <= 0.0 or delta > 5.0:
        raise ValueError("delta_seconds must be within (0, 5]")
    return derive_manifest(
        manifest,
        InterventionName.REVEAL_PEDESTRIAN_EARLIER.value,
        dict(params),
        emergence_shift_s=-delta,
    )


def _apply_vary_ego_speed(manifest: ScenarioManifest, params: dict[str, float]) -> ScenarioManifest:
    speed = float(params.get("speed_mps", 0.0))
    if speed <= 1.0 or speed > manifest.route.speed_limit_mps:
        raise ValueError("speed_mps out of range")
    return derive_manifest(
        manifest,
        InterventionName.VARY_EGO_SPEED.value,
        dict(params),
        ego_speed_override=speed,
    )


def _apply_vary_pedestrian_speed(manifest: ScenarioManifest, params: dict[str, float]) -> ScenarioManifest:
    speed = float(params.get("speed_mps", 0.0))
    if speed <= 0.2 or speed > 8.0:
        raise ValueError("speed_mps out of range")
    return derive_manifest(
        manifest,
        InterventionName.VARY_PEDESTRIAN_SPEED.value,
        dict(params),
        ped_speed_override=speed,
    )


def _make_oracle_applier(flag: str) -> Callable[[ScenarioManifest, dict[str, float]], tuple[ScenarioManifest, OracleConfig]]:
    def applier(manifest: ScenarioManifest, params: dict[str, float]):
        derived = derive_manifest(
            manifest,
            f"oracle_{flag}",
            dict(params),
        )
        oracle_params = {"oracle_" + flag: 1.0}
        return derived, OracleConfig(**{flag: True}), oracle_params

    return applier


InterventionApplier = Callable[..., object]

_APPLIERS: dict[InterventionName, object] = {
    InterventionName.REMOVE_OCCLUDER: _apply_remove_occluder,
    InterventionName.REVEAL_PEDESTRIAN_EARLIER: _apply_reveal_earlier,
    InterventionName.VARY_EGO_SPEED: _apply_vary_ego_speed,
    InterventionName.VARY_PEDESTRIAN_SPEED: _apply_vary_pedestrian_speed,
}


@dataclass(frozen=True)
class ExperimentResult:
    experiment_record: object
    outcome: ExperimentOutcome
    derived_scenario: ScenarioManifest
    run_evidence: RunEvidence | None
    result_value: RunResult | None


class CounterfactualEngine:
    VERSION = EXPERIMENT_ENGINE_VERSION

    def __init__(self, seeds_per_arm: int = 3, max_parallel: int = 4) -> None:
        if seeds_per_arm < 1 or seeds_per_arm > 7:
            raise ValueError("seeds_per_arm must be within [1, 7]")
        self.seeds_per_arm = seeds_per_arm
        self.max_parallel = max_parallel

    def execute_request(
        self,
        parent: ScenarioManifest,
        request,  # diagnosis.base.ExperimentRequest
        policy: PolicyAdapter,
        failure_record_id: str,
        campaign_id: str | None = None,
    ) -> list[ExperimentResult]:
        intervention = request.intervention
        results: list[ExperimentResult] = []
        for arm_index in range(self.seeds_per_arm):
            arm_params = dict(request.parameters)
            if arm_index > 0:
                arm_params = {**arm_params, "arm_seed_offset": float(arm_index)}

            if intervention in (InterventionName.ORACLE_PERCEPTION, InterventionName.ORACLE_PLANNER, InterventionName.ORACLE_CONTROLLER):
                flag = {
                    InterventionName.ORACLE_PERCEPTION: "perception",
                    InterventionName.ORACLE_PLANNER: "planner",
                    InterventionName.ORACLE_CONTROLLER: "controller",
                }[intervention]
                derived = derive_manifest(parent, intervention.value, dict(arm_params))
                oracle = OracleConfig(**{flag: True})
                merged_params = {**arm_params, "oracle_" + flag: 1.0}
            else:
                applier = _APPLIERS.get(intervention)
                if applier is None:
                    record = self._failed_record(
                        parent, request, failure_record_id, campaign_id,
                        f"unsupported intervention: {intervention}",
                    )
                    results.append(
                        ExperimentResult(record, ExperimentOutcome.INVALID, parent, None, None)
                    )
                    continue
                derived = applier(parent, arm_params)  # type: ignore[operator]
                oracle = OracleConfig()
                merged_params = dict(arm_params)

            runner = ScenarioRunner(derived, policy, oracle=oracle)
            outcome = runner.run()
            record = self._record(
                parent=parent,
                derived=derived,
                request=request,
                params=merged_params,
                failure_record_id=failure_record_id,
                campaign_id=campaign_id,
                result=outcome.result,
            )
            results.append(
                ExperimentResult(
                    experiment_record=record,
                    outcome=self._to_outcome(outcome.result),
                    derived_scenario=derived,
                    run_evidence=None,
                    result_value=outcome.result,
                )
            )
        return results

    def _to_outcome(self, result: RunResult) -> ExperimentOutcome:
        if result == RunResult.SUCCESS:
            return ExperimentOutcome.SAFE
        if result in (RunResult.COLLISION, RunResult.NEAR_MISS):
            return ExperimentOutcome.UNSAFE
        return ExperimentOutcome.INVALID

    def _record(
        self,
        parent: ScenarioManifest,
        derived: ScenarioManifest,
        request,
        params: dict[str, float],
        failure_record_id: str,
        campaign_id: str | None,
        result: RunResult,
    ):
        from ..schemas.diagnosis import CounterfactualExperiment

        return CounterfactualExperiment(
            record_id=new_record_id("exp"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            causation_id=failure_record_id,
            experiment_id=new_record_id("exp"),
            failure_record_id=failure_record_id,
            intervention=request.intervention,
            parameters=params,
            parent_scenario_hash=parent.compute_content_hash(),
            derived_scenario_hash=derived.compute_content_hash(),
            derived_scenario_id=derived.scenario_id,
            status=ExperimentStatus.COMPLETED,
            outcome=self._to_outcome(result),
            hypothesis_ids=tuple(request.hypothesis_ids),
            cost_estimate_seconds=float(params.get("estimated_cost_seconds", 6.0)),
        ).sealed()

    def _failed_record(self, parent, request, failure_record_id, campaign_id, reason: str):
        from ..schemas.diagnosis import CounterfactualExperiment

        return CounterfactualExperiment(
            record_id=new_record_id("exp"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            experiment_id=new_record_id("exp"),
            failure_record_id=failure_record_id,
            intervention=request.intervention,
            parameters=dict(request.parameters),
            parent_scenario_hash=parent.compute_content_hash(),
            derived_scenario_hash=parent.compute_content_hash(),
            derived_scenario_id=parent.scenario_id,
            status=ExperimentStatus.FAILED,
            outcome=ExperimentOutcome.INVALID,
            hypothesis_ids=tuple(request.hypothesis_ids),
            cost_estimate_seconds=0.0,
        ).sealed()


def apply_intervention(manifest: ScenarioManifest, name: InterventionName, params: dict[str, float]) -> ScenarioManifest:
    """Standalone derivation helper exposed for tooling and tests."""

    applier = _APPLIERS.get(name)
    if applier is None and name in (
        InterventionName.ORACLE_PERCEPTION,
        InterventionName.ORACLE_PLANNER,
        InterventionName.ORACLE_CONTROLLER,
    ):
        return manifest
    if applier is None:
        raise ValueError(f"unsupported intervention: {name}")
    return applier(manifest, params)  # type: ignore[operator]
