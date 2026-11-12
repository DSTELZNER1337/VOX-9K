"""Detect ownership pipe loss without blocking Windows native startup."""
import os
import sys

def wait_for_parent_eof():
    if os.name != "nt":
        while sys.stdin.buffer.read(1):
            pass
        return
    # Blocking stdin readers reproduced native-extension import stalls on Windows.
    # This dedicated ownership handle has no other readers; poll without consuming data.
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
    peek=kernel32.PeekNamedPipe
    peek.argtypes=[wintypes.HANDLE,wintypes.LPVOID,wintypes.DWORD,wintypes.LPVOID,wintypes.LPVOID,wintypes.LPVOID]
    peek.restype=wintypes.BOOL
    handle=msvcrt.get_osfhandle(sys.stdin.fileno())
    import time
    while True:
        if not peek(handle,None,0,None,None,None):
            error=ctypes.get_last_error()
            if error in (109,232):
                return
            raise ctypes.WinError(error)
        time.sleep(0.25)
