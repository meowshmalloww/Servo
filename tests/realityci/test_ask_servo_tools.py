from __future__ import annotations

from tools.realityci.ask_servo.tools import (
    AskPlanRequest,
    AskToolName,
    deterministic_plan,
)


def test_deterministic_weather_plan_carries_real_accumulation() -> None:
    call = deterministic_plan(
        AskPlanRequest(
            prompt="Set inferred snow accumulation to 65%",
            provider="deterministic",
        )
    )
    assert call.tool == AskToolName.SET_WEATHER
    assert call.arguments == {
        "weather": "snow",
        "engine": "servo-inferred-surface",
        "snow_accumulation": 0.65,
    }


def test_deterministic_clear_weather_does_not_claim_climatenerf() -> None:
    call = deterministic_plan(
        AskPlanRequest(prompt="Set clear weather", provider="deterministic")
    )
    assert call.tool == AskToolName.SET_WEATHER
    assert call.arguments["weather"] == "clear"
    assert call.arguments["engine"] == "none"
