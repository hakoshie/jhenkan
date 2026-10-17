"""Windows tray icon with an approved native multi-size ICO when supplied."""
import ctypes
import pystray
from pystray._util import win32


class TrayIcon(pystray.Icon):
    def __init__(self, *args, icon_file=None, **kwargs):
        self.icon_file = str(icon_file) if icon_file is not None else None
        self._notification_icon_handle = None
        super().__init__(*args, **kwargs)
        # pystray swallows unlisted messages after attaching its window dispatcher.
        self._message_handlers[0x007F] = lambda w, l: (  # WM_GETICON
            self._notification_icon_handle if w == 1 else self._icon_handle)
        self._message_handlers[0x0080] = lambda w, l: win32.DefWindowProc(  # WM_SETICON
            self._hwnd, 0x0080, w, l)

    def _assert_icon_handle(self):
        if not self.icon_file:
            return super()._assert_icon_handle()
        if self._icon_handle:
            return
        # Load the exact native-size bitmap rather than resampling a large glyph.
        size = ctypes.windll.user32.GetSystemMetrics(49) or 16  # SM_CXSMICON
        self._icon_handle = win32.LoadImage(
            None, self.icon_file, win32.IMAGE_ICON, size, size, win32.LR_LOADFROMFILE)
        if not self._icon_handle:
            raise OSError('The approved tray icon could not be loaded')

    def _assert_notification_icon_handle(self):
        if not self._notification_icon_handle:
            size = ctypes.windll.user32.GetSystemMetrics(11) or 32  # SM_CXICON
            self._notification_icon_handle = win32.LoadImage(
                None, self.icon_file, win32.IMAGE_ICON, size, size, win32.LR_LOADFROMFILE)
            if not self._notification_icon_handle:
                raise OSError('The approved notification icon could not be loaded')

    def _notify(self, message, title=None):
        if not self.icon_file:
            return super()._notify(message, title)
        self._assert_notification_icon_handle()
        self._message(win32.NIM_MODIFY, win32.NIF_INFO,
            szInfo=message, szInfoTitle=title or self.title or '',
            dwInfoFlags=0x04 | 0x20,  # NIIF_USER | NIIF_LARGE_ICON
            hBalloonIcon=self._notification_icon_handle)

    def _create_window(self, atom):
        hwnd = super()._create_window(atom)
        self._set_window_icons(hwnd)
        return hwnd

    def _set_window_icons(self, hwnd):
        if self.icon_file and hwnd:
            self._assert_icon_handle()
            self._assert_notification_icon_handle()
            # Windows may use the sender window's icons in the notification header.
            send = ctypes.windll.user32.SendMessageW
            send.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
            send(hwnd, 0x0080, 0, self._icon_handle)  # WM_SETICON, ICON_SMALL
            send(hwnd, 0x0080, 1, self._notification_icon_handle)  # ICON_BIG

    def _update_icon(self):
        # pystray replaces native handles when the tray becomes visible/reappears.
        super()._update_icon()
        self._set_window_icons(self._hwnd)
        self._set_window_icons(self._menu_hwnd)

    def _release_icon(self):
        if self._notification_icon_handle:
            win32.DestroyIcon(self._notification_icon_handle)
            self._notification_icon_handle = None
        super()._release_icon()

    def _on_notify(self, wparam, lparam):
        if lparam == win32.WM_LBUTTONUP:
            lparam = win32.WM_RBUTTONUP
        return super()._on_notify(wparam, lparam)


def set_app_identity(app_id):
    """Keep this app's sender identity separate from the shared Python runtime."""
    function = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    function.argtypes = (ctypes.c_wchar_p,)
    function.restype = ctypes.c_long
    result = function(app_id)
    if result < 0:
        raise OSError('Windows application identity could not be set')
