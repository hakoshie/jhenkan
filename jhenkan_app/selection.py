from __future__ import annotations

import ctypes
import logging
import time
import uuid
from dataclasses import dataclass

import keyboard
import pyperclip


logger = logging.getLogger("jhenkan")


@dataclass(frozen=True)
class CapturedText:
    text: str
    window: int
    clipboard_before: str
    delete_count: int = 0


def foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow())


def activate_window(window: int, wait_seconds: float = 0.15) -> bool:
    """Restore a captured foreground window, including after a topmost overlay."""
    user32 = ctypes.windll.user32
    if not user32.IsWindow(window):
        return False
    if foreground_window() == window:
        return True
    current_thread = int(ctypes.windll.kernel32.GetCurrentThreadId())
    foreground = foreground_window()
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
    attached = bool(foreground_thread and foreground_thread != current_thread)
    if attached:
        user32.AttachThreadInput(current_thread, foreground_thread, True)
    try:
        user32.BringWindowToTop(window)
        user32.SetForegroundWindow(window)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    time.sleep(wait_seconds)
    return foreground_window() == window


def _wait_for_hotkey_release(timeout: float = 2.0) -> None:
    """Avoid Ctrl+Shift+Home when Ctrl is still held after Ctrl+J."""
    deadline = time.monotonic() + timeout
    while ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000 and time.monotonic() < deadline:
        time.sleep(0.01)


def _copy_selection(marker: str, wait_seconds: float = 0.35) -> str | None:
    pyperclip.copy(marker)
    keyboard.send("ctrl+c")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        value = pyperclip.paste()
        if value != marker:
            return value
        time.sleep(0.015)
    return None


def capture_selection_or_line() -> CapturedText | None:
    """Capture selection, or select text from the caret back to line start."""
    _wait_for_hotkey_release()
    clipboard_before = pyperclip.paste()
    window = foreground_window()
    marker = f"__JHENKAN_{uuid.uuid4()}__"
    selected = _copy_selection(marker)
    if selected is not None and selected != "":
        return CapturedText(selected, window, clipboard_before)

    keyboard.send("shift+home")
    # Notepad can take a moment to expose the new selection to Ctrl+C.
    time.sleep(0.08)
    selected = _copy_selection(marker)
    if selected is None or selected == "":
        keyboard.send("right")
        pyperclip.copy(clipboard_before)
        return None
    return CapturedText(selected, window, clipboard_before)


def capture_selection_only() -> CapturedText | None:
    """Capture an explicit selection without changing the caret selection."""
    _wait_for_hotkey_release()
    clipboard_before = pyperclip.paste()
    window = foreground_window()
    marker = f"__JHENKAN_{uuid.uuid4()}__"
    selected = _copy_selection(marker)
    if selected is None or selected == "":
        pyperclip.copy(clipboard_before)
        return None
    return CapturedText(selected, window, clipboard_before)


def capture_buffered_text(text: str) -> CapturedText | None:
    """Create a replacement target from the invisible typing buffer."""
    if not text:
        return None
    _wait_for_hotkey_release()
    clipboard_before = pyperclip.paste()
    window = foreground_window()
    return CapturedText(text, window, clipboard_before, len(text))


def paste_replacement(captured: CapturedText, replacement: str) -> bool:
    """Paste only if focus stayed in the application where capture occurred."""
    if not activate_window(captured.window):
        logger.warning(
            "Could not focus target window: target=%d foreground=%d",
            captured.window,
            foreground_window(),
        )
        pyperclip.copy(replacement)
        return False
    logger.info("Replacing target: delete_count=%d", captured.delete_count)
    for _ in range(captured.delete_count):
        keyboard.press_and_release("backspace")
        time.sleep(0.012)
    time.sleep(0.08)
    pyperclip.copy(replacement)
    time.sleep(0.06)
    logger.info("Clipboard prepared: replacement_length=%d", len(replacement))
    keyboard.send("ctrl+v")
    time.sleep(0.35)
    logger.info("Replacement pasted")
    return True


def restore_clipboard(captured: CapturedText) -> None:
    pyperclip.copy(captured.clipboard_before)


def paste_text_to_window(window: int, text: str, clipboard_before: str) -> bool:
    """Focus a previously active window and paste a committed composition."""
    if not ctypes.windll.user32.IsWindow(window):
        pyperclip.copy(text)
        return False
    ctypes.windll.user32.SetForegroundWindow(window)
    time.sleep(0.12)
    if foreground_window() != window:
        pyperclip.copy(text)
        return False
    pyperclip.copy(text)
    keyboard.send("ctrl+v")
    time.sleep(0.12)
    pyperclip.copy(clipboard_before)
    return True
