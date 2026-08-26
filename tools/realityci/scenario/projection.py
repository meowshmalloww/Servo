"""Virtual pinhole camera used by the scenario compositor.

The camera is a declared, self-consistent virtual sensor: it defines how
deterministic scenario-state actor positions map into the composited image.
It never re-projects or interprets the observed background pixels; the
background supplies appearance only.

Convention: X forward along the route, Y lateral right, Z up.  The camera
sits at height `height_m` above the road plane, `forward_offset_m` ahead of
the ego rear axle reference, pitched downward by `pitch_down_rad`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraModel:
    width_px: int
    height_px: int
    focal_px: float
    height_m: float
    forward_offset_m: float
    pitch_down_rad: float
    near_clip_m: float = 0.5

    @staticmethod
    def from_horizontal_fov(
        width_px: int,
        height_px: int,
        horizontal_fov_deg: float,
        height_m: float,
        forward_offset_m: float,
        pitch_down_deg: float,
    ) -> "CameraModel":
        if width_px <= 0 or height_px <= 0:
            raise ValueError("image dimensions must be positive")
        if not (1.0 < horizontal_fov_deg < 179.0):
            raise ValueError("horizontal fov out of range")
        if height_m <= 0.0:
            raise ValueError("camera height must be positive")
        focal_px = (width_px / 2.0) / math.tan(math.radians(horizontal_fov_deg) / 2.0)
        return CameraModel(
            width_px=width_px,
            height_px=height_px,
            focal_px=float(focal_px),
            height_m=height_m,
            forward_offset_m=forward_offset_m,
            pitch_down_rad=math.radians(pitch_down_deg),
        )

    def principal_point(self) -> tuple[float, float]:
        return self.width_px / 2.0, self.height_px / 2.0

    def horizon_row(self) -> float:
        _, cy = self.principal_point()
        return cy - self.focal_px * math.tan(self.pitch_down_rad)


def project_point(
    camera: CameraModel, x_forward_m: float, y_lateral_m: float, z_up_m: float
) -> tuple[float, float] | None:
    dx = x_forward_m - camera.forward_offset_m
    dz = z_up_m - camera.height_m
    sin_p = math.sin(camera.pitch_down_rad)
    cos_p = math.cos(camera.pitch_down_rad)

    z_cam = dx * cos_p - dz * sin_p
    up_cam = dx * sin_p + dz * cos_p
    right_cam = y_lateral_m

    if z_cam <= camera.near_clip_m:
        return None

    cx, cy = camera.principal_point()
    u = cx + camera.focal_px * right_cam / z_cam
    v = cy - camera.focal_px * up_cam / z_cam
    return u, v
