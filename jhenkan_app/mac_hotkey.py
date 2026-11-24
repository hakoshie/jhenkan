"""Register two explicit shortcuts, without installing an input-monitoring hook."""
import ctypes as C


def fourcc(value):
    return int.from_bytes(value, "big")


class EventType(C.Structure):
    _fields_ = [("event_class", C.c_uint32), ("kind", C.c_uint32)]


class HotkeyId(C.Structure):
    _fields_ = [("signature", C.c_uint32), ("number", C.c_uint32)]


Handler = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.c_void_p, C.c_void_p)


class MacHotkeys:
    def __init__(self, callback):
        self.callback = callback
        self.handler = Handler(self.event)
        self.refs = []
        self.installed = C.c_void_p()
        self.lib = C.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        for name, result, params in (
            ("GetApplicationEventTarget", C.c_void_p, []),
            ("InstallEventHandler", C.c_int32, [C.c_void_p, Handler, C.c_uint32, C.POINTER(EventType), C.c_void_p, C.POINTER(C.c_void_p)]),
            ("RegisterEventHotKey", C.c_int32, [C.c_uint32, C.c_uint32, HotkeyId, C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p)]),
            ("GetEventParameter", C.c_int32, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32, C.c_void_p, C.POINTER(HotkeyId)]),
            ("UnregisterEventHotKey", C.c_int32, [C.c_void_p]),
            ("RemoveEventHandler", C.c_int32, [C.c_void_p]),
        ):
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, params

    def start(self):
        if self.installed:
            return
        target = self.lib.GetApplicationEventTarget()
        key_pressed = EventType(fourcc(b"keyb"), 5)
        if self.lib.InstallEventHandler(target, self.handler, 1, C.byref(key_pressed), None, C.byref(self.installed)):
            raise OSError("ショートカットを登録できませんでした。")
        for number, modifiers in ((1, 1 << 12), (2, (1 << 12) | (1 << 9))):
            ref = C.c_void_p()
            status = self.lib.RegisterEventHotKey(38, modifiers, HotkeyId(fourcc(b"JHKN"), number), target, 0, C.byref(ref))
            if status:
                self.stop()
                raise OSError("Ctrl+J または Ctrl+Shift+J を登録できませんでした。")
            self.refs.append(ref)

    def event(self, _handler, event, _data):
        value = HotkeyId()
        status = self.lib.GetEventParameter(event, fourcc(b"----"), fourcc(b"hkid"), None,
                                            C.sizeof(value), None, C.byref(value))
        if status or value.signature != fourcc(b"JHKN") or value.number not in (1, 2):
            return -9874  # eventNotHandledErr
        self.callback(value.number == 2)
        return 0

    def stop(self):
        for ref in self.refs:
            self.lib.UnregisterEventHotKey(ref)
        self.refs.clear()
        if self.installed:
            self.lib.RemoveEventHandler(self.installed)
            self.installed = C.c_void_p()
