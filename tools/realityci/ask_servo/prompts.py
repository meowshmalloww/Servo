"""Ask Servo prompts — genetic loop recipes.

Each prompt is a structured instruction that the brain can invoke via MCP.
No free-form LLM generation of workflow; the prompt expands into a bounded
sequence of tool calls with deterministic gates.
"""

from __future__ import annotations

from typing import Any

PROMPTS: dict[str, dict[str, Any]] = {
    "genetic_loop": {
        "name": "genetic_loop",
        "description": "MODEL->RUN->FAILURE->DIAGNOSIS->TRAIN->HIDDEN_EXAM->PROMOTE->DEBT->NEXT. Idempotent, resumable.",
        "arguments": [
            {"name": "baseline_checkpoint_uri", "description": "Path to baseline .pt", "required": True},
            {"name": "campaign_id", "description": "Existing campaign or create new", "required": False},
        ],
        "steps": [
            "get_build_status",
            "get_world_details",
            "create_campaign(baseline_checkpoint_uri)",
            "run_to_completion OR stepwise: step_campaign + get_campaign_events after each transition",
            "on FAILURE_DETECTED: explain_failure -> run_counterfactuals -> advance_to_root_cause",
            "if ROOT_CAUSE_ESTABLISHED: create_curriculum -> start_training -> run_hidden_exam -> show_checkpoint_comparison",
            "select_next_weakness -> if BLOCKED_MISSING_REALITY read capture mission",
            "for weather robustness: activate only a quality-accepted ClimateNeRF bundle, then create_simulation -> get_vehicle_metrics",
        ],
    },
    "self_healing": {
        "name": "self_healing",
        "description": "Watch lastError / worker-failure.json, diagnose, and retry the failed gate once.",
        "steps": [
            "get_errors",
            "get_campaign_events",
            "if TRAINING_FAILED: verify dataset positive_count, then start_training",
            "if physics_world_invalid: get_world_execution -> prepare_world_for_carla(validate_in_carla=true)",
            "if sensor_desynchronization: get_live_state -> get_telemetry -> pause_simulation -> resume_simulation",
        ],
    },
    "full_vehicle_check": {
        "name": "full_vehicle_check",
        "description": "Load a world, spawn a vehicle, stream live metrics and policy frames.",
        "steps": ["get_world_execution(ready_for_carla=true)", "create_simulation", "get_live_state @100ms", "get_vehicle_metrics", "get_telemetry", "get_policy_frame"],
    },
}

def prompt_schema() -> list[dict[str, Any]]:
    return list(PROMPTS.values())
