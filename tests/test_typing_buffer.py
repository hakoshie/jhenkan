from types import SimpleNamespace

from jhenkan_app.typing_buffer import TypingBuffer


def press(buffer: TypingBuffer, name: str) -> None:
    buffer._on_press(SimpleNamespace(name=name))


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
