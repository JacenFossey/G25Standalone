"""Hidden top-level window for graceful Windows sign-out/shutdown notification."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import threading

LOG = logging.getLogger('g25.session')
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016


class SessionShutdown:
    def __init__(self, request_stop):
        self.request_stop = request_stop
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.error = None
        self.hwnd = None
        self.thread = threading.Thread(target=self._pump, name='Windows-session-events', daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError('Windows session notification window did not start.')
        if self.error:
            raise self.error

    def close(self) -> None:
        # Called only after the wheel-owning service has completed its cleanup.
        self.finished.set()
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self.thread.join(timeout=5)

    def _pump(self) -> None:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user32 = user32
        procedure = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                       ctypes.c_size_t, ctypes.c_ssize_t)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', procedure),
                        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                        ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HANDLE),
                        ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HANDLE),
                        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

        signatures = {
            'RegisterClassW': ([ctypes.POINTER(WNDCLASS)], wintypes.ATOM),
            'UnregisterClassW': ([wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL),
            'CreateWindowExW': ([wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HWND),
            'DefWindowProcW': ([wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'DestroyWindow': ([wintypes.HWND], wintypes.BOOL),
            'PostMessageW': ([wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t], wintypes.BOOL),
            'PostQuitMessage': ([ctypes.c_int], None),
            'GetMessageW': ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], ctypes.c_int),
            'TranslateMessage': ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
            'DispatchMessageW': ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
        }
        for name, (args, result) in signatures.items():
            function = getattr(user32, name)
            function.argtypes, function.restype = args, result
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        instance = kernel32.GetModuleHandleW(None)
        class_name = 'G25Standalone.Session.' + str(os.getpid())
        registered = False

        @procedure
        def window_proc(hwnd, message, wparam, lparam):
            if message == WM_QUERYENDSESSION or (message == WM_ENDSESSION and wparam):
                try:
                    LOG.info('Windows session ending; requesting neutralization.')
                    self.request_stop()
                    # Give the main loop time to neutralize before Windows ends
                    # the session. Shutdown remains best-effort, not guaranteed
                    # under forced termination or a blocked HID driver.
                    self.finished.wait(3)
                except Exception:
                    LOG.exception('Session stop request failed.')
                return 1 if message == WM_QUERYENDSESSION else 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        try:
            window_class = WNDCLASS()
            window_class.lpfnWndProc = window_proc
            window_class.hInstance = instance
            window_class.lpszClassName = class_name
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError()
            registered = True
            # A message-only HWND would NOT receive Windows session broadcasts.
            self.hwnd = user32.CreateWindowExW(0, class_name, 'G25Standalone', 0,
                                               0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise ctypes.WinError()
            self.ready.set()
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError()
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.error = exc
            self.ready.set()
            LOG.exception('Windows session notification failed.')
        finally:
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
                self.hwnd = None
            if registered:
                user32.UnregisterClassW(class_name, instance)
