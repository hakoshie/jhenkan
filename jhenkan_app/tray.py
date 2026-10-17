"""Windows tray icon with an approved native multi-size ICO when supplied."""
import ctypes
import pystray
from pystray._util import win32


class TrayIcon(pystray.Icon):
    def __init__(self, *args, icon_file=None, **kwargs):
        self.icon_file = str(icon_file) if icon_file is not None else None
        super().__init__(*args, **kwargs)

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

    def _on_notify(self, wparam, lparam):
        if lparam == win32.WM_LBUTTONUP:
            lparam = win32.WM_RBUTTONUP
        return super()._on_notify(wparam, lparam)
