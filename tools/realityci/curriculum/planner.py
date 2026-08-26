"""Curriculum planner: targeted easy-to-hard scenario pools for training.

The planner sees ONLY training-partition seeds.  Hidden exam material is
sealed by the SeedVault before the curriculum exists and never enters this
module's inputs or outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..pools import build_clear_pool, build_occluded_pool
from ..schemas.base import verify_seal
from ..schemas.diagnosis import CausalDiagnosis
from ..schemas.training import Curriculum, CurriculumDimension, CurriculumStage, DatasetManifest, DatasetSplitCounts
from .seed_vault import DEFAULT_PARTITION, SeedVault


CURRICULUM_PLANNER_VERSION = "curriculum-planner/v1"


@dataclass(frozen=True)
class CurriculumPlan:
    curriculum: Curriculum
    dataset_manifest: DatasetManifest
    training_scenarios: list[ScenarioManifest]


class CurriculumPlanner:
    def __init__(self, vault_dir: Path) -> None:
        self._vault = SeedVault(vault_dir)

    def plan(
        self,
        diagnosis: CausalDiagnosis,
        training_scenario_count: int,
        hidden_exam_count: int,
        campaign_id: str | None = None,
    ) -> CurriculumPlan:
        """Targeted curriculum: the diagnosed weakness dominates the mix;
        ordinary traffic is kept as a replay minority to protect regressions."""
        occluded_count = max(2, round(training_scenario_count * 0.6))
        clear_count = training_scenario_count - occluded_count

        clear = build_clear_pool(
            DEFAULT_PARTITION.training_seed(0), _spread(clear_count)
        )[:clear_count]
        occluded = build_occluded_pool(
            DEFAULT_PARTITION.training_seed(500_000), occluded_count
        )
        training_scenarios = clear + occluded

        difficulty_stages = [
            CurriculumStage(
                stage_index=0,
                name="ordinary-visible",
                difficulty=0.25,
                scenario_count=len(clear),
                dimension_ranges={
                    CurriculumDimension.OCCLUSION_RATIO.value: (0.0, 0.0),
                    CurriculumDimension.EGO_SPEED.value: (11.5, 17.0),
                },
                seed_low=min(s.seed for s in clear) if clear else 0,
                seed_high=max(s.seed for s in clear) if clear else 0,
            ),
            CurriculumStage(
                stage_index=1,
                name="occluded-emergence",
                difficulty=0.85,
                scenario_count=len(occluded),
                dimension_ranges={
                    CurriculumDimension.OCCLUSION_RATIO.value: (0.4, 1.0),
                    CurriculumDimension.EGO_SPEED.value: (16.0, 17.0),
                },
                seed_low=min(s.seed for s in occluded) if occluded else 0,
                seed_high=max(s.seed for s in occluded) if occluded else 0,
            ),
        ]

        curriculum = Curriculum(
            record_id=new_record_id("curr"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            causation_id=diagnosis.record_id,
            parent_id=diagnosis.record_id,
            objective_capability=diagnosis.capability_id,
            stages=tuple(difficulty_stages),
            total_scenarios=len(training_scenarios),
            provenance="deterministic-pools-v1",
        ).sealed()
        verify_seal(curriculum)

        dataset_manifest = DatasetManifest(
            record_id=new_record_id("ds"),
            created_at=utc_now(),
            campaign_id=campaign_id,
            causation_id=diagnosis.record_id,
            purpose="behavior-cloning-fine-tune",
            split_counts=DatasetSplitCounts(
                train=len(training_scenarios),
                validation=max(2, len(training_scenarios) // 6),
            ),
            scenario_hashes=tuple(sorted(s.compute_content_hash() for s in training_scenarios)),
            oracle_label_method="unbraking-conflict-horizon/v1",
            seed_range_lo=min(s.seed for s in training_scenarios),
            seed_range_hi=max(s.seed for s in training_scenarios),
        ).sealed()
        verify_seal(dataset_manifest)

        hidden = SeedVault.build_hidden_manifests(hidden_exam_count, 0)
        self._vault.seal_hidden(hidden, campaign_id)

        return CurriculumPlan(
            curriculum=curriculum,
            dataset_manifest=dataset_manifest,
            training_scenarios=training_scenarios,
        )


def _spread(count: int) -> int:
    """Clear pools use stride-17 seeds; request enough raw slots."""

    return count * 17 + 17
