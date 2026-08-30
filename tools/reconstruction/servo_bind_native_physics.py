#!/usr/bin/env python3
"""Bind an evidence-bounded native vehicle surface to a Gaussian world.

The Gaussian PLY remains the appearance representation.  A vehicle cannot
collide with alpha-blended ellipsoids directly, so Servo publishes a separate
finite collider derived from the *same calibrated capture geometry*.  The
binding is fail-closed: camera coordinates and source hashes must match, and
space outside the retained road interval/width is deliberately left void.

This tool does not claim metric reconstruction or collision certification.
The optional SI scale is an explicit road-width assumption used only by the
interactive physics demo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Sequence


PHYSICS_SCHEMA = "servo.native-gaussian-vehicle-physics/v1"
ROAD_SCHEMA = "servo.road-surface/v1"
WORLD_SCHEMA = "servo.gaussian-world/v1"


class BindingError(RuntimeError):
    """Raised when a physics binding would be ambiguous or unsafe."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BindingError(f"Unable to read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise BindingError(f"JSON root must be an object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BindingError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BindingError(f"{name} must be finite")
    return result


def _vector(value: Any, size: int, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise BindingError(f"{name} must contain {size} numbers")
    return [_number(component, f"{name}[{index}]") for index, component in enumerate(value)]


def _add(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [float(a) + float(b) for a, b in zip(left, right, strict=True)]


def _sub(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [float(a) - float(b) for a, b in zip(left, right, strict=True)]


def _mul(value: Sequence[float], scalar: float) -> list[float]:
    return [float(component) * scalar for component in value]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right, strict=True))


def _cross(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _normalized(value: Sequence[float], name: str) -> list[float]:
    length = math.sqrt(_dot(value, value))
    if not math.isfinite(length) or length <= 1.0e-10:
        raise BindingError(f"{name} is degenerate")
    return [float(component) / length for component in value]


def _interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise BindingError("Road splines require at least two matching samples")
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    low = 0
    high = len(xs) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if xs[middle] <= x:
            low = middle
        else:
            high = middle
    span = max(float(xs[high]) - float(xs[low]), 1.0e-12)
    amount = (x - float(xs[low])) / span
    return float(ys[low]) * (1.0 - amount) + float(ys[high]) * amount


def _path_point(path_frame: dict[str, Any], station: float, lateral: float, height: float) -> list[float]:
    centers = [_vector(value, 3, "pathFrame.centers") for value in path_frame["centers"]]
    arc = [_number(value, "pathFrame.arcLengths") for value in path_frame["arcLengths"]]
    origin = _vector(path_frame["origin"], 3, "pathFrame.origin")
    up = _normalized(_vector(path_frame["up"], 3, "pathFrame.up"), "pathFrame.up")
    if len(centers) != len(arc) or len(centers) < 2:
        raise BindingError("Path centers and arc lengths do not match")
    station = min(max(station, arc[0]), arc[-1])
    segment = 0
    while segment + 2 < len(arc) and arc[segment + 1] < station:
        segment += 1
    span = max(arc[segment + 1] - arc[segment], 1.0e-12)
    amount = (station - arc[segment]) / span
    center = _add(_mul(centers[segment], 1.0 - amount), _mul(centers[segment + 1], amount))
    delta = _sub(centers[segment + 1], centers[segment])
    horizontal = _sub(delta, _mul(up, _dot(delta, up)))
    forward = _normalized(horizontal, "path tangent")
    right = _normalized(_cross(up, forward), "path right")
    center_height = _dot(_sub(center, origin), up)
    horizontal_center = _sub(center, _mul(up, center_height))
    return _add(_add(horizontal_center, _mul(right, lateral)), _mul(up, height))


def _write_debug_mesh(path: Path, road: dict[str, Any], longitudinal_samples: int = 320) -> None:
    surface = road.get("surface")
    path_frame = road.get("pathFrame")
    if not isinstance(surface, dict) or not isinstance(path_frame, dict):
        raise BindingError("Road surface/path frame is missing")
    knots = [_number(value, "surface.knots") for value in surface.get("knots", [])]
    elevations = [_number(value, "surface.elevations") for value in surface.get("elevations", [])]
    banks = [_number(value, "surface.banks") for value in surface.get("banks", [])]
    if not (len(knots) == len(elevations) == len(banks)) or len(knots) < 2:
        raise BindingError("Road spline arrays are malformed")
    lateral_min = _number(surface.get("lateralMin"), "surface.lateralMin")
    lateral_max = _number(surface.get("lateralMax"), "surface.lateralMax")
    lateral_origin = _number(surface.get("lateralOrigin"), "surface.lateralOrigin")
    if lateral_max <= lateral_min:
        raise BindingError("Road lateral bounds are invalid")
    arc = [_number(value, "pathFrame.arcLengths")
           for value in path_frame.get("arcLengths", [])]
    if len(arc) < 2:
        raise BindingError("Road path arc lengths are malformed")
    station_min = max(knots[0], arc[0])
    station_max = min(knots[-1], arc[-1])
    if station_max <= station_min:
        raise BindingError("Road surface and camera path do not overlap")
    lateral_samples = 9
    vertices: list[list[float]] = []
    for longitudinal in range(longitudinal_samples + 1):
        amount = longitudinal / longitudinal_samples
        station = station_min * (1.0 - amount) + station_max * amount
        elevation = _interpolate(knots, elevations, station)
        bank = _interpolate(knots, banks, station)
        for lateral_index in range(lateral_samples):
            lateral_amount = lateral_index / (lateral_samples - 1)
            lateral = lateral_min * (1.0 - lateral_amount) + lateral_max * lateral_amount
            height = elevation + bank * (lateral - lateral_origin)
            vertices.append(_path_point(path_frame, station, lateral, height))
    lines = [
        "# Servo finite native road collider debug mesh",
        "# Visual inspection only; native runtime evaluates the bound surface analytically.",
    ]
    lines.extend("v {:.9g} {:.9g} {:.9g}".format(*vertex) for vertex in vertices)
    for longitudinal in range(longitudinal_samples):
        row = longitudinal * lateral_samples
        next_row = (longitudinal + 1) * lateral_samples
        for lateral in range(lateral_samples - 1):
            a = row + lateral + 1
            b = next_row + lateral + 1
            c = next_row + lateral + 2
            d = row + lateral + 2
            lines.append(f"f {a} {b} {c}")
            lines.append(f"f {a} {c} {d}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def bind(world_root: Path, road_path: Path, assumed_road_width_meters: float) -> dict[str, Any]:
    world_root = world_root.resolve()
    manifest_path = world_root / "world.json"
    cameras_path = world_root / "cameras.json"
    world = _read_json(manifest_path)
    cameras = _read_json(cameras_path)
    road = _read_json(road_path.resolve())
    if world.get("schema") != WORLD_SCHEMA:
        raise BindingError("World does not use servo.gaussian-world/v1")
    if road.get("schema") != ROAD_SCHEMA:
        raise BindingError("Road surface does not use servo.road-surface/v1")
    route_tiles = world.get("routeTiles")
    if not isinstance(route_tiles, list) or len(route_tiles) < 1:
        raise BindingError("World has no route-tile source fields")

    camera_records = cameras.get("cameras")
    path_frame = road.get("pathFrame")
    if not isinstance(camera_records, list) or not isinstance(path_frame, dict):
        raise BindingError("Camera or path-frame evidence is missing")
    raw_centers = path_frame.get("rawCenters")
    if not isinstance(raw_centers, list) or len(raw_centers) != len(camera_records):
        raise BindingError("Road and Gaussian camera counts do not match")
    maximum_camera_error = 0.0
    for index, (record, road_center) in enumerate(zip(camera_records, raw_centers, strict=True)):
        if not isinstance(record, dict):
            raise BindingError(f"Camera {index} is malformed")
        matrix = record.get("cameraToWorldNormalized")
        if not isinstance(matrix, list) or len(matrix) != 4:
            raise BindingError(f"Camera {index} transform is malformed")
        gaussian_center = []
        for row in range(3):
            values = matrix[row].split() if isinstance(matrix[row], str) else matrix[row]
            if not isinstance(values, list) or len(values) != 4:
                raise BindingError(f"Camera {index} row {row} is malformed")
            gaussian_center.append(_number(values[3], f"camera {index}"))
        candidate = _vector(road_center, 3, f"road camera {index}")
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(gaussian_center, candidate, strict=True)))
        maximum_camera_error = max(maximum_camera_error, error)
    if maximum_camera_error > 1.0e-5:
        raise BindingError(
            f"Road/Gaussian camera coordinates disagree by {maximum_camera_error:.9g}"
        )

    surface = road.get("surface")
    if not isinstance(surface, dict):
        raise BindingError("Road surface descriptor is missing")
    lateral_min = _number(surface.get("lateralMin"), "surface.lateralMin")
    lateral_max = _number(surface.get("lateralMax"), "surface.lateralMax")
    normalized_width = lateral_max - lateral_min
    if normalized_width <= 0.0 or assumed_road_width_meters <= 0.0:
        raise BindingError("Road width or SI assumption is invalid")
    meters_per_world_unit = assumed_road_width_meters / normalized_width

    physics_root = world_root / "physics" / "native-t5-v1"
    physics_root.mkdir(parents=True, exist_ok=True)
    bound_road_path = physics_root / "road-surface.json"
    mesh_path = physics_root / "road-collider.obj"
    descriptor_path = physics_root / "native-vehicle-physics.json"
    shutil.copyfile(road_path, bound_road_path)
    _write_debug_mesh(mesh_path, road)

    tile_sources = []
    for index, tile in enumerate(route_tiles):
        if not isinstance(tile, dict):
            raise BindingError(f"Route tile {index} is malformed")
        relative = str(tile.get("ply", ""))
        expected_hash = str(tile.get("plySha256", ""))
        source = world_root / relative
        if not source.is_file() or not expected_hash.startswith("sha256:"):
            raise BindingError(f"Route tile {index} is missing or unbound")
        actual_hash = _sha256(source)
        if actual_hash != expected_hash:
            raise BindingError(f"Route tile {index} hash does not match world.json")
        tile_sources.append({"path": relative, "sha256": actual_hash})

    descriptor = {
        "schema": PHYSICS_SCHEMA,
        "worldId": world.get("worldId"),
        "worldCoordinateSystem": "t5-normalized-world-v1",
        "roadSurface": "road-surface.json",
        "roadSurfaceSha256": _sha256(bound_road_path),
        "debugColliderMesh": "road-collider.obj",
        "debugColliderMeshSha256": _sha256(mesh_path),
        "sourceGaussianFields": tile_sources,
        "cameraEvidence": {
            "path": "../../cameras.json",
            "sha256": _sha256(cameras_path),
            "cameraCount": len(camera_records),
            "maximumCoordinateDisagreement": maximum_camera_error,
        },
        "surfacePolicy": {
            "road": "piecewise grade and bank inside retained longitudinal/lateral bounds",
            "outsideRoad": "void-no-static-floor",
            "outsideRouteEndpoints": "void-no-static-floor",
            "collisionValidated": False,
            "metric": False,
        },
        "siScale": {
            "metersPerWorldUnit": meters_per_world_unit,
            "provenance": "explicit-assumption-from-two-lane-road-width",
            "assumedRoadWidthMeters": assumed_road_width_meters,
            "measured": False,
        },
        "gravityMetersPerSecondSquared": 9.80665,
        "vehicle": {
            "massKg": 1840.0,
            "lengthMeters": 4.75,
            "widthMeters": 1.92,
            "heightMeters": 1.45,
            "wheelbaseMeters": 2.85,
            "trackMeters": 1.62,
            "wheelRadiusMeters": 0.34,
            "suspensionRestMeters": 0.24,
            "springNewtonsPerMeter": 46000.0,
            "damperNewtonSecondsPerMeter": 5200.0,
        },
        "provenance": {
            "appearance": "five hashed T5 v2 Gaussian fields",
            "collisionSurface": "same-capture calibrated semantic/depth road fit",
            "generatedGeometry": False,
            "hardcodedRouteMotion": False,
            "carla": False,
        },
        "limitations": [
            "Monocular scale is not measured; SI scale uses the recorded road-width assumption.",
            "The collider is evidence-bounded but is not independently collision certified.",
            "Unobserved space is intentionally void rather than an inferred infinite floor.",
        ],
    }
    _atomic_json(descriptor_path, descriptor)

    relative_descriptor = descriptor_path.relative_to(world_root).as_posix()
    relative_road = bound_road_path.relative_to(world_root).as_posix()
    relative_mesh = mesh_path.relative_to(world_root).as_posix()
    world["physics"] = {
        "schema": PHYSICS_SCHEMA,
        "runtime": "servo-native-four-wheel-rigid-body-v1",
        "descriptor": relative_descriptor,
        "descriptorSha256": _sha256(descriptor_path),
        "roadSurface": relative_road,
        "roadSurfaceSha256": _sha256(bound_road_path),
        "debugColliderMesh": relative_mesh,
        "debugColliderMeshSha256": _sha256(mesh_path),
        "outsideSupport": "void",
        "gravityMetersPerSecondSquared": 9.80665,
        "carla": False,
        "ready": True,
        "collisionValidated": False,
    }
    usage = world.setdefault("usage", {})
    if not isinstance(usage, dict):
        raise BindingError("World usage must be an object")
    usage["nativeVehiclePhysicsReady"] = True
    usage["collisionValidated"] = False
    hashes = world.setdefault("hashes", {})
    if not isinstance(hashes, dict):
        raise BindingError("World hashes must be an object")
    hashes[relative_descriptor] = _sha256(descriptor_path)
    hashes[relative_road] = _sha256(bound_road_path)
    hashes[relative_mesh] = _sha256(mesh_path)
    _atomic_json(manifest_path, world)
    return descriptor


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--world", required=True, type=Path)
    result.add_argument("--road-surface", required=True, type=Path)
    result.add_argument("--assumed-road-width-meters", type=float, default=7.4)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    descriptor = bind(
        arguments.world,
        arguments.road_surface,
        arguments.assumed_road_width_meters,
    )
    print(json.dumps(descriptor, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
