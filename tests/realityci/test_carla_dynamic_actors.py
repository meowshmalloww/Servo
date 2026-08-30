from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tools.realityci.schemas.simulation import ScenarioDescriptor
from tools.realityci.simulation.carla.actors import (
    apply_pedestrian_motion,
    finalize_pedestrian_spawn_receipt,
    pedestrian_crossing_distance_m,
    plan_one_pedestrian_crossing,
    spawn_one_pedestrian,
)
from tools.realityci.simulation.carla.cleanup import OwnedActors
from tools.realityci.simulation.carla.runner import _evidence_artifact_names


class _Location:
    def __init__(self, *, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z


class _Rotation:
    def __init__(self, *, yaw: float = 0.0) -> None:
        self.yaw = yaw


class _Transform:
    def __init__(self, location: _Location, rotation: _Rotation) -> None:
        self.location, self.rotation = location, rotation


class _WalkerControl:
    direction = None
    speed = 0.0
    jump = False

    def __init__(self) -> None:
        self.direction = None
        self.speed = 0.0
        self.jump = False


class _Blueprint:
    def __init__(self, blueprint_id: str) -> None:
        self.id = blueprint_id
        self.attributes: dict[str, str] = {}

    def has_attribute(self, name: str) -> bool:
        return name in {"is_invincible", "role_name"}

    def set_attribute(self, name: str, value: str) -> None:
        self.attributes[name] = value


class _BlueprintLibrary:
    def __init__(self, blueprints: list[_Blueprint]) -> None:
        self.blueprints = blueprints

    def filter(self, pattern: str) -> list[_Blueprint]:
        assert pattern == "walker.pedestrian.*"
        return list(self.blueprints)


class _Actor:
    def __init__(self, transform: _Transform, actor_id: int = 73) -> None:
        self.id = actor_id
        self.type_id = "walker.pedestrian.0001"
        self._transform = transform
        self.is_alive = True
        self.physics_enabled = False
        self.controls: list[_WalkerControl] = []
        self.stopped = False
        self.destroyed = False

    def set_simulate_physics(self, enabled: bool) -> None:
        self.physics_enabled = enabled

    def apply_control(self, control: _WalkerControl) -> None:
        self.controls.append(control)

    def get_transform(self) -> _Transform:
        return self._transform

    def stop(self) -> None:
        self.stopped = True

    def destroy(self) -> None:
        self.destroyed = True
        self.is_alive = False


class _World:
    def __init__(self, blueprints: list[_Blueprint], *, spawn: bool = True) -> None:
        self.library = _BlueprintLibrary(blueprints)
        self.spawn = spawn
        self.spawn_requests: list[tuple[_Blueprint, _Transform]] = []
        self.actor: _Actor | None = None

    def get_blueprint_library(self) -> _BlueprintLibrary:
        return self.library

    def try_spawn_actor(self, blueprint: _Blueprint, transform: _Transform):
        self.spawn_requests.append((blueprint, transform))
        if not self.spawn:
            return None
        self.actor = _Actor(transform)
        return self.actor


_CARLA = SimpleNamespace(
    Location=_Location,
    Rotation=_Rotation,
    Transform=_Transform,
    Vector3D=_Location,
    WalkerControl=_WalkerControl,
)


def test_route_relative_pedestrian_plan_is_deterministic_and_crosses_lane() -> None:
    route = ((0.0, 0.0, 1.0), (40.0, 0.0, 1.0), (100.0, 0.0, 2.0))
    left = plan_one_pedestrian_crossing(route, seed=42)
    repeated = plan_one_pedestrian_crossing(route, seed=42)
    right = plan_one_pedestrian_crossing(route, seed=43)

    assert left == repeated
    assert left.crossing_center == pytest.approx((58.0, 0.0, 1.3))
    assert left.spawn_position == pytest.approx((58.0, 1.25, 1.55))
    assert left.direction == pytest.approx((0.0, -1.0, 0.0))
    assert 0.05 <= left.activation_progress < left.route_fraction
    assert right.spawn_position[1] == pytest.approx(-1.25)
    assert right.direction == pytest.approx((0.0, 1.0, 0.0))


@pytest.mark.parametrize(
    "route,error",
    [
        (((0.0, 0.0, 0.0),), "at least two route points"),
        (((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), "at least two metres"),
        (((0.0, 0.0, 0.0), (float("nan"), 3.0, 0.0)), "finite"),
    ],
)
def test_route_relative_pedestrian_plan_rejects_invalid_routes(route, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        plan_one_pedestrian_crossing(route, seed=1)


def test_spawned_pedestrian_uses_native_walker_control_and_is_not_teleported() -> None:
    blueprints = [_Blueprint("walker.pedestrian.0002"), _Blueprint("walker.pedestrian.0001")]
    world = _World(blueprints)
    owned = OwnedActors("sim-0123456789abcdef")

    pedestrian = spawn_one_pedestrian(
        world,
        _CARLA,
        ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0)),
        seed=42,
        owned=owned,
    )

    assert pedestrian.actor is world.actor
    assert pedestrian.actor in owned.actors
    assert pedestrian.actor.physics_enabled is False
    assert pedestrian.actor.controls[-1].speed == 0.0
    assert pedestrian.receipt["actor_id"] == 73
    assert pedestrian.receipt["blueprint_id"] == "walker.pedestrian.0001"
    assert pedestrian.receipt["ownership"] == {
        "session_id": "sim-0123456789abcdef",
        "cleanup_registered": True,
    }
    assert pedestrian.receipt["spawn_provenance"]["method"] == (
        "deterministic-route-relative-crossing/v1"
    )
    assert pedestrian.receipt["motion"]["controller"] == "carla.WalkerControl"
    assert pedestrian.receipt["motion"]["teleported_during_run"] is False
    assert pedestrian.receipt["motion"]["simulate_physics_forced"] is False
    assert pedestrian.receipt["motion"]["bounded_crossing_distance_m"] == pytest.approx(2.5)

    finalized = finalize_pedestrian_spawn_receipt(pedestrian)
    assert finalized["spawn_provenance"]["warmup_surface_gate_pass"] is True
    assert finalized["spawn_provenance"]["actual_spawn_carla"]["warmup_drift_m"] == 0.0
    assert finalized["spawn_provenance"]["actual_spawn_carla"]["warmup_horizontal_drift_m"] == 0.0
    assert finalized["spawn_provenance"]["actual_spawn_carla"]["warmup_vertical_settle_m"] == 0.0

    apply_pedestrian_motion(_CARLA, pedestrian, active=True)
    assert pedestrian.actor.controls[-1].speed == pytest.approx(1.4)
    assert pedestrian.actor.controls[-1].direction.y == pytest.approx(-1.0)

    pedestrian.actor._transform.location.y -= 2.5
    assert pedestrian_crossing_distance_m(pedestrian) == pytest.approx(2.5)

    cleanup = owned.cleanup()
    assert cleanup["destroyed"] == 1
    assert pedestrian.actor.stopped and pedestrian.actor.destroyed


def test_pedestrian_warmup_fails_closed_if_actor_falls_through_surface() -> None:
    world = _World([_Blueprint("walker.pedestrian.0001")])
    pedestrian = spawn_one_pedestrian(
        world,
        _CARLA,
        ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0)),
        seed=42,
        owned=OwnedActors("sim-0123456789abcdef"),
    )
    pedestrian.actor._transform.location.z -= 10.0

    with pytest.raises(RuntimeError, match="left the supported road surface"):
        finalize_pedestrian_spawn_receipt(pedestrian)


