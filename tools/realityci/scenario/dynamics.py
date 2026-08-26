"""Deterministic kinematics, ground-truth visibility, and collision truth.

Physics lives here and only here.  The Gaussian/background layer never
contributes to visibility, motion, or collision decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..schemas.scenario import EgoSpec, OccluderSpec, PedestrianSpec


@dataclass(frozen=True)
class EgoState:
    s_m: float
    speed_mps: float
    braking_active: bool


@dataclass(frozen=True)
class OccluderBox:
    s_lo: float
    s_hi: float
    y_lo: float
    y_hi: float
    height_m: float

    @classmethod
    def from_spec(cls, occluder: OccluderSpec) -> "OccluderBox":
        return cls(
            s_lo=occluder.position_s_m - occluder.length_m / 2.0,
            s_hi=occluder.position_s_m + occluder.length_m / 2.0,
            y_lo=occluder.lateral_offset_m - occluder.width_m / 2.0,
            y_hi=occluder.lateral_offset_m + occluder.width_m / 2.0,
            height_m=occluder.height_m,
        )


def segment_intersects_axis_aligned_rect(
    ax: float, ay: float, bx: float, by: float, rect: OccluderBox
) -> bool:
    """Slab-method segment/AABB intersection in the (s, y) top-down plane."""

    dx = bx - ax
    dy = by - ay
    t_min = 0.0
    t_max = 1.0

    for origin, delta, lo, hi in ((ax, dx, rect.s_lo, rect.s_hi), (ay, dy, rect.y_lo, rect.y_hi)):
        if abs(delta) < 1e-12:
            if origin < lo or origin > hi:
                return False
            continue
        inv = 1.0 / delta
        t_near = (lo - origin) * inv
        t_far = (hi - origin) * inv
        if t_near > t_far:
            t_near, t_far = t_far, t_near
        t_min = max(t_min, t_near)
        t_max = min(t_max, t_far)
        if t_min > t_max:
            return False
    return True


def segment_intersects_box(
    ax: float, ay: float, az: float,
    bx: float, by: float, bz: float,
    box: OccluderBox,
) -> bool:
    """Slab-method segment/AABB intersection in 3D (s, y, z)."""

    t_min = 0.0
    t_max = 1.0
    for origin, delta, lo, hi in (
        (ax, bx - ax, box.s_lo, box.s_hi),
        (ay, by - ay, box.y_lo, box.y_hi),
        (az, bz - az, 0.0, box.height_m),
    ):
        if abs(delta) < 1e-12:
            if origin < lo or origin > hi:
                return False
            continue
        inv = 1.0 / delta
        t_near = (lo - origin) * inv
        t_far = (hi - origin) * inv
        if t_near > t_far:
            t_near, t_far = t_far, t_near
        t_min = max(t_min, t_near)
        t_max = min(t_max, t_far)
        if t_min > t_max:
            return False
    return True


_PEDESTRIAN_WIDTH_SAMPLES = 9
_PEDESTRIAN_HEIGHT_SAMPLES = 5


def pedestrian_world_position(
    cross_s_m: float, spec: PedestrianSpec, elapsed_s: float
) -> tuple[float, float]:
    """World position (s, y).  The walk starts at (cross_s, start_lateral)."""

    travelled = max(0.0, elapsed_s - spec.emergence_s) * spec.crossing_speed_mps
    angle_rad = math.radians(spec.crossing_angle_deg)
    direction_y = 1.0 if spec.end_lateral_m >= spec.start_lateral_m else -1.0
    ds = travelled * math.cos(angle_rad)
    dy = travelled * math.sin(angle_rad) * direction_y
    return cross_s_m + ds, spec.start_lateral_m + dy


def visible_fraction(
    camera_s: float,
    camera_y: float,
    camera_z: float,
    ped_s: float,
    ped_y: float,
    ped_width_m: float,
    ped_height_m: float,
    horizontal_fov_half_deg: float,
    occluder: OccluderBox | None,
) -> float:
    """Fraction of pedestrian body samples with an unoccluded sight ray.

    Rays are tested in full 3D so that a head visible above a parked-car
    roofline counts as visible, consistent with the rendered image.
    """

    if ped_s <= camera_s:
        return 0.0
    half_fov = math.radians(horizontal_fov_half_deg)
    center_bearing = math.atan2(ped_y - camera_y, ped_s - camera_s)
    if abs(center_bearing) > half_fov:
        return 0.0

    height_offsets = np_linspace(0.08 * ped_height_m, 0.97 * ped_height_m, _PEDESTRIAN_HEIGHT_SAMPLES)
    width_offsets = np_linspace(-ped_width_m / 2.0, ped_width_m / 2.0, _PEDESTRIAN_WIDTH_SAMPLES)

    total = 0
    visible = 0
    for z in height_offsets:
        for offset in width_offsets:
            sample_s = ped_s
            sample_y = ped_y + offset
            bearing = math.atan2(sample_y - camera_y, sample_s - camera_s)
            if abs(bearing) > half_fov:
                continue
            total += 1
            if occluder is None:
                visible += 1
                continue
            if not segment_intersects_box(
                camera_s, camera_y, camera_z,
                sample_s, sample_y, z,
                occluder,
            ):
                visible += 1
    if total == 0:
        return 0.0
    return visible / total


def np_linspace(lo: float, hi: float, count: int) -> list[float]:
    if count == 1:
        return [lo]
    step = (hi - lo) / (count - 1)
    return [lo + i * step for i in range(count)]


@dataclass(frozen=True)
class CollisionEvent:
    time_s: float
    relative_speed_mps: float


def ego_box(state: EgoState, spec: EgoSpec, front_offset_m: float = 0.0) -> tuple[float, float, float, float]:
    front = state.s_m + spec.length_m / 2.0 + front_offset_m
    rear = state.s_m - spec.length_m / 2.0
    return rear, front, -spec.width_m / 2.0, spec.width_m / 2.0


def pedestrian_circle(
    s_m: float, y_m: float, spec: PedestrianSpec
) -> tuple[float, float, float]:
    return s_m, y_m, spec.width_m / 2.0 + 0.12


def circle_box_collision(
    cx: float, cy: float, radius: float, box: tuple[float, float, float, float]
) -> bool:
    s_lo, s_hi, y_lo, y_hi = box
    nearest_s = min(max(cx, s_lo), s_hi)
    nearest_y = min(max(cy, y_lo), y_hi)
    ds = cx - nearest_s
    dy = cy - nearest_y
    return ds * ds + dy * dy < radius * radius


def circle_box_distance(
    cx: float, cy: float, radius: float, box: tuple[float, float, float, float]
) -> float:
    s_lo, s_hi, y_lo, y_hi = box
    nearest_s = min(max(cx, s_lo), s_hi)
    nearest_y = min(max(cy, y_lo), y_hi)
    ds = cx - nearest_s
    dy = cy - nearest_y
    return math.hypot(ds, dy) - radius


def advance_ego(
    state: EgoState,
    brake_requested: bool,
    actuation_delay_remaining_s: float,
    dt_s: float,
    spec: EgoSpec,
) -> tuple[EgoState, float]:
    """Advance ego one step.

    Brake commands take effect only after the actuation delay has elapsed.
    Returns the new state and the updated remaining delay.
    """

    braking = state.braking_active
    delay = actuation_delay_remaining_s
    if brake_requested and not state.braking_active:
        if delay <= 0.0:
            braking = True
        else:
            delay = max(0.0, delay - dt_s)
            if delay <= 0.0:
                braking = True
    elif not brake_requested and state.braking_active:
        braking = False
        delay = spec.brake_actuation_delay_s

    speed = state.speed_mps
    if braking:
        speed = max(0.0, speed - spec.max_braking_mps2 * dt_s)
    new_s = state.s_m + speed * dt_s
    return EgoState(s_m=new_s, speed_mps=speed, braking_active=braking), delay
