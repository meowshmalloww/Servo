#!/usr/bin/env python3
"""Fetch Servo's pinned, licensed OpenX Volvo EX30 runtime asset."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


RELEASE_URL = (
    "https://github.com/vevalabs/openx-assets/releases/download/20250821/"
    "openx-assets.zip"
)
ARCHIVE_SHA256 = "0aea8934133a25cb70002084fd87745a628d91240699c372408bfc604e687846"
ASSET_MEMBER = "model3d/m1_volvo_ex30_2024/m1_volvo_ex30_2024.glb"
ASSET_SHA256 = "6c9a190919432a379671c4a72fce7b9d575560b74de612b2d220f09328e9db4d"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="servo-openx-vehicle-") as directory:
        archive = Path(directory) / "openx-assets.zip"
        urllib.request.urlretrieve(RELEASE_URL, archive)
        if sha256(archive) != ARCHIVE_SHA256:
            raise RuntimeError("OpenX release archive SHA-256 mismatch")
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open(ASSET_MEMBER) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)
    if sha256(output) != ASSET_SHA256:
        output.unlink(missing_ok=True)
        raise RuntimeError("OpenX Volvo EX30 GLB SHA-256 mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "src" / "ui" / "assets" / "vehicles" / "OpenXVolvoEX30.glb",
    )
    args = parser.parse_args()
    if args.output.exists() and sha256(args.output) == ASSET_SHA256:
        print(f"Verified existing asset: {args.output}")
        return 0
    fetch(args.output)
    print(f"Fetched verified asset: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
