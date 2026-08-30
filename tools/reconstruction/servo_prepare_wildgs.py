#!/usr/bin/env python3
"""Prepare a non-destructive WildGS-SLAM comparison dataset and configs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


SCHEMA = "servo.external-wildgs-comparison/v1"
WILDGS_COMMIT = "be187eabbe6862cef3cfe87031ee2e64ad8c4cec"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def load_camera_contract(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cameras = payload.get("cameras")
    if payload.get("schema") != "servo.gaussian-cameras/v1" or not cameras:
        raise RuntimeError("The Servo camera contract is missing or malformed.")
    first = cameras[0]
    width = int(first["width"])
    height = int(first["height"])
    calibration = first["calibration"]
    fx, _, cx = (float(value) for value in calibration[0])
    _, fy, cy = (float(value) for value in calibration[1])
    for camera in cameras:
        if int(camera["width"]) != width or int(camera["height"]) != height:
            raise RuntimeError("WildGS comparison requires one constant camera size.")
        if camera["calibration"] != calibration:
            raise RuntimeError("WildGS comparison requires one constant calibration.")
    return cameras, {
        "width": width,
        "height": height,
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
    }


def link_or_copy(source: Path, target: Path) -> str:
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        shutil.copy2(source, target)
        return "copy"


def yaml_path(path: Path) -> str:
    return path.resolve().as_posix()


def write_config(
    *,
    path: Path,
    wildgs_root: Path,
    dataset_root: Path,
    output_root: Path,
    scene: str,
    camera: dict[str, Any],
    output_width: int,
    output_height: int,
) -> None:
    content = f"""inherit_from: {yaml_path(wildgs_root / 'configs' / 'wildgs_slam.yaml')}
scene: {scene}
dataset: 'wild_slam_iphone'
stride: 1
max_frames: -1
setup_seed: 42
gui: False
fast_mode: False

data:
  input_folder: {yaml_path(dataset_root)}
  output: {yaml_path(output_root)}

cam:
  H: {camera['height']}
  W: {camera['width']}
  H_out: {output_height}
  W_out: {output_width}
  fx: {camera['fx']:.12g}
  fy: {camera['fy']:.12g}
  cx: {camera['cx']:.12g}
  cy: {camera['cy']:.12g}
  H_edge: 0
  W_edge: 0
  distortion: [0.0, 0.0, 0.0, 0.0, 0.0]

mapping:
  full_resolution: False
  model_params:
    sh_degree: 0
  uncertainty_params:
    uncer_depth_mult: 0.0
"""
    path.write_text(content, encoding="utf-8", newline="\n")


def prepare(
    *,
    cameras_json: Path,
    servo_data_root: Path,
    wildgs_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite WildGS comparison: {output_root}")
    if not (wildgs_root / "run.py").is_file():
        raise RuntimeError(f"WildGS-SLAM source is missing: {wildgs_root}")
    cameras, camera = load_camera_contract(cameras_json)
    rgb = output_root / "dataset" / "rgb"
    rgb.mkdir(parents=True)
    methods: set[str] = set()
    sources: list[str] = []
    for index, record in enumerate(cameras):
        source = servo_data_root / "images" / str(record["image"])
        if not source.is_file():
            raise RuntimeError(f"Source frame is missing: {source}")
        target = rgb / f"frame_{index:05d}.png"
        methods.add(link_or_copy(source, target))
        sources.append(str(source.resolve()))
    configs = output_root / "configs"
    configs.mkdir()
    safe_config = configs / "yosemite-wildgs-360x640.yaml"
    high_config = configs / "yosemite-wildgs-537x955.yaml"
    write_config(
        path=safe_config,
        wildgs_root=wildgs_root,
        dataset_root=output_root / "dataset",
        output_root=output_root / "runs" / "360x640",
        scene="yosemite_servo_observed_373_safe",
        camera=camera,
        output_width=640,
        output_height=360,
    )
    write_config(
        path=high_config,
        wildgs_root=wildgs_root,
        dataset_root=output_root / "dataset",
        output_root=output_root / "runs" / "537x955",
        scene="yosemite_servo_observed_373_high",
        camera=camera,
        output_width=955,
        output_height=537,
    )
    receipt = {
        "schema": SCHEMA,
        "wildgsCommit": WILDGS_COMMIT,
        "wildgsRoot": str(wildgs_root.resolve()),
        "camerasSha256": sha256_file(cameras_json),
        "frameCount": len(cameras),
        "sourceWidth": camera["width"],
        "sourceHeight": camera["height"],
        "sourceFrames": sources,
        "materialization": sorted(methods),
        "configs": [str(safe_config.resolve()), str(high_config.resolve())],
        "usesColmapPoses": False,
        "usesColmapIntrinsicsAsCalibrationOnly": True,
        "publishable": False,
        "claimLimit": (
            "External comparison only. WildGS estimates poses; the carried Servo "
            "intrinsics are calibration, not pose supervision."
        ),
    }
    (output_root / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras-json", type=Path, required=True)
    parser.add_argument("--servo-data-root", type=Path, required=True)
    parser.add_argument("--wildgs-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(
        cameras_json=args.cameras_json,
        servo_data_root=args.servo_data_root,
        wildgs_root=args.wildgs_root,
        output_root=args.output_root,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
