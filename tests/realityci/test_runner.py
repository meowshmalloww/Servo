from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from tools.realityci.scenario.runner import OracleConfig, RunnerTiming, ScenarioRunner
from tools.realityci.schemas import (
    AppearanceSpec,
    EgoSpec,
    OccluderSpec,
    PedestrianSpec,
    RouteSpec,
    RunResult,
    ScenarioManifest,
    ScenarioProvenance,
    WorldRef,
)
from tools.realityci.hashing import new_record_id


PROVENANCE = ScenarioProvenance(
    background="procedural-deterministic-road",
    actors="synthetic-controllable",
    collision_truth="deterministic-scenario-state",
)


def make_manifest(**overrides: object) -> ScenarioManifest:
    fields = dict(
        record_id=new_record_id("scn"),
        scenario_id="test-occ-ped",
        seed=11,
        created_at=__import__("datetime").datetime(2026, 8, 23, tzinfo=__import__("datetime").timezone.utc),
        world_ref=WorldRef(world_id="virtual-test", source_tag="procedural"),
        route=RouteSpec(start_s_m=12.0, end_s_m=58.0, speed_limit_mps=15.0),
        ego=EgoSpec(
            initial_speed_mps=13.4,
            max_braking_mps2=6.5,
            brake_actuation_delay_s=0.18,
            lane_width_m=3.5,
        ),
        pedestrian=PedestrianSpec(
            crossing_speed_mps=1.6,
            emergence_s=0.4,
            crossing_angle_deg=87.0,
            start_lateral_m=2.4,
            end_lateral_m=-3.0,
        ),
        occluder=OccluderSpec(position_s_m=38.0, lateral_offset_m=2.1),
        appearance=AppearanceSpec(),
        provenance=PROVENANCE,
        horizon_s=12.0,
    )
    fields.update(overrides)
    return ScenarioManifest.model_validate(fields)


class ScriptedPolicy:
    def __init__(self, risks: list[float] | None = None, constant: float | None = None) -> None:
        self._risks = list(risks) if risks is not None else []
        self._constant = constant
        self._index = 0

    @property
    def descriptor(self):  # pragma: no cover - interface shim for tests only
        raise NotImplementedError

    def reset(self, seed: int) -> None:
        self._index = 0

    def observe(self, packet) -> float:
        if self._constant is not None:
            return self._constant
        value = self._risks[min(self._index, len(self._risks) - 1)]
        self._index += 1
        return value


@dataclass
class NeverBrake:
    def reset(self, seed: int) -> None: ...

    def observe(self, packet) -> float:
        return 0.0


def test_never_brake_collides() -> None:
    manifest = make_manifest()
    outcome = ScenarioRunner(manifest, NeverBrake()).run()
    assert outcome.result == RunResult.COLLISION
    assert outcome.collision_time_s is not None
    assert outcome.brake_command_s is None
    assert outcome.min_pedestrian_distance_m is not None
    assert outcome.min_pedestrian_distance_m < 0.4


def test_always_brake_stops_in_time() -> None:
    manifest = make_manifest()
    timing = RunnerTiming(detection_threshold=0.4)
    outcome = ScenarioRunner(
        manifest, ScriptedPolicy(constant=0.9), timing=timing, capture_frames=True
    ).run()
    assert outcome.result in (RunResult.SUCCESS, RunResult.NEAR_MISS)
    assert outcome.brake_requested is True
    assert outcome.final_ego_speed_mps < 0.06


def test_oracle_perception_prevents_collision() -> None:
    manifest = make_manifest()
    outcome = ScenarioRunner(
        manifest,
        NeverBrake(),
        oracle=OracleConfig(perception=True),
    ).run()
    assert outcome.result in (RunResult.SUCCESS, RunResult.NEAR_MISS)
    assert outcome.first_policy_detection_s is not None
    assert outcome.first_ground_truth_visibility_s is not None
    delay = outcome.first_policy_detection_s - outcome.first_ground_truth_visibility_s
    assert abs(delay) < 0.05


def test_late_scripted_detection_collides_but_early_succeeds() -> None:
    manifest = make_manifest()
    dt = manifest.dt_s
    steps_per_frame = int(round((1.0 / 10.0) / dt))

    late_risks = [0.0] * (steps_per_frame * 14) + [0.95]
    late = ScenarioRunner(manifest, ScriptedPolicy(risks=late_risks), capture_frames=True).run()
    early_risks = [0.95]
    early = ScenarioRunner(manifest, ScriptedPolicy(risks=early_risks), capture_frames=True).run()

    assert late.result == RunResult.COLLISION
    assert early.result in (RunResult.SUCCESS, RunResult.NEAR_MISS)


def test_held_detection_persists_between_camera_frames() -> None:
    manifest = make_manifest()
    dt = manifest.dt_s
    steps_per_frame = int(round((1.0 / 10.0) / dt))

    class CountingPolicy(ScriptedPolicy):
        def __init__(self, risks):
            super().__init__(risks=risks)
            self.calls = 0

        def observe(self, packet):
            self.calls += 1
            return super().observe(packet)

    sustained_pulse = [0.95] * 4 + [0.0] * 40
    policy = CountingPolicy(risks=sustained_pulse)
    outcome = ScenarioRunner(manifest, policy, capture_frames=True).run()

    assert policy.calls == len(outcome.frames)
    assert outcome.brake_requested is True
    assert outcome.min_ego_speed_mps < manifest.ego.initial_speed_mps - 1.0
    assert outcome.final_ego_speed_mps > 0.5


