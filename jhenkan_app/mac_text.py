"""Accessibility text edits: validate the same focus and UTF-16 range before writing."""
from dataclasses import dataclass

import ApplicationServices as ax
from CoreFoundation import CFEqual, CFRange
from AppKit import NSWorkspace


RANGE = "AXSelectedTextRange"
SELECTED = "AXSelectedText"
SUPPORTED_ROLES = {"AXTextField", "AXTextArea", "AXComboBox"}
MAX_INPUT = 8192


def read(element, name):
    error, value = ax.AXUIElementCopyAttributeValue(element, name, None)
    return None if error else value


def allowed_element(element):
    if element is None or read(element, "AXRole") not in SUPPORTED_ROLES:
        return False
    # Never read values/selection in secure fields. Fail closed on unexpected AX errors.
    error, subrole = ax.AXUIElementCopyAttributeValue(element, "AXSubrole", None)
    return (error in (0, ax.kAXErrorAttributeUnsupported, ax.kAXErrorNoValue)
            and subrole != "AXSecureTextField" and not read(element, "AXProtectedContent"))


def focused_element():
    running = NSWorkspace.sharedWorkspace().frontmostApplication()
    if not running:
        return None
    app = ax.AXUIElementCreateApplication(running.processIdentifier())
    ax.AXUIElementSetMessagingTimeout(app, 0.5)
    return read(app, "AXFocusedUIElement")


def selected_range(element):
    value = read(element, RANGE)
    if value is None:
        return None
    ok, span = ax.AXValueGetValue(value, ax.kAXValueCFRangeType, None)
    return tuple(span) if ok else None


def editable(element, name):
    error, can_set = ax.AXUIElementIsAttributeSettable(element, name, None)
    return not error and bool(can_set)


def target_range(value, span):
    """A selection wins; otherwise use the current line up to the insertion point."""
    start, length = span
    units = value.encode("utf-16-le")
    if start < 0 or length < 0 or (start + length) * 2 > len(units):
        return None
    try:
        if length:
            if length > MAX_INPUT:
                return None
            source = units[start * 2:(start + length) * 2].decode("utf-16-le")
            return (start, length), source
        prefix = units[:start * 2].decode("utf-16-le")
        line = prefix.replace("\r", "\n").rsplit("\n", 1)[-1]
        size = len(line.encode("utf-16-le")) // 2
        return ((start - size, size), line) if 0 < size <= MAX_INPUT else None
    except UnicodeError:
        return None


@dataclass
class Capture:
    element: object
    caret: tuple[int, int]
    replace: tuple[int, int]
    source: str
    value: str


def capture():
    element = focused_element()
    if not allowed_element(element):
        return None
    caret = selected_range(element)
    if caret is None or not editable(element, SELECTED) or (not caret[1] and not editable(element, RANGE)):
        return None
    value = read(element, "AXValue")
    if not isinstance(value, str):
        return None
    target = target_range(value, caret)
    if target is None or not target[1].strip():
        return None
    if caret[1] and read(element, SELECTED) != target[1]:
        return None
    return Capture(element, caret, *target, value)


def same_control(left, right):
    return left is not None and right is not None and bool(CFEqual(left, right))


def expected_value(captured, result):
    start, length = captured.replace
    raw = captured.value.encode("utf-16-le")
    return (raw[:start * 2] + result.encode("utf-16-le") + raw[(start + length) * 2:]).decode("utf-16-le")


def since_last(captured, last_control, boundary, previous_value):
    """Prefer only newly inserted text if the previous conversion is still in place."""
    if captured.caret[1] or not same_control(captured.element, last_control):
        return captured
    end = captured.caret[0]
    if not (captured.replace[0] < boundary < end):
        return captured
    old, new = (value.encode("utf-16-le") for value in (previous_value, captured.value))
    if boundary * 2 > len(old) or old[:boundary * 2] != new[:boundary * 2] or old[boundary * 2:] != new[end * 2:]:
        return captured
    new_text = new[boundary * 2:end * 2].decode("utf-16-le")
    if new_text.strip():
        return Capture(captured.element, captured.caret, (boundary, end - boundary), new_text, captured.value)
    return captured


def apply(captured, result):
    element = focused_element()
    if not same_control(element, captured.element) or not allowed_element(element):
        return False
    if selected_range(element) != captured.caret or read(element, "AXValue") != captured.value:
        return False
    moved = captured.replace != captured.caret
    if moved:
        box = ax.AXValueCreate(ax.kAXValueCFRangeType, CFRange(*captured.replace))
        if ax.AXUIElementSetAttributeValue(element, RANGE, box):
            return False
    if (same_control(focused_element(), element)
            and selected_range(element) == captured.replace
            and read(element, SELECTED) == captured.source
            and not ax.AXUIElementSetAttributeValue(element, SELECTED, result)):
        return read(element, "AXValue") == expected_value(captured, result)
    if moved and same_control(focused_element(), element) and selected_range(element) == captured.replace:
        box = ax.AXValueCreate(ax.kAXValueCFRangeType, CFRange(*captured.caret))
        ax.AXUIElementSetAttributeValue(element, RANGE, box)
    return False
