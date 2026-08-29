from __future__ import annotations

import threading

import keyboard

from .selection import foreground_window


class TypingBuffer:
    """Track the contiguous characters typed before the caret."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._window = 0
        self._paused = False
        self._hook = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._hook is None:
            self._hook = keyboard.on_press(self._on_press)

    def stop(self) -> None:
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None

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

    def _on_press(self, event: keyboard.KeyboardEvent) -> None:
        with self._lock:
            if self._paused:
                return
            window = foreground_window()
            if window != self._window:
                self._items.clear()
                self._window = window

            name = event.name or ""
            if keyboard.is_pressed("ctrl") or keyboard.is_pressed("alt") or keyboard.is_pressed("windows"):
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
