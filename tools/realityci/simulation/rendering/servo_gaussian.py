"""Bounded headless gsplat renderer using Servo's published Gaussian PLY contract."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from ...hashing import payload_hash, sha256_file
from ...schemas.driving import ObservationSource
from ..carla.coordinates import matrix_to_quaternion, quaternion_to_matrix
from ...schemas.driving import Pose, Vector3
from .base import ObservationRenderRequest, ObservationRenderResult, ObservationRenderer


class ServoGaussianObservationRenderer(ObservationRenderer):
    VERSION = "servo-headless-gsplat-live-camera/v3"

    def __init__(
        self,
        world_manifest: Path,
        *,
        device: str = "cuda",
        minimum_coverage: float = 0.50,
        weather: str = "clear",
        snow_accumulation: float = 0.90,
        preload_route_tiles: bool = True,
    ) -> None:
        if weather not in {"clear", "snow"}:
            raise ValueError(f"unsupported Gaussian simulation weather: {weather}")
        if not 0.0 <= snow_accumulation <= 1.0:
            raise ValueError("snow_accumulation must be in [0, 1]")
        self.world_manifest = world_manifest.resolve()
        self.minimum_coverage = minimum_coverage
        self.weather = weather
        self.snow_accumulation = snow_accumulation if weather == "snow" else 0.0
        manifest = json.loads(self.world_manifest.read_text(encoding="utf-8"))
        if manifest.get("schema") != "servo.gaussian-world/v1":
            raise ValueError("Gaussian renderer requires servo.gaussian-world/v1")
        self.world_root = self.world_manifest.parent
        self.ply_path = (self.world_root / manifest["artifacts"]["ply"]).resolve()
        self.ply_path.relative_to(self.world_root)
        if not self.ply_path.is_file():
            raise ValueError("published Gaussian PLY is missing")
        import torch
        from tools.reconstruction.servo_gsplat_runtime import prepare_gsplat_runtime
        from tools.reconstruction.servo_audit_world import load_gaussians

        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("Servo Gaussian policy rendering requested CUDA, but CUDA is unavailable")
        # The packaged Windows worker must use Servo's hash-checked native
        # gsplat wheel.  Importing gsplat directly can fall back to a JIT build
        # and incorrectly require a Visual Studio developer shell at runtime.
        # This loader performs no installation and records the exact binary
        # receipt used by the renderer.
        self.gsplat_runtime = prepare_gsplat_runtime()
        self.device = device
        self._load_gaussians = load_gaussians
        self.gaussians, self.sh_degree = load_gaussians(self.ply_path, device)
        self._active_tile_index = 0
        self._tile_cache: dict[int, tuple[dict, int]] = {
            0: (self.gaussians, self.sh_degree)
        }
        route_bundle_name = manifest["artifacts"].get("routeBundle")
        self.route_tiles: list[dict] = []
        if route_bundle_name:
            route_bundle_path = (self.world_root / route_bundle_name).resolve()
            route_bundle_path.relative_to(self.world_root)
            route_bundle = json.loads(route_bundle_path.read_text(encoding="utf-8"))
            for tile in route_bundle.get("tiles", []):
                tile_path = (self.world_root / tile["ply"]).resolve()
                tile_path.relative_to(self.world_root)
                self.route_tiles.append({**tile, "path": tile_path})
        # A T5 route is deliberately split to keep the native interactive
        # viewer bounded, but a deterministic CARLA run cannot pause for PLY
        # parsing every time it crosses an overlap.  All five published tiles
        # occupy about the same memory as the original aggregate PLY and fit
        # the qualified 12 GiB profile.  Load them before synchronous ticking;
        # if allocation fails, release the partial cache and retain the safe
        # one-tile fallback rather than failing halfway through a drive.
        self.preload_route_tiles = bool(preload_route_tiles)
        if self.preload_route_tiles and len(self.route_tiles) > 1:
            try:
                for index, tile in enumerate(self.route_tiles):
                    if index in self._tile_cache:
                        continue
                    self._tile_cache[index] = self._load_gaussians(tile["path"], self.device)
            except (RuntimeError, MemoryError):
                first = self._tile_cache.get(0, (self.gaussians, self.sh_degree))
                self._tile_cache.clear()
                self._tile_cache[0] = first
        self.cameras_path = (self.world_root / manifest["artifacts"]["cameras"]).resolve()
        self.cameras_path.relative_to(self.world_root)
        cameras_document = json.loads(self.cameras_path.read_text(encoding="utf-8"))
        cameras = cameras_document.get("cameras", [])
        self.registered_c2w = np.asarray(
            [camera["cameraToWorldNormalized"] for camera in cameras], dtype=np.float32
        )
        if self.registered_c2w.ndim != 3 or self.registered_c2w.shape[1:] != (4, 4):
            raise ValueError("published registered camera transforms are missing or invalid")
        self.registered_positions = self.registered_c2w[:, :3, 3]
        camera_ups = -self.registered_c2w[:, :3, 1]
        reference_up = camera_ups[0]
        camera_ups = np.where(
            (camera_ups @ reference_up)[:, None] < 0.0,
            -camera_ups,
            camera_ups,
        )
        navigation_up = np.mean(camera_ups, axis=0)
        navigation_up /= max(float(np.linalg.norm(navigation_up)), 1e-8)
        self.navigation_up = navigation_up.astype(np.float32)
        self.weather_receipt = {
            "schema_name": "servo.gaussian-surface-weather/v1",
            "condition": self.weather,
            "visual_method": (
                "inferred-up-facing-gaussian-surface-deposition/v1"
                if self.weather == "snow" else "unchanged-observed-appearance"
            ),
            "snow_accumulation": self.snow_accumulation,
            "metric_snow_depth": False,
            "climatenerf_qualified": False,
            "collision_geometry_changed": False,
            "route_tile_cache": (
                "all-gpu-preloaded" if self.preload_route_tiles else "active-tile-only"
            ),
        }
        self.weather_hash = payload_hash(self.weather_receipt)
        self.surface_snow_stats: list[dict[str, float]] = []
        if self.weather == "snow":
            for gaussian_set, _ in self._tile_cache.values():
                self.surface_snow_stats.append(
                    self.apply_surface_snow(
                        gaussian_set, self.navigation_up, self.snow_accumulation
                    )
                )
        # Explicit registered-camera anchors are reserved for controlled audit
        # captures.  Live policy/chase rendering uses the exact CARLA camera
        # pose; silently snapping it made the world look static while telemetry
        # claimed that the vehicle was moving.
        self._frame_anchors: dict[int, tuple[int, np.ndarray, np.ndarray]] = {}
        self.source_hashes = (
            sha256_file(str(self.ply_path)),
            sha256_file(str(self.cameras_path)),
            sha256_file(str(self.world_manifest)),
            self.weather_hash,
        )

    @staticmethod
    def apply_surface_snow(
        gaussians: dict,
        navigation_up: np.ndarray,
        amount: float,
    ) -> dict[str, float]:
        """Deposit visual snow on supported, up-facing Gaussian surfaces.

        This is a deterministic surface treatment derived from each splat's
        shortest covariance axis. It changes appearance only: it does not
        invent depth, change collision geometry, or claim metric snow mass.
        """
        import torch

        bounded = float(np.clip(amount, 0.0, 1.0))
        if bounded <= 0.0 or gaussians["means"].shape[0] == 0:
            return {"mean_weight": 0.0, "affected_fraction": 0.0}
        with torch.inference_mode():
            scales = gaussians["scales"]
            quats = gaussians["quats"]
            quats = quats / torch.linalg.vector_norm(quats, dim=1, keepdim=True).clamp_min(1e-8)
            w, x, y, z = quats.unbind(dim=1)
            rotations = torch.stack(
                (
                    1 - 2 * (y * y + z * z), 2 * (x * y - w * z),
                    2 * (x * z + w * y), 2 * (x * y + w * z),
                    1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
                    2 * (x * z - w * y), 2 * (y * z + w * x),
                    1 - 2 * (x * x + y * y),
                ),
                dim=1,
            ).reshape(-1, 3, 3)
            shortest = torch.argmin(scales, dim=1)
            row = torch.arange(scales.shape[0], device=scales.device)
            normals = rotations[row, :, shortest]
            up = torch.as_tensor(
                navigation_up, dtype=normals.dtype, device=normals.device
            )
            up = up / torch.linalg.vector_norm(up).clamp_min(1e-8)
            alignment = torch.abs(torch.sum(normals * up[None, :], dim=1))
            anisotropy_support = 1.0 - (
                torch.amin(scales, dim=1)
                / torch.amax(scales, dim=1).clamp_min(1e-8)
            )

            def smoothstep(edge0: float, edge1: float, value):
                t = ((value - edge0) / (edge1 - edge0)).clamp(0.0, 1.0)
                return t * t * (3.0 - 2.0 * t)

            deposit = (
                bounded
                * smoothstep(0.38, 0.82, alignment)
                * smoothstep(0.22, 0.72, anisotropy_support)
            ).clamp(0.0, 1.0)
            colors = gaussians["colors"]
            weight = deposit[:, None]
            snow_rgb = torch.tensor(
                (0.88, 0.91, 0.94), dtype=colors.dtype, device=colors.device
            )
            snow_dc = (snow_rgb - 0.5) / 0.28209479177387814
            colors[:, 0, :].mul_(1.0 - weight).add_(weight * snow_dc[None, :])
            if colors.shape[1] > 1:
                colors[:, 1:, :].mul_((1.0 - 0.72 * deposit)[:, None, None])
            return {
                "mean_weight": float(deposit.mean().item()),
                "affected_fraction": float((deposit >= 0.10).float().mean().item()),
            }

    def _activate_tile(self, camera_index: int) -> None:
        if not self.route_tiles:
            return
        candidates = [
            (index, tile) for index, tile in enumerate(self.route_tiles)
            if int(tile["cameraStart"]) <= camera_index < int(tile["cameraEndExclusive"])
        ]
        if not candidates:
            raise RuntimeError(f"registered camera {camera_index} is outside every T5 route tile")
        # In an overlap, choose the tile with the greatest distance from an
        # edge so transitions occur where both local fields have support.
        selected_index, selected = max(
            candidates,
            key=lambda item: min(
                camera_index - int(item[1]["cameraStart"]),
                int(item[1]["cameraEndExclusive"]) - 1 - camera_index,
            ),
        )
        if selected_index == self._active_tile_index:
            return
        cached = self._tile_cache.get(selected_index)
        if cached is None:
            # A low-memory run must retain exactly one GPU tile. The previous
            # implementation kept tile 0 in `_tile_cache` while loading tile
            # 1, temporarily allocating two multi-million-splat fields next
            # to DriveMA and causing 20-second policy timeouts at handoff.
            if not self.preload_route_tiles:
                previous = self._tile_cache.pop(self._active_tile_index, None)
                if previous is not None:
                    previous[0].clear()
                else:
                    self.gaussians.clear()
                self.gaussians = {}
                if self.device == "cuda":
                    import torch
                    torch.cuda.empty_cache()
            cached = self._load_gaussians(selected["path"], self.device)
            if not self.preload_route_tiles:
                self._tile_cache[selected_index] = cached
            if self.weather == "snow":
                self.surface_snow_stats.append(
                    self.apply_surface_snow(
                        cached[0], self.navigation_up, self.snow_accumulation
                    )
                )
        self.gaussians, self.sh_degree = cached
        self.ply_path = selected["path"]
        self._active_tile_index = selected_index
        self.source_hashes = (
            sha256_file(str(self.ply_path)),
            sha256_file(str(self.cameras_path)),
            sha256_file(str(self.world_manifest)),
            self.weather_hash,
        )

    @property
    def source(self) -> ObservationSource:
        return ObservationSource.SERVO_GAUSSIAN

    def nearest_registered_pose(self, requested_pose: Pose) -> tuple[int, Pose]:
        """Return the exact published camera used for a requested world position.

        CARLA evidence sensors use this before capture so the native foreground
        and Gaussian background have the same registered optical orientation.
        This is deliberately public: silently snapping only the Gaussian side
        produces a plausible-looking but geometrically invalid composite.
        """
        requested_position = np.asarray(
            (requested_pose.position.x, requested_pose.position.y, requested_pose.position.z), dtype=np.float32
        )
        index = int(np.argmin(np.linalg.norm(self.registered_positions - requested_position, axis=1)))
        c2w = self.registered_c2w[index]
        return index, Pose(
            position=Vector3(x=float(c2w[0, 3]), y=float(c2w[1, 3]), z=float(c2w[2, 3])),
            orientation=matrix_to_quaternion(c2w[:3, :3]),
        )

    def registered_pose(self, index: int) -> Pose:
        if not 0 <= index < len(self.registered_c2w):
            raise IndexError(f"registered camera index out of range: {index}")
        c2w = self.registered_c2w[index]
        return Pose(
            position=Vector3(x=float(c2w[0, 3]), y=float(c2w[1, 3]), z=float(c2w[2, 3])),
            orientation=matrix_to_quaternion(c2w[:3, :3]),
        )

    def registered_camera_matrix(self, index: int) -> np.ndarray:
        """Return a copy of the published OpenCV camera-to-world matrix."""
        if not 0 <= index < len(self.registered_c2w):
            raise IndexError(f"registered camera index out of range: {index}")
        return self.registered_c2w[index].copy()

    @property
    def registered_camera_count(self) -> int:
        return len(self.registered_c2w)

    def force_frame_anchor(self, frame_id: int, index: int) -> None:
        """Bind an evidence frame to a route-selected registered camera."""
        pose = self.registered_pose(index)
        rotation = quaternion_to_matrix(pose.orientation).astype(np.float32)
        self._frame_anchors[frame_id] = (index, rotation, self.registered_c2w[index].copy())

    def clear_frame_anchor(self, frame_id: int) -> None:
        self._frame_anchors.pop(frame_id, None)

    def render(self, request: ObservationRenderRequest) -> ObservationRenderResult:
        import torch
        from gsplat import rasterization

        started = time.perf_counter()
        requested_pose = request.camera_pose_servo
        requested_rotation = quaternion_to_matrix(requested_pose.orientation).astype(np.float32)
        requested_position = np.asarray(
            (requested_pose.position.x, requested_pose.position.y, requested_pose.position.z), dtype=np.float32
        )
        anchor_index, _ = self.nearest_registered_pose(requested_pose)
        self._activate_tile(anchor_index)
        forced = self._frame_anchors.get(request.frame_id)
        if forced is not None:
            anchor_index, requested_front_rotation, anchor_c2w = forced
            self._activate_tile(anchor_index)
            c2w = anchor_c2w.copy()
            if request.sensor_id != "front":
                relative_rotation = requested_front_rotation.T @ requested_rotation
                c2w[:3, :3] = anchor_c2w[:3, :3] @ relative_rotation
            warning = f"explicit-registered-camera-anchor:{anchor_index}"
        else:
            c2w = np.eye(4, dtype=np.float32)
            c2w[:3, :3] = requested_rotation
            c2w[:3, 3] = requested_position
            warning = f"live-camera-nearest-tile-anchor:{anchor_index}"
        pose = Pose(
            position=Vector3(x=float(c2w[0, 3]), y=float(c2w[1, 3]), z=float(c2w[2, 3])),
            orientation=matrix_to_quaternion(c2w[:3, :3]),
        )
        view = torch.linalg.inv(torch.from_numpy(c2w)[None].to(self.device))
        intrinsics = request.intrinsics
        calibration = torch.tensor(
            [[[intrinsics.fx, 0.0, intrinsics.cx], [0.0, intrinsics.fy, intrinsics.cy], [0.0, 0.0, 1.0]]],
            dtype=torch.float32,
            device=self.device,
        )
        with torch.inference_mode():
            rgb_depth, alpha, _ = rasterization(
                means=self.gaussians["means"], quats=self.gaussians["quats"],
                scales=self.gaussians["scales"], opacities=self.gaussians["opacities"],
                colors=self.gaussians["colors"], viewmats=view, Ks=calibration,
                width=intrinsics.width, height=intrinsics.height, packed=True,
                rasterize_mode="antialiased", eps2d=0.3, camera_model="pinhole",
                render_mode="RGB+ED", sh_degree=self.sh_degree, near_plane=0.01,
                far_plane=1e4,
                # gsplat 1.5.3 rejects batched backgrounds when packed=True;
                # omitting it is exactly the requested black background.
            )
        support = alpha[0, :, :, 0].clamp(0.0, 1.0).cpu().numpy().astype(np.float32)
        rgb = (rgb_depth[0, :, :, :3].clamp(0.0, 1.0).cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
        depth = rgb_depth[0, :, :, 3].cpu().numpy().astype(np.float32)
        coverage = float(np.mean(support >= 0.05))
        if not math.isfinite(coverage) or not np.all(np.isfinite(depth)):
            raise RuntimeError("Servo Gaussian renderer produced non-finite output")
        if coverage < self.minimum_coverage:
            raise RuntimeError(
                f"Servo Gaussian renderer out of support: coverage={coverage:.3f}, required={self.minimum_coverage:.3f}"
            )
        return ObservationRenderResult(
            frame_id=request.frame_id, rgb=rgb, intrinsics=intrinsics,
            camera_pose=pose, source=self.source, source_hashes=self.source_hashes,
            render_latency_ms=(time.perf_counter() - started) * 1000.0,
            coverage_score=coverage,
            warnings=(warning,),
            expected_depth=depth, support_map=support,
        )

    def close(self) -> None:
        for gaussians, _ in self._tile_cache.values():
            gaussians.clear()
        self._tile_cache.clear()
        self.gaussians.clear()
