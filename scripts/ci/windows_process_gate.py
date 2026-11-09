"""Pre-user-code process gate for a dedicated, already resource-guarded worker.

Windows x64 only. The worker must exit on any failure so Windows kills its
debuggees. No caller may use this as an in-process debugger of an existing app.
"""
import ctypes as c
from pathlib import Path
import struct
import subprocess
import time


class GateError(RuntimeError):
    pass


class _CreateProcess(c.Structure):
    _fields_ = [(n, c.c_void_p) for n in ('file', 'process', 'thread', 'image')] + [
        ('offset', c.c_uint32), ('size', c.c_uint32)] + [
        (n, c.c_void_p) for n in ('tls', 'start', 'image_name')] + [('unicode', c.c_uint16)]


class _LoadDll(c.Structure):
    _fields_ = [('file', c.c_void_p), ('base', c.c_void_p), ('offset', c.c_uint32), ('size', c.c_uint32),
                ('name', c.c_void_p), ('unicode', c.c_uint16)]


class _EventInfo(c.Union):
    _fields_ = [('create', _CreateProcess), ('dll', _LoadDll), ('exit_code', c.c_uint32),
                ('raw', c.c_uint64 * 20)]


class _Event(c.Structure):
    _fields_ = [('kind', c.c_uint32), ('pid', c.c_uint32), ('tid', c.c_uint32), ('info', _EventInfo)]


def _api():
    if c.sizeof(c.c_void_p) != 8:
        raise GateError('Only the qualified Windows x64 process layout is supported')
    k = c.WinDLL('kernel32', use_last_error=True)
    sig = {
        'WaitForDebugEvent': ([c.POINTER(_Event), c.c_uint32], c.c_int),
        'ContinueDebugEvent': ([c.c_uint32, c.c_uint32, c.c_uint32], c.c_int),
        'DebugSetProcessKillOnExit': ([c.c_int], c.c_int),
        'ReadProcessMemory': ([c.c_void_p, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)], c.c_int),
        'GetFinalPathNameByHandleW': ([c.c_void_p, c.c_wchar_p, c.c_uint32, c.c_uint32], c.c_uint32),
        'CloseHandle': ([c.c_void_p], c.c_int),
        'LocalFree': ([c.c_void_p], c.c_void_p),
        'TerminateProcess': ([c.c_void_p, c.c_uint32], c.c_int),
        'IsWow64Process': ([c.c_void_p, c.POINTER(c.c_int)], c.c_int),
    }
    for name, (args, result) in sig.items():
        f = getattr(k, name)
        f.argtypes, f.restype = args, result
    n = c.WinDLL('ntdll')
    n.NtQueryInformationProcess.argtypes = [c.c_void_p, c.c_uint32, c.c_void_p, c.c_uint32, c.c_void_p]
    n.NtQueryInformationProcess.restype = c.c_long
    shell = c.WinDLL('shell32')
    shell.CommandLineToArgvW.argtypes = [c.c_wchar_p, c.POINTER(c.c_int)]
    shell.CommandLineToArgvW.restype = c.POINTER(c.c_wchar_p)
    return k, n, shell


def _read(k, process, address, size):
    if not address or not 0 < size <= 131072:
        raise GateError('Invalid remote process parameter size')
    data, got = c.create_string_buffer(size), c.c_size_t()
    if not k.ReadProcessMemory(process, address, data, size, c.byref(got)) or got.value != size:
        raise GateError(f'Cannot read suspended process parameters: {c.get_last_error()}')
    return data.raw


def _unicode(k, process, address):
    value = _read(k, process, address, 16)
    size, maximum = struct.unpack_from('<HH', value)
    pointer = struct.unpack_from('<Q', value, 8)[0]
    if size % 2 or not 0 < size <= maximum <= 65534:
        raise GateError('Invalid process Unicode string')
    return _read(k, process, pointer, size).decode('utf-16-le')


