from __future__ import annotations

import json
import math

import pytest

from tools.realityci.hashing import (
    CanonicalizationError,
    canonical_json_bytes,
    idempotency_key,
    new_record_id,
    payload_hash,
    sha256_digest,
    verify_hash,
    HashMismatch,
)


def test_canonical_json_is_sorted_and_compact() -> None:
    a = canonical_json_bytes({"b": 1, "a": [2, {"z": 0, "y": None}]})
    b = canonical_json_bytes({"a": [2, {"y": None, "z": 0}], "b": 1})
    assert a == b == b'{"a":[2,{"y":null,"z":0}],"b":1}'


def test_canonical_json_rejects_non_finite() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"x": float("nan")})
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"x": float("inf")})


def test_sha256_known_vector() -> None:
    assert sha256_digest(b"abc") == "sha256:" + (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_payload_hash_stable_across_key_order() -> None:
    one = payload_hash({"alpha": 1.5, "beta": "x", "gamma": [1, 2]})
    two = payload_hash({"gamma": [1, 2], "beta": "x", "alpha": 1.5})
    assert one == two


def test_verify_hash_detects_mutation() -> None:
    digest = sha256_digest(b"original")
    verify_hash(digest, b"original")
    with pytest.raises(HashMismatch):
        verify_hash(digest, b"mutated")


def test_idempotency_key_deterministic_and_scope_sensitive() -> None:
    first = idempotency_key("run-baseline", "cam-123", "scn-abc", 7)
    again = idempotency_key("run-baseline", "cam-123", "scn-abc", 7)
    other_scope = idempotency_key("run-exam", "cam-123", "scn-abc", 7)
    other_value = idempotency_key("run-baseline", "cam-123", "scn-abc", 8)
    assert first == again
    assert first != other_scope
    assert first != other_value


def test_new_record_id_format() -> None:
    record_id = new_record_id("cam")
    assert record_id.startswith("cam-")
    suffix = record_id.split("-", 1)[1]
    assert len(suffix) == 16
    assert all(c in "0123456789abcdef" for c in suffix)
    with pytest.raises(ValueError):
        new_record_id("../evil")


def test_float_roundtrip_stability() -> None:
    value = {"v": 4.82, "w": 1 / 3}
    decoded = json.loads(canonical_json_bytes(value))
    assert decoded["v"] == 4.82
    assert math.isclose(decoded["w"], 1 / 3)
    assert canonical_json_bytes(decoded) == canonical_json_bytes(value)
