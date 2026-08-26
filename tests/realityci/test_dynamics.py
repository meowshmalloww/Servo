from __future__ import annotations

from tools.realityci.scenario.dynamics import (
    EgoState,
    OccluderBox,
    advance_ego,
    circle_box_collision,
    circle_box_distance,
    ego_box,
    pedestrian_circle,
    segment_intersects_axis_aligned_rect,
    visible_fraction,
)
from tools.realityci.schemas import EgoSpec, PedestrianSpec
from tools.realityci.scenario.projection import CameraModel, project_point


RECT = OccluderBox(s_lo=39.25, s_hi=43.75, y_lo=1.175, y_hi=3.025, height_m=1.5)


def test_segment_rect_basic_cases() -> None:
    assert segment_intersects_axis_aligned_rect(10.0, 0.0, 47.5, 2.4, RECT)
    assert not segment_intersects_axis_aligned_rect(10.0, -1.0, 47.5, -0.5, RECT)
    assert segment_intersects_axis_aligned_rect(41.0, 2.0, 42.0, 2.5, RECT)
    assert not segment_intersects_axis_aligned_rect(44.0, 0.0, 46.0, 0.5, RECT)
    assert not segment_intersects_axis_aligned_rect(40.0, 3.5, 41.0, 3.4, RECT)


def test_segment_touching_corner_counts_as_intersection() -> None:
    assert segment_intersects_axis_aligned_rect(38.0, 0.0, 39.25, 1.175, RECT)


def test_visible_fraction_occluded_and_free() -> None:
    hidden = visible_fraction(
        camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=47.9, ped_y=2.35,
        ped_width_m=0.5, ped_height_m=1.4,
        horizontal_fov_half_deg=22.5, occluder=RECT,
    )
    free = visible_fraction(
        camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=47.9, ped_y=-0.8,
        ped_width_m=0.5, ped_height_m=1.75,
        horizontal_fov_half_deg=22.5, occluder=RECT,
    )
    none = visible_fraction(
        camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=47.9, ped_y=2.35,
        ped_width_m=0.5, ped_height_m=1.75,
        horizontal_fov_half_deg=22.5, occluder=None,
    )
    assert hidden == 0.0
    assert free == 1.0
    assert none == 1.0


def test_head_above_roofline_is_partially_visible() -> None:
    short_pedestrian = visible_fraction(
        camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=47.9, ped_y=2.35,
        ped_width_m=0.5, ped_height_m=1.4,
        horizontal_fov_half_deg=22.5, occluder=RECT,
    )
    tall_pedestrian = visible_fraction(
        camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=47.9, ped_y=2.35,
        ped_width_m=0.5, ped_height_m=1.75,
        horizontal_fov_half_deg=22.5, occluder=RECT,
    )
    assert tall_pedestrian > 0.0 > short_pedestrian - 0.001
    assert tall_pedestrian > short_pedestrian
    assert tall_pedestrian < 0.35


def test_visible_fraction_partial_emergence() -> None:
    fractions = [
        visible_fraction(
            camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=47.9, ped_y=y,
            ped_width_m=0.5, ped_height_m=1.75,
            horizontal_fov_half_deg=22.5, occluder=RECT,
        )
        for y in (2.2, 1.55, 1.35, 1.0)
    ]
    assert fractions[0] < fractions[1] < fractions[2] < fractions[3]
    assert fractions[3] == 1.0


def test_visible_fraction_out_of_fov() -> None:
    assert (
        visible_fraction(
            camera_s=14.3, camera_y=0.0, camera_z=1.45, ped_s=20.0, ped_y=60.0,
            ped_width_m=0.5, ped_height_m=1.75,
            horizontal_fov_half_deg=22.5, occluder=None,
        )
        == 0.0
    )


