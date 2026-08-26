"""Hidden-seed isolation.

Seed spaces are structurally partitioned so the Trainer/Curriculum Planner
can never observe hidden exam material: this module owns the partitions,
seals hidden manifests behind a content-addressed receipt, and hands the
examiner an opaque bundle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..hashing import canonical_json_bytes
from ..schemas.base import utc_now
from ..schemas.base import verify_seal
from ..schemas.scenario import ScenarioManifest
from ..pools import build_occluded_pool


TRAINING_SEED_BASE = 41_000_000
HIDDEN_SEED_BASE = 87_000_000
PROTECTED_SEED_BASE = 73_000_000


@dataclass(frozen=True)
class SeedPartition:
    training_base: int
    hidden_base: int
    protected_base: int

    def training_seed(self, index: int) -> int:
        return TRAINING_SEED_BASE + index

    def hidden_seed(self, index: int) -> int:
        return HIDDEN_SEED_BASE + index

    def protected_seed(self, index: int) -> int:
        return PROTECTED_SEED_BASE + index


DEFAULT_PARTITION = SeedPartition(
    training_base=TRAINING_SEED_BASE,
    hidden_base=HIDDEN_SEED_BASE,
    protected_base=PROTECTED_SEED_BASE,
)


class SeedVault:
    """Seals hidden exam manifests into a directory with a verifiable receipt."""

    SCHEMA = "servo.realityci.seed-vault/v1"

    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = Path(vault_dir)
        self.sealed_path = self.vault_dir / "sealed-manifests.json"
        self.receipt_path = self.vault_dir / "vault-receipt.json"

    def seal_hidden(self, hidden_manifests: list[ScenarioManifest], campaign_id: str | None) -> str:
        if not hidden_manifests:
            raise ValueError("cannot seal an empty hidden set")
        sealed_manifests = [
            m if m.content_hash else m.sealed() for m in hidden_manifests
        ]
        for manifest in sealed_manifests:
            verify_seal(manifest)

        self.vault_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.SCHEMA,
            "campaign_id": campaign_id,
            "created_at": utc_now().isoformat(),
            "manifests": [m.model_dump(mode="json") for m in sealed_manifests],
        }
        blob = canonical_json_bytes(payload)
        receipt_hash = "sha256:" + hashlib.sha256(blob).hexdigest()
        self.sealed_path.write_bytes(blob)
        receipt = {
            "schema": self.SCHEMA + ".receipt",
            "scenario_count": len(hidden_manifests),
            "sealed_sha256": receipt_hash,
            "seed_range_lo": min(m.seed for m in hidden_manifests),
            "seed_range_hi": max(m.seed for m in hidden_manifests),
            "created_at": utc_now().isoformat(),
        }
        self.receipt_path.write_text(json.dumps(receipt, indent=2))
        return receipt_hash

    def open_for_examiner(self) -> tuple[list[ScenarioManifest], dict]:
        receipt = json.loads(self.receipt_path.read_text())
        blob = self.sealed_path.read_bytes()
        actual = "sha256:" + hashlib.sha256(blob).hexdigest()
        if actual != receipt["sealed_sha256"]:
            raise ValueError("hidden vault receipt mismatch: sealed material was modified")
        payload = json.loads(blob.decode("utf-8"))
        manifests = [ScenarioManifest.model_validate(m) for m in payload["manifests"]]
        return manifests, receipt

    @staticmethod
    def build_hidden_manifests(count: int, seed_base: int) -> list[ScenarioManifest]:
        del seed_base
        return build_occluded_pool(HIDDEN_SEED_BASE, count)
