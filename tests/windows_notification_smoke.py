"""Send only a synthetic notification and inspect actual Windows API payloads."""
import argparse,ctypes,importlib,json,sys,threading,time
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageChops
from ctypes import wintypes

class Header(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),('planes',wintypes.WORD),('bits',wintypes.WORD),('compression',wintypes.DWORD),('bytes',wintypes.DWORD),('x',wintypes.LONG),('y',wintypes.LONG),('used',wintypes.DWORD),('important',wintypes.DWORD)]
class Info(ctypes.Structure):
    _fields_=[('header',Header),('colors',wintypes.DWORD*1)]
def draw_handle(hicon,n):
    u=ctypes.windll.user32;g=ctypes.windll.gdi32
    g.CreateCompatibleDC.restype=ctypes.c_void_p;dc=g.CreateCompatibleDC(None)
    g.CreateDIBSection.restype=ctypes.c_void_p
    g.CreateDIBSection.argtypes=(ctypes.c_void_p,ctypes.POINTER(Info),ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p,wintypes.DWORD)
    info=Info();info.header=Header(ctypes.sizeof(Header),n,-n,1,32,0,n*n*4,0,0,0,0)
    bits=ctypes.c_void_p();bm=g.CreateDIBSection(dc,ctypes.byref(info),0,ctypes.byref(bits),None,0)
    g.SelectObject.restype=ctypes.c_void_p;g.SelectObject.argtypes=(ctypes.c_void_p,ctypes.c_void_p)
    old=g.SelectObject(dc,bm);ctypes.memset(bits,255,n*n*4)
    u.DrawIconEx.argtypes=(ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint)
    assert u.DrawIconEx(dc,0,0,hicon,n,n,0,None,3)
    im=Image.frombytes('RGBA',(n,n),ctypes.string_at(bits,n*n*4),'raw','BGRA').convert('RGB')
    g.SelectObject(dc,old);g.DeleteObject(ctypes.c_void_p(bm));g.DeleteDC(ctypes.c_void_p(dc))
    return im

parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--app',choices=['JHenkan','JTranslate'],default='JHenkan');args=parser.parse_args()
sys.path.insert(0,str(args.repo));package=args.app.lower()+'_app';module=importlib.import_module(package+'.tray')
module.set_app_identity('hakoshie.'+args.app)
appid=ctypes.c_void_p();get=ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID;get.argtypes=(ctypes.POINTER(ctypes.c_void_p),)
assert get(ctypes.byref(appid))==0
try:assert ctypes.wstring_at(appid)=='hakoshie.'+args.app
finally:ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(appid.value))
asset=next((args.repo/'assets').glob('*.ico'));seen=[];ready=threading.Event();shown=threading.Event()
class Probe(module.TrayIcon):
    def _on_notify(self,wparam,lparam):
        if lparam==0x0402:shown.set()  # NIN_BALLOONSHOW
        return super()._on_notify(wparam,lparam)
with Image.open(asset.with_suffix('.png')) as im:icon=Probe(args.app,im.copy(),args.app,icon_file=asset)
real=module.win32.Shell_NotifyIcon
def send(code,data):
    if data.uFlags & module.win32.NIF_INFO and data.szInfo:
        assert data.dwInfoFlags==0x24 and data.hBalloonIcon
        n=ctypes.windll.user32.GetSystemMetrics(11) or 32
        with Image.open(asset) as ico:expected=ico.ico.getimage((n,n)).convert('RGBA')
        white=Image.new('RGBA',(n,n),'white');white.alpha_composite(expected)
        assert max(hi for lo,hi in ImageChops.difference(draw_handle(data.hBalloonIcon,n),white.convert('RGB')).getextrema())<=1
        geticon=ctypes.windll.user32.SendMessageW;geticon.restype=ctypes.c_void_p;geticon.argtypes=(ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t)
        assert geticon(data.hWnd,0x007f,0,0)==icon._icon_handle
        assert geticon(data.hWnd,0x007f,1,0)==data.hBalloonIcon
        result=real(code,data);assert result
        seen.append({'native_icon_size':n,'approved_pixels':True,'window_small_and_large_icons':True,'shell_accepted':True})
        return result
    return real(code,data)
with patch.object(module.win32,'Shell_NotifyIcon',send):
    icon.run_detached(setup=lambda item:(setattr(item,'visible',True),ready.set()))
    assert ready.wait(5)
    try:
        icon.notify('Synthetic notification icon verification. No document text.',args.app+' icon check')
        shown.wait(8)
    finally:icon.stop()
assert len(seen)==1
report={'app':args.app,'explicit_app_id':'hakoshie.'+args.app,'notifications':seen,'balloon_shown_callback':shown.is_set()}
(args.repo/'NOTIFICATION-TEST-RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
