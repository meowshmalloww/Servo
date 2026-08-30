#!/usr/bin/env python3
"""Run one bounded, receipt-producing Difix reference-guided repair probe.

This is deliberately a diagnostic. It never edits a Gaussian world and it marks
the repaired image as generated visual evidence, not geometry or collision truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image


SCHEMA = "servo.difix-memory-quality-probe/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def image_metrics(candidate: Image.Image, target: Image.Image) -> dict[str, float]:
    size = target.size
    a = np.asarray(candidate.resize(size, Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
    b = np.asarray(target.convert("RGB"), dtype=np.float32) / 255.0
    error = a - b
    mse = float(np.mean(error * error))
    return {
        "mse": mse,
        "psnrDb": float(-10.0 * math.log10(max(mse, 1.0e-12))),
        "meanAbsoluteError": float(np.mean(np.abs(error))),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--difix-source", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="nvidia/difix_ref")
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-vram-gib", type=float, default=11.0)
    parser.add_argument("--no-cpu-offload", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (args.difix_source, args.input, args.reference):
        if not path.exists():
            raise FileNotFoundError(path)
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"refusing to overwrite nonempty output: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    source_root = args.difix_source.resolve()
    sys.path.insert(0, str(source_root))
    # Difix's pinned diffusers 0.25 UNet imports PositionNet even when its
    # configuration uses ordinary attention and never constructs it. Newer
    # Servo runtimes removed that unused symbol. Supply a fail-closed shim so
    # the official checkpoint can load without downgrading Servo's environment.
    import diffusers.models.embeddings as diffusion_embeddings  # pylint: disable=import-outside-toplevel
    if not hasattr(diffusion_embeddings, "PositionNet"):
        class PositionNet(nn.Module):
            def __init__(self, *unused_args, **unused_kwargs):
                super().__init__()
                raise RuntimeError("Difix requested unsupported GLIGEN PositionNet")

        diffusion_embeddings.PositionNet = PositionNet
    from src.pipeline_difix import DifixPipeline  # pylint: disable=import-error,import-outside-toplevel

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this probe")
    device = torch.device("cuda:0")
    total_vram = torch.cuda.get_device_properties(device).total_memory / 1024**3
    if total_vram > args.max_vram_gib + 1.25:
        # The limit is an experiment policy, not a claim about physical VRAM.
        pass

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)

    started = time.perf_counter()
    pipe = DifixPipeline.from_pretrained(
        args.model,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
        # The pinned checkpoint's VAE and reference-aware UNet definitions were
        # inspected before enabling them: they import only torch/diffusers/peft/
        # einops and contain no filesystem, process, or network operations.
        trust_remote_code=True,
    )
    if args.no_cpu_offload:
        pipe.to(device)
        placement = "cuda-fp16"
    else:
        pipe.enable_model_cpu_offload(gpu_id=0)
        placement = "accelerate-model-cpu-offload-fp16"
    pipe.enable_attention_slicing("max")
    pipe.enable_vae_slicing()
    # Difix uses a skip-connected VAE. Generic diffusers VAE tiling separates
    # skip tensors at incompatible tile sizes and must remain disabled.
    load_seconds = time.perf_counter() - started

    degraded = Image.open(args.input).convert("RGB")
    reference = Image.open(args.reference).convert("RGB")
    target_path = args.target or args.reference
    target = Image.open(target_path).convert("RGB")

    infer_started = time.perf_counter()
    with torch.inference_mode():
        result = pipe(
            "remove degradation",
            image=degraded,
            ref_image=reference,
            height=args.height,
            width=args.width,
            num_inference_steps=1,
            timesteps=[199],
            guidance_scale=0.0,
            generator=torch.Generator(device="cpu").manual_seed(args.seed),
        ).images[0]
    torch.cuda.synchronize(device)
    inference_seconds = time.perf_counter() - infer_started
    peak_allocated = torch.cuda.max_memory_allocated(device) / 1024**3
    peak_reserved = torch.cuda.max_memory_reserved(device) / 1024**3

    output_image = args.output / "repaired.png"
    result.save(output_image)
    receipt = {
        "schema": SCHEMA,
        "model": args.model,
        "modelPurpose": "single-step novel-view artifact repair",
        "modelSourceCommit": "c76edc595586e16732c91ddee82f3a6d83a8a9cc",
        "placement": placement,
        "input": {"path": str(args.input.resolve()), "sha256": sha256(args.input)},
        "reference": {"path": str(args.reference.resolve()), "sha256": sha256(args.reference)},
        "target": {"path": str(target_path.resolve()), "sha256": sha256(target_path)},
        "output": {"path": str(output_image.resolve()), "sha256": sha256(output_image)},
        "resolution": {"width": args.width, "height": args.height},
        "timingSeconds": {"load": load_seconds, "inference": inference_seconds},
        "cuda": {
            "device": torch.cuda.get_device_name(device),
            "physicalVramGiB": total_vram,
            "peakAllocatedGiB": peak_allocated,
            "peakReservedGiB": peak_reserved,
            "policyLimitGiB": args.max_vram_gib,
        },
        "before": image_metrics(degraded, target),
        "after": image_metrics(result, target),
        "provenance": "generated-visual-only",
        "finiteGeometry": False,
        "collisionValidated": False,
        "passedMemoryGate": peak_reserved <= args.max_vram_gib,
    }
    receipt["improvedPsnrDb"] = receipt["after"]["psnrDb"] - receipt["before"]["psnrDb"]
    receipt_path = args.output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["passedMemoryGate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
