"""Base contract for every durable RealityCI record.

Records are immutable, strictly validated (unknown fields rejected), and
sealed with a content hash that covers every field except the hash itself.
`verify_seal` recomputes the hash and fails closed on any mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..hashing import HashMismatch, canonical_json_bytes, sha256_digest

PRODUCER_NAME = "servo-realityci"
PRODUCER_VERSION = "0.1.0"

R = TypeVar("R", bound="RealityCIRecord")


class ProducerInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = PRODUCER_NAME
    version: str = PRODUCER_VERSION


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RealityCIRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str
    record_id: str = Field(pattern=r"^[a-z][a-z0-9-]*-[0-9a-f]{16}$")
    created_at: datetime
    producer: ProducerInfo = Field(default_factory=ProducerInfo)
    campaign_id: Optional[str] = None
    parent_id: Optional[str] = None
    causation_id: Optional[str] = None
    content_hash: str = ""

    def content_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("content_hash", None)
        return payload

    def compute_content_hash(self) -> str:
        return sha256_digest(canonical_json_bytes(self.content_payload()))

    def sealed(self: R) -> R:
        if self.content_hash:
            raise ValueError(f"record {self.record_id} is already sealed")
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


def derived(record: R, /, **updates: Any) -> R:
    payload = record.model_dump()
    payload.pop("content_hash", None)
    payload.update(updates)
    return type(record).model_validate(payload)


def verify_seal(record: RealityCIRecord) -> None:
    computed = record.compute_content_hash()
    if not record.content_hash:
        raise HashMismatch(f"record {record.record_id} is unsealed")
    if record.content_hash != computed:
        raise HashMismatch(
            f"record {record.record_id} failed integrity check: "
            f"sealed {record.content_hash}, computed {computed}"
        )
