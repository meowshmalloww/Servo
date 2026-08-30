"""Fail-closed Servo Gaussian-world to calibrated Climate dataset adapter."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .schemas import validate_dataset
from .source_receipt import canonical_json, create_source_receipt, sha256_file


class DatasetError(RuntimeError):
    """The source world cannot safely produce a Climate dataset."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetError(f"Unable to read {path}: {error}") from error
    if not isinstance(value, dict):
        raise DatasetError(f"{path} must contain an object")
    return value


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    os.replace(temporary, path)


def _verified_world(manifest: dict[str, Any]) -> bool:
    quality = manifest.get("quality", {})
    explicitly_accepted = quality.get("tier") in {"accepted", "verified", "production"}
    measured_visual_route = (
        quality.get("decision") == "visual-route-pass"
        and float(quality.get("psnrMean", 0.0)) >= 20.0
        and float(quality.get("ssimMean", 0.0)) >= 0.70
        and float(quality.get("validationPassFraction", 0.0)) >= 0.75
    )
    return (explicitly_accepted or measured_visual_route) and \
        quality.get("metricsState") not in {"audited-rejected", "failed", "invalid"}


def inspect_world(world_root: Path) -> dict[str, Any]:
    manifest_path = world_root / "world.json"
    cameras_path = world_root / "cameras.json"
    manifest = _read_object(manifest_path)
    cameras_doc = _read_object(cameras_path)
    cameras = cameras_doc.get("cameras")
    errors: list[str] = []
    if manifest.get("schema") != "servo.gaussian-world/v1":
        errors.append("world schema is not servo.gaussian-world/v1")
    if not _verified_world(manifest):
        errors.append("world quality gate is not accepted/verified")
    if manifest.get("evidence", {}).get("usesColmap") is not True:
        errors.append("world has no verified COLMAP sparse reconstruction")
    sparse_relative = manifest.get("artifacts", {}).get("colmapSparse", "sparse/0")
    sparse_root = (world_root / sparse_relative).resolve()
    try:
        sparse_root.relative_to(world_root.resolve())
    except ValueError:
        errors.append("COLMAP sparse artifact escapes the world bundle")
    else:
        missing_sparse = [name for name in ("cameras.bin", "images.bin", "points3D.bin")
                          if not (sparse_root / name).is_file()]
        if missing_sparse:
            errors.append("verified COLMAP sparse files are missing: "
                          + ", ".join(missing_sparse))
    if not isinstance(cameras, list) or not cameras:
        errors.append("registered cameras are missing")
    else:
        for index, camera in enumerate(cameras):
            calibration = camera.get("calibration")
            pose = camera.get("cameraToWorldNormalized")
            if not (isinstance(calibration, list) and len(calibration) == 3 and
                    all(isinstance(row, list) and len(row) == 3 for row in calibration)):
                errors.append(f"camera {index} has malformed intrinsics")
            if not (isinstance(pose, list) and len(pose) == 4 and
                    all(isinstance(row, list) and len(row) == 4 for row in pose)):
                errors.append(f"camera {index} has malformed pose")
    expected = manifest.get("hashes", {})
    for name, digest in expected.items():
        path = world_root / name
        if not path.is_file() and name == "world.ply":
            path = world_root / manifest.get("artifacts", {}).get("ply", "world.ply")
        if not path.is_file() or sha256_file(path) != digest:
            errors.append(f"world artifact hash mismatch: {name}")
    return {"manifest": manifest, "cameras": cameras or [], "errors": errors,
            "sparse_root": sparse_root}


