"""Deterministic frame compositor.

Renders the declared virtual scene: a background layer (observed registered
source frames when configured, otherwise a procedural road) plus synthetic,
controllable actors projected through the virtual camera.  Actor pixels are
always generated here; collision truth always comes from scenario state.
Painter's algorithm: renderables are filled far-to-near so partial
emergence from behind the occluder falls out of the geometry naturally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..schemas.scenario import ScenarioManifest
from .dynamics import OccluderBox
from .projection import CameraModel, project_point


@dataclass(frozen=True)
class _Renderable:
    depth: float
    points: tuple[tuple[float, float], ...]
    color_bgr: tuple[int, int, int]


_HEAD_WORLD_RADIUS_M = 0.11


class FrameCompositor:
    WIDTH_PX = 160
    HEIGHT_PX = 96

    def __init__(self, manifest: ScenarioManifest, camera: CameraModel) -> None:
        self.manifest = manifest
        self.camera = camera
        self._frames: list[np.ndarray] | None = None
        seed = manifest.seed
        self._jacket_bgr = _pick_jacket_color(seed)
        self._pants_bgr = (
            max(0, int(self._jacket_bgr[0]) - 60),
            max(0, int(self._jacket_bgr[1]) - 60),
            max(0, int(self._jacket_bgr[2]) - 60),
        )
        self._car_bgr = _pick_car_color(seed)

    def attach_background_frames(self, directory: Path) -> int:
        paths = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() == ".png")
        if not paths:
            raise FileNotFoundError(f"no PNG frames under {directory}")
        loaded: list[np.ndarray] = []
        for path in paths:
            raw = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if raw is None:
                raise IOError(f"unreadable background frame: {path}")
            resized = cv2.resize(raw, (self.WIDTH_PX, self.HEIGHT_PX), interpolation=cv2.INTER_AREA)
            loaded.append(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
        self._frames = loaded
        return len(loaded)

    def render(
        self,
        ego_s: float,
        elapsed_s: float,
        occluder_box: OccluderBox | None,
        ped_position: tuple[float, float] | None,
        ped_height_m: float,
        ped_width_m: float,
    ) -> np.ndarray:
        del elapsed_s
        canvas = self._background(ego_s)
        renderables: list[_Renderable] = []

        if ped_position is not None and self.manifest.pedestrian is not None and ped_height_m > 0.0:
            renderables.extend(self._pedestrian_renderables(ped_position, ped_height_m, ped_width_m, ego_s))
        if occluder_box is not None:
            renderables.extend(self._occluder_renderables(occluder_box, ego_s))

        renderables.sort(key=lambda item: item.depth, reverse=True)
        for item in renderables:
            pts = np.array(item.points, dtype=np.int32)
            cv2.fillPoly(canvas, [pts], item.color_bgr)

        return self._apply_appearance(canvas)

    def _camera_depth(self, x_forward: float, z_up: float) -> float:
        dx = x_forward - self.camera.forward_offset_m
        dz = z_up - self.camera.height_m
        return dx * math.cos(self.camera.pitch_down_rad) - dz * math.sin(
            self.camera.pitch_down_rad
        )

    def _project_ring(
        self, points_3d: list[tuple[float, float, float]], ego_s: float
    ) -> tuple[list[tuple[float, float]] | None, float]:
        projected: list[tuple[float, float]] = []
        depth_sum = 0.0
        for x, y, z in points_3d:
            point = project_point(self.camera, x - ego_s, y, z)
            if point is None:
                return None, 0.0
            projected.append(point)
            depth_sum += self._camera_depth(x - ego_s, z)
        return projected, depth_sum / len(points_3d)

    def _background(self, ego_s: float) -> np.ndarray:
        if self._frames:
            span = self.manifest.route.end_s_m - self.manifest.route.start_s_m
            progress = (ego_s - self.manifest.route.start_s_m) / max(span, 1e-6)
            index = min(max(int(round(progress * (len(self._frames) - 1))), 0), len(self._frames) - 1)
            return self._frames[index].copy()
        return self._procedural_background(ego_s)

    def _procedural_background(self, ego_s: float) -> np.ndarray:
        height, width = self.HEIGHT_PX, self.WIDTH_PX
        rng = np.random.default_rng(self.manifest.seed + 77)
        horizon_row = max(self.camera.horizon_row(), 1.0)
        rows = np.arange(height, dtype=np.float32)
        sky_t = np.clip(rows / horizon_row, 0.0, 1.0)[:, None]
        road_t = np.clip((rows - horizon_row) / max(height - horizon_row, 1.0), 0.0, 1.0)[:, None]
        sky_top = np.float32([196, 172, 142])
        sky_bottom = np.float32([226, 214, 198])
        road_near = np.float32([58, 62, 66])
        road_far = np.float32([92, 94, 97])
        sky = sky_bottom[None, :] + (sky_top[None, :] - sky_bottom[None, :]) * sky_t
        road = road_far[None, :] + (road_near[None, :] - road_far[None, :]) * road_t
        img = np.where((rows < horizon_row)[:, None], sky, road).astype(np.uint8)
        img = np.tile(img[:, None, :], (1, width, 1))
        noise = rng.integers(-7, 8, size=(height, width, 1), dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        lane_y_world = self.manifest.ego.lane_center_lateral_m
        period = 9.0
        dash_length = 3.0
        start_k = math.floor((ego_s - 10.0) / period)
        for k in range(start_k, start_k + 14):
            s0 = k * period
            s1 = s0 + dash_length
            p0 = project_point(self.camera, s0 - ego_s + self.camera.forward_offset_m, lane_y_world, 0.0)
            p1 = project_point(self.camera, s1 - ego_s + self.camera.forward_offset_m, lane_y_world, 0.0)
            if p0 is None or p1 is None:
                continue
            cv2.line(
                img,
                (int(round(p0[0])), int(round(p0[1]))),
                (int(round(p1[0])), int(round(p1[1]))),
                (230, 230, 230),
                1,
            )
        return img

    def _occluder_renderables(self, box: OccluderBox, ego_s: float) -> list[_Renderable]:
        spec = self.manifest.occluder
        if spec is None:
            return []
        h = spec.height_m
        bottom = [
            (box.s_lo, box.y_lo),
            (box.s_hi, box.y_lo),
            (box.s_hi, box.y_hi),
            (box.s_lo, box.y_hi),
        ]
        renderables: list[_Renderable] = []
        for i in range(4):
            s0, y0 = bottom[i]
            s1, y1 = bottom[(i + 1) % 4]
            ring = [(s0, y0, 0.0), (s1, y1, 0.0), (s1, y1, h), (s0, y0, h)]
            projected, depth = self._project_ring(ring, ego_s)
            if projected is None:
                continue
            shade = 118 + (i % 2) * 34
            color = (
                int(min(255, self._car_bgr[0] * shade // 128)),
                int(min(255, self._car_bgr[1] * shade // 128)),
                int(min(255, self._car_bgr[2] * shade // 128)),
            )
            renderables.append(_Renderable(depth=depth, points=tuple(projected), color_bgr=color))
        roof_ring = [
            (box.s_lo, box.y_lo, h),
            (box.s_hi, box.y_lo, h),
            (box.s_hi, box.y_hi, h),
            (box.s_lo, box.y_hi, h),
        ]
        roof_projected, roof_depth = self._project_ring(roof_ring, ego_s)
        if roof_projected is not None:
            roof_color = (
                min(255, self._car_bgr[0] + 26),
                min(255, self._car_bgr[1] + 26),
                min(255, self._car_bgr[2] + 26),
            )
            renderables.append(
                _Renderable(depth=roof_depth + 1e-3, points=tuple(roof_projected), color_bgr=roof_color)
            )
        return renderables

    def _pedestrian_renderables(
        self, position: tuple[float, float], height_m: float, width_m: float, ego_s: float
    ) -> list[_Renderable]:
        s_p, y_p = position
        slices = 10
        torso_split_index = int(slices * 0.52)
        rings: list[tuple[float, tuple[float, float], tuple[float, float], float]] = []
        for k in range(slices + 1):
            frac = k / slices
            z = frac * height_m
            half_w = width_m / 2.0 * (0.55 if z < 0.45 * height_m else 1.0)
            left = project_point(self.camera, s_p - ego_s, y_p - half_w, z)
            right = project_point(self.camera, s_p - ego_s, y_p + half_w, z)
            if left is None or right is None:
                continue
            depth = self._camera_depth(s_p - ego_s, z)
            rings.append((z, (left[0], left[1]), (right[0], right[1]), depth))

        renderables: list[_Renderable] = []
        for lo, hi, color in (
            (0, torso_split_index + 1, self._pants_bgr),
            (torso_split_index, len(rings), self._jacket_bgr),
        ):
            band_rings = rings[lo:hi]
            if len(band_rings) < 2:
                continue
            ordered: list[tuple[float, float]] = []
            depths: list[float] = []
            for _, left_pt, _, depth in band_rings:
                ordered.append(left_pt)
                depths.append(depth)
            for _, _, right_pt, _ in reversed(band_rings):
                ordered.append(right_pt)
            renderables.append(
                _Renderable(depth=float(np.mean(depths)), points=tuple(ordered), color_bgr=color)
            )

        head = self._head_renderable(s_p, y_p, height_m, ego_s)
        if head is not None:
            renderables.append(head)
        return renderables

    def _head_renderable(
        self, s_p: float, y_p: float, height_m: float, ego_s: float
    ) -> _Renderable | None:
        head_z = height_m * 0.94
        center = project_point(self.camera, s_p - ego_s, y_p, head_z)
        left = project_point(self.camera, s_p - ego_s, y_p - _HEAD_WORLD_RADIUS_M, head_z)
        right = project_point(self.camera, s_p - ego_s, y_p + _HEAD_WORLD_RADIUS_M, head_z)
        if center is None or left is None or right is None:
            return None
        radius_px = abs(right[0] - left[0]) / 2.0
        if radius_px < 0.75:
            radius_px = 0.75
        octagon = [
            (
                center[0] + radius_px * math.cos(math.pi / 4 + k * math.pi / 4),
                center[1] + radius_px * math.sin(math.pi / 4 + k * math.pi / 4),
            )
            for k in range(8)
        ]
        return _Renderable(
            depth=self._camera_depth(s_p - ego_s, head_z),
            points=tuple(octagon),
            color_bgr=self._jacket_bgr,
        )

    def _apply_appearance(self, canvas: np.ndarray) -> np.ndarray:
        appearance = self.manifest.appearance
        adjusted = canvas.astype(np.float32) / 255.0
        adjusted = (adjusted - 0.5) * appearance.contrast + 0.5
        adjusted *= appearance.brightness
        return np.clip(adjusted * 255.0, 0, 255).astype(np.uint8)


def _pick_jacket_color(seed: int) -> tuple[int, int, int]:
    palette = [
        (210, 48, 40),
        (62, 84, 36),
        (34, 60, 170),
        (144, 128, 128),
        (40, 190, 200),
    ]
    return palette[seed % len(palette)]


def _pick_car_color(seed: int) -> tuple[int, int, int]:
    palette = [
        (78, 70, 70),
        (96, 90, 90),
        (130, 64, 52),
        (140, 88, 44),
    ]
    return palette[(seed // 7) % len(palette)]
