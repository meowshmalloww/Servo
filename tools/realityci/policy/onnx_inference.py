"""Inference-only ONNX adapter.

Proves the adapter boundary is model-agnostic without pretending Servo can
train every policy: this adapter serves diagnosed failure datasets to an
external training owner instead of retraining itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from ..hashing import HASH_PREFIX
from ..policy.base import SensorPacket
from ..schemas.run import PolicyAdapterKind, PolicyDescriptor


class OnnxInferenceOnlyAdapter:
    REQUIRED_INPUT_SPEC = "rgb-1x96x160+ego-speed"

    def __init__(self, model_path: Path, decision_threshold: float = 0.5) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime is required for the ONNX inference adapter") from exc

        self._path = Path(model_path)
        if not self._path.is_file():
            raise FileNotFoundError(f"ONNX model not found: {self._path}")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(self._path), options, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        self._aux_names = {item.name for item in self._session.get_inputs()[1:]}
        if not 0.0 < decision_threshold < 1.0:
            raise ValueError("decision threshold must be in (0, 1)")
        self._threshold = float(decision_threshold)
        self._sha256 = HASH_PREFIX + hashlib.sha256(self._path.read_bytes()).hexdigest()

    @property
    def descriptor(self) -> PolicyDescriptor:
        return PolicyDescriptor(
            adapter=PolicyAdapterKind.ONNX_INFERENCE_ONLY,
            checkpoint_uri=str(self._path),
            checkpoint_sha256=self._sha256,
            input_spec=self.REQUIRED_INPUT_SPEC,
            supports_training=False,
            trainable_adapter=None,
        )

    def reset(self, seed: int) -> None:
        del seed

    def observe(self, packet: SensorPacket) -> float:
        if packet.frame_rgb is None:
            return 0.0
        frame = np.asarray(packet.frame_rgb, dtype=np.float32) / 255.0
        if frame.shape != (96, 160, 3):
            raise ValueError(f"unexpected frame shape: {frame.shape}")
        nchw = frame.transpose(2, 0, 1)[None]
        feeds = {self._input_name: nchw}
        if "ego_speed" in self._aux_names:
            feeds["ego_speed"] = np.array([packet.ego_speed_mps], dtype=np.float32)
        output = self._session.run(None, feeds)[0]
        probability = float(np.asarray(output).reshape(-1)[0])
        return float(np.clip(probability, 0.0, 1.0))

    def close(self) -> None:
        return None
