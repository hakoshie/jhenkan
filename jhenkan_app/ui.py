from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import threading
import ctypes
import webbrowser
from tkinter import messagebox, ttk

import pyperclip

from .config import Settings, get_api_key, set_api_key, set_startup, startup_enabled
from .converter import JapaneseConverter
from .selection import (
    CapturedText,
    activate_window,
    paste_replacement,
    paste_text_to_window,
    restore_clipboard,
)


def edit_settings(settings: Settings, first_run: bool = False) -> bool:
    root = tk.Tk()
    root.title("JHenkan 設定")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=18)
    frame.grid()
    ttk.Label(frame, text="プロバイダー").grid(row=0, column=0, sticky="w")
    provider_var = tk.StringVar(value=settings.provider)
    provider_box = ttk.Combobox(
        frame,
        textvariable=provider_var,
        values=("gemini", "openai"),
        state="readonly",
        width=43,
    )
    provider_box.grid(row=1, column=0, columnspan=2, pady=(3, 10), sticky="ew")

    key_label = ttk.Label(frame)
    key_label.grid(row=2, column=0, sticky="w")
    key_page_button = ttk.Button(
        frame,
        text="APIキーを取得",
        command=lambda: webbrowser.open(
            "https://aistudio.google.com/api-keys"
            if provider_var.get() == "gemini"
            else "https://platform.openai.com/api-keys"
        ),
    )
    key_page_button.grid(row=2, column=1, sticky="e")
    key_var = tk.StringVar()
    key_entry = ttk.Entry(frame, textvariable=key_var, show="●", width=46)
    key_entry.grid(row=3, column=0, columnspan=2, pady=(3, 2), sticky="ew")
    saved_label = ttk.Label(frame)
    saved_label.grid(row=4, column=0, columnspan=2, sticky="w")

    ttk.Label(frame, text="モデル").grid(row=5, column=0, sticky="w", pady=(10, 0))
    models = {
        "gemini": settings.gemini_model,
        "openai": settings.openai_model,
    }
    current_provider = settings.provider
    model_var = tk.StringVar(value=models[current_provider])
    ttk.Entry(frame, textvariable=model_var, width=46).grid(
        row=6, column=0, columnspan=2, pady=(3, 10), sticky="ew"
    )

    def refresh_provider(_event=None) -> None:
        nonlocal current_provider
        models[current_provider] = model_var.get().strip()
        current_provider = provider_var.get()
        model_var.set(models[current_provider])
        key_var.set("")
        key_label.configure(
            text="Gemini APIキー" if current_provider == "gemini" else "OpenAI APIキー"
        )
        saved_label.configure(
            text="保存済み（空欄なら変更しません）"
            if get_api_key(current_provider)
            else "未登録"
        )

    provider_box.bind("<<ComboboxSelected>>", refresh_provider)
    refresh_provider()

    startup_var = tk.BooleanVar(value=startup_enabled() or settings.start_with_windows)
    ttk.Checkbutton(
        frame, text="Windowsへのサインイン時に起動", variable=startup_var
    ).grid(row=7, column=0, columnspan=2, sticky="w")
    diagnostic_var = tk.BooleanVar(value=settings.diagnostic_text_logging)
    ttk.Checkbutton(
        frame,
        text="診断ログに変換前・変換後の本文を記録する",
        variable=diagnostic_var,
    ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Label(
        frame,
        text="注意: 診断ログを有効にすると入力内容が jhenkan.log に残ります。\n"
        "使い方: 未選択でCtrl+Jなら未確定入力。選択中なら直接再変換。",
        wraplength=390,
    ).grid(row=9, column=0, columnspan=2, pady=(12, 14), sticky="w")

    saved = False

    def save() -> None:
        nonlocal saved
        provider = provider_var.get()
        if not get_api_key(provider) and not key_var.get().strip():
            messagebox.showerror("JHenkan", f"{provider} APIキーを入力してください", parent=root)
            return
        if key_var.get().strip():
            try:
                set_api_key(provider, key_var.get().strip())
            except Exception as exc:
                messagebox.showerror("JHenkan", f"APIキーを保存できません: {exc}", parent=root)
                return
        models[current_provider] = model_var.get().strip()
        settings.provider = provider
        settings.gemini_model = models["gemini"] or "gemini-3.6-flash"
        settings.openai_model = models["openai"] or "gpt-5.6-luna"
        settings.start_with_windows = startup_var.get()
        settings.diagnostic_text_logging = diagnostic_var.get()
        settings.save()
        set_startup(settings.start_with_windows)
        saved = True
        root.destroy()

    ttk.Button(frame, text="保存", command=save).grid(row=10, column=1, sticky="e")
    if not first_run:
        ttk.Button(frame, text="キャンセル", command=root.destroy).grid(
            row=10, column=0, sticky="e", padx=(0, 8)
        )
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    key_entry.focus_set()
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

        def worker() -> None:
            try:
                converter = JapaneseConverter(
                    get_api_key(settings.provider),
                    settings.model,
                    settings.api_timeout_seconds,
                    settings.provider,
                    settings.diagnostic_text_logging,
                )
                result = converter.convert(source)
                root.after(0, finish, result)
            except Exception as exc:
                root.after(0, fail, exc)

        threading.Thread(target=worker, daemon=True).start()
        return "break"

    entry.bind("<Control-j>", convert)
    entry.bind("<Control-J>", convert)
    root.bind("<Escape>", close_and_keep)
    root.protocol("WM_DELETE_WINDOW", close_and_keep)
    root.after(50, entry.focus_force)
    root.mainloop()
    return retained_text


def convert_selected(settings: Settings, captured: CapturedText, notify) -> bool:
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
        root.destroy()

    def failure(exc: Exception) -> None:
        restore_clipboard(captured)
        root.geometry(f"420x108+{max(0, point.x - 30)}+{max(0, point.y + 14)}")
        title.configure(text="変換できませんでした", foreground="#ff7070")
        body.configure(text=str(exc)[:180], foreground="#ffb4b4")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        notify(str(exc)[:220], "JHenkan: 変換エラー")
        root.after(3500, root.destroy)

    def worker() -> None:
        try:
            converter = JapaneseConverter(
                get_api_key(settings.provider),
                settings.model,
                settings.api_timeout_seconds,
                settings.provider,
                settings.diagnostic_text_logging,
            )
            root.after(0, success, converter.convert(captured.text))
        except Exception as exc:
            root.after(0, failure, exc)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    return converted
