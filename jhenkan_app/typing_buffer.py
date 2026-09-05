from __future__ import annotations

import ctypes
import threading

import keyboard
import pyperclip

from .selection import foreground_window


def modifier_pressed(name: str) -> bool:
    """Read live state instead of potentially stale keyboard hook bookkeeping."""
    keys = {"ctrl": (0x11,), "alt": (0x12,), "windows": (0x5B, 0x5C)}
    return any(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000
               for key in keys[name])


class TypingBuffer:
    """Track the contiguous characters typed before the caret."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._window = 0
        self._paused = False
        self._hook = None
        self._mouse_thread: threading.Thread | None = None
        self._mouse_stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._hook is None:
            self._hook = keyboard.on_press(self._on_press)
        if self._mouse_thread is None or not self._mouse_thread.is_alive():
            self._mouse_stop.clear()
            self._mouse_thread = threading.Thread(
                target=self._watch_mouse_buttons,
                name="JHenkanMouseWatcher",
                daemon=True,
            )
            self._mouse_thread.start()

    def stop(self) -> None:
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None
        self._mouse_stop.set()
        if self._mouse_thread is not None:
            self._mouse_thread.join(timeout=0.2)
            self._mouse_thread = None

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._window = foreground_window()
            self._paused = False

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._window = foreground_window()

    def length(self) -> int:
        with self._lock:
            return len(self._items)

    def text(self) -> str:
        with self._lock:
            return "".join(self._items)

    def _on_mouse_click(self) -> None:
        with self._lock:
            if self._paused:
                return
            self._items.clear()
            self._window = foreground_window()

    def _watch_mouse_buttons(self) -> None:
        """Notice clicks without installing a hook that can disrupt dragging."""
        user32 = ctypes.windll.user32
        buttons = (0x01, 0x02, 0x04, 0x05, 0x06)
        was_down = {button: bool(user32.GetAsyncKeyState(button) & 0x8000) for button in buttons}
        while not self._mouse_stop.wait(0.02):
            for button in buttons:
                is_down = bool(user32.GetAsyncKeyState(button) & 0x8000)
                if is_down and not was_down[button]:
                    self._on_mouse_click()
                was_down[button] = is_down

    def _on_press(self, event: keyboard.KeyboardEvent) -> None:
        with self._lock:
            if self._paused:
                return
            window = foreground_window()
            if window != self._window:
                self._items.clear()
                self._window = window

            name = event.name or ""
            if modifier_pressed("ctrl"):
                if name == "v":
                    try:
                        self._items.extend(pyperclip.paste())
                    except pyperclip.PyperclipException:
                        # If the clipboard cannot be read, the editor still
                        # changed underneath us, so the old buffer is unsafe.
                        self._items.clear()
                elif name in {"x", "z", "y", "a"}:
                    # These shortcuts can replace the selection, move the
                    # caret, or rewrite text in ways the hook cannot observe.
                    self._items.clear()
                return
            if modifier_pressed("alt") or modifier_pressed("windows"):
                return
            if name == "backspace":
                if self._items:
                    self._items.pop()
                return
            if name == "enter":
                # IME uses Enter to commit composition. Keep the pending keys,
                # but do not count the Enter itself as a character.
                return
            if len(name) == 1:
                self._items.append(name)
                return
            if name in {"space", "tab", "decimal"}:
                self._items.append({"space": " ", "tab": "\t", "decimal": "."}[name])
                return
            if name in {
                "left", "right", "up", "down", "home", "end", "delete",
                "page up", "page down", "esc",
            }:
                self._items.clear()
