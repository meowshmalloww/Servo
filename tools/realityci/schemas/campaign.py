"""Campaign contract.

A campaign is the durable unit of autonomous work: one objective capability,
one world, one baseline policy, and the complete evidence chain produced
while attempting to close the gap.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import RealityCIRecord
from .run import PolicyDescriptor


class CampaignObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_taxonomy_id: str
    description: str = ""


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostician: str = "deterministic"
    max_counterfactuals: int = Field(ge=1, default=8)
    training_seed_pool_size: int = Field(ge=1)
    hidden_exam_size: int = Field(ge=1)
    protected_suite_size: int = Field(ge=1)
    promotion_target_success_rate: float = Field(gt=0.0, le=1.0)
    promotion_min_lower_bound: float = Field(gt=0.0, le=1.0)
    promotion_max_regression_pp: float = Field(ge=0.0)
    seeds_per_arm: int = Field(ge=1, default=3)
    samples_per_scenario: int = Field(ge=1, default=12)
    training_epochs: int = Field(ge=1, default=4)


class CampaignWorld(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    world_id: str
    source_tag: str
    background_frame_dir: Optional[str] = None
    background_provenance: str = "procedural-deterministic-road"


class Campaign(RealityCIRecord):
    schema_name: str = "servo.realityci.campaign/v1"
    record_id: str = Field(pattern=r"^cam-[0-9a-f]{16}$")
    campaign_id: str = Field(pattern=r"^cam-[0-9a-f]{16}$")
    objective: CampaignObjective
    world: CampaignWorld
    baseline_policy: PolicyDescriptor
    config: CampaignConfig
