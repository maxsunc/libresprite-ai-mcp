"""Test-only byte-pipe adapter for the existing native regression client. GPLv2."""
import ctypes
from ctypes import wintypes
import time
import os


class WindowsPipeClient:
    def __init__(self, path):
        import msvcrt
        self.path = str(path)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        deadline = time.monotonic() + 15
        while True:
            handle = create(self.path, 0xC0000000, 0, None, 3, 0, None)
            if handle != wintypes.HANDLE(-1).value:
                break
            error = ctypes.get_last_error()
            if error != 231 or time.monotonic() >= deadline:
                raise ctypes.WinError(error)
            time.sleep(.01)  # The GUI timer must observe disconnect before reconnect.
        self.file = os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY), "r+b", buffering=0)
        self.handle = handle
        self.peek = kernel.PeekNamedPipe
        self.peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        self.peek.restype = wintypes.BOOL
        self.timeout = 15
        self.pending = b""

    def settimeout(self, seconds):
        self.timeout = seconds

    def getpeername(self):
        return self.path

    def makefile(self, mode):
        assert mode == "rb"
        return self

    def close(self):
        self.file.close()

    def sendall(self, data):
        # shortcut: test writes are synchronous, use overlapped I/O for stalled-GUI tests.
        remaining = memoryview(data)
        while remaining:
            count = self.file.write(remaining)
            if not count:
                raise ConnectionError("Pipe closed during test request")
            remaining = remaining[count:]

    def readline(self):
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self.pending:
            available = wintypes.DWORD()
            if not self.peek(self.handle, None, 0, None, ctypes.byref(available), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if available.value:
                part = self.file.read(min(available.value, 65536))
                if not part:
                    raise ConnectionError("Pipe closed during test response")
                self.pending += part
                if len(self.pending) > 8 * 1024 * 1024:
                    raise ValueError("Test response exceeds the bridge limit")
            elif time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for the native editor")
            else:
                time.sleep(.005)
        line, self.pending = self.pending.split(b"\n", 1)
        return line + b"\n"
