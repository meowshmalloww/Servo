#!/usr/bin/env python3
"""Durable native media-to-Gaussian reconstruction worker for Servo.

The worker is deliberately UI-independent. It consumes a versioned job manifest,
emits versioned JSON Lines events, checkpoints every committed stage, and only
publishes an artifact bundle after the sparse reconstruction and Gaussian PLY
pass validation.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import queue
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence


WORKER_VERSION = "0.6.0"
PIPELINE_REVISION = "native-colmap-servo-fidelity-gs-r6"
REPRESENTATION_TYPE = "servo-fidelity-3dgs-v1"
CHECKPOINT_BYTES_PER_GAUSSIAN = 768
PLY_BYTES_PER_GAUSSIAN = 256
ATOMIC_CHECKPOINT_EQUIVALENTS = 4
ATOMIC_PLY_EQUIVALENTS = 3
SELECTED_FRAME_STORAGE_FLOOR = 2 * 1024**3
JOB_SCHEMA = "servo.reconstruction-job/v1"
EVENT_SCHEMA = "servo.reconstruction-event/v1"
RECEIPT_SCHEMA = "servo.reconstruction-receipt/v1"
WORLD_SCHEMA = "servo.gaussian-world/v1"
STAGES = ("hash", "extract", "pose", "train", "validate", "publish")
WINDOWS_CREATE_SUSPENDED = 0x00000004


class WorkerError(RuntimeError):
    """A deterministic, user-actionable reconstruction failure."""

    def __init__(self, code: str, message: str, details: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class Cancelled(WorkerError):
    def __init__(self, message: str = "Reconstruction was cancelled.") -> None:
        super().__init__("cancelled", message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json(value) + b"\n")


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise WorkerError("invalid_json", f"Unable to read {path.name}.", str(error)) from error
    if not isinstance(value, dict):
        raise WorkerError("invalid_json", f"{path.name} must contain a JSON object.")
    return value


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024.0 or unit == "PiB":
            precision = 0 if unit == "B" else (2 if size < 10 else 1)
            return f"{size:.{precision}f} {unit}"
        size /= 1024.0
    return f"{value} B"


class EventSink:
    def __init__(self, job_id: str | None = None, event_path: Path | None = None) -> None:
        self.job_id = job_id
        self.event_path = event_path
        self.sequence = 0

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        self.sequence += 1
        event = {
            "schema": EVENT_SCHEMA,
            "workerVersion": WORKER_VERSION,
            "sequence": self.sequence,
            "timestamp": utc_now(),
            "event": event_type,
        }
        if self.job_id:
            event["jobId"] = self.job_id
        event.update(fields)
        line = canonical_json(event).decode("utf-8")
        print(line, flush=True)
        if self.event_path is not None:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return event


@dataclasses.dataclass(frozen=True)
class Profile:
    name: str
    label: str
    max_dimension: int
    sample_hz: float
    min_interval_seconds: float
    max_interval_seconds: float
    motion_threshold: float
    data_factor: int
    sh_degree: int
    max_steps: int
    checkpoint_every: int
    min_registered_ratio: float
    min_registered_images: int
    max_reprojection_error: float
    min_median_track_length: float
    max_camera_rotation_step_degrees: float
    max_camera_speed_ratio: float
    expected_vram_gib: float
    disk_multiplier: float
    rasterization_mode: str
    eps2d: float
    absgrad: bool
    grow_grad2d: float
    coarse_factor: int
    coarse_steps: int
    final_fit_steps: int
    target_gaussians: int
    max_gaussians: int
    appearance_compensation: bool
    appearance_learning_rate: float
    appearance_regularization: float


PROFILES: dict[str, Profile] = {
    "balanced-12gb": Profile(
        name="balanced-12gb",
        label="Servo Balanced / 12 GB",
        max_dimension=1920,
        sample_hz=10.0,
        min_interval_seconds=0.08,
        max_interval_seconds=0.35,
        motion_threshold=0.005,
        data_factor=1,
        sh_degree=3,
        max_steps=30_000,
        checkpoint_every=1_000,
        min_registered_ratio=0.90,
        min_registered_images=20,
        max_reprojection_error=1.5,
        min_median_track_length=6.0,
        max_camera_rotation_step_degrees=12.0,
        max_camera_speed_ratio=6.0,
        expected_vram_gib=10.5,
        disk_multiplier=5.0,
        rasterization_mode="antialiased",
        eps2d=0.3,
        absgrad=True,
        grow_grad2d=0.0008,
        coarse_factor=2,
        coarse_steps=3_000,
        final_fit_steps=3_000,
        target_gaussians=2_000_000,
        max_gaussians=4_000_000,
        appearance_compensation=True,
        appearance_learning_rate=0.001,
        appearance_regularization=0.0001,
    ),
    "fidelity-12gb": Profile(
        name="fidelity-12gb",
        label="Servo Fidelity / 12 GB",
        max_dimension=2560,
        sample_hz=10.0,
        min_interval_seconds=0.08,
        max_interval_seconds=0.30,
        motion_threshold=0.0035,
        data_factor=1,
        sh_degree=3,
        max_steps=40_000,
        checkpoint_every=1_000,
        min_registered_ratio=0.92,
        min_registered_images=24,
        max_reprojection_error=1.25,
        min_median_track_length=8.0,
        max_camera_rotation_step_degrees=10.0,
        max_camera_speed_ratio=5.0,
        expected_vram_gib=11.0,
        disk_multiplier=7.0,
        rasterization_mode="antialiased",
        eps2d=0.3,
        absgrad=True,
        grow_grad2d=0.0008,
        coarse_factor=2,
        coarse_steps=4_000,
        final_fit_steps=4_000,
        target_gaussians=2_500_000,
        max_gaussians=5_000_000,
        appearance_compensation=True,
        appearance_learning_rate=0.001,
        appearance_regularization=0.0001,
    ),
    "recovery-12gb": Profile(
        name="recovery-12gb",
        label="Recovery / difficult capture",
        max_dimension=1600,
        sample_hz=10.0,
        min_interval_seconds=0.08,
        max_interval_seconds=0.40,
        motion_threshold=0.004,
        data_factor=2,
        sh_degree=3,
        max_steps=30_000,
        checkpoint_every=1_000,
        min_registered_ratio=0.80,
        min_registered_images=20,
        max_reprojection_error=2.0,
        min_median_track_length=4.0,
        max_camera_rotation_step_degrees=15.0,
        max_camera_speed_ratio=8.0,
        expected_vram_gib=8.0,
        disk_multiplier=5.5,
        rasterization_mode="antialiased",
        eps2d=0.3,
        absgrad=False,
        grow_grad2d=0.0002,
        coarse_factor=2,
        coarse_steps=4_000,
        final_fit_steps=3_000,
        target_gaussians=1_500_000,
        max_gaussians=3_000_000,
        appearance_compensation=True,
        appearance_learning_rate=0.001,
        appearance_regularization=0.0001,
    ),
}


def estimated_derived_bytes(source_bytes: int, profile: Profile) -> int:
    """Conservative peak workspace, including atomic files and resume state."""
    gaussian_workspace = profile.max_gaussians * (
        CHECKPOINT_BYTES_PER_GAUSSIAN * ATOMIC_CHECKPOINT_EQUIVALENTS
        + PLY_BYTES_PER_GAUSSIAN * ATOMIC_PLY_EQUIVALENTS
    )
    selected_frames = max(
        SELECTED_FRAME_STORAGE_FLOOR,
        round(max(source_bytes, 0) * profile.disk_multiplier),
    )
    return max(4 * 1024**3, gaussian_workspace + selected_frames)


def local_runtime_root() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "Servo" / "reconstruction"
    return Path.home() / ".servo" / "reconstruction"


def find_colmap() -> Path | None:
    explicit = os.environ.get("SERVO_COLMAP")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for name in ("colmap", "colmap.exe", "COLMAP.bat"):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    toolchain = local_runtime_root() / "toolchain" / "colmap-4.1.1"
    candidates.extend(
        [
            toolchain / "COLMAP.bat",
            toolchain / "bin" / "colmap.exe",
            toolchain / "colmap.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    if toolchain.is_dir():
        for pattern in ("COLMAP.bat", "colmap.exe"):
            found = next(toolchain.rglob(pattern), None)
            if found is not None:
                return found.resolve()
    return None


def find_vocab_tree() -> Path | None:
    explicit = os.environ.get("SERVO_COLMAP_VOCAB_TREE")
    candidates = [Path(explicit)] if explicit else []
    candidates.append(
        local_runtime_root()
        / "toolchain"
        / "colmap-vocab"
        / "vocab_tree_faiss_flickr100K_words32K.bin"
    )
    return next((path.resolve() for path in candidates if path.is_file()), None)


def find_cuda_home() -> Path | None:
    explicit = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
    candidates = [Path(explicit)] if explicit else []
    candidates.extend(
        [
            Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"),
            Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8.1"),
        ]
    )
    for candidate in candidates:
        if (candidate / "bin" / "nvcc.exe").is_file():
            return candidate.resolve()
    return None


def find_vcvars64() -> Path | None:
    explicit = os.environ.get("SERVO_VCVARS64")
    if explicit and Path(explicit).is_file():
        return Path(explicit).resolve()
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if vswhere.is_file():
        result = subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        installation = result.stdout.strip().splitlines()
        if installation:
            candidate = Path(installation[-1]) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
            if candidate.is_file():
                return candidate.resolve()
    return None


def compiler_environment() -> dict[str, str]:
    environment = dict(os.environ)

    def set_value(key: str, value: str) -> None:
        # A regular dict is case-sensitive even though the Windows process
        # environment is not.  Avoid emitting both ``Path`` and ``PATH``: the
        # value selected by CreateProcess is otherwise order-dependent.
        for existing in list(environment):
            if existing.casefold() == key.casefold():
                del environment[existing]
        environment[key] = value

    cuda_home = find_cuda_home()
    if cuda_home:
        current_path = next(
            (value for key, value in environment.items() if key.casefold() == "path"),
            "",
        )
        set_value("CUDA_HOME", str(cuda_home))
        set_value("CUDA_PATH", str(cuda_home))
        set_value("PATH", str(cuda_home / "bin") + os.pathsep + current_path)
        if not any(key.casefold() == "torch_cuda_arch_list" for key in environment):
            set_value("TORCH_CUDA_ARCH_LIST", "8.9")
        if not any(key.casefold() == "max_jobs" for key in environment):
            set_value("MAX_JOBS", "2")
        if os.name == "nt":
            # gsplat 1.5.3's official Windows source build passes these same
            # nvcc options.  Its JIT backend omits them, so inject them through
            # nvcc's documented environment hook without modifying the
            # installed package or the user's global environment.
            existing_flags = next(
                (
                    value
                    for key, value in environment.items()
                    if key.casefold() == "nvcc_prepend_flags"
                ),
                "",
            )
            required_flags = ["-DWIN32_LEAN_AND_MEAN", "-allow-unsupported-compiler"]
            merged_flags = existing_flags.split()
            merged_flags.extend(flag for flag in required_flags if flag not in merged_flags)
            set_value("NVCC_PREPEND_FLAGS", " ".join(merged_flags))
    vcvars = find_vcvars64()
    if os.name == "nt" and vcvars:
        # Passing the command as an argv element makes Python escape the
        # embedded quotes before cmd.exe sees them.  A complete, trusted
        # command line is required for a batch path containing spaces.
        command = f'cmd.exe /d /s /c ""{vcvars}" >nul && set"'
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=environment,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key:
                    set_value(key, value)
            # PyTorch's setuptools integration intentionally refuses to
            # reactivate an already prepared MSVC environment unless this is
            # declared.  Servo owns this child environment, so that is the
            # correct and deterministic mode.
            set_value("DISTUTILS_USE_SDK", "1")
    return environment


def executable_command(program: Path | str, arguments: Sequence[str]) -> list[str]:
    path = Path(program)
    if os.name == "nt" and path.suffix.lower() in {".bat", ".cmd"}:
        command = "call " + subprocess.list2cmdline([str(path), *map(str, arguments)])
        return ["cmd.exe", "/d", "/s", "/c", command]
    return [str(program), *map(str, arguments)]


def version_output(program: Path | str, arguments: Sequence[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            executable_command(program, arguments),
            capture_output=True,
            text=True,
            timeout=30,
            env=compiler_environment(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output[:4000]


def dependency(name: str, ready: bool, version: str = "", path: str = "", detail: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "ready": ready,
        "version": version,
        "path": path,
        "detail": detail,
    }


def process_identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information | synchronize,
            False,
            pid,
        )
        if not handle:
            # Access denied means a protected process still exists. Treat it
            # as live so a lock is never removed based on insufficient access.
            return "access-denied" if ctypes.get_last_error() == 5 else None
        try:
            if kernel32.WaitForSingleObject(handle, 0) != wait_timeout:
                return None
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return "alive"
            ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            return f"windows-filetime:{ticks}"
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return f"pid:{pid}"


def process_is_alive(pid: int, expected_identity: str | None = None) -> bool:
    identity = process_identity(pid)
    if identity is None:
        return False
    if expected_identity and identity not in {expected_identity, "access-denied", "alive"}:
        return False
    return True


@contextlib.contextmanager
def exclusive_process_lock(path: Path, code: str, message: str) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as error:
            stale = False
            try:
                value = read_json(path)
                stale = not process_is_alive(
                    int(value.get("pid", -1)),
                    str(value.get("processIdentity") or "") or None,
                )
            except (WorkerError, TypeError, ValueError):
                stale = True
            if stale:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                continue
            raise WorkerError(code, message) from error
    else:
        raise WorkerError(code, message)
    try:
        os.write(
            descriptor,
            canonical_json(
                {
                    "pid": os.getpid(),
                    "processIdentity": process_identity(os.getpid()),
                    "startedAt": utc_now(),
                }
            ),
        )
        os.close(descriptor)
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def collect_preflight(verify_kernel: bool = False) -> dict[str, Any]:
    dependencies: list[dict[str, Any]] = []
    lock_path = Path(__file__).with_name("worker-lock.json")
    lock_ready = False
    lock_detail = "worker-lock.json is missing."
    if lock_path.is_file():
        try:
            worker_lock = read_json(lock_path)
            lock_ready = (
                worker_lock.get("schema") == "servo.reconstruction-worker-lock/v1"
                and worker_lock.get("workerVersion") == WORKER_VERSION
                and worker_lock.get("trainerVersion") == "0.6.0"
                and worker_lock.get("pipelineRevision") == PIPELINE_REVISION
                and worker_lock.get("representationType") == REPRESENTATION_TYPE
                and worker_lock.get("rasterizationMode") == "antialiased"
            )
            lock_detail = (
                "Pinned worker, trainer, and pipeline revisions match."
                if lock_ready
                else "Worker lock revisions do not match the running code."
            )
        except WorkerError as error:
            lock_detail = str(error)
    dependencies.append(
        dependency(
            "Servo worker lock",
            lock_ready,
            WORKER_VERSION if lock_ready else "",
            str(lock_path),
            lock_detail,
        )
    )
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    dependencies.append(dependency("FFmpeg", bool(ffmpeg), path=ffmpeg or "", detail="Streaming decode and media validation"))
    dependencies.append(dependency("ffprobe", bool(ffprobe), path=ffprobe or "", detail="Media metadata"))

    colmap = find_colmap()
    colmap_ready = False
    colmap_version = ""
    colmap_detail = "Official COLMAP 4.1.1 Windows CUDA build is required."
    if colmap:
        ok, output = version_output(colmap, ["-h"])
        match = re.search(r"COLMAP\s+([0-9][^\s]*)", output, re.IGNORECASE)
        colmap_version = match.group(1) if match else "detected"
        colmap_ready = ok and colmap_version == "4.1.1"
        colmap_detail = "Pinned 4.1.1" if colmap_ready else "Detected COLMAP does not match pinned 4.1.1."
    dependencies.append(dependency("COLMAP", colmap_ready, colmap_version, str(colmap or ""), colmap_detail))
    vocab_tree = find_vocab_tree()
    dependencies.append(
        dependency(
            "COLMAP retrieval vocabulary",
            vocab_tree is not None,
            "Flickr100K / 32K words" if vocab_tree else "",
            str(vocab_tree or ""),
            "Required for scalable matching across large or mixed source collections.",
        )
    )

    cuda_home = find_cuda_home()
    dependencies.append(
        dependency(
            "CUDA Toolkit",
            cuda_home is not None,
            "12.8" if cuda_home else "",
            str(cuda_home or ""),
            "Must match the installed PyTorch cu128 build.",
        )
    )
    vcvars = find_vcvars64()
    dependencies.append(
        dependency(
            "MSVC x64",
            vcvars is not None,
            path=str(vcvars or ""),
            detail="Required for gsplat's native CUDA extension.",
        )
    )

    python_modules: dict[str, tuple[bool, str, str]] = {}
    for module_name in ("torch", "gsplat", "pycolmap", "cv2", "numpy", "PIL", "scipy"):
        try:
            module = __import__(module_name)
            version = str(getattr(module, "__version__", "installed"))
            python_modules[module_name] = (True, version, str(getattr(module, "__file__", "")))
        except Exception as error:  # import errors must be surfaced in preflight
            python_modules[module_name] = (False, "", str(error))

    torch_ready = python_modules["torch"][0]
    cuda_ready = False
    gpu_name = ""
    gpu_total_bytes = 0
    gpu_free_bytes = 0
    if torch_ready:
        try:
            import torch

            torch_ready = torch.__version__ == "2.11.0+cu128"
            cuda_ready = bool(
                torch_ready
                and torch.version.cuda == "12.8"
                and torch.cuda.is_available()
            )
            if cuda_ready:
                gpu_name = str(torch.cuda.get_device_name(0))
                gpu_free_bytes, gpu_total_bytes = map(int, torch.cuda.mem_get_info(0))
        except Exception:
            cuda_ready = False
    dependencies.append(
        dependency(
            "PyTorch CUDA",
            cuda_ready,
            python_modules["torch"][1],
            python_modules["torch"][2] if python_modules["torch"][0] else "",
            (
                f"{gpu_name}; CUDA 12.8; {format_bytes(gpu_total_bytes)} total"
                if cuda_ready
                else "Exact PyTorch 2.11.0+cu128 with CUDA 12.8 is required."
            ),
        )
    )
    for display, module_name, required_prefix in (
        ("gsplat", "gsplat", "1.5.3"),
        ("PyCOLMAP", "pycolmap", "4.1.1"),
        ("OpenCV", "cv2", ""),
        ("NumPy", "numpy", ""),
        ("Pillow", "PIL", ""),
        ("SciPy", "scipy", ""),
    ):
        installed, version, module_path = python_modules[module_name]
        matches = installed and (not required_prefix or version == required_prefix)
        dependencies.append(
            dependency(
                display,
                matches,
                version,
                module_path if installed else "",
                "Pinned version" if matches and required_prefix else (module_path if not installed else "Installed"),
            )
        )

    kernel_ready: bool | None = None
    kernel_detail = "Kernel test not requested."
    if verify_kernel and all(item["ready"] for item in dependencies):
        helper = Path(__file__).with_name("servo_train.py")
        fingerprint = sha256_bytes(
            canonical_json(
                {
                    "python": sys.executable,
                    "modules": python_modules,
                    "gpu": gpu_name,
                    "gpuTotalBytes": gpu_total_bytes,
                    "cuda": str(cuda_home or ""),
                    "trainerSha256": sha256_file(helper),
                }
            )
        )
        cache_path = local_runtime_root() / "kernel-check.json"
        cache: dict[str, Any] = {}
        if cache_path.is_file():
            with contextlib.suppress(WorkerError):
                cache = read_json(cache_path)
        if (
            cache.get("schema") == "servo.gsplat-kernel-check/v1"
            and cache.get("fingerprint") == fingerprint
            and cache.get("ready") is True
        ):
            kernel_ready = True
            kernel_detail = "Verified compiled gsplat CUDA kernel (cached environment fingerprint)."
        else:
            try:
                result = subprocess.run(
                    [sys.executable, str(helper), "kernel-check"],
                    capture_output=True,
                    text=True,
                    timeout=20 * 60,
                    env=compiler_environment(),
                    check=False,
                )
                kernel_ready = result.returncode == 0
                kernel_detail = (result.stdout + "\n" + result.stderr).strip()[-4000:]
            except (OSError, subprocess.SubprocessError) as error:
                kernel_ready = False
                kernel_detail = str(error)
            atomic_write_json(
                cache_path,
                {
                    "schema": "servo.gsplat-kernel-check/v1",
                    "fingerprint": fingerprint,
                    "ready": bool(kernel_ready),
                    "checkedAt": utc_now(),
                    "detail": kernel_detail,
                },
            )
        dependencies.append(dependency("gsplat CUDA kernel", bool(kernel_ready), detail=kernel_detail))

    ready = all(item["ready"] for item in dependencies)
    disk = shutil.disk_usage(local_runtime_root().anchor or str(local_runtime_root()))
    return {
        "ready": ready,
        "workerVersion": WORKER_VERSION,
        "pipelineRevision": PIPELINE_REVISION,
        "python": sys.executable,
        "platform": platform.platform(),
        "runtimeRoot": str(local_runtime_root()),
        "freeBytes": disk.free,
        "freeText": format_bytes(disk.free),
        "gpuFreeBytes": gpu_free_bytes,
        "gpuTotalBytes": gpu_total_bytes,
        "dependencies": dependencies,
        "profiles": [dataclasses.asdict(profile) for profile in PROFILES.values()],
    }


def require_job(job_path: Path) -> tuple[dict[str, Any], Profile]:
    job = read_json(job_path)
    if job.get("schema") != JOB_SCHEMA:
        raise WorkerError("unsupported_job_schema", f"Expected job schema {JOB_SCHEMA}.")
    pipeline_revision = job.get("pipelineRevision")
    if pipeline_revision is not None and pipeline_revision != PIPELINE_REVISION:
        raise WorkerError(
            "pipeline_revision_mismatch",
            f"This job requires pipeline {pipeline_revision}; this worker provides {PIPELINE_REVISION}.",
        )
    job_id = job.get("jobId")
    if not isinstance(job_id, str) or not job_id:
        raise WorkerError("invalid_job", "jobId is required.")
    sources = job.get("sources")
    if not isinstance(sources, list) or not sources:
        raise WorkerError("no_sources", "At least one ready image or video source is required.")
    profile_name = job.get("profile", "balanced-12gb")
    profile = PROFILES.get(str(profile_name))
    if profile is None:
        raise WorkerError("invalid_profile", f"Unknown reconstruction profile: {profile_name}")
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise WorkerError("invalid_source", f"Source {index + 1} has no local path.")
        path = Path(source["path"])
        if not path.is_file():
            raise WorkerError("missing_source", f"Source is missing: {path}")
        if source.get("kind") not in {"image", "video"}:
            raise WorkerError("invalid_source", f"Source is not a ready image or video: {path.name}")
    return job, profile


class JobContext:
    def __init__(self, job_path: Path, job: dict[str, Any], profile: Profile) -> None:
        self.job_path = job_path.resolve()
        self.job = job
        self.profile = profile
        self.job_id = str(job["jobId"])
        self.root = self.job_path.parent
        self.receipts = self.root / "receipts"
        self.cancel_path = self.root / "cancel.request"
        self.events = EventSink(self.job_id, self.root / "events.jsonl")
        self.lock_path = self.root / "worker.lock"
        self.configuration_hash = sha256_bytes(
            canonical_json(
                {
                    "job": job,
                    "profile": dataclasses.asdict(profile),
                    "workerVersion": WORKER_VERSION,
                    "pipelineRevision": PIPELINE_REVISION,
                }
            )
        )

    def check_cancel(self) -> None:
        if self.cancel_path.exists():
            raise Cancelled()

    def require_free_space(self, required_bytes: int, operation: str) -> None:
        free_bytes = shutil.disk_usage(self.root).free
        if free_bytes < required_bytes:
            raise WorkerError(
                "disk_full",
                f"{operation} needs at least {format_bytes(required_bytes)} free; "
                f"only {format_bytes(free_bytes)} is available.",
            )

    def stage_path(self, stage: str) -> Path:
        return self.root / "stages" / stage

    def receipt_path(self, stage: str) -> Path:
        return self.receipts / f"{stage}.json"

    def stage_input_hash(self, stage: str) -> str:
        index = STAGES.index(stage)
        previous_hashes = []
        for previous in STAGES[:index]:
            receipt = read_json(self.receipt_path(previous))
            previous_hashes.append(receipt.get("receiptHash", ""))
        value = {
            "stage": stage,
            "job": self.job,
            "configurationHash": self.configuration_hash,
            "previous": previous_hashes,
        }
        return sha256_bytes(canonical_json(value))

    def valid_receipt(self, stage: str) -> dict[str, Any] | None:
        path = self.receipt_path(stage)
        if not path.is_file():
            return None
        try:
            receipt = read_json(path)
            if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("stage") != stage:
                return None
            stored_hash = receipt.pop("receiptHash", None)
            calculated = sha256_bytes(canonical_json(receipt))
            receipt["receiptHash"] = stored_hash
            if stored_hash != calculated or receipt.get("inputHash") != self.stage_input_hash(stage):
                return None
            for artifact in receipt.get("artifacts", []):
                artifact_path = self.root / artifact["path"]
                if not artifact_path.is_file() or sha256_file(artifact_path) != artifact["sha256"]:
                    return None
            if stage == "hash":
                manifest = read_json(self.stage_path("hash") / "sources.json")
                records = manifest.get("sources")
                if not isinstance(records, list) or len(records) != len(self.job["sources"]):
                    return None
                for source, record in zip(self.job["sources"], records, strict=True):
                    source_path = Path(source["path"]).resolve()
                    if (
                        str(source_path) != str(record.get("path", ""))
                        or not source_path.is_file()
                        or source_path.stat().st_size != int(record.get("bytes", -1))
                        or sha256_file(source_path) != record.get("sha256")
                    ):
                        return None
            return receipt
        except (WorkerError, KeyError, OSError, TypeError):
            return None

    def commit_receipt(self, stage: str, metrics: dict[str, Any], artifact_paths: Iterable[Path]) -> dict[str, Any]:
        artifacts = []
        for artifact_path in artifact_paths:
            resolved = artifact_path.resolve()
            artifacts.append(
                {
                    "path": resolved.relative_to(self.root.resolve()).as_posix(),
                    "bytes": resolved.stat().st_size,
                    "sha256": sha256_file(resolved),
                }
            )
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "jobId": self.job_id,
            "stage": stage,
            "completedAt": utc_now(),
            "workerVersion": WORKER_VERSION,
            "inputHash": self.stage_input_hash(stage),
            "metrics": metrics,
            "artifacts": artifacts,
        }
        receipt["receiptHash"] = sha256_bytes(canonical_json(receipt))
        atomic_write_json(self.receipt_path(stage), receipt)
        return receipt

    def clear_uncommitted_stage(self, stage: str) -> None:
        if stage == "train":
            return
        if stage == "publish":
            publish_root = self.stage_path("publish")
            if publish_root.is_dir():
                for attempt in publish_root.glob(".attempt-*"):
                    if attempt.is_dir() and attempt.parent.resolve() == publish_root.resolve():
                        shutil.rmtree(attempt)
            return
        target = self.stage_path(stage).resolve()
        stage_root = (self.root / "stages").resolve()
        if target.parent != stage_root or target == stage_root:
            raise WorkerError("unsafe_stage_path", f"Refusing to clear unsafe stage path: {target}")
        if target.exists():
            shutil.rmtree(target)

    @contextlib.contextmanager
    def acquire_lock(self) -> Iterator[None]:
        with exclusive_process_lock(
            self.lock_path,
            "job_locked",
            "This reconstruction job already has an active worker.",
        ):
            yield


def full_hash_stage(context: JobContext) -> tuple[dict[str, Any], list[Path]]:
    output = context.stage_path("hash")
    output.mkdir(parents=True, exist_ok=True)
    total_bytes = sum(Path(source["path"]).stat().st_size for source in context.job["sources"])
    completed_bytes = 0
    source_records = []
    for index, source in enumerate(context.job["sources"]):
        context.check_cancel()
        source_path = Path(source["path"])
        digest = hashlib.sha256()
        size = source_path.stat().st_size
        with source_path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                context.check_cancel()
                digest.update(chunk)
                completed_bytes += len(chunk)
                context.events.emit(
                    "stage_progress",
                    stage="hash",
                    completed=completed_bytes,
                    total=total_bytes,
                    unit="bytes",
                    source=source_path.name,
                )
        source_records.append(
            {
                **source,
                "sourceId": f"s{index:03d}",
                "path": str(source_path.resolve()),
                "bytes": size,
                "sha256": "sha256:" + digest.hexdigest(),
            }
        )
    manifest = output / "sources.json"
    atomic_write_json(
        manifest,
        {
            "schema": "servo.reconstruction-sources/v1",
            "jobId": context.job_id,
            "hashedAt": utc_now(),
            "sources": source_records,
        },
    )
    return {"sourceCount": len(source_records), "sourceBytes": total_bytes}, [manifest]


def normalized_image(frame: Any, max_dimension: int) -> Any:
    import cv2

    height, width = frame.shape[:2]
    largest = max(height, width)
    if largest <= max_dimension:
        return frame
    scale = max_dimension / float(largest)
    return cv2.resize(
        frame,
        (max(2, round(width * scale)), max(2, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def frame_features(frame: Any) -> tuple[float, float, Any, Any, float]:
    import cv2

    height, width = frame.shape[:2]
    scale = min(1.0, 720.0 / max(height, width))
    if scale < 1.0:
        small = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    focus = float(laplacian.var())
    # Global Laplacian variance is dominated by sharp foliage at the frame
    # edges even when the road/building evidence is motion-soft.  Use a robust
    # lower-center tile score for selection while retaining the global value
    # for diagnostics.
    region = laplacian[
        gray.shape[0] // 3 :,
        gray.shape[1] // 5 : 4 * gray.shape[1] // 5,
    ]
    tile_scores: list[float] = []
    for y_tile in range(2):
        for x_tile in range(2):
            y0 = y_tile * region.shape[0] // 2
            y1 = (y_tile + 1) * region.shape[0] // 2
            x0 = x_tile * region.shape[1] // 2
            x1 = (x_tile + 1) * region.shape[1] // 2
            tile_scores.append(float(region[y0:y1, x0:x1].var()))
    regional_focus = float(sorted(tile_scores)[1]) if tile_scores else focus
    orb = cv2.ORB_create(nfeatures=1800, fastThreshold=12)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    return (
        focus,
        regional_focus,
        keypoints or [],
        descriptors,
        math.hypot(small.shape[0], small.shape[1]),
    )


def overlap_motion(previous_keypoints: Any, previous_descriptors: Any, keypoints: Any, descriptors: Any, diagonal: float) -> tuple[float, float, int]:
    import cv2
    import numpy as np

    if previous_descriptors is None or descriptors is None:
        return 0.0, 0.0, 0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    pairs = matcher.knnMatch(previous_descriptors, descriptors, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance
    ]
    if len(good) < 12:
        return 0.0, 0.0, len(good)
    first_points = np.float32([previous_keypoints[match.queryIdx].pt for match in good])
    second_points = np.float32([keypoints[match.trainIdx].pt for match in good])
    displacement = np.linalg.norm(second_points - first_points, axis=1)
    movement = float(np.median(displacement) / max(diagonal, 1.0))
    _, mask = cv2.findFundamentalMat(
        first_points,
        second_points,
        cv2.FM_RANSAC,
        1.5,
        0.995,
    )
    overlap = float(mask.mean()) if mask is not None else 0.0
    return movement, overlap, len(good)


def write_selected_frame(path: Path, frame: Any) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.png")
    if not cv2.imwrite(
        str(temporary), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3]
    ):
        raise WorkerError("image_write_failed", f"Unable to write selected frame {path.name}.")
    os.replace(temporary, path)


def camera_group_for_source(source: dict[str, Any], source_index: int) -> str:
    override = str(source.get("cameraGroup") or "").strip()
    if override:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", override).strip(".-")[:64]
        if not safe:
            raise WorkerError("invalid_camera_group", "cameraGroup must contain a letter or number.")
        return f"{source['kind']}-manual-{safe}"
    if source["kind"] == "video":
        return f"video-{source_index:03d}"

    source_path = Path(source["path"])
    signature: dict[str, Any] = {
        "width": int(source.get("width", 0) or 0),
        "height": int(source.get("height", 0) or 0),
        "make": "",
        "model": "",
        "lens": "",
        "focalLength": "",
    }
    try:
        from PIL import Image, ImageOps

        with Image.open(source_path) as image:
            # OpenCV applies EXIF orientation while staging.  Hash the dimensions
            # after the same logical transform so portrait/landscape captures do
            # not get assigned to an incompatible shared COLMAP camera.
            signature["width"], signature["height"] = ImageOps.exif_transpose(image).size
            exif = image.getexif()
            signature["make"] = str(exif.get(271, "")).strip()
            signature["model"] = str(exif.get(272, "")).strip()
            signature["lens"] = str(exif.get(42036, "")).strip()
            signature["focalLength"] = str(exif.get(37386, "")).strip()
    except Exception:
        pass
    digest = sha256_bytes(canonical_json(signature)).split(":", 1)[1][:16]
    return f"photo-{digest}"


def probe_video_decode(source_path: Path, max_dimension: int) -> dict[str, Any]:
    environment = compiler_environment()
    search_path = environment.get("PATH")
    ffmpeg = shutil.which("ffmpeg", path=search_path)
    ffprobe = shutil.which("ffprobe", path=search_path)
    if ffmpeg is None or ffprobe is None:
        raise WorkerError(
            "ffmpeg_missing",
            "Lossless color-managed video extraction requires FFmpeg and ffprobe.",
        )
    stream_result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            (
                "stream=width,height,avg_frame_rate,color_space,color_transfer,"
                "color_primaries,color_range:stream_side_data=rotation"
            ),
            "-of",
            "json",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=environment,
        check=False,
    )
    if stream_result.returncode != 0:
        raise WorkerError(
            "video_probe_failed",
            f"ffprobe could not inspect {source_path.name}.",
            stream_result.stderr[-4000:],
        )
    try:
        stream_document = json.loads(stream_result.stdout)
        stream = stream_document["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise WorkerError(
            "video_probe_failed", f"{source_path.name} has no usable video stream."
        ) from error
    rotation = 0
    for side_data in stream.get("side_data_list", []):
        if isinstance(side_data, dict) and isinstance(
            side_data.get("rotation"), (int, float)
        ):
            rotation = int(side_data["rotation"])
            break
    if abs(rotation) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise WorkerError("video_probe_failed", "Video dimensions are invalid.")
    resize_scale = min(1.0, max_dimension / float(max(width, height)))
    output_width = max(2, int(round(width * resize_scale / 2.0) * 2))
    output_height = max(2, int(round(height * resize_scale / 2.0) * 2))

    timestamp_result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10 * 60,
        env=environment,
        check=False,
    )
    if timestamp_result.returncode != 0:
        raise WorkerError(
            "video_probe_failed",
            f"ffprobe could not read frame timestamps from {source_path.name}.",
            timestamp_result.stderr[-4000:],
        )
    timestamps: list[float] = []
    for line in timestamp_result.stdout.splitlines():
        field = line.split(",", 1)[0].strip()
        try:
            timestamp = float(field)
        except ValueError:
            continue
        if math.isfinite(timestamp):
            timestamps.append(timestamp)
    if not timestamps:
        raise WorkerError(
            "video_probe_failed", f"{source_path.name} has no finite presentation timestamps."
        )

    color_primaries = str(stream.get("color_primaries") or "unknown").lower()
    color_transfer = str(stream.get("color_transfer") or "unknown").lower()
    color_space = str(stream.get("color_space") or "unknown").lower()
    color_range = str(stream.get("color_range") or "unknown").lower()
    scale_filter = f"scale={output_width}:{output_height}:flags=lanczos"
    if color_transfer == "arib-std-b67":
        decode_filter = (
            "zscale=min=2020_ncl:tin=arib-std-b67:pin=2020:rin=limited:"
            "t=linear:npl=1000,format=gbrpf32le,"
            "tonemap=mobius:param=0.3:desat=0,"
            "zscale=tin=linear:t=iec61966-2-1:p=709:m=gbr:r=full,"
            f"{scale_filter},format=bgr24"
        )
        transform = "bt2020-hlg-limited-to-bt709-srgb-mobius-v1"
    elif color_transfer in {"smpte2084", "smpte-st-2084"}:
        raise WorkerError(
            "unsupported_hdr_transfer",
            "PQ HDR video needs a separately calibrated display transform; "
            "this build will not decode it implicitly.",
        )
    elif color_primaries.startswith("bt2020"):
        raise WorkerError(
            "unsupported_hdr_transfer",
            "BT.2020 video has unrecognized transfer metadata; implicit color "
            "conversion is disabled to protect reconstruction fidelity.",
        )
    else:
        decode_filter = f"{scale_filter},format=bgr24"
        transform = "ffmpeg-declared-sdr-to-bgr24-v1"
    version_result = subprocess.run(
        [ffmpeg, "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=environment,
        check=False,
    )
    return {
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "environment": environment,
        "timestamps": timestamps,
        "width": output_width,
        "height": output_height,
        "sourceWidth": int(stream["width"]),
        "sourceHeight": int(stream["height"]),
        "rotationDegrees": rotation,
        "colorPrimaries": color_primaries,
        "colorTransfer": color_transfer,
        "colorSpace": color_space,
        "colorRange": color_range,
        "filter": decode_filter,
        "displayTransform": transform,
        "ffmpegVersion": version_result.stdout.splitlines()[0]
        if version_result.stdout
        else "unknown",
    }


def extract_video(
    context: JobContext,
    source: dict[str, Any],
    source_index: int,
    camera_group: str,
    images: Path,
    start_index: int,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    import cv2
    import numpy as np

    source_path = Path(source["path"])
    decode = probe_video_decode(source_path, context.profile.max_dimension)
    timestamps = list(decode["timestamps"])
    width = int(decode["width"])
    height = int(decode["height"])
    frame_bytes = width * height * 3
    duration = max(0.0, timestamps[-1] - timestamps[0])
    command = [
        str(decode["ffmpeg"]),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        str(decode["filter"]),
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    creation_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | WINDOWS_CREATE_SUSPENDED
        if os.name == "nt"
        else 0
    )
    process = subprocess.Popen(
        command,
        cwd=str(context.root),
        env=decode["environment"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        creationflags=creation_flags,
    )
    windows_job = create_windows_kill_job(int(getattr(process, "_handle", 0)))
    if os.name == "nt" and (
        windows_job is None or not resume_windows_process_threads(process.pid)
    ):
        terminate_windows_job(windows_job)
        with contextlib.suppress(Exception):
            process.kill()
        close_windows_handle(windows_job)
        raise WorkerError(
            "process_guard_failed",
            "Unable to start FFmpeg inside the reconstruction process guard.",
        )
    stderr_recent: list[str] = []

    def read_stderr() -> None:
        if process.stderr is None:
            return
        for raw_line in iter(process.stderr.readline, b""):
            stderr_recent.append(raw_line.decode("utf-8", errors="replace").rstrip())
            del stderr_recent[:-40]

    stderr_reader = threading.Thread(
        target=read_stderr,
        name=f"servo-extract-{source_index}-stderr",
        daemon=True,
    )
    stderr_reader.start()

    def read_frame() -> bytes:
        assert process.stdout is not None
        result = bytearray()
        while len(result) < frame_bytes:
            chunk = process.stdout.read(frame_bytes - len(result))
            if not chunk:
                break
            result.extend(chunk)
        if result and len(result) != frame_bytes:
            raise WorkerError(
                "video_decode_failed",
                f"FFmpeg returned a partial frame for {source_path.name}.",
            )
        return bytes(result)

    sample_period = 1.0 / context.profile.sample_hz
    motion_threshold = context.profile.motion_threshold
    next_sample_time = timestamps[0]
    frame_index = 0
    last_decode_timestamp = -math.inf
    selected: list[dict[str, Any]] = []
    last_selected_time = -1e9
    last_keypoints = None
    last_descriptors = None
    blur_rejections = 0
    overlap_rejections = 0
    bridge_frames = 0
    try:
        while True:
            context.check_cancel()
            raw_frame = read_frame()
            if not raw_frame:
                break
            if frame_index >= len(timestamps):
                raise WorkerError(
                    "video_timestamp_mismatch",
                    f"FFmpeg decoded more frames than ffprobe indexed for {source_path.name}.",
                    "Servo requires a one-to-one decoded-frame/PTS mapping and will not "
                    "fabricate camera timestamps.",
                )
            timestamp = timestamps[frame_index]
            frame_index += 1
            if not math.isfinite(timestamp) or timestamp <= last_decode_timestamp:
                timestamp = last_decode_timestamp + sample_period
            last_decode_timestamp = timestamp
            if timestamp + 1e-6 < next_sample_time:
                continue
            next_sample_time = timestamp + sample_period
            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape(
                height, width, 3
            )
            (
                global_focus,
                regional_focus,
                keypoints,
                descriptors,
                feature_diagonal,
            ) = frame_features(frame)
            elapsed = timestamp - last_selected_time
            accept = not selected and regional_focus >= 30.0
            reason = "first"
            movement = 0.0
            overlap = 1.0
            matches = 0
            if selected:
                movement, overlap, matches = overlap_motion(
                    last_keypoints,
                    last_descriptors,
                    keypoints,
                    descriptors,
                    feature_diagonal,
                )
                sharp_enough = regional_focus >= 45.0
                has_overlap = overlap >= 0.25 and matches >= 48
                useful_motion = movement >= motion_threshold
                not_a_jump = movement <= 0.25
                bridge_candidate = (
                    elapsed >= context.profile.max_interval_seconds
                    and regional_focus >= 15.0
                    and overlap >= 0.12
                    and matches >= 32
                    and movement <= 0.40
                )
                accept = (
                    elapsed >= context.profile.min_interval_seconds
                    and (
                        (
                            sharp_enough
                            and has_overlap
                            and not_a_jump
                            and useful_motion
                        )
                        or bridge_candidate
                    )
                )
                if bridge_candidate and accept and not (
                    sharp_enough and has_overlap and not_a_jump and useful_motion
                ):
                    reason = "connectivity-bridge"
                    bridge_frames += 1
                elif not sharp_enough:
                    blur_rejections += 1
                    reason = "regional-blur"
                elif not has_overlap or not useful_motion:
                    overlap_rejections += 1
                    reason = "epipolar-overlap-or-motion"
                else:
                    reason = "motion"
                if elapsed > context.profile.max_interval_seconds * 3.0 and not accept:
                    raise WorkerError(
                        "video_connectivity_gap",
                        f"{source_path.name} loses reliable visual overlap for "
                        f"{elapsed:.2f} seconds near {timestamp:.2f}s.",
                        "Use a slower/sharper capture or add overlapping media; "
                        "Servo will not silently train across a camera-path hole.",
                    )
            if accept:
                output_name = f"{start_index + len(selected):08d}.png"
                output_path = images / camera_group / output_name
                write_selected_frame(output_path, frame)
                selected.append(
                    {
                        "image": output_path.relative_to(images).as_posix(),
                        "cameraGroup": camera_group,
                        "sourceId": f"s{source_index:03d}",
                        "source": str(source_path.resolve()),
                        "timestampSeconds": timestamp,
                        "focus": regional_focus,
                        "globalFocus": global_focus,
                        "movement": movement,
                        "overlap": overlap,
                        "matches": matches,
                        "selectionReason": reason,
                        "displayTransform": decode["displayTransform"],
                    }
                )
                last_selected_time = timestamp
                last_keypoints = keypoints
                last_descriptors = descriptors
                context.events.emit(
                    "stage_progress",
                    stage="extract",
                    completed=len(selected),
                    total=None,
                    unit="selected_frames",
                    source=source_path.name,
                    mediaTimeSeconds=timestamp,
                    mediaDurationSeconds=duration if duration > 0 else None,
                )
        return_code = process.wait(timeout=30)
        stderr_reader.join(timeout=2)
        if return_code != 0:
            raise WorkerError(
                "video_decode_failed",
                f"FFmpeg failed while decoding {source_path.name}.",
                "\n".join(stderr_recent[-20:]),
            )
        if frame_index != len(timestamps):
            raise WorkerError(
                "video_timestamp_mismatch",
                f"FFmpeg decoded {frame_index} frames but ffprobe indexed "
                f"{len(timestamps)} frames for {source_path.name}.",
                "The video may be truncated or corrupt; Servo will not assign "
                "camera poses to guessed timestamps.",
            )
    finally:
        if process.poll() is None:
            if not terminate_windows_job(windows_job):
                with contextlib.suppress(Exception):
                    process.terminate()
            with contextlib.suppress(Exception):
                process.wait(timeout=10)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        close_windows_handle(windows_job)
    if not selected:
        raise WorkerError("no_video_frames", f"No usable frames were decoded from {source_path.name}.")
    decode_manifest = {
        "sourceId": f"s{source_index:03d}",
        "sourceName": source_path.name,
        "decoder": "ffmpeg-rawvideo-stream-v1",
        "ffmpegVersion": decode["ffmpegVersion"],
        "sourceWidth": decode["sourceWidth"],
        "sourceHeight": decode["sourceHeight"],
        "outputWidth": width,
        "outputHeight": height,
        "rotationDegrees": decode["rotationDegrees"],
        "colorPrimaries": decode["colorPrimaries"],
        "colorTransfer": decode["colorTransfer"],
        "colorSpace": decode["colorSpace"],
        "colorRange": decode["colorRange"],
        "displayTransform": decode["displayTransform"],
        "filter": decode["filter"],
        "decodedFrames": frame_index,
        "selectedFrames": len(selected),
        "connectivityBridgeFrames": bridge_frames,
        "losslessFrameFormat": "png",
    }
    return selected, blur_rejections + overlap_rejections, decode_manifest


def stage_image(source_path: Path, output_path: Path, max_dimension: int) -> None:
    import cv2

    frame = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if frame is None:
        raise WorkerError("image_decode_failed", f"Unable to decode {source_path.name}.")
    frame = normalized_image(frame, max_dimension)
    write_selected_frame(output_path, frame)


def extract_stage(context: JobContext) -> tuple[dict[str, Any], list[Path]]:
    output = context.stage_path("extract")
    images = output / "images"
    images.mkdir(parents=True, exist_ok=True)
    selected: list[dict[str, Any]] = []
    rejected = 0
    video_decodes: list[dict[str, Any]] = []
    for source_index, source in enumerate(context.job["sources"]):
        context.check_cancel()
        source_path = Path(source["path"])
        camera_group = camera_group_for_source(source, source_index)
        if source["kind"] == "image":
            name = f"{len(selected):08d}.png"
            staged_path = images / camera_group / name
            stage_image(source_path, staged_path, context.profile.max_dimension)
            focus, regional_focus, _, _, _ = frame_features(
                __import__("cv2").imread(str(staged_path))
            )
            selected.append(
                {
                    "image": staged_path.relative_to(images).as_posix(),
                    "cameraGroup": camera_group,
                    "sourceId": f"s{source_index:03d}",
                    "source": str(source_path.resolve()),
                    "timestampSeconds": None,
                    "focus": regional_focus,
                    "globalFocus": focus,
                    "selectionReason": "source-image",
                }
            )
            context.events.emit(
                "stage_progress",
                stage="extract",
                completed=len(selected),
                total=len(context.job["sources"]),
                unit="selected_frames",
                source=source_path.name,
            )
        else:
            video_frames, video_rejected, video_decode = extract_video(
                context,
                source,
                source_index,
                camera_group,
                images,
                len(selected),
            )
            selected.extend(video_frames)
            rejected += video_rejected
            video_decodes.append(video_decode)
    if len(selected) < context.profile.min_registered_images:
        raise WorkerError(
            "insufficient_frames",
            f"Only {len(selected)} usable frames were selected; {context.profile.min_registered_images} are required.",
            "Capture more overlapping views with translation and less blur.",
        )
    manifest = output / "frames.json"
    atomic_write_json(
        manifest,
        {
            "schema": "servo.reconstruction-frames/v1",
            "jobId": context.job_id,
            "profile": context.profile.name,
            "selectedCount": len(selected),
            "rejectedCandidates": rejected,
            "videoDecodes": video_decodes,
            "frames": selected,
        },
    )
    artifacts = [manifest, *sorted(images.rglob("*.png"))]
    return {"selectedFrames": len(selected), "rejectedCandidates": rejected}, artifacts


def create_windows_kill_job(process_handle: int) -> int | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    configured = kernel32.SetInformationJobObject(
        handle, 9, ctypes.byref(information), ctypes.sizeof(information)
    )
    assigned = configured and kernel32.AssignProcessToJobObject(
        handle, wintypes.HANDLE(process_handle)
    )
    if not assigned:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def close_windows_handle(handle: int | None) -> None:
    if os.name == "nt" and handle:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(wintypes.HANDLE(handle))


def terminate_windows_job(handle: int | None) -> bool:
    if os.name != "nt" or not handle:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    return bool(kernel32.TerminateJobObject(wintypes.HANDLE(handle), 1))


def resume_windows_process_threads(process_id: int) -> bool:
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    class ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or int(snapshot) == invalid_handle:
        return False
    resumed = False
    try:
        entry = ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while has_entry:
            if int(entry.th32OwnerProcessID) == process_id:
                thread = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                if thread:
                    try:
                        resumed = kernel32.ResumeThread(thread) != 0xFFFFFFFF or resumed
                    finally:
                        kernel32.CloseHandle(thread)
            has_entry = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return resumed


def run_process(
    context: JobContext,
    stage: str,
    command: Sequence[str],
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    timeout: float | None = None,
) -> None:
    context.check_cancel()
    context.events.emit("command_started", stage=stage, command=list(command), cwd=str(cwd or context.root))
    creation_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | WINDOWS_CREATE_SUSPENDED
        if os.name == "nt"
        else 0
    )
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd or context.root),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creation_flags,
    )
    windows_job = create_windows_kill_job(int(getattr(process, "_handle", 0)))
    if os.name == "nt":
        if windows_job is None or not resume_windows_process_threads(process.pid):
            terminate_windows_job(windows_job)
            with contextlib.suppress(Exception):
                process.kill()
            close_windows_handle(windows_job)
            raise WorkerError(
                "process_guard_failed",
                "Unable to start the child process inside a Windows kill-on-close Job Object.",
            )
    started = time.monotonic()
    recent: list[str] = []
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        try:
            for output_line in process.stdout:
                lines.put(output_line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, name=f"servo-{stage}-output", daemon=True)
    reader.start()
    try:
        output_closed = False
        graceful_cancel_started: float | None = None
        while True:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if line is None:
                output_closed = True
                line = ""
            if line:
                clean = line.rstrip()
                recent.append(clean)
                recent = recent[-80:]
                try:
                    child_event = json.loads(clean)
                except json.JSONDecodeError:
                    context.events.emit("command_output", stage=stage, message=clean[-4000:])
                else:
                    if isinstance(child_event, dict) and child_event.get("event"):
                        forwarded = {key: value for key, value in child_event.items() if key not in {"schema", "workerVersion", "jobId", "sequence", "timestamp"}}
                        context.events.emit("worker_child_event", stage=stage, child=forwarded)
                    else:
                        context.events.emit("command_output", stage=stage, message=clean[-4000:])
            return_code = process.poll()
            if return_code is not None and output_closed:
                break
            if context.cancel_path.exists():
                if stage != "train":
                    raise Cancelled()
                if graceful_cancel_started is None:
                    graceful_cancel_started = time.monotonic()
                    context.events.emit(
                        "command_cancelling",
                        stage=stage,
                        message="Waiting for the trainer to commit a safe checkpoint.",
                    )
                elif time.monotonic() - graceful_cancel_started > 120:
                    raise Cancelled(
                        "The trainer did not stop within the checkpoint grace period."
                    )
            if timeout is not None and time.monotonic() - started > timeout:
                raise WorkerError("command_timeout", f"The {stage} command exceeded its time limit.")
        if return_code == 130 and context.cancel_path.exists():
            raise Cancelled()
        if return_code != 0:
            raise WorkerError(
                "command_failed",
                f"The {stage} command exited with code {return_code}.",
                "\n".join(recent[-30:]),
            )
    except (Cancelled, WorkerError):
        if process.poll() is None:
            if os.name == "nt":
                with contextlib.suppress(OSError):
                    process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                with contextlib.suppress(OSError):
                    process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                terminated_tree = terminate_windows_job(windows_job)
                if not terminated_tree:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        with contextlib.suppress(OSError, subprocess.SubprocessError):
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True,
                                timeout=15,
                                check=False,
                            )
                    else:
                        process.kill()
        raise
    finally:
        close_windows_handle(windows_job)


def run_colmap(context: JobContext, stage: str, arguments: Sequence[str]) -> None:
    colmap = find_colmap()
    if colmap is None:
        raise WorkerError("colmap_missing", "COLMAP 4.1.1 is not installed.")
    run_process(context, stage, executable_command(colmap, arguments), environment=compiler_environment())


def reconstruction_metrics(
    model_path: Path,
    selected_count: int,
    frame_timestamps: dict[str, float] | None = None,
) -> dict[str, Any]:
    import numpy as np
    import pycolmap

    reconstruction = pycolmap.Reconstruction(str(model_path))
    registered = int(reconstruction.num_reg_images())
    points = list(reconstruction.points3D.values())
    errors = [float(point.error) for point in points if math.isfinite(float(point.error))]
    track_lengths = [int(point.track.length()) for point in points]
    metrics = {
        "selectedImages": selected_count,
        "registeredImages": registered,
        "registeredRatio": registered / max(selected_count, 1),
        "points3D": int(reconstruction.num_points3D()),
        "meanReprojectionError": float(np.mean(errors)) if errors else None,
        "p95ReprojectionError": float(np.percentile(errors, 95)) if errors else None,
        "medianTrackLength": float(statistics.median(track_lengths)) if track_lengths else None,
        "cameraCount": int(reconstruction.num_cameras()),
    }
    if frame_timestamps:
        trajectory: list[tuple[float, Any, Any, Any]] = []
        for image in reconstruction.images.values():
            timestamp = frame_timestamps.get(image.name)
            if timestamp is None or not math.isfinite(timestamp):
                continue
            camera_to_world = np.asarray(
                image.cam_from_world().inverse().matrix(), dtype=np.float64
            )
            if camera_to_world.shape != (3, 4) or not np.isfinite(
                camera_to_world
            ).all():
                continue
            position = camera_to_world[:3, 3]
            forward = camera_to_world[:3, 2]
            up = -camera_to_world[:3, 1]
            forward /= max(float(np.linalg.norm(forward)), 1e-12)
            up /= max(float(np.linalg.norm(up)), 1e-12)
            trajectory.append((timestamp, position, forward, up))
        trajectory.sort(key=lambda value: value[0])
        if len(trajectory) >= 3:
            speeds: list[float] = []
            forward_steps: list[float] = []
            up_steps: list[float] = []

            def angle_degrees(left: Any, right: Any) -> float:
                cosine = float(np.clip(np.dot(left, right), -1.0, 1.0))
                return math.degrees(math.acos(cosine))

            for left, right in zip(trajectory, trajectory[1:]):
                elapsed = right[0] - left[0]
                if elapsed > 1e-6:
                    speeds.append(float(np.linalg.norm(right[1] - left[1]) / elapsed))
                forward_steps.append(angle_degrees(left[2], right[2]))
                up_steps.append(angle_degrees(left[3], right[3]))
            positive_speeds = [speed for speed in speeds if speed > 1e-9]
            median_speed = (
                float(statistics.median(positive_speeds))
                if positive_speeds
                else 0.0
            )
            metrics.update(
                {
                    "trajectoryImages": len(trajectory),
                    "cameraForwardStepP95Degrees": float(
                        np.percentile(forward_steps, 95)
                    ),
                    "cameraForwardStepMaxDegrees": max(forward_steps),
                    "cameraUpStepP95Degrees": float(np.percentile(up_steps, 95)),
                    "cameraUpStepMaxDegrees": max(up_steps),
                    "cameraSpeedMedian": median_speed,
                    "cameraSpeedP95Ratio": (
                        float(np.percentile(positive_speeds, 95)) / median_speed
                        if median_speed > 0.0
                        else None
                    ),
                    "cameraSpeedMaxRatio": (
                        max(positive_speeds) / median_speed
                        if median_speed > 0.0
                        else None
                    ),
                }
            )
    return metrics


def minimum_reliable_pose_points(candidate: dict[str, Any]) -> int:
    """Scale the sparse-evidence floor with the recovered camera count."""

    return max(1_000, int(candidate.get("registeredImages", 0)) * 20)


def pose_candidate_passes_gate(candidate: dict[str, Any], profile: Profile) -> bool:
    p95 = candidate.get("p95ReprojectionError")
    track_length = candidate.get("medianTrackLength")
    forward_step = candidate.get("cameraForwardStepMaxDegrees")
    up_step = candidate.get("cameraUpStepMaxDegrees")
    speed_ratio = candidate.get("cameraSpeedMaxRatio")
    return (
        candidate["registeredImages"] >= profile.min_registered_images
        and candidate["registeredRatio"] >= profile.min_registered_ratio
        and candidate["points3D"] >= minimum_reliable_pose_points(candidate)
        and p95 is not None
        and p95 <= profile.max_reprojection_error
        and track_length is not None
        and track_length >= profile.min_median_track_length
        and (
            forward_step is None
            or forward_step <= profile.max_camera_rotation_step_degrees
        )
        and (
            up_step is None
            or up_step <= profile.max_camera_rotation_step_degrees
        )
        and (
            speed_ratio is None or speed_ratio <= profile.max_camera_speed_ratio
        )
    )


def pose_candidate_quality_key(
    item: tuple[dict[str, Any], str, Path],
) -> tuple[Any, ...]:
    candidate = item[0]
    track_length = candidate.get("medianTrackLength")
    p95 = candidate.get("p95ReprojectionError")
    rotation = candidate.get("cameraForwardStepMaxDegrees")
    # Once every hard gate passes, spatial evidence coverage is more useful than
    # shaving a few hundredths of a pixel from an already-clean residual.  This
    # lets the exhaustive Fidelity refinement beat a smaller filtered model
    # without allowing a noisy or discontinuous reconstruction through.
    return (
        candidate["registeredRatio"],
        float(track_length) if track_length is not None else -math.inf,
        candidate["points3D"],
        -(float(p95) if p95 is not None else math.inf),
        -(float(rotation) if rotation is not None else 0.0),
    )


def select_pose_candidate(
    scored: Sequence[tuple[dict[str, Any], str, Path]],
    profile: Profile,
) -> tuple[dict[str, Any], str, Path] | None:
    ranked = sorted(scored, key=pose_candidate_quality_key, reverse=True)
    passing = [item for item in ranked if pose_candidate_passes_gate(item[0], profile)]
    return (passing or ranked)[0] if ranked else None


def pose_filter_min_track_length(profile: Profile) -> int:
    # A retained track should already contain enough independent observations
    # that the median of the filtered cloud can meet the profile-level gate.
    # This maps Recovery/Balanced/Fidelity to 3/4/5 observed views.
    return max(3, math.floor(profile.min_median_track_length / 2.0) + 1)


def filter_pose_candidate(
    context: JobContext,
    model: Path,
    output: Path,
    selected_count: int,
    frame_timestamps: dict[str, float],
    solver: str,
) -> tuple[dict[str, Any], str, Path]:
    raw_metrics = reconstruction_metrics(model, selected_count, frame_timestamps)
    output.mkdir(parents=True, exist_ok=True)
    minimum_track_length = pose_filter_min_track_length(context.profile)
    run_colmap(
        context,
        "pose",
        [
            "point_filtering",
            "--input_path", str(model),
            "--output_path", str(output),
            "--min_track_len", str(minimum_track_length),
            "--max_reproj_error", str(context.profile.max_reprojection_error),
            "--min_tri_angle", "1.5",
        ],
    )
    metrics = reconstruction_metrics(output, selected_count, frame_timestamps)
    metrics.update(
        {
            "confidenceFilter": {
                "minimumTrackLength": minimum_track_length,
                "maximumReprojectionError": context.profile.max_reprojection_error,
                "minimumTriangulationAngleDegrees": 1.5,
            },
            "preFilter": raw_metrics,
        }
    )
    return metrics, f"{solver}+confidence-filter", output


def fidelity_refine_pose_candidates(
    context: JobContext,
    output: Path,
    images: Path,
    database: Path,
    raw_scored: Sequence[tuple[dict[str, Any], str, Path]],
    selected_count: int,
    frame_timestamps: dict[str, float],
) -> list[tuple[dict[str, Any], str, Path]]:
    """Complete and clean a small Fidelity capture using all image pairs.

    COLMAP recommends exhaustive matching for collections of a few hundred
    images when reconstruction quality is the priority.  We retain a robust
    sequential/global seeds, rebuild the correspondence graph with guided
    exhaustive matching, retriangulate and globally refine each viable solver,
    and only then retain long, low-residual points for Gaussian initialization.
    """

    if context.profile.name != "fidelity-12gb" or selected_count > 500:
        return []
    if not raw_scored:
        return []

    def seed_key(item: tuple[dict[str, Any], str, Path]) -> tuple[Any, ...]:
        candidate = item[0]
        p95 = candidate.get("p95ReprojectionError")
        rotation = candidate.get("cameraForwardStepMaxDegrees")
        return (
            candidate["registeredRatio"],
            -(float(p95) if p95 is not None else math.inf),
            candidate["points3D"],
            float(candidate.get("medianTrackLength") or 0.0),
            -(float(rotation) if rotation is not None else 0.0),
        )

    ordered_seeds = sorted(raw_scored, key=seed_key, reverse=True)
    seeds: list[tuple[dict[str, Any], str, Path]] = []
    seen_solvers: set[str] = set()
    for item in ordered_seeds:
        candidate, solver, _model = item
        if solver in seen_solvers:
            continue
        if (
            candidate["registeredImages"] < context.profile.min_registered_images
            or candidate["registeredRatio"] < context.profile.min_registered_ratio
        ):
            continue
        seeds.append(item)
        seen_solvers.add(solver)
        if len(seeds) == 2:
            break
    if not seeds:
        seeds = ordered_seeds[:1]
    refinement_root = output / "fidelity-refinement"
    refinement_root.mkdir(parents=True, exist_ok=True)
    refinement_database = refinement_root / "database.db"
    context.require_free_space(
        database.stat().st_size * 2 + 2 * 1024**3,
        "Fidelity exhaustive camera refinement",
    )
    shutil.copy2(database, refinement_database)
    for table in ("matches", "two_view_geometries"):
        run_colmap(
            context,
            "pose",
            [
                "database_cleaner",
                "--type", table,
                "--database_path", str(refinement_database),
            ],
        )
    run_colmap(
        context,
        "pose",
        [
            "exhaustive_matcher",
            "--database_path", str(refinement_database),
            "--FeatureMatching.use_gpu", "1",
            "--FeatureMatching.guided_matching", "1",
            "--TwoViewGeometry.max_error", "3.0",
            "--ExhaustiveMatching.block_size", "25",
        ],
    )

    triangulation_error = max(2.5, context.profile.max_reprojection_error * 2.0)
    results: list[tuple[dict[str, Any], str, Path]] = []
    for index, (seed_metrics, seed_solver, seed_model) in enumerate(seeds):
        seed_root = refinement_root / f"seed-{index:02d}-{seed_solver}"
        triangulated = seed_root / "triangulated"
        refined = seed_root / "bundle-adjusted"
        triangulated.mkdir(parents=True, exist_ok=True)
        refined.mkdir(parents=True, exist_ok=True)
        try:
            run_colmap(
                context,
                "pose",
                [
                    "point_triangulator",
                    "--database_path", str(refinement_database),
                    "--image_path", str(images),
                    "--input_path", str(seed_model),
                    "--output_path", str(triangulated),
                    "--clear_points", "1",
                    "--refine_intrinsics", "1",
                    "--Mapper.tri_ignore_two_view_tracks", "0",
                    "--Mapper.filter_max_reproj_error", str(triangulation_error),
                    "--Mapper.tri_merge_max_reproj_error", str(triangulation_error),
                    "--Mapper.tri_complete_max_reproj_error", str(triangulation_error),
                ],
            )
            run_colmap(
                context,
                "pose",
                [
                    "bundle_adjuster",
                    "--input_path", str(triangulated),
                    "--output_path", str(refined),
                    "--BundleAdjustment.refine_focal_length", "1",
                    "--BundleAdjustment.refine_principal_point", "0",
                    "--BundleAdjustment.refine_extra_params", "1",
                    "--BundleAdjustmentCeres.max_num_iterations", "150",
                ],
            )
            result = filter_pose_candidate(
                context,
                refined,
                seed_root / "filtered",
                selected_count,
                frame_timestamps,
                f"{seed_solver}+exhaustive-guided",
            )
        except Cancelled:
            raise
        except WorkerError as error:
            context.events.emit(
                "pose_solver_failed",
                stage="pose",
                solver=f"{seed_solver}+exhaustive-guided",
                code=error.code,
                message=str(error),
                details=error.details,
            )
            continue
        result[0].update(
            {
                "fidelityRefinement": {
                    "matching": "exhaustive-guided",
                    "seedSolver": seed_solver,
                    "seedMetrics": seed_metrics,
                    "comparedSeedCount": len(seeds),
                    "maximumImages": 500,
                    "triangulationMaximumReprojectionError": triangulation_error,
                }
            }
        )
        results.append(result)
    return results


def static_pair_confidence(
    first_gray: Any,
    second_gray: Any,
    fundamental: Any,
) -> tuple[Any, Any]:
    """Estimate bidirectional static-scene confidence for one registered pair.

    Dense flow alone cannot distinguish camera parallax from object motion.  The
    recovered epipolar geometry supplies that distinction: a correspondence may
    move substantially and still be static when it remains on the correct
    epipolar line.  Forward/backward disagreement catches occlusion and unstable
    flow.  Values are uint8 weights (0, 96, or 255), not semantic labels.
    """
    import cv2
    import numpy as np

    if (
        first_gray.ndim != 2
        or second_gray.ndim != 2
        or first_gray.shape != second_gray.shape
    ):
        raise WorkerError(
            "static_mask_failed",
            "Adjacent video frames must have matching grayscale dimensions.",
        )
    matrix = np.asarray(fundamental, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise WorkerError(
            "static_mask_failed", "Recovered epipolar geometry is not finite."
        )
    norm = float(np.linalg.norm(matrix))
    if norm <= 1e-12:
        raise WorkerError(
            "static_mask_failed", "Recovered epipolar geometry is degenerate."
        )
    matrix /= norm

    forward_solver = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    backward_solver = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    forward_solver.setUseSpatialPropagation(True)
    backward_solver.setUseSpatialPropagation(True)
    forward = forward_solver.calc(first_gray, second_gray, None)
    backward = backward_solver.calc(second_gray, first_gray, None)
    height, width = first_gray.shape
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )

    def directional_confidence(flow: Any, opposite: Any, geometry: Any) -> Any:
        mapped_x = grid_x + flow[..., 0]
        mapped_y = grid_y + flow[..., 1]
        inside = (
            (mapped_x >= 0.0)
            & (mapped_x <= width - 1.0)
            & (mapped_y >= 0.0)
            & (mapped_y <= height - 1.0)
        )
        sampled_opposite = cv2.remap(
            opposite,
            mapped_x,
            mapped_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        round_trip = np.linalg.norm(flow + sampled_opposite, axis=2)
        first_points = np.stack(
            [grid_x, grid_y, np.ones_like(grid_x)], axis=-1
        )
        second_points = np.stack(
            [mapped_x, mapped_y, np.ones_like(mapped_x)], axis=-1
        )
        lines_second = first_points @ geometry.T
        lines_first = second_points @ geometry
        numerator = np.abs(np.sum(second_points * lines_second, axis=-1))
        denominator = np.sqrt(
            np.square(lines_second[..., 0])
            + np.square(lines_second[..., 1])
            + np.square(lines_first[..., 0])
            + np.square(lines_first[..., 1])
        )
        epipolar_error = numerator / np.maximum(denominator, 1e-6)
        strong = inside & (round_trip <= 1.5) & (epipolar_error <= 1.5)
        usable = inside & (round_trip <= 3.0) & (epipolar_error <= 3.0)
        confidence = np.zeros((height, width), dtype=np.uint8)
        confidence[usable] = 96
        confidence[strong] = 255
        # Remove a narrow uncertain boundary around occlusion/flow failures so
        # high-frequency foliage edges cannot leak into the photometric loss.
        rejected = (confidence < 96).astype(np.uint8)
        rejected = cv2.dilate(rejected, np.ones((3, 3), np.uint8), iterations=1)
        confidence[rejected != 0] = 0
        return confidence

    return (
        directional_confidence(forward, backward, matrix),
        directional_confidence(backward, forward, matrix.T),
    )


def build_static_confidence_masks(
    context: JobContext,
    training_root: Path,
    frame_timestamps: dict[str, float],
) -> dict[str, Any]:
    """Write lossless confidence weights aligned to COLMAP-undistorted images."""
    import cv2
    import numpy as np
    import pycolmap

    sparse_candidates = [training_root / "sparse", training_root / "sparse" / "0"]
    model_root = next(
        (
            candidate
            for candidate in sparse_candidates
            if candidate.is_dir() and any(candidate.glob("cameras.*"))
        ),
        None,
    )
    if model_root is None:
        raise WorkerError(
            "static_mask_failed",
            "The undistorted COLMAP model is missing; static confidence cannot be built.",
        )
    reconstruction = pycolmap.Reconstruction(str(model_root))
    images_by_name = {
        image.name: image
        for image in reconstruction.images.values()
        if image.has_pose
    }
    image_root = training_root / "images"
    mask_root = training_root / "masks"
    mask_root.mkdir(parents=True, exist_ok=True)
    video_groups: dict[str, list[tuple[float, str]]] = collections.defaultdict(list)
    for name in images_by_name:
        timestamp = frame_timestamps.get(name)
        if timestamp is not None and math.isfinite(timestamp):
            video_groups[Path(name).parent.as_posix()].append((timestamp, name))
    for values in video_groups.values():
        values.sort(key=lambda item: (item[0], item[1]))

    work_limit = 720
    confidences: dict[str, Any] = {}
    image_dimensions: dict[str, tuple[int, int]] = {}
    pair_count = 0

    def load_work_image(name: str) -> Any:
        image = cv2.imread(str(image_root / name), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise WorkerError(
                "static_mask_failed", f"Unable to read undistorted image {name}."
            )
        height, width = image.shape
        image_dimensions[name] = (width, height)
        scale = min(1.0, work_limit / float(max(width, height)))
        if scale < 1.0:
            image = cv2.resize(
                image,
                (max(2, round(width * scale)), max(2, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        return image

    def scaled_calibration(name: str, work: Any) -> tuple[Any, Any]:
        image = images_by_name[name]
        camera = reconstruction.cameras[image.camera_id]
        calibration = np.asarray(camera.calibration_matrix(), dtype=np.float64)
        calibration[0, :] *= work.shape[1] / float(camera.width)
        calibration[1, :] *= work.shape[0] / float(camera.height)
        pose = np.asarray(image.cam_from_world().matrix(), dtype=np.float64)
        return calibration, pose

    total_pairs = sum(max(0, len(values) - 1) for values in video_groups.values())
    for group_name, values in sorted(video_groups.items()):
        if len(values) < 2:
            continue
        previous_name = values[0][1]
        previous_gray = load_work_image(previous_name)
        confidences.setdefault(
            previous_name, np.full(previous_gray.shape, 255, dtype=np.uint8)
        )
        for _, current_name in values[1:]:
            context.check_cancel()
            current_gray = load_work_image(current_name)
            if current_gray.shape != previous_gray.shape:
                raise WorkerError(
                    "static_mask_failed",
                    f"Video camera group {group_name} changes dimensions after undistortion.",
                    "Split clips at focal/crop changes or provide an explicit camera group.",
                )
            first_k, first_pose = scaled_calibration(previous_name, previous_gray)
            second_k, second_pose = scaled_calibration(current_name, current_gray)
            relative_rotation = second_pose[:, :3] @ first_pose[:, :3].T
            relative_translation = (
                second_pose[:, 3] - relative_rotation @ first_pose[:, 3]
            )
            tx, ty, tz = relative_translation.tolist()
            cross_translation = np.asarray(
                [[0.0, -tz, ty], [tz, 0.0, -tx], [-ty, tx, 0.0]],
                dtype=np.float64,
            )
            fundamental = (
                np.linalg.inv(second_k).T
                @ cross_translation
                @ relative_rotation
                @ np.linalg.inv(first_k)
            )
            first_confidence, second_confidence = static_pair_confidence(
                previous_gray, current_gray, fundamental
            )
            confidences[previous_name] = np.minimum(
                confidences[previous_name], first_confidence
            )
            if current_name in confidences:
                confidences[current_name] = np.minimum(
                    confidences[current_name], second_confidence
                )
            else:
                confidences[current_name] = second_confidence
            pair_count += 1
            context.events.emit(
                "stage_progress",
                stage="pose",
                completed=pair_count,
                total=total_pairs,
                unit="static_flow_pairs",
            )
            previous_name = current_name
            previous_gray = current_gray

    coverage_values: list[float] = []
    zero_fraction_values: list[float] = []
    video_image_count = 0
    for name in sorted(images_by_name):
        context.check_cancel()
        if name in confidences:
            confidence = confidences[name]
            video_image_count += 1
        else:
            gray = load_work_image(name)
            confidence = np.full(gray.shape, 255, dtype=np.uint8)
        if name in confidences:
            # The lowest video strip often contains the capture vehicle or
            # dashboard and is never stable world geometry.  Still photos are
            # not cropped by this video-specific rule.
            bottom = max(1, round(confidence.shape[0] * 0.04))
            confidence[-bottom:, :] = 0
        width, height = image_dimensions[name]
        if confidence.shape != (height, width):
            confidence = cv2.resize(
                confidence, (width, height), interpolation=cv2.INTER_LINEAR
            )
        output_path = mask_root / name
        write_selected_frame(output_path, confidence)
        coverage_values.append(float(confidence.mean() / 255.0))
        zero_fraction_values.append(float(np.mean(confidence == 0)))

    if not coverage_values or len(coverage_values) != len(images_by_name):
        raise WorkerError(
            "static_mask_failed",
            "Static-confidence masks do not cover every registered training image.",
        )
    mean_coverage = float(np.mean(coverage_values))
    p10_coverage = float(np.percentile(coverage_values, 10))
    if video_image_count and (mean_coverage < 0.20 or p10_coverage < 0.08):
        raise WorkerError(
            "static_mask_gate_failed",
            "Too little static, geometrically consistent image evidence remains.",
            f"Mean confidence coverage is {mean_coverage:.1%}; frame P10 is "
            f"{p10_coverage:.1%}. Use a sharper, slower capture with fewer "
            "moving objects or unstable foliage.",
        )
    return {
        "schema": "servo.static-confidence/v1",
        "method": "DIS-bidirectional-flow-plus-COLMAP-epipolar-v1",
        "registeredImages": len(images_by_name),
        "videoImages": video_image_count,
        "videoPairs": pair_count,
        "workMaxDimension": work_limit,
        "bottomExclusionFraction": 0.04,
        "meanCoverage": mean_coverage,
        "p10Coverage": p10_coverage,
        "meanZeroWeightFraction": float(np.mean(zero_fraction_values)),
    }


def pose_stage(context: JobContext) -> tuple[dict[str, Any], list[Path]]:
    output = context.stage_path("pose")
    output.mkdir(parents=True, exist_ok=True)
    images = context.stage_path("extract") / "images"
    frames_manifest = read_json(context.stage_path("extract") / "frames.json")
    selected_count = int(frames_manifest["selectedCount"])
    frame_timestamps = {
        str(frame["image"]): float(frame["timestampSeconds"])
        for frame in frames_manifest.get("frames", [])
        if isinstance(frame, dict)
        and isinstance(frame.get("image"), str)
        and isinstance(frame.get("timestampSeconds"), (int, float))
        and math.isfinite(float(frame["timestampSeconds"]))
    }
    database = output / "database.db"
    sparse_root = output / "sparse"
    sparse_root.mkdir(parents=True, exist_ok=True)

    feature_arguments = [
        "feature_extractor",
        "--database_path", str(database),
        "--image_path", str(images),
        "--ImageReader.single_camera_per_folder", "1",
        "--ImageReader.camera_model", "SIMPLE_RADIAL",
        "--FeatureExtraction.type", "SIFT",
        "--FeatureExtraction.use_gpu", "1",
    ]
    run_colmap(context, "pose", feature_arguments)
    sources = context.job["sources"]
    has_video = any(source["kind"] == "video" for source in sources)
    needs_cross_source_matching = len(sources) > 1 or not has_video
    if has_video:
        vocabulary = find_vocab_tree()
        if vocabulary is None:
            raise WorkerError(
                "vocab_tree_missing",
                "Video loop closure requires the pinned COLMAP retrieval vocabulary.",
            )
        run_colmap(
            context,
            "pose",
            [
                "sequential_matcher",
                "--database_path", str(database),
                "--FeatureMatching.use_gpu", "1",
                "--SequentialMatching.overlap", "12",
                "--SequentialMatching.loop_detection", "1",
                "--SequentialMatching.loop_detection_period", "10",
                "--SequentialMatching.loop_detection_num_images", "50",
                "--SequentialMatching.vocab_tree_path", str(vocabulary),
            ],
        )
    if needs_cross_source_matching:
        if selected_count <= 500:
            matcher_arguments = [
                "exhaustive_matcher",
                "--database_path", str(database),
                "--FeatureMatching.use_gpu", "1",
            ]
        else:
            vocabulary = find_vocab_tree()
            if vocabulary is None:
                raise WorkerError(
                    "vocab_tree_missing",
                    "Large or mixed source collections require the pinned COLMAP retrieval vocabulary.",
                )
            matcher_arguments = [
                "vocab_tree_matcher",
                "--database_path", str(database),
                "--FeatureMatching.use_gpu", "1",
                "--VocabTreeMatching.vocab_tree_path", str(vocabulary),
                "--VocabTreeMatching.num_images", "100",
            ]
        run_colmap(context, "pose", matcher_arguments)
    run_colmap(
        context,
        "pose",
        [
            "mapper",
            "--database_path", str(database),
            "--image_path", str(images),
            "--output_path", str(sparse_root),
        ],
    )
    models = [("incremental", path) for path in sparse_root.iterdir() if path.is_dir()]

    raw_scored = [
        (
            reconstruction_metrics(model, selected_count, frame_timestamps),
            solver,
            model,
        )
        for solver, model in models
    ]
    # Always compare the incremental solution with COLMAP's calibrated global
    # solver.  A model can register every frame and still have short tracks or
    # an unstable trajectory; the old road artifact did exactly that, so count
    # and reprojection gates alone must not suppress the stronger candidate.
    global_root = output / "sparse-global"
    global_root.mkdir(parents=True, exist_ok=True)
    global_database = output / "database-global.db"
    try:
        context.require_free_space(
            database.stat().st_size * 2 + 512 * 1024**2,
            "Calibrated global-mapper comparison",
        )
        shutil.copy2(database, global_database)
        run_colmap(
            context,
            "pose",
            [
                "view_graph_calibrator",
                "--database_path", str(global_database),
            ],
        )
        run_colmap(
            context,
            "pose",
            [
                "global_mapper",
                "--database_path", str(global_database),
                "--image_path", str(images),
                "--output_path", str(global_root),
            ],
        )
        global_models = [path for path in global_root.iterdir() if path.is_dir()]
        raw_scored.extend(
            (
                reconstruction_metrics(model, selected_count, frame_timestamps),
                "global",
                model,
            )
            for model in global_models
        )
    except Cancelled:
        raise
    except WorkerError as error:
        context.events.emit(
            "pose_solver_failed",
            stage="pose",
            solver="global",
            code=error.code,
            message=str(error),
            details=error.details,
        )
    if not raw_scored:
        raise WorkerError(
            "pose_failed",
            "COLMAP could not recover a connected camera model.",
            "The capture needs more overlap, translation, texture, and less motion blur.",
        )
    scored: list[tuple[dict[str, Any], str, Path]] = []
    for index, (candidate, solver, model) in enumerate(raw_scored):
        try:
            scored.append(
                filter_pose_candidate(
                    context,
                    model,
                    output / f"sparse-filtered-{index:02d}",
                    selected_count,
                    frame_timestamps,
                    solver,
                )
            )
        except Cancelled:
            raise
        except WorkerError as error:
            context.events.emit(
                "pose_solver_failed",
                stage="pose",
                solver=f"{solver}+confidence-filter",
                code=error.code,
                message=str(error),
                details=error.details,
            )
    fidelity_refinement_required = (
        context.profile.name == "fidelity-12gb" and selected_count <= 500
    )
    if fidelity_refinement_required:
        fidelity_candidates = fidelity_refine_pose_candidates(
            context,
            output,
            images,
            database,
            raw_scored,
            selected_count,
            frame_timestamps,
        )
        passing_fidelity_candidates = [
            candidate
            for candidate in fidelity_candidates
            if pose_candidate_passes_gate(candidate[0], context.profile)
        ]
        if not fidelity_candidates:
            raise WorkerError(
                "fidelity_pose_refinement_failed",
                "The required guided exhaustive Fidelity refinement produced no camera model.",
            )
        if not passing_fidelity_candidates:
            raise WorkerError(
                "fidelity_pose_refinement_failed",
                "The required guided exhaustive Fidelity refinement did not pass its camera-quality gates.",
                json.dumps(
                    [candidate[0] for candidate in fidelity_candidates], sort_keys=True
                ),
            )
        scored.extend(fidelity_candidates)
    if not scored:
        raise WorkerError(
            "pose_failed",
            "No confidence-filtered camera model remained after pose refinement.",
            "The capture needs more overlap, translation, texture, and less motion blur.",
        )
    selected = select_pose_candidate(scored, context.profile)
    assert selected is not None
    metrics, selected_solver, best_model = selected
    ranked_attempts = sorted(scored, key=pose_candidate_quality_key, reverse=True)
    metrics["solver"] = selected_solver
    metrics["solverAttempts"] = [
        {"solver": solver, "model": model.name, **candidate}
        for candidate, solver, model in ranked_attempts
    ]
    metrics["rawSolverAttempts"] = [
        {"solver": solver, "model": model.name, **candidate}
        for candidate, solver, model in sorted(
            raw_scored, key=pose_candidate_quality_key, reverse=True
        )
    ]
    if metrics["registeredImages"] < context.profile.min_registered_images:
        raise WorkerError(
            "pose_gate_failed",
            f"Only {metrics['registeredImages']} cameras registered; {context.profile.min_registered_images} are required.",
        )
    if metrics["registeredRatio"] < context.profile.min_registered_ratio:
        raise WorkerError(
            "pose_gate_failed",
            f"Camera registration was {metrics['registeredRatio']:.1%}; the {context.profile.label} gate requires {context.profile.min_registered_ratio:.0%}.",
        )
    minimum_points = minimum_reliable_pose_points(metrics)
    if metrics["points3D"] < minimum_points:
        raise WorkerError(
            "pose_gate_failed",
            f"Only {metrics['points3D']} confidence-filtered sparse points remained; "
            f"this {metrics['registeredImages']}-camera solve requires at least "
            f"{minimum_points}.",
        )
    p95_error = metrics.get("p95ReprojectionError")
    if p95_error is not None and p95_error > context.profile.max_reprojection_error:
        raise WorkerError(
            "pose_gate_failed",
            f"P95 reprojection error was {p95_error:.2f}px; the gate is {context.profile.max_reprojection_error:.2f}px.",
        )
    if p95_error is None:
        raise WorkerError(
            "pose_gate_failed", "The camera solution has no finite reprojection evidence."
        )
    median_track_length = metrics.get("medianTrackLength")
    if (
        median_track_length is None
        or median_track_length < context.profile.min_median_track_length
    ):
        raise WorkerError(
            "pose_gate_failed",
            "Median feature-track length was "
            f"{float(median_track_length or 0.0):.1f}; "
            f"the {context.profile.label} gate requires "
            f"{context.profile.min_median_track_length:.1f} views per track.",
        )
    for field, label in (
        ("cameraForwardStepMaxDegrees", "view direction"),
        ("cameraUpStepMaxDegrees", "camera up"),
    ):
        value = metrics.get(field)
        if (
            value is not None
            and value > context.profile.max_camera_rotation_step_degrees
        ):
            raise WorkerError(
                "pose_gate_failed",
                f"The recovered {label} jumps {value:.1f} degrees between video "
                f"frames; the gate is "
                f"{context.profile.max_camera_rotation_step_degrees:.1f} degrees.",
            )
    speed_ratio = metrics.get("cameraSpeedMaxRatio")
    if speed_ratio is not None and speed_ratio > context.profile.max_camera_speed_ratio:
        raise WorkerError(
            "pose_gate_failed",
            f"The recovered camera speed jumps to {speed_ratio:.1f}x its median; "
            f"the gate is {context.profile.max_camera_speed_ratio:.1f}x.",
        )
    training = output / "training"
    run_colmap(
        context,
        "pose",
        [
            "image_undistorter",
            "--image_path", str(images),
            "--input_path", str(best_model),
            "--output_path", str(training),
            "--output_type", "COLMAP",
            "--max_image_size", str(context.profile.max_dimension),
        ],
    )
    metrics["staticConfidence"] = build_static_confidence_masks(
        context, training, frame_timestamps
    )
    metrics_path = output / "pose-metrics.json"
    atomic_write_json(
        metrics_path,
        {
            "schema": "servo.pose-metrics/v1",
            "jobId": context.job_id,
            "profile": context.profile.name,
            "pipelineRevision": PIPELINE_REVISION,
            **metrics,
        },
    )
    artifacts = [database, metrics_path]
    global_database = output / "database-global.db"
    if global_database.is_file():
        artifacts.append(global_database)
    artifacts.extend(
        path
        for _, _, model in scored
        for path in model.rglob("*")
        if path.is_file()
    )
    artifacts.extend(path for path in training.rglob("*") if path.is_file())
    return metrics, artifacts


def train_stage(context: JobContext) -> tuple[dict[str, Any], list[Path]]:
    output = context.stage_path("train")
    output.mkdir(parents=True, exist_ok=True)
    training_data = context.stage_path("pose") / "training"
    config = {
        "schema": "servo.gsplat-training/v2",
        "jobId": context.job_id,
        "data": str(training_data),
        "output": str(output),
        "profile": context.profile.name,
        "pipelineRevision": PIPELINE_REVISION,
        "dataFactor": context.profile.data_factor,
        "maxSteps": context.profile.max_steps,
        "checkpointEvery": context.profile.checkpoint_every,
        "packed": True,
        "shDegree": context.profile.sh_degree,
        "representationType": REPRESENTATION_TYPE,
        "rasterizationMode": context.profile.rasterization_mode,
        "eps2d": context.profile.eps2d,
        "absgrad": context.profile.absgrad,
        "growGrad2d": context.profile.grow_grad2d,
        "coarseFactor": context.profile.coarse_factor,
        "coarseSteps": context.profile.coarse_steps,
        "finalFitSteps": context.profile.final_fit_steps,
        "targetGaussians": context.profile.target_gaussians,
        "maxGaussians": context.profile.max_gaussians,
        "qualityGate": {
            "minimumPsnr": 22.0,
            "minimumSsim": 0.75,
            "maximumDepthAmbiguityP50": 0.20,
            "maximumDepthAmbiguityP95": 1.0,
            "maximumDepthAmbiguityFractionAbove10Percent": 0.75,
            "minimumFinalArtifactPsnr": 22.0,
            "minimumFinalArtifactSsim": 0.75,
            "maximumFinalPsnrRegression": 0.5,
            "maximumFinalSsimRegression": 0.03,
            "minimumExactPlyRegisteredPsnrP10": 18.0,
            "minimumExactPlyRegisteredSsimP10": 0.60,
            "maximumConsecutiveDegradedViews": 2,
        },
        "appearanceCompensation": context.profile.appearance_compensation,
        "appearanceLearningRate": context.profile.appearance_learning_rate,
        "appearanceRegularization": context.profile.appearance_regularization,
        "staticConfidenceMasks": True,
        "staticConfidenceMethod": "DIS-bidirectional-flow-plus-COLMAP-epipolar-v1",
        "scaleRegularization": 0.001,
        "sparseDepthWeight": 0.05,
        "depthLayerVarianceWeight": 0.01,
        "depthLayerVarianceEvery": 8,
        "depthLayerVarianceStart": 1_000,
        "maxReprojectionError": context.profile.max_reprojection_error,
        "maxVramGiB": context.profile.expected_vram_gib,
        "cancelPath": str(context.cancel_path),
        "configurationHash": context.configuration_hash,
    }
    config_path = output / "training-config.json"
    atomic_write_json(config_path, config)
    trainer = Path(__file__).with_name("servo_train.py")
    run_process(
        context,
        "train",
        [sys.executable, str(trainer), "train", "--config", str(config_path)],
        environment=compiler_environment(),
    )
    metrics_path = output / "train-metrics.json"
    ply_path = output / "world.ply"
    cameras_path = output / "cameras.json"
    appearance_path = output / "appearance.json"
    if (
        not metrics_path.is_file()
        or not ply_path.is_file()
        or not cameras_path.is_file()
        or not appearance_path.is_file()
    ):
        raise WorkerError(
            "training_artifact_missing",
            "Gaussian training did not produce its required metrics, cameras, appearance, and PLY.",
        )
    metrics = read_json(metrics_path)
    heldout_metrics_path = output / "heldout-metrics.json"
    if not heldout_metrics_path.is_file():
        raise WorkerError(
            "training_artifact_missing",
            "Gaussian training did not preserve its unbiased held-out evaluation.",
        )
    artifacts = [
        config_path,
        metrics_path,
        heldout_metrics_path,
        cameras_path,
        appearance_path,
        ply_path,
    ]
    artifacts.extend(sorted((output / "checkpoints").glob("*.pt")))
    artifacts.extend(sorted((output / "checkpoints").glob("*.json")))
    artifacts.extend(sorted((output / "validation").glob("*.png")))
    artifacts.extend(sorted((output / "path-stress-validation").glob("*.png")))
    artifacts.extend(sorted((output / "final-validation").glob("*.png")))
    return metrics, artifacts


def parse_ply_header(
    path: Path,
    *,
    spatial_limit: float = 10.0,
    scale_limit: float = 2.0,
) -> dict[str, Any]:
    import numpy as np

    required = {
        "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
        "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
    }
    with path.open("rb") as stream:
        header = stream.read(1024 * 1024)
    marker = b"end_header\n"
    end = header.find(marker)
    if end < 0:
        marker = b"end_header\r\n"
        end = header.find(marker)
    if end < 0:
        raise WorkerError("invalid_ply", "Gaussian PLY has no complete header.")
    try:
        lines = header[: end + len(marker)].decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise WorkerError("invalid_ply", "Gaussian PLY header is not ASCII.") from error
    if not lines or lines[0] != "ply":
        raise WorkerError("invalid_ply", "Gaussian artifact is not a PLY file.")
    format_line = next((line for line in lines if line.startswith("format ")), "")
    if format_line not in {"format binary_little_endian 1.0", "format ascii 1.0"}:
        raise WorkerError("invalid_ply", f"Unsupported PLY format: {format_line or 'missing'}")
    vertex_line = next((line for line in lines if line.startswith("element vertex ")), "")
    try:
        vertex_count = int(vertex_line.rsplit(" ", 1)[-1])
    except ValueError as error:
        raise WorkerError("invalid_ply", "Gaussian PLY has an invalid vertex count.") from error
    scalar_types = {
        "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
        "short": "<i2", "int16": "<i2", "ushort": "<u2", "uint16": "<u2",
        "int": "<i4", "int32": "<i4", "uint": "<u4", "uint32": "<u4",
        "float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8",
    }
    current_element = ""
    vertex_properties: list[tuple[str, str]] = []
    other_elements: list[str] = []
    comments: list[str] = []
    for line in lines:
        if line.startswith("comment "):
            comments.append(line[len("comment ") :])
        elif line.startswith("element "):
            parts = line.split()
            current_element = parts[1] if len(parts) >= 3 else ""
            if current_element and current_element != "vertex":
                other_elements.append(current_element)
        elif line.startswith("property ") and current_element == "vertex":
            parts = line.split()
            if len(parts) != 3 or parts[1] == "list":
                raise WorkerError("invalid_ply", "Gaussian PLY vertex properties must be scalar values.")
            if parts[1] not in scalar_types:
                raise WorkerError("invalid_ply", f"Unsupported PLY scalar type: {parts[1]}")
            vertex_properties.append((parts[1], parts[2]))
    if other_elements:
        raise WorkerError("invalid_ply", "Gaussian PLY must contain only a vertex element.")
    properties = [name for _, name in vertex_properties]
    if len(properties) != len(set(properties)):
        raise WorkerError("invalid_ply", "Gaussian PLY contains duplicate vertex property names.")
    missing = sorted(required.difference(properties))
    if missing:
        raise WorkerError("invalid_ply", "Gaussian PLY is missing required properties: " + ", ".join(missing))
    property_types = {name: data_type for data_type, name in vertex_properties}
    non_floating = sorted(
        name for name in required
        if not np.issubdtype(np.dtype(scalar_types[property_types[name]]), np.floating)
    )
    if non_floating:
        raise WorkerError(
            "invalid_ply",
            "Gaussian PLY requires floating-point values for: " + ", ".join(non_floating),
        )
    rest = [name for name in properties if name.startswith("f_rest_")]
    if rest:
        coefficient_count = len(rest) // 3 + 1
        degree = round(math.sqrt(coefficient_count) - 1)
        if len(rest) % 3 or (degree + 1) ** 2 != coefficient_count:
            raise WorkerError("invalid_ply", "Gaussian PLY has a partial spherical-harmonic basis.")
    else:
        degree = 0
    if vertex_count <= 0:
        raise WorkerError("invalid_ply", "Gaussian PLY contains no splats.")
    header_bytes = end + len(marker)
    numpy_dtype = np.dtype([(name, scalar_types[data_type]) for data_type, name in vertex_properties])
    payload_bytes = int(numpy_dtype.itemsize) * vertex_count
    minimum_bytes = header_bytes + payload_bytes
    file_bytes = path.stat().st_size
    if format_line == "format binary_little_endian 1.0" and file_bytes < minimum_bytes:
        raise WorkerError(
            "invalid_ply",
            f"Gaussian PLY payload is truncated: expected at least {minimum_bytes} bytes; found {file_bytes}.",
        )
    quality: dict[str, Any] = {}
    if format_line == "format binary_little_endian 1.0":
        records = np.memmap(
            path,
            dtype=numpy_dtype,
            mode="r",
            offset=header_bytes,
            shape=(vertex_count,),
        )
        property_indices = {name: index for index, name in enumerate(properties)}
        bounds_min_array = np.full(3, np.inf, dtype=np.float64)
        bounds_max_array = np.full(3, -np.inf, dtype=np.float64)
        sample_stride = max(1, math.ceil(vertex_count / 250_000))
        samples: list[Any] = []
        sample_columns = [
            property_indices[name]
            for name in (
                "x",
                "y",
                "z",
                "opacity",
                "scale_0",
                "scale_1",
                "scale_2",
            )
        ]
        for start in range(0, vertex_count, 65_536):
            stop = min(start + 65_536, vertex_count)
            chunk = records[start:stop]
            matrix = np.column_stack([chunk[name] for name in properties])
            if not bool(np.isfinite(matrix).all()):
                raise WorkerError("invalid_ply", "Gaussian PLY contains NaN or infinity.")
            quaternion = matrix[
                :,
                [property_indices[f"rot_{index}"] for index in range(4)],
            ].astype(np.float64, copy=False)
            if bool((np.linalg.norm(quaternion, axis=1) < 1e-8).any()):
                raise WorkerError("invalid_ply", "Gaussian PLY contains a zero quaternion.")
            scale_logs = matrix[
                :,
                [property_indices[f"scale_{index}"] for index in range(3)],
            ]
            if bool((np.abs(scale_logs) > 80.0).any()):
                raise WorkerError("invalid_ply", "Gaussian PLY contains a scale that would overflow at runtime.")
            positions = matrix[:, :3]
            bounds_min_array = np.minimum(bounds_min_array, positions.min(axis=0))
            bounds_max_array = np.maximum(bounds_max_array, positions.max(axis=0))
            first_sample = (-start) % sample_stride
            samples.append(matrix[first_sample::sample_stride, sample_columns].copy())
        sample = np.concatenate(samples, axis=0).astype(np.float64, copy=False)
        radius = np.linalg.norm(sample[:, :3], axis=1)
        radius_p99 = float(np.percentile(radius, 99))
        scale_values = np.exp(np.clip(sample[:, 4:7], -80.0, 80.0))
        largest_scale = scale_values.max(axis=1)
        anisotropy = largest_scale / np.maximum(scale_values.min(axis=1), 1e-12)
        opacity = 1.0 / (1.0 + np.exp(-np.clip(sample[:, 3], -80.0, 80.0)))
        quality = {
            "sampleCount": int(len(sample)),
            "radiusP99": radius_p99,
            "radiusMax": float(radius.max()),
            "spatialLimit": float(spatial_limit),
            "spatialOutlierFraction": float(np.mean(radius > spatial_limit)),
            "anisotropyP99": float(np.percentile(anisotropy, 99)),
            "needleFraction": float(np.mean(anisotropy > 50.0)),
            "largestScaleP99": float(np.percentile(largest_scale, 99)),
            "scaleLimit": float(scale_limit),
            "oversizedFraction": float(np.mean(largest_scale > scale_limit)),
            "nearTransparentFraction": float(np.mean(opacity < 0.01)),
        }
        bounds_min = bounds_min_array.tolist()
        bounds_max = bounds_max_array.tolist()
        del records
    else:
        bounds_min = [math.inf, math.inf, math.inf]
        bounds_max = [-math.inf, -math.inf, -math.inf]
        with path.open("rb") as stream:
            stream.seek(header_bytes)
            for row in range(vertex_count):
                line = stream.readline()
                if not line:
                    raise WorkerError("invalid_ply", f"Gaussian PLY ASCII payload ended at vertex {row}.")
                values = line.split()
                if len(values) != len(vertex_properties):
                    raise WorkerError("invalid_ply", f"Gaussian PLY vertex {row} has the wrong property count.")
                parsed: dict[str, float] = {}
                for (_, name), value in zip(vertex_properties, values):
                    try:
                        number = float(value)
                    except ValueError as error:
                        raise WorkerError("invalid_ply", f"Gaussian PLY property {name} is not numeric.") from error
                    if not math.isfinite(number):
                        raise WorkerError("invalid_ply", f"Gaussian PLY property {name} contains NaN or infinity.")
                    parsed[name] = number
                norm = math.sqrt(sum(parsed[f"rot_{index}"] ** 2 for index in range(4)))
                if norm < 1e-8:
                    raise WorkerError("invalid_ply", "Gaussian PLY contains a zero quaternion.")
                for axis, name in enumerate(("x", "y", "z")):
                    bounds_min[axis] = min(bounds_min[axis], parsed[name])
                    bounds_max[axis] = max(bounds_max[axis], parsed[name])
    return {
        "format": format_line.split()[1],
        "vertexCount": vertex_count,
        "shDegree": degree,
        "properties": properties,
        "comments": comments,
        "headerBytes": header_bytes,
        "payloadBytes": payload_bytes,
        "fileBytes": file_bytes,
        "boundsMin": bounds_min,
        "boundsMax": bounds_max,
        "quality": quality,
    }


def validate_stage(context: JobContext) -> tuple[dict[str, Any], list[Path]]:
    output = context.stage_path("validate")
    output.mkdir(parents=True, exist_ok=True)
    ply = context.stage_path("train") / "world.ply"
    if not ply.is_file():
        raise WorkerError("missing_ply", "The trained Gaussian PLY is missing.")
    train_metrics = read_json(context.stage_path("train") / "train-metrics.json")
    heldout_metrics = read_json(
        context.stage_path("train") / "heldout-metrics.json"
    )
    pose_metrics = read_json(context.stage_path("pose") / "pose-metrics.json")
    training_config = read_json(context.stage_path("train") / "training-config.json")
    cameras = read_json(context.stage_path("train") / "cameras.json")
    appearance = read_json(context.stage_path("train") / "appearance.json")
    cleanup = train_metrics.get("cleanup")
    if not isinstance(cleanup, dict):
        raise WorkerError("invalid_metrics", "Training cleanup metrics are missing.")
    try:
        spatial_limit = float(cleanup["radiusLimitNormalized"])
        scale_limit = float(cleanup["scaleLimitNormalized"])
    except (KeyError, TypeError, ValueError) as error:
        raise WorkerError(
            "invalid_metrics",
            "Training cleanup limits are missing or invalid.",
        ) from error
    if not math.isfinite(spatial_limit) or spatial_limit <= 0:
        raise WorkerError("invalid_metrics", "Training cleanup spatial limit is invalid.")
    if not math.isfinite(scale_limit) or scale_limit <= 0:
        raise WorkerError("invalid_metrics", "Training cleanup scale limit is invalid.")
    ply_metrics = parse_ply_header(
        ply,
        spatial_limit=spatial_limit,
        scale_limit=scale_limit,
    )

    def require_finite(value: Any, location: str) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise WorkerError("invalid_metrics", f"{location} is NaN or infinite.")
            return
        if isinstance(value, dict):
            for key, child in value.items():
                require_finite(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                require_finite(child, f"{location}[{index}]")

    require_finite(train_metrics, "training")
    require_finite(heldout_metrics, "heldout")
    require_finite(pose_metrics, "pose")
    if train_metrics.get("schema") != "servo.gsplat-metrics/v2":
        raise WorkerError("invalid_metrics", "Training metrics use an unsupported schema.")
    if pose_metrics.get("schema") != "servo.pose-metrics/v1":
        raise WorkerError("invalid_metrics", "Pose metrics use an unsupported schema.")
    if heldout_metrics.get("schema") != "servo.gsplat-heldout-evaluation/v1":
        raise WorkerError(
            "invalid_metrics", "Held-out metrics use an unsupported schema."
        )
    if training_config.get("schema") != "servo.gsplat-training/v2":
        raise WorkerError("invalid_metrics", "Training configuration uses an unsupported schema.")
    if cameras.get("schema") != "servo.gaussian-cameras/v1":
        raise WorkerError("invalid_metrics", "Camera artifact uses an unsupported schema.")
    if appearance.get("schema") != "servo.gaussian-appearance/v1":
        raise WorkerError("invalid_metrics", "Appearance artifact uses an unsupported schema.")
    for artifact_name, artifact in (
        ("training", train_metrics),
        ("held-out", heldout_metrics),
        ("pose", pose_metrics),
    ):
        if artifact.get("jobId") != context.job_id:
            raise WorkerError("artifact_mismatch", f"{artifact_name.title()} artifact belongs to another job.")
        if artifact.get("profile") != context.profile.name:
            raise WorkerError("artifact_mismatch", f"{artifact_name.title()} artifact uses another profile.")
    if train_metrics.get("pipelineRevision") != PIPELINE_REVISION:
        raise WorkerError("artifact_mismatch", "Training artifact uses another pipeline revision.")
    if heldout_metrics.get("pipelineRevision") != PIPELINE_REVISION:
        raise WorkerError(
            "artifact_mismatch", "Held-out artifact uses another pipeline revision."
        )
    if train_metrics.get("configurationHash") != context.configuration_hash:
        raise WorkerError("artifact_mismatch", "Training artifact configuration hash does not match the job.")
    if heldout_metrics.get("configurationHash") != context.configuration_hash:
        raise WorkerError(
            "artifact_mismatch",
            "Held-out artifact configuration hash does not match the job.",
        )
    if train_metrics.get("representationType") != REPRESENTATION_TYPE:
        raise WorkerError("artifact_mismatch", "Training artifact uses another Gaussian representation.")
    if training_config.get("representationType") != REPRESENTATION_TYPE:
        raise WorkerError("artifact_mismatch", "Training configuration uses another Gaussian representation.")
    rasterization_mode = training_config.get("rasterizationMode")
    if rasterization_mode not in {"classic", "antialiased"}:
        raise WorkerError("invalid_metrics", "Training rasterization mode is invalid.")
    if train_metrics.get("rasterizationMode") != rasterization_mode:
        raise WorkerError("artifact_mismatch", "Training rasterization metadata is inconsistent.")
    try:
        configured_eps2d = float(training_config["eps2d"])
        measured_eps2d = float(train_metrics["eps2d"])
    except (KeyError, TypeError, ValueError) as error:
        raise WorkerError("invalid_metrics", "Training antialias filter metadata is invalid.") from error
    if (
        not math.isfinite(configured_eps2d)
        or configured_eps2d <= 0.0
        or not math.isclose(configured_eps2d, measured_eps2d, rel_tol=0.0, abs_tol=1e-9)
    ):
        raise WorkerError("artifact_mismatch", "Training antialias filter metadata is inconsistent.")
    quality_gate = training_config.get("qualityGate")
    if not isinstance(quality_gate, dict):
        raise WorkerError("invalid_metrics", "Training quality-gate policy is missing.")

    def required_finite_number(record: dict[str, Any], field: str, label: str) -> float:
        value = record.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise WorkerError(
                "invalid_metrics", f"{label} metric {field} is missing or non-finite."
            )
        return float(value)

    try:
        minimum_psnr = float(quality_gate["minimumPsnr"])
        minimum_ssim = float(quality_gate["minimumSsim"])
        maximum_depth_ambiguity = float(
            quality_gate["maximumDepthAmbiguityP50"]
        )
        maximum_depth_ambiguity_p95 = float(
            quality_gate["maximumDepthAmbiguityP95"]
        )
        maximum_depth_ambiguity_fraction = float(
            quality_gate["maximumDepthAmbiguityFractionAbove10Percent"]
        )
        minimum_final_artifact_psnr = float(
            quality_gate["minimumFinalArtifactPsnr"]
        )
        minimum_final_artifact_ssim = float(
            quality_gate["minimumFinalArtifactSsim"]
        )
        maximum_final_psnr_regression = float(
            quality_gate["maximumFinalPsnrRegression"]
        )
        maximum_final_ssim_regression = float(
            quality_gate["maximumFinalSsimRegression"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise WorkerError(
            "invalid_metrics", "Training quality-gate thresholds are invalid."
        ) from error
    thresholds = (
        minimum_psnr,
        minimum_ssim,
        maximum_depth_ambiguity,
        maximum_depth_ambiguity_p95,
        maximum_depth_ambiguity_fraction,
        minimum_final_artifact_psnr,
        minimum_final_artifact_ssim,
        maximum_final_psnr_regression,
        maximum_final_ssim_regression,
    )
    if not all(math.isfinite(value) and value >= 0.0 for value in thresholds):
        raise WorkerError(
            "invalid_metrics", "Training quality-gate thresholds must be finite."
        )
    required_numeric = (
        "finalLoss",
        "psnrMean",
        "psnrMedian",
        "ssimMean",
        "ssimMedian",
        "depthAmbiguityRelativeStdP50",
        "depthAmbiguityRelativeStdP95",
        "depthAmbiguityFractionAbove10Percent",
        "peakVramGiB",
        "elapsedSeconds",
    )
    for field in required_numeric:
        required_finite_number(train_metrics, field, "Training")
    camera_records = cameras.get("cameras")
    if not isinstance(camera_records, list) or not camera_records:
        raise WorkerError("invalid_metrics", "Camera artifact contains no cameras.")
    camera_count = len(camera_records)
    if int(train_metrics.get("steps", -1)) != int(training_config.get("maxSteps", -2)):
        raise WorkerError("artifact_mismatch", "Training did not complete the configured step count.")
    if int(train_metrics.get("finalFitSteps", -1)) != int(training_config.get("finalFitSteps", -2)):
        raise WorkerError("artifact_mismatch", "The all-frame final-fit step count is inconsistent.")
    if int(train_metrics.get("finalFitImages", -1)) != camera_count:
        raise WorkerError("artifact_mismatch", "The published model was not final-fit on every camera.")
    if int(train_metrics.get("finalFitUniqueImages", -1)) != camera_count:
        raise WorkerError(
            "artifact_mismatch",
            "The final-fit coverage receipt does not include every camera.",
        )
    if int(training_config.get("finalFitSteps", -1)) < camera_count:
        raise WorkerError(
            "artifact_mismatch", "The final-fit schedule cannot cover every camera."
        )
    if int(train_metrics.get("targetGaussians", -1)) != int(training_config.get("targetGaussians", -2)):
        raise WorkerError("artifact_mismatch", "The Gaussian target metadata is inconsistent.")
    if int(train_metrics.get("gaussians", -1)) != int(ply_metrics["vertexCount"]):
        raise WorkerError("artifact_mismatch", "PLY vertex count does not match training metrics.")
    if int(ply_metrics["shDegree"]) != int(training_config.get("shDegree", -1)):
        raise WorkerError("artifact_mismatch", "PLY spherical-harmonic degree does not match training configuration.")
    if int(ply_metrics["vertexCount"]) > int(training_config.get("maxGaussians", -1)):
        raise WorkerError("artifact_mismatch", "PLY exceeds the configured Gaussian allocation ceiling.")
    world_digest = sha256_file(ply)
    if train_metrics.get("worldSha256") != world_digest:
        raise WorkerError(
            "artifact_mismatch",
            "The published PLY is not the exact model recorded by training metrics.",
        )
    if ply_metrics["format"] != "binary_little_endian":
        raise WorkerError("invalid_ply", "Published Gaussian worlds must use streaming binary little-endian PLY.")
    expected_comments = {
        f"ServoRepresentation {REPRESENTATION_TYPE}",
        f"ServoRasterizationMode {rasterization_mode}",
        f"ServoEps2d {configured_eps2d:.9g}",
    }
    if not expected_comments.issubset(set(ply_metrics.get("comments", []))):
        raise WorkerError("artifact_mismatch", "PLY rendering contract comments are missing or inconsistent.")
    if cameras.get("normalization") != train_metrics.get("normalization"):
        raise WorkerError("artifact_mismatch", "Camera and training normalization transforms differ.")
    expected_appearance_mode = (
        "per-frame-log-gain-bias-v1"
        if training_config.get("appearanceCompensation") is True
        else "disabled"
    )
    training_appearance = train_metrics.get("appearance")
    if not isinstance(training_appearance, dict):
        raise WorkerError("invalid_metrics", "Training appearance metrics are missing.")
    if (
        appearance.get("mode") != expected_appearance_mode
        or training_appearance.get("mode") != expected_appearance_mode
    ):
        raise WorkerError("artifact_mismatch", "Appearance compensation artifacts are inconsistent.")
    geometry_regularization = train_metrics.get("geometryRegularization")
    if not isinstance(geometry_regularization, dict):
        raise WorkerError(
            "invalid_metrics", "Geometry regularization metrics are missing."
        )
    static_confidence = pose_metrics.get("staticConfidence")
    if (
        not isinstance(static_confidence, dict)
        or static_confidence.get("schema") != "servo.static-confidence/v1"
        or static_confidence.get("method")
        != training_config.get("staticConfidenceMethod")
        or training_config.get("staticConfidenceMasks") is not True
        or geometry_regularization.get("staticConfidenceMasks") is not True
        or geometry_regularization.get("staticConfidenceMethod")
        != training_config.get("staticConfidenceMethod")
        or int(static_confidence.get("registeredImages", 0)) != camera_count
    ):
        raise WorkerError(
            "artifact_mismatch",
            "Static-confidence masks are missing or inconsistent across pose and training artifacts.",
        )
    for field in ("meanCoverage", "p10Coverage", "meanZeroWeightFraction"):
        required_finite_number(static_confidence, field, "Static confidence")
    try:
        configured_sparse_depth_weight = float(
            training_config["sparseDepthWeight"]
        )
        configured_variance_weight = float(
            training_config["depthLayerVarianceWeight"]
        )
        configured_variance_every = int(
            training_config["depthLayerVarianceEvery"]
        )
        configured_variance_start = int(
            training_config["depthLayerVarianceStart"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise WorkerError(
            "invalid_metrics", "Geometry regularization configuration is invalid."
        ) from error
    for metric_field in (
        "sparseDepthWeight",
        "recentSparseDepthLoss",
        "depthLayerVarianceWeight",
        "recentDepthLayerVarianceLoss",
    ):
        required_finite_number(
            geometry_regularization, metric_field, "Geometry regularization"
        )
    if (
        not math.isclose(
            float(geometry_regularization["sparseDepthWeight"]),
            configured_sparse_depth_weight,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            float(geometry_regularization["depthLayerVarianceWeight"]),
            configured_variance_weight,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or int(geometry_regularization.get("depthLayerVarianceEvery", -1))
        != configured_variance_every
        or int(geometry_regularization.get("depthLayerVarianceStart", -1))
        != configured_variance_start
        or int(geometry_regularization.get("sparseDepthSamples", 0)) <= 0
    ):
        raise WorkerError(
            "artifact_mismatch",
            "Geometry regularization receipt is inconsistent or empty.",
        )
    first_variance_step = (
        (configured_variance_start + configured_variance_every - 1)
        // configured_variance_every
    ) * configured_variance_every
    expected_variance_steps = (
        0
        if first_variance_step >= int(training_config["maxSteps"])
        else (
            (int(training_config["maxSteps"]) - 1 - first_variance_step)
            // configured_variance_every
            + 1
        )
    )
    if int(geometry_regularization.get("depthLayerVarianceSteps", -1)) != (
        expected_variance_steps if configured_variance_weight > 0.0 else 0
    ):
        raise WorkerError(
            "artifact_mismatch",
            "Depth-layer variance regularization did not run on its configured schedule.",
        )

    heldout_step = int(train_metrics.get("heldoutEvaluationStep", -1))
    if int(heldout_metrics.get("evaluatedAtStep", -2)) != heldout_step:
        raise WorkerError(
            "artifact_mismatch", "Held-out metrics refer to another training state."
        )
    checkpoint_reference = heldout_metrics.get("checkpoint")
    if not isinstance(checkpoint_reference, dict):
        raise WorkerError(
            "invalid_metrics", "Held-out metrics have no verified checkpoint receipt."
        )
    checkpoint_name = checkpoint_reference.get("path")
    if (
        not isinstance(checkpoint_name, str)
        or Path(checkpoint_name).name != checkpoint_name
        or int(checkpoint_reference.get("step", -2)) != heldout_step - 1
        or checkpoint_reference.get("configurationHash")
        != context.configuration_hash
    ):
        raise WorkerError(
            "artifact_mismatch", "Held-out checkpoint metadata is inconsistent."
        )
    checkpoint_path = context.stage_path("train") / "checkpoints" / checkpoint_name
    if (
        not checkpoint_path.is_file()
        or checkpoint_path.stat().st_size != int(checkpoint_reference.get("bytes", -1))
        or sha256_file(checkpoint_path) != checkpoint_reference.get("sha256")
    ):
        raise WorkerError(
            "artifact_mismatch", "The exact held-out checkpoint failed verification."
        )
    heldout_fields = (
        "validationImages",
        "psnrMean",
        "psnrMedian",
        "ssimMean",
        "ssimMedian",
        "depthAmbiguityRelativeStdP50",
        "depthAmbiguityRelativeStdP95",
        "depthAmbiguityFractionAbove10Percent",
    )
    for field in heldout_fields:
        heldout_value = required_finite_number(heldout_metrics, field, "Held-out")
        training_value = required_finite_number(train_metrics, field, "Training")
        if not math.isclose(
            heldout_value, training_value, rel_tol=0.0, abs_tol=1e-9
        ):
            raise WorkerError(
                "artifact_mismatch",
                f"Held-out metric {field} does not match the training receipt.",
            )

    final_artifact_validation = train_metrics.get("finalArtifactValidation")
    if not isinstance(final_artifact_validation, dict):
        raise WorkerError(
            "invalid_metrics", "Final-artifact validation metrics are missing."
        )
    final_psnr = required_finite_number(
        final_artifact_validation, "psnrMean", "Final artifact"
    )
    final_ssim = required_finite_number(
        final_artifact_validation, "ssimMean", "Final artifact"
    )
    final_depth_ambiguity = required_finite_number(
        final_artifact_validation,
        "depthAmbiguityRelativeStdP50",
        "Final artifact",
    )
    final_depth_ambiguity_p95 = required_finite_number(
        final_artifact_validation,
        "depthAmbiguityRelativeStdP95",
        "Final artifact",
    )
    final_depth_ambiguity_fraction = required_finite_number(
        final_artifact_validation,
        "depthAmbiguityFractionAbove10Percent",
        "Final artifact",
    )
    for field in (
        "psnrMedian",
        "ssimMedian",
        "depthAmbiguityRelativeStdP95",
        "depthAmbiguityFractionAbove10Percent",
    ):
        required_finite_number(final_artifact_validation, field, "Final artifact")
    if int(final_artifact_validation.get("validationImages", -1)) != camera_count:
        raise WorkerError(
            "artifact_mismatch",
            "Final-artifact validation did not render every published camera.",
        )
    if (
        final_psnr < minimum_final_artifact_psnr
        or final_ssim < minimum_final_artifact_ssim
        or final_depth_ambiguity > maximum_depth_ambiguity
        or final_depth_ambiguity_p95 > maximum_depth_ambiguity_p95
        or final_depth_ambiguity_fraction > maximum_depth_ambiguity_fraction
        or final_psnr < float(train_metrics["psnrMean"])
        - maximum_final_psnr_regression
        or final_ssim < float(train_metrics["ssimMean"])
        - maximum_final_ssim_regression
    ):
        raise WorkerError(
            "quality_gate_failed",
            "The exact cleaned PLY failed its all-camera appearance or geometry gate.",
        )

    psnr = float(train_metrics["psnrMean"])
    ssim_mean = float(train_metrics["ssimMean"])
    if psnr < minimum_psnr or ssim_mean < minimum_ssim:
        raise WorkerError(
            "quality_gate_failed",
            f"Held-out quality is too low to publish (PSNR {psnr:.2f} dB, SSIM {ssim_mean:.3f}).",
        )
    depth_ambiguity_p50 = float(train_metrics["depthAmbiguityRelativeStdP50"])
    depth_ambiguity_p95 = float(train_metrics["depthAmbiguityRelativeStdP95"])
    depth_ambiguity_fraction = float(
        train_metrics["depthAmbiguityFractionAbove10Percent"]
    )
    if (
        depth_ambiguity_p50 > maximum_depth_ambiguity
        or depth_ambiguity_p95 > maximum_depth_ambiguity_p95
        or depth_ambiguity_fraction > maximum_depth_ambiguity_fraction
    ):
        raise WorkerError(
            "geometry_quality_gate_failed",
            "Composited depth layers exceed the verified mixed-layer limits "
            f"(median relative spread {depth_ambiguity_p50:.1%}, "
            f"p95 {depth_ambiguity_p95:.1%}, "
            f"{depth_ambiguity_fraction:.1%} above 10%).",
        )
    ply_quality = ply_metrics.get("quality", {})
    hard_artifact_gates = {
        "needleFraction": 0.05,
        "oversizedFraction": 0.02,
        "spatialOutlierFraction": 0.01,
        "nearTransparentFraction": 0.25,
    }
    for field, maximum in hard_artifact_gates.items():
        value = float(ply_quality.get(field, math.inf))
        if not math.isfinite(value) or value > maximum:
            raise WorkerError(
                "artifact_cleanup_gate_failed",
                f"Gaussian artifact {field} is {value:.3%}; the publish gate is {maximum:.3%}.",
            )
    warnings = [
        "Monocular reconstruction has unknown absolute scale until a measurement anchor is provided.",
        "The artifact contains observed appearance geometry, not collision-safe robotics geometry.",
        "Surfaces never seen by a source camera are not reconstructed.",
    ]
    if float(ply_quality.get("needleFraction", 0.0)) > 0.01:
        warnings.append("More than 1% of sampled Gaussians remain highly anisotropic.")
    if psnr >= 23.0 and ssim_mean >= 0.75:
        quality_tier = "preferred"
    elif psnr >= 18.0 and ssim_mean >= 0.60:
        quality_tier = "review-required"
        warnings.append(
            "Appearance clears the engineering gate but remains below the preferred benchmark tier; inspect every validation render."
        )
    else:
        quality_tier = "review-required"
    report = {
        "schema": "servo.reconstruction-validation/v1",
        "jobId": context.job_id,
        "validatedAt": utc_now(),
        "ply": ply_metrics,
        "pose": pose_metrics,
        "training": train_metrics,
        "qualityTier": quality_tier,
        "gates": {
            "minimumPsnr": minimum_psnr,
            "minimumSsim": minimum_ssim,
            "maximumDepthAmbiguityP50": maximum_depth_ambiguity,
            "maximumDepthAmbiguityP95": maximum_depth_ambiguity_p95,
            "maximumDepthAmbiguityFractionAbove10Percent": (
                maximum_depth_ambiguity_fraction
            ),
            "minimumFinalArtifactPsnr": minimum_final_artifact_psnr,
            "minimumFinalArtifactSsim": minimum_final_artifact_ssim,
            "maximumFinalPsnrRegression": maximum_final_psnr_regression,
            "maximumFinalSsimRegression": maximum_final_ssim_regression,
            "preferredPsnr": 23.0,
            "preferredSsim": 0.75,
            "artifactMaximums": hard_artifact_gates,
        },
        "warnings": warnings,
    }
    report_path = output / "validation.json"
    atomic_write_json(report_path, report)
    return {
        "gaussians": ply_metrics["vertexCount"],
        "shDegree": ply_metrics["shDegree"],
        "qualityTier": quality_tier,
        "psnrMean": psnr,
        "ssimMean": ssim_mean,
    }, [report_path]


def public_source_records(
    private_sources: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    allowed = (
        "kind",
        "bytes",
        "sha256",
        "width",
        "height",
        "durationSeconds",
        "frameRate",
        "frameCount",
        "codec",
        "cameraGroup",
    )
    public_sources: list[dict[str, Any]] = []
    source_ids_by_path: dict[str, str] = {}
    for index, source in enumerate(private_sources):
        private_path = Path(str(source["path"]))
        source_id = str(source.get("sourceId") or f"s{index:03d}")
        source_ids_by_path[str(private_path.resolve())] = source_id
        record = {key: source[key] for key in allowed if key in source}
        record["sourceId"] = source_id
        record["name"] = private_path.name
        public_sources.append(record)
    return public_sources, source_ids_by_path


def public_frame_records(
    private_frames: Sequence[dict[str, Any]],
    source_ids_by_path: dict[str, str],
) -> list[dict[str, Any]]:
    allowed = (
        "image",
        "cameraGroup",
        "sourceId",
        "timestampSeconds",
        "focus",
        "movement",
        "overlap",
        "matches",
        "selectionReason",
    )
    result: list[dict[str, Any]] = []
    for frame in private_frames:
        record = {key: frame[key] for key in allowed if key in frame}
        if "sourceId" not in record and "source" in frame:
            source_path = str(Path(str(frame["source"])).resolve())
            record["sourceId"] = source_ids_by_path.get(source_path, "unknown")
        result.append(record)
    return result


def publish_stage(context: JobContext) -> tuple[dict[str, Any], list[Path]]:
    output = context.stage_path("publish")
    output.mkdir(parents=True, exist_ok=True)
    attempt = output / f".attempt-{uuid.uuid4().hex}"
    attempt.mkdir(parents=True, exist_ok=False)
    source_ply = context.stage_path("train") / "world.ply"
    context.require_free_space(
        source_ply.stat().st_size + 1024**3,
        "Atomic world publication",
    )
    destination_ply = attempt / "world.ply"
    shutil.copy2(source_ply, destination_ply)
    bundle_files = {
        "validation": context.stage_path("validate") / "validation.json",
        "poseMetrics": context.stage_path("pose") / "pose-metrics.json",
        "trainingMetrics": context.stage_path("train") / "train-metrics.json",
        "heldoutMetrics": context.stage_path("train") / "heldout-metrics.json",
        "cameras": context.stage_path("train") / "cameras.json",
        "appearance": context.stage_path("train") / "appearance.json",
    }
    copied: dict[str, str] = {"ply": "world.ply"}
    for key, source in bundle_files.items():
        destination = attempt / source.name
        shutil.copy2(source, destination)
        copied[key] = destination.name
    private_sources = read_json(context.stage_path("hash") / "sources.json")
    public_sources, source_ids_by_path = public_source_records(
        private_sources["sources"]
    )
    atomic_write_json(
        attempt / "sources.json",
        {
            "schema": private_sources["schema"],
            "jobId": context.job_id,
            "sources": public_sources,
        },
    )
    copied["sources"] = "sources.json"
    private_frames = read_json(context.stage_path("extract") / "frames.json")
    public_frames = public_frame_records(
        private_frames["frames"], source_ids_by_path
    )
    atomic_write_json(
        attempt / "frames.json",
        {
            key: value
            for key, value in private_frames.items()
            if key != "frames"
        }
        | {"frames": public_frames},
    )
    copied["frames"] = "frames.json"
    private_training_config = read_json(
        context.stage_path("train") / "training-config.json"
    )
    public_training_fields = (
        "schema",
        "jobId",
        "profile",
        "pipelineRevision",
        "dataFactor",
        "maxSteps",
        "checkpointEvery",
        "packed",
        "shDegree",
        "representationType",
        "rasterizationMode",
        "eps2d",
        "absgrad",
        "growGrad2d",
        "coarseFactor",
        "coarseSteps",
        "finalFitSteps",
        "targetGaussians",
        "maxGaussians",
        "qualityGate",
        "appearanceCompensation",
        "appearanceLearningRate",
        "appearanceRegularization",
        "staticConfidenceMasks",
        "staticConfidenceMethod",
        "scaleRegularization",
        "sparseDepthWeight",
        "depthLayerVarianceWeight",
        "depthLayerVarianceEvery",
        "depthLayerVarianceStart",
        "maxReprojectionError",
        "maxVramGiB",
        "configurationHash",
    )
    public_training_config = {
        key: private_training_config[key]
        for key in public_training_fields
        if key in private_training_config
    }
    atomic_write_json(attempt / "training-config.json", public_training_config)
    copied["trainingConfig"] = "training-config.json"
    sparse_source = context.stage_path("pose") / "training" / "sparse"
    sparse_destination = attempt / "colmap-sparse"
    shutil.copytree(sparse_source, sparse_destination)
    copied["colmapSparse"] = "colmap-sparse"
    validation_source = context.stage_path("train") / "validation"
    if validation_source.is_dir():
        shutil.copytree(validation_source, attempt / "validation-renders")
        copied["validationRenders"] = "validation-renders"
    path_stress_source = context.stage_path("train") / "path-stress-validation"
    if path_stress_source.is_dir():
        shutil.copytree(
            path_stress_source, attempt / "path-stress-validation-renders"
        )
        copied["pathStressValidationRenders"] = (
            "path-stress-validation-renders"
        )
    final_validation_source = context.stage_path("train") / "final-validation"
    if final_validation_source.is_dir():
        shutil.copytree(
            final_validation_source, attempt / "final-validation-renders"
        )
        copied["finalValidationRenders"] = "final-validation-renders"
    training_metrics = read_json(context.stage_path("train") / "train-metrics.json")
    heldout_metrics = read_json(context.stage_path("train") / "heldout-metrics.json")
    training_config = public_training_config
    validation = read_json(context.stage_path("validate") / "validation.json")
    checkpoint_pointer = read_json(
        context.stage_path("train") / "checkpoints" / "last-good.json"
    )
    normalization = training_metrics["normalization"]
    manifest = {
        "schema": WORLD_SCHEMA,
        "worldId": context.job_id,
        "createdAt": utc_now(),
        "workerVersion": WORKER_VERSION,
        "pipelineRevision": PIPELINE_REVISION,
        "configurationHash": context.configuration_hash,
        "profile": context.profile.name,
        "representationType": REPRESENTATION_TYPE,
        "coordinateSystem": {
            "source": "COLMAP",
            "scale": "unknown-monocular",
            "units": "arbitrary",
            "normalizationMethod": normalization["method"],
            "normalizedFromColmap": normalization["colmapToNormalized"],
            "colmapFromNormalized": normalization["normalizedToColmap"],
        },
        "rasterization": training_metrics["rasterizationMode"],
        "rasterizationParameters": {
            "eps2d": training_metrics["eps2d"],
            "antialiasCompensation": training_metrics["rasterizationMode"]
            == "antialiased",
        },
        "provenance": "observed",
        "runtime": {
            **training_metrics["runtime"],
            "colmap": "4.1.1",
            "worker": WORKER_VERSION,
            "trainer": training_metrics["trainerVersion"],
        },
        "quality": {
            "tier": validation["qualityTier"],
            "heldout": {
                "psnrMean": training_metrics["psnrMean"],
                "ssimMean": training_metrics["ssimMean"],
                "depthAmbiguityRelativeStdP50": training_metrics[
                    "depthAmbiguityRelativeStdP50"
                ],
                "checkpointSha256": heldout_metrics["checkpoint"]["sha256"],
            },
            "finalArtifact": training_metrics["finalArtifactValidation"],
            "cleanup": training_metrics["cleanup"],
            "appearance": training_metrics["appearance"],
            "geometryRegularization": training_metrics[
                "geometryRegularization"
            ],
        },
        "training": {
            "steps": training_metrics["steps"],
            "densificationStrategy": training_metrics["densificationStrategy"],
            "resolutionSchedule": training_metrics["resolutionSchedule"],
            "configuration": training_config,
            "heldoutCheckpoint": heldout_metrics["checkpoint"],
            "lastVerifiedCheckpoint": checkpoint_pointer,
        },
        "worldSha256": training_metrics["worldSha256"],
        "artifacts": copied,
    }
    manifest["hashes"] = {
        path.relative_to(attempt).as_posix(): sha256_file(path)
        for path in sorted(attempt.rglob("*"))
        if path.is_file()
    }
    atomic_write_json(attempt / "world.json", manifest)

    audit_output = attempt / "path-audit"
    audit_tool = Path(__file__).with_name("servo_audit_world.py")
    run_process(
        context,
        "path-audit",
        [
            sys.executable,
            str(audit_tool),
            "--world",
            str(attempt),
            "--output",
            str(audit_output),
            "--width",
            "320",
            "--frames-per-segment",
            "2",
            "--fps",
            "30",
            "--reference-images",
            str(context.stage_path("pose") / "training" / "images"),
        ],
        environment=compiler_environment(),
    )
    audit_metrics_path = audit_output / "observed-path-audit.json"
    audit_video_path = audit_output / "observed-path-audit.mp4"
    if not audit_metrics_path.is_file() or not audit_video_path.is_file():
        raise WorkerError(
            "path_audit_failed",
            "The final PLY did not produce its mandatory observed-path audit.",
        )
    audit_metrics = read_json(audit_metrics_path)
    if (
        audit_metrics.get("schema") != "servo.gaussian-path-audit/v2"
        or audit_metrics.get("worldId") != context.job_id
        or audit_metrics.get("worldPlySha256")
        != training_metrics["worldSha256"]
        or int(audit_metrics.get("gaussians", -1))
        != int(training_metrics["gaussians"])
        or int(audit_metrics.get("shDegree", -1))
        != int(training_config["shDegree"])
    ):
        raise WorkerError(
            "path_audit_failed",
            "Observed-path audit provenance does not match the final PLY.",
        )
    support = audit_metrics.get("support")
    ambiguity = audit_metrics.get("depthAmbiguity")
    appearance_audit = audit_metrics.get("appearance")
    if (
        not isinstance(support, dict)
        or not isinstance(ambiguity, dict)
        or not isinstance(appearance_audit, dict)
    ):
        raise WorkerError(
            "path_audit_failed", "Observed-path audit metrics are incomplete."
        )

    def audit_number(record: dict[str, Any], field: str) -> float:
        value = record.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise WorkerError(
                "path_audit_failed",
                f"Observed-path audit metric {field} is missing or non-finite.",
            )
        return float(value)

    overall_support_minimum = audit_number(support, "overallMinimum")
    lower_support_minimum = audit_number(support, "lowerHalfMinimum")
    center_support_minimum = audit_number(support, "centerMinimum")
    audit_depth_p50 = audit_number(ambiguity, "relativeStdP50")
    audit_depth_p95 = audit_number(ambiguity, "relativeStdP95")
    audit_depth_fraction = audit_number(ambiguity, "fractionAboveTenPercent")
    audit_registered_psnr = audit_number(appearance_audit, "registeredPsnrMean")
    audit_registered_ssim = audit_number(appearance_audit, "registeredSsimMean")
    audit_registered_psnr_p10 = audit_number(
        appearance_audit, "registeredPsnrP10"
    )
    audit_registered_ssim_p10 = audit_number(
        appearance_audit, "registeredSsimP10"
    )
    audit_heldout_psnr = audit_number(appearance_audit, "heldoutPsnrMean")
    audit_heldout_ssim = audit_number(appearance_audit, "heldoutSsimMean")
    audit_gate = training_config["qualityGate"]
    if (
        appearance_audit.get("available") is not True
        or int(appearance_audit.get("registeredImages", -1))
        != int(training_metrics["finalArtifactValidation"]["validationImages"])
        or int(appearance_audit.get("heldoutImages", -1))
        != int(heldout_metrics["validationImages"])
        or audit_registered_psnr
        < float(audit_gate["minimumFinalArtifactPsnr"])
        or audit_registered_ssim
        < float(audit_gate["minimumFinalArtifactSsim"])
        or audit_heldout_psnr < float(audit_gate["minimumPsnr"])
        or audit_heldout_ssim < float(audit_gate["minimumSsim"])
        or audit_registered_psnr_p10
        < float(audit_gate["minimumExactPlyRegisteredPsnrP10"])
        or audit_registered_ssim_p10
        < float(audit_gate["minimumExactPlyRegisteredSsimP10"])
        or int(appearance_audit.get("maximumConsecutiveDegradedViews", -1))
        > int(audit_gate["maximumConsecutiveDegradedViews"])
        or overall_support_minimum < 0.90
        or lower_support_minimum < 0.85
        or center_support_minimum < 0.90
        or audit_depth_p50 > float(audit_gate["maximumDepthAmbiguityP50"])
        or audit_depth_p95 > float(audit_gate["maximumDepthAmbiguityP95"])
        or audit_depth_fraction
        > float(audit_gate["maximumDepthAmbiguityFractionAbove10Percent"])
    ):
        raise WorkerError(
            "path_audit_failed",
            "The exact final PLY failed its appearance, support, or mixed-depth "
            "gate between registered cameras; it will not be published.",
        )
    copied["pathAuditMetrics"] = "path-audit/observed-path-audit.json"
    copied["pathAuditVideo"] = "path-audit/observed-path-audit.mp4"
    manifest["artifacts"] = copied
    manifest["quality"]["pathAudit"] = {
        "appearance": appearance_audit,
        "support": support,
        "depthAmbiguity": ambiguity,
        "cameraPath": audit_metrics.get("cameraPath"),
        "render": audit_metrics.get("render"),
    }
    manifest["hashes"] = {
        path.relative_to(attempt).as_posix(): sha256_file(path)
        for path in sorted(attempt.rglob("*"))
        if path.is_file() and path.name != "world.json"
    }
    atomic_write_json(attempt / "world.json", manifest)
    final = output / "world"
    previous: Path | None = None
    if final.exists():
        previous = output / f"world.previous-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        os.replace(final, previous)
    try:
        os.replace(attempt, final)
    except Exception:
        if previous is not None and previous.exists() and not final.exists():
            os.replace(previous, final)
        raise
    previous_worlds = sorted(
        (path for path in output.glob("world.previous-*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for stale in previous_worlds[1:]:
        if stale.parent.resolve() == output.resolve():
            shutil.rmtree(stale)
    artifacts = [path for path in final.rglob("*") if path.is_file()]
    return {"worldPath": str(final), "artifactCount": len(artifacts)}, artifacts


STAGE_RUNNERS: dict[str, Callable[[JobContext], tuple[dict[str, Any], list[Path]]]] = {
    "hash": full_hash_stage,
    "extract": extract_stage,
    "pose": pose_stage,
    "train": train_stage,
    "validate": validate_stage,
    "publish": publish_stage,
}


def run_job(job_path: Path) -> int:
    job, profile = require_job(job_path)
    context = JobContext(job_path, job, profile)
    context.events.emit(
        "job_opened",
        state="running",
        profile=profile.name,
        jobPath=str(job_path.resolve()),
        pid=os.getpid(),
        processIdentity=process_identity(os.getpid()),
    )
    try:
        preflight = collect_preflight(verify_kernel=True)
        if not preflight["ready"]:
            missing = [item["name"] for item in preflight["dependencies"] if not item["ready"]]
            raise WorkerError("preflight_failed", "Native reconstruction dependencies are not ready: " + ", ".join(missing))
        source_bytes = sum(Path(source["path"]).stat().st_size for source in job["sources"])
        derived_estimate = estimated_derived_bytes(source_bytes, profile)
        existing_job_bytes = sum(
            path.stat().st_size
            for path in context.root.rglob("*")
            if path.is_file()
            and not any(
                marker in part
                for part in path.parts
                for marker in (".incompatible-", ".legacy-", "world.previous-")
            )
        )
        free_bytes = shutil.disk_usage(context.root).free
        required_capacity = derived_estimate + 2 * 1024**3
        if free_bytes + existing_job_bytes < required_capacity:
            raise WorkerError(
                "disk_full",
                f"This reconstruction profile needs about {format_bytes(required_capacity)} "
                f"of total job capacity; current artifacts plus free space provide "
                f"{format_bytes(free_bytes + existing_job_bytes)}.",
            )
        with context.acquire_lock():
            with exclusive_process_lock(
                local_runtime_root() / "gpu-worker.lock",
                "gpu_busy",
                "Another Servo reconstruction is already using the GPU.",
            ):
                for stage in STAGES:
                    context.check_cancel()
                    receipt = context.valid_receipt(stage)
                    if receipt is not None:
                        context.events.emit("stage_resumed", stage=stage, receipt=receipt)
                        continue
                    context.clear_uncommitted_stage(stage)
                    context.events.emit("stage_started", stage=stage)
                    started = time.monotonic()
                    metrics, artifacts = STAGE_RUNNERS[stage](context)
                    receipt = context.commit_receipt(stage, metrics, artifacts)
                    context.events.emit(
                        "stage_completed",
                        stage=stage,
                        elapsedSeconds=time.monotonic() - started,
                        metrics=metrics,
                        receipt=receipt,
                    )
                world = context.stage_path("publish") / "world"
                context.events.emit("job_completed", state="complete", worldPath=str(world))
                return 0
    except Cancelled as error:
        context.events.emit("job_cancelled", state="cancelled", code=error.code, message=str(error))
        return 130
    except WorkerError as error:
        context.events.emit(
            "job_failed",
            state="failed",
            code=error.code,
            message=str(error),
            details=error.details,
        )
        return 2
    except Exception as error:  # preserve unexpected faults as explicit worker failures
        context.events.emit(
            "job_failed",
            state="failed",
            code="internal_error",
            message=str(error),
            details=traceback.format_exc(),
        )
        return 3


def estimate(sources_path: Path, profile_name: str) -> dict[str, Any]:
    value = read_json(sources_path)
    sources = value.get("sources") if isinstance(value.get("sources"), list) else []
    profile = PROFILES.get(profile_name)
    if profile is None:
        raise WorkerError("invalid_profile", f"Unknown profile {profile_name}.")
    source_bytes = sum(int(source.get("sizeBytes", source.get("bytes", 0))) for source in sources if isinstance(source, dict))
    derived = estimated_derived_bytes(source_bytes, profile)
    return {
        "profile": profile.name,
        "sourceBytes": source_bytes,
        "estimatedDerivedBytes": derived,
        "estimatedDerivedText": format_bytes(derived),
        "expectedVramGiB": profile.expected_vram_gib,
        "note": (
            "Conservative peak estimate includes lossless selected frames, the "
            "protected held-out checkpoint, two resume checkpoints, an atomic "
            "checkpoint temporary, and atomic PLY publication."
        ),
    }


def compiled_gsplat_probe(environment: dict[str, str]) -> tuple[bool, dict[str, Any] | str]:
    probe = """
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

