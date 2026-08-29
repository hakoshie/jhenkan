from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as Item

from jhenkan_app.config import Settings, get_api_key
from jhenkan_app.hotkey import GlobalHotkey
from jhenkan_app.selection import capture_buffered_text, capture_selection_only
from jhenkan_app.typing_buffer import TypingBuffer
from jhenkan_app.ui import convert_selected, edit_settings


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
    image = Image.new("RGB", (64, 64), "#202124")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((5, 5, 59, 59), radius=13, fill="#f5f5f5")
    draw.text((17, 12), "J", fill="#202124", stroke_width=1)
    draw.text((31, 29), "J", fill="#2563eb", stroke_width=1)
    return image


class App:
    def __init__(self) -> None:
        self.settings = Settings.load()
        self.paused = False
        self.busy = threading.Lock()
        self.global_hotkey: GlobalHotkey | None = None
        self.typing_buffer = TypingBuffer()
        self.actions: queue.Queue[str] = queue.Queue()
        self.icon = pystray.Icon(
            "JHenkan",
            tray_image(),
            "JHenkan — Ctrl+Jで変換",
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

    def hotkey(self) -> None:
        logger.info("Ctrl+J received")
        if self.paused or not self.busy.acquire(blocking=False):
            logger.info("Ctrl+J ignored: paused=%s busy=%s", self.paused, self.busy.locked())
            return
        threading.Thread(target=self.convert_current, daemon=True).start()

    def convert_current(self) -> None:
        queued = False
        self.typing_buffer.pause()
        try:
            captured = capture_selection_only()
            if not captured:
                buffered_text = self.typing_buffer.text()
                logger.info("Typing buffer contains %d characters", len(buffered_text))
                captured = capture_buffered_text(buffered_text)
            if not captured:
                logger.info("No text captured")
                self.notify("変換対象がありません。文字を入力してからCtrl+Jを押してください。")
                return
            logger.info("Captured %d characters", len(captured.text))
            api_key = get_api_key(self.settings.provider)
            if not api_key:
                self.notify(
                    f"設定画面で{self.settings.provider} APIキーを登録してください",
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
        if not get_api_key(self.settings.provider):
            edit_settings(self.settings, first_run=True)
            self.settings = Settings.load()
            if not get_api_key(self.settings.provider):
                return
        self.icon.run_detached()
        self.typing_buffer.start()
        self.register_hotkey()
        self.notify("起動しました。Ctrl+Jで未確定入力、選択範囲は直接再変換できます。")
        while True:
            action = self.actions.get()
            if action == "quit":
                break
            if isinstance(action, tuple) and action[0] == "convert":
                self.unregister_hotkey()
                converted = False
                try:
                    converted = convert_selected(self.settings, action[1], self.notify)
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
                finally:
                    self.typing_buffer.clear()
                    self.typing_buffer.resume()
        self.unregister_hotkey()
        self.typing_buffer.stop()
        self.icon.stop()

    def register_hotkey(self) -> None:
        self.unregister_hotkey()
        self.global_hotkey = GlobalHotkey(self.hotkey)
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
        App().run()