def test_pedestrian_warmup_allows_bounded_vertical_gravity_settle() -> None:
    world = _World([_Blueprint("walker.pedestrian.0001")])
    pedestrian = spawn_one_pedestrian(
        world,
        _CARLA,
        ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0)),
        seed=42,
        owned=OwnedActors("sim-0123456789abcdef"),
    )
    pedestrian.actor._transform.location.z -= 1.25

    finalized = finalize_pedestrian_spawn_receipt(pedestrian)
    actual = finalized["spawn_provenance"]["actual_spawn_carla"]
    assert actual["warmup_horizontal_drift_m"] == 0.0
    assert actual["warmup_vertical_settle_m"] == pytest.approx(1.25)
    assert finalized["spawn_provenance"]["warmup_surface_gate_pass"] is True


def test_pedestrian_spawn_fails_closed_without_blueprint_or_free_pose() -> None:
    route = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
    with pytest.raises(RuntimeError, match="no walker blueprints"):
        spawn_one_pedestrian(
            _World([]), _CARLA, route, seed=1,
            owned=OwnedActors("sim-0123456789abcdef"),
        )
    with pytest.raises(RuntimeError, match="failed to spawn"):
        spawn_one_pedestrian(
            _World([_Blueprint("walker.pedestrian.0001")], spawn=False),
            _CARLA,
            route,
            seed=1,
            owned=OwnedActors("sim-0123456789abcdef"),
        )


def test_one_pedestrian_manifest_profile_and_receipts_are_sealed() -> None:
    scenario = ScenarioDescriptor(seed=9, dynamic_actor_profile="one-pedestrian")
    assert scenario.dynamic_actor_profile == "one-pedestrian"
    with pytest.raises(ValidationError):
        ScenarioDescriptor(seed=9, dynamic_actor_profile="crowd")
    artifacts = _evidence_artifact_names(("front",))
    assert "dynamic-actors.json" in artifacts
    assert "dynamic-actor-events.jsonl" in artifacts
