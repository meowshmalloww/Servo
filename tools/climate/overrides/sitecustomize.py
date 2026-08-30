"""Fail-closed stubs for ClimateNeRF's absent optional MTMT submodule.

The upstream dataset package imports MTMT at module load time even when shadow
prediction is disabled.  These stubs permit non-shadow training; requesting a
shadow operation still raises immediately and never fabricates an output.
"""

from __future__ import annotations

import sys
import types
import os
from pathlib import Path

import tinycudann as tcnn


def _unavailable(*_args, **_kwargs):
    raise RuntimeError(
        "ClimateNeRF shadow prediction is disabled: the MTMT source and "
        "checkpoint have not passed Servo's license/hash audit"
    )


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    return module


_package("datasets.shadow_tools")
_package("datasets.shadow_tools.MTMT")
_package("datasets.shadow_tools.MTMT.networks")
network = types.ModuleType("datasets.shadow_tools.MTMT.networks.MTMT")
network.build_model = _unavailable
sys.modules[network.__name__] = network
_package("datasets.shadow_tools.MTMT.utils")
utility = types.ModuleType("datasets.shadow_tools.MTMT.utils.util")
utility.crf_refine = _unavailable
sys.modules[utility.__name__] = utility

# ClimateNeRF's repository straddles the mmseg 0.x/1.x API rename.  Prefer the
# real audited dependency when installed and expose the names used upstream.
# The RGB-only image intentionally remains fail-closed rather than providing
# mock semantic labels.
try:
    import torch
    import mmseg.apis as apis
    from mmseg.apis import inference_segmentor, init_segmentor
    from mmseg.core import get_classes

    def _inference_model_compat(model, image):
        result = inference_segmentor(model, image)
        prediction = result[0] if isinstance(result, (list, tuple)) else result
        downsample = float(os.environ.get(
            "SERVO_CLIMATE_SEMANTIC_DOWNSAMPLE", "1.0"))
        if downsample != 1.0:
            labels = torch.as_tensor(prediction).unsqueeze(0).unsqueeze(0).float()
            height = max(1, round(labels.shape[-2] * downsample))
            width = max(1, round(labels.shape[-1] * downsample))
            prediction = torch.nn.functional.interpolate(
                labels, size=(height, width), mode="nearest").squeeze(0).squeeze(0).long()
        return types.SimpleNamespace(
            pred_sem_seg=types.SimpleNamespace(data=torch.as_tensor(prediction)))

    apis.inference_model = _inference_model_compat
    apis.init_model = init_segmentor
    utils = types.ModuleType("mmseg.utils")
    utils.get_classes = get_classes
    sys.modules[utils.__name__] = utils
except ImportError:
    mmseg = _package("mmseg")
    apis = types.ModuleType("mmseg.apis")
    apis.inference_model = _unavailable
    apis.init_model = _unavailable
    sys.modules[apis.__name__] = apis
    utils = types.ModuleType("mmseg.utils")
    utils.get_classes = _unavailable
    sys.modules[utils.__name__] = utils
    mmcv = types.ModuleType("mmcv")
    mmcv.Config = type("UnavailableConfig", (), {"fromfile": staticmethod(_unavailable)})
    sys.modules["mmcv"] = mmcv

# tiny-cuda-nn 1.6 returns FP16 encoding tensors on this CUDA 11.3 build even
# when PyTorch Lightning is configured for precision=32. ClimateNeRF feeds
# those tensors directly to FP32 torch.nn.Linear layers, which aborts with a
# dtype mismatch on Ada GPUs. Preserve autograd while restoring the FP32
# boundary expected by the upstream network.
_encoding_forward = tcnn.Encoding.forward


def _encoding_forward_float32(self, value):
    return _encoding_forward(self, value).float()


tcnn.Encoding.forward = _encoding_forward_float32

# Upstream counts appearance embeddings with ``len(os.listdir(images))``.
# Servo preserves COLMAP's nested image names (for example
# ``video-000/00000000.png``), so that expression incorrectly returns one.
# Return the actual relative image entries only for this exact dataset folder;
# all other filesystem behavior remains untouched.
_original_listdir = os.listdir


def _servo_colmap_listdir(path):
    candidate = Path(path)
    if candidate.as_posix().rstrip("/") == "/data/images" and candidate.is_dir():
        return [
            str(item.relative_to(candidate))
            for item in candidate.rglob("*")
            if item.is_file()
        ]
    return _original_listdir(path)


os.listdir = _servo_colmap_listdir
