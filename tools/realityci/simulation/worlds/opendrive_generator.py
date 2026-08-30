"""Generate a bounded, junction-free OpenDRIVE corridor."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def generate_single_corridor_opendrive(
    centerline: np.ndarray,
    output: Path,
    *,
    lane_width_m: float,
    shoulder_width_m: float,
    driving_side: str,
    include_opposing_lane: bool,
) -> str:
    points = np.asarray(centerline, dtype=np.float64)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
        raise ValueError("centerline must be a finite Nx3 array with at least two points")
    if not 2.5 <= lane_width_m <= 5.0:
        raise ValueError("lane width must be between 2.5 and 5.0 meters")
    if not 0.0 <= shoulder_width_m <= 4.0:
        raise ValueError("shoulder width must be between 0.0 and 4.0 meters")
    if driving_side not in {"right", "left"}:
        raise ValueError("driving_side must be right or left")
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "header", revMajor="1", revMinor="4", name="Servo inferred corridor", version="1.00", north="0", south="0", east="0", west="0")
    lengths = np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1)
    road_length = float(lengths.sum())
    road = ET.SubElement(root, "road", name="Servo inferred single corridor", length=f"{road_length:.9f}", id="1", junction="-1", rule="RHT" if driving_side == "right" else "LHT")
    ET.SubElement(road, "link")
    plan = ET.SubElement(road, "planView")
    cumulative = 0.0
    for index, length in enumerate(lengths):
        delta = points[index + 1] - points[index]
        heading = math.atan2(float(delta[1]), float(delta[0]))
        geometry = ET.SubElement(plan, "geometry", s=f"{cumulative:.9f}", x=f"{points[index,0]:.9f}", y=f"{points[index,1]:.9f}", hdg=f"{heading:.12f}", length=f"{float(length):.9f}")
        ET.SubElement(geometry, "line")
        cumulative += float(length)
    elevation = ET.SubElement(road, "elevationProfile")
    # Preserve the fitted camera-corridor grade.  A single constant elevation
    # record made CARLA's physical road diverge vertically from the Gaussian
    # road by several metres near the route end.
    cumulative = 0.0
    for index, length in enumerate(lengths):
        slope = 0.0 if length <= 1e-9 else float((points[index + 1, 2] - points[index, 2]) / length)
        ET.SubElement(
            elevation,
            "elevation",
            s=f"{cumulative:.9f}",
            a=f"{points[index,2]:.9f}",
            b=f"{slope:.12f}",
            c="0",
            d="0",
        )
        cumulative += float(length)
    ET.SubElement(road, "lateralProfile")
    lanes = ET.SubElement(road, "lanes")
    ET.SubElement(lanes, "laneOffset", s="0", a="0", b="0", c="0", d="0")
    section = ET.SubElement(lanes, "laneSection", s="0")
    left = ET.SubElement(section, "left")
    center = ET.SubElement(section, "center")
    center_lane = ET.SubElement(center, "lane", id="0", type="none", level="false")
    ET.SubElement(center_lane, "link")
    # BehaviorAgent reads both adjacent lane-marking objects even on a
    # junction-free road.  Omitting the center reference marking makes CARLA
    # return None for the driven lane's inner boundary and crashes its normal
    # tailgating check.
    ET.SubElement(
        center_lane,
        "roadMark",
        sOffset="0",
        type="solid",
        weight="standard",
        color="yellow" if include_opposing_lane else "standard",
        width="0.12",
        laneChange="none",
    )
    right = ET.SubElement(section, "right")

    driven_container, driven_id = (right, "-1") if driving_side == "right" else (left, "1")
    driven = ET.SubElement(driven_container, "lane", id=driven_id, type="driving", level="false")
    ET.SubElement(driven, "link")
    ET.SubElement(driven, "width", sOffset="0", a=f"{lane_width_m:.6f}", b="0", c="0", d="0")
    ET.SubElement(driven, "roadMark", sOffset="0", type="broken", weight="standard", color="standard", width="0.12", laneChange="both")
    if include_opposing_lane:
        opposing_container, opposing_id = (left, "1") if driving_side == "right" else (right, "-1")
        opposing = ET.SubElement(opposing_container, "lane", id=opposing_id, type="driving", level="false")
        ET.SubElement(opposing, "link")
        ET.SubElement(opposing, "width", sOffset="0", a=f"{lane_width_m:.6f}", b="0", c="0", d="0")
        ET.SubElement(opposing, "roadMark", sOffset="0", type="solid", weight="standard", color="yellow", width="0.15", laneChange="none")
    if shoulder_width_m > 0:
        shoulder_id = "-2" if driving_side == "right" else "2"
        shoulder = ET.SubElement(driven_container, "lane", id=shoulder_id, type="shoulder", level="false")
        ET.SubElement(shoulder, "link")
        ET.SubElement(shoulder, "width", sOffset="0", a=f"{shoulder_width_m:.6f}", b="0", c="0", d="0")
        ET.SubElement(shoulder, "roadMark", sOffset="0", type="solid", weight="standard", color="standard", width="0.12", laneChange="none")
    ET.indent(root, space="  ")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return output.read_text(encoding="utf-8")
