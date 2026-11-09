"""Fail-closed resource bounds for the lightweight FABER checks (stdlib only).

Windows uses an aggregate Job Object commit limit. Linux requires an existing
enforced cgroup limit; RLIMIT_AS is deliberately not used as a substitute.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time


MAX_TIMEOUT_SECONDS = 180
MAX_MEMORY_MB = 1024
_MIB = 1024 * 1024
_JOB_MEMORY = 0x200
_KILL_ON_CLOSE = 0x2000
_EXTENDED_LIMITS = 9


class BudgetSetupError(RuntimeError):
    """No command may start when a required resource guard is unavailable."""


@dataclass(frozen=True)
class Outcome:
    returncode: int
    timed_out: bool
    memory_limit_mb: int
    elapsed_seconds: float
    # Raw Windows job accounting; a refused charge can raise this counter above
    # the configured cap. Do not clamp it or treat it as successful retained RAM.
    peak_memory_mb: float | None = None


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_processes", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes"
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


def _windows_api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], handle),
        "SetInformationJobObject": ([handle, dword, ctypes.c_void_p, dword], boolean),
        "QueryInformationJobObject": ([handle, dword, ctypes.c_void_p, dword, ctypes.c_void_p], boolean),
        "OpenProcess": ([dword, boolean, dword], handle),
        "AssignProcessToJobObject": ([handle, handle], boolean),
        "TerminateJobObject": ([handle, dword], boolean),
        "CloseHandle": ([handle], boolean),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def _windows_error(operation: str) -> BudgetSetupError:
    return BudgetSetupError(f"{operation}: Windows error {ctypes.get_last_error()}")


def _query_job(api, handle) -> _ExtendedLimits | None:
    limits = _ExtendedLimits()
    if not api.QueryInformationJobObject(handle, _EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits), None):
        return None
    return limits


class _WindowsJob:
    def __init__(self, memory_mb: int):
        self.api = _windows_api()
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise _windows_error("CreateJobObject")
        limits = _ExtendedLimits()
        limits.basic.flags = _JOB_MEMORY | _KILL_ON_CLOSE
        limits.job_memory = memory_mb * _MIB
        if not self.api.SetInformationJobObject(self.handle, _EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = _windows_error("SetInformationJobObject")
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        # Assignment requires PROCESS_SET_QUOTA | PROCESS_TERMINATE.
        process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise _windows_error("OpenProcess for Job assignment")
        try:
            if not self.api.AssignProcessToJobObject(self.handle, process):
                raise _windows_error("AssignProcessToJobObject")
        finally:
            self.api.CloseHandle(process)

    def peak_mb(self) -> float | None:
        limits = _query_job(self.api, self.handle)
        return None if limits is None else limits.peak_job_memory / _MIB

    def terminate(self) -> None:
        if self.handle and not self.api.TerminateJobObject(self.handle, 124):
            raise _windows_error("TerminateJobObject")

    def close(self) -> None:
        if self.handle:
            handle, self.handle = self.handle, None
            # KILL_ON_JOB_CLOSE also cleans up descendants after a successful command.
            if not self.api.CloseHandle(handle):
                raise _windows_error("CloseHandle for Job")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mount_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def _linux_memory_limit_bytes() -> int | None:
    try:
        groups = [line.split(":", 2) for line in _read_text(Path("/proc/self/cgroup")).splitlines()]
        mounts = _read_text(Path("/proc/self/mountinfo")).splitlines()
    except OSError:
        return None
    limits = []
    for line in mounts:
        before, separator, after = line.partition(" - ")
        fields, detail = before.split(), after.split()
        if not separator or len(fields) < 5 or len(detail) < 3:
            continue
        v2 = detail[0] == "cgroup2"
        v1 = detail[0] == "cgroup" and "memory" in detail[2].split(",")
        if not (v2 or v1):
            continue
        mount_root = PurePosixPath(_mount_path(fields[3]))
        mount = PurePosixPath(_mount_path(fields[4]))
        if not mount.is_absolute() or not mount_root.is_absolute():
            continue
        for group in groups:
            if len(group) != 3 or not ((v2 and group[0] == "0" and not group[1]) or (v1 and "memory" in group[1].split(","))):
                continue
            membership = PurePosixPath(group[2])
            if not membership.is_absolute() or ".." in membership.parts:
                continue
            try:
                relative = membership.relative_to(mount_root)
            except ValueError:
                continue  # Ambiguous/unrelated mount: refuse rather than trust its cap.
            directory = mount.joinpath(*relative.parts)
            leaf = directory
            filename = "memory.max" if v2 else "memory.limit_in_bytes"
            while True:
                try:
                    text = _read_text(Path(str(directory / filename))).strip()
                    if text != "max":
                        value = int(text)
                        # v1 represents an unlimited cap with a huge page-aligned integer.
                        hierarchical = v2 or directory == leaf
                        if not hierarchical:
                            try:
                                hierarchical = _read_text(Path(str(directory / "memory.use_hierarchy"))).strip() == "1"
                            except OSError:
                                pass
                        if 0 < value < (1 << 60) and hierarchical:
                            limits.append(value)
                except (OSError, ValueError):
                    pass
                if directory == mount:
                    break
                directory = directory.parent
    return min(limits) if limits else None


def current_memory_limit_mb() -> float | None:
    """Read the real aggregate guard inherited by this process, never an env marker."""
    if sys.platform == "win32":
        limits = _query_job(_windows_api(), None)
        if limits is None or not limits.basic.flags & _JOB_MEMORY or not limits.job_memory:
            return None
        return limits.job_memory / _MIB
    if sys.platform.startswith("linux"):
        limit = _linux_memory_limit_bytes()
        return None if limit is None else limit / _MIB
    return None


def _validate_memory(memory_mb: int) -> None:
    if isinstance(memory_mb, bool) or not isinstance(memory_mb, int) or not 1 <= memory_mb <= MAX_MEMORY_MB:
        raise ValueError(f"memory_mb must be an integer from 1 to {MAX_MEMORY_MB}")


def ensure_guarded(memory_mb: int = MAX_MEMORY_MB) -> float:
    """Fail closed unless the current process already has a sufficiently small cap."""
    _validate_memory(memory_mb)
    limit = current_memory_limit_mb()
    if limit is None or limit > memory_mb:
        raise BudgetSetupError(f"No enforced aggregate memory cap at or below {memory_mb} MiB")
    return limit


# -I -S ignores Python environment hooks. No supplied command is launched before
# the parent assigns this tiny, waiting process to the already-limited Job.
_BOOTSTRAP = """import json, subprocess, sys
if sys.stdin.buffer.read(1) != b'1':
    sys.exit(125)
