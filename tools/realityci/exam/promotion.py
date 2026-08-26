"""Deterministic promotion gate.

The gate is pure code over measured reports: it never consults an LLM and
cannot be overridden by one.  Identical inputs always yield the identical
decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..schemas.base import verify_seal
from ..schemas.verification import (
    Decision,
    GateCheck,
    HiddenExam,
    PromotionDecision,
    RegressionReport,
)


PROMOTION_GATE_VERSION = "promotion-gate/v1"


@dataclass(frozen=True)
class PromotionInputs:
    exam: HiddenExam
    regression: RegressionReport
    candidate_checkpoint_sha256: str
    baseline_checkpoint_sha256: str
    target_success_rate: float = 0.9
    min_lower_bound: float = 0.8
    max_regression_pp: float = 3.0


class PromotionGate:
    VERSION = PROMOTION_GATE_VERSION

    def decide(self, inputs: PromotionInputs, campaign_id: str | None = None) -> PromotionDecision:
        checks: list[GateCheck] = []
        reasons: list[str] = []

        exam = inputs.exam
        regression = inputs.regression

        checks.append(_check("exam_completed", exam.status.value == "completed", "hidden exam status"))
        target_rate = exam.candidate.counts.success / exam.candidate.counts.total
        checks.append(
            _check(
                "candidate_target_success",
                target_rate >= inputs.target_success_rate,
                f"candidate hidden success {target_rate:.3f} < target {inputs.target_success_rate}",
            )
        )
        checks.append(
            _check(
                "candidate_lower_bound",
                exam.candidate_success_interval.lower >= inputs.min_lower_bound,
                f"lower bound {exam.candidate_success_interval.lower:.3f} < floor {inputs.min_lower_bound}",
            )
        )
        beats_baseline = target_rate > (exam.baseline.counts.success / exam.baseline.counts.total)
        checks.append(
            _check(
                "beats_baseline_on_hidden",
                beats_baseline,
                "candidate must strictly beat baseline on the hidden set",
            )
        )

        worst = min((s.delta_percentage_points for s in regression.suites), default=0.0)
        checks.append(
            _check(
                "no_protected_regression",
                all(s.delta_percentage_points >= -inputs.max_regression_pp for s in regression.suites),
                f"worst protected drop {worst:.2f}pp exceeds limit {inputs.max_regression_pp}pp",
            )
        )
        checks.append(
            _check(
                "no_severity_one_regressions",
                regression.severity_one_regressions == 0,
                f"{regression.severity_one_regressions} severity-1 regressions",
            )
        )
        checks.append(
            _check(
                "checkpoint_identity",
                inputs.candidate_checkpoint_sha256
                == exam.candidate.checkpoint_sha256 == regression.candidate_checkpoint_sha256,
                "candidate checkpoint hash must match across exam and regression records",
            )
        )
        checks.append(
            _check(
                "baseline_identity",
                inputs.baseline_checkpoint_sha256
                == exam.baseline.checkpoint_sha256 == regression.baseline_checkpoint_sha256,
                "baseline checkpoint hash must match across exam and regression records",
            )
        )
        checks.append(
            _check(
                "isolation_receipt_present",
                bool(exam.isolation_receipt_sha256),
                "hidden-data isolation receipt required",
            )
        )

        passed = all(c.passed for c in checks)
        if not passed:
            reasons = [c.detail for c in checks if not c.passed]
        decision = Decision.PROMOTED if passed else Decision.REJECTED

        promotion = PromotionDecision(
            record_id=new_record_id("promo"),
            decision_id=new_record_id("promo"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            decision=decision,
            candidate_checkpoint_sha256=inputs.candidate_checkpoint_sha256,
            baseline_checkpoint_sha256=inputs.baseline_checkpoint_sha256,
            checks=tuple(checks),
            reasons=tuple(reasons),
            gate_version=self.VERSION,
        ).sealed()
        verify_seal(promotion)
        return promotion


def _check(name: str, passed: bool, fail_detail: str) -> GateCheck:
    return GateCheck(name=name, passed=bool(passed), detail="" if passed else fail_detail)
