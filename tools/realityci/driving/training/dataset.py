"""Sealed TinyDrive dataset manifests with hidden-seed isolation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from ...hashing import canonical_json_bytes, sha256_digest, sha256_file
from ...simulation.session_store import atomic_write_json


def seal_dataset_manifest(output: Path, *, observation_source: str, expert_source: str, training_seeds: list[int], hidden_seeds: list[int], route_hashes: list[str], sample_files: list[Path], augmentation: dict) -> dict:
    overlap = set(training_seeds) & set(hidden_seeds)
    if overlap:
        raise ValueError(f"hidden seeds leaked into training: {sorted(overlap)}")
    samples = [{"uri": str(path.resolve()), "sha256": sha256_file(str(path))} for path in sample_files]
    payload = {
        "schema_name": "servo.tinydrive-dataset/v1",
        "observation_source": observation_source,
        "expert_source": expert_source,
        "training_seeds": sorted(training_seeds),
        "route_hashes": sorted(set(route_hashes)),
        "samples": samples,
        "augmentation": augmentation,
        "hidden_set_exclusion_receipt": sha256_digest(canonical_json_bytes({"training": sorted(training_seeds), "hidden_hash": sha256_digest(canonical_json_bytes(sorted(hidden_seeds)))})),
    }
    payload["content_hash"] = sha256_digest(canonical_json_bytes(payload))
    atomic_write_json(output, payload)
    return payload


class TinyDriveDataset(Dataset):
    def __init__(self, sample_files: list[Path]) -> None:
        self.samples: list[dict[str, np.ndarray]] = []
        for path in sample_files:
            with np.load(path, allow_pickle=False) as data:
                sample = {key: np.array(data[key], copy=True) for key in data.files}
            required = {"frames", "auxiliary", "waypoints", "desired_speed"}
            if set(sample) != required:
                raise ValueError(f"TinyDrive sample fields mismatch in {path}")
            self.samples.append(sample)

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        sample = self.samples[index]
        frames = torch.from_numpy(sample["frames"]).float() / 255.0
        return frames, torch.from_numpy(sample["auxiliary"]).float(), torch.from_numpy(sample["waypoints"]).float(), torch.tensor(float(sample["desired_speed"]), dtype=torch.float32)
