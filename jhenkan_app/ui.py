from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import threading
import queue
import gc
from contextlib import contextmanager
import ctypes
import webbrowser
from tkinter import messagebox, ttk

import pyperclip

from .config import (
    DEFAULT_OPENAI_MODEL, Settings, get_api_key, set_api_key, set_startup, startup_enabled,
)
from .converter import JapaneseConverter, supported_efforts
from . import chatgpt_auth
from .selection import (
    CapturedText,
    activate_window,
    paste_replacement,
    paste_text_to_window,
    restore_clipboard,
)


@contextmanager
def gui_thread_lifetime():
    """Keep Tcl finalizers on the GUI thread, including between modal windows.

    CPython may otherwise collect Tk cycles on an API or keyboard thread,
    aborting the process with Tcl_AsyncDelete. App collects at GUI safe points.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("JHenkanの画面はメインスレッドで実行してください。")
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        gc.collect()
        if was_enabled:
            gc.enable()


def poll_background_result(root, results, success, failure):
    """Workers only enqueue data; Tk callbacks always run on the GUI thread."""
    try:
        value, error = results.get_nowait()
    except queue.Empty:
        root.after(25, poll_background_result, root, results, success, failure)
    else:
        if error is not None:
            failure(error)
        else:
            success(value)


def edit_settings(settings: Settings, first_run: bool = False,
                  connect_chatgpt: bool = False) -> bool:
    root = tk.Tk()
    root.title("JHenkan 設定")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frame = ttk.Frame(root, padding=18)
    frame.grid()
    labels = {"chatgpt": "ChatGPT（ログイン）", "openai": "OpenAI（APIキー）",
              "gemini": "Gemini（APIキー）"}
    provider_var = tk.StringVar(value=labels["chatgpt" if connect_chatgpt else settings.provider])
    ttk.Label(frame, text="接続方法").grid(row=0, column=0, sticky="w")
    provider_box = ttk.Combobox(frame, textvariable=provider_var,
                              values=list(labels.values()), state="readonly", width=46)
    provider_box.grid(row=1, column=0, columnspan=2, pady=(3, 10), sticky="ew")
    key_label = ttk.Label(frame)
    key_label.grid(row=2, column=0, sticky="w")
    key_var = tk.StringVar()
    key_entry = ttk.Entry(frame, textvariable=key_var, show="●", width=46)
    key_entry.grid(row=3, column=0, columnspan=2, pady=(3, 2), sticky="ew")
    saved_label = ttk.Label(frame, wraplength=400)
    saved_label.grid(row=4, column=0, columnspan=2, sticky="w")
    key_button = ttk.Button(frame)
    key_button.grid(row=2, column=1, sticky="e")
    ttk.Label(frame, text="モデル").grid(row=5, column=0, sticky="w", pady=(10, 0))
    models = {"gemini": settings.gemini_model, "openai": settings.openai_model,
              "chatgpt": settings.chatgpt_model}
    current_provider = "chatgpt" if connect_chatgpt else settings.provider
    model_var = tk.StringVar(value=models[current_provider])
    model_box = ttk.Combobox(frame, textvariable=model_var, width=46)
    model_box.grid(row=6, column=0, columnspan=2, pady=(3, 10), sticky="ew")
    account_frame = ttk.Frame(frame)
    account_frame.grid(row=7, column=0, columnspan=2, sticky="ew")
    ttk.Label(account_frame, text="ChatGPTアカウント").pack(anchor="w")
    account_var = tk.StringVar()
    account_box = ttk.Combobox(account_frame, textvariable=account_var, state="readonly", width=46)
    account_box.pack(fill="x", pady=(3, 5))
    account_actions = ttk.Frame(account_frame)
    account_actions.pack(fill="x", pady=(0, 10))
    reload_button = ttk.Button(account_actions, text="モデルを再読み込み")
    reload_button.pack(side="left")
    logout_button = ttk.Button(account_actions, text="ログアウト")
    logout_button.pack(side="left", padx=5)
    ttk.Button(account_actions, text="利用枠を管理",
               command=lambda: webbrowser.open(chatgpt_auth.USAGE_URL)).pack(side="right")
    effort_frame = ttk.Frame(frame)
    effort_frame.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    ttk.Label(effort_frame, text="推論（none: 速さ優先 / low: 軽く考える）").pack(anchor="w")
    effort_var = tk.StringVar(value=settings.reasoning_effort)
    effort_box = ttk.Combobox(effort_frame, textvariable=effort_var, state="readonly", width=46)
    effort_box.pack(fill="x", pady=(3, 0))
    startup_var = tk.BooleanVar(value=startup_enabled() or settings.start_with_windows)
    ttk.Checkbutton(frame, text="Windowsへのサインイン時に起動", variable=startup_var).grid(
        row=9, column=0, columnspan=2, sticky="w")
    diagnostic_var = tk.BooleanVar(value=settings.diagnostic_text_logging)
    ttk.Checkbutton(frame, text="診断ログに変換前・変換後の本文を記録する",
                    variable=diagnostic_var).grid(row=10, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Label(frame, text="ChatGPT接続はPlus／Proの利用枠を使います。\n"
              "診断ログを有効にすると入力内容が jhenkan.log に残ります。",
              wraplength=410).grid(row=11, column=0, columnspan=2, pady=(12, 14), sticky="w")
    saved = False
    busy = False
    cancel = threading.Event()
    results = queue.Queue()
    pending_done = None
    account_labels = {}
    current_account = settings.chatgpt_account
    if not current_account:
        registered = chatgpt_auth.accounts()
        if registered:
            current_account = registered[-1]["client_id"]
    available_models = []

    def refresh_accounts():
        account_labels.clear()
        for item in chatgpt_auth.accounts():
            label = f"{item['email']} [{item['client_id'][-8:]}]"
            if not item['connected']:
                label += "（未接続）"
            account_labels[label] = item['client_id']
        account_labels["別のアカウントを追加"] = ""
        account_box.configure(values=list(account_labels))
        account_var.set(next((name for name, cid in account_labels.items()
                              if cid == current_account), "別のアカウントを追加"))

    def update_effort(_event=None):
        allowed = supported_efforts(model_var.get())
        effort_box.configure(values=allowed)
        if effort_var.get() not in allowed:
            effort_var.set(allowed[0])

    def controls():
        provider_box.configure(state="disabled" if busy else "readonly")
        account_box.configure(state="disabled" if busy else "readonly")
        for button in (key_button, reload_button, logout_button, save_button):
            button.configure(state="disabled" if busy else "normal")

    def async_work(work, done):
        nonlocal busy, pending_done
        if busy:
            return
        busy = True
        pending_done = done
        controls()
        def worker():
            try:
                results.put((work(), None))
            except Exception as exc:
                results.put((None, exc))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        nonlocal busy, current_account, pending_done
        try:
            value, error = results.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            done, pending_done = pending_done, None
            controls()
            if error:
                root.attributes("-topmost", True)
                if current_provider == "chatgpt":
                    registered = chatgpt_auth.accounts()
                    if not current_account and registered:
                        current_account = registered[-1]["client_id"]
                    refresh_accounts()
                saved_label.configure(text="接続を確認してください。")
                messagebox.showerror("JHenkan", str(error), parent=root)
            else:
                done(value)
        root.after(100, poll)

    def loaded(items):
        available_models[:] = items
        choices = [item['slug'] for item in items]
        model_box.configure(values=choices)
        if model_var.get() not in choices:
            model_var.set(DEFAULT_OPENAI_MODEL if DEFAULT_OPENAI_MODEL in choices else "")
        update_effort()
        saved_label.configure(text="ChatGPT接続済み。モデルを選んで保存してください。")

    def load_models():
        available_models.clear()
        model_box.configure(values=())
        if not current_account or not chatgpt_auth.connected(current_account):
            return
        saved_label.configure(text="使えるモデルを確認中…")
        async_work(lambda: chatgpt_auth.list_models(current_account), loaded)

    def signed_in(cid):
        nonlocal current_account
        root.attributes("-topmost", True)
        root.lift()
        current_account = cid
        refresh_accounts()
        load_models()

    def login():
        root.attributes("-topmost", False)
        saved_label.configure(text="ブラウザーでChatGPTにログインしてください…")
        cid = current_account
        async_work(lambda: chatgpt_auth.sign_in(cid, cancel), signed_in)

    def logout():
        def finished(confirmed):
            available_models.clear()
            model_box.configure(values=())
            refresh_accounts()
            saved_label.configure(text="ログアウトしました（ChatGPT側の登録は残ります）。")
            if not confirmed:
                messagebox.showinfo("JHenkan", "このPCではログアウトしました。サーバー側の解除は確認できなかったため、ChatGPTの設定から接続を解除してください。", parent=root)
        cid = current_account
        async_work(lambda: chatgpt_auth.sign_out(cid), finished)

    def selected_account(_event=None):
        nonlocal current_account
        current_account = account_labels.get(account_var.get(), "")
        saved_label.configure(text="Continue with ChatGPTで接続してください。")
        load_models()

    def refresh_provider(_event=None):
        nonlocal current_provider
        models[current_provider] = model_var.get().strip()
        current_provider = next(key for key, label in labels.items() if label == provider_var.get())
        model_var.set(models[current_provider])
        key_var.set("")
        is_chatgpt = current_provider == "chatgpt"
        model_box.configure(state="readonly" if is_chatgpt else "normal",
                            values=() if is_chatgpt else (DEFAULT_OPENAI_MODEL, "gpt-6.1-sol"))
        if is_chatgpt:
            key_entry.grid_remove()
            account_frame.grid()
            key_label.configure(text="ChatGPTに接続")
            key_button.configure(text="Continue with ChatGPT", command=login)
            saved_label.configure(text="Continue with ChatGPTで接続してください。")
            refresh_accounts()
            load_models()
        else:
            key_entry.grid()
            account_frame.grid_remove()
            key_label.configure(text="Gemini APIキー" if current_provider == "gemini" else "OpenAI APIキー")
            key_button.configure(text="APIキーを取得", command=lambda: webbrowser.open(
                "https://aistudio.google.com/api-keys" if current_provider == "gemini"
                else "https://platform.openai.com/api-keys"))
            saved_label.configure(text="保存済み（空欄なら変更しません）" if get_api_key(current_provider) else "未登録")
        if current_provider == "gemini":
            effort_frame.grid_remove()
            model_box.configure(values=("gemini-3.6-flash",))
        else:
            effort_frame.grid()
        update_effort()

    def save():
        nonlocal saved
        if current_provider == "chatgpt":
            if not current_account or not chatgpt_auth.connected(current_account):
                messagebox.showerror("JHenkan", "ChatGPTにログインしてください。", parent=root)
                return
            if model_var.get() not in [item['slug'] for item in available_models]:
                messagebox.showerror("JHenkan", "モデルを再読み込みして、使えるモデルを選んでください。", parent=root)
                return
        elif not get_api_key(current_provider) and not key_var.get().strip():
            messagebox.showerror("JHenkan", "APIキーを入力してください。", parent=root)
            return
        try:
            if current_provider != "chatgpt" and key_var.get().strip():
                set_api_key(current_provider, key_var.get().strip())
            models[current_provider] = model_var.get().strip()
            settings.provider = current_provider
            settings.gemini_model = models["gemini"] or "gemini-3.6-flash"
            settings.openai_model = models["openai"] or DEFAULT_OPENAI_MODEL
            settings.chatgpt_model = models["chatgpt"] or DEFAULT_OPENAI_MODEL
            settings.chatgpt_account = current_account
            settings.reasoning_effort = effort_var.get()
            settings.start_with_windows = startup_var.get()
            settings.diagnostic_text_logging = diagnostic_var.get()
            settings.save()
            set_startup(settings.start_with_windows)
        except Exception as exc:
            messagebox.showerror("JHenkan", f"設定を保存できません: {exc}", parent=root)
            return
        saved = True
        close()

    def close():
        cancel.set()
        root.destroy()

    save_button = ttk.Button(frame, text="保存", command=save)
    save_button.grid(row=12, column=1, sticky="e")
    if not first_run:
        ttk.Button(frame, text="キャンセル", command=close).grid(row=12, column=0, sticky="e", padx=(0, 8))
    provider_box.bind("<<ComboboxSelected>>", refresh_provider)
    account_box.bind("<<ComboboxSelected>>", selected_account)
    model_box.bind("<<ComboboxSelected>>", update_effort)
    model_box.bind("<FocusOut>", update_effort)
    reload_button.configure(command=load_models)
    logout_button.configure(command=logout)
    root.protocol("WM_DELETE_WINDOW", close)
    refresh_provider()
    root.after(100, poll)
    if connect_chatgpt and not busy:
        root.after(250, login)
    root.mainloop()
    return saved


def compose_text(
    settings: Settings,
    target_window: int,
    notify,
    initial_text: str = "",
) -> str:
    """Show a real uncommitted text buffer, then commit its conversion once."""
    root = tk.Tk()
    root.title("JHenkan 入力バッファ")
    root.attributes("-topmost", True)
    root.resizable(True, False)
    root.configure(background="#111111")
    style = ttk.Style(root)
    style.configure("JHenkanDark.TFrame", background="#111111")
    style.configure(
        "JHenkanDark.TLabel", background="#111111", foreground="#ffffff"
    )

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    root.geometry(f"540x148+{max(0, point.x - 40)}+{max(0, point.y + 18)}")

    frame = ttk.Frame(root, padding=10, style="JHenkanDark.TFrame")
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="未確定文字列（閉じても次回まで保持）",
        style="JHenkanDark.TLabel",
    ).pack(anchor="w", pady=(0, 5))
    entry = tk.Text(frame, height=3, wrap="word", font=("Yu Gothic UI", 12))
    entry.configure(
        background="#202020",
        foreground="#ffffff",
        insertbackground="#ffffff",
        relief="flat",
        padx=7,
        pady=5,
    )
    entry.pack(fill="both", expand=True)
    if initial_text:
        entry.insert("1.0", initial_text)
        entry.mark_set("insert", "end-1c")
    status = ttk.Label(
        frame,
        text="ここにローマ字・かなを入力 → Ctrl+Jで変換 / Esc・×で保持",
        style="JHenkanDark.TLabel",
    )
    status.pack(anchor="w", pady=(5, 0))
    clipboard_before = pyperclip.paste()
    converting = False
    retained_text = initial_text

    def finish(result: str) -> None:
        nonlocal retained_text
        retained_text = ""
        root.withdraw()
        root.update_idletasks()
        if not paste_text_to_window(target_window, result, clipboard_before):
            notify("元の入力先へ戻れませんでした。変換結果はクリップボードにあります。")
        root.destroy()

    def fail(exc: Exception) -> None:
        nonlocal converting
        converting = False
        root.configure(background="SystemButtonFace")
        frame.configure(style="TFrame")
        entry.configure(state="normal")
        entry.configure(background="#ffffff", foreground="#000000")
        status.configure(style="TLabel")
        status.configure(text=f"変換エラー: {str(exc)[:120]} — Ctrl+Jで再試行")
        entry.focus_force()

    def close_and_keep(_event=None) -> None:
        nonlocal retained_text
        retained_text = entry.get("1.0", "end-1c")
        root.destroy()

    def convert(_event=None):
        nonlocal converting
        source = entry.get("1.0", "end-1c")
        if converting or not source.strip():
            return "break"
        converting = True
        root.configure(background="#111111")
        frame.configure(style="JHenkanDark.TFrame")
        entry.configure(state="disabled")
        entry.configure(background="#111111", foreground="#bdbdbd")
        status.configure(style="JHenkanDark.TLabel")
        summary = source.replace("\n", " ↵ ")
        if len(summary) > 60:
            summary = summary[:57] + "…"
        status.configure(text=f"「{summary}」を変換中…")
        results = queue.Queue()

        def worker() -> None:
            try:
                converter = JapaneseConverter(
                    get_api_key(settings.provider, settings.chatgpt_account),
                    settings.model,
                    settings.api_timeout_seconds,
                    settings.provider,
                    settings.diagnostic_text_logging,
                    reasoning_effort=settings.reasoning_effort,
                )
                result = converter.convert(source)
                results.put((result, None))
            except Exception as exc:
                results.put((None, exc))

        threading.Thread(target=worker, daemon=True).start()
        root.after(25, poll_background_result, root, results, finish, fail)
        return "break"

    entry.bind("<Control-j>", convert)
    entry.bind("<Control-J>", convert)
    root.bind("<Escape>", close_and_keep)
    root.protocol("WM_DELETE_WINDOW", close_and_keep)
    root.after(50, entry.focus_force)
    root.mainloop()
    return retained_text


def convert_selected(settings: Settings, captured: CapturedText, notify,
                     source: str | None = None, previous: str | None = None,
                     on_converted=None) -> bool:
    """Display a dark progress overlay while replacing selected text."""
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(background="#111111")

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    preview = captured.text.replace("\r", "").replace("\n", " ↵ ")
    summary = preview if len(preview) <= 38 else preview[:35] + "…"
    title_text = f"「{summary}」を変換中…"
    title_font = tkfont.Font(root=root, family="Yu Gothic UI", size=9, weight="bold")
    overlay_width = max(110, min(430, title_font.measure(title_text) + 22))
    root.geometry(
        f"{overlay_width}x42+{max(0, point.x - 20)}+{max(0, point.y + 12)}"
    )
    title = tk.Label(
        root,
        text=title_text,
        background="#111111",
        foreground="#ffffff",
        font=title_font,
        anchor="w",
    )
    title.pack(fill="both", expand=True, padx=8, pady=6)
    if len(preview) > 180:
        preview = preview[:177] + "…"
    body = tk.Label(
        root,
        text=preview,
        background="#111111",
        foreground="#bdbdbd",
        font=("Yu Gothic UI", 10),
        anchor="w",
        justify="left",
        wraplength=450,
    )
    root.update_idletasks()
    # A progress indicator must never take keyboard focus away from the editor.
    # Apply WS_EX_NOACTIVATE to both Tk's client and wrapper handles.
    user32 = ctypes.windll.user32
    gwl_exstyle = -20
    ws_ex_noactivate = 0x08000000
    client_hwnd = int(root.winfo_id())
    wrapper_hwnd = int(user32.GetParent(client_hwnd))
    for hwnd in {client_hwnd, wrapper_hwnd}:
        if hwnd:
            style = int(user32.GetWindowLongPtrW(hwnd, gwl_exstyle))
            user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style | ws_ex_noactivate)
    root.deiconify()
    root.update()
    activate_window(captured.window, wait_seconds=0.05)
    converted = False

    def success(result: str) -> None:
        root.withdraw()
        activate_window(captured.window, wait_seconds=0.05)
        root.after(100, commit, result)

    def commit(result: str) -> None:
        nonlocal converted
        if not paste_replacement(captured, result):
            notify("入力先が変わったため貼り付けませんでした。変換結果はクリップボードにあります。")
        else:
            converted = True
            if on_converted:
                on_converted(captured.text if source is None else source, result, captured.window)
        root.destroy()

    def failure(exc: Exception) -> None:
        restore_clipboard(captured)
        root.geometry(f"420x108+{max(0, point.x - 30)}+{max(0, point.y + 14)}")
        title.configure(text="変換できませんでした", foreground="#ff7070")
        body.configure(text=str(exc)[:180], foreground="#ffb4b4")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        notify(str(exc)[:220], "JHenkan: 変換エラー")
        root.after(3500, root.destroy)

    results = queue.Queue()

    def worker() -> None:
        try:
            converter = JapaneseConverter(
                get_api_key(settings.provider, settings.chatgpt_account),
                settings.model,
                settings.api_timeout_seconds,
                settings.provider,
                settings.diagnostic_text_logging,
                reasoning_effort=settings.reasoning_effort,
            )
            result = converter.convert(captured.text if source is None else source, previous=previous)
            results.put((result, None))
        except Exception as exc:
            results.put((None, exc))

    threading.Thread(target=worker, daemon=True).start()
    root.after(25, poll_background_result, root, results, success, failure)
    root.mainloop()
    return converted