import gsplat
from gsplat import csrc

package_path = Path(gsplat.__file__).resolve()
environment_path = Path(sys.prefix).resolve()
try:
    package_path.relative_to(environment_path)
    managed = True
except ValueError:
    managed = False
print(json.dumps({
    "version": metadata.version("gsplat"),
    "packagePath": str(package_path),
    "extensionPath": str(Path(csrc.__file__).resolve()),
    "managed": managed,
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        return False, f"Compiled gsplat probe returned invalid output: {error}"
    ready = value.get("version") == "1.5.3" and value.get("managed") is True
    return ready, value


def provision_gsplat(requirement_path: Path, sink: EventSink) -> int:
    requirement_path = requirement_path.resolve()
    if not requirement_path.is_file():
        raise WorkerError("missing_requirement", f"gsplat source requirement is missing: {requirement_path}")
    environment = compiler_environment()
    ready, probe = compiled_gsplat_probe(environment)
    if ready:
        sink.emit("gsplat_provisioned", reused=True, **probe)
        return 0

    sink.emit(
        "gsplat_build_started",
        reused=False,
        requirement=str(requirement_path),
        maxJobs=int(environment.get("MAX_JOBS", "2")),
    )
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--force-reinstall",
        "--no-deps",
        "--no-build-isolation",
        "--progress-bar",
        "off",
        "--requirement",
        str(requirement_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        details = (result.stdout + "\n" + result.stderr).strip()
        raise WorkerError(
            "gsplat_build_failed",
            "The pinned native gsplat extension could not be built.",
            details=details[-16000:],
        )
    ready, probe = compiled_gsplat_probe(environment)
    if not ready:
        raise WorkerError(
            "gsplat_probe_failed",
            "gsplat built, but its managed native extension did not load.",
            details=str(probe),
        )
    sink.emit("gsplat_provisioned", reused=False, **probe)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=WORKER_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight", help="Report exact native dependency readiness as JSONL.")
    preflight.add_argument("--verify-kernel", action="store_true", help="Compile/run a tiny gsplat CUDA rasterization.")
    run = commands.add_parser("run", help="Run or resume a durable reconstruction job.")
    run.add_argument("--job", type=Path, required=True)
    estimate_parser = commands.add_parser("estimate", help="Estimate derived storage for a source manifest.")
    estimate_parser.add_argument("--sources", type=Path, required=True)
    estimate_parser.add_argument("--profile", choices=sorted(PROFILES), default="balanced-12gb")
    validate = commands.add_parser("validate-ply", help="Validate the Gaussian PLY interchange contract.")
    validate.add_argument("path", type=Path)
    provision = commands.add_parser(
        "provision-gsplat",
        help="Build the pinned native gsplat extension inside Servo's managed environment.",
    )
    provision.add_argument("--requirement", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    sink = EventSink()
    try:
        if arguments.command == "preflight":
            result = collect_preflight(arguments.verify_kernel)
            sink.emit("preflight_result", **result)
            return 0 if result["ready"] else 2
        if arguments.command == "run":
            return run_job(arguments.job)
        if arguments.command == "estimate":
            sink.emit("estimate_result", **estimate(arguments.sources, arguments.profile))
            return 0
        if arguments.command == "validate-ply":
            sink.emit("ply_validation_result", path=str(arguments.path.resolve()), **parse_ply_header(arguments.path))
            return 0
        if arguments.command == "provision-gsplat":
            return provision_gsplat(arguments.requirement, sink)
    except WorkerError as error:
        sink.emit("command_failed", code=error.code, message=str(error), details=error.details)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
