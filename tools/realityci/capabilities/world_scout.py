"""WorldScout: missing-reality detection and capture-mission generation.

When the next weakness is a capability whose evidence cannot be produced
from authorized worlds (BLOCKED_MISSING_REALITY), WorldScout emits a
structured CaptureMission instead of letting training loops spin.  It never
scrapes media and never labels generated content as observed truth.
"""

from __future__ import annotations

from pathlib import Path

from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..schemas.base import verify_seal
from ..schemas.capability import (
    CapabilityRecord,
    CapabilityState,
    CaptureMission,
)


WORLD_SCOUT_VERSION = "world-scout/v1"


_MISSION_TEMPLATES: dict[str, dict] = {
    "low-light": {
        "environment": "urban roadway at night, lit street lamps every 30 m, wet asphalt patches",
        "actors": "adult pedestrians crossing at marked and unmarked spots; parked vehicles as occluders",
        "sensor_placement": "forward camera at 1.45 m height, 45 deg horizontal fov, rolling shutter disabled where possible",
        "motion_profile": "ego speed 8-14 m/s with natural deceleration events; pedestrian speeds 0.8-2.2 m/s",
        "duration_minutes": (12, 20),
        "minimum_samples": 300,
    },
    "glare": {
        "environment": "east-west arterial road at sunrise/sunset, direct low sun within camera fov",
        "actors": "pedestrians emerging from behind parked trucks and buses",
        "sensor_placement": "forward camera 1.45 m height; optional second exposure bracketed capture",
        "motion_profile": "ego speed 10-15 m/s; crossing events during peak glare windows",
        "duration_minutes": (10, 18),
        "minimum_samples": 250,
    },
}


def _template_for(taxonomy_id: str) -> dict:
    key = taxonomy_id.split("/")[0]
    for prefix, template in _MISSION_TEMPLATES.items():
        if key.startswith(prefix):
            return template
    return {
        "environment": "roadway matching the capability's declared operational domain",
        "actors": "actors required to exercise the capability gap end to end",
        "sensor_placement": "camera placement matching the deployed policy input spec",
        "motion_profile": "speeds covering the failing parameter band",
        "duration_minutes": (10, 20),
        "minimum_samples": 200,
    }


def requires_capture_mission(capability: CapabilityRecord) -> bool:
    return capability.state == CapabilityState.BLOCKED_MISSING_REALITY


def create_capture_mission(
    capability: CapabilityRecord,
    reason: str,
    campaign_id: str | None = None,
) -> CaptureMission:
    if not requires_capture_mission(capability):
        raise ValueError(
            f"capability {capability.taxonomy_id} is {capability.state.value}, "
            "not BLOCKED_MISSING_REALITY"
        )
    template = _template_for(capability.taxonomy_id)
    mission = CaptureMission(
        record_id=new_record_id("miss"),
        created_at=utc_now(),
        campaign_id=campaign_id,
        causation_id=capability.record_id,
        parent_id=capability.record_id,
        capability_id=capability.record_id,
        reason=reason,
        environment=template["environment"],
        actors=template["actors"],
        sensor_placement=template["sensor_placement"],
        motion_profile=template["motion_profile"],
        duration_minutes=template["duration_minutes"],
        minimum_samples=template["minimum_samples"],
        acceptance_checks=(
            "calibrated camera intrinsics recorded",
            "gps/time anchor per session",
            "no recognizable faces or plates retained without consent release",
            f">= {template['minimum_samples']} usable frames meeting contrast gates",
        ),
        privacy_constraints=(
            "blur faces and license plates at ingest",
            "store only derived hazard labels for public distribution",
        ),
    ).sealed()
    verify_seal(mission)
    return mission


def write_mission(mission: CaptureMission, directory: Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{mission.record_id}.json"
    path.write_text(mission.model_dump_json(indent=2), encoding="utf-8")
    return path
