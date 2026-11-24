import pytest

pytest.importorskip("ApplicationServices")
from jhenkan_app import mac_text as mac


def test_explicit_selection_and_utf16_cursor():
    assert mac.target_range("上\r\n🤝romaji", (11, 0)) == ((3, 8), "🤝romaji")
    assert mac.target_range("あ🤝bc", (1, 3)) == ((1, 3), "🤝b")
    assert mac.target_range("あ🤝bc", (2, 1)) is None
    assert mac.target_range("abc", (5, 0)) is None
    assert mac.target_range("abc\n", (4, 0)) is None


def test_protected_field_is_never_captured(monkeypatch):
    element = object()
    access = []
    def attr(_element, name, _out):
        access.append(name)
        return 0, {"AXRole": "AXTextField", "AXSubrole": "AXSecureTextField"}.get(name)
    monkeypatch.setattr(mac, "focused_element", lambda: element)
    monkeypatch.setattr(mac.ax, "AXUIElementCopyAttributeValue", attr)
    assert mac.capture() is None
    assert access == ["AXRole", "AXSubrole"]


def test_caret_target_replaces_only_current_line(monkeypatch):
    element = object()
    state = {"AXValue": "first\nromaji other", mac.RANGE: (12, 0)}
    monkeypatch.setattr(mac, "focused_element", lambda: element)
    monkeypatch.setattr(mac, "allowed_element", lambda e: e is element)
    monkeypatch.setattr(mac, "same_control", lambda a, b: a is b)
    monkeypatch.setattr(mac, "editable", lambda *a: True)
    monkeypatch.setattr(mac, "selected_range", lambda _e: state[mac.RANGE])
    monkeypatch.setattr(mac, "CFRange", lambda a, b: (a, b))
    monkeypatch.setattr(mac.ax, "AXValueCreate", lambda _kind, span: span)
    def read(_el, key):
        if key == mac.SELECTED:
            start, length = state[mac.RANGE]
            return state["AXValue"][start:start + length]
        return state.get(key)
    def write(_el, key, value):
        if key == mac.RANGE:
            state[key] = value
        else:
            start, length = state[mac.RANGE]
            old = state["AXValue"]
            state["AXValue"] = old[:start] + value + old[start + length:]
        return 0
    monkeypatch.setattr(mac, "read", read)
    monkeypatch.setattr(mac.ax, "AXUIElementSetAttributeValue", write)
    captured = mac.capture()
    assert captured.source == "romaji"
    state[mac.RANGE] = (12, 1)
    assert not mac.apply(captured, "ローマ字")
    assert state["AXValue"] == "first\nromaji other"
    state[mac.RANGE] = (12, 0)
    assert mac.apply(captured, "ローマ字")
    assert state["AXValue"] == "first\nローマ字 other"


def test_new_input_does_not_reconvert_the_previous_result(monkeypatch):
    element = object()
    monkeypatch.setattr(mac, "same_control", lambda a, b: a is b)
    capture = mac.Capture(element, (7, 0), (0, 7), "漢字kana!", "漢字kana! suffix")
    narrowed = mac.since_last(capture, element, 2, "漢字 suffix")
    assert narrowed.source == "kana!"
    assert narrowed.replace == (2, 5)
    assert mac.since_last(capture, object(), 2, "漢字 suffix") is capture
    assert mac.since_last(capture, element, 2, "違う suffix") is capture
