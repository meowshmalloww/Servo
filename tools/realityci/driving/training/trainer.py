"""Resource-bounded deterministic local ServoTinyDrive trainer."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, random_split

from ...hashing import sha256_file
from ...simulation.session_store import atomic_write_json
from ..policies.tinydrive import ServoTinyDriveNetwork
from .dataset import TinyDriveDataset


@dataclass(frozen=True)
class TinyDriveTrainingConfig:
    seed: int = 1234
    max_epochs: int = 20
    batch_size: int = 16
    learning_rate: float = 3e-4
    early_stop_patience: int = 4
    maximum_wall_time_s: float = 900.0
    validation_fraction: float = 0.2
    maximum_samples: int = 20000
    resource_profile: str = "balanced"


class TinyDriveTrainer:
    VERSION = "servo-tinydrive-trainer/v1"

    def train(self, sample_files: list[Path], parent_checkpoint: Path, output_dir: Path, config: TinyDriveTrainingConfig = TinyDriveTrainingConfig()) -> dict:
        if not sample_files or len(sample_files) > config.maximum_samples:
            raise ValueError("TinyDrive sample count is empty or exceeds the configured limit")
        if config.resource_profile not in {"balanced", "carla-visual", "hybrid"}:
            raise ValueError("unsupported resource profile")
        random.seed(config.seed); np.random.seed(config.seed); torch.manual_seed(config.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(config.seed)
        torch.use_deterministic_algorithms(True, warn_only=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        package = torch.load(parent_checkpoint, map_location=device, weights_only=True)
        model = ServoTinyDriveNetwork(
            frame_count=int(package["config"]["frame_count"]),
            waypoint_count=int(package["config"]["waypoint_count"]),
        ).to(device)
        model.load_state_dict(package["state_dict"], strict=True)
        dataset = TinyDriveDataset(sample_files)
        validation_count = max(1, round(len(dataset) * config.validation_fraction))
        if validation_count >= len(dataset):
            raise ValueError("TinyDrive training requires at least two samples")
        training, validation = random_split(dataset, [len(dataset) - validation_count, validation_count], generator=torch.Generator().manual_seed(config.seed))
        train_loader = DataLoader(training, batch_size=min(config.batch_size, len(training)), shuffle=True, generator=torch.Generator().manual_seed(config.seed))
        val_loader = DataLoader(validation, batch_size=min(config.batch_size, len(validation)), shuffle=False)
        optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
        started = time.monotonic(); best_loss = float("inf"); best_state = None; stale = 0; history = []

        def loss_for(batch):
            frames, auxiliary, target_points, target_speed = (item.to(device) for item in batch)
            points, speed = model(frames, auxiliary)
            waypoint_loss = torch.nn.functional.smooth_l1_loss(points, target_points)
            speed_loss = torch.nn.functional.smooth_l1_loss(speed, target_speed)
            smoothness = (points[:, 2:] - 2 * points[:, 1:-1] + points[:, :-2]).abs().mean()
            return waypoint_loss + 0.25 * speed_loss + 0.02 * smoothness

        for epoch in range(config.max_epochs):
            if time.monotonic() - started > config.maximum_wall_time_s:
                stop_reason = "wall-time-limit"; break
            model.train(); train_total = 0.0
            for batch in train_loader:
                optimizer.zero_grad(set_to_none=True); loss = loss_for(batch); loss.backward(); optimizer.step(); train_total += float(loss.detach().cpu())
            model.eval(); val_total = 0.0
            with torch.inference_mode():
                for batch in val_loader: val_total += float(loss_for(batch).cpu())
            train_loss, val_loss = train_total / len(train_loader), val_total / len(val_loader)
            history.append({"epoch": epoch + 1, "train_loss": train_loss, "validation_loss": val_loss})
            if val_loss + 1e-7 < best_loss:
                best_loss = val_loss; stale = 0
                best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            else:
                stale += 1
                if stale >= config.early_stop_patience:
                    stop_reason = "early-stopping"; break
        else:
            stop_reason = "maximum-epochs"
        if best_state is None:
            raise RuntimeError("TinyDrive training produced no checkpoint")
        output_dir.mkdir(parents=True, exist_ok=True)
        candidate = output_dir / "candidate.pt"
        torch.save({"schema_name": "servo.tinydrive-checkpoint/v1", "state_dict": best_state, "config": package["config"], "parent_sha256": sha256_file(str(parent_checkpoint)), "trainer_version": self.VERSION}, candidate)
        parent_hash, candidate_hash = sha256_file(str(parent_checkpoint)), sha256_file(str(candidate))
        if parent_hash == candidate_hash:
            raise RuntimeError("candidate checkpoint hash did not change")
        summary = {
            "schema_name": "servo.tinydrive-training/v1", "trainer_version": self.VERSION,
            "parent_sha256": parent_hash, "candidate_sha256": candidate_hash,
            "device": device, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "pytorch": torch.__version__, "cuda": torch.version.cuda, "config": asdict(config),
            "metrics": history, "best_validation_loss": best_loss, "stop_reason": stop_reason,
            "candidate_uri": str(candidate),
        }
        atomic_write_json(output_dir / "training-summary.json", summary)
        return summary
