"""Scenario manifest contract.

A scenario is an immutable, content-addressed specification of one
deterministic physical situation: route, ego kinematics, actors, occluder,
appearance, and provenance.  Counterfactual experiments derive new manifests
from parents via recorded patches; nothing mutates a sealed manifest.

Provenance is explicit and honest:
  background      = observed Gaussian render (camera appearance only)
  actors          = synthetic controllable state
  collisionTruth  = deterministic scenario state (never Gaussian geometry)
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import RealityCIRecord


class WorldRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    world_id: str = Field(min_length=1)
    source_tag: str = Field(min_length=1)


class RouteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_s_m: float = Field(ge=0.0)
    end_s_m: float
    speed_limit_mps: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _ordered(self) -> "RouteSpec":
        if self.end_s_m <= self.start_s_m:
            raise ValueError("route end must be after start")
        return self


class EgoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_speed_mps: float = Field(gt=0.0)
    max_acceleration_mps2: float = Field(gt=0.0, default=2.5)
    max_braking_mps2: float = Field(gt=0.0, default=6.5)
    brake_actuation_delay_s: float = Field(ge=0.0, default=0.18)
    length_m: float = Field(gt=0.0, default=4.6)
    width_m: float = Field(gt=0.0, default=1.9)
    lane_center_lateral_m: float = 0.0
    lane_width_m: float = Field(gt=0.0, default=3.5)


class PedestrianSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    crossing_speed_mps: float = Field(gt=0.0, le=8.0)
    emergence_s: float = Field(ge=0.0)
    crossing_angle_deg: float = Field(gt=0.0, lt=180.0)
    start_lateral_m: float
    end_lateral_m: float
    width_m: float = Field(gt=0.0, default=0.5)
    height_m: float = Field(gt=0.0, default=1.75)

    @model_validator(mode="after")
    def _crosses_lane(self) -> "PedestrianSpec":
        if (self.start_lateral_m - self.end_lateral_m) == 0.0:
            raise ValueError("pedestrian must actually cross laterally")
        return self


class OccluderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position_s_m: float
    lateral_offset_m: float
    length_m: float = Field(gt=0.0, default=4.5)
    width_m: float = Field(gt=0.0, default=1.85)
    height_m: float = Field(gt=0.0, default=1.5)


class AppearanceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brightness: float = Field(gt=0.0, le=2.0, default=1.0)
    contrast: float = Field(gt=0.0, le=2.0, default=1.0)
    weather_tag: str = "clear"


class ScenarioProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    background: str
    actors: str
    collision_truth: str


OBSERVED_BACKGROUND_PROVENANCE = ScenarioProvenance(
    background="observed-gaussian-source-frames",
    actors="synthetic-controllable",
    collision_truth="deterministic-scenario-state",
)

SYNTHETIC_BACKGROUND_PROVENANCE = ScenarioProvenance(
    background="procedural-deterministic-road",
    actors="synthetic-controllable",
    collision_truth="deterministic-scenario-state",
)


class DerivationInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intervention: str
    parameters: dict[str, float] = Field(default_factory=dict)


class ScenarioManifest(RealityCIRecord):
    schema_name: str = "servo.realityci.scenario/v1"
    record_id: str = Field(pattern=r"^scn-[0-9a-f]{16}$")
    scenario_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    world_ref: WorldRef
    route: RouteSpec
    ego: EgoSpec
    pedestrian: Optional[PedestrianSpec] = None
    occluder: Optional[OccluderSpec] = None
    appearance: AppearanceSpec
    provenance: ScenarioProvenance
    derivation: Optional[DerivationInfo] = None
    dt_s: float = Field(gt=0.0, le=0.1, default=0.02)
    horizon_s: float = Field(gt=0.0, le=60.0)

    @model_validator(mode="after")
    def _validate_physics(self) -> "ScenarioManifest":
        span = self.route.end_s_m - self.route.start_s_m
        max_travel = self.ego.initial_speed_mps * self.horizon_s + 0.5 * self.ego.max_braking_mps2 * self.horizon_s**2
        if max_travel < span * 0.25:
            raise ValueError("ego cannot traverse a meaningful fraction of the route within the horizon")
        if self.pedestrian is not None and self.occluder is not None:
            if not (self.route.start_s_m <= self.occluder.position_s_m <= self.route.end_s_m):
                raise ValueError("occluder must lie on the route")
        return self

    def requires_occlusion(self) -> bool:
        return self.occluder is not None and self.pedestrian is not None
