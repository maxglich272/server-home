import ctypes, sys, uuid
from ctypes import wintypes
sys.path.insert(0, r"Z:\home\claude\servidor-home")
import servidor_home as sh
user32 = ctypes.windll.user32
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
hwnd = user32.CreateWindowExW(0, "STATIC", "Servidor Home", 0x10000000, 10, 10, 200, 100, None, None, None, None)
print("set:", sh.win_app_identity(hwnd))
class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]
class PK(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]
class PV(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort), ("val", ctypes.c_void_p), ("v2", ctypes.c_void_p)]
def guid(t):
    g = GUID(); ctypes.memmove(ctypes.byref(g), uuid.UUID(t).bytes_le, 16); return g
store = ctypes.c_void_p()
sh32 = ctypes.windll.shell32
sh32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
print("hr", sh32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")), ctypes.byref(store)))
vt = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
get = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PK), ctypes.POINTER(PV))(vt[5])
for pid in (2, 3, 4, 5):
    k = PK(guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"), pid); v = PV()
    hr = get(store, ctypes.byref(k), ctypes.byref(v))
    print(pid, hr, v.vt, ctypes.wstring_at(v.val) if v.vt == 31 and v.val else None)
