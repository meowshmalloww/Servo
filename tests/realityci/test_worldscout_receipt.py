from __future__ import annotations

import pytest

from tools.realityci.capabilities import (
    compute_reality_debt,
    create_capture_mission,
    default_register,
    requires_capture_mission,
)
from tools.realityci.schemas.base import verify_seal
from tools.realityci.capabilities.world_scout import write_mission


def _low_light():
    return next(
        c for c in default_register().all() if "low-light" in c.taxonomy_id
    )


def test_blocked_capability_yields_sealed_mission(tmp_path) -> None:
    cap = _low_light()
    assert requires_capture_mission(cap)
    mission = create_capture_mission(
        cap,
        reason="no authorized world contains low-light pedestrian crossings",
        campaign_id="cam-0000000000000000",
    )
    verify_seal(mission)
    assert mission.capability_id == cap.record_id
    assert mission.duration_minutes[0] <= mission.duration_minutes[1]
    assert mission.minimum_samples >= 200
    assert any("blur" in p for p in mission.privacy_constraints)

    path = write_mission(mission, tmp_path)
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["record_id"] == mission.record_id


def test_non_blocked_capability_rejects_mission() -> None:
    cap = next(
        c
        for c in default_register().all()
        if c.state.value == "untested"
    )
    with pytest.raises(ValueError):
        create_capture_mission(cap, reason="not blocked")


def test_selector_can_return_blocked_weakness_for_missions() -> None:
    register = default_register()
    # Verify every other high-weight capability so only blocked ones remain.
    from tools.realityci.schemas.capability import CapabilityState

    promoted_like = {
        "occluded-pedestrian-crossing/v1": CapabilityState.VERIFIED,
        "visible-pedestrian-crossing/v1": CapabilityState.VERIFIED,
        "empty-road-cruise/v1": CapabilityState.VERIFIED,
        "glare-approach/v1": CapabilityState.VERIFIED,
    }
    updated = []
    for record in register.all():
        target = promoted_like.get(record.taxonomy_id)
        if target is None:
            updated.append(record)
            continue
        payload = record.model_dump()
        payload.pop("content_hash", None)
        payload["state"] = target.value
        updated.append(type(record).model_validate(payload).sealed())

    nxt = __import__(
        "tools.realityci.capabilities.register", fromlist=["select_next_weakness"]
    ).select_next_weakness(tuple(updated))
    assert nxt is not None
    assert nxt.state == CapabilityState.BLOCKED_MISSING_REALITY


def test_debt_snapshot_sealed_and_positive() -> None:
    snapshot = compute_reality_debt(default_register().all())
    verify_seal(snapshot)
    assert snapshot.total_debt > 0
