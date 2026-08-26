"""Regression guardian: protects previously-passing capabilities.

Protected suites are deterministic scenario families drawn from the
protected seed partition.  A candidate that degrades any suite beyond the
configured tolerance is flagged regardless of its target-capability gains.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..evaluate import evaluate_suite, SuiteReport
from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..pools import build_clear_pool, build_occluded_pool
from ..schemas.base import verify_seal
from ..schemas.verification import (
    ProtectedSuite,
    RegressionReport,
    SuiteComparison,
)
from ..curriculum.seed_vault import DEFAULT_PARTITION


REGRESSION_GUARDIAN_VERSION = "regression-guardian/v1"


@dataclass(frozen=True)
class RegressionOutcome:
    report: RegressionReport


def _build_suites(ordinary_count: int):
    return {
        ProtectedSuite.ORDINARY_CROSSING: build_clear_pool(
            DEFAULT_PARTITION.protected_seed(0), ordinary_count
        ),
        ProtectedSuite.VISIBLE_PEDESTRIAN: build_clear_pool(
            DEFAULT_PARTITION.protected_seed(100_000), max(2, ordinary_count // 2)
        ),
        ProtectedSuite.NO_PEDESTRIAN: [
            s for s in build_clear_pool(DEFAULT_PARTITION.protected_seed(200_000), ordinary_count)
            if s.pedestrian is None
        ],
        ProtectedSuite.BRAKING_CONTROL: build_clear_pool(
            DEFAULT_PARTITION.protected_seed(300_000), max(2, ordinary_count // 2)
        ),
    }


class RegressionGuardian:
    VERSION = REGRESSION_GUARDIAN_VERSION

    def run_regression(
        self,
        baseline_policy,
        candidate_policy,
        ordinary_count: int = 10,
        campaign_id: str | None = None,
    ) -> RegressionOutcome:
        suites = _build_suites(ordinary_count)

        comparisons: list[SuiteComparison] = []
        max_drop_pp = 0.0
        severity_one = 0
        for suite_enum, manifests in suites.items():
            if not manifests:
                continue
            base_report: SuiteReport = evaluate_suite(suite_enum.value, manifests, baseline_policy)
            cand_report: SuiteReport = evaluate_suite(suite_enum.value, manifests, candidate_policy)
            delta_pp = (cand_report.success_rate - base_report.success_rate) * 100.0
            comparisons.append(
                SuiteComparison(
                    suite=suite_enum,
                    scenario_count=len(manifests),
                    baseline_success_rate=round(base_report.success_rate, 6),
                    candidate_success_rate=round(cand_report.success_rate, 6),
                    delta_percentage_points=round(delta_pp, 6),
                )
            )
            if delta_pp < max_drop_pp:
                max_drop_pp = delta_pp
            if delta_pp <= -100.0:
                severity_one += 1

        report = RegressionReport(
            record_id=new_record_id("regr"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            candidate_checkpoint_sha256=candidate_policy.descriptor.checkpoint_sha256,
            baseline_checkpoint_sha256=baseline_policy.descriptor.checkpoint_sha256,
            suites=tuple(comparisons),
            severity_one_regressions=severity_one,
            max_drop_percentage_points=round(max_drop_pp, 6),
        ).sealed()
        verify_seal(report)
        return RegressionOutcome(report=report)
