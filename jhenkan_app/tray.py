"""Windows tray icon with the same popup menu on either mouse button."""
import pystray
from pystray._util import win32


class TrayIcon(pystray.Icon):
    def _on_notify(self, wparam, lparam):
        # pystray has no public popup method. Reuse the Windows backend's
        # right-click handling so placement and menu actions stay identical.
        if lparam == win32.WM_LBUTTONUP:
            lparam = win32.WM_RBUTTONUP
        return super()._on_notify(wparam, lparam)