def prepare_dataset(world_root: Path, output_root: Path, climate_source: Path,
                    source_images_root: Path, colmap_sparse: Path | None = None,
                    colmap_qualification: Path | None = None) -> dict[str, Any]:
    world_root, output_root = world_root.resolve(), output_root.resolve()
    audit = inspect_world(world_root)
    if colmap_sparse is not None or colmap_qualification is not None:
        if colmap_sparse is None or colmap_qualification is None:
            raise DatasetError("COLMAP sparse override and qualification must be supplied together")
        sparse = colmap_sparse.resolve()
        qualification = _read_object(colmap_qualification.resolve())
        if qualification.get("schema_name") != "servo.climatenerf-colmap-qualification/v1" \
                or qualification.get("accepted") is not True:
            raise DatasetError("external COLMAP sparse qualification is not accepted")
        if qualification.get("camera_manifest_sha256") != sha256_file(world_root / "cameras.json"):
            raise DatasetError("COLMAP qualification does not match the T5 camera manifest")
        expected_sparse = qualification.get("sparse_files", {})
        for name in ("cameras.bin", "images.bin", "points3D.bin"):
            path = sparse / name
            if not path.is_file() or sha256_file(path) != expected_sparse.get(name):
                raise DatasetError(f"qualified COLMAP sparse hash mismatch: {name}")
        audit["sparse_root"] = sparse
        audit["errors"] = [error for error in audit["errors"]
                           if error != "world has no verified COLMAP sparse reconstruction"
                           and not error.startswith("verified COLMAP sparse files are missing:")]
    if audit["errors"]:
        raise DatasetError("Climate dataset preparation failed closed: " + "; ".join(audit["errors"]))
    cameras = audit["cameras"]
    missing = [camera["image"] for camera in cameras
               if not (source_images_root / camera["image"]).is_file()]
    if missing:
        raise DatasetError(f"{len(missing)} registered source images are missing")
    output_root.mkdir(parents=True, exist_ok=False)
    image_root = output_root / "images"
    generated: list[dict[str, str]] = []
    source_receipt: dict[str, str] = {}
    for camera in cameras:
        relative = Path(camera["image"])
        source = source_images_root / relative
        destination = image_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
            method = "hard-link"
        except OSError:
            shutil.copy2(source, destination)
            method = "copy"
        digest = sha256_file(source)
        source_receipt[relative.as_posix()] = digest
        generated.append({"path": destination.relative_to(output_root).as_posix(),
                           "sha256": digest, "method": method})
    sparse_output = output_root / "sparse" / "0"
    sparse_output.mkdir(parents=True, exist_ok=False)
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        source = audit["sparse_root"] / name
        destination = sparse_output / name
        shutil.copy2(source, destination)
        generated.append({"path": destination.relative_to(output_root).as_posix(),
                          "sha256": sha256_file(destination), "method": "copy"})
    camera_export = {"schema_name": "servo.climate-cameras/v1", "cameras": cameras,
                     "conversion": {"source": "servo-camera-to-world-normalized",
                                    "target": "climatenerf-opengl-camera-to-world",
                                    "matrix": [[1, 0, 0, 0], [0, -1, 0, 0],
                                               [0, 0, -1, 0], [0, 0, 0, 1]]}}
    _atomic_json(output_root / "cameras.json", camera_export)
    camera_hash = sha256_file(output_root / "cameras.json")
    indices = list(range(len(cameras)))
    validation = indices[::10]
    test = indices[5::10]
    train = [i for i in indices if i not in set(validation + test)]
    world_ply = world_root / audit["manifest"]["artifacts"]["ply"]
    manifest = {
        "schema_name": "servo.climate-dataset/v1",
        "dataset_id": audit["manifest"]["worldId"] + "-climate-v1",
        "base_world_id": audit["manifest"]["worldId"],
        "base_world_sha256": sha256_file(world_ply),
        "source_image_receipt": {"files": source_receipt,
                                 "identity": "sha256:" + hashlib.sha256(canonical_json(source_receipt)).hexdigest()},
        "camera_receipt": camera_hash,
        "coordinate_conversion": camera_export["conversion"],
        "scale_status": "metric" if audit["manifest"].get("usage", {}).get("metricScale") else "relative",
        "semantic_producer": None, "depth_producer": audit["manifest"].get("evidence", {}).get("depthPrior"),
        "static_mask_producer": None,
        "train_frames": train, "validation_frames": validation, "test_frames": test,
        "hidden_validation_frames": [], "generated_files": generated,
        "producer_version": "servo-climate-adapter/0.1.0",
        "source_tree_receipt": create_source_receipt(climate_source),
        "warnings": ["Relative scene units; metric weather controls are disabled."],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    validate_dataset(manifest)
    _atomic_json(output_root / "dataset.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world-root", required=True, type=Path)
    parser.add_argument("--source-images", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--climate-source", required=True, type=Path)
    parser.add_argument("--colmap-sparse", type=Path)
    parser.add_argument("--colmap-qualification", type=Path)
    args = parser.parse_args()
    try:
        manifest = prepare_dataset(args.world_root, args.output, args.climate_source,
                                   args.source_images, args.colmap_sparse,
                                   args.colmap_qualification)
    except DatasetError as error:
        print(json.dumps({"schema_name": "servo.climate-dataset-error/v1", "error": str(error)}))
        return 2
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
