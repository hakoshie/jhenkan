"""Exercise settings changes through real, hidden Tk widgets without network calls."""
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from jhenkan_app.config import Settings
from jhenkan_app.ui import edit_settings


def test_settings_reuse_existing_registration_and_adjust_sol_effort():
    original_tk = tk.Tk
    errors = []
    def make_root():
        root = original_tk()
        root.withdraw()
        def exercise():
            try:
                def widgets(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from widgets(child)
                all_widgets = list(widgets(root))
                combos = [widget for widget in all_widgets if isinstance(widget, ttk.Combobox)]
                model = next(widget for widget in combos if "gpt-6.1-sol" in widget['values'])
                effort = next(widget for widget in combos if "none" in widget['values'])
                assert model.get() == "gpt-6-luna"
                model.set("gpt-6.1-sol")
                model.event_generate("<<ComboboxSelected>>")
                assert effort.get() == "low"
                assert tuple(effort['values']) == ("low",)
                save = next(widget for widget in all_widgets
                            if isinstance(widget, ttk.Button) and widget['text'] == "保存")
                save.invoke()
            except Exception as exc:
                errors.append(exc)
                root.destroy()
        root.after(500, exercise)
        root.after(3000, root.destroy)
        return root
    settings = Settings(chatgpt_account="")
    available = [{"slug": "gpt-6-luna"}, {"slug": "gpt-6.1-sol"}]
    with patch("jhenkan_app.ui.tk.Tk", side_effect=make_root), \
            patch("jhenkan_app.ui.chatgpt_auth.accounts", return_value=[
                {"client_id": "oaiapp_test", "email": "test@example.com", "connected": True}]), \
            patch("jhenkan_app.ui.chatgpt_auth.connected", return_value=True), \
            patch("jhenkan_app.ui.chatgpt_auth.list_models", return_value=available), \
            patch("jhenkan_app.ui.startup_enabled", return_value=False), \
            patch("jhenkan_app.ui.set_startup"), \
            patch.object(settings, "save") as save:
        assert edit_settings(settings)
        assert not errors, errors
        save.assert_called_once()
    assert settings.chatgpt_model == "gpt-6.1-sol"
    assert settings.reasoning_effort == "low"
    assert settings.chatgpt_account == "oaiapp_test"
