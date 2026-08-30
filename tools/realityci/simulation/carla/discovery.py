"""Discover and validate an external packaged CARLA 0.9.16 runtime."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import secrets
import socket
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from ...hashing import canonical_json_bytes, sha256_digest, sha256_file
from . import SUPPORTED_CARLA_VERSION

INTEGRATION_VERSION = "servo-carla/v1"
SERVO_ROOT = Path(__file__).resolve().parents[4]
COMMON_ROOTS = (
    SERVO_ROOT / "runtime" / "carla" / "CARLA_0.9.16",
    Path("C:/CARLA_0.9.16"),
    Path("D:/CARLA_0.9.16"),
    Path("C:/CARLA"),
    Path("D:/CARLA"),
)


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    ready: bool
    expected_version: str
    root: str | None
    executable: str | None
    executable_sha256: str | None
    python_api_path: str | None
    python_api_sha256: str | None
    client_version: str | None
    server_version: str | None
    agents_available: bool
    rpc_port_available: bool
    maps: tuple[str, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    integration_version: str = INTEGRATION_VERSION

    def payload(self) -> dict:
        return asdict(self)


def port_available(port: int, host: str = "127.0.0.1") -> bool:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def port_block_available(first_port: int, count: int = 3, host: str = "127.0.0.1") -> bool:
    """Check the complete socket family CARLA will bind.

    Setting CARLA's RPC port also binds streaming at +1 and the multi-GPU
    router at +2. Checking only the first port can crash Unreal with WSAEACCES
    or WSAEADDRINUSE during startup.
    """
    if count <= 0 or first_port < 1 or first_port + count - 1 > 65535:
        return False
    sockets: list[socket.socket] = []
    try:
        for port in range(first_port, first_port + count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        for sock in sockets:
            sock.close()


def find_free_port(host: str = "127.0.0.1", block_size: int = 3) -> int:
    """Return the base of a verified contiguous CARLA port block."""
    generator = secrets.SystemRandom()
    for _ in range(2048):
        candidate = generator.randrange(20000, 48000 - block_size)
        if port_block_available(candidate, block_size, host):
            return candidate
    raise RuntimeError(f"unable to reserve a contiguous block of {block_size} TCP ports")


def candidate_roots(explicit: str | None = None, persisted: str | None = None) -> tuple[Path, ...]:
    values: list[Path] = []
    for value in (explicit, os.environ.get("SERVO_CARLA_ROOT"), persisted):
        if value:
            values.append(Path(value))
    values.extend(COMMON_ROOTS)
    unique: list[Path] = []
    keys: set[str] = set()
    for value in values:
        key = os.path.normcase(str(value.expanduser().absolute()))
        if key not in keys:
            keys.add(key)
            unique.append(value)
    return tuple(unique)


def _python_candidates(root: Path) -> tuple[Path, ...]:
    python_api = root / "PythonAPI"
    result: list[Path] = []
    direct = python_api / "carla"
    # CARLA 0.9.16's Windows package currently bundles a CPython 3.12 wheel.
    # Servo runs its locked workers on Python 3.11, so setup may provision the
    # matching official PyPI wheel into this runtime-local directory. Keep the
    # API beside CARLA rather than changing Servo's primary Python version.
    managed = direct / f"py{sys.version_info.major}{sys.version_info.minor}"
    if (managed / "carla" / "__init__.py").is_file():
        result.append(managed)
    if direct.is_dir() and (direct / "__init__.py").exists():
        result.append(python_api)
    dist = direct / "dist"
    if dist.is_dir():
        result.extend(sorted((*dist.glob("carla-*.whl"), *dist.glob("carla-*.egg"))))
    result.extend(sorted(python_api.glob("carla-*.whl")))
    return tuple(dict.fromkeys(path.resolve() for path in result))


def _python_identity(candidates: tuple[Path, ...]) -> str | None:
    if not candidates:
        return None
    payload: list[dict] = []
    for candidate in candidates:
        if candidate.is_file():
            payload.append({"path": candidate.name, "sha256": sha256_file(str(candidate))})
        else:
            files = sorted(
                path for path in candidate.rglob("*")
                if path.is_file() and path.suffix.lower() in {".py", ".pyd"}
            )
            payload.append(
                {
                    "path": candidate.name,
                    "files": [
                        {
                            "name": path.relative_to(candidate).as_posix(),
                            "sha256": sha256_file(str(path)),
                        }
                        for path in files[:2048]
                    ],
                }
            )
    return sha256_digest(canonical_json_bytes(payload))


@contextmanager
def carla_import_path(path: Path) -> Iterator[None]:
    """Expose CARLA's API path without unloading its native extension.

    ``carla.libcarla`` owns native Boost/Python state. Removing it from
    ``sys.modules`` while a Client, World, or Actor is still alive can abort
    the interpreter on a later import. CARLA workers therefore pin the first
    selected API for their complete process lifetime.
    """
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
    yield


def import_carla(path: Path):
    with carla_import_path(path):
        module = importlib.import_module("carla")
        if not hasattr(module, "Client"):
            raise ImportError("CARLA Python API does not export carla.Client")
        version = getattr(module, "__version__", None)
        if not version:
            try:
                probe = module.Client("127.0.0.1", 1)
                version_getter = getattr(probe, "get_client_version", None)
                version = version_getter() if version_getter else None
            except Exception:
                version = None
        return module, str(version) if version else None


def _version_from_name(candidates: tuple[Path, ...]) -> str | None:
    for path in candidates:
        for token in path.name.replace("_", "-").split("-"):
            if token.startswith("0.9."):
                return token.split("+")[0]
    return None


def discover_runtime(carla_root: str | None = None, *, persisted_root: str | None = None, rpc_port: int = 2000, import_api: bool = True) -> DiscoveryResult:
    roots = candidate_roots(carla_root, persisted_root)
    root = next((path.resolve() for path in roots if path.is_dir()), None)
    if root is None:
        return DiscoveryResult(
            status="runtime-missing", ready=False, expected_version=SUPPORTED_CARLA_VERSION,
            root=None, executable=None, executable_sha256=None, python_api_path=None,
            python_api_sha256=None, client_version=None, server_version=None,
            agents_available=False, rpc_port_available=port_available(rpc_port), maps=(),
            errors=("Packaged CARLA 0.9.16 was not found. Set SERVO_CARLA_ROOT or register its extracted directory.",), warnings=(),
        )
    executable = root / "CarlaUE4.exe"
    python_api = root / "PythonAPI"
    candidates = _python_candidates(root)
    errors: list[str] = []
    warnings: list[str] = []
    if not executable.is_file():
        errors.append(f"missing packaged server executable: {executable}")
    if not python_api.is_dir():
        errors.append(f"missing PythonAPI directory: {python_api}")
    if not candidates:
        errors.append("missing compatible CARLA wheel, egg, or package directory under PythonAPI/carla")
    client_version = _version_from_name(candidates)
    selected_python = candidates[0] if candidates else None
    if import_api and selected_python:
        try:
            _, imported_version = import_carla(selected_python)
            client_version = imported_version or client_version
        except Exception as exc:
            errors.append(f"CARLA Python API import failed: {exc}")
    if client_version and client_version != SUPPORTED_CARLA_VERSION:
        errors.append(
            f"CARLA client version mismatch: detected {client_version}, expected {SUPPORTED_CARLA_VERSION}. "
            "Register the packaged CARLA 0.9.16 release."
        )
    if not client_version and candidates:
        errors.append("CARLA client version could not be verified; expected 0.9.16")
    agents_available = (python_api / "carla" / "agents" / "navigation" / "behavior_agent.py").is_file()
    if not agents_available:
        warnings.append("CARLA BehaviorAgent modules were not found; oracle reference driving is unavailable")
    maps_root = root / "CarlaUE4" / "Content" / "Carla" / "Maps"
    maps = tuple(sorted(path.stem for path in maps_root.rglob("*.umap"))) if maps_root.is_dir() else ()
    available = port_available(rpc_port)
    if not available:
        warnings.append(f"RPC port {rpc_port} is already in use; ownership must be verified before reuse")
    ready = not errors
    return DiscoveryResult(
        status="ready" if ready else "invalid-runtime", ready=ready,
        expected_version=SUPPORTED_CARLA_VERSION, root=str(root),
        executable=str(executable) if executable.is_file() else None,
        executable_sha256=sha256_file(str(executable)) if executable.is_file() else None,
        python_api_path=str(selected_python) if selected_python else None,
        python_api_sha256=_python_identity(candidates), client_version=client_version,
        server_version=None, agents_available=agents_available, rpc_port_available=available,
        maps=maps, errors=tuple(errors), warnings=tuple(warnings),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carla-root")
    parser.add_argument("--rpc-port", type=int, default=2000)
    parser.add_argument("--no-import", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = discover_runtime(args.carla_root, rpc_port=args.rpc_port, import_api=not args.no_import)
        print(json.dumps(result.payload(), sort_keys=True, separators=(",", ":")))
        return 0 if result.ready else 2
    except Exception as exc:
        print(json.dumps({"status": "error", "ready": False, "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
