"""Small trainable vision-and-route trajectory policy for bounded corridors."""

from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path

import numpy as np
import torch
from torch import nn

from ...hashing import sha256_file
from ...schemas.driving import (
    DrivingPolicyDescriptor,
    RouteCommand,
    TrajectoryAction,
    TrajectoryWaypoint,
)
from ..contracts import DrivingObservation, DrivingPolicyAdapter, PolicyResetContext

COMMANDS = tuple(RouteCommand)


class ServoTinyDriveNetwork(nn.Module):
    def __init__(self, frame_count: int = 3, waypoint_count: int = 5) -> None:
        super().__init__()
        self.frame_count = frame_count
        self.waypoint_count = waypoint_count
        self.visual = nn.Sequential(
            nn.Conv2d(frame_count * 3, 24, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(24, 48, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(48, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(64, 96, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((3, 5)), nn.Flatten(),
        )
        auxiliary_size = 1 + 2 + len(COMMANDS)
        self.head = nn.Sequential(
            nn.Linear(96 * 3 * 5 + auxiliary_size, 256), nn.ReLU(), nn.Dropout(0.05),
            nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, waypoint_count * 2 + 1),
        )

    def forward(self, frames: torch.Tensor, auxiliary: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        output = self.head(torch.cat((self.visual(frames), auxiliary), dim=1))
        waypoints = output[:, : self.waypoint_count * 2].reshape(-1, self.waypoint_count, 2)
        desired_speed = torch.nn.functional.softplus(output[:, -1])
        return waypoints, desired_speed


class ServoTinyDrivePolicy(DrivingPolicyAdapter):
    VERSION = "servo-tinydrive/v1"

    def __init__(self, checkpoint: Path, *, device: str = "cpu") -> None:
        self.checkpoint = checkpoint.resolve()
        if not self.checkpoint.is_file():
            raise ValueError(f"TinyDrive checkpoint does not exist: {self.checkpoint}")
        package = torch.load(self.checkpoint, map_location=device, weights_only=True)
        config = package.get("config", {})
        self.model = ServoTinyDriveNetwork(
            frame_count=int(config.get("frame_count", 3)),
            waypoint_count=int(config.get("waypoint_count", 5)),
        ).to(device)
        self.model.load_state_dict(package["state_dict"], strict=True)
        self.model.eval()
        self.device = device
        self.frame_width = int(config.get("width", 256))
        self.frame_height = int(config.get("height", 144))
        self._frames: deque[np.ndarray] = deque(maxlen=self.model.frame_count)
        self._descriptor = DrivingPolicyDescriptor(
            adapter="servo-tinydrive", name="ServoTinyDrive", adapter_version=self.VERSION,
            checkpoint_uri=str(self.checkpoint), checkpoint_sha256=sha256_file(str(self.checkpoint)),
            oracle=False, uses_privileged_state=False, trainable=True,
            eligible_for_promotion=True, input_camera_ids=("front",), uses_ego_speed=True,
        )

    @property
    def descriptor(self) -> DrivingPolicyDescriptor:
        return self._descriptor

    def reset(self, context: PolicyResetContext) -> None:
        random.seed(context.seed)
        np.random.seed(context.seed & 0xFFFFFFFF)
        torch.manual_seed(context.seed)
        self._frames.clear()

    def _resize(self, rgb: np.ndarray) -> np.ndarray:
        from PIL import Image

        return np.asarray(Image.fromarray(rgb).resize((self.frame_width, self.frame_height), Image.Resampling.BILINEAR), dtype=np.uint8)

    def infer(self, observation: DrivingObservation) -> TrajectoryAction:
        if observation.hidden_seed is not None or observation.privileged_actor_state is not None:
            raise ValueError("non-oracle TinyDrive observation contains privileged fields")
        if set(observation.camera_rgb) != {"front"}:
            raise ValueError("ServoTinyDrive requires exactly the declared front camera")
        frame = self._resize(observation.camera_rgb["front"])
        self._frames.append(frame)
        while len(self._frames) < self.model.frame_count:
            self._frames.appendleft(frame)
        stacked = np.concatenate(tuple(self._frames), axis=2).transpose(2, 0, 1)
        frames = torch.from_numpy(stacked.copy()).float().unsqueeze(0).to(self.device) / 255.0
        command = np.zeros(len(COMMANDS), dtype=np.float32)
        command[COMMANDS.index(observation.navigation_command)] = 1.0
        auxiliary_np = np.concatenate((
            np.array([observation.ego_speed_mps / 20.0], dtype=np.float32),
            np.asarray(observation.route_target_ego_m[:2], dtype=np.float32) / 20.0,
            command,
        ))
        auxiliary = torch.from_numpy(auxiliary_np).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            points, speed = self.model(frames, auxiliary)
        points_np = points[0].cpu().numpy()
        waypoints = tuple(
            TrajectoryWaypoint(time_offset_s=0.2 * (index + 1), x_forward_m=float(point[0]), y_left_m=float(point[1]))
            for index, point in enumerate(points_np)
        )
        return TrajectoryAction(waypoints=waypoints, desired_speed_mps=min(20.0, float(speed[0].cpu())), confidence=1.0)


def create_initial_checkpoint(path: Path, *, seed: int = 0, width: int = 256, height: int = 144) -> str:
    torch.manual_seed(seed)
    model = ServoTinyDriveNetwork()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"schema_name": "servo.tinydrive-checkpoint/v1", "state_dict": model.state_dict(), "config": {"frame_count": 3, "waypoint_count": 5, "width": width, "height": height}, "seed": seed},
        path,
    )
    return sha256_file(str(path))
