"""Policy evaluation harness: runs suites and reports measured matrices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .policy.base import PolicyAdapter
from .scenario.runner import OracleConfig, RunResult, ScenarioRunner, RunnerTiming
from .schemas.run import RunResult as RunResultEnum
from .schemas.scenario import ScenarioManifest


@dataclass(frozen=True)
class ScenarioEvaluation:
    scenario_id: str
    seed: int
    result: str
    collision_s: Optional[float]
    first_visibility_s: Optional[float]
    first_detection_s: Optional[float]
    detection_delay_s: Optional[float]
    brake_command_s: Optional[float]
    ego_speed_mps: float

    @property
    def success(self) -> bool:
        return self.result == RunResultEnum.SUCCESS.value


@dataclass(frozen=True)
class SuiteReport:
    suite_name: str
    evaluations: tuple[ScenarioEvaluation, ...]

    @property
    def success_rate(self) -> float:
        if not self.evaluations:
            return 0.0
        return sum(1 for e in self.evaluations if e.success) / len(self.evaluations)

    @property
    def collision_rate(self) -> float:
        if not self.evaluations:
            return 0.0
        return sum(1 for e in self.evaluations if e.result == RunResultEnum.COLLISION.value) / len(
            self.evaluations
        )

    @property
    def mean_detection_delay_s(self) -> Optional[float]:
        delays = [e.detection_delay_s for e in self.evaluations if e.detection_delay_s is not None]
        if not delays:
            return None
        return sum(delays) / len(delays)

    def to_dict(self) -> dict:
        return {
            "suite": self.suite_name,
            "count": len(self.evaluations),
            "success_rate": self.success_rate,
            "collision_rate": self.collision_rate,
            "mean_detection_delay_s": self.mean_detection_delay_s,
            "evaluations": [vars(e) for e in self.evaluations],
        }


def evaluate_scenario(
    manifest: ScenarioManifest,
    policy: PolicyAdapter,
    oracle: OracleConfig = OracleConfig(),
) -> ScenarioEvaluation:
    outcome = ScenarioRunner(manifest, policy, oracle=oracle, capture_frames=True).run()
    detection_delay = None
    if (
        outcome.first_policy_detection_s is not None
        and outcome.first_ground_truth_visibility_s is not None
    ):
        detection_delay = outcome.first_policy_detection_s - outcome.first_ground_truth_visibility_s
    return ScenarioEvaluation(
        scenario_id=manifest.scenario_id,
        seed=manifest.seed,
        result=outcome.result.value,
        collision_s=outcome.collision_time_s,
        first_visibility_s=outcome.first_ground_truth_visibility_s,
        first_detection_s=outcome.first_policy_detection_s,
        detection_delay_s=detection_delay,
        brake_command_s=outcome.brake_command_s,
        ego_speed_mps=manifest.ego.initial_speed_mps,
    )


def evaluate_suite(
    name: str,
    manifests: list[ScenarioManifest],
    policy: PolicyAdapter,
    oracle: OracleConfig = OracleConfig(),
) -> SuiteReport:
    evaluations = tuple(evaluate_scenario(m, policy, oracle) for m in manifests)
    return SuiteReport(suite_name=name, evaluations=evaluations)


def report_summary_line(report: SuiteReport) -> str:
    delay = report.mean_detection_delay_s
    delay_text = f"{delay:.3f}s" if delay is not None else "n/a"
    return (
        f"{report.suite_name:<28} n={len(report.evaluations):<3} "
        f"success={report.success_rate*100:5.1f}% collisions={report.collision_rate*100:5.1f}% "
        f"mean_detect_delay={delay_text}"
    )
