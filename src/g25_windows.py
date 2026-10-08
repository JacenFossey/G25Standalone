"""Windows session-end handling for a background app without a console."""

from __future__ import annotations

import logging
import os
import threading

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_DESTROY = 0x0002
WM_CLOSE_MONITOR = 0x8001


class SessionNotifications:
    def __init__(self, request_stop, stopped_event: threading.Event):
        self.request_stop = request_stop
        self.stopped_event = stopped_event
        self.hwnd = None
        self.class_name = f"G25StandaloneSession-{os.getpid()}-{id(self)}"
        self._thread = None
        self._ready = threading.Event()
        self._error = None
        self._user32 = None

    def session_message(self, message: int, ending: bool) -> int | None:
        if message == WM_QUERYENDSESSION:
            return 1  # Allow shutdown, but do not stop if another app cancels it.
        if message == WM_ENDSESSION:
            if ending:
                self.request_stop("Windows session ending")
                # Windows may terminate us after this notification returns.
                self.stopped_event.wait(timeout=4)
            return 0
        return None

    def start(self) -> None:
        if os.name != "nt":
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Windows session notification window did not start")
        if self._error is not None:
            raise RuntimeError("Windows session notification window failed") from self._error

    def close(self) -> None:
        if self.hwnd and self._user32 is not None:
            self._user32.PostMessageW(self.hwnd, WM_CLOSE_MONITOR, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = user32
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            ctypes.c_size_t, ctypes.c_ssize_t,
        )

        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", callback_type),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        instance = kernel32.GetModuleHandleW(None)
        registered = False

        @callback_type
        def window_proc(hwnd, message, wparam, lparam):
            result = self.session_message(message, bool(wparam))
            if result is not None:
                return result
            if message == WM_CLOSE_MONITOR:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        try:
            definition = WindowClass()
            definition.lpfnWndProc = window_proc
            definition.hInstance = instance
            definition.lpszClassName = self.class_name
            if not user32.RegisterClassW(ctypes.byref(definition)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            # A hidden top-level window receives session broadcasts; a
            # message-only HWND_MESSAGE window would not receive them.
            self.hwnd = user32.CreateWindowExW(
                0, self.class_name, "G25Standalone", 0, 0, 0, 0, 0,
                None, None, instance, None,
            )
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except BaseException as exc:
            self._error = exc
            logging.getLogger("g25").exception("Windows session notification failure")
            self.request_stop("Windows session notification failure")
        finally:
            self._ready.set()
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
                self.hwnd = None
            if registered:
                user32.UnregisterClassW(self.class_name, instance)
