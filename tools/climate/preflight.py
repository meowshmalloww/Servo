"""Native-Windows ClimateNeRF capability and CUDA execution preflight."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .source_receipt import create_source_receipt


def _module(name: str) -> dict[str, Any]:
    available = importlib.util.find_spec(name) is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version(name.replace("_", "-"))
        except importlib.metadata.PackageNotFoundError:
            version = None
    return {"available": available, "version": version}


def _nvcc() -> dict[str, Any]:
    executable = shutil.which("nvcc")
    if not executable:
        candidate = Path(os.environ.get("CUDA_PATH", "")) / "bin" / "nvcc.exe"
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        return {"available": False, "version": None, "path": None}
    result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                            timeout=15, check=False)
    return {"available": result.returncode == 0, "version": result.stdout.strip(), "path": executable}


def _cuda_qualification() -> dict[str, Any]:
    result: dict[str, Any] = {"executed": False, "passed": False}
    try:
        import torch
        result.update({"torch_version": torch.__version__, "cuda_runtime": torch.version.cuda,
                       "cuda_available": torch.cuda.is_available()})
        if not torch.cuda.is_available():
            result["reason"] = "torch.cuda.is_available() is false"
            return result
        device = torch.device("cuda")
        torch.manual_seed(7103)
        model = torch.nn.Sequential(torch.nn.Linear(6, 32), torch.nn.SiLU(), torch.nn.Linear(32, 4)).to(device)
        rays = torch.randn((4096, 6), device=device, requires_grad=True)
        output = model(rays)
        loss = output.square().mean()
        loss.backward()
        torch.cuda.synchronize()
        finite = bool(torch.isfinite(output).all() and torch.isfinite(rays.grad).all())
        free, total = torch.cuda.mem_get_info()
        result.update({
            "executed": True, "passed": finite, "finite_output": finite,
            "forward_shape": list(output.shape), "backward_gradient": rays.grad is not None,
            "device": torch.cuda.get_device_name(0),
            "compute_capability": list(torch.cuda.get_device_capability(0)),
            "free_vram_bytes": free, "total_vram_bytes": total,
        })
    except Exception as error:  # surfaced verbatim in machine-readable preflight
        result["reason"] = f"{type(error).__name__}: {error}"
    return result


def run_preflight(servo_root: Path, climate_source: Path) -> dict[str, Any]:
    servo_root = servo_root.resolve()
    climate_source = climate_source.resolve()
    receipt = create_source_receipt(climate_source)
    dependencies = {name: _module(name) for name in (
        "tinycudann", "vren", "torch_scatter", "pytorch_lightning", "torchmetrics",
        "kornia", "cv2", "numpy", "scipy", "mmseg", "mmcv", "cupy", "pynvrtc",
        "open3d", "gsplat",
    )}
    cuda = _cuda_qualification()
    core_missing = [name for name in ("tinycudann", "vren", "torch_scatter")
                    if not dependencies[name]["available"]]
    semantic_ready = dependencies["mmseg"]["available"] and dependencies["mmcv"]["available"]
    shadow_tree = climate_source / "datasets" / "shadow_tools" / "MTMT"
    shadow_weights = list(shadow_tree.rglob("*.pth")) if shadow_tree.is_dir() else []
    style_weights = list((climate_source / "datasets" / "stylize_tools").rglob("*.pth"))
    backend_ready = cuda.get("passed", False) and not core_missing
    warnings = [
        "ClimateNeRF output is generated visual weather, not observed weather or physics.",
        "Checkpoint licenses and hashes must be recorded before use.",
    ]
    if core_missing:
        warnings.append("Reference backend cannot load: missing " + ", ".join(core_missing))
    return {
        "schema_name": "servo.climate-preflight/v1",
        "servo_root": str(servo_root), "climate_source": str(climate_source),
        "platform": platform.platform(), "python_version": sys.version,
        "source_tree_receipt": receipt,
        "cuda_toolkit": _nvcc(), "cuda_qualification": cuda,
        "dependencies": dependencies,
        "custom_extension_status": dependencies["vren"],
        "tiny_cuda_nn_status": dependencies["tinycudann"],
        "semantic_backend_status": {"ready": semantic_ready, "weights_audited": False},
        "shadow_backend_status": {"source_present": shadow_tree.is_dir(),
                                  "checkpoint_count": len(shadow_weights), "weights_audited": False},
        "style_backend_status": {"checkpoint_count": len(style_weights), "weights_audited": False},
        "panorama_support": {"source_present": (climate_source / "render_panorama.py").is_file(),
                             "ready": backend_ready},
        "effect_readiness": {
            "smog": "ready-relative-units" if backend_ready else "unsupported",
            "flood": "degraded" if backend_ready else "unsupported",
            "snow": "ready" if backend_ready and shadow_weights else "unsupported",
            "stylization": "ready" if backend_ready and semantic_ready and style_weights else "unsupported",
        },
        "reference_backend_ready": backend_ready,
        "climate_model_qualification": {"passed": False,
            "reason": "Core ClimateNeRF modules were not executed" if not backend_ready else
                      "Scene checkpoint and calibrated dataset are still required"},
        "missing_dependencies": core_missing,
        "unsupported_features": [key for key, value in {
            "semantic_prediction": semantic_ready,
            "shadow_prediction": bool(shadow_weights),
            "semantic_stylization": semantic_ready and bool(style_weights),
        }.items() if not value],
        "license_warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--servo-root", required=True, type=Path)
    parser.add_argument("--climate-source", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_preflight(args.servo_root, args.climate_source)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if report["reference_backend_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
