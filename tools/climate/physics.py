"""Reference numerical primitives derived from ClimateNeRF's paper/source.

These functions implement the weather equations, not a substitute scene model.
They consume calibrated renderer outputs (depth, normals, semantics) and are
therefore only one layer of the full reference pipeline.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def beer_lambert_transmission(depth: Any, sigma: float, *, depth_bound: float | None = None,
                              max_optical_depth: float = 20.0) -> np.ndarray:
    if not math.isfinite(sigma) or sigma < 0:
        raise ValueError("sigma must be finite and non-negative")
    if not math.isfinite(max_optical_depth) or max_optical_depth <= 0:
        raise ValueError("max_optical_depth must be finite and positive")
    distance = np.asarray(depth, dtype=np.float64)
    if np.any(~np.isfinite(distance)) or np.any(distance < 0):
        raise ValueError("depth must contain finite non-negative values")
    if depth_bound is not None:
        if not math.isfinite(depth_bound) or depth_bound <= 0:
            raise ValueError("depth_bound must be finite and positive")
        distance = np.minimum(distance, depth_bound)
    optical_depth = np.minimum(sigma * distance, max_optical_depth)
    return np.exp(-optical_depth)


def composite_smog(rgb: Any, depth: Any, sigma: float, color: Any, **kwargs: Any) -> tuple[np.ndarray, np.ndarray]:
    image = np.asarray(rgb, dtype=np.float64)
    medium = np.asarray(color, dtype=np.float64)
    if image.shape[-1] != 3 or medium.shape != (3,):
        raise ValueError("rgb must end in three channels and color must have three values")
    transmission = beer_lambert_transmission(depth, sigma, **kwargs)
    result = transmission[..., None] * image + (1.0 - transmission[..., None]) * medium
    return np.clip(result, 0.0, 1.0), transmission


def dielectric_fresnel(cos_incident: Any, n_air: float = 1.00029, n_water: float = 1.333) -> np.ndarray:
    """Unpolarized dielectric Fresnel reflectance, including TIR."""
    if n_air <= 0 or n_water <= 0 or not math.isfinite(n_air + n_water):
        raise ValueError("indices of refraction must be finite and positive")
    ci = np.clip(np.asarray(cos_incident, dtype=np.float64), 0.0, 1.0)
    sin_t2 = (n_air / n_water) ** 2 * np.maximum(0.0, 1.0 - ci * ci)
    tir = sin_t2 > 1.0
    ct = np.sqrt(np.maximum(0.0, 1.0 - sin_t2))
    rs = ((n_air * ci - n_water * ct) / np.maximum(1e-12, n_air * ci + n_water * ct)) ** 2
    rp = ((n_air * ct - n_water * ci) / np.maximum(1e-12, n_air * ct + n_water * ci)) ** 2
    return np.where(tir, 1.0, np.clip(0.5 * (rs + rp), 0.0, 1.0))


def refract(direction: Any, normal: Any, n_from: float = 1.00029, n_to: float = 1.333) -> tuple[np.ndarray, np.ndarray]:
    d = np.asarray(direction, dtype=np.float64)
    n = np.asarray(normal, dtype=np.float64)
    d = d / np.linalg.norm(d, axis=-1, keepdims=True)
    n = n / np.linalg.norm(n, axis=-1, keepdims=True)
    cos_i = -np.sum(d * n, axis=-1, keepdims=True)
    eta = n_from / n_to
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    tir = k[..., 0] < 0.0
    transmitted = eta * d + (eta * cos_i - np.sqrt(np.maximum(k, 0.0))) * n
    transmitted = np.where(tir[..., None], 0.0, transmitted)
    return transmitted, tir


def intersect_plane(ray_origins: Any, ray_directions: Any, plane_origin: Any,
                    plane_normal: Any, *, epsilon: float = 1e-8) -> tuple[np.ndarray, np.ndarray]:
    origins = np.asarray(ray_origins, dtype=np.float64)
    directions = np.asarray(ray_directions, dtype=np.float64)
    origin = np.asarray(plane_origin, dtype=np.float64)
    normal = np.asarray(plane_normal, dtype=np.float64)
    normal = normal / np.linalg.norm(normal)
    denominator = np.sum(directions * normal, axis=-1)
    numerator = np.sum((origin - origins) * normal, axis=-1)
    valid = np.abs(denominator) > epsilon
    distance = np.where(valid, numerator / denominator, np.inf)
    valid &= distance >= 0.0
    return distance, valid


def water_mask(ray_origins: Any, ray_directions: Any, scene_depth: Any,
               plane_origin: Any, plane_normal: Any) -> np.ndarray:
    distance, valid = intersect_plane(ray_origins, ray_directions, plane_origin, plane_normal)
    depth = np.asarray(scene_depth, dtype=np.float64)
    return valid & np.isfinite(depth) & (distance < depth)


def deterministic_wave_normals(shape: tuple[int, int], *, seed: int, time_s: float,
                               wind_direction_deg: float, wind_speed: float,
                               amplitude: float, spatial_scale: float) -> np.ndarray:
    """Deterministic FFT spectral wave normals for native/reference validation."""
    height, width = shape
    if height < 2 or width < 2 or amplitude < 0 or spatial_scale <= 0 or wind_speed < 0:
        raise ValueError("invalid wave parameters")
    rng = np.random.default_rng(seed)
    ky = np.fft.fftfreq(height)[:, None]
    kx = np.fft.fftfreq(width)[None, :]
    k = np.sqrt(kx * kx + ky * ky)
    theta = math.radians(wind_direction_deg)
    alignment = np.maximum(0.0, (kx * math.cos(theta) + ky * math.sin(theta)) / np.maximum(k, 1e-9)) ** 2
    spectrum = alignment * np.exp(-1.0 / np.maximum((k * spatial_scale) ** 2, 1e-9)) / np.maximum(k ** 4, 1e-9)
    spectrum[0, 0] = 0.0
    noise = rng.normal(size=shape) + 1j * rng.normal(size=shape)
    omega = np.sqrt(9.81 * k * (1.0 + 0.03 * wind_speed))
    field = np.fft.ifft2(noise * np.sqrt(spectrum) * np.exp(1j * omega * time_s)).real
    peak = np.max(np.abs(field))
    field = amplitude * field / peak if peak > 0 else field
    dy, dx = np.gradient(field)
    normals = np.stack((-dx, np.ones_like(dx), -dy), axis=-1)
    return normals / np.linalg.norm(normals, axis=-1, keepdims=True)


def snow_candidate_confidence(normals: Any, up: Any, semantic_supported: Any,
                              visible_from_sky: Any, *, minimum_up_dot: float = 0.35) -> np.ndarray:
    surface = np.asarray(normals, dtype=np.float64)
    up_vector = np.asarray(up, dtype=np.float64)
    surface = surface / np.maximum(np.linalg.norm(surface, axis=-1, keepdims=True), 1e-12)
    up_vector = up_vector / np.linalg.norm(up_vector)
    facing = np.clip((np.sum(surface * up_vector, axis=-1) - minimum_up_dot) /
                     max(1e-12, 1.0 - minimum_up_dot), 0.0, 1.0)
    return facing * np.asarray(semantic_supported, dtype=bool) * np.asarray(visible_from_sky, dtype=bool)


def metaball_density(points: Any, centers: Any, radii: Any) -> np.ndarray:
    samples = np.asarray(points, dtype=np.float64)
    sources = np.asarray(centers, dtype=np.float64)
    radius = np.asarray(radii, dtype=np.float64)
    if sources.shape[-1] != 3 or samples.shape[-1] != 3 or np.any(radius <= 0):
        raise ValueError("metaball inputs are malformed")
    delta = samples[..., None, :] - sources
    squared = np.sum(delta * delta, axis=-1) / (radius * radius)
    return np.sum(np.exp(-0.5 * squared), axis=-1)
