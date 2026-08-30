"""Content-addressed receipt for an unversioned ClimateNeRF source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


RELEVANT_ROOT_FILES = {
    ".gitmodules", "LICENSE", "README.md", "requirements.txt", "opt.py",
    "train.py", "losses.py", "render.py", "render_panorama.py", "simulate.py",
    "simulate_wave.py", "make_snow.py", "stylize.py", "extract_mesh.py",
    "colmap_read_model.py", "utils.py",
}
RELEVANT_DIRECTORIES = {
    "models", "datasets", "utility", "configs", "scripts", "benchmarking",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def relevant_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root)
        if relative.as_posix() in RELEVANT_ROOT_FILES or relative.parts[0] in RELEVANT_DIRECTORIES:
            yield path


def create_source_receipt(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"ClimateNeRF source directory does not exist: {root}")
    files = {
        path.relative_to(root).as_posix(): {
            "sha256": sha256_file(path), "size_bytes": path.stat().st_size,
        }
        for path in relevant_files(root)
    }
    if not files:
        raise ValueError("No relevant ClimateNeRF source files were found.")
    return {
        "schema_name": "servo.climate-source-receipt/v1",
        "identity": "sha256:" + hashlib.sha256(canonical_json(files)).hexdigest(),
        "source_root": str(root),
        "git_metadata_present": (root / ".git").exists(),
        "file_count": len(files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = create_source_receipt(args.source)
    data = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data, encoding="utf-8", newline="\n")
    else:
        print(data, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
