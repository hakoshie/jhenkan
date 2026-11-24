"""Native macOS menu bar frontend; only reads text when conversion is requested."""
from __future__ import annotations

import os
import sys
import threading

from objc import IBAction, python_method

import AppKit as A
from Foundation import NSObject
from PyObjCTools import AppHelper
import keyring
from keyring.backends.macOS import Keyring

from jhenkan_app.converter import JapaneseConverter


PROVIDERS = ("openai", "gemini")
MODELS = {"openai": "gpt-6-luna", "gemini": "gemini-3.6-flash"}


class MenuController(NSObject):
    @python_method
    def setup(self):
        self.busy = False
        self.status = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
        self.status.button().setTitle_("J")
        self.status.button().setToolTip_("JHenkan")
        menu = A.NSMenu.alloc().init()
        self.convert_item = self.add(menu, "クリップボードの文字を変換", "convert:")
        self.add(menu, "API設定…", "settings:")
        menu.addItem_(A.NSMenuItem.separatorItem())
        self.add(menu, "終了", "quit:")
        self.status.setMenu_(menu)
        self.store = Keyring()

    @python_method
    def add(self, menu, title, action):
        item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        item.setTarget_(self)
        menu.addItem_(item)
        return item

    @python_method
    def message(self, title, detail=""):
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_("OK")
        A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert.runModal()

    @python_method
    def provider(self):
        value = A.NSUserDefaults.standardUserDefaults().stringForKey_("provider")
        return value if value in PROVIDERS else "openai"

    @IBAction
    def settings_(self, _sender):
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_("JHenkan API設定")
        alert.setInformativeText_("選択したサービスに変換対象の文字を送信します。キーを入力すると、このMacのキーチェーンに保存します。空欄なら保存済みのキーを使用します。")
        view = A.NSView.alloc().initWithFrame_(((0, 0), (320, 64)))
        popup = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 34), (320, 26)), False)
        popup.addItemsWithTitles_(["OpenAI API", "Gemini API"])
        popup.selectItemAtIndex_(PROVIDERS.index(self.provider()))
        secret = A.NSSecureTextField.alloc().initWithFrame_(((0, 2), (320, 24)))
        secret.setPlaceholderString_("APIキー")
        view.addSubview_(popup)
        view.addSubview_(secret)
        alert.setAccessoryView_(view)
        alert.addButtonWithTitle_("保存")
        alert.addButtonWithTitle_("キャンセル")
        A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if alert.runModal() != A.NSAlertFirstButtonReturn:
            return
        provider = PROVIDERS[popup.indexOfSelectedItem()]
        value = secret.stringValue().strip()
        secret.setStringValue_("")
        try:
            if value:
                self.store.set_password("JHenkan " + provider, "default", value)
            A.NSUserDefaults.standardUserDefaults().setObject_forKey_(provider, "provider")
        except keyring.errors.KeyringError:
            self.message("APIキーを保存できませんでした", "キーチェーンの状態を確認してください。")

    @IBAction
    def convert_(self, _sender):
        if self.busy:
            return
        board = A.NSPasteboard.generalPasteboard()
        sequence = board.changeCount()
        source = board.stringForType_(A.NSPasteboardTypeString)
        if not source or not source.strip():
            self.message("変換する文字をコピーしてください")
            return
        provider = self.provider()
        self.busy = True
        self.convert_item.setTitle_("変換中…")

        def work():
            try:
                key = self.store.get_password("JHenkan " + provider, "default")
                key = key or os.getenv("OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY")
                if not key:
                    AppHelper.callAfter(self.finish, sequence, None, "先に「API設定…」でキーを登録してください。")
                    return
                result = JapaneseConverter(key, MODELS[provider], provider=provider).convert(source)
                AppHelper.callAfter(self.finish, sequence, result, "")
            except Exception:
                AppHelper.callAfter(self.finish, sequence, None, "変換できませんでした。API設定と接続を確認してください。")

        threading.Thread(target=work, daemon=True).start()

    @python_method
    def finish(self, sequence, result, error):
        self.busy = False
        self.convert_item.setTitle_("クリップボードの文字を変換")
        if error:
            self.message("JHenkan", error)
            return
        board = A.NSPasteboard.generalPasteboard()
        if board.changeCount() != sequence:
            self.message("クリップボードが変更されたため、変換結果で上書きしませんでした。")
            return
        board.clearContents()
        if not board.setString_forType_(result, A.NSPasteboardTypeString):
            self.message("変換結果をクリップボードに書き込めませんでした。")

    @IBAction
    def quit_(self, _sender):
        A.NSApplication.sharedApplication().terminate_(None)


def main():
    if "--smoke-test" in sys.argv:
        assert callable(JapaneseConverter.convert) and A.NSPasteboardTypeString
        return
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    controller = MenuController.alloc().init()
    controller.setup()
    app.run()


if __name__ == "__main__":
    main()
