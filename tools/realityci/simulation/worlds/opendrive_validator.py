"""Fail-closed structural validation for Servo-generated OpenDRIVE."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OpenDriveValidation:
    valid: bool
    road_count: int
    junction_count: int
    driving_lane_count: int
    length_m: float
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_opendrive(path: Path) -> OpenDriveValidation:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return OpenDriveValidation(False, 0, 0, 0, 0.0, (f"OpenDRIVE parse failed: {exc}",), ())
    if root.tag != "OpenDRIVE":
        errors.append("root element must be OpenDRIVE")
    roads = root.findall("road")
    junctions = root.findall("junction")
    if len(roads) != 1:
        errors.append("bounded initial implementation requires exactly one road")
    if junctions:
        errors.append("junction topology is not supported")
    length = 0.0
    driving_lanes = 0
    for road in roads:
        try:
            road_length = float(road.attrib["length"])
            if not math.isfinite(road_length) or road_length <= 2.0:
                raise ValueError
            length += road_length
        except (KeyError, ValueError):
            errors.append("road length must be finite and greater than two meters")
        geometries = road.findall("./planView/geometry")
        if not geometries or any(geometry.find("line") is None for geometry in geometries):
            errors.append("road planView must contain line geometries")
        lanes = road.findall("./lanes/laneSection/*/lane")
        driving_lanes += sum(1 for lane in lanes if lane.attrib.get("type") == "driving")
    if driving_lanes < 1:
        errors.append("at least one driving lane is required")
    return OpenDriveValidation(not errors, len(roads), len(junctions), driving_lanes, length, tuple(errors), tuple(warnings))
