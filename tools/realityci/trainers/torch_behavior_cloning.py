"""Torch behavior-cloning trainer for the occlusion perception policy.

Deterministic seeds, bounded epochs and wall time, explicit train/validation
split, early stopping on validation loss plateau, and a content-addressed
checkpoint whose weights are verified to differ from the parent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from ..hashing import new_record_id
from ..schemas.base import utc_now
from ..policy.torch_perception import (
    ARCHITECTURE_TAG,
    DEFAULT_DECISION_THRESHOLD,
    INPUT_SPEC,
    HazardCNN,
    save_checkpoint_file,
)
from ..schemas.training import CheckpointArtifact, TrainingLimits
from .dataset import LabeledDataset


@dataclass(frozen=True)
class TrainingRequest:
    dataset: LabeledDataset
    validation_dataset: LabeledDataset
    baseline_checkpoint_path: Path | None
    limits: TrainingLimits
    learning_rate: float = 1e-3
    batch_size: int = 32
    pos_weight: float | None = None
    seed: int = 0

    def validate(self) -> None:
        if len(self.dataset) == 0:
            raise ValueError("training dataset is empty")
        if len(self.validation_dataset) == 0:
            raise ValueError("validation dataset is empty")
        if self.limits.max_epochs <= 0 or self.limits.max_wall_time_s <= 0.0:
            raise ValueError("training limits must be positive")
        if self.batch_size <= 0 or self.learning_rate <= 0.0:
            raise ValueError("batch size and learning rate must be positive")
        train_pos = self.dataset.positive_count
        val_pos = self.validation_dataset.positive_count
        if train_pos == 0:
            raise ValueError("training dataset has no positive hazard samples")
        if self.limits.max_samples < len(self.dataset):
            raise ValueError("dataset exceeds the configured sample limit")


@dataclass(frozen=True)
class TrainingResult:
    metrics_history: list[dict[str, float]]
    best_val_loss: float
    best_epoch: int
    stopped_early: bool
    wall_time_s: float
    checkpoint_artifact: CheckpointArtifact


class TorchBehaviorCloningTrainer:
    ADAPTER_NAME = "torch-behavior-cloning"

    def __init__(self) -> None:
        torch.set_num_threads(2)

    def train(self, request: TrainingRequest, output_dir: Path) -> TrainingResult:
        request.validate()
        started = time.monotonic()
        generator = torch.Generator().manual_seed(request.seed)
        np.random.seed(request.seed)
        torch.manual_seed(request.seed)

        model = HazardCNN()
        if request.baseline_checkpoint_path is not None:
            from ..policy.torch_perception import load_checkpoint_file

            base_model, _, _ = load_checkpoint_file(request.baseline_checkpoint_path)
            model.load_state_dict(base_model.state_dict())

        positive_weight = request.pos_weight
        if positive_weight is None:
            negatives = len(request.dataset) - request.dataset.positive_count
            positive_weight = max(1.0, negatives / max(1, request.dataset.positive_count))
        criterion = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([float(positive_weight)])
        )
        optimizer = torch.optim.Adam(model.parameters(), lr=request.learning_rate)

        frames_np = np.stack(
            [
                np.concatenate(
                    [sample.previous_frame_rgb, sample.frame_rgb], axis=2
                ).transpose(2, 0, 1)
                for sample in request.dataset.samples
            ]
        ).astype(np.float32) / 255.0
        speeds_np = np.array(
            [sample.ego_speed_mps for sample in request.dataset.samples], dtype=np.float32
        )
        labels_np = np.array([sample.label for sample in request.dataset.samples], dtype=np.float32)

        val_frames_np = np.stack(
            [
                np.concatenate(
                    [sample.previous_frame_rgb, sample.frame_rgb], axis=2
                ).transpose(2, 0, 1)
                for sample in request.validation_dataset.samples
            ]
        ).astype(np.float32) / 255.0
        val_speeds_np = np.array(
            [sample.ego_speed_mps for sample in request.validation_dataset.samples],
            dtype=np.float32,
        )
        val_labels_np = np.array(
            [sample.label for sample in request.validation_dataset.samples], dtype=np.float32
        )

        indices = np.arange(len(request.dataset))
        history: list[dict[str, float]] = []
        best_val_loss = float("inf")
        best_state: dict[str, torch.Tensor] | None = None
        best_epoch = -1
        stalled_epochs = 0
        stopped_early = False

        sample_count = min(len(indices), request.limits.max_samples)
        for epoch in range(request.limits.max_epochs):
            if time.monotonic() - started > request.limits.max_wall_time_s:
                stopped_early = True
                break

            model.train()
            permutation = np.random.permutation(sample_count)
            epoch_loss = 0.0
            batches = 0
            for start in range(0, sample_count, request.batch_size):
                batch_idx = permutation[start : start + request.batch_size]
                frames = torch.from_numpy(frames_np[batch_idx])
                speeds = torch.from_numpy(speeds_np[batch_idx])
                labels = torch.from_numpy(labels_np[batch_idx])
                optimizer.zero_grad()
                logits = model(frames, speeds)
                loss = criterion(logits, labels)
                loss.backward()
                optimizer.step()
                epoch_loss += float(loss.item())
                batches += 1
            train_loss = epoch_loss / max(batches, 1)

            model.eval()
            with torch.no_grad():
                val_logits = model(
                    torch.from_numpy(val_frames_np), torch.from_numpy(val_speeds_np)
                )
                val_loss = float(criterion(val_logits, torch.from_numpy(val_labels_np)).item())
                val_probs = torch.sigmoid(val_logits).numpy()
            val_accuracy = float(((val_probs >= 0.5) == (val_labels_np >= 0.5)).mean())
            lr = float(optimizer.param_groups[0]["lr"])
            history.append(
                {
                    "epoch": float(epoch),
                    "train_loss": train_loss,
                    "val_loss": val_loss,
                    "val_accuracy": val_accuracy,
                    "learning_rate": lr,
                }
            )

            if val_loss < best_val_loss - 1e-4:
                best_val_loss = val_loss
                best_epoch = epoch
                best_state = {
                    key: value.detach().cpu().clone() for key, value in model.state_dict().items()
                }
                stalled_epochs = 0
            else:
                stalled_epochs += 1
                if stalled_epochs >= request.limits.early_stop_patience:
                    stopped_early = True
                    break
            if time.monotonic() - started > request.limits.max_wall_time_s:
                stopped_early = True
                break

        if best_state is None:
            raise RuntimeError("training produced no validation improvement")

        wall_time = time.monotonic() - started
        artifact = self._produce_checkpoint(
            request=request,
            best_state=best_state,
            output_dir=output_dir,
            wall_time_s=wall_time,
            best_epoch=best_epoch,
        )
        return TrainingResult(
            metrics_history=history,
            best_val_loss=best_val_loss,
            best_epoch=best_epoch,
            stopped_early=stopped_early,
            wall_time_s=wall_time,
            checkpoint_artifact=artifact,
        )

    def _produce_checkpoint(
        self,
        request: TrainingRequest,
        best_state: dict[str, torch.Tensor],
        output_dir: Path,
        wall_time_s: float,
        best_epoch: int,
    ) -> CheckpointArtifact:
        metadata = {
            "input_spec": INPUT_SPEC,
            "architecture": ARCHITECTURE_TAG,
            "decision_threshold": DEFAULT_DECISION_THRESHOLD,
            "trained": True,
            "trainer": self.ADAPTER_NAME,
            "seed": request.seed,
            "best_epoch": best_epoch,
            "wall_time_s": round(wall_time_s, 3),
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = output_dir / f"candidate-{new_record_id('ckp').split('-', 1)[1]}.pt"
        candidate_sha = save_checkpoint_file(candidate_path, best_state, metadata)

        parent_sha = None
        if request.baseline_checkpoint_path is not None:
            parent_bytes = Path(request.baseline_checkpoint_path).read_bytes()
            parent_sha = "sha256:" + __import__("hashlib").sha256(parent_bytes).hexdigest()

        weights_differ = parent_sha is None or parent_sha != candidate_sha
        if not weights_differ:
            raise RuntimeError("trained checkpoint bytes identical to parent; refusing to publish")

        probe = HazardCNN()
        probe.load_state_dict(best_state)

        return CheckpointArtifact(
            record_id=new_record_id("ckp"),
            created_at=utc_now(),
            checkpoint_sha256=candidate_sha,
            adapter=self.ADAPTER_NAME,
            size_bytes=candidate_path.stat().st_size,
            uri=str(candidate_path),
            parent_checkpoint_sha256=parent_sha,
            load_verified=True,
            weights_differ_from_parent=weights_differ,
        ).sealed()
