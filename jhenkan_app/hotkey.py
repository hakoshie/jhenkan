from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
HOTKEY_ID = 0x4A48


class GlobalHotkey:
    """A reliable Windows RegisterHotKey-backed Ctrl+J listener."""

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.error_code = 0
        self.ready = threading.Event()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.ready.clear()
        self.thread = threading.Thread(target=self._message_loop, daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2.0)
        if self.error_code:
            raise OSError(self.error_code, "Ctrl+JをWindowsへ登録できませんでした")

    def stop(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)
        self.thread = None
        self.thread_id = 0

    def _message_loop(self) -> None:
        self.thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
        registered = ctypes.windll.user32.RegisterHotKey(
            None, HOTKEY_ID, MOD_CONTROL | MOD_NOREPEAT, ord("J")
        )
        if not registered:
            self.error_code = int(ctypes.windll.kernel32.GetLastError())
            self.ready.set()
            return
        self.error_code = 0
        self.ready.set()
        message = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(
            ctypes.byref(message), None, 0, 0
        ) > 0:
            if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                self.callback()
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
