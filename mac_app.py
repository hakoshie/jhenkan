"""JHenkan macOS resident frontend."""
from __future__ import annotations

import fcntl
import sys
import threading

import AppKit as A
import ApplicationServices as ax
from Foundation import NSObject
from PyObjCTools import AppHelper
from objc import IBAction, python_method

from jhenkan_app import chatgpt_auth, mac_text
from jhenkan_app.config import Settings, data_dir, get_api_key, set_api_key
from jhenkan_app.converter import JapaneseConverter, supported_efforts
from jhenkan_app.mac_hotkey import MacHotkeys


class MenuController(NSObject):
    @python_method
    def setup(self):
        self.settings = Settings.load()
        self.paused = False
        self.busy = False
        self.auth_pending = None
        self.last = None
        self.keys = None
        self.bar = A.NSStatusBar.systemStatusBar()
        self.status = self.bar.statusItemWithLength_(A.NSVariableStatusItemLength)
        self.status.button().setTitle_("J")
        self.status.button().setToolTip_("JHenkan · Control+J")
        menu = A.NSMenu.alloc().init()
        self.pause_item = self.add(menu, "一時停止", "togglePause:")
        self.add(menu, "設定…", "settings:")
        self.add(menu, "ChatGPTにログイン…", "login:")
        self.add(menu, "ChatGPTからログアウト…", "logout:")
        self.add(menu, "アクセシビリティの許可…", "permissions:")
        menu.addItem_(A.NSMenuItem.separatorItem())
        self.add(menu, "終了", "quit:")
        self.status.setMenu_(menu)

    @python_method
    def start_hotkeys(self):
        try:
            self.keys = MacHotkeys(lambda alternate: AppHelper.callAfter(self.convert, alternate))
            self.keys.start()
        except (OSError, AttributeError):
            self.message("ショートカットを登録できませんでした",
                         "ほかのアプリが Ctrl+J または Ctrl+Shift+J を使っていないか確認してください。")

    @python_method
    def add(self, menu, title, action):
        item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        item.setTarget_(self)
        menu.addItem_(item)
        return item

    @python_method
    def alert(self, title, detail=""):
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        return alert

    @python_method
    def show(self, alert):
        A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return alert.runModal()

    @python_method
    def message(self, title, detail="", result=None):
        alert = self.alert(title, detail)
        alert.addButtonWithTitle_("OK")
        if result is not None:
            alert.addButtonWithTitle_("変換結果をコピー")
        if self.show(alert) == A.NSAlertSecondButtonReturn and result is not None:
            board = A.NSPasteboard.generalPasteboard()
            board.clearContents()
            board.setString_forType_(result, A.NSPasteboardTypeString)

    @IBAction
    def togglePause_(self, _sender):
        self.paused = not self.paused
        self.pause_item.setState_(int(self.paused))
        self.status.button().setToolTip_("JHenkan · 一時停止中" if self.paused else "JHenkan · Control+J")

    @IBAction
    def permissions_(self, _sender):
        if ax.AXIsProcessTrustedWithOptions({ax.kAXTrustedCheckOptionPrompt: True}):
            self.message("アクセシビリティは許可済みです")
        else:
            self.message("アクセシビリティを許可してください",
                         "システム設定 → プライバシーとセキュリティ → アクセシビリティで JHenkan を許可してください。")

    @IBAction
    def settings_(self, _sender):
        alert = self.alert("JHenkan 設定", "接続方法を選んでください。APIキーはキーチェーンへ保存します。空欄なら既存のモデル・キーを使います。")
        view = A.NSView.alloc().initWithFrame_(((0, 0), (340, 124)))
        popup = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 94), (340, 26)), False)
        popup.addItemsWithTitles_(["ChatGPT（ログイン）", "OpenAI（APIキー）", "Gemini（APIキー）"])
        popup.selectItemAtIndex_(PROVIDERS_FOR_UI.index(self.settings.provider))
        model = A.NSTextField.alloc().initWithFrame_(((0, 65), (340, 24)))
        model.setPlaceholderString_("モデルを変更する場合だけ入力")
        secret = A.NSSecureTextField.alloc().initWithFrame_(((0, 35), (340, 24)))
        secret.setPlaceholderString_("APIキー（OpenAI／Geminiのみ）")
        effort = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 2), (340, 26)), False)
        effort.addItemsWithTitles_(["推論なし（none）", "軽い推論（low）"])
        effort.selectItemAtIndex_(0 if self.settings.reasoning_effort == "none" else 1)
        for field in (popup, model, secret, effort):
            view.addSubview_(field)
        alert.setAccessoryView_(view)
        alert.addButtonWithTitle_("保存")
        alert.addButtonWithTitle_("キャンセル")
        if self.show(alert) != A.NSAlertFirstButtonReturn:
            return
        provider = PROVIDERS_FOR_UI[popup.indexOfSelectedItem()]
        key, chosen = secret.stringValue().strip(), model.stringValue().strip()
        secret.setStringValue_("")
        settings = Settings.load()
        try:
            if key and provider != "chatgpt":
                set_api_key(provider, key)
            if chosen:
                setattr(settings, f"{provider}_model", chosen)
            settings.provider = provider
            requested = ("none", "low")[effort.indexOfSelectedItem()]
            supported = supported_efforts(settings.model)
            settings.reasoning_effort = requested if requested in supported else supported[0]
            settings.save()
            self.settings = settings
        except Exception:
            self.message("設定を保存できませんでした", "設定フォルダーとキーチェーンを確認してください。")

    @IBAction
    def login_(self, _sender):
        if self.auth_pending:
            self.message("ChatGPTの操作が進行中です")
            return
        try:
            accounts = chatgpt_auth.accounts()
        except chatgpt_auth.AuthError as error:
            self.message("ChatGPTログイン", str(error))
            return
        alert = self.alert("ChatGPTにログイン", "続けるとブラウザーで認証を開始します。")
        popup = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 0), (320, 27)), False)
        ids = [item["client_id"] for item in accounts] + [""]
        popup.addItemsWithTitles_([f"{item['email']} [{item['client_id'][-8:]}]" for item in accounts] + ["別のアカウントを追加"])
        if self.settings.chatgpt_account in ids[:-1]:
            popup.selectItemAtIndex_(ids.index(self.settings.chatgpt_account))
        alert.setAccessoryView_(popup)
        alert.addButtonWithTitle_("Continue with ChatGPT")
        alert.addButtonWithTitle_("キャンセル")
        if self.show(alert) != A.NSAlertFirstButtonReturn:
            return
        client_id = ids[popup.indexOfSelectedItem()]
        cancel = self.auth_pending = threading.Event()

        def work():
            try:
                account = chatgpt_auth.sign_in(client_id, cancel)
                models = []
                try:
                    models = chatgpt_auth.list_models(account)
                except chatgpt_auth.AuthError:
                    pass
                AppHelper.callAfter(self.auth_finished, account, models, "")
            except chatgpt_auth.AuthError as error:
                AppHelper.callAfter(self.auth_finished, "", [], str(error))
            except Exception:
                AppHelper.callAfter(self.auth_finished, "", [], "ログインを完了できませんでした。")

        threading.Thread(target=work, daemon=True).start()

    @python_method
    def auth_finished(self, account, models, error):
        self.auth_pending = None
        if error:
            self.message("ChatGPTログイン", error)
            return
        self.settings.provider = "chatgpt"
        self.settings.chatgpt_account = account
        ids = [model["slug"] for model in models]
        if ids and self.settings.chatgpt_model not in ids:
            self.settings.chatgpt_model = ids[0]
        self.settings.save()
        self.message("ChatGPTにログインしました", "設定から使うモデルを変更できます。")

    @IBAction
    def logout_(self, _sender):
        account = self.settings.chatgpt_account
        if self.auth_pending or not account:
            return
        alert = self.alert("ChatGPTからログアウトしますか？")
        alert.addButtonWithTitle_("ログアウト")
        alert.addButtonWithTitle_("キャンセル")
        if self.show(alert) != A.NSAlertFirstButtonReturn:
            return
        self.auth_pending = threading.Event()

        def work():
            try:
                confirmed = chatgpt_auth.sign_out(account)
                error = "" if confirmed else "このMacの認証は解除しました。サーバー側の解除は確認できませんでした。"
            except Exception:
                error = "ログアウトできませんでした。キーチェーンと接続を確認してください。"
            AppHelper.callAfter(self.logout_finished, error)

        threading.Thread(target=work, daemon=True).start()

    @python_method
    def logout_finished(self, error):
        self.auth_pending = None
        self.message("ChatGPTログアウト", error or "ログアウトしました。")

    @python_method
    def convert(self, alternate):
        if self.paused or self.busy or self.auth_pending:
            return
        if not ax.AXIsProcessTrusted():
            self.permissions_(None)
            return
        try:
            captured = mac_text.capture()
        except Exception:
            captured = None
        if captured is None:
            self.message("変換できる入力がありません",
                         "対応している入力欄でカーソルの前に文字を入力するか、変換したい部分を選択してください。")
            return
        if self.last and not alternate:
            try:
                captured = mac_text.since_last(captured, self.last[2], self.last[4], self.last[5])
            except UnicodeError:
                pass
        source, previous = captured.source, None
        if alternate:
            if not (self.last and captured.caret[1] and captured.source == self.last[1]
                    and captured.replace[0] == self.last[3] and mac_text.same_control(captured.element, self.last[2])):
                self.message("直前の変換結果を選択して Ctrl+Shift+J を押してください")
                return
            source, previous = self.last[:2]
        self.busy = True
        self.status.button().setTitle_("J…")
        settings = self.settings

        def work():
            try:
                key = get_api_key(settings.provider, settings.chatgpt_account)
                if not key:
                    raise chatgpt_auth.AuthError("メニューバーの「設定…」で接続を設定してください。")
                result = JapaneseConverter(key, settings.model, settings.api_timeout_seconds, settings.provider,
                                           False, settings.reasoning_effort).convert(source, previous)
                AppHelper.callAfter(self.finish, captured, source, result, "")
            except chatgpt_auth.AuthError as error:
                AppHelper.callAfter(self.finish, captured, source, None, str(error))
            except Exception:
                AppHelper.callAfter(self.finish, captured, source, None, "変換できませんでした。設定とネット接続を確認してください。")

        threading.Thread(target=work, daemon=True).start()

    @python_method
    def finish(self, captured, source, result, error):
        self.busy = False
        self.status.button().setTitle_("J")
        if error:
            self.message("JHenkan", error)
            return
        try:
            if not self.paused and mac_text.apply(captured, result):
                start = captured.replace[0]
                end = start + len(result.encode("utf-16-le")) // 2
                self.last = (source, result, captured.element, start, end, mac_text.expected_value(captured, result))
                return
        except Exception:
            pass
        self.message("変換結果を自動で差し替えませんでした",
                     "入力欄や選択範囲が変わったか、このアプリでは置き換えに対応していません。必要なら結果をコピーできます。", result)

    @IBAction
    def quit_(self, _sender):
        if self.auth_pending:
            self.auth_pending.set()
        if self.keys is not None:
            self.keys.stop()
        A.NSApplication.sharedApplication().terminate_(None)


PROVIDERS_FOR_UI = ("chatgpt", "openai", "gemini")


def main():
    if "--smoke-test" in sys.argv:
        assert callable(JapaneseConverter.convert) and A.NSPasteboardTypeString
        MacHotkeys(lambda _alternate: None)  # Verify that both native architectures resolve the symbols.
        from CoreFoundation import CFRange
        value = ax.AXValueCreate(ax.kAXValueCFRangeType, CFRange(2, 4))
        ok, span = ax.AXValueGetValue(value, ax.kAXValueCFRangeType, None)
        assert ok and tuple(span) == (2, 4)
        assert mac_text.target_range("昨日\n🤝konnichiwa", (15, 0))[1] == "🤝konnichiwa"
        return
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "resident.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        app = A.NSApplication.sharedApplication()
        app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
        controller = MenuController.alloc().init()
        controller.setup()
        AppHelper.callAfter(controller.start_hotkeys)
        app.run()


if __name__ == "__main__":
    main()