def test_identical_inputs_produce_identical_outcomes() -> None:
    manifest_a = make_manifest(seed=7)
    manifest_b = make_manifest(seed=7)
    outcome_a = ScenarioRunner(manifest_a, ScriptedPolicy(constant=0.6), capture_frames=True).run()
    outcome_b = ScenarioRunner(manifest_b, ScriptedPolicy(constant=0.6), capture_frames=True).run()

    rows_a = [row.__dict__ for row in outcome_a.telemetry]
    rows_b = [row.__dict__ for row in outcome_b.telemetry]

    def _default(obj: object) -> str:
        if isinstance(obj, np.ndarray):
            return f"ndarray-{obj.shape}"
        raise TypeError

    assert json.dumps(rows_a, default=_default) == json.dumps(rows_b, default=_default)
    assert outcome_a.frames.keys() == outcome_b.frames.keys()
    for key in outcome_a.frames:
        assert np.array_equal(outcome_a.frames[key], outcome_b.frames[key], equal_nan=False)


def test_no_pedestrian_scenario_succeeds() -> None:
    manifest = make_manifest(pedestrian=None)
    outcome = ScenarioRunner(manifest, NeverBrake()).run()
    assert outcome.result == RunResult.SUCCESS
    assert outcome.brake_requested is False


def test_frames_are_captured_at_declared_rate() -> None:
    manifest = make_manifest()
    outcome = ScenarioRunner(manifest, NeverBrake(), capture_frames=True).run()
    assert len(outcome.frames) >= 10
    for frame in outcome.frames.values():
        assert frame.shape == (96, 160, 3)
        assert frame.dtype == np.uint8


def test_compositor_shows_pedestrian_only_when_visible() -> None:
    from tools.realityci.scenario.compositor import FrameCompositor
    from tools.realityci.scenario.projection import CameraModel
    from tools.realityci.scenario.dynamics import OccluderBox

    camera = CameraModel.from_horizontal_fov(
        width_px=160, height_px=96, horizontal_fov_deg=45.0,
        height_m=1.45, forward_offset_m=2.3, pitch_down_deg=8.0,
    )
    manifest = make_manifest()
    compositor = FrameCompositor(manifest, camera)

    occluder = OccluderBox.from_spec(manifest.occluder)
    hidden_frame = compositor.render(ego_s=16.0, elapsed_s=0.5, occluder_box=occluder,
                                     ped_position=(44.0, 2.35), ped_height_m=1.75, ped_width_m=0.5)
    near_visible_frame = compositor.render(ego_s=16.0, elapsed_s=0.5, occluder_box=None,
                                           ped_position=(30.0, -0.5), ped_height_m=1.75, ped_width_m=0.5)
    far_visible_frame = compositor.render(ego_s=16.0, elapsed_s=0.5, occluder_box=None,
                                          ped_position=(44.0, -0.5), ped_height_m=1.75, ped_width_m=0.5)

    jacket_color = np.array(compositor._jacket_bgr, dtype=np.int32)
    def jacket_pixels(frame: np.ndarray) -> int:
        distance = np.abs(frame.astype(np.int32) - jacket_color[None, None, :]).sum(axis=2)
        return int((distance < 30).sum())

    hidden_pixels = jacket_pixels(hidden_frame)
    near_pixels = jacket_pixels(near_visible_frame)
    far_pixels = jacket_pixels(far_visible_frame)
    assert 0 <= hidden_pixels < 60
    assert near_pixels > 80
    assert 0 < far_pixels < near_pixels
    assert near_pixels > hidden_pixels * 3

    again_hidden = compositor.render(ego_s=16.0, elapsed_s=0.5, occluder_box=occluder,
                                     ped_position=(44.0, 2.35), ped_height_m=1.75, ped_width_m=0.5)
    assert np.array_equal(hidden_frame, again_hidden)


def test_background_frames_attach_and_flow(tmp_path) -> None:
    from tools.realityci.scenario.compositor import FrameCompositor
    from tools.realityci.scenario.projection import CameraModel

    rng = np.random.default_rng(3)
    for index in range(4):
        image = rng.integers(0, 255, size=(96, 160, 3), dtype=np.uint8)
        __import__("cv2").imwrite(str(tmp_path / f"f{index:04d}.png"), image)

    camera = CameraModel.from_horizontal_fov(
        width_px=160, height_px=96, horizontal_fov_deg=45.0,
        height_m=1.45, forward_offset_m=2.3, pitch_down_deg=8.0,
    )
    compositor = FrameCompositor(make_manifest(), camera)
    count = compositor.attach_background_frames(tmp_path)
    assert count == 4

    first = compositor.render(ego_s=13.0, elapsed_s=0.0, occluder_box=None,
                              ped_position=None, ped_height_m=0.0, ped_width_m=0.0)
    last = compositor.render(ego_s=57.0, elapsed_s=3.0, occluder_box=None,
                             ped_position=None, ped_height_m=0.0, ped_width_m=0.0)
    assert not np.array_equal(first, last)
