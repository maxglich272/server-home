# Ventana falsa de Edge para pruebas: clase y título como una ventana de app de Chromium.
import ctypes, os, sys, time
from ctypes import wintypes
here = os.path.dirname(os.path.abspath(__file__))
flag = os.path.join(here, "cerrar-ventana.txt")
with open(os.path.join(here, "edge-args.txt"), "a", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
done = [False]
def proc(h, m, w, l):
    if m == 0x2:          # WM_DESTROY
        done[0] = True
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(h, m, w, l)
wp = WNDPROC(proc)
class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]
hinst = kernel32.GetModuleHandleW(None)
wc = WNDCLASSW(); wc.lpfnWndProc = wp; wc.hInstance = hinst; wc.lpszClassName = "Chrome_WidgetWin_1"; wc.hbrBackground = 6
user32.RegisterClassW(ctypes.byref(wc))
hwnd = user32.CreateWindowExW(0, "Chrome_WidgetWin_1", "Servidor Home", 0x10CF0000, 200, 150, 700, 450, None, None, hinst, None)
user32.ShowWindow(hwnd, 5)
msg = wintypes.MSG()
while not done[0]:
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
    if os.path.exists(flag):
        os.remove(flag)
        user32.DestroyWindow(hwnd)
    time.sleep(0.2)
