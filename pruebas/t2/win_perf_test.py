# Bajo Wine: las llamadas nuevas de Windows no botan la app (identidad de la ventana para la barra de tareas,
# EcoQoS del servidor y «no suspender»). Wine no implementa todo; lo importante es que nunca fallen feo.
import ctypes, subprocess, sys, threading, time
from ctypes import wintypes
sys.path.insert(0, r"Z:\home\claude\servidor-home")
import servidor_home as sh
ok = fail = 0
def check(n, c, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if c else (ok, fail + 1)
    print(("OK  " if c else "FAIL"), n, extra, flush=True)

p = subprocess.Popen(["cmd", "/c", "ping -n 2 127.0.0.1 >nul"])
r = sh.win_no_power_throttling(p)
check("EcoQoS: la llamada no falla", r in (True, False), f"(resultado {r})")
p.wait()

user32 = ctypes.windll.user32
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
hwnd = user32.CreateWindowExW(0, "STATIC", "Servidor Home", 0x10000000, 10, 10, 200, 100, None, None, None, None)
r = sh.win_app_identity(hwnd)
check("identidad para la barra de tareas: la llamada no falla", r in (True, False), f"(resultado {r}; en Windows real es True)")
check("identidad sin ventana: no hace nada", sh.win_app_identity(0) is False)
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(sh.APP_USER_MODEL_ID)
    check("identidad del proceso", True)
except Exception as e:
    check("identidad del proceso", False, str(e))

sh.running_servers = lambda: [object()]
ka = sh.KeepAwake()
time.sleep(1.5)
check("no suspender con un servidor encendido", ka.on is True)
sh.running_servers = lambda: []
check("KeepAwake sigue vivo", any(t.is_alive() for t in threading.enumerate() if t.daemon))
print(f"\n{ok} OK, {fail} fallas")
