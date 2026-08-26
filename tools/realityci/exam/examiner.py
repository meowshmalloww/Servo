"""Hidden examiner.

Opens the sealed vault through its authorized path, evaluates baseline and
candidate on identical hidden scenarios, and publishes aggregate results.
Hidden seeds never flow back to training-side components.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..evaluate import evaluate_scenario
from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..policy.base import PolicyAdapter
from ..schemas.base import verify_seal
from ..schemas.verification import (
    ArmResult,
    ExamStatus,
    HiddenExam,
    ScenarioOutcomeCounts,
    WilsonInterval,
)
from ..curriculum.seed_vault import SeedVault


EXAMINER_VERSION = "hidden-examiner/v1"


def _wilson_lower_upper(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    lower = max(0.0, (centre - spread) / denom)
    upper = min(1.0, (centre + spread) / denom)
    return lower, upper


@dataclass(frozen=True)
class ExamReport:
    exam: HiddenExam


class HiddenExaminer:
    VERSION = EXAMINER_VERSION

    def __init__(self, vault_dir) -> None:
        self._vault = SeedVault(vault_dir)

    def run_exam(
        self,
        baseline_policy: PolicyAdapter,
        candidate_policy: PolicyAdapter,
        campaign_id: str | None = None,
    ) -> ExamReport:
        manifests, receipt = self._vault.open_for_examiner()
        if not manifests:
            raise ValueError("vault opened empty")

        def arm(policy: PolicyAdapter) -> ArmResult:
            evaluations = [evaluate_scenario(m, policy) for m in manifests]
            counts = ScenarioOutcomeCounts(
                total=len(evaluations),
                success=sum(1 for e in evaluations if e.success),
                collision=sum(1 for e in evaluations if e.result == "collision"),
                near_miss=sum(1 for e in evaluations if e.result == "near_miss"),
                timeout_or_other=sum(
                    1 for e in evaluations if e.result not in ("success", "collision", "near_miss")
                ),
            )
            delays = [e.detection_delay_s for e in evaluations if e.detection_delay_s is not None]
            mean_delay = sum(delays) / len(delays) if delays else None
            return ArmResult(
                checkpoint_sha256=policy.descriptor.checkpoint_sha256,
                counts=counts,
                mean_detection_delay_s=mean_delay,
            )

        baseline_arm = arm(baseline_policy)
        candidate_arm = arm(candidate_policy)
        lower, upper = _wilson_lower_upper(
            candidate_arm.counts.success, candidate_arm.counts.total
        )

        exam = HiddenExam(
            record_id=new_record_id("exam"),
            exam_id=new_record_id("exam"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            causation_id=receipt.get("sealed_sha256"),
            vault_id=f"vault:{receipt['sealed_sha256'][:24]}",
            scenario_count=counts_total(manifests),
            baseline=baseline_arm,
            candidate=candidate_arm,
            candidate_success_interval=WilsonInterval(lower=lower, upper=upper),
            isolation_receipt_sha256=receipt["sealed_sha256"],
            status=ExamStatus.COMPLETED,
        ).sealed()
        verify_seal(exam)
        return ExamReport(exam=exam)


def counts_total(manifests) -> int:
    return len(list(manifests))
