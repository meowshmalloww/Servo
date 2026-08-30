"""Build and qualify a real COLMAP sparse model for ClimateNeRF."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def build(images: Path, cameras_json: Path, output: Path,
          minimum_registration_fraction: float = 0.75,
          minimum_points: int = 5_000) -> dict:
    import pycolmap

    images = images.resolve()
    cameras_json = cameras_json.resolve()
    output = output.resolve()
    cameras = json.loads(cameras_json.read_text(encoding="utf-8")).get("cameras", [])
    names = [str(camera.get("image", "")).replace("\\", "/") for camera in cameras]
    if not names or any(not name for name in names):
        raise RuntimeError("registered camera image names are missing")
    missing = [name for name in names if not (images / name).is_file()]
    if missing:
        raise RuntimeError(f"{len(missing)} registered source images are missing")

    output.mkdir(parents=True, exist_ok=True)
    database = output / "database.db"
    mapped = output / "mapped"
    mapped.mkdir(exist_ok=True)
    if not database.exists():
        extraction = pycolmap.FeatureExtractionOptions()
        extraction.sift.max_num_features = 8192
        extraction.max_image_size = 1600
        extraction.num_threads = 4
        reader = pycolmap.ImageReaderOptions()
        reader.camera_model = "SIMPLE_RADIAL"
        pycolmap.extract_features(database, images, image_names=names,
                                  camera_mode=pycolmap.CameraMode.SINGLE,
                                  reader_options=reader,
                                  extraction_options=extraction,
                                  device=pycolmap.Device.auto)
    pairing = pycolmap.SequentialPairingOptions()
    pairing.overlap = 3
    pairing.loop_detection = False
    matching = pycolmap.FeatureMatchingOptions()
    matching.num_threads = 4
    pycolmap.match_sequential(database, matching_options=matching, pairing_options=pairing,
                              device=pycolmap.Device.auto)

    reconstructions = pycolmap.incremental_mapping(database, images, mapped)
    if not reconstructions:
        raise RuntimeError("COLMAP recovered no connected sparse model")
    reconstruction = max(reconstructions.values(),
                         key=lambda value: (value.num_reg_images(), value.num_points3D()))
    sparse = output / "sparse" / "0"
    sparse.mkdir(parents=True, exist_ok=True)
    reconstruction.write_binary(sparse)
    registered = reconstruction.num_reg_images()
    points = reconstruction.num_points3D()
    fraction = registered / len(names)
    accepted = fraction >= minimum_registration_fraction and points >= minimum_points
    files = {name: _sha256(sparse / name)
             for name in ("cameras.bin", "images.bin", "points3D.bin")}
    receipt = {
        "schema_name": "servo.climatenerf-colmap-qualification/v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pycolmap_version": pycolmap.__version__,
        "input_camera_count": len(names),
        "registered_image_count": registered,
        "registration_fraction": fraction,
        "point3D_count": points,
        "minimum_registration_fraction": minimum_registration_fraction,
        "minimum_point3D_count": minimum_points,
        "accepted": accepted,
        "sparse_files": files,
        "camera_manifest_sha256": _sha256(cameras_json),
        "limitations": [
            "COLMAP geometry is independent of the T5 Gaussian appearance field.",
            "Metric scale remains unavailable until an explicit physical anchor is supplied.",
        ],
    }
    (output / "qualification.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not accepted:
        raise RuntimeError(
            f"COLMAP qualification rejected: {registered}/{len(names)} images, {points} points")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--cameras", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--minimum-registration-fraction", type=float, default=0.75)
    parser.add_argument("--minimum-points", type=int, default=5_000)
    args = parser.parse_args()
    try:
        receipt = build(args.images, args.cameras, args.output,
                        args.minimum_registration_fraction, args.minimum_points)
    except Exception as error:
        print(json.dumps({"schema_name": "servo.climatenerf-colmap-error/v1",
                          "error": str(error)}))
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
