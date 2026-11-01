"""Per-user Windows lifecycle control; never opens the physical wheel."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import time

WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 258
ERROR_ALREADY_EXISTS = 183
ERROR_FILE_NOT_FOUND = 2
SYNCHRONIZE = 0x00100000
MUTEX_MODIFY_STATE = 0x0001
EVENT_MODIFY_STATE = 0x0002


def state_directory() -> Path:
    if not os.environ.get('LOCALAPPDATA'):
        raise RuntimeError('LOCALAPPDATA is unavailable; run as the signed-in Windows user.')
    return Path(os.environ['LOCALAPPDATA']) / 'G25Standalone'


def object_names(folder: Path) -> tuple[str, str]:
    # Global names allow an installer to stop a process in another session of
    # the same user. Default Windows object ACLs restrict other users.
    identity = hashlib.sha256(str(folder.resolve()).casefold().encode()).hexdigest()[:24]
    prefix = 'Global\\G25Standalone.' + identity
    return prefix + '.mutex', prefix + '.stop'


def windows_api():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateMutexW': ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'OpenMutexW': ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'ReleaseMutex': ([wintypes.HANDLE], wintypes.BOOL),
        'CreateEventW': ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'OpenEventW': ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetEvent': ([wintypes.HANDLE], wintypes.BOOL),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = args
        function.restype = result
    return api


class WindowsRuntime:
    def __init__(self, folder: Path):
        self.api = windows_api()
        self.mutex_name, self.event_name = object_names(folder)
        self.mutex = None
        self.event = None
        self.owns_mutex = False

    def acquire(self) -> bool:
        self.mutex = self.api.CreateMutexW(None, True, self.mutex_name)
        error = ctypes.get_last_error()
        if not self.mutex:
            raise ctypes.WinError(error)
        if error == ERROR_ALREADY_EXISTS:
            # An old mutex may still exist while a stop command holds a handle.
            result = self.api.WaitForSingleObject(self.mutex, 0)
            if result == WAIT_TIMEOUT:
                return False
            if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
                raise ctypes.WinError()
        self.owns_mutex = True
        self.event = self.api.CreateEventW(None, True, False, self.event_name)
        if not self.event:
            raise ctypes.WinError()
        # We exclusively own the runtime. Clear a previous stop request if a
        # stop command still has the old event open during a restart.
        reset = self.api.ResetEvent
        reset.argtypes = [wintypes.HANDLE]
        reset.restype = wintypes.BOOL
        if not reset(self.event):
            raise ctypes.WinError()
        return True

    def request_stop(self) -> None:
        if not self.api.SetEvent(self.event):
            raise ctypes.WinError()

    def stop_requested(self) -> bool:
        result = self.api.WaitForSingleObject(self.event, 0)
        if result not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
            raise ctypes.WinError()
        return result == WAIT_OBJECT_0

    def close(self) -> None:
        if self.event:
            self.api.CloseHandle(self.event)
            self.event = None
        if self.mutex:
            if self.owns_mutex:
                self.api.ReleaseMutex(self.mutex)
            self.api.CloseHandle(self.mutex)
            self.mutex = None
            self.owns_mutex = False


def stop_running(folder: Path, timeout: float = 15.0) -> None:
    """Wait for graceful cleanup; never terminate a torque-owning process."""
    api = windows_api()
    mutex_name, event_name = object_names(folder)
    mutex = api.OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, False, mutex_name)
    if not mutex:
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            return
        raise ctypes.WinError(error)
    event = None
    owns_mutex = False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            result = api.WaitForSingleObject(mutex, 0)
            if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
                owns_mutex = True
                return
            if result != WAIT_TIMEOUT:
                raise ctypes.WinError()
            event = api.OpenEventW(EVENT_MODIFY_STATE, False, event_name)
            if event:
                break
            error = ctypes.get_last_error()
            if error != ERROR_FILE_NOT_FOUND:
                raise ctypes.WinError(error)
            time.sleep(0.02)
        if event:
            if not api.SetEvent(event):
                raise ctypes.WinError()
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            result = api.WaitForSingleObject(mutex, remaining)
            if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
                owns_mutex = True
                return
            if result != WAIT_TIMEOUT:
                raise ctypes.WinError()
        raise TimeoutError('G25Standalone did not stop safely. Close games and try again; files were not removed.')
    finally:
        if event:
            api.CloseHandle(event)
        if owns_mutex:
            api.ReleaseMutex(mutex)
        api.CloseHandle(mutex)
