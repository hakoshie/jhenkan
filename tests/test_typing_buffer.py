from types import SimpleNamespace

from jhenkan_app.typing_buffer import TypingBuffer


def press(buffer: TypingBuffer, name: str) -> None:
    buffer._on_press(SimpleNamespace(name=name))


def click(buffer: TypingBuffer) -> None:
    buffer._on_mouse_click()


def test_tracks_typing_and_backspace(monkeypatch):
    monkeypatch.setattr("jhenkan_app.typing_buffer.foreground_window", lambda: 10)
    monkeypatch.setattr("jhenkan_app.typing_buffer.keyboard.is_pressed", lambda _key: False)
    buffer = TypingBuffer()

    for name in ("n", "i", "h", "o", "n", "g", "o"):
        press(buffer, name)
    press(buffer, "backspace")

    assert buffer.length() == 6
    assert buffer.text() == "nihong"


def test_navigation_and_window_change_clear_buffer(monkeypatch):
    current_window = [10]
    monkeypatch.setattr(
        "jhenkan_app.typing_buffer.foreground_window", lambda: current_window[0]
    )
    monkeypatch.setattr("jhenkan_app.typing_buffer.keyboard.is_pressed", lambda _key: False)
    buffer = TypingBuffer()

    press(buffer, "a")
    press(buffer, "left")
    assert buffer.length() == 0

    press(buffer, "b")
    current_window[0] = 20
    press(buffer, "c")
    assert buffer.length() == 1


def test_mouse_click_clears_buffer(monkeypatch):
    monkeypatch.setattr("jhenkan_app.typing_buffer.foreground_window", lambda: 10)
    monkeypatch.setattr("jhenkan_app.typing_buffer.keyboard.is_pressed", lambda _key: False)
    buffer = TypingBuffer()

    press(buffer, "a")
    click(buffer)
    assert buffer.text() == ""


def test_mouse_click_does_not_clear_paused_buffer(monkeypatch):
    monkeypatch.setattr("jhenkan_app.typing_buffer.foreground_window", lambda: 10)
    monkeypatch.setattr("jhenkan_app.typing_buffer.keyboard.is_pressed", lambda _key: False)
    buffer = TypingBuffer()

    press(buffer, "a")
    buffer.pause()
    click(buffer)

    assert buffer.text() == "a"


def test_enter_is_ignored_without_clearing_buffer(monkeypatch):
    monkeypatch.setattr("jhenkan_app.typing_buffer.foreground_window", lambda: 10)
    monkeypatch.setattr("jhenkan_app.typing_buffer.keyboard.is_pressed", lambda _key: False)
    buffer = TypingBuffer()

    press(buffer, "a")
    press(buffer, "b")
    press(buffer, "enter")

    assert buffer.text() == "ab"


def test_clipboard_paste_is_included_in_buffer(monkeypatch):
    pressed = {"ctrl": False}
    monkeypatch.setattr("jhenkan_app.typing_buffer.foreground_window", lambda: 10)
    monkeypatch.setattr(
        "jhenkan_app.typing_buffer.keyboard.is_pressed",
        lambda key: pressed.get(key, False),
    )
    monkeypatch.setattr("jhenkan_app.typing_buffer.pyperclip.paste", lambda: "paste")
    buffer = TypingBuffer()

    press(buffer, "a")
    pressed["ctrl"] = True
    press(buffer, "v")
    pressed["ctrl"] = False
    press(buffer, "b")

    assert buffer.text() == "apasteb"

    press(buffer, "backspace")
    assert buffer.text() == "apaste"


def test_editing_shortcut_clears_stale_buffer(monkeypatch):
    pressed = {"ctrl": False}
    monkeypatch.setattr("jhenkan_app.typing_buffer.foreground_window", lambda: 10)
    monkeypatch.setattr(
        "jhenkan_app.typing_buffer.keyboard.is_pressed",
        lambda key: pressed.get(key, False),
    )
    buffer = TypingBuffer()

    press(buffer, "a")
    pressed["ctrl"] = True
    press(buffer, "z")

    assert buffer.text() == ""
