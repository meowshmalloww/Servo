"""Immutable, hash-verified Climate Weather Bundle publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .schemas import SchemaError, validate_parameters_finite, validate_weather_bundle
from .source_receipt import canonical_json, sha256_file


class PublicationError(RuntimeError):
    """A Climate bundle failed validation or immutable publication."""


def bundle_identity(manifest: dict[str, Any]) -> str:
    copy = dict(manifest)
    copy.pop("bundle_sha256", None)
    return "sha256:" + hashlib.sha256(canonical_json(copy)).hexdigest()


def verify_bundle(root: Path) -> dict[str, Any]:
    path = root / "climate-weather.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        validate_weather_bundle(manifest)
        validate_parameters_finite(manifest["parameters"])
    except (OSError, json.JSONDecodeError, SchemaError) as error:
        raise PublicationError(f"Invalid climate bundle: {error}") from error
    if manifest.get("bundle_sha256") != bundle_identity(manifest):
        raise PublicationError("Climate bundle identity does not match its manifest")
    for name, record in manifest["outputs"].items():
        if not isinstance(record, dict) or "path" not in record or "sha256" not in record:
            raise PublicationError(f"Output {name} has no path/hash receipt")
        target = (root / record["path"]).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            raise PublicationError(f"Output {name} escapes or is missing from the bundle")
        if sha256_file(target) != record["sha256"]:
            raise PublicationError(f"Output {name} hash mismatch")
    return manifest


def publish_bundle(staging: Path, destination: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    staging, destination = staging.resolve(), destination.resolve()
    if destination.exists():
        raise PublicationError(f"Refusing to overwrite immutable bundle: {destination}")
    validate_weather_bundle(manifest)
    validate_parameters_finite(manifest["parameters"])
    manifest = dict(manifest)
    manifest["bundle_sha256"] = bundle_identity(manifest)
    temporary_manifest = staging / f".climate-weather.{uuid.uuid4().hex}.tmp"
    temporary_manifest.write_bytes(canonical_json(manifest) + b"\n")
    os.replace(temporary_manifest, staging / "climate-weather.json")
    verify_bundle(staging)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.publishing")
    try:
        shutil.copytree(staging, temporary)
        verify_bundle(temporary)
        os.replace(temporary, destination)
    except Exception:
        if temporary.is_dir():
            shutil.rmtree(temporary)
        raise
    return verify_bundle(destination)
