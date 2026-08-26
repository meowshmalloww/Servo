"""Small deterministic CNN perception policy with content-addressed checkpoints.

Input: one RGB frame 96x160 plus ego speed.  Output: pedestrian hazard
probability in [0, 1].  The planner threshold is part of the checkpoint
metadata so evaluation is reproducible from the artifact alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import torch
from torch import nn

from ..hashing import HASH_PREFIX
from ..policy.base import SensorPacket
from ..schemas.run import PolicyAdapterKind, PolicyDescriptor

CHECKPOINT_FILE_SCHEMA = "servo.realityci.checkpoint-file/v1"
INPUT_SPEC = "rgb-stack-2x96x160+ego-speed"
ARCHITECTURE_TAG = "hazard-cnn-v2-stacked"
DEFAULT_DECISION_THRESHOLD = 0.5
STACK_DEPTH = 2


class HazardCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3 * STACK_DEPTH, 16, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.speed_encoder = nn.Sequential(nn.Linear(1, 8), nn.ReLU())
        self.head = nn.Sequential(
            nn.Linear(64 + 8, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, frame_nchw: torch.Tensor, ego_speed: torch.Tensor) -> torch.Tensor:
        pooled = self.features(frame_nchw).flatten(1)
        speed = self.speed_encoder(ego_speed.unsqueeze(1))
        logits = self.head(torch.cat([pooled, speed], dim=1))
        return logits.squeeze(1)


def stack_frames(previous: np.ndarray | None, current: np.ndarray) -> np.ndarray:
    """Channel-concatenate up to STACK_DEPTH recent frames (oldest first)."""

    if previous is None:
        previous = current
    return np.concatenate([previous, current], axis=2)


def save_checkpoint_file(
    path: Path,
    state_dict: dict[str, torch.Tensor],
    metadata: dict[str, object],
) -> str:
    payload = {
        "schema": CHECKPOINT_FILE_SCHEMA,
        "architecture": ARCHITECTURE_TAG,
        "state_dict": {key: value.detach().cpu() for key, value in state_dict.items()},
        "metadata": metadata,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, tmp_path)
    tmp_path.replace(path)
    return HASH_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def load_checkpoint_file(path: Path) -> tuple[HazardCNN, dict[str, object], str]:
    payload = torch.load(Path(path), map_location="cpu", weights_only=False)
    if payload.get("schema") != CHECKPOINT_FILE_SCHEMA:
        raise ValueError(f"unsupported checkpoint schema: {payload.get('schema')!r}")
    if payload.get("architecture") != ARCHITECTURE_TAG:
        raise ValueError(f"unsupported architecture: {payload.get('architecture')!r}")
    model = HazardCNN()
    model.load_state_dict(payload["state_dict"])
    digest = HASH_PREFIX + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return model, dict(payload.get("metadata", {})), digest


class TorchOcclusionPerceptionAdapter:
    def __init__(self, checkpoint_path: Path | None = None) -> None:
        self._previous_frame: np.ndarray | None = None
        if checkpoint_path is None:
            self._model = HazardCNN()
            self._metadata: dict[str, object] = {
                "input_spec": INPUT_SPEC,
                "decision_threshold": DEFAULT_DECISION_THRESHOLD,
                "trained": False,
            }
            self._checkpoint_sha256 = ""
            self._checkpoint_uri = ""
        else:
            self._model, self._metadata, self._checkpoint_sha256 = load_checkpoint_file(checkpoint_path)
            self._checkpoint_uri = str(checkpoint_path)
        self._model.eval()

    @property
    def decision_threshold(self) -> float:
        return float(self._metadata.get("decision_threshold", DEFAULT_DECISION_THRESHOLD))

    def set_decision_threshold(self, threshold: float) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("decision threshold must be in (0, 1)")
        self._metadata["decision_threshold"] = float(threshold)

    @property
    def descriptor(self) -> PolicyDescriptor:
        if not self._checkpoint_uri:
            raise RuntimeError("adapter has no persisted checkpoint; persist it first")
        return PolicyDescriptor(
            adapter=PolicyAdapterKind.TORCH_OCCLUSION_PERCEPTION,
            checkpoint_uri=self._checkpoint_uri,
            checkpoint_sha256=self._checkpoint_sha256,
            input_spec=INPUT_SPEC,
            supports_training=True,
            trainable_adapter="torch-behavior-cloning",
        )

    @property
    def model(self) -> HazardCNN:
        return self._model

    def state_dict(self) -> dict[str, torch.Tensor]:
        return {key: value.detach().cpu().clone() for key, value in self._model.state_dict().items()}

    def reset(self, seed: int) -> None:
        del seed
        self._previous_frame = None
        self._model.eval()

    def observe(self, packet: SensorPacket) -> float:
        if packet.frame_rgb is None:
            return 0.0
        current = np.asarray(packet.frame_rgb, dtype=np.uint8)
        if current.shape != (96, 160, 3):
            raise ValueError(f"unexpected frame shape: {current.shape}")
        stacked = stack_frames(self._previous_frame, current).astype(np.float32) / 255.0
        self._previous_frame = current.copy()
        tensor = torch.from_numpy(stacked.transpose(2, 0, 1)).unsqueeze(0)
        speed = torch.tensor([float(packet.ego_speed_mps)], dtype=torch.float32)
        with torch.no_grad():
            logits = self._model(tensor, speed)
        probability = torch.sigmoid(logits).item()
        return float(probability)

    def close(self) -> None:
        return None
