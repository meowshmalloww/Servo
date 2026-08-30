"""Strict schema validation for Climate artifacts and RealityCI descriptors."""

from __future__ import annotations

import math
import re
from typing import Any, Iterable


HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
READINESS = {"ready", "ready-relative-units", "degraded", "unsupported", "invalid"}
EFFECTS = {"smog", "flood", "snow", "stylized-clear", "stylized-snow"}
ENGINES = {"climatenerf-reference", "servo-climatenerf-native", "baked"}
OBSERVATION_SOURCES = {
    "servo-gaussian-clear", "servo-climatenerf-native-smog",
    "servo-climatenerf-native-flood", "servo-climatenerf-native-snow",
    "climatenerf-reference", "climatenerf-baked",
}


class SchemaError(ValueError):
    """A Climate or weather artifact violates its versioned contract."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{name} must be an object")
    return value


def _required(value: dict[str, Any], fields: Iterable[str]) -> None:
    missing = sorted(set(fields) - value.keys())
    if missing:
        raise SchemaError("missing required fields: " + ", ".join(missing))


def _hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise SchemaError(f"{name} must be a lowercase sha256 receipt")


def validate_dataset(value: Any) -> dict[str, Any]:
    doc = _object(value, "dataset")
    _required(doc, ("schema_name", "dataset_id", "base_world_id", "base_world_sha256",
                    "source_image_receipt", "camera_receipt", "coordinate_conversion",
                    "scale_status", "train_frames", "validation_frames", "test_frames",
                    "hidden_validation_frames", "generated_files", "producer_version",
                    "source_tree_receipt", "warnings", "created_at"))
    if doc["schema_name"] != "servo.climate-dataset/v1":
        raise SchemaError("unexpected dataset schema_name")
    _hash(doc["base_world_sha256"], "base_world_sha256")
    if doc["scale_status"] not in {"metric", "relative", "unknown"}:
        raise SchemaError("invalid scale_status")
    return doc


def validate_weather_bundle(value: Any) -> dict[str, Any]:
    doc = _object(value, "weather bundle")
    _required(doc, ("schema_name", "weather_world_id", "base_world_id", "base_world_sha256",
                    "effect", "engine", "provenance", "climate_source_receipt",
                    "dataset_manifest_sha256", "parameters", "coordinate_system", "scale",
                    "geometry_readiness", "semantic_readiness", "normal_readiness", "outputs",
                    "validation", "physics_effects", "created_at", "producer"))
    if doc["schema_name"] != "servo.climate-weather/v1":
        raise SchemaError("unexpected weather schema_name")
    if doc["effect"] not in EFFECTS or doc["engine"] not in ENGINES:
        raise SchemaError("unsupported effect or engine")
    if doc["provenance"] != "generated-climate":
        raise SchemaError("climate weather provenance must be generated-climate")
    _hash(doc["base_world_sha256"], "base_world_sha256")
    _hash(doc["dataset_manifest_sha256"], "dataset_manifest_sha256")
    for key in ("geometry_readiness", "semantic_readiness", "normal_readiness"):
        if doc[key] not in READINESS:
            raise SchemaError(f"invalid {key}")
    physics = _object(doc["physics_effects"], "physics_effects")
    for key in ("collision_geometry_changed", "friction_changed", "water_depth_ground_truth", "snow_mass_ground_truth"):
        if physics.get(key) is not False:
            raise SchemaError(f"{key} must be explicitly false for a visual bundle")
    return doc


def validate_weather_condition(value: Any) -> dict[str, Any]:
    doc = _object(value, "weather condition")
    _required(doc, ("schema_name", "visual_weather_engine", "visual_weather_effect", "parameters",
                    "seed", "base_world", "climate_bundle", "observation_source", "scale_status",
                    "generated_provenance", "physics_profile", "synchronization_mode"))
    if doc["schema_name"] != "servo.weather-condition/v1":
        raise SchemaError("unexpected weather-condition schema_name")
    if doc["observation_source"] not in OBSERVATION_SOURCES:
        raise SchemaError("unsupported observation_source")
    if doc["generated_provenance"] != "generated-climate":
        raise SchemaError("generated_provenance must be generated-climate")
    if not isinstance(doc["seed"], int) or doc["seed"] < 0:
        raise SchemaError("seed must be a non-negative integer")
    return doc


def validate_parameters_finite(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            validate_parameters_finite(child)
    elif isinstance(value, list):
        for child in value:
            validate_parameters_finite(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise SchemaError("parameters cannot contain NaN or infinity")