def test_braking_distance_matches_physics() -> None:
    spec = EgoSpec(initial_speed_mps=13.4, max_braking_mps2=6.5)
    state = EgoState(s_m=12.0, speed_mps=13.4, braking_active=False)
    distance = 0.0
    delay = spec.brake_actuation_delay_s
    dt = 0.02
    previous_speed = state.speed_mps
    while state.speed_mps > 0.0 and distance < 1000.0:
        state, delay = advance_ego(state, True, delay, dt, spec)
        distance += state.speed_mps * dt
        assert state.speed_mps <= previous_speed + 1e-9
        previous_speed = state.speed_mps
    ideal_braking_only = 13.4**2 / (2 * 6.5)
    envelope_with_delay = ideal_braking_only + 13.4 * spec.brake_actuation_delay_s + 2 * 13.4 * dt
    assert ideal_braking_only < distance < envelope_with_delay
    assert state.speed_mps == 0.0


def test_brake_release_resets_delay() -> None:
    spec = EgoSpec(initial_speed_mps=10.0)
    state = EgoState(s_m=0.0, speed_mps=10.0, braking_active=True)
    state, _ = advance_ego(state, False, 0.0, 0.02, spec)
    assert state.braking_active is False


def test_brake_request_respects_actuation_delay() -> None:
    spec = EgoSpec(initial_speed_mps=10.0, brake_actuation_delay_s=0.18)
    state = EgoState(s_m=0.0, speed_mps=10.0, braking_active=False)
    delay = spec.brake_actuation_delay_s
    dt = 0.02
    elapsed_without_braking = 0.0
    for _ in range(50):
        if state.braking_active:
            break
        state, delay = advance_ego(state, True, delay, dt, spec)
        elapsed_without_braking += dt
    assert state.braking_active is True
    assert abs(elapsed_without_braking - spec.brake_actuation_delay_s) < dt + 1e-9


def test_collision_predicates() -> None:
    spec = EgoSpec(initial_speed_mps=10.0)
    ego = EgoState(s_m=44.0, speed_mps=10.0, braking_active=False)
    rear, front, y_lo, y_hi = ego_box(ego, spec)
    s_p, y_p, radius = pedestrian_circle(44.0 + spec.length_m / 2.0 - 0.05, 0.0, _ped_spec())
    assert circle_box_collision(s_p, y_p, radius, (rear, front, y_lo, y_hi))
    far_distance = circle_box_distance(s_p + 5.0, y_p, radius, (rear, front, y_lo, y_hi))
    assert far_distance > 4.0


def _ped_spec() -> PedestrianSpec:
    return PedestrianSpec(
        crossing_speed_mps=1.6,
        emergence_s=0.4,
        crossing_angle_deg=87.0,
        start_lateral_m=2.4,
        end_lateral_m=-3.0,
    )


def test_camera_projection_geometry() -> None:
    camera = CameraModel.from_horizontal_fov(
        width_px=160,
        height_px=96,
        horizontal_fov_deg=45.0,
        height_m=1.45,
        forward_offset_m=2.3,
        pitch_down_deg=8.0,
    )
    horizon = camera.horizon_row()
    assert 0.0 < horizon < 48.0

    near_ground = project_point(camera, 5.0, 0.0, 0.0)
    mid_ground = project_point(camera, 15.0, 0.0, 0.0)
    far_ground = project_point(camera, 80.0, 0.0, 0.0)
    assert near_ground is not None and mid_ground is not None and far_ground is not None
    assert near_ground[1] > mid_ground[1] > far_ground[1]
    assert far_ground[1] >= horizon - 1.0

    head = project_point(camera, 20.0, 0.0, 1.75)
    feet = project_point(camera, 20.0, 0.0, 0.0)
    assert head is not None and feet is not None
    assert feet[1] > head[1]

    behind = project_point(camera, -5.0, 0.0, 0.0)
    assert behind is None

    lateral_right = project_point(camera, 20.0, 5.0, 0.5)
    lateral_left = project_point(camera, 20.0, -5.0, 0.5)
    assert lateral_right is not None and lateral_left is not None
    assert lateral_right[0] > 80.0 > lateral_left[0]