def _parameters(k, n, shell, process):
    wow = c.c_int()
    if not k.IsWow64Process(process, c.byref(wow)) or wow.value:
        raise GateError('Unqualified child process architecture')
    info = (c.c_void_p * 6)()
    if n.NtQueryInformationProcess(process, 0, c.byref(info), c.sizeof(info), None) < 0 or not info[1]:
        raise GateError('Cannot identify suspended process')
    params = struct.unpack('<Q', _read(k, process, info[1] + 0x20, 8))[0]
    command = _unicode(k, process, params + 0x70)
    cwd = _unicode(k, process, params + 0x38)
    count = c.c_int()
    args = shell.CommandLineToArgvW(command, c.byref(count))
    if not args or not 1 <= count.value <= 4096:
        raise GateError('Cannot decode child command line')
    try:
        argv = [args[i] for i in range(count.value)]
    finally:
        k.LocalFree(args)
    pointer = struct.unpack('<Q', _read(k, process, params + 0x80, 8))[0]
    block = bytearray()
    while len(block) < 131072:
        address = pointer + len(block)
        block.extend(_read(k, process, address, min(4096 - address % 4096, 131072-len(block))))
        end = next((i for i in range(0, len(block)-3, 2) if block[i:i+4] == b'\0\0\0\0'), None)
        if end is not None:
            env = {}
            for entry in block[:end].decode('utf-16-le').split('\0'):
                key, separator, value = entry.partition('=')
                if separator and key.upper() in ('CARGO_MANIFEST_DIR', 'CARGO_PKG_NAME'):
                    if key.upper() in env:
                        raise GateError('Duplicate Cargo identity in child environment')
                    env[key.upper()] = value
            return argv, cwd, env, int(info[5] or 0)
    raise GateError('Child environment exceeds inspection limit')


def _image(k, handle):
    buffer = c.create_unicode_buffer(32768)
    size = k.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not 0 < size < len(buffer):
        raise GateError('Cannot identify child executable from its image handle')
    name = buffer.value
    if name.startswith('\\\\?\\'):
        name = name[4:]
    return Path(name).resolve(strict=True)


def supervise(command, cwd, env, authorize, report, timeout_seconds=120):
    """Run only in a disposable worker; authorize each process before continuing it.

    The outer Windows Job owns resource limits and final descendant cleanup.
    authorize(image, argv, cwd, selected_env, parent_record) returns a role record.
    Full environment contents are never retained or logged.
    """
    k, n, shell = _api()
    processes, startup = {}, set()
    child = subprocess.Popen(command, cwd=cwd, env=env, creationflags=0x1)  # DEBUG_PROCESS, all descendants.
    deadline, root_code = time.monotonic()+timeout_seconds, None
    try:
        # The thread becomes a debugger only after CreateProcess(DEBUG_PROCESS).
        # Its initial create event is still suspended and has not been continued.
        if not k.DebugSetProcessKillOnExit(True):
            raise GateError(f'Cannot enforce debugger-exit cleanup: {c.get_last_error()}')
        while root_code is None or processes:
            if time.monotonic() >= deadline:
                raise GateError('Process gate deadline exceeded')
            event = _Event()
            if not k.WaitForDebugEvent(c.byref(event), 50):
                if c.get_last_error() == 121:
                    continue
                raise GateError(f'Cannot obtain a debug event: {c.get_last_error()}')
            status = 0x00010002  # DBG_CONTINUE
            if event.kind == 3:
                created = event.info.create
                try:
                    image = _image(k, created.file)
                    argv, working, selected, parent = _parameters(k, n, shell, created.process)
                    parent_record = processes.get(parent)
                    if event.pid != child.pid and parent_record is None:
                        raise GateError('Child has no authorized parent')
                    record = authorize(image, argv, working, selected, parent_record)
                    processes[event.pid] = record
                    report.append(dict(pid=event.pid, parent=parent, role=record['role'], decision='allowed_before_user_code'))
                except Exception as error:
                    report.append(dict(pid=event.pid, decision='denied_before_user_code', reason=str(error)))
                    raise
                finally:
                    if created.file:
                        k.CloseHandle(created.file)
            elif event.kind == 5:
                processes.pop(event.pid, None)
                if event.pid == child.pid:
                    root_code = event.info.exit_code
            elif event.kind == 6:
                if event.info.dll.file:
                    k.CloseHandle(event.info.dll.file)
            elif event.kind == 1:
                exception = struct.unpack_from('<I', bytes(event.info.raw))[0]
                if exception == 0x80000003 and event.pid not in startup:
                    startup.add(event.pid)
                else:
                    status = 0x80010001  # DBG_EXCEPTION_NOT_HANDLED: preserve program exceptions.
            elif event.kind == 9:
                raise GateError('Windows reported a debugger error')
            if not k.ContinueDebugEvent(event.pid, event.tid, status):
                raise GateError('Cannot continue an authorized debug event')
        child.wait(timeout=5)
        return root_code
    except BaseException:
        # Do not resume the denied child's pending create event. The worker must
        # exit immediately; kill-on-debugger-exit and the outer Job kill the tree.
        k.TerminateProcess(child._handle, 125)
        child.returncode = 125
        raise
    finally:
        child._handle.Close()
