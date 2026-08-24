"""Load a verified locally cached gsplat binary without installing packages."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import platform
import sys
import zipfile
from pathlib import Path
from typing import Any


_DLL_HANDLES: list[Any] = []
_RECEIPT: dict[str, Any] | None = None


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def prepare_gsplat_runtime() -> dict[str, Any]:
    """Preload a matching native wheel artifact when Windows JIT is unavailable.

    Servo never invokes pip here. The loader accepts only an existing CPython
    3.11 win_amd64 gsplat 1.5.3 wheel, verifies its metadata and zip CRC, then
    extracts the single native module into Servo's content-addressed cache.
    """

    global _RECEIPT
    if _RECEIPT is not None:
        return dict(_RECEIPT)
    if os.name != "nt" or "gsplat.csrc" in sys.modules:
        _RECEIPT = {"mode": "default-import"}
        return dict(_RECEIPT)

    import torch

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    configured = os.environ.get("SERVO_GSPLAT_WHEEL")
    candidates = [Path(configured)] if configured else []
    pip_wheels = local_app_data / "pip" / "cache" / "wheels"
    if not candidates and pip_wheels.is_dir():
        candidates = sorted(
            pip_wheels.rglob("gsplat-1.5.3-cp311-cp311-win_amd64.whl")
        )
    wheel = next((path.resolve() for path in candidates if path.is_file()), None)
    if wheel is None:
        _RECEIPT = {"mode": "jit", "reason": "no-compatible-cached-wheel"}
        return dict(_RECEIPT)

    wheel_payload = wheel.read_bytes()
    wheel_sha256 = _sha256(wheel_payload)
    with zipfile.ZipFile(wheel) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError("The cached gsplat wheel failed its CRC check.")
        metadata = archive.read("gsplat-1.5.3.dist-info/METADATA").decode("utf-8")
        wheel_metadata = archive.read("gsplat-1.5.3.dist-info/WHEEL").decode("utf-8")
        if "Version: 1.5.3" not in {
            line.strip() for line in metadata.splitlines()
        }:
            raise RuntimeError("The cached gsplat wheel has an unexpected version.")
        if "Tag: cp311-cp311-win_amd64" not in wheel_metadata:
            raise RuntimeError("The cached gsplat wheel has an incompatible ABI tag.")
        extension_payload = archive.read("gsplat/csrc.pyd")

    cache = (
        local_app_data
        / "Servo"
        / "runtime-cache"
        / "gsplat-1.5.3"
        / wheel_sha256.removeprefix("sha256:")
    )
    cache.mkdir(parents=True, exist_ok=True)
    extension = cache / "csrc.pyd"
    if not extension.is_file() or _sha256(extension.read_bytes()) != _sha256(
        extension_payload
    ):
        temporary = cache / f"csrc-{os.getpid()}.tmp"
        temporary.write_bytes(extension_payload)
        os.replace(temporary, extension)

    for directory in (
        Path(torch.__file__).resolve().parent / "lib",
        Path(os.environ.get("CUDA_PATH", "")) / "bin",
    ):
        if directory.is_dir():
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    specification = importlib.util.spec_from_file_location("gsplat.csrc", extension)
    if specification is None or specification.loader is None:
        raise RuntimeError("The cached gsplat extension could not be resolved.")
    module = importlib.util.module_from_spec(specification)
    sys.modules["gsplat.csrc"] = module
    try:
        specification.loader.exec_module(module)
    except Exception:
        sys.modules.pop("gsplat.csrc", None)
        raise
    _RECEIPT = {
        "mode": "verified-cached-wheel",
        "wheelSha256": wheel_sha256,
        "extensionSha256": _sha256(extension_payload),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
    }
    return dict(_RECEIPT)
