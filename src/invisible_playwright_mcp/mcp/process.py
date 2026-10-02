"""Whether a process is still running, asked the way each system can answer.

⛔ ONE PLACE, BECAUSE THE OBVIOUS SPELLING KILLS ON WINDOWS. `os.kill(pid, 0)`
is the POSIX question "does it exist", and on Windows the same call is
`TerminateProcess` with exit code 0: asking would end the process asked about.
A profile lock and an upload snapshot both need the question, so it is written
once, with the Windows answer read from the process table instead.
"""
from __future__ import annotations

import os


def alive(pid: int) -> bool:
    """True while a process with this id is running."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _alive_on_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _alive_on_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    query_limited_information, still_active = 0x1000, 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        # Access denied means it exists and belongs to somebody else.
        return ctypes.get_last_error() == 5
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
