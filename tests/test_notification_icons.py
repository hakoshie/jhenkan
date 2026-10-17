"""Check the native notification boundary without posting real notifications."""
import ctypes,importlib,os
from pathlib import Path
from unittest.mock import patch
from PIL import Image
module=importlib.import_module('jhenkan_app'+'.tray')
asset=next((Path(__file__).resolve().parents[1]/'assets').glob('*.ico'))

def test_notification_supplies_approved_large_icon():
    with Image.open(asset.with_suffix('.png')) as image:
        icon=module.TrayIcon('notification-test',image.copy(),icon_file=asset)
    try:
        with patch.object(icon,'_message') as message:
            icon._notify('Synthetic notification icon check','Icon check')
        args,kw=message.call_args
        assert args==(module.win32.NIM_MODIFY,module.win32.NIF_INFO)
        assert kw.get('dwInfoFlags')==0x24
        assert kw.get('hBalloonIcon')
        assert kw['hBalloonIcon']==icon._notification_icon_handle
        assert kw['szInfo']=='Synthetic notification icon check'
    finally:icon._release_icon()

def test_notification_handle_is_released():
    with Image.open(asset.with_suffix('.png')) as image:
        icon=module.TrayIcon('notification-test',image.copy(),icon_file=asset)
    with patch.object(icon,'_message'):
        icon._notify('Synthetic','Icon check')
    handle=getattr(icon,'_notification_icon_handle',None)
    assert handle
    icon._release_icon()
    assert icon._notification_icon_handle is None


def test_identity_registers_only_app_metadata_and_preserves_other_values():
    import uuid,winreg
    app_id='NotificationIdentityTest.'+uuid.uuid4().hex
    subkey='Software\\Classes\\AppUserModelId\\'+app_id
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,subkey) as key:
        winreg.SetValueEx(key,'UnrelatedExistingValue',0,winreg.REG_SZ,'preserve')
    try:
        module.set_app_identity(app_id,'JTranslate',asset.with_suffix('.png'))
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,subkey) as key:
            assert winreg.QueryValueEx(key,'DisplayName')[0]=='JTranslate'
            assert winreg.QueryValueEx(key,'IconUri')[0]==str(asset.with_suffix('.png').resolve())
            assert winreg.QueryValueEx(key,'UnrelatedExistingValue')[0]=='preserve'
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,subkey)


def test_identity_rejects_missing_icon_before_registration():
    import pytest,uuid,winreg
    app_id='NotificationIdentityTest.'+uuid.uuid4().hex
    with pytest.raises(FileNotFoundError):
        module.set_app_identity(app_id,'JTranslate',asset.with_name('missing.png'))
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Software\\Classes\\AppUserModelId\\'+app_id)
