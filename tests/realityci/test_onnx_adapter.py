from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

torch.manual_seed(11)

try:
    import onnx  # noqa: F401

    HAS_ONNX_EXPORTER = True
except ImportError:
    HAS_ONNX_EXPORTER = False

from tools.realityci.policy.base import SensorPacket
from tools.realityci.policy.onnx_inference import OnnxInferenceOnlyAdapter
from tools.realityci.policy.torch_perception import HazardCNN, TorchOcclusionPerceptionAdapter


def _export_tiny_onnx(path: Path) -> HazardCNN:
    model = HazardCNN()
    model.eval()
    frame = torch.zeros(1, 6, 96, 160)
    speed = torch.zeros(1)
    torch.onnx.export(
        model,
        (frame, speed),
        str(path),
        input_names=["frame", "ego_speed"],
        output_names=["logit"],
        opset_version=17,
        dynamo=False,
    )
    return model


@pytest.mark.skipif(not HAS_ONNX_EXPORTER, reason="onnx exporter not installed in the locked reconstruction environment")
def test_onnx_adapter_matches_torch_outputs(tmp_path: Path) -> None:
    onnx_path = tmp_path / "policy.onnx"
    reference = _export_tiny_onnx(onnx_path)

    adapter = OnnxInferenceOnlyAdapter(onnx_path, decision_threshold=0.5)
    assert adapter.descriptor.supports_training is False
    assert adapter.descriptor.trainable_adapter is None

    rng = np.random.default_rng(0)
    for i in range(4):
        frame = rng.integers(0, 255, size=(96, 160, 3), dtype=np.uint8)
        speed = float(8.0 + i)
        packet = SensorPacket(time_s=float(i), ego_speed_mps=speed, frame_rgb=frame)
        onnx_risk = adapter.observe(packet)

        tensor = torch.from_numpy(frame.astype(np.float32).transpose(2, 0, 1) / 255.0)[None]
        speed_t = torch.tensor([speed], dtype=torch.float32)
        with torch.no_grad():
            expected = float(torch.sigmoid(reference(tensor, speed_t)).item())
        assert abs(onnx_risk - expected) < 1e-4


def test_onnx_adapter_rejects_missing_model(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        OnnxInferenceOnlyAdapter(tmp_path / "missing.onnx")
