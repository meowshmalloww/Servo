"""Ownership-safe lifecycle management for the packaged CARLA server."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import ctypes
from datetime import datetime, timezone
from pathlib import Path

from ...hashing import sha256_file
from ..session_store import atomic_write_json
from .discovery import DiscoveryResult, find_free_port, port_block_available

try:
    import psutil
except ImportError:  # pragma: no cover - optional diagnostic dependency
    psutil = None


def process_alive(pid: int, expected_executable: str | None = None) -> bool:
    if pid <= 0:
        return False
    if psutil is not None:
        try:
            process = psutil.Process(pid)
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return False
            if expected_executable:
                return os.path.normcase(process.exe()) == os.path.normcase(str(Path(expected_executable).resolve()))
            return True
        except (psutil.Error, OSError):
            return False
    try:
        os.kill(pid, 0)
        return expected_executable is None
    except OSError:
        return False


class CarlaProcessManager:
    def __init__(self, runtime_root: Path, record_path: Path) -> None:
        self.runtime_root = runtime_root.resolve()
        self.record_path = record_path
        self.process: subprocess.Popen | None = None
        self._windows_job = None

    def _attach_windows_kill_job(self) -> None:
        """Contain Unreal's bootstrapper and shipping child in one owned job.

        CARLA's top-level executable launches ``CarlaUE4-Win64-Shipping.exe``.
        Killing only the bootstrapper leaves the shipping server holding RPC,
        streaming, and secondary ports. A kill-on-close job also cleans both
        processes if the Python worker crashes or is force-closed.
        """
        if os.name != "nt" or self.process is None:
            return

        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(self.process._handle))):
            kernel32.CloseHandle(job)
            raise ctypes.WinError(ctypes.get_last_error())
        self._windows_job = job

    def read_record(self) -> dict | None:
        if not self.record_path.is_file():
            return None
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    def verify_record(self) -> bool:
        record = self.read_record()
        if not record:
            return False
        executable = record.get("executable", "")
        if not process_alive(int(record.get("pid", 0)), executable):
            return False
        path = Path(executable)
        return path.is_file() and sha256_file(str(path)) == record.get("executable_sha256")

    def launch(self, discovery: DiscoveryResult, *, require_rendering: bool, rpc_port: int | None = None, traffic_manager_port: int | None = None) -> dict:
        if not discovery.ready or not discovery.executable:
            raise RuntimeError("cannot launch CARLA: runtime discovery is not ready")
        if self.verify_record():
            record = self.read_record()
            if record and bool(record.get("require_rendering")) == require_rendering:
                return record
            raise RuntimeError("a healthy owned CARLA server exists with a different rendering profile")
        rpc_port = rpc_port or find_free_port()
        traffic_manager_port = traffic_manager_port or find_free_port()
        while traffic_manager_port in {rpc_port, rpc_port + 1, rpc_port + 2}:
            traffic_manager_port = find_free_port()
        if not port_block_available(rpc_port, 3):
            raise RuntimeError(
                f"CARLA RPC port block {rpc_port}-{rpc_port + 2} is unavailable; "
                "RPC, streaming, and multi-GPU router ports must all be free"
            )
        logs = self.record_path.parent / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stdout_path, stderr_path = logs / "carla.stdout.log", logs / "carla.stderr.log"
        args = [
            discovery.executable,
            f"-carla-rpc-port={rpc_port}",
            f"-carla-streaming-port={rpc_port + 1}",
            f"-carla-secondary-port={rpc_port + 2}",
            "-quality-level=Epic" if require_rendering else "-quality-level=Low",
            "-nosound",
        ]
        if require_rendering:
            args.extend(["-RenderOffScreen", "-windowed", "-ResX=640", "-ResY=360"])
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        stdout = stdout_path.open("ab")
        stderr = stderr_path.open("ab")
        try:
            self.process = subprocess.Popen(
                args,
                cwd=str(self.runtime_root),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
                shell=False,
            )
            self._attach_windows_kill_job()
        finally:
            stdout.close()
            stderr.close()
        record = {
            "schema_name": "servo.carla-server/v1",
            "pid": self.process.pid,
            "executable": discovery.executable,
            "executable_sha256": discovery.executable_sha256,
            "version": discovery.client_version,
            "rpc_port": rpc_port,
            "traffic_manager_port": traffic_manager_port,
            "launch_arguments": args[1:],
            "launched_at": datetime.now(timezone.utc).isoformat(),
            "state": "launching",
            "last_health_result": None,
            "require_rendering": require_rendering,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
        }
        atomic_write_json(self.record_path, record)
        return record

    def record_health(self, healthy: bool, server_version: str | None, detail: str = "") -> dict:
        record = self.read_record()
        if not record:
            raise RuntimeError("CARLA server ownership record is missing")
        record["state"] = "healthy" if healthy else "unhealthy"
        record["last_health_result"] = {
            "healthy": healthy,
            "server_version": server_version,
            "detail": detail,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(self.record_path, record)
        return record

    def stop(self, graceful_timeout_s: float = 10.0) -> bool:
        record = self.read_record()
        if not record:
            return True
        pid = int(record.get("pid", 0))
        executable = record.get("executable")
        if not process_alive(pid, executable):
            record["state"] = "stale"
            atomic_write_json(self.record_path, record)
            return True
        if os.name == "nt" and psutil is not None:
            # The packaged bootstrapper owns a separate Unreal shipping child.
            # Stop the verified process tree, not only the tiny launcher.
            process = psutil.Process(pid)
            descendants = process.children(recursive=True)
            for child in reversed(descendants):
                child.terminate()
            process.terminate()
            _, alive = psutil.wait_procs([*descendants, process], timeout=graceful_timeout_s)
            for remaining in alive:
                remaining.kill()
            psutil.wait_procs(alive, timeout=5)
            if self.process and self.process.pid == pid:
                self.process.wait(timeout=5)
        elif self.process and self.process.pid == pid:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=graceful_timeout_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        elif psutil is not None:
            process = psutil.Process(pid)
            process.terminate()
            try:
                process.wait(timeout=graceful_timeout_s)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        else:
            raise RuntimeError("cannot safely stop an owned detached process without psutil")
        record["state"] = "stopped"
        record["stopped_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(self.record_path, record)
        if self._windows_job is not None:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._windows_job)
            self._windows_job = None
        return True
