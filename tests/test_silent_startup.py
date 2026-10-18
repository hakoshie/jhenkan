import importlib.machinery,importlib.util,queue
from pathlib import Path
from unittest.mock import Mock,patch
import pytest
from jhenkan_app.config import Settings

def load_app():
    path=Path(__file__).resolve().parents[1]/'app.pyw'
    loader=importlib.machinery.SourceFileLoader('jhenkan_silent_startup_test',str(path))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    return module

@pytest.mark.parametrize('connected',[True,False])
def test_startup_is_silent_with_saved_configuration(connected):
    module=load_app();app=module.App.__new__(module.App)
    app.settings=Settings();app.icon=Mock();app.typing_buffer=Mock()
    app.register_hotkey=Mock();app.unregister_hotkey=Mock()
    app.actions=queue.Queue();app.actions.put('quit')
    with patch.object(module.sys,'argv',['app.pyw']),patch.object(module,'has_credentials',return_value=connected),patch.object(module,'config_path') as path,patch.object(module,'edit_settings') as settings:
        path.return_value.exists.return_value=True
        app._run()
    app.icon.run_detached.assert_called_once()
    app.register_hotkey.assert_called_once()
    app.icon.notify.assert_not_called()
    settings.assert_not_called()

def test_hotkey_registration_error_is_still_reported():
    module=load_app();app=module.App.__new__(module.App)
    app.global_hotkey=None;app.notify=Mock()
    with patch.object(module,'GlobalHotkey') as hotkey:
        hotkey.return_value.start.side_effect=OSError('synthetic hotkey collision')
        app.register_hotkey()
    app.notify.assert_called_once()
