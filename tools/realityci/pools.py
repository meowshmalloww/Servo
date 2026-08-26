"""Deterministic scenario pool construction.

Pools are pure functions of their seed ranges: identical inputs always yield
identical manifests, so every suite is reproducible from its definition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .hashing import new_record_id
from .schemas.scenario import (
    AppearanceSpec,
    DerivationInfo,
    EgoSpec,
    OccluderSpec,
    PedestrianSpec,
    RouteSpec,
    ScenarioManifest,
    ScenarioProvenance,
    WorldRef,
)
from .scenario.runner import OracleConfig


OBSERVED_PROVENANCE = ScenarioProvenance(
    background="procedural-deterministic-road",
    actors="synthetic-controllable",
    collision_truth="deterministic-scenario-state",
)

WORLD = WorldRef(world_id="virtual-yosemite-straight", source_tag="procedural")
ROUTE = RouteSpec(start_s_m=12.0, end_s_m=100.0, speed_limit_mps=17.0)

OCCLUDER_POSITION_S_M = 78.0
OCCLUDER_LATERAL_M = 2.1
CROSS_S_MARGIN_M = 6.0


def _uniform(rng: "AnyRng", lo: float, hi: float) -> float:
    return lo + (hi - lo) * rng.random()


class AnyRng:
    """Minimal deterministic RNG facade over numpy."""

    def __init__(self, seed: int) -> None:
        import numpy as np

        self._rng = np.random.default_rng(seed)

    def random(self) -> float:
        return float(self._rng.random())


def _make_manifest(
    seed: int,
    scenario_prefix: str,
    ego_speed: float,
    appearance_jitter: bool,
    rng: AnyRng,
    *,
    pedestrian: PedestrianSpec | None,
    occluder: OccluderSpec | None,
) -> ScenarioManifest:
    return ScenarioManifest(
        record_id=new_record_id("scn"),
        scenario_id=f"{scenario_prefix}-{seed}",
        created_at=datetime.now(timezone.utc),
        seed=seed,
        world_ref=WORLD,
        route=ROUTE,
        ego=EgoSpec(
            initial_speed_mps=ego_speed,
            max_braking_mps2=6.5,
            brake_actuation_delay_s=0.18,
            lane_width_m=3.5,
        ),
        pedestrian=pedestrian,
        occluder=occluder,
        appearance=AppearanceSpec(
            brightness=_uniform(rng, 0.9, 1.1),
            contrast=_uniform(rng, 0.9, 1.1),
        )
        if appearance_jitter
        else AppearanceSpec(),
        provenance=OBSERVED_PROVENANCE,
        horizon_s=12.0,
    )


def _clear_crossing(seed: int, rng: AnyRng) -> ScenarioManifest:
    """Pedestrian becomes hazardous only during a decisive final window."""

    ego_speed = _uniform(rng, 11.5, 17.0)
    cross_s = _uniform(rng, 40.0, 86.0)
    ped_speed = _uniform(rng, 1.2, 2.0)
    angle = _uniform(rng, 78.0, 102.0)
    direction = -1.0 if seed % 2 == 0 else 1.0

    camera_x = ROUTE.start_s_m + 2.3
    distance_when_emerges = _uniform(rng, 24.0, 38.0)
    t_conflict = (cross_s - camera_x) / ego_speed
    emergence_s = max(0.05, t_conflict - distance_when_emerges / ego_speed)

    return _make_manifest(
        seed,
        "clear",
        ego_speed,
        True,
        rng,
        pedestrian=PedestrianSpec(
            crossing_speed_mps=ped_speed,
            emergence_s=emergence_s,
            crossing_angle_deg=angle,
            start_lateral_m=2.4 * direction,
            end_lateral_m=-3.0 * direction,
        ),
        occluder=None,
    )


def _irrelevant_pedestrian(seed: int, rng: AnyRng) -> ScenarioManifest:
    """Visible pedestrian who never conflicts: finishes early or starts late."""

    ego_speed = _uniform(rng, 11.5, 17.0)
    cross_s = _uniform(rng, 40.0, 86.0)
    ped_speed = _uniform(rng, 1.4, 2.2)
    angle = _uniform(rng, 80.0, 100.0)
    direction = -1.0 if seed % 2 == 0 else 1.0

    camera_x = ROUTE.start_s_m + 2.3
    t_conflict = (cross_s - camera_x) / ego_speed
    lane_traverse_time = 7.5 / ped_speed

    if seed % 3 == 0:
        emergence_s = max(0.05, t_conflict - lane_traverse_time - _uniform(rng, 1.0, 2.5))
    else:
        emergence_s = min(11.0, t_conflict + _uniform(rng, 0.5, 2.0))

    return _make_manifest(
        seed,
        "irrel",
        ego_speed,
        True,
        rng,
        pedestrian=PedestrianSpec(
            crossing_speed_mps=ped_speed,
            emergence_s=emergence_s,
            crossing_angle_deg=angle,
            start_lateral_m=2.4 * direction,
            end_lateral_m=-3.0 * direction,
        ),
        occluder=None,
    )


def build_clear_pool(seed_base: int, count: int) -> list[ScenarioManifest]:
    """Mixed ordinary traffic: crossings, empty road, non-conflicting pedestrians."""

    manifests: list[ScenarioManifest] = []
    for index in range(count):
        seed = seed_base + index * 17
        rng = AnyRng(seed)
        role = index % 5
        if role == 3:
            manifests.append(
                _make_manifest(seed, "empty", _uniform(rng, 11.5, 17.0), True, rng,
                               pedestrian=None, occluder=None)
            )
        elif role == 4:
            manifests.append(_irrelevant_pedestrian(seed, rng))
        else:
            manifests.append(_clear_crossing(seed, rng))
    return manifests


def build_occluded_pool(seed_base: int, count: int) -> list[ScenarioManifest]:
    """Partial-occlusion band designed so the causal window exists.

    With ego speed v, conflict at s_c, the pedestrian (lateral speed w)
    becomes a full silhouette roughly (start_lateral - clear_y)/w after
    starting to walk, while an ideal detector reacts at the first roofline
    sliver (~0.1 s after onset).  Choosing emergence in [0.55, 0.85] s keeps
    both constraints satisfiable simultaneously:
      oracle-perception gap >= stopping distance   (candidate solvable)
      baseline-delayed gap  <  stopping distance   (baseline fails)
    """

    manifests: list[ScenarioManifest] = []
    for index in range(count):
        seed = seed_base + index
        rng = AnyRng(seed)
        ego_speed = _uniform(rng, 11.8, 12.0)
        ped_speed = _uniform(rng, 1.55, 1.85)
        angle = _uniform(rng, 84.0, 94.0)

        cross_s = OCCLUDER_POSITION_S_M + CROSS_S_MARGIN_M
        emergence_s = _uniform(rng, 4.3, 4.9)

        manifest = ScenarioManifest(
            record_id=new_record_id("scn"),
            scenario_id=f"occ-{seed}",
            created_at=datetime.now(timezone.utc),
            seed=seed,
            world_ref=WORLD,
            route=ROUTE,
            ego=EgoSpec(
                initial_speed_mps=ego_speed,
                max_braking_mps2=6.5,
                brake_actuation_delay_s=0.18,
                lane_width_m=3.5,
            ),
            pedestrian=PedestrianSpec(
                crossing_speed_mps=ped_speed,
                emergence_s=emergence_s,
                crossing_angle_deg=angle,
                start_lateral_m=2.4,
                end_lateral_m=-3.0,
            ),
            occluder=OccluderSpec(
                position_s_m=OCCLUDER_POSITION_S_M,
                lateral_offset_m=OCCLUDER_LATERAL_M,
            ),
            appearance=AppearanceSpec(
                brightness=_uniform(rng, 0.9, 1.1),
                contrast=_uniform(rng, 0.9, 1.1),
            ),
            provenance=OBSERVED_PROVENANCE,
            horizon_s=12.0,
        )
        manifests.append(manifest)
    return manifests


def derive_manifest(
    parent: ScenarioManifest,
    intervention: str,
    parameters: dict[str, float],
    *,
    drop_occluder: bool = False,
    emergence_shift_s: float = 0.0,
    ego_speed_override: Optional[float] = None,
    ped_speed_override: Optional[float] = None,
) -> ScenarioManifest:
    """Build an immutable derived scenario for one counterfactual arm.

    Derived identities are pure functions of (parent id, intervention,
    parameters): identical interventions reproduce byte-identical manifests.
    `created_at` inherits the parent's so the derivation chain stays
    deterministic; the wall-clock moment of derivation lives on the
    experiment record that caused it.
    """

    import hashlib

    seed_material = f"{parent.record_id}:{intervention}:{sorted(parameters.items())}"
    digest = hashlib.sha256(seed_material.encode()).hexdigest()
    short_digest = digest[:8]
    new_seed = (parent.seed + int(digest[:8], 16)) % (2**31)

    ego_kwargs: dict[str, float] = {}
    if ego_speed_override is not None:
        ego_kwargs["initial_speed_mps"] = ego_speed_override
    ped_kwargs: dict[str, float] = {}
    if ped_speed_override is not None:
        ped_kwargs["crossing_speed_mps"] = ped_speed_override

    pedestrian = None
    if parent.pedestrian is not None:
        payload = parent.pedestrian.model_dump()
        if emergence_shift_s != 0.0:
            payload["emergence_s"] = max(0.0, payload["emergence_s"] + emergence_shift_s)
        payload.update(ped_kwargs)
        pedestrian = PedestrianSpec.model_validate(payload)

    ego = EgoSpec.model_validate({**parent.ego.model_dump(), **ego_kwargs})

    derivation = DerivationInfo(intervention=intervention, parameters=dict(parameters))
    return ScenarioManifest(
        record_id=f"scn-{digest[:16]}",
        scenario_id=f"{parent.scenario_id}-d{short_digest}",
        created_at=parent.created_at,
        seed=new_seed,
        campaign_id=parent.campaign_id,
        parent_id=parent.record_id,
        world_ref=parent.world_ref,
        route=parent.route,
        ego=ego,
        pedestrian=pedestrian,
        occluder=None if drop_occluder else parent.occluder,
        appearance=parent.appearance,
        provenance=parent.provenance,
        derivation=derivation,
        dt_s=parent.dt_s,
        horizon_s=parent.horizon_s,
    )


ORACLE_FLAG_FIELDS = ("perception", "planner", "controller")


def oracle_from_flags(perception: bool = False, planner: bool = False, controller: bool = False) -> OracleConfig:
    return OracleConfig(perception=perception, planner=planner, controller=controller)
