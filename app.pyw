from __future__ import annotations

import ctypes
import gc
import logging
import queue
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as Item

from jhenkan_app.config import Settings, has_credentials, config_path
from jhenkan_app.hotkey import GlobalHotkey
from jhenkan_app.selection import (
    capture_buffered_text,
    capture_selection_only,
    capture_selection_or_line,
)
from jhenkan_app.typing_buffer import TypingBuffer
from jhenkan_app.tray import TrayIcon, set_app_identity
from jhenkan_app.ui import convert_selected, edit_settings, gui_thread_lifetime


ICON_PATH = Path(__file__).with_name('assets') / 'jhenkan-d-kan.ico'
MUTEX_NAME = "Local\\JHenkan-7f44f5c6"
LOG_PATH = Path(__file__).with_name("jhenkan.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("jhenkan")


def single_instance() -> object | None:
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or ctypes.windll.kernel32.GetLastError() == 183:
        return None
    return handle


def tray_image() -> Image.Image:
    with Image.open(ICON_PATH.with_suffix('.png')) as image:
        return image.copy()


class App:
    def __init__(self) -> None:
        self.settings = Settings.load()
        self.paused = False
        self.busy = threading.Lock()
        self.global_hotkey: GlobalHotkey | None = None
        self.last_conversion: tuple[str, str, int] | None = None
        self.typing_buffer = TypingBuffer()
        self.actions: queue.Queue[str] = queue.Queue()
        self.icon = TrayIcon(
            "JHenkan",
            tray_image(),
            "JHenkan — Ctrl+Jで変換",
            icon_file=ICON_PATH,
            menu=pystray.Menu(
                Item("一時停止", self.toggle_pause, checked=lambda _item: self.paused),
                Item("設定", lambda _icon, _item: self.actions.put("settings")),
                Item("終了", lambda _icon, _item: self.actions.put("quit")),
            ),
        )

    def notify(self, message: str, title: str = "JHenkan") -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def toggle_pause(self, _icon: object, _item: object) -> None:
        self.paused = not self.paused
        self.icon.title = "JHenkan — 一時停止中" if self.paused else "JHenkan — Ctrl+Jで変換"
        self.icon.update_menu()

    def hotkey(self, alternate: bool = False) -> None:
        logger.info("%s received", "Ctrl+Shift+J" if alternate else "Ctrl+J")
        if self.paused or not self.busy.acquire(blocking=False):
            logger.info("Ctrl+J ignored: paused=%s busy=%s", self.paused, self.busy.locked())
            return
        threading.Thread(target=self.convert_current, args=(alternate,), daemon=True).start()

    def convert_current(self, alternate: bool = False) -> None:
        queued = False
        self.typing_buffer.pause()
        try:
            captured = capture_selection_only()
            if alternate:
                last = self.last_conversion
                if not captured or not last or captured.text != last[1] or captured.window != last[2]:
                    self.notify("直前の変換結果を選択してCtrl+Shift+Jを押してください。")
                    return
                self.actions.put(("convert", captured, last[0], last[1]))
                queued = True
                return
            if not captured:
                buffered_text = self.typing_buffer.text()
                logger.info("Typing buffer contains %d characters", len(buffered_text))
                captured = capture_buffered_text(buffered_text)
            if not captured:
                # A long-running Windows keyboard hook can occasionally miss
                # keystrokes (notably in browser text fields). Read the text
                # before the caret directly instead of reporting a false
                # "no conversion target" error.
                logger.info("Typing buffer empty; falling back to caret line capture")
                captured = capture_selection_or_line()
            if not captured:
                logger.info("No text captured")
                self.notify("変換対象がありません。文字を入力してからCtrl+Jを押してください。")
                return
            logger.info("Captured %d characters", len(captured.text))
            if not has_credentials(self.settings):
                self.notify(
                    "設定画面でChatGPTにログインしてください" if self.settings.provider == "chatgpt"
                    else f"設定画面で{self.settings.provider} APIキーを登録してください",
                    "JHenkan: 設定が必要です",
                )
                self.actions.put("settings")
                return
            self.actions.put(("convert", captured))
            queued = True
        except Exception as exc:
            logger.exception("Capture failed")
            self.notify(str(exc)[:220], "JHenkan: 変換エラー")
        finally:
            if not queued:
                self.typing_buffer.resume()
            self.busy.release()

    def run(self) -> None:
        with gui_thread_lifetime():
            self._run()

    def _run(self) -> None:
        if "--connect-chatgpt" in sys.argv:
            edit_settings(self.settings, connect_chatgpt=True)
            self.settings = Settings.load()
            gc.collect()
        elif not has_credentials(self.settings) and not config_path().exists():
            edit_settings(self.settings, first_run=True)
            self.settings = Settings.load()
            gc.collect()
        self.icon.run_detached()
        self.typing_buffer.start()
        self.register_hotkey()
        self.notify(
            "起動しました。Ctrl+Jで未確定入力、選択範囲は直接再変換できます。"
            if has_credentials(self.settings)
            else "常駐を開始しました。変換するにはトレイの設定からログイン・APIキー登録を行ってください。"
        )
        while True:
            # Tcl interpreters and variables must be finalized by this thread.
            gc.collect()
            try:
                action = self.actions.get(timeout=1.0)
            except queue.Empty:
                continue
            if action == "quit":
                break
            if isinstance(action, tuple) and action[0] == "convert":
                self.unregister_hotkey()
                converted = False
                try:
                    converted = convert_selected(
                        self.settings, action[1], self.notify,
                        source=action[2] if len(action) > 2 else None,
                        previous=action[3] if len(action) > 3 else None,
                        on_converted=self.remember_conversion,
                    )
                except Exception as exc:
                    logger.exception("Conversion window failed")
                    self.notify(str(exc)[:220], "JHenkan: 画面エラー")
                finally:
                    if converted:
                        self.typing_buffer.clear()
                    self.typing_buffer.resume()
                    self.register_hotkey()
            if action == "settings":
                self.typing_buffer.pause()
                try:
                    if edit_settings(self.settings):
                        self.register_hotkey()
                except Exception:
                    logger.exception("Settings window failed")
                    self.notify("設定画面を開けませんでした。常駐は継続しています。")
                finally:
                    self.typing_buffer.clear()
                    self.typing_buffer.resume()
        self.unregister_hotkey()
        self.typing_buffer.stop()
        self.icon.stop()

    def remember_conversion(self, source, result, window) -> None:
        self.last_conversion = (source, result, window)

    def register_hotkey(self) -> None:
        self.unregister_hotkey()
        self.global_hotkey = GlobalHotkey(self.hotkey, lambda: self.hotkey(alternate=True))
        try:
            self.global_hotkey.start()
            logger.info("Ctrl+J registered")
        except OSError as exc:
            logger.exception("Hotkey registration failed")
            self.notify(str(exc), "JHenkan: ホットキーエラー")

    def unregister_hotkey(self) -> None:
        if self.global_hotkey:
            self.global_hotkey.stop()
            self.global_hotkey = None


if __name__ == "__main__":
    mutex = single_instance()
    if mutex is not None:
        set_app_identity("JHenkan", "JHenkan", ICON_PATH.with_suffix(".png"))
        App().run()
