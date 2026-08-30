"""Strict inference-only ONNX trajectory adapter with explicit tensor names."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ...hashing import sha256_file
from ...schemas.driving import DrivingPolicyDescriptor, TrajectoryAction, TrajectoryWaypoint
from ..contracts import DrivingObservation, DrivingPolicyAdapter, PolicyResetContext


class OnnxDrivingPolicy(DrivingPolicyAdapter):
    def __init__(self, model_path: Path, *, frames_input: str, auxiliary_input: str, waypoints_output: str, speed_output: str, width: int, height: int) -> None:
        import onnxruntime as ort

        self.model_path = model_path.resolve()
        if not self.model_path.is_file():
            raise ValueError("ONNX policy model does not exist")
        self.session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
        self.frames_input, self.auxiliary_input = frames_input, auxiliary_input
        self.waypoints_output, self.speed_output = waypoints_output, speed_output
        self.width, self.height = width, height
        actual_inputs = {item.name for item in self.session.get_inputs()}
        actual_outputs = {item.name for item in self.session.get_outputs()}
        if {frames_input, auxiliary_input} != actual_inputs:
            raise ValueError(f"ONNX input names mismatch: configured={sorted((frames_input, auxiliary_input))}, actual={sorted(actual_inputs)}")
        if not {waypoints_output, speed_output}.issubset(actual_outputs):
            raise ValueError("ONNX output names mismatch")
        self._descriptor = DrivingPolicyDescriptor(
            adapter="onnx-driving", name="ONNX driving policy", adapter_version="servo-onnx-driving/v1",
            checkpoint_uri=str(self.model_path), checkpoint_sha256=sha256_file(str(self.model_path)),
            trainable=False, eligible_for_promotion=True,
        )

    @property
    def descriptor(self) -> DrivingPolicyDescriptor:
        return self._descriptor

    def reset(self, context: PolicyResetContext) -> None:
        return None

    def infer(self, observation: DrivingObservation) -> TrajectoryAction:
        from PIL import Image

        rgb = observation.camera_rgb["front"]
        image = np.asarray(Image.fromarray(rgb).resize((self.width, self.height)), dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        auxiliary = np.asarray([[observation.ego_speed_mps, *observation.route_target_ego_m[:2]]], dtype=np.float32)
        waypoints, speed = self.session.run([self.waypoints_output, self.speed_output], {self.frames_input: image, self.auxiliary_input: auxiliary})
        if waypoints.shape != (1, 5, 2) or np.asarray(speed).size != 1:
            raise ValueError(f"ONNX output shape mismatch: waypoints={waypoints.shape}, speed={np.asarray(speed).shape}")
        return TrajectoryAction(
            waypoints=tuple(TrajectoryWaypoint(time_offset_s=0.2 * (i + 1), x_forward_m=float(p[0]), y_left_m=float(p[1])) for i, p in enumerate(waypoints[0])),
            desired_speed_mps=float(np.asarray(speed).reshape(-1)[0]), confidence=1.0,
        )
