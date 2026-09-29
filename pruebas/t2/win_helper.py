# Ayudante bajo Wine: responde la pregunta nativa (MessageBox), simula clic en el ícono de la bandeja
# y lista ventanas.   python win_helper.py msgbox si|no [espera_s] | tray-open | windows
import ctypes, sys, time
from ctypes import wintypes
user32 = ctypes.WinDLL("user32")
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetDlgItem.restype = wintypes.HWND
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetDlgItemTextW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPWSTR, ctypes.c_int]

cmd = sys.argv[1]
if cmd == "msgbox":
    button = {"si": 6, "no": 7}[sys.argv[2]]
    limit = float(sys.argv[3]) if len(sys.argv) > 3 else 10
    t = time.time()
    h = None
    while time.time() - t < limit:
        h = user32.FindWindowW("#32770", "Servidor Home")
        if h:
            break
        time.sleep(0.1)
    if not h:
        print("MSGBOX: no apareció"); sys.exit(2)
    buf = ctypes.create_unicode_buffer(2000)
    user32.GetDlgItemTextW(h, 0xFFFF, buf, 2000)
    print(f"MSGBOX apareció (esperé {time.time() - t:.1f} s): {buf.value!r}")
    time.sleep(0.5)
    b = user32.GetDlgItem(h, button)
    user32.SendMessageW(b, 0xF5, 0, 0)        # BM_CLICK
    print("MSGBOX respondida:", sys.argv[2])
elif cmd == "tray-open":
    h = user32.FindWindowW("ServidorHomeTray", None)
    print("bandeja:", h)
    if h:
        user32.PostMessageW(h, 0x8001, 1, 0x202)        # WM_APP+1 con WM_LBUTTONUP: clic en el ícono
elif cmd == "tray-count":           # cuántas ventanas ocultas de ícono de bandeja hay (una por app abierta)
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    n, h = 0, None
    while True:
        h = user32.FindWindowExW(None, h, "ServidorHomeTray", None)
        if not h:
            break
        n += 1
    print("bandejas:", n)
elif cmd == "windows":
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256); c = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, t, 256); user32.GetClassNameW(h, c, 256)
            if t.value:
                print(f"  {h:#x} [{c.value}] {t.value!r}")
        return True
    user32.EnumWindows(proto(cb), 0)
