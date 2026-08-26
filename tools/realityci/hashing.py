"""Canonical JSON serialization and content addressing for RealityCI records.

Every durable record is content-addressed with SHA-256 over canonical JSON:
sorted keys, no whitespace, ASCII escaping, and NaN/Infinity rejected.  The
same logical record must always serialize to the same bytes on any machine.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

HASH_PREFIX = "sha256:"
_ID_SEPARATOR = "\x1f"


class CanonicalizationError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(f"value is not canonically serializable: {exc}") from exc
    return text.encode("utf-8")


def sha256_digest(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return HASH_PREFIX + hasher.hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256_digest(canonical_json_bytes(payload))


def new_record_id(prefix: str) -> str:
    if not prefix or not prefix.replace("-", "").isalnum():
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def idempotency_key(scope: str, *parts: Any) -> str:
    material = _ID_SEPARATOR.join([scope, *(str(part) for part in parts)])
    return sha256_digest(canonical_json_bytes(material))


def verify_hash(expected: str, data: bytes) -> None:
    actual = sha256_digest(data)
    if actual != expected:
        raise HashMismatch(f"expected {expected}, computed {actual}")


class HashMismatch(ValueError):
    pass
