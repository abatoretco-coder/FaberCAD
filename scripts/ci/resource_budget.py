"""Fail-closed resource bounds for the lightweight FABER checks (stdlib only).

Windows uses an aggregate Job Object commit limit. Linux requires an existing
enforced cgroup limit; RLIMIT_AS is deliberately not used as a substitute.
The opt-in WindowsWatchdog adds verified single-CPU affinity and sampled
working-set/system-headroom aborts. It does not authorize native compilation.
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
_JOB_AFFINITY = 0x10
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
    stop_reason: str | None = None
    peak_working_set_mb: float | None = None
    cpu_affinity_mask: int | None = None
    cleanup_verified: bool = False


@dataclass(frozen=True)
class WindowsWatchdog:
    """Opt-in single-CPU and sampled RAM/headroom checks, not a build runner."""
    working_set_mb: int = 768
    minimum_available_physical_mb: int = 4096
    minimum_available_commit_mb: int = 2048
    sample_interval_ms: int = 100


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


class _ProcessMemory(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
        (name, ctypes.c_size_t) for name in (
            "peak_working_set", "working_set", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32)] + [(name, ctypes.c_size_t) for name in (
        "commit_total", "commit_limit", "commit_peak", "physical_total", "physical_available", "system_cache",
        "kernel_total", "kernel_paged", "kernel_nonpaged", "page_size")] + [
        (name, ctypes.c_uint32) for name in ("handles", "processes", "threads")]


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
        "GetCurrentProcess": ([], handle),
        "GetProcessAffinityMask": ([handle, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)], boolean),
        "IsProcessInJob": ([handle, handle, ctypes.POINTER(boolean)], boolean),
        "WaitForSingleObject": ([handle, dword], dword),
        "K32GetProcessMemoryInfo": ([handle, ctypes.POINTER(_ProcessMemory), dword], boolean),
        "K32GetPerformanceInfo": ([ctypes.POINTER(_PerformanceInformation), dword], boolean),
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


def _system_headroom_mb(api):
    info = _PerformanceInformation()
    info.cb = ctypes.sizeof(info)
    if not api.K32GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise _windows_error("GetPerformanceInfo")
    if not info.page_size or info.commit_total > info.commit_limit or info.physical_available > info.physical_total:
        raise BudgetSetupError("Invalid system-memory telemetry")
    return (info.physical_available * info.page_size / _MIB,
            (info.commit_limit - info.commit_total) * info.page_size / _MIB)


def _headroom_reason(available, watchdog):
    if (not isinstance(available, (tuple, list)) or len(available) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in available)):
        raise BudgetSetupError("Invalid system-memory telemetry")
    physical, commit = available
    if physical < watchdog.minimum_available_physical_mb:
        return "available_physical_memory"
    if commit < watchdog.minimum_available_commit_mb:
        return "available_system_commit"
    return None


def _process_affinity(api, process):
    mask, system = ctypes.c_size_t(), ctypes.c_size_t()
    if not api.GetProcessAffinityMask(process, ctypes.byref(mask), ctypes.byref(system)) or not mask.value:
        raise _windows_error("GetProcessAffinityMask")
    return mask.value


class _WindowsJob:
    def __init__(self, memory_mb: int, watchdog: WindowsWatchdog | None = None):
        self.api = _windows_api()
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise _windows_error("CreateJobObject")
        limits = _ExtendedLimits()
        limits.basic.flags = _JOB_MEMORY | _KILL_ON_CLOSE
        limits.job_memory = memory_mb * _MIB
        self.affinity_mask = None
        if watchdog is not None:
            try:
                allowed = _process_affinity(self.api, self.api.GetCurrentProcess())
                self.affinity_mask = allowed & -allowed
                limits.basic.flags |= _JOB_AFFINITY
                limits.basic.affinity = self.affinity_mask
            except BaseException:
                self.close()
                raise
        if not self.api.SetInformationJobObject(self.handle, _EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = _windows_error("SetInformationJobObject")
            self.close()
            raise error
        if watchdog is not None:
            actual = _query_job(self.api, self.handle)
            required = _JOB_MEMORY | _KILL_ON_CLOSE | _JOB_AFFINITY
            if (actual is None or actual.basic.flags & required != required or actual.job_memory != limits.job_memory
                    or actual.basic.affinity != self.affinity_mask):
                self.close()
                raise BudgetSetupError("Job memory/affinity limits could not be verified")

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

    def pids(self):
        capacity = 64
        while capacity <= 4096:
            class ProcessIds(ctypes.Structure):
                _fields_ = [("assigned", ctypes.c_uint32), ("count", ctypes.c_uint32), ("ids", ctypes.c_size_t * capacity)]
            info = ProcessIds()
            ok = self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(info), ctypes.sizeof(info), None)
            if ok and info.count == info.assigned and info.count <= capacity:
                return list(info.ids[:info.count])
            if not ok and ctypes.get_last_error() != 234:
                raise _windows_error("Query Job process IDs")
            capacity = max(capacity * 2, info.assigned)
        raise BudgetSetupError("Job process list exceeded telemetry capacity")

    def working_set_mb(self):
        total = 0
        for pid in self.pids():
            # Query and synchronize only: do not change individual process limits.
            process = self.api.OpenProcess(0x0400 | 0x00100000, False, pid)
            if not process:
                error = ctypes.get_last_error()
                if error == 87 or pid not in self.pids():  # A sampled process has already exited.
                    continue
                raise BudgetSetupError(f"OpenProcess for telemetry: Windows error {error}")
            try:
                in_job = ctypes.c_int()
                if not self.api.IsProcessInJob(process, self.handle, ctypes.byref(in_job)):
                    raise _windows_error("IsProcessInJob")
                if not in_job.value or self.api.WaitForSingleObject(process, 0) == 0:
                    continue  # Exited or PID reused outside this Job.
                try:
                    affinity = _process_affinity(self.api, process)
                except BudgetSetupError:
                    if self.api.WaitForSingleObject(process, 0) == 0:
                        continue
                    raise
                if affinity != self.affinity_mask:
                    raise BudgetSetupError("A Job process has unexpected CPU affinity")
                memory = _ProcessMemory()
                memory.cb = ctypes.sizeof(memory)
                if not self.api.K32GetProcessMemoryInfo(process, ctypes.byref(memory), memory.cb):
                    if self.api.WaitForSingleObject(process, 0) == 0:
                        continue
                    raise _windows_error("GetProcessMemoryInfo")
                total += memory.working_set
            finally:
                self.api.CloseHandle(process)
        return total / _MIB

    def stop_and_drain(self):
        deadline = time.monotonic() + 5
        processes = []
        try:
            # Job membership can reach zero before process teardown releases its
            # working-directory handle. Also wait on the owned process objects.
            for pid in self.pids():
                process = self.api.OpenProcess(0x0400 | 0x00100000, False, pid)
                if not process:
                    error = ctypes.get_last_error()
                    if error == 87 or pid not in self.pids():
                        continue
                    raise BudgetSetupError(f"OpenProcess for cleanup: Windows error {error}")
                in_job = ctypes.c_int()
                if not self.api.IsProcessInJob(process, self.handle, ctypes.byref(in_job)):
                    self.api.CloseHandle(process)
                    raise _windows_error("Cleanup membership")
                if in_job.value:
                    processes.append(process)
                else:
                    self.api.CloseHandle(process)
            self.terminate()
            for process in processes:
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                if self.api.WaitForSingleObject(process, remaining_ms) != 0:
                    raise BudgetSetupError("Owned process exit could not be verified")
            while self.pids():
                if time.monotonic() >= deadline:
                    raise BudgetSetupError("Job descendant cleanup could not be verified")
                time.sleep(.01)
        finally:
            for process in processes:
                self.api.CloseHandle(process)

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


def _watch_windows(job, child, deadline, watchdog):
    peak_ws = 0.0
    reason = None
    while True:
        started = time.monotonic()
        if started >= deadline:
            reason = "timeout"
            break
        try:
            reason = _headroom_reason(_system_headroom_mb(job.api), watchdog)
            working_set = job.working_set_mb()
            peak_ws = max(peak_ws, working_set)
            if working_set > watchdog.working_set_mb:
                reason = "working_set"
        except (BudgetSetupError, OSError) as error:
            reason = f"telemetry_unavailable: {error}"
        if reason is not None or child.poll() is not None:
            break
        time.sleep(max(0, min(started + watchdog.sample_interval_ms / 1000, deadline) - time.monotonic()))
    code = child.poll() if reason is None else (124 if reason == "timeout" else 125)
    job.stop_and_drain()
    child.wait(timeout=5)
    peak = job.peak_mb()
    if peak is None:
        code, reason = 125, "telemetry_unavailable: Job commit peak"
    return code, reason == "timeout", peak, reason, peak_ws, job.affinity_mask, True


def _run_windows(command, cwd, deadline, memory_mb, env, watchdog=None):
    job = _WindowsJob(memory_mb, watchdog)
    child = None
    try:
        if watchdog is not None:
            reason = _headroom_reason(_system_headroom_mb(job.api), watchdog)
            if reason:
                raise BudgetSetupError(f"Preflight refused: {reason}")
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", _BOOTSTRAP, json.dumps(command, ensure_ascii=True)], cwd=cwd, env=env, stdin=subprocess.PIPE)
        job.assign(child.pid)
        if watchdog is not None:
            reason = _headroom_reason(_system_headroom_mb(job.api), watchdog)
            if reason or job.working_set_mb() > watchdog.working_set_mb:
                raise BudgetSetupError(f"Preflight refused before command release: {reason or 'working_set'}")
        if time.monotonic() >= deadline:
            if watchdog is not None:
                job.stop_and_drain()
                child.wait(timeout=5)
                return 124, True, job.peak_mb(), "timeout", 0.0, job.affinity_mask, True
            job.terminate()
            child.wait(timeout=5)
            return 124, True, job.peak_mb()
        child.stdin.write(b"1")
        child.stdin.close()
        child.stdin = None
        if watchdog is not None:
            return _watch_windows(job, child, deadline, watchdog)
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


def _validate_watchdog(watchdog, memory_mb):
    if not isinstance(watchdog, WindowsWatchdog):
        raise ValueError("watchdog must be a WindowsWatchdog")
    for name in ("working_set_mb", "minimum_available_physical_mb", "minimum_available_commit_mb", "sample_interval_ms"):
        value = getattr(watchdog, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
    # Shared resident pages are counted in every process working set. This metric
    # is independent of Job commit; both have their own unchanged global ceiling.
    if not 1 <= watchdog.working_set_mb <= MAX_MEMORY_MB:
        raise ValueError("working_set_mb must be positive and at most the global memory ceiling")
    if watchdog.minimum_available_physical_mb < 0 or watchdog.minimum_available_commit_mb < 0:
        raise ValueError("System headroom thresholds cannot be negative")
    if not 1 <= watchdog.sample_interval_ms <= 100:
        raise ValueError("sample_interval_ms must be between 1 and 100")


def run_bounded(command: list[str], cwd: Path, timeout_seconds: float = MAX_TIMEOUT_SECONDS,
                memory_mb: int = MAX_MEMORY_MB, env: dict | None = None,
                watchdog: WindowsWatchdog | None = None) -> Outcome:
    """Run with aggregate memory and elapsed-time bounds; inherit output, never use a shell.

    Linux callers must enter a constrained cgroup first (for example a transient
    systemd service with MemoryMax, MemorySwapMax=0, RuntimeMaxSec and KillMode).
    Setup failure raises BudgetSetupError without starting the supplied command.
    An optional WindowsWatchdog has no unsupported-platform fallback. Working
    sets are sampled, not an absolute aggregate physical-RAM cap.
    """
    _validate_memory(memory_mb)
    if watchdog is not None:
        _validate_watchdog(watchdog, memory_mb)
        if sys.platform != "win32":
            raise BudgetSetupError("CPU/RAM watchdog currently requires Windows; no unguarded fallback")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be finite, above zero and at most {MAX_TIMEOUT_SECONDS}")
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\0" in arg for arg in command) or not command[0]:
        raise ValueError("command must be a nonempty list of string arguments without NUL")
    cwd = Path(cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("cwd must be a directory")
    started = time.monotonic()
    deadline = started + timeout_seconds
    extra = ()
    if sys.platform == "win32":
        code, timed_out, peak, *extra = _run_windows(command, cwd, deadline, memory_mb, env, watchdog)
    elif sys.platform.startswith("linux"):
        code, timed_out, peak = _run_linux(command, cwd, deadline, memory_mb, env)
    else:
        raise BudgetSetupError("Resource guard supports only Windows Jobs and Linux cgroups")
    return Outcome(code, timed_out, memory_mb, time.monotonic() - started, peak, *extra)