sys.exit(subprocess.call(json.loads(sys.argv[1])))
"""


def _run_windows(command, cwd, deadline, memory_mb, env):
    job = _WindowsJob(memory_mb)
    child = None
    try:
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", _BOOTSTRAP, json.dumps(command, ensure_ascii=True)], cwd=cwd, env=env, stdin=subprocess.PIPE)
        job.assign(child.pid)
        if time.monotonic() >= deadline:
            job.terminate()
            child.wait(timeout=5)
            return 124, True, job.peak_mb()
        child.stdin.write(b"1")
        child.stdin.close()
        child.stdin = None
        try:
            returncode = child.wait(timeout=max(0, deadline - time.monotonic()))
            timed_out = False
        except subprocess.TimeoutExpired:
            job.terminate()
            child.wait(timeout=5)
            returncode, timed_out = 124, True
        return returncode, timed_out, job.peak_mb()
    finally:
        try:
            job.close()
        finally:
            if child is not None:
                if child.stdin is not None:
                    try:
                        child.stdin.close()
                    except BrokenPipeError:
                        pass
                try:
                    if child.poll() is None:
                        try:
                            child.kill()  # Assignment failure leaves only a waiting bootstrap.
                        except OSError:
                            if child.poll() is None:
                                raise
                    child.wait(timeout=5)
                finally:
                    # CPython's Windows Popen handle otherwise waits for collection,
                    # including when an exception traceback keeps the child alive.
                    child._handle.Close()


def _run_linux(command, cwd, deadline, memory_mb, env):
    ensure_guarded(memory_mb)
    if time.monotonic() >= deadline:
        return 124, True, None
    child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        try:
            return child.wait(timeout=max(0, deadline - time.monotonic())), False, None
        except subprocess.TimeoutExpired:
            return 124, True, None
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)


def run_bounded(command: list[str], cwd: Path, timeout_seconds: float = MAX_TIMEOUT_SECONDS,
                memory_mb: int = MAX_MEMORY_MB, env: dict | None = None) -> Outcome:
    """Run with aggregate memory and elapsed-time bounds; inherit output, never use a shell.

    Linux callers must enter a constrained cgroup first (for example a transient
    systemd service with MemoryMax, MemorySwapMax=0, RuntimeMaxSec and KillMode).
    Setup failure raises BudgetSetupError without starting the supplied command.
    """
    _validate_memory(memory_mb)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be finite, above zero and at most {MAX_TIMEOUT_SECONDS}")
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\0" in arg for arg in command) or not command[0]:
        raise ValueError("command must be a nonempty list of string arguments without NUL")
    cwd = Path(cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("cwd must be a directory")
    started = time.monotonic()
    deadline = started + timeout_seconds
    if sys.platform == "win32":
        code, timed_out, peak = _run_windows(command, cwd, deadline, memory_mb, env)
    elif sys.platform.startswith("linux"):
        code, timed_out, peak = _run_linux(command, cwd, deadline, memory_mb, env)
    else:
        raise BudgetSetupError("Resource guard supports only Windows Jobs and Linux cgroups")
    return Outcome(code, timed_out, memory_mb, time.monotonic() - started, peak)
