"""RealityCI visual/physical weather separation contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.climate.schemas import validate_weather_condition


@dataclass(frozen=True)
class WeatherCondition:
    visual_weather_engine: str
    visual_weather_effect: str
    parameters: dict[str, Any]
    seed: int
    base_world: str
    climate_bundle: str
    observation_source: str
    scale_status: str
    physics_profile: str | None = None
    synchronization_mode: str = "simulation-time"

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_name": "servo.weather-condition/v1",
            "visual_weather_engine": self.visual_weather_engine,
            "visual_weather_effect": self.visual_weather_effect,
            "parameters": self.parameters,
            "seed": self.seed,
            "base_world": self.base_world,
            "climate_bundle": self.climate_bundle,
            "observation_source": self.observation_source,
            "scale_status": self.scale_status,
            "generated_provenance": "generated-climate",
            "physics_profile": self.physics_profile,
            "synchronization_mode": self.synchronization_mode,
        }
        return validate_weather_condition(value)
