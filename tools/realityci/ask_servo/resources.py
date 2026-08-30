"""Ask Servo resources — read-only snapshots of durable state.

MCP resources are `servo://...` URIs that return JSON without mutating state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .tools import AskToolName

# Canonical resource roots exposed via MCP
RESOURCE_TEMPLATES: dict[str, str] = {
    "servo://campaign/{campaign_id}/events": "Ordered events for a campaign (after_sequence).",
    "servo://campaign/{campaign_id}/artifacts": "List of campaign artifacts with hashes.",
    "servo://campaign/{campaign_id}/diagnosis": "Causal diagnosis (proposed vs established).",
    "servo://world/{world_id}": "world.json + cameras.json + hashes + coverage + metrics.",
    "servo://world/{world_id}/execution": "execution-manifest.json + validation-report.json (ready_for_carla).",
    "servo://simulation/{sim_id}/live": "100 ms decimated live-state.json (speed, accel, steering, etc).",
    "servo://simulation/{sim_id}/telemetry": "telemetry.jsonl tail + run-evidence.json.",
    "servo://simulation/{sim_id}/policy-frame": "Latest policy camera JPEG bytes (base64).",
    "servo://build/status": "ReconstructionController dependencies + freeSpace + stage.",
    "servo://build/logs/{jobId}": "events.jsonl tail + worker logs.",
    "servo://settings": "baseUrl, CARLA root, reconstruction root, api token presence.",
    "servo://errors": "lastError + worker-failure.json + failure records.",
    "servo://system/metrics": "process CPU/RSS, Vulkan FPS, disk/VRAM.",
}


def resource_schema() -> list[dict[str, Any]]:
    return [{"uriTemplate": k, "description": v} for k, v in RESOURCE_TEMPLATES.items()]
