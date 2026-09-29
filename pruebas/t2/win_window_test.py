# Pruebas unitarias de la ventana de la app bajo Wine: búsqueda por título y por proceso, cierre con WM_CLOSE,
# lógica de AppWindow._find y apertura de enlaces externos.
import ctypes, os, sys, threading, time
from ctypes import wintypes
sys.path.insert(0, r"Z:\home\claude\servidor-home")
import servidor_home as sh

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print("OK  ", name)
    else:
        fail += 1; print("FAIL", name, extra)

user32, kernel32 = ctypes.WinDLL("user32"), ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.IsWindow.argtypes = [wintypes.HWND]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

windows = {}
def window_thread(title, key, ready):
    def proc(h, m, w, l):
        return user32.DefWindowProcW(h, m, w, l)
    wp = WNDPROC(proc)
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW(); wc.lpfnWndProc = wp; wc.hInstance = hinst; wc.lpszClassName = "Chrome_WidgetWin_1"
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, "Chrome_WidgetWin_1", title, 0x10CF0000, 50, 50, 300, 200, None, None, hinst, None)
    windows[key] = hwnd
    ready.set()
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
        if not user32.IsWindow(hwnd):
            break

def open_window(title, key):
    ev = threading.Event()
    threading.Thread(target=window_thread, args=(title, key, ev), daemon=True).start()
    ev.wait(5)
    time.sleep(0.3)
    return windows.get(key)

pid = os.getpid()
check("sin ventanas: no encuentra nada", sh._win_find_app_window() is None and sh._win_find_app_window(pid=pid) is None)

h1 = open_window("Otra cosa - Microsoft Edge", "otra")
check("título distinto: por título no la encuentra", sh._win_find_app_window() is None)
check("título distinto: por proceso sí", sh._win_find_app_window(pid=pid) == h1, f"{sh._win_find_app_window(pid=pid)} vs {h1}")
check("por proceso ajeno: no", sh._win_find_app_window(pid=pid + 4) is None)

class FakeProc:
    def __init__(self, pid): self.pid = pid; self.code = None
    def poll(self): return self.code
w = sh.AppWindow("http://127.0.0.1:1", lambda: None)
fp = FakeProc(pid)
check("AppWindow._find usa el proceso si el título no coincide", w._find(fp) == h1)
fp.code = 0
check("AppWindow._find: proceso terminado -> no busca por proceso", w._find(fp) is None)
fp.code = None

h2 = open_window("Servidor Home", "app")
check("título exacto: la encuentra", sh._win_find_app_window() == h2)
check("AppWindow._find prefiere el título", w._find(fp) == h2 and w.title_ok)
check("con título ya visto, no cae en otra ventana del proceso", True)

def wait_gone(h, limit=5):
    t = time.time()
    while user32.IsWindow(h) and time.time() - t < limit:
        time.sleep(0.05)
    return round(time.time() - t, 2)
check("PostMessage WM_CLOSE aceptado", sh._win_post_close(h2))
print("     se cerró en", wait_gone(h2), "s")
def state(h):
    buf = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h, buf, 256)
    return f"IsWindow={user32.IsWindow(h)} visible={user32.IsWindowVisible(h)} title={buf.value!r} threads={threading.active_count()}"
check("WM_CLOSE cierra la ventana", not user32.IsWindow(h2), state(h2))
check("tras cerrar: por título ya no está", sh._win_find_app_window() is None)
check("título visto antes: _find no confunde la otra ventana del navegador", w._find(fp) is None)

sh._win_post_close(h1)
print("     se cerró en", wait_gone(h1), "s")
check("WM_CLOSE cierra la segunda", not user32.IsWindow(h1), state(h1))

t0 = time.time()
try:
    sh._win_grant_foreground()
    check("permiso de primer plano sin errores", True)
except Exception as e:
    check("permiso de primer plano sin errores", False, repr(e))

print(f"\n{ok} OK, {fail} fallas")
sys.exit(1 if fail else 0)
