import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import pytest

from jhenkan_app.config import Settings


def test_dialog_cleanup_and_conversion_survive_background_allocations():
    # A Tcl_AsyncDelete abort cannot be caught by pytest; exercise it in a child.
    script = r'''
import ctypes
import gc
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch
from jhenkan_app.config import Settings
from jhenkan_app.ui import edit_settings, convert_selected, gui_thread_lifetime
ctypes.windll.kernel32.SetErrorMode(2)
original = tk.Tk
mode = 'settings'
fail = False
def hidden():
    root = original()
    root.withdraw()
    root.deiconify = lambda: None
    original_after = root.after
    def after(delay, callback=None, *args):
        assert threading.current_thread() is threading.main_thread(), 'Worker touched Tk'
        return original_after(1 if delay == 3500 else delay, callback, *args)
    root.after = after
    if mode == 'settings':
        root.after(5, root.destroy)
    return root
class Converter:
    def __init__(self, *args, **kwargs): pass
    def convert(self, *args, **kwargs):
        assert not gc.isenabled()
        time.sleep(0.01)
        if fail: raise RuntimeError('simulated offline')
        return '日本語'
def allocations():
    assert not gc.isenabled()
    for _ in range(10000):
        cycle = []
        cycle.append(cycle)
with gui_thread_lifetime(), patch('jhenkan_app.ui.tk.Tk', side_effect=hidden), \
     patch('jhenkan_app.ui.get_api_key', return_value='test'), \
     patch('jhenkan_app.ui.startup_enabled', return_value=False), \
     patch('jhenkan_app.ui.activate_window'), patch('jhenkan_app.ui.restore_clipboard'), \
     patch('jhenkan_app.ui.paste_replacement', return_value=True), \
     patch('jhenkan_app.ui.JapaneseConverter', Converter):
    for _ in range(8):
        mode = 'settings'
        edit_settings(Settings(provider='openai'))
        gc.collect()
        worker = threading.Thread(target=allocations)
        worker.start()
        worker.join()
        gc.collect()
        mode = 'conversion'
        for fail in (False, True):
            result = convert_selected(Settings(provider='openai'),
                SimpleNamespace(text='nihongo', window=0), lambda *args: None)
            assert result is not fail
            gc.collect()
assert gc.isenabled()
print('settings, success, failure and worker allocations survived')
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                            text=True, encoding="utf-8", timeout=30,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Tcl_AsyncDelete" not in result.stderr
    assert "Exception ignored" not in result.stderr


@pytest.mark.parametrize("saved_config", [True, False])
def test_app_stays_resident_when_logged_out_or_setup_is_cancelled(saved_config):
    path = Path(__file__).resolve().parents[1] / "app.pyw"
    loader = importlib.machinery.SourceFileLoader("jhenkan_test_app", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    with patch.object(module.Settings, "load", return_value=Settings()), \
            patch.object(module, "has_credentials", return_value=False), \
            patch.object(module, "edit_settings", return_value=False), \
            patch.object(module, "config_path") as config_path, \
            patch.object(module, "TypingBuffer"), patch.object(module, "GlobalHotkey"), \
            patch.object(module, "TrayIcon") as icon, patch.object(module.sys, "argv", ["app.pyw"]):
        app = module.App()
        config_path.return_value.exists.return_value = saved_config
        app.actions.put("quit")
        app.run()
        icon.return_value.run_detached.assert_called_once()
        app.typing_buffer.start.assert_called_once()
        icon.return_value.stop.assert_called_once()
