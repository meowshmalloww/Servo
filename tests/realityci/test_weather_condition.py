from __future__ import annotations

import pytest

from tools.climate.schemas import SchemaError
from tools.realityci.schemas.weather import WeatherCondition


def test_climate_observation_source_requires_generated_provenance() -> None:
    record = WeatherCondition(
        visual_weather_engine="servo-climatenerf-native",
        visual_weather_effect="flood",
        parameters={"water_height": 0.2}, seed=77, base_world="world-a",
        climate_bundle="sha256:" + "1" * 64,
        observation_source="servo-climatenerf-native-flood", scale_status="relative",
        physics_profile=None,
    ).to_dict()
    assert record["physics_profile"] is None
    assert record["generated_provenance"] == "generated-climate"


def test_carla_rgb_is_not_a_climate_observation_source() -> None:
    with pytest.raises(SchemaError):
        WeatherCondition(
            visual_weather_engine="servo-climatenerf-native", visual_weather_effect="smog",
            parameters={}, seed=1, base_world="world", climate_bundle="sha256:" + "2" * 64,
            observation_source="carla-rgb", scale_status="relative",
        ).to_dict()
