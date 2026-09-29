#!/usr/bin/env python3
"""
Servidor Home — importa un modpack, enciende el servidor de Minecraft en este PC
y compártelo por internet con playit.gg (sin abrir puertos).

Sin dependencias externas: solo necesita Python 3.8+. Funciona en Linux y Windows.
Uso:
    Windows:  doble clic en «Servidor Home.bat»
    Linux:    bash iniciar.sh
    Directo:  python3 servidor_home.py [--lan] [--port 9000] [--no-browser]
"""

import argparse
import base64
import concurrent.futures
import hashlib
import hmac
import json
import math
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "Servidor Home"
APP_VERSION = "2.5.5"
IS_WINDOWS = os.name == "nt"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
# Instalada con el instalador de Windows: el programa vive en AppData y los servidores en Documentos.
INSTALLED = os.path.exists(os.path.join(BASE_DIR, "instalado.txt"))


def documents_dir():
    """Carpeta Documentos del usuario (en Windows la real, aunque esté movida a OneDrive)."""
    if IS_WINDOWS:
        try:
            import ctypes
            import uuid
            from ctypes import wintypes
            shell32 = ctypes.windll.shell32
            shell32.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE,
                                                     ctypes.POINTER(ctypes.c_wchar_p)]
            folder_id = ctypes.create_string_buffer(uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le, 16)
            path = ctypes.c_wchar_p()
            if shell32.SHGetKnownFolderPath(folder_id, 0, None, ctypes.byref(path)) == 0 and path.value:
                value = path.value
                ctypes.windll.ole32.CoTaskMemFree(path)
                return value
        except Exception:
            pass
    home = os.path.expanduser("~")
    for name in ("Documentos", "Documents"):
        if os.path.isdir(os.path.join(home, name)):
            return os.path.join(home, name)
    return home


if INSTALLED:
    DATA_DIR = os.path.join(documents_dir(), "servidor home")
    APPDATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)
else:
    DATA_DIR = APPDATA_DIR = BASE_DIR
SERVERS_DIR = os.path.join(DATA_DIR, "servidores")
UPLOADS_DIR = os.path.join(SERVERS_DIR, ".subidas")
SHARE_DIR = os.path.join(DATA_DIR, "compartir")          # zips de mods para los amigos
JAVA_DIR = os.path.join(APPDATA_DIR, "java")
# La versión portable guardaba Java en Documentos\servidor home\java: si existe, se reutiliza.
JAVA_DIRS = [JAVA_DIR] + ([os.path.join(DATA_DIR, "java")] if INSTALLED else [])
PLAYIT_DIR = os.path.join(APPDATA_DIR, "playit")
LOG_FILE = os.path.join(APPDATA_DIR, "servidor-home.log")
if IS_WINDOWS:
    WINDOW_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA") or APPDATA_DIR, APP_NAME, "ventana")
else:
    WINDOW_PROFILE = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                                  "servidor-home", "ventana")
META_FILE = "servidor-home.json"
STAGING_MARK = ".importando"
USER_AGENT = f"ServidorHome/{APP_VERSION} (panel casero de Minecraft)"
DEFAULT_PORT = 25565

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)            # Windows: sin ventanas negras
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def child_kwargs(detach=False):
    """Opciones para procesos hijos: en Windows sin ventana de consola; separados si detach."""
    if IS_WINDOWS:
        return {"creationflags": NO_WINDOW | (NEW_GROUP if detach else 0)}
    return {"start_new_session": True} if detach else {}


_JOB = None


def attach_to_job(proc):
    """Windows: mete el proceso en un 'Job' para que Windows lo cierre si la app se cierra de golpe
    (así no quedan servidores huérfanos ocupando el puerto)."""
    global _JOB
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _JOB is None:
            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IoCounters(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                            "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IoCounters),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            job = k32.CreateJobObjectW(None, None)
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                return
            _JOB = job
        k32.AssignProcessToJobObject(_JOB, int(proc._handle))
    except Exception:
        pass


def windows_process_image(pid):
    """Nombre del ejecutable de un PID en Windows (ej. 'java.exe'), o None si no existe."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, errors="replace", timeout=20, **child_kwargs()).stdout
        m = re.match(r'^"([^"]+)"', out.strip())
        return m.group(1).lower() if m else None
    except Exception:
        return None


def windows_pids_for_exe(exe_path):
    """PIDs de procesos que ejecutan exactamente ese .exe (para cerrar copias viejas de playit)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='{name}'\" | Where-Object {{ $_.ExecutablePath -eq '{path}' }} "
          "| ForEach-Object {{ $_.ProcessId }}").format(name=os.path.basename(exe_path),
                                                        path=os.path.abspath(exe_path).replace("'", "''"))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                             text=True, errors="replace", timeout=60, **child_kwargs()).stdout
        return [int(x) for x in out.split() if x.isdigit()]
    except Exception:
        return []


def windows_kill(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=20,
                       **child_kwargs())
    except Exception:
        pass

SERVER_TYPES = {
    "vanilla": {"label": "Vanilla", "desc": "Minecraft normal, sin mods.", "addons": None},
    "paper": {"label": "Paper", "desc": "Rápido y con plugins.", "addons": "plugins"},
    "fabric": {"label": "Fabric", "desc": "Mods de Fabric.", "addons": "mods"},
    "forge": {"label": "Forge", "desc": "Mods de Forge.", "addons": "mods"},
    "neoforge": {"label": "NeoForge", "desc": "Mods de NeoForge.", "addons": "mods"},
}

EDITABLE_PROPERTIES = [
    "motd", "server-port", "max-players", "gamemode", "difficulty", "hardcore",
    "online-mode", "pvp", "white-list", "level-seed", "level-type", "view-distance",
    "simulation-distance", "spawn-protection", "allow-flight", "enable-command-block",
]


# --------------------------------------------------------------------------- #
# Utilidades de red
# --------------------------------------------------------------------------- #

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url, timeout=30):
    return json.loads(http_get(url, timeout).decode("utf-8"))


_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn):
    """Cachea en memoria resultados de red (listas de versiones, etc.)."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def download(url, dest, log=None, expected_sha1=None, expected_sha256=None, expected_sha512=None, progress=None):
    """Descarga un archivo (con verificación opcional) mostrando el progreso.
    progress(hecho, total) se llama durante la descarga (para la barra de la interfaz)."""
    tmp = dest + ".part"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        last_bucket = 0
        last_report = 0.0
        hashes = {"sha1": hashlib.sha1(), "sha256": hashlib.sha256(), "sha512": hashlib.sha512()}
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            for h in hashes.values():
                h.update(chunk)
            done += len(chunk)
            if progress and total and time.time() - last_report > 0.25:
                last_report = time.time()
                try:
                    progress(done, total)
                except Exception:
                    pass
            if log and total and total > 2 * 1048576:
                bucket = done * 10 // total          # avisamos cada 10 %
                if bucket > last_bucket:
                    last_bucket = bucket
                    log(f"  descargando {os.path.basename(dest)}: {bucket * 10}% ({done // 1048576} de {total // 1048576} MB)")
    for name, expected in (("sha1", expected_sha1), ("sha256", expected_sha256), ("sha512", expected_sha512)):
        if expected and hashes[name].hexdigest() != expected.lower():
            os.remove(tmp)
            raise RuntimeError(f"La descarga de {os.path.basename(dest)} llegó dañada ({name} no coincide).")
    os.replace(tmp, dest)
    if progress and total:
        try:
            progress(total, total)
        except Exception:
            pass
    return dest


class Progress:
    """Avance de una tarea larga (crear, instalar, encender o arreglar) para la barra de carga.
    Se arma con fases que pesan distinto; cada fase avanza de 0 a 1 y la barra nunca retrocede."""

    def __init__(self, kind, phases):
        self.kind = kind
        total = float(sum(w for _k, _l, w in phases)) or 1.0
        self.phases = [(k, l, w / total) for k, l, w in phases]
        self.i = 0
        self.frac = 0.0
        self.label = self.phases[0][1] if self.phases else ""
        self.detail = ""
        self.started = time.time()
        self.lock = threading.Lock()
        self.last_pct = 0

    def has(self, key):
        return any(k == key for k, _l, _w in self.phases)

    def begin(self, key, label=None, detail=""):
        with self.lock:
            for n, (k, l, _w) in enumerate(self.phases):
                if k == key:
                    if n >= self.i:
                        self.i, self.frac = n, 0.0
                    self.label, self.detail = label or l, detail
                    return
            self.label, self.detail = label or self.label, detail

    def update(self, frac=None, detail=None, label=None):
        with self.lock:
            if frac is not None:
                self.frac = max(self.frac, min(1.0, float(frac)))
            if detail is not None:
                self.detail = detail
            if label is not None:
                self.label = label

    def pct(self):
        done = sum(w for _k, _l, w in self.phases[:self.i])
        cur = self.phases[self.i][2] if self.i < len(self.phases) else 0
        self.last_pct = max(self.last_pct, min(99, int((done + cur * self.frac) * 100)))
        return self.last_pct

    def to_json(self):
        return {"kind": self.kind, "pct": self.pct(), "label": self.label, "detail": self.detail,
                "step": min(self.i + 1, len(self.phases)), "steps": len(self.phases),
                "elapsed": int(time.time() - self.started)}


def mb_text(done, total):
    if total < 1048576:
        return f"{done // 1024} de {max(1, total // 1024)} KB"
    return f"{done // 1048576} de {max(1, total // 1048576)} MB"


def png_size(data):
    """(ancho, alto) de un PNG, o None si no es un PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def safe_filename(name):
    """Un nombre de archivo que sirve en Windows (sin \\ / : * ? " < > | ni puntos al final)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name or "")).strip(" .")
    return name[:80] or "servidor"


def prop_escape(value):
    """server.properties: lo que no es ASCII va como \\uXXXX (Minecraft lo lee bien en cualquier versión; así los
    colores § y las tildes del mensaje del servidor no salen como símbolos raros)."""
    return "".join(c if ord(c) < 128 else f"\\u{ord(c):04x}" for c in str(value))


def prop_unescape(value):
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), str(value))


def java_tuning_flags(ram_mb, custom=""):
    """Ajustes de Java probados para servidores de Minecraft (los «flags de Aikar», con G1): la limpieza de memoria
    hace pausas cortas y parejas, así el servidor no da tirones. Si el modpack o la persona ya eligieron su propio
    recolector de memoria, no se agregan (dos recolectores juntos impiden que Java arranque)."""
    if re.search(r"-XX:[+-]Use\w*GC\b", custom or ""):
        return []
    big = int(ram_mb) >= 12 * 1024
    return ["-XX:+IgnoreUnrecognizedVMOptions",          # si una versión de Java no conoce alguno, lo ignora
            "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled", "-XX:MaxGCPauseMillis=200",
            "-XX:+UnlockExperimentalVMOptions", "-XX:+DisableExplicitGC",
            f"-XX:G1NewSizePercent={40 if big else 30}", f"-XX:G1MaxNewSizePercent={50 if big else 40}",
            f"-XX:G1HeapRegionSize={16 if big else 8}M", f"-XX:G1ReservePercent={15 if big else 20}",
            "-XX:G1HeapWastePercent=5", "-XX:G1MixedGCCountTarget=4",
            f"-XX:InitiatingHeapOccupancyPercent={20 if big else 15}", "-XX:G1MixedGCLiveThresholdPercent=90",
            "-XX:G1RSetUpdatingPauseTimePercent=5", "-XX:SurvivorRatio=32", "-XX:+PerfDisableSharedMem",
            "-XX:MaxTenuringThreshold=1"]


def win_no_power_throttling(proc):
    """Windows 11 puede poner a un proceso sin ventana en «modo eficiencia» (EcoQoS) y bajarle la velocidad,
    sobre todo con batería. Al servidor de Minecraft eso le causa lag: se lo desactivamos."""
    if not IS_WINDOWS or proc is None:
        return False
    try:
        import ctypes

        class PPTS(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
        state = PPTS(1, 1, 0)       # versión 1; controlar EXECUTION_SPEED; estado 0 = sin reducir velocidad
        k32 = ctypes.windll.kernel32
        k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        return bool(k32.SetProcessInformation(ctypes.c_void_p(int(proc._handle)), 4, ctypes.byref(state),
                                              ctypes.sizeof(state)))           # 4 = ProcessPowerThrottling
    except Exception:
        return False


class KeepAwake:
    """Windows: mientras haya un servidor encendido, el PC no se suspende solo (la pantalla sí puede apagarse).
    Si el PC se duerme, el servidor se congela y tus amigos se desconectan."""

    def __init__(self):
        self.on = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import ctypes
        set_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_state.argtypes = [ctypes.c_uint32]
        while True:
            want = bool(running_servers())
            if want != self.on:
                # ES_CONTINUOUS | ES_SYSTEM_REQUIRED mientras haya servidores; solo ES_CONTINUOUS para soltarlo
                set_state(0x80000000 | (0x00000001 if want else 0))
                self.on = want
            time.sleep(15)


APP_USER_MODEL_ID = "ServidorHome.App"


def win_app_identity(hwnd):
    """La ventana es de Edge (modo aplicación): sin esto, Windows la agrupa con Edge y al anclarla a la barra de
    tareas ancla Edge. Le ponemos el nombre, el ícono y el comando de Servidor Home."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                        ("Data4", ctypes.c_ubyte * 8)]

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                        ("val", ctypes.c_void_p), ("val2", ctypes.c_void_p)]

        def guid(text):
            g = GUID()
            ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
            return g
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        store = ctypes.c_void_p()
        iid = guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")            # IPropertyStore
        if shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store)) != 0 or not store.value:
            return False
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtbl[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        exe = sys.executable
        if os.path.basename(exe).lower() == "python.exe" and os.path.exists(os.path.join(os.path.dirname(exe), "pythonw.exe")):
            exe = os.path.join(os.path.dirname(exe), "pythonw.exe")         # sin consola negra
        values = [(2, f'"{exe}" "{os.path.abspath(sys.argv[0])}"'),       # RelaunchCommand
                  (3, os.path.join(WEB_DIR, "icono.ico") + ",0"),           # RelaunchIconResource
                  (4, APP_NAME),                                            # RelaunchDisplayNameResource
                  (5, APP_USER_MODEL_ID)]                                   # AppUserModel.ID (al final)
        ok = True
        try:
            for pid, text in values:
                key = PROPERTYKEY(guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"), pid)
                buf = ctypes.create_unicode_buffer(text)
                pv = PROPVARIANT()
                pv.vt = 31                                                  # VT_LPWSTR
                pv.val = ctypes.cast(buf, ctypes.c_void_p)
                ok = set_value(store, ctypes.byref(key), ctypes.byref(pv)) == 0 and ok
            commit(store)
        finally:
            release(store)
        return ok
    except Exception:
        return False


def version_key(v):
    """Clave de orden aproximada para versiones tipo 1.20.1 / 21.1.172-beta / 1.21-rc1."""
    v = str(v or "")
    base, _, rest = v.partition("-")
    nums = [int(n) for n in re.findall(r"\d+", base)][:4]
    stable = 0 if re.search(r"(pre|rc|beta|alpha|snapshot|w\d)", v, re.I) else 1
    return (nums + [0] * (4 - len(nums)), stable, [int(n) for n in re.findall(r"\d+", rest)])


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def total_ram_mb():
    if IS_WINDOWS:
        try:
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile",
                                                       "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                                                       "ullAvailExtendedVirtual")]
            st = MemStatus()
            st.dwLength = ctypes.sizeof(st)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys // 1048576)
        except Exception:
            pass
        return 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    try:
        if sys.platform == "darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()) // 1048576
    except Exception:
        pass
    return 0


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "servidor"


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def stale_process(pid_file, check):
    """Devuelve el PID guardado si ese proceso sigue vivo y `check(pid)` confirma que es nuestro."""
    try:
        pid = int(_read_text(pid_file).strip() or 0)
    except ValueError:
        pid = 0
    if pid and pid_alive(pid):
        try:
            if check(pid):
                return pid
        except OSError:
            pass
    try:
        os.remove(pid_file)
    except OSError:
        pass
    return None


def lp(path):
    """Windows: permite rutas de más de 260 caracteres (algunos modpacks tienen carpetas muy profundas)."""
    if IS_WINDOWS and len(path) >= 240 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path


def safe_join(root, rel):
    """Une rutas impidiendo salir de root (protección contra zips maliciosos)."""
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or any(p == ".." for p in rel.split("/")):
        return None
    full = os.path.normpath(os.path.join(root, rel))
    if not (full == os.path.normpath(root) or full.startswith(os.path.normpath(root) + os.sep)):
        return None
    return full


# --------------------------------------------------------------------------- #
# Catálogo de versiones por tipo de servidor
# --------------------------------------------------------------------------- #

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def mojang_manifest():
    return cached("mojang", 600, lambda: http_json(MOJANG_MANIFEST))


def mojang_version_info(mc):
    def fetch():
        for v in mojang_manifest()["versions"]:
            if v["id"] == mc:
                return http_json(v["url"])
        raise RuntimeError(f"Mojang no reconoce la versión {mc}.")
    return cached("mojang:" + mc, 3600, fetch)


def java_for_mc(mc):
    """Versión de Java que exige Mojang para esa versión de Minecraft."""
    try:
        info = mojang_version_info(mc)
        return int(info.get("javaVersion", {}).get("majorVersion") or 8)
    except Exception:
        k = version_key(mc)[0]
        if k[0] >= 25:           # nuevo esquema de versiones de Mojang (26.1, ...)
            return 25
        minor, patch = k[1], k[2]
        if minor > 20 or (minor == 20 and patch >= 5):
            return 21
        if minor >= 18:
            return 17
        if minor == 17:
            return 16
        return 8


# Protección contra Log4Shell (CVE-2021-44228) para versiones antiguas: la misma que publicó Mojang.
LOG4J_XML_17_111 = """<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="WARN" packages="com.mojang.util">
    <Appenders>
        <Console name="SysOut" target="SYSTEM_OUT">
            <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level]: %msg%n" />
        </Console>
        <Queue name="ServerGuiConsole">
            <PatternLayout pattern="[%d{HH:mm:ss} %level]: %msg%n" />
        </Queue>
        <RollingRandomAccessFile name="File" fileName="logs/latest.log" filePattern="logs/%d{yyyy-MM-dd}-%i.log.gz">
            <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level]: %msg%n" />
            <Policies>
                <TimeBasedTriggeringPolicy />
                <OnStartupTriggeringPolicy />
            </Policies>
        </RollingRandomAccessFile>
    </Appenders>
    <Loggers>
        <Root level="info">
            <filters>
                <MarkerFilter marker="NETWORK_PACKETS" onMatch="DENY" onMismatch="NEUTRAL" />
                <RegexFilter regex="(?s).*\\$\\{[^}]*\\}.*" onMatch="DENY" onMismatch="NEUTRAL"/>
            </filters>
            <AppenderRef ref="SysOut"/>
            <AppenderRef ref="File"/>
            <AppenderRef ref="ServerGuiConsole"/>
        </Root>
    </Loggers>
</Configuration>
"""
LOG4J_XML_112_116 = (LOG4J_XML_17_111.replace("%msg%n", "%msg{nolookups}%n")
                     .replace('                <RegexFilter regex="(?s).*\\$\\{[^}]*\\}.*" onMatch="DENY" onMismatch="NEUTRAL"/>\n', ""))


def log4j_fix_args(t, mc, server_dir):
    """Argumentos de Java que protegen a las versiones antiguas del fallo Log4Shell (quien escribía cierto texto
    en el chat podía tomar control del PC). Las versiones nuevas ya vienen corregidas."""
    k = version_key(mc)[0]
    if k[0] != 1 or not re.match(r"^1\.\d+(\.\d+)?$", str(mc)):
        return []
    minor, patch = k[1], k[2]
    if minor == 17 or (minor == 18 and patch == 0):
        return ["-Dlog4j2.formatMsgNoLookups=true"]
    if t != "vanilla":
        return []       # Paper, Forge y Fabric corrigieron sus versiones antiguas en sus propias descargas
    if 12 <= minor <= 16:
        name, xml = "log4j2_112-116.xml", LOG4J_XML_112_116
    elif 7 <= minor <= 11:
        name, xml = "log4j2_17-111.xml", LOG4J_XML_17_111
    else:
        return []
    path = os.path.join(server_dir, name)
    if _read_text(path) != xml:
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
    return [f"-Dlog4j.configurationFile={name}"]


def list_vanilla(snapshots=False):
    """Todas las versiones que publica Mojang (de la más nueva a la más antigua)."""
    out = []
    for v in mojang_manifest()["versions"]:
        if v["type"] == "release" or (snapshots and v["type"] == "snapshot"):
            item = {"id": v["id"], "label": v["id"]}
            if v["type"] == "snapshot":
                item["snapshot"] = True
            out.append(item)
    return out


PAPER_FILL = "https://fill.papermc.io/v3/projects/paper"
PAPER_V2 = "https://api.papermc.io/v2/projects/paper"


def list_paper(snapshots=False):
    def fetch():
        try:
            data = http_json(PAPER_FILL)
            vs = data.get("versions", {})
            flat = []
            if isinstance(vs, dict):
                for group in vs.values():
                    flat.extend(group)
            else:
                flat = list(vs)
            return flat
        except Exception:
            return http_json(PAPER_V2).get("versions", [])
    versions = cached("paper", 600, fetch)
    versions = sorted(set(versions), key=version_key, reverse=True)
    out = []
    for v in versions:
        test = bool(re.search(r"(pre|rc|beta|alpha|snapshot)", v, re.I))
        if snapshots or not test:
            out.append({"id": v, "label": v, **({"snapshot": True} if test else {})})
    return out


def paper_download_info(mc):
    """Devuelve (url, nombre, sha256) de la última build estable de Paper."""
    try:
        builds = http_json(f"{PAPER_FILL}/versions/{mc}/builds")
        if isinstance(builds, dict):
            builds = builds.get("builds", [])
        if not builds:
            raise RuntimeError("sin builds")
        stable = [b for b in builds if str(b.get("channel", "")).upper() == "STABLE"] or builds
        b = max(stable, key=lambda x: int(x.get("id", x.get("build", 0))))
        dl = b["downloads"].get("server:default") or next(iter(b["downloads"].values()))
        return dl["url"], dl.get("name", "paper.jar"), dl.get("checksums", {}).get("sha256")
    except Exception:
        data = http_json(f"{PAPER_V2}/versions/{mc}/builds")
        builds = data.get("builds", [])
        stable = [b for b in builds if b.get("channel") == "default"] or builds
        b = stable[-1]
        app = b["downloads"]["application"]
        url = f"{PAPER_V2}/versions/{mc}/builds/{b['build']}/downloads/{app['name']}"
        return url, app["name"], app.get("sha256")


FABRIC_META = "https://meta.fabricmc.net/v2/versions"


def list_fabric(snapshots=False):
    games = cached("fabric:game", 600, lambda: http_json(f"{FABRIC_META}/game"))
    return [{"id": g["version"], "label": g["version"], **({} if g.get("stable") else {"snapshot": True})}
            for g in games if g.get("stable") or snapshots]


def fabric_loaders(mc=None):
    loaders = cached("fabric:loader", 600, lambda: http_json(f"{FABRIC_META}/loader"))
    out = []
    first_stable = next((l["version"] for l in loaders if l.get("stable")), None)
    for l in loaders:
        rec = l["version"] == first_stable
        out.append({"id": l["version"], "label": l["version"] + (" (recomendada)" if rec else ""), "recommended": rec,
                    "stable": bool(l.get("stable"))})
    return out


FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"


def _maven_versions(url):
    root = ET.fromstring(http_get(url + "/maven-metadata.xml"))
    return [v.text for v in root.iter("version") if v.text]


def forge_catalog():
    """{mc: [forge_version, ...]} solo para 1.12.2 en adelante."""
    def fetch():
        cat = {}
        for full in _maven_versions(FORGE_MAVEN):
            parts = full.split("-")
            if len(parts) != 2:     # formatos antiguos "mc-forge-mc" no soportados
                continue
            mc, fv = parts
            k = version_key(mc)[0]
            if k[0] == 1 and k[1] < 12:
                continue
            cat.setdefault(mc, []).append(fv)
        return cat
    return cached("forge", 1800, fetch)


def forge_promos():
    try:
        return cached("forge:promos", 1800, lambda: http_json(FORGE_PROMOS)).get("promos", {})
    except Exception:
        return {}


def list_forge(snapshots=False):
    cat = forge_catalog()
    out = []
    for mc in sorted(cat, key=version_key, reverse=True):
        test = bool(re.search(r"(pre|rc)", mc, re.I))
        if snapshots or not test:
            out.append({"id": mc, "label": mc, **({"snapshot": True} if test else {})})
    return out


def forge_loaders(mc):
    promos = forge_promos()
    rec = promos.get(f"{mc}-recommended")
    latest = promos.get(f"{mc}-latest")
    versions = sorted(forge_catalog().get(mc, []), key=version_key, reverse=True)
    if not rec and versions:
        rec = latest or versions[0]
    out = []
    for fv in versions:
        tag = " (recomendada)" if fv == rec else (" (última)" if fv == latest else "")
        out.append({"id": fv, "label": fv + tag, "recommended": fv == rec})
    return out


NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"


def neoforge_mc(nv):
    """Traduce la versión de NeoForge a la de Minecraft (21.1.172 -> 1.21.1)."""
    parts = re.findall(r"\d+", str(nv).split("-")[0])
    if len(parts) < 2:
        return None
    a, b = int(parts[0]), int(parts[1])
    if a < 25:
        return f"1.{a}" + (f".{b}" if b else "")
    # Esquema nuevo (Minecraft 26.1 y siguientes): 26.1.0.x -> 26.1, 26.1.1.x -> 26.1.1
    c = int(parts[2]) if len(parts) >= 4 else 0
    return f"{a}.{b}" + (f".{c}" if c else "")


def neoforge_catalog():
    def fetch():
        cat = {}
        for nv in _maven_versions(NEOFORGE_MAVEN):
            mc = neoforge_mc(nv)
            if mc:
                cat.setdefault(mc, []).append(nv)
        return cat
    return cached("neoforge", 1800, fetch)


def list_neoforge(snapshots=False):
    cat = neoforge_catalog()
    out = []
    for mc in sorted(cat, key=version_key, reverse=True):
        has_stable = any("beta" not in v and "alpha" not in v for v in cat[mc])
        if has_stable or snapshots:
            out.append({"id": mc, "label": mc + ("" if has_stable else " (solo beta)"),
                        **({} if has_stable else {"snapshot": True})})
    return out


def neoforge_loaders(mc):
    vs = sorted(neoforge_catalog().get(mc, []), key=version_key, reverse=True)
    out = []
    first_stable = next((v for v in vs if "beta" not in v and "alpha" not in v), vs[0] if vs else None)
    for v in vs:
        out.append({"id": v, "label": v + (" (recomendada)" if v == first_stable else ""), "recommended": v == first_stable})
    return out


LISTERS = {"vanilla": list_vanilla, "paper": list_paper, "fabric": list_fabric,
           "forge": list_forge, "neoforge": list_neoforge}
LOADERS = {"fabric": fabric_loaders, "forge": forge_loaders, "neoforge": neoforge_loaders}


def version_list(t, snapshots=False):
    """Versiones de Minecraft disponibles para ese tipo, de la más nueva a la más antigua;
    la versión estable más nueva va marcada con latest."""
    out = [dict(v) for v in LISTERS[t](snapshots)]
    for v in out:
        if not v.get("snapshot"):
            v["latest"] = True
            break
    return out


def check_version(t, mc, lv=None):
    """Revisa que exista esa versión (y la del loader) antes de crear o cambiar un servidor.
    Si no hay internet para consultarlo, no bloquea: la instalación dirá qué pasó."""
    label = SERVER_TYPES[t]["label"]
    try:
        ids = {v["id"] for v in version_list(t, snapshots=True)}
    except Exception:
        return
    if ids and mc not in ids:
        raise ValueError(f"No encontré la versión {mc} de Minecraft para {label}. Revisa que esté bien escrita "
                         f"o elige una de la lista.")
    if lv and t in LOADERS:
        try:
            lids = {v["id"] for v in LOADERS[t](mc)}
        except Exception:
            return
        if lids and lv not in lids:
            raise ValueError(f"No existe {label} {lv} para Minecraft {mc}.")


def recommended_loader(t, mc):
    lst = LOADERS[t](mc)
    if not lst:
        raise RuntimeError(f"No encontré versiones de {SERVER_TYPES[t]['label']} para Minecraft {mc}.")
    return next((l["id"] for l in lst if l.get("recommended")), lst[0]["id"])


# --------------------------------------------------------------------------- #
# Java: detectar o descargar automáticamente (Eclipse Temurin)
# --------------------------------------------------------------------------- #

ADOPTIUM_API = "https://api.adoptium.net/v3/binary/latest"


def java_major(java_bin):
    try:
        out = subprocess.run([java_bin, "-version"], capture_output=True, text=True, errors="replace",
                             timeout=30, **child_kwargs())
        text = out.stderr + out.stdout
        m = re.search(r'version "([^"]+)"', text)
        if not m:
            return None
        v = m.group(1)
        if v.startswith("1."):
            return int(v.split(".")[1])
        return int(re.match(r"\d+", v).group(0))
    except Exception:
        return None


def _java_ok(have, need):
    if have is None:
        return False
    if need <= 8:
        return have == 8          # Forge antiguo solo funciona con Java 8
    if need <= 16:
        return 16 <= have <= 17
    return have >= need


def _java_exe_name():
    return "java.exe" if IS_WINDOWS else "java"


def _find_java_in(folder):
    for root, _dirs, files in os.walk(folder):
        if _java_exe_name() in files and os.path.basename(root) == "bin":
            return os.path.join(root, _java_exe_name())
    return None


def system_java_candidates():
    cands = []
    w = shutil.which("java")
    if w:
        cands.append(w)
    if os.environ.get("JAVA_HOME"):
        cands.append(os.path.join(os.environ["JAVA_HOME"], "bin", _java_exe_name()))
    for base in ("/usr/lib/jvm", "/usr/java", "/Library/Java/JavaVirtualMachines", "/opt"):
        if os.path.isdir(base):
            for d in sorted(os.listdir(base)):
                for p in (os.path.join(base, d, "bin", "java"), os.path.join(base, d, "Contents", "Home", "bin", "java")):
                    if os.path.isfile(p):
                        cands.append(p)
    if IS_WINDOWS:
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            root = os.environ.get(env)
            for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "BellSoft", "Amazon Corretto", "Semeru"):
                vd = os.path.join(root, vendor) if root else ""
                if vd and os.path.isdir(vd):
                    for d in sorted(os.listdir(vd)):
                        p = os.path.join(vd, d, "bin", "java.exe")
                        if os.path.isfile(p):
                            cands.append(p)
    seen, out = set(), []
    for c in cands:
        rc = os.path.realpath(c)
        if rc not in seen and os.path.isfile(rc):
            seen.add(rc)
            out.append(c)
    return out


_java_lock = threading.Lock()


def ensure_java(need, log, progress=None):
    """Devuelve la ruta a un Java apto; si no hay, descarga Temurin en ./java/<versión>."""
    with _java_lock:
        for base in JAVA_DIRS:
            if os.path.isdir(os.path.join(base, str(need))):
                j = _find_java_in(os.path.join(base, str(need)))
                if j:
                    return j
        own = os.path.join(JAVA_DIR, str(need))
        cands = [(c, java_major(c)) for c in system_java_candidates()]
        for c, have in cands:
            if have == need:
                log(f"Usando Java {have} del sistema: {c}")
                return c
        for c, have in cands:
            if _java_ok(have, need):
                log(f"Usando Java {have} del sistema: {c}")
                return c
        found = ", ".join(str(h) for _, h in cands if h) or "ninguno"
        log(f"Este servidor necesita Java {need} (en el sistema: {found}). Descargando Java {need}...")
        os_name = {"linux": "linux", "darwin": "mac", "win32": "windows"}.get(sys.platform, "linux")
        arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "aarch64", "arm64": "aarch64",
                "armv7l": "arm"}.get(platform.machine().lower(), "x64")
        url = f"{ADOPTIUM_API}/{need}/ga/{os_name}/{arch}/jre/hotspot/normal/eclipse"
        os.makedirs(own, exist_ok=True)
        ext = ".zip" if os_name == "windows" else ".tar.gz"
        archive = os.path.join(JAVA_DIR, f"temurin-{need}{ext}")
        try:
            download(url, archive, log, progress=progress)
            if ext == ".zip":
                with zipfile.ZipFile(archive) as z:
                    z.extractall(own)
            else:
                with tarfile.open(archive) as t:
                    t.extractall(own)
        except Exception as e:
            shutil.rmtree(own, ignore_errors=True)
            raise RuntimeError(
                f"No pude descargar Java {need} ({e}). Instálalo a mano, por ejemplo: "
                f"sudo apt install openjdk-{need}-jre-headless") from e
        finally:
            if os.path.exists(archive):
                os.remove(archive)
        j = _find_java_in(own)
        if not j:
            raise RuntimeError("Se descargó Java pero no se encontró el ejecutable.")
        if not IS_WINDOWS:
            os.chmod(j, 0o755)
        log(f"Java {need} listo.")
        return j


# --------------------------------------------------------------------------- #
# server.properties
# --------------------------------------------------------------------------- #

def read_properties(path):
    props = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v
    return props


_props_cache = {}
_count_cache = {}


def read_properties_cached(path):
    """server.properties se lee en cada actualización de la pantalla: solo se vuelve a leer si cambió."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    hit = _props_cache.get(path)
    if not hit or hit[0] != key:
        hit = (key, read_properties(path))
        _props_cache[path] = hit
    return dict(hit[1])


def count_mod_files(folder):
    try:
        key = os.stat(folder).st_mtime_ns          # agregar, quitar o renombrar un mod cambia la carpeta
    except OSError:
        return 0
    hit = _count_cache.get(folder)
    if not hit or hit[0] != key:
        hit = (key, len(list_mod_files(folder)))
        _count_cache[folder] = hit
    return hit[1]


def write_properties(path, updates):
    """Actualiza claves conservando comentarios y el orden del archivo."""
    lines, seen = [], set()
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                raw = line.rstrip("\n")
                if raw and not raw.lstrip().startswith("#") and "=" in raw:
                    k = raw.split("=", 1)[0].strip()
                    if k in updates:
                        raw = f"{k}={updates[k]}"
                        seen.add(k)
                lines.append(raw)
    else:
        lines.append("#Minecraft server properties (creado por Servidor Home)")
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def clean_prop_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).replace("\n", " ").replace("\r", " ")


# --------------------------------------------------------------------------- #
# Consola (buffer de líneas con número de secuencia)
# --------------------------------------------------------------------------- #

class Console:
    def __init__(self, size=3000):
        self.size = size
        self.lines = []
        self.seq = 0
        self.lock = threading.Lock()

    def add(self, text, kind="out"):
        with self.lock:
            for part in str(text).splitlines() or [""]:
                self.seq += 1
                self.lines.append((self.seq, time.strftime("%H:%M:%S"), kind, part))
            if len(self.lines) > self.size:
                self.lines = self.lines[-self.size:]

    def since(self, n):
        with self.lock:
            return self.seq, [{"n": s, "t": t, "k": k, "s": l} for s, t, k, l in self.lines if s > n]

    def tail(self, count):
        with self.lock:
            return [l for _s, _t, _k, l in self.lines[-count:]]


# --------------------------------------------------------------------------- #
# Análisis de mods y modpacks
# --------------------------------------------------------------------------- #

# Mods conocidos que solo sirven en el cliente (gráficos, interfaz, sonido).
# Se desactivan al importar desde un launcher; en el servidor no aportan nada.
KNOWN_CLIENT_ONLY = {
    "oculus", "iris", "embeddium", "rubidium", "sodium", "sodium_extra", "sodiumextra",
    "reeses_sodium_options", "sodiumoptionsapi", "sodiumdynamiclights", "embeddiumplus",
    "magnesium_extras", "dynamiclights", "lambdynlights", "dynamic_fps", "dynamicfps",
    "betterf3", "notenoughanimations", "skinlayers3d", "entity_texture_features",
    "entity_model_features", "entityculling", "immediatelyfast", "fancymenu",
    "drippyloadingscreen", "controlling", "mousetweaks", "toastcontrol", "legendarytooltips",
    "betterthirdperson", "freecam", "chat_heads", "zoomify", "okzoomer", "citresewn",
    "continuity", "betterclouds", "cullleaves", "cull_less_leaves", "sound_physics_remastered",
    "presencefootsteps", "particlerain", "visuality", "fallingleaves", "euphoria_patcher",
    "craftpresence", "modmenu", "nvidium", "ambientsounds", "betteradvancements", "enchdesc",
    "catalogue", "fpsreducer", "blur", "betterpingdisplay", "gpudedicada",
    "smart_particles", "armor_hud", "weatherrefind",       # botaron el servidor de «kyalita world» (NeoForge 1.21.1)
}
# Mods que solo sirven en el servidor: no van en el zip de mods para los amigos.
KNOWN_SERVER_ONLY = {
    "luckperms", "dynmap", "bluemap", "squaremap", "pl3xmap", "servercore", "ledger", "fabricproxy-lite",
    "proxy_compatible_forge", "neoforwarding", "textile_backup", "dcintegration", "discord_integration",
}
# Dependencias que no son mods que se puedan activar o descargar.
NON_MOD_DEPS = {"minecraft", "neoforge", "forge", "fml", "javafml", "lowcodefml", "fabricloader", "fabric-loader",
                "java", "quilt_loader", "quilt_base"}

MC_VERSION_RE = re.compile(r"^(1\.\d+(\.\d+)?|2\d\.\d+(\.\d+)?)$")
# [[mods]], [[dependencies.x]] y también [tablas] sueltas; puede haber un comentario al final («[[mods]] #mandatory»)
TOML_HEADER_RE = re.compile(r"^[ \t]*(\[\[?)[ \t]*([^\[\]\n]+?)[ \t]*\]\]?[ \t]*(?:#[^\n]*)?$", re.M)
TOML_KV_RE = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*=\s*(\"[^\"\n]*\"|'[^'\n]*'|[^\s#]+)", re.M)


def _toml_blocks(text):
    """Lector mínimo de mods.toml: lista de (encabezado [[...]], {clave: valor})."""
    # muchos mods traen el archivo con líneas de Windows (\r\n): sin esto no se leía ni su modId (WeatherRefind)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # los textos de varias líneas (descripciones) pueden traer cualquier cosa, incluso «[[algo]]» o «modId=...»
    text = re.sub(r"'''.*?'''|\"\"\".*?\"\"\"", '""', text, flags=re.S)
    marks = [(m.start(), m.end(), (m.group(2).strip().strip('"') if m.group(1) == "[["
                                   else "tabla:" + m.group(2).strip()))
             for m in TOML_HEADER_RE.finditer(text)]
    segs, prev_end, prev_header = [], 0, ""
    for start, end, header in marks:
        segs.append((prev_header, text[prev_end:start]))
        prev_header, prev_end = header, end
    segs.append((prev_header, text[prev_end:]))
    out = []
    for header, body in segs:
        kv = {}
        for m in TOML_KV_RE.finditer(body):
            v = m.group(2)
            if v[:1] in "\"'":
                v = v[1:-1]
            kv.setdefault(m.group(1), v)
        out.append((header, kv))
    return out


def _range_lower(r):
    """Límite inferior de un rango de versiones ('[1.21.1,1.22)' -> '1.21.1', '>=1.20' -> '1.20')."""
    if r is None:
        return None
    if isinstance(r, list):
        vals = [_range_lower(x) for x in r]
        vals = [v for v in vals if v]
        return min(vals, key=version_key) if vals else None
    r = str(r).strip()
    if not r or r == "*":
        return None
    if r[0] in "[(":
        inner = r[1:].split(",")[0].rstrip("])").strip()
        return inner or None
    m = re.search(r"\d+\.\d+(?:\.\d+)?", r)
    return m.group(0) if m else None


def _next_version(v, level):
    """La primera versión que ya no calza: ('0.14.21', 1) -> '0.15.0'; ('1.2', 0) -> '2.0.0'."""
    nums = [int(n) for n in re.findall(r"\d+", v)][:3] + [0, 0, 0]
    nums = nums[:3]
    nums[level] += 1
    for i in range(level + 1, 3):
        nums[i] = 0
    return ".".join(map(str, nums))


def fabric_range_bounds(rng):
    """(mínimo, máximo excluido) que pide un mod de Fabric para otra dependencia: '>=0.14.8' -> ('0.14.8', None),
    '0.14.x' -> ('0.14.0', '0.15.0'), '~0.14.21' -> ('0.14.21', '0.15.0'), '<0.15' -> (None, '0.15').
    Una lista es «cualquiera de estas»: se toma lo más amplio."""
    if isinstance(rng, list):
        parts = [fabric_range_bounds(x) for x in rng] or [(None, None)]
        los = [lo for lo, _hi in parts]
        his = [hi for _lo, hi in parts]
        lo = None if any(x is None for x in los) else min(los, key=version_key)
        hi = None if any(x is None for x in his) else max(his, key=version_key)
        return lo, hi
    lo = hi = None
    for p in str(rng or "").split():
        p = p.strip()
        if p in ("", "*", "x", "X"):
            continue
        m = re.match(r"^(>=|<=|>|<|=|~|\^)?v?(\d+(?:\.(?:\d+|x|X|\*))*)", p)
        if not m:
            continue
        op, v = m.group(1) or "", m.group(2)
        wild = re.search(r"\.(?:x|X|\*)", v)
        base = re.sub(r"\.(?:x|X|\*).*$", "", v)
        nums = base.split(".")
        if wild or (not op and len(nums) < 3 and not re.search(r"[\-+]", p)):
            new_lo, new_hi = base, _next_version(base, max(0, len(nums) - 1))
        elif op in (">=", ">"):
            new_lo, new_hi = base, None
        elif op == "<":
            new_lo, new_hi = None, base
        elif op == "<=":
            new_lo, new_hi = None, _next_version(base, 2)
        elif op == "~":
            new_lo, new_hi = base, _next_version(base, 1 if len(nums) >= 2 else 0)
        elif op == "^":
            major = int(nums[0]) if nums[0].isdigit() else 0
            new_lo, new_hi = base, _next_version(base, 0 if major > 0 else 1)
        else:                                   # «=0.14.9» o «0.14.9»: esa versión exacta
            new_lo, new_hi = base, _next_version(base, 2)
        if new_lo and (lo is None or version_key(new_lo) > version_key(lo)):
            lo = new_lo
        if new_hi and (hi is None or version_key(new_hi) < version_key(hi)):
            hi = new_hi
    return lo, hi


def fabric_loader_bounds(infos, who=False):
    """Qué Fabric Loader aguantan estos mods: (el mínimo que pide el más exigente, el primer tope que ponen).
    Con who=True también dice qué mod pone cada límite: (mínimo, tope, mod del mínimo, mod del tope)."""
    lo = hi = lo_mod = hi_mod = None

    def up(v, name):
        nonlocal lo, lo_mod
        if v and (lo is None or version_key(v) > version_key(lo)):
            lo, lo_mod = v, name

    def down(v, name):
        nonlocal hi, hi_mod
        if v and (hi is None or version_key(v) < version_key(hi)):
            hi, hi_mod = v, name
    for info in infos:
        name = mod_label(info)
        for d in info.get("deps") or []:
            if d.get("id") not in ("fabricloader", "fabric-loader"):
                continue
            dlo, dhi = fabric_range_bounds(d.get("range"))
            if d.get("incompatible"):            # «breaks»: con esas versiones no funciona
                if dlo:
                    down(dlo, name)             # «>=0.15»: desde la 0.15 ya no sirve
                else:
                    up(dhi, name)               # «<0.14»: necesita la 0.14 o más nueva
                continue
            up(dlo, name)
            down(dhi, name)
    return (lo, hi, lo_mod, hi_mod) if who else (lo, hi)


# Fabric Loader 0.15 (diciembre de 2023) quitó la librería de mapeos que usaban mods viejos (por ejemplo Not Enough
# Crashes 4.1): los modpacks de Minecraft 1.20.1 o anteriores se hicieron con la 0.14.
FABRIC_ERA_LIMIT = ("1.20.2", "0.15")


def pick_fabric_loader(mc, infos=(), below=None, prefer=None, newer_than=None):
    """La versión de Fabric Loader para un modpack: la más nueva que cumpla lo que piden todos sus mods. Si el modpack
    es de Minecraft 1.20.1 o anterior y ningún mod pide la 0.15 o más nueva, la última 0.14. «prefer» es la versión
    con la que se juega el modpack en el launcher: si calza, se usa esa. «below»: tiene que ser anterior a esa;
    «newer_than»: tiene que ser más nueva que esa. None si ninguna calza (o si no hay lista de versiones)."""
    lo, hi = fabric_loader_bounds(infos)
    if mc and version_key(mc) < version_key(FABRIC_ERA_LIMIT[0]) and (not lo or version_key(lo) < version_key(FABRIC_ERA_LIMIT[1])):
        if hi is None or version_key(FABRIC_ERA_LIMIT[1]) < version_key(hi):
            hi = FABRIC_ERA_LIMIT[1]
    if below and (hi is None or version_key(below) < version_key(hi)):
        hi = below

    def fits(v):
        return ((not lo or version_key(v) >= version_key(lo)) and (not hi or version_key(v) < version_key(hi))
                and (not newer_than or version_key(v) > version_key(newer_than)))
    if prefer and fits(prefer) and not re.search(r"beta|alpha|rc|pre", prefer, re.I):
        return prefer
    # (en la lista de Fabric solo la más nueva viene marcada «stable»: las anteriores también son versiones normales;
    #  las de prueba se reconocen por el nombre, como 0.17.0-beta.1)
    cands = [l["id"] for l in fabric_loaders(mc) if not re.search(r"beta|alpha|rc|pre|snapshot", l["id"], re.I)]
    ok = [v for v in cands if fits(v)]
    return max(ok, key=version_key) if ok else None


def launcher_loader_version(path, mc=None):
    """La versión de Fabric con la que el launcher abrió ese modpack la última vez (según su registro), o None."""
    if not path:
        return None
    for lf in ("logs/latest.log", "logs/debug.log"):
        text = _read_text(os.path.join(path, lf), limit=400000)
        m = re.search(r"Loading Minecraft ([\w.\-+]+) with Fabric Loader ([\w.\-+]+)", text)
        if m and (not mc or m.group(1) == mc):
            return m.group(2)
    return None


def running_fabric_loader(text):
    """La versión de Fabric Loader que dice el registro del servidor («Loading Minecraft 1.18.2 with Fabric Loader
    0.19.5»), o None."""
    m = re.search(r"with Fabric Loader ([\w.\-+]+)", text) or re.search(r"fabric-loader-(\d+\.\d+\.\d+)\.jar", text)
    return m.group(1) if m else None


_scan_cache = {}


def scan_mod_jar(path):
    """Lee los metadatos de un mod (.jar): ids, nombres, loader, versión de Minecraft, dependencias y si es
    solo para el jugador. Se guarda en memoria mientras el archivo no cambie (un modpack grande tiene cientos)."""
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    hit = _scan_cache.get(path)
    if key is None or not hit or hit[0] != key:
        info = _scan_mod_jar(path)
        if key is not None:
            if len(_scan_cache) > 6000:
                _scan_cache.clear()
            _scan_cache[path] = (key, info)
    else:
        info = hit[1]
    out = dict(info)
    for k in ("ids", "names", "deps", "mixins"):
        out[k] = list(info.get(k) or [])
    return out


def _scan_mod_jar(path):
    info = {"file": os.path.basename(path), "loader": None, "ids": [], "names": [],
            "mc": None, "client_only": None, "version": None, "deps": [], "server_only": False,
            "display_test": None, "mixins": []}
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            toml_name = next((n for n in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml") if n in names), None)
            if toml_name:
                text = z.read(toml_name)[:512 * 1024].decode("utf-8", "replace")
                loader = "neoforge" if toml_name.endswith("neoforge.mods.toml") else "forge"
                mc_sides = []
                for header, kv in _toml_blocks(text):
                    if header == "mods":
                        if kv.get("modId"):
                            info["ids"].append(kv["modId"].lower())
                        if kv.get("displayName"):
                            info["names"].append(kv["displayName"])
                        if kv.get("version") and not info["version"]:
                            info["version"] = kv["version"]
                        if kv.get("displayTest"):
                            info["display_test"] = kv["displayTest"].upper()
                        if kv.get("clientSideOnly", "").lower() == "true":
                            info["client_only"] = "El mod se declara solo para el cliente."
                    elif header.startswith("dependencies"):
                        dep = kv.get("modId", "").lower()
                        side = (kv.get("side") or "BOTH").upper()
                        kind = (kv.get("type") or "").lower()
                        mandatory = kv.get("mandatory", "").lower()
                        required = kind == "required" if kind else (mandatory != "false")
                        if dep == "neoforge":
                            loader = "neoforge"
                        if dep == "minecraft":
                            mc_sides.append(side)
                            low = _range_lower(kv.get("versionRange"))
                            if low and MC_VERSION_RE.match(low):
                                info["mc"] = low
                        if dep:
                            info["deps"].append({"id": dep, "required": required, "side": side,
                                                 "incompatible": kind == "incompatible",
                                                 "range": kv.get("versionRange")})
                    elif header == "mixins" and kv.get("config"):
                        info["mixins"].append(kv["config"])
                    elif header == "":
                        if kv.get("displayTest") and not info["display_test"]:
                            info["display_test"] = kv["displayTest"].upper()
                        if kv.get("clientSideOnly", "").lower() == "true":
                            info["client_only"] = "El mod se declara solo para el cliente."
                # OJO: displayTest="IGNORE_SERVER_VERSION" NO quiere decir «solo cliente»: quiere decir que el
                # jugador no lo necesita (JEI, FTB Essentials, SmartBrainLib...). Esos sí van en el servidor.
                if mc_sides and all(s == "CLIENT" for s in mc_sides) and not info["client_only"]:
                    info["client_only"] = "El mod dice que solo necesita Minecraft en el lado del jugador."
                info["loader"] = loader
                if (info["version"] or "").startswith("${") and "META-INF/MANIFEST.MF" in names:
                    mf = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
                    mv = re.search(r"^Implementation-Version:\s*(\S+)", mf, re.M)
                    info["version"] = mv.group(1) if mv else None
            elif "fabric.mod.json" in names or "quilt.mod.json" in names:
                is_quilt = "fabric.mod.json" not in names
                raw = z.read("quilt.mod.json" if is_quilt else "fabric.mod.json").decode("utf-8", "replace")
                try:
                    data = json.loads(raw, strict=False)
                except ValueError:
                    data = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M), strict=False)
                if is_quilt:
                    info["loader"] = "quilt"
                    ql = data.get("quilt_loader", {})
                    info["ids"].append(str(ql.get("id", "")).lower())
                    env = (data.get("minecraft") or {}).get("environment")
                    env = {"dedicated_server": "server"}.get(env, env)
                    deps = {}
                    for d in ql.get("depends", []):
                        if isinstance(d, str):
                            deps[d] = (None, True)
                        elif isinstance(d, dict) and d.get("id"):
                            deps[d["id"]] = (d.get("versions"), not d.get("optional"))
                    mc = (deps.get("minecraft") or (None, True))[0]
                    for dep, (v, req) in deps.items():
                        info["deps"].append({"id": str(dep).lower(), "required": req, "side": "BOTH", "incompatible": False,
                                             "range": v})
                    for d in ql.get("breaks", []) if isinstance(ql.get("breaks"), list) else []:
                        if isinstance(d, dict) and d.get("id"):
                            info["deps"].append({"id": str(d["id"]).lower(), "required": False, "side": "BOTH",
                                                 "incompatible": True, "range": d.get("versions")})
                else:
                    info["loader"] = "fabric"
                    info["ids"].append(str(data.get("id", "")).lower())
                    info["version"] = str(data.get("version") or "") or None
                    if data.get("name"):
                        info["names"].append(str(data["name"]))
                    env = data.get("environment")
                    depends = data.get("depends") or {}
                    mc = depends.get("minecraft") if isinstance(depends, dict) else None
                    if isinstance(depends, dict):
                        for dep, rng in depends.items():
                            info["deps"].append({"id": str(dep).lower(), "required": True, "side": "BOTH",
                                                 "incompatible": False, "range": rng})
                    # «breaks»: con esas versiones de otro mod (o del loader) este mod no funciona
                    breaks = data.get("breaks") or {}
                    if isinstance(breaks, dict):
                        for dep, rng in breaks.items():
                            info["deps"].append({"id": str(dep).lower(), "required": False, "side": "BOTH",
                                                 "incompatible": True, "range": rng})
                mx = data.get("mixins") if not is_quilt else data.get("mixin")
                for x in (mx if isinstance(mx, list) else [mx] if mx else []):
                    cfg = x.get("config") if isinstance(x, dict) else x
                    if isinstance(cfg, str):
                        info["mixins"].append(cfg)
                if env == "client":
                    info["client_only"] = "El mod se declara solo para el cliente."
                elif env == "server":
                    info["server_only"] = True
                low = _range_lower(mc)
                if low and MC_VERSION_RE.match(low):
                    info["mc"] = low
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, TypeError, AttributeError):
        info["bad"] = True
    if not info["client_only"] and any(i in KNOWN_CLIENT_ONLY for i in info["ids"]):
        info["client_only"] = "Mod conocido que solo funciona en el cliente (gráficos/interfaz)."
    if any(i in KNOWN_SERVER_ONLY for i in info["ids"]):
        info["server_only"] = True
    return info


def server_required_deps(info):
    """Mods que este mod necesita sí o sí en el servidor (no cuenta Minecraft, el loader ni lo opcional)."""
    return [d["id"] for d in info.get("deps") or []
            if d.get("required") and not d.get("incompatible") and d.get("side", "BOTH") != "CLIENT"
            and d["id"] not in NON_MOD_DEPS]


def mod_label(info, fallback=""):
    return (info.get("names") or info.get("ids") or [fallback or info.get("file", "")])[0]


def resolve_client_only(infos, cands):
    """Ajusta la lista de mods que se van a desactivar por ser solo del jugador, mirando qué necesita cada mod.
    infos = {archivo: datos del mod}; cands = {archivo: (motivo, seguro)}. «seguro» = el propio mod (o la lista de
    mods conocidos) dice que es solo del jugador; si no, lo marcó solo CurseForge, que a veces se equivoca.
    - Si un mod que queda en el servidor necesita una librería marcada solo por CurseForge, la librería se queda.
    - Si un mod necesita (obligatorio, también en el servidor) un mod que de verdad es solo del jugador, ese mod
      tampoco puede ir en el servidor (por ejemplo Colorwheel, que necesita el mod de shaders Iris)."""
    by_id = {}
    for f, info in infos.items():
        for i in info.get("ids", []):
            by_id.setdefault(i, []).append(f)
    changed, rounds = True, 0
    while changed and rounds < 50:
        changed, rounds = False, rounds + 1
        for f, info in infos.items():
            if f in cands:
                continue
            for dep in server_required_deps(info):
                hits = [g for g in by_id.get(dep, []) if g != f]
                if not hits or any(g not in cands for g in hits):
                    continue                  # lo trae otro archivo que se queda, o no está: no cambia nada
                strong = [g for g in hits if cands[g][1]]
                if strong:
                    cands[f] = (f"Necesita {mod_label(infos[strong[0]], dep)}, que es solo para el jugador.", True)
                else:
                    for g in hits:
                        del cands[g]           # CurseForge lo marcó de cliente, pero otro mod lo necesita
                changed = True
                break
    return cands


def list_mod_files(mods_dir):
    if not os.path.isdir(mods_dir):
        return []
    return sorted(f for f in os.listdir(mods_dir) if f.lower().endswith(".jar") and os.path.isfile(os.path.join(mods_dir, f)))


def _loader_from_name(name):
    """'neoforge-21.1.77' / 'forge-47.2.0' / 'fabric-0.15.11-1.20.1' -> (tipo, versión)."""
    m = re.match(r"^(neoforge|forge|fabric|quilt)[-_ ]?([\w.+]+(?:-[\w.+]+)*)$", str(name or "").strip(), re.I)
    if not m:
        return None, None
    t, v = m.group(1).lower(), m.group(2)
    if t == "fabric":
        v = v.split("-")[0]
    if t == "forge" and re.match(r"^1\.\d+(\.\d+)?-", v):
        v = v.split("-", 1)[1]
    return t, v


LOG_PATTERNS = [
    (re.compile(r"neoForgeVersion,?\s*([\w.\-+]+)"), "neoforge", None),
    (re.compile(r"--fml\.forgeVersion,?\s*([\w.\-+]+)"), "forge", None),
    (re.compile(r"NeoForge mod loading, version ([\w.\-+]+), for MC ([\w.\-+]+)"), "neoforge", 2),
    (re.compile(r"(?<!Neo)Forge mod loading, version ([\w.\-+]+), for MC ([\w.\-+]+)"), "forge", 2),
    (re.compile(r"Loading Minecraft ([\w.\-+]+) with Fabric Loader ([\w.\-+]+)"), "fabric", -1),
    (re.compile(r"Loading Minecraft ([\w.\-+]+) with Quilt Loader ([\w.\-+]+)"), "quilt", -1),
]
LOG_MC_RE = re.compile(r"--fml\.mcVersion,?\s*([\w.\-+]+)")


def analyze_game_dir(root, launcher=None, mods_dir=None):
    """Averigua loader, versión de Minecraft y mods de una carpeta de juego o de servidor."""
    res = {"type": None, "mc_version": None, "loader_version": None, "detected_from": None,
           "installed": False, "client_only": [], "warnings": [], "mods_count": 0,
           "name": None, "ram_mb": None, "launcher": launcher}
    src = []

    def put(t=None, mc=None, lv=None, why=None):
        changed = False
        if t and not res["type"]:
            res["type"] = t
            changed = True
        if lv and not res["loader_version"] and (t is None or t == res["type"]):
            res["loader_version"] = lv
            changed = True
        if mc and not res["mc_version"] and MC_VERSION_RE.match(mc):
            res["mc_version"] = mc
            changed = True
        if changed and why and why not in src:
            src.append(why)

    files = set(os.listdir(root)) if os.path.isdir(root) else set()

    # 1) Servidor ya instalado dentro del pack (libraries/ + run.sh)
    nb = os.path.join(root, "libraries", "net", "neoforged", "neoforge")
    if os.path.isdir(nb):
        for v in sorted(os.listdir(nb), key=version_key, reverse=True):
            if os.path.exists(os.path.join(nb, v, "unix_args.txt")) or os.path.exists(os.path.join(nb, v, "win_args.txt")):
                put("neoforge", neoforge_mc(v), v, "servidor ya instalado")
                res["installed"] = res["type"] == "neoforge"
                break
    fb = os.path.join(root, "libraries", "net", "minecraftforge", "forge")
    if os.path.isdir(fb):
        for d in sorted(os.listdir(fb), key=version_key, reverse=True):
            if "-" in d and (os.path.exists(os.path.join(fb, d, "unix_args.txt")) or any(
                    j.endswith(".jar") for j in os.listdir(os.path.join(fb, d)))):
                mc, fv = d.split("-", 1)
                put("forge", mc, fv, "servidor ya instalado")
                res["installed"] = res["type"] == "forge" and (
                    os.path.exists(os.path.join(fb, d, "unix_args.txt"))
                    or any(f.startswith(f"forge-{d}") and f.endswith(".jar") and "installer" not in f for f in files))
                break
    if "fabric-server-launch.jar" in files:
        put("fabric", why="servidor ya instalado")
        res["installed"] = res["type"] == "fabric"

    # 2) Instaladores o lanzadores incluidos
    for f in sorted(files):
        m = re.match(r"^neoforge-([\w.+\-]+?)-installer\.jar$", f)
        if m:
            put("neoforge", neoforge_mc(m.group(1)), m.group(1), f)
        m = re.match(r"^forge-(\d+\.\d+(?:\.\d+)?)-([\w.+\-]+?)-installer\.jar$", f)
        if m:
            put("forge", m.group(1), m.group(2), f)
        m = re.match(r"^fabric-server-mc\.([\w.\-]+)-loader\.([\w.\-]+)-launcher\.[\w.\-]+\.jar$", f)
        if m:
            put("fabric", m.group(1), m.group(2), f)

    # 3) Archivos de configuración de los scripts de arranque
    if "variables.txt" in files:
        kv = dict(re.findall(r"^\s*([A-Z_]+)\s*=\s*\"?([^\"\r\n]*)\"?", _read_text(os.path.join(root, "variables.txt")), re.M))
        t = kv.get("MODLOADER", "").strip().lower()
        t = {"neoforge": "neoforge", "forge": "forge", "fabric": "fabric", "quilt": "quilt"}.get(t)
        put(t, kv.get("MINECRAFT_VERSION"), kv.get("MODLOADER_VERSION"), "variables.txt")
    if "server-setup-config.yaml" in files:
        y = _read_text(os.path.join(root, "server-setup-config.yaml"))
        mc = re.search(r"mcVersion:\s*[\"']?([\w.\-]+)", y)
        lv = re.search(r"loaderVersion:\s*[\"']?([\w.\-]+)", y)
        t = "neoforge" if "neoforge" in y.lower() else ("forge" if "forge" in y.lower() else ("fabric" if "fabric" in y.lower() else None))
        put(t, mc.group(1) if mc else None, lv.group(1) if lv else None, "server-setup-config.yaml")
    for f in sorted(files):
        if f.lower().endswith((".sh", ".bat", ".cmd", ".ps1")) and os.path.getsize(os.path.join(root, f)) < 200000:
            txt = _read_text(os.path.join(root, f))
            m = re.search(r"NEOFORGE_VERSION\s*=\s*\"?([\w.+\-]+)", txt)
            if m:
                put("neoforge", neoforge_mc(m.group(1)), m.group(1), f)
            m = re.search(r"\bFORGE_VERSION\s*=\s*\"?([\w.+\-]+)", txt)
            if m:
                put("forge", None, m.group(1), f)
            m = re.search(r"\b(?:MC_VERSION|MINECRAFT_VERSION)\s*=\s*\"?([\w.\-]+)", txt)
            if m:
                put(None, m.group(1), None, f)
            m = re.search(r"neoforge-([\w.+\-]+?)-installer\.jar", txt)
            if m and "$" not in m.group(1):
                put("neoforge", neoforge_mc(m.group(1)), m.group(1), f)
            m = re.search(r"forge-(1\.\d+(?:\.\d+)?)-([\w.+\-]+?)-installer\.jar", txt)
            if m and "$" not in m.group(2):
                put("forge", m.group(1), m.group(2), f)

    # 4) Metadatos de launchers
    cf = os.path.join(root, "minecraftinstance.json")
    if os.path.exists(cf):
        try:
            d = json.loads(_read_text(cf))
            bl = d.get("baseModLoader") or {}
            t, v = _loader_from_name(bl.get("name"))
            if t == "forge" and bl.get("forgeVersion"):
                v = bl["forgeVersion"]
            put(t, d.get("gameVersion") or bl.get("minecraftVersion"), v, "instancia de CurseForge")
            res["name"] = res["name"] or d.get("name")
            client_files = {}
            for a in d.get("installedAddons") or []:
                f = a.get("installedFile") or {}
                gv = f.get("gameVersion") or f.get("gameVersions") or []
                if "Client" in gv and "Server" not in gv:
                    for key in ("fileNameOnDisk", "fileName"):
                        if f.get(key):
                            client_files[f[key]] = "CurseForge lo marca solo para el cliente."
            res["_cf_client"] = client_files
        except (ValueError, OSError):
            pass
    for mmc in (os.path.join(os.path.dirname(root.rstrip(os.sep)), "mmc-pack.json"), os.path.join(root, "mmc-pack.json")):
        if os.path.exists(mmc):
            try:
                comps = {c.get("uid"): c.get("version") for c in json.loads(_read_text(mmc)).get("components", [])}
                mc = comps.get("net.minecraft")
                for uid, t in (("net.neoforged", "neoforge"), ("net.minecraftforge", "forge"),
                               ("net.fabricmc.fabric-loader", "fabric"), ("org.quiltmc.quilt-loader", "quilt")):
                    if comps.get(uid):
                        put(t, mc, comps[uid], "instancia de Prism/MultiMC")
                put(None, mc, None, "instancia de Prism/MultiMC")
                cfg = os.path.join(os.path.dirname(mmc), "instance.cfg")
                if os.path.exists(cfg):
                    m = re.search(r"^name=(.+)$", _read_text(cfg), re.M)
                    if m:
                        res["name"] = res["name"] or m.group(1).strip()
            except (ValueError, OSError):
                pass
            break
    mf = os.path.join(root, "manifest.json")
    if os.path.exists(mf):
        try:
            d = json.loads(_read_text(mf))
            if d.get("manifestType") == "minecraftModpack":
                mcinfo = d.get("minecraft") or {}
                primary = next((l for l in mcinfo.get("modLoaders", []) if l.get("primary")), None) or \
                    (mcinfo.get("modLoaders") or [{}])[0]
                t, v = _loader_from_name(primary.get("id"))
                put(t, mcinfo.get("version"), v, "manifest.json")
                res["name"] = res["name"] or d.get("name")
                if mcinfo.get("recommendedRam"):
                    res["ram_mb"] = int(mcinfo["recommendedRam"])
        except (ValueError, OSError):
            pass

    # 5) Registros del juego (si el modpack se abrió alguna vez)
    for lf in ("logs/latest.log", "logs/debug.log"):
        p = os.path.join(root, lf)
        if os.path.exists(p):
            head = _read_text(p, limit=400000)
            for rx, t, mc_group in LOG_PATTERNS:
                m = rx.search(head)
                if m:
                    if mc_group == -1:
                        put(t, m.group(1), m.group(2), "registro del juego")
                    elif mc_group:
                        put(t, m.group(2), m.group(1), "registro del juego")
                    else:
                        mm = LOG_MC_RE.search(head)
                        put(t, mm.group(1) if mm else None, m.group(1), "registro del juego")
            break

    # 6) Los propios mods
    mods_dir = mods_dir or os.path.join(root, "mods")
    mod_files = list_mod_files(mods_dir)
    res["mods_count"] = len(mod_files)
    votes, mcs = {}, []
    cf_client = res.pop("_cf_client", {})
    infos, cands = {}, {}
    for f in mod_files:
        info = scan_mod_jar(os.path.join(mods_dir, f))
        infos[f] = info
        if info.get("loader"):
            votes[info["loader"]] = votes.get(info["loader"], 0) + 1
        if info.get("mc"):
            mcs.append(info["mc"])
        if info.get("client_only"):
            cands[f] = (info["client_only"], True)
        elif cf_client.get(f):
            cands[f] = (cf_client[f], False)
    resolve_client_only(infos, cands)
    for f in mod_files:
        if f in cands:
            res["client_only"].append({"file": f, "name": mod_label(infos[f], f), "reason": cands[f][0]})
    if votes:
        best = max(votes, key=votes.get)
        # Un pack de NeoForge 1.20.1 usa mods de Forge: si el loader ya se sabe, se respeta.
        put(best, None, None, "análisis de los mods")
        if res["type"] and best != res["type"] and not (best == "forge" and res["type"] == "neoforge"):
            res["warnings"].append(f"La mayoría de los mods son de {SERVER_TYPES.get(best, {}).get('label', best)}, "
                                   f"pero se detectó {SERVER_TYPES.get(res['type'], {}).get('label', res['type'])}.")
    if mcs:
        put(None, max(mcs, key=version_key), None, "análisis de los mods")
    if res["type"] == "neoforge" and not res["mc_version"] and res["loader_version"]:
        put(None, neoforge_mc(res["loader_version"]), None)
    if res["type"] == "quilt":
        res["warnings"].append("Quilt no está soportado todavía; se intentará con Fabric (la mayoría de mods de Quilt no funcionarán).")
        res["type"] = "fabric"
        res["loader_version"] = None
    res["detected_from"] = ", ".join(src) if src else None
    if not res["type"]:
        res["type"] = "vanilla" if not mod_files else None
    if not res["ram_mb"]:
        n = len(mod_files)
        res["ram_mb"] = 3072 if n == 0 else 4096 if n < 60 else 6144 if n < 180 else 8192
    return res


def _read_text(path, limit=2 * 1024 * 1024):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _count_jars(mods):
    try:
        return sum(1 for f in os.listdir(mods) if f.lower().endswith(".jar"))
    except OSError:
        return 0


def launcher_roots():
    h = os.path.expanduser("~")
    j = os.path.join
    if IS_WINDOWS:
        ad = os.environ.get("APPDATA") or j(h, "AppData", "Roaming")
        return [
            ("CurseForge", [j(h, "curseforge", "minecraft", "Instances"),
                            j(h, "Documents", "curseforge", "minecraft", "Instances"),
                            j(h, "OneDrive", "Documents", "curseforge", "minecraft", "Instances"),
                            j(h, "OneDrive", "Documentos", "curseforge", "minecraft", "Instances")]),
            ("Prism Launcher", [j(ad, "PrismLauncher", "instances")]),
            ("MultiMC", [j(h, "MultiMC", "instances")]),
            ("Modrinth App", [j(ad, "ModrinthApp", "profiles"), j(ad, "com.modrinth.theseus", "profiles")]),
            ("ATLauncher", [j(ad, "ATLauncher", "instances"), j(h, "ATLauncher", "instances")]),
            ("GDLauncher", [j(ad, "gdlauncher_carbon", "data", "instances")]),
            ("SKLauncher", [j(h, ".sklauncher", "instances"), j(ad, ".sklauncher", "instances")]),
            ("TLauncher/Minecraft", [j(ad, ".minecraft")]),
        ]
    return [
        ("CurseForge", [j(h, "Documents", "curseforge", "minecraft", "Instances"),
                        j(h, "Documentos", "curseforge", "minecraft", "Instances"),
                        j(h, "curseforge", "minecraft", "Instances"),
                        j(h, ".local", "share", "curseforge", "minecraft", "Instances")]),
        ("SKLauncher", [j(h, ".sklauncher", "instances")]),
        ("Prism Launcher", [j(h, ".local", "share", "PrismLauncher", "instances"),
                            j(h, ".var", "app", "org.prismlauncher.PrismLauncher", "data", "PrismLauncher", "instances")]),
        ("MultiMC", [j(h, ".local", "share", "multimc", "instances"), j(h, "MultiMC", "instances")]),
        ("Modrinth App", [j(h, ".local", "share", "ModrinthApp", "profiles"),
                          j(h, ".local", "share", "com.modrinth.theseus", "profiles"),
                          j(h, ".var", "app", "com.modrinth.ModrinthApp", "data", "ModrinthApp", "profiles")]),
        ("ATLauncher", [j(h, ".local", "share", "ATLauncher", "instances"), j(h, "ATLauncher", "instances")]),
        ("TLauncher/Minecraft", [j(h, ".minecraft")]),
    ]


def game_dir_of(path):
    """Si la carpeta es la raíz de una instancia de Prism/MultiMC, devuelve su subcarpeta de juego."""
    for sub in ("minecraft", ".minecraft"):
        p = os.path.join(path, sub)
        if os.path.isdir(os.path.join(p, "mods")) or (os.path.isdir(p) and not os.path.isdir(os.path.join(path, "mods"))):
            return p
    return path


def find_instances():
    out = []
    for launcher, roots in launcher_roots():
        for root in roots:
            if not os.path.isdir(root):
                continue
            if launcher == "TLauncher/Minecraft":
                cands = [root]
            else:
                cands = [os.path.join(root, d) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
            for inst in cands:
                gd = game_dir_of(inst)
                n = _count_jars(os.path.join(gd, "mods"))
                if not n:
                    continue
                name = os.path.basename(inst.rstrip(os.sep))
                if launcher == "TLauncher/Minecraft":
                    name = ".minecraft"
                quick = ""
                cfj = os.path.join(gd, "minecraftinstance.json")
                if os.path.exists(cfj):
                    try:
                        d = json.loads(_read_text(cfj))
                        t, _v = _loader_from_name((d.get("baseModLoader") or {}).get("name"))
                        quick = f"{SERVER_TYPES.get(t, {}).get('label', t or '')} {d.get('gameVersion', '')}".strip()
                        name = d.get("name") or name
                    except ValueError:
                        pass
                try:
                    mtime = os.path.getmtime(os.path.join(gd, "mods"))
                except OSError:
                    mtime = 0
                out.append({"launcher": launcher, "name": name, "path": gd, "mods": n,
                            "summary": quick, "mtime": mtime})
    out.sort(key=lambda x: -x["mtime"])
    return out


# Carpetas y archivos de un launcher que el servidor no necesita.
INSTANCE_EXCLUDE = {
    "saves", "resourcepacks", "shaderpacks", "screenshots", "logs", "crash-reports", "options.txt",
    "optionsof.txt", "optionsshaders.txt", "options.amecsapi.txt", "servers.dat", "servers.dat_old",
    "usercache.json", "usernamecache.json", "journeymap", "xaero", "xaerowaypoints", "xaeroworldmap",
    ".mixin.out", "downloads", "minecraftinstance.json", "instance.cfg", "mmc-pack.json", "natives",
    "bin", "libraries", "versions", "assets", "server-resource-packs", "command_history.txt",
    "hotbar.nbt", "realms_persistence.json", "emotes", "essential", "replay_recordings", "replay_videos",
    ".fabric", ".cache", "cache", "profileimage", "instance.json", "modrinth.index.json", "icon.png",
    "local", "backups", "pcl", "launcher_profiles.json", "launcher_accounts.json", "webcache2",
    "tlauncher", "sklauncher", "profile.json", ".curseclient", "mods-desactivados",
}


def copy_instance(src, dst, log, progress=None):
    """Copia una instancia de launcher a la carpeta del servidor, sin lo que es solo del cliente."""
    entries = [e for e in os.listdir(src) if e.lower() not in INSTANCE_EXCLUDE and not e.lower().endswith(".log")]
    total, files = 0, []
    for e in entries:
        p = os.path.join(src, e)
        if os.path.isdir(p):
            for root, _dirs, fs in os.walk(p):
                os.makedirs(lp(os.path.join(dst, os.path.relpath(root, src))), exist_ok=True)
                for f in fs:
                    fp = os.path.join(root, f)
                    files.append(fp)
                    total += os.path.getsize(lp(fp)) if os.path.isfile(lp(fp)) else 0
        elif os.path.isfile(p):
            files.append(p)
            total += os.path.getsize(p)
    done, last = 0, -10
    for fp in files:
        rel = os.path.relpath(fp, src)
        out = os.path.join(dst, rel)
        os.makedirs(lp(os.path.dirname(out)), exist_ok=True)
        try:
            shutil.copy2(lp(fp), lp(out))
            done += os.path.getsize(lp(fp))
        except OSError as e:
            log(f"  no se pudo copiar {rel}: {e}", "err")
        pct = int(done * 100 / total) if total else 100
        if progress:
            progress(done, total or 1)
        if pct >= last + 10:
            last = pct - pct % 10
            log(f"  copiando archivos: {pct}%")
    log(f"Copiados {len(files)} archivos ({total // 1048576} MB).")


# --------------------------------------------------------------------------- #
# Diagnóstico de errores al arrancar
# --------------------------------------------------------------------------- #

def mod_index(mods_dir):
    """{modid: archivo} de los mods instalados."""
    out = {}
    for f in list_mod_files(mods_dir):
        for i in scan_mod_jar(os.path.join(mods_dir, f)).get("ids", []):
            if i:
                out[i] = f
    return out


# --------------------------------------------------------------------------- #
# Arreglos automáticos: leer por qué falló el servidor y cómo arreglarlo
# --------------------------------------------------------------------------- #

MODRINTH_API = "https://api.modrinth.com/v2"
MODRINTH_LOADERS = {"fabric": "fabric", "forge": "forge", "neoforge": "neoforge"}
# id del mod -> proyecto en Modrinth, cuando no se llaman igual
MOD_ALIASES = {
    "architectury": "architectury-api", "yet_another_config_lib_v3": "yacl", "yet-another-config-lib": "yacl",
    "forgeconfigapiport": "forge-config-api-port", "fabric": "fabric-api", "fabric_api": "fabric-api",
    "kotlinforforge": "kotlin-for-forge", "puzzleslib": "puzzles-lib", "resourcefullib": "resourceful-lib",
    "resourcefulconfig": "resourceful-config", "owo": "owo-lib", "cloth_config": "cloth-config",
    "bookshelf": "bookshelf-lib", "playeranimator": "playeranimator", "fzzy_config": "fzzy-config",
    "cristellib": "cristel-lib", "supermartijn642corelib": "supermartijn642s-core-lib",
    "supermartijn642configlib": "supermartijn642s-config-lib", "creativecore": "creativecore",
    "ferritecore": "ferrite-core",
}
# Mods de rendimiento para el servidor (no cambian cómo se juega): (id, nombre, ids que ya cumplen esa función)
PERF_MODS = {
    "fabric": [("lithium", "Lithium", ("lithium", "canary", "radium")), ("ferritecore", "FerriteCore", ("ferritecore",)),
               ("modernfix", "ModernFix", ("modernfix",))],
    "neoforge": [("modernfix", "ModernFix", ("modernfix",)), ("ferritecore", "FerriteCore", ("ferritecore",)),
                 ("lithium", "Lithium", ("lithium", "canary", "radium"))],
    "forge": [("modernfix", "ModernFix", ("modernfix",)), ("ferritecore", "FerriteCore", ("ferritecore",))],
}
LOADER_IDS = {"fabricloader", "fabric-loader", "forge", "neoforge", "fml", "javafml", "quilt_loader"}
# con estos se respalda el mundo antes de encender (los mods solo del jugador no agregan nada al mundo)
FIX_RISKY = ("update_mod", "disable_content", "update_loader", "downgrade_loader")
MAX_AUTO_FIXES = 20
MAX_CASCADE = 8        # si al quitar un mod que falla habría que quitar más mods que lo necesitan, se pregunta antes
MODS_REVISION = 1      # sube cuando cambia cómo se decide qué mods son solo del jugador (ver revisar_mods)
STUCK_WAIT = 25        # segundos que se espera a que Java se cierre solo después de fallar al encender
# Señales de que el servidor se cayó aunque Java terminó con código 0 (NeoForge/Forge terminan así si falla
# la carga de mods, y Minecraft si no acepta el EULA)
BOOT_FAIL_RE = re.compile(r"Failed to start the minecraft server|Crash report saved to|This crash report has been "
                          r"saved to|Mod loading has failed|Loading errors encountered|Encountered an unexpected "
                          r"exception|Considering it to be crashed|agree to the EULA|FAILED TO BIND TO PORT|"
                          r"Incompatible mods found|Exception in server tick loop")


class NeedsConfirmation(RuntimeError):
    """Un arreglo que la app no hace sola porque cambia mucho (se ofrece con el botón)."""


def new_chain():
    """Arreglos de un mismo intento de encender (se reinicia cuando la persona enciende o el servidor queda en línea)."""
    return {"done": set(), "count": 0, "log": [], "failed": {}, "backed_up": False, "needs_backup": False}


def _problem(key, title, text, fix=None, auto=False, label=None, mod=None):
    """mod: el nombre del mod que causó el problema (sale en el mensaje de error)."""
    p = {"key": key, "title": title, "text": text, "fix": fix, "auto": bool(fix) and auto, "label": label}
    if mod:
        p["mod"] = mod
    return p


def culprit_names(probs):
    """Los mods que causaron la caída, sin repetir, en el orden en que aparecen."""
    out = []
    for p in probs:
        if p.get("mod") and p["mod"] not in out:
            out.append(p["mod"])
    return out


def crash_message(probs, online=False, code=None):
    """El mensaje de error de una caída, con el mod que la causó si se sabe."""
    base = "El servidor se cayó" if online else "El servidor no pudo encender"
    names = culprit_names([p for p in probs if not p.get("suspect")])
    if names:
        return f"{base} por {'el mod' if len(names) == 1 else 'los mods'} {names_text(names)}."
    sus = culprit_names([p for p in probs if p.get("suspect")])
    if sus:
        return f"{base}; el error apunta {'al mod' if len(sus) == 1 else 'a los mods'} {names_text(sus)}."
    return base + (f" (código {code})." if code else ".")


def names_text(names, limit=3):
    """«A» / «A» y «B» / «A», «B», «C» y 2 más"""
    q = [f"«{n}»" for n in names]
    if len(q) > limit:
        q = q[:limit] + [f"{len(names) - limit} más"]
    return q[0] if len(q) == 1 else ", ".join(q[:-1]) + " y " + q[-1]


def _client_mod_culprit(text, idx):
    """El mod que intentó cargar cosas del cliente (Forge/NeoForge por «dist», Fabric por clases del cliente)."""
    if re.search(r"invalid dist DEDICATED_SERVER|Environment type CLIENT is invalid|client-side-only|onlyIn\(Dist\.CLIENT\)",
                 text, re.I):
        m = re.search(r"([^\n\]]+?) \(([a-z0-9_\-]+)\) has failed to load correctly", text)
        if m and m.group(2) in idx:
            return m.group(2)
        for cand in re.findall(r"TRANSFORMER/([a-z0-9_\-]+)@", text):
            if cand not in ("minecraft", "neoforge", "forge", "fml_loader", "mixinextras") and cand in idx:
                return cand
        for cand in re.findall(r"\bat [\w/]*?([a-z0-9_]+)@[\w.\-+]+/", text):
            if cand in idx and cand not in ("minecraft", "neoforge", "forge"):
                return cand
        return ""          # es un mod de cliente, pero no sabemos cuál
    # (sin los avisos «Error loading class: net/minecraft/class_5616 ...» de Mixin, que salen siempre y no botan nada)
    quiet = "\n".join(l for l in text.splitlines() if "Error loading class:" not in l and "@Mixin target" not in l)
    client_class = re.search(r"(NoClassDefFoundError|ClassNotFoundException)[:\s]+(net[./]minecraft[./](class_\d+|client[./])"
                             r"|com[./]mojang[./]blaze3d)", quiet)
    m = (re.search(r"Could not execute entrypoint stage '\w+' due to errors, provided by '([\w\-]+)'", text)
         or re.search(r"Mixin \[[^\]]+\] from mod ([\w\-]+) ", text))
    if m and client_class and m.group(1) in idx:
        return m.group(1)
    return None


def fmt_gb(mb):
    return f"{mb // 1024} GB" if mb % 1024 == 0 else f"{round(mb / 1024, 1)} GB"


def find_problems(lines, server=None, mods_dir=None, online=False):
    """Lee la consola de un servidor que falló y devuelve los problemas encontrados, en orden, cada uno con
    su arreglo. auto=True son arreglos seguros que la app aplica sola; el resto se ofrece con un botón.
    online=True: se cayó mientras funcionaba (ahí no se cambian mods solos; se reinicia)."""
    text = re.sub(r"§.", "", "\n".join(lines))
    meta = server.meta if server else {}
    mods_dir = mods_dir or (server.mods_dir if server else "")
    _idx = {}

    def idx():
        if not _idx:
            _idx.update(mod_index(mods_dir) if mods_dir else {})
            _idx.setdefault("__names__", {})
            for f in list_mod_files(mods_dir) if mods_dir else []:
                info = scan_mod_jar(os.path.join(mods_dir, f))
                for n in info.get("names", []):
                    if info.get("ids"):
                        _idx["__names__"][n.lower()] = info["ids"][0]
        return _idx

    def mod_id_of(name_or_id):
        v = str(name_or_id or "").strip().strip("'\"")
        if v.lower() in idx():
            return v.lower()
        return idx()["__names__"].get(v.lower(), v.lower() if re.match(r"^[\w\-]+$", v) else None)

    probs, seen = [], set()

    def add(p):
        if p["key"] not in seen:
            seen.add(p["key"])
            probs.append(p)

    has_world = bool(server and server.world_dirs())
    client_marks = set((meta.get("client_mods") or {}).keys())
    broken_marks = set((meta.get("broken_mods") or {}).keys())      # los que la app desactivó porque fallaban
    _dis = {}

    def dis_idx():
        """{modid: [(archivo .jar.disabled, datos)]}, la versión más nueva primero."""
        if "__listo__" not in _dis:
            _dis["__listo__"] = True
            try:
                files = [f for f in os.listdir(mods_dir) if f.lower().endswith(".jar.disabled")] if mods_dir else []
            except OSError:
                files = []
            for f in files:
                info = scan_mod_jar(os.path.join(mods_dir, f))
                if info.get("bad"):
                    continue
                for i in info.get("ids", []):
                    _dis.setdefault(i, []).append((f, info))
            for k, v in _dis.items():
                if k != "__listo__":
                    v.sort(key=lambda x: version_key(x[1].get("version") or "0"), reverse=True)
        return _dis

    def client_dep(dep):
        """¿Ese mod es solo del jugador? (conocido, declarado así, o ya desactivado por ser de cliente)"""
        if dep in KNOWN_CLIENT_ONLY:
            return True
        return any(info.get("client_only") or f[: -len(".disabled")] in client_marks for f, info in dis_idx().get(dep, []))

    def dep_fix(dep, requester=None, missing=True):
        dep = (dep or "").lower()
        if not dep or dep in ("java",):
            return
        if missing and dep not in LOADER_IDS and dep != "minecraft":
            who = f" (lo pide {requester})" if requester else ""
            if client_dep(dep):
                f = idx().get(requester) if requester else None
                if f and requester not in LOADER_IDS:
                    add(_problem(f"disable:{f}", f"Desactivando {requester} (necesita {dep}, que es solo del jugador)",
                                 f"«{requester}» necesita «{dep}», un mod solo para el jugador (gráficos o interfaz) que no "
                                 f"funciona en un servidor. Desactivo «{requester}» en el servidor; tus amigos lo pueden "
                                 "seguir usando en su juego.",
                                 {"type": "disable_client", "file": f, "reason": f"necesita {dep}, que es solo del jugador"},
                                 True, f"Desactivar {f} y reintentar"))
                else:
                    add(_problem(f"clientdep:{dep}", "", f"Un mod{who} necesita «{dep}», que es solo para el jugador. "
                                 "Desactiva en la pestaña Mods el mod que lo pide."))
                return
            if any(f[: -len(".disabled")] in broken_marks for f, _i in dis_idx().get(dep, [])):
                # lo que pide se desactivó porque fallaba: no se vuelve a activar; sin eso este mod tampoco carga
                f = idx().get(requester) if requester else None
                if f and requester not in LOADER_IDS:
                    nombre = mod_label(scan_mod_jar(os.path.join(mods_dir, f)), requester)
                    add(_problem(f"disable:{f}", f"Desactivando {nombre} (necesita {dep}, que falla)",
                                 f"«{nombre}» necesita «{dep}», que se desactivó porque fallaba al cargar; sin él tampoco puede "
                                 "cargar. Lo desactivo también (antes respaldo el mundo).",
                                 {"type": "disable_content", "file": f, "reason": f"necesita {dep}, que se desactivó porque fallaba"},
                                 True, f"Desactivar {f} y reintentar", mod=nombre))
                else:
                    add(_problem(f"brokendep:{dep}", "", f"Un mod{who} necesita «{dep}», que se desactivó porque fallaba al "
                                 "cargar. Desactiva en la pestaña Mods el mod que lo pide, o vuelve a activar el otro."))
                return
            found = dis_idx().get(dep)
            if found:
                f = found[0][0]
                add(_problem(f"enable:{f}", f"Reactivando {dep}{who}", f"El mod «{dep}» está desactivado en el servidor, "
                             f"pero hace falta{who}. Lo vuelvo a activar.", {"type": "enable_mod", "file": f, "for": requester},
                             True, f"Activar {dep} y reintentar"))
                return
        if dep == "minecraft":
            if requester:
                add(_problem(f"update:{requester}", f"Buscando una versión de {requester} para esta versión de Minecraft",
                             f"El mod «{requester}» es para otra versión de Minecraft. Busco su versión para "
                             f"Minecraft {meta.get('mc_version', '')}.", {"type": "update_mod", "mod": requester}, True,
                             f"Buscar {requester} para esta versión"))
            return
        if dep in LOADER_IDS:
            need = None
            if dep in ("fabricloader", "fabric-loader"):     # «requires version 0.15.0 or later of fabricloader»
                mm = re.search(r"requires (?:version |any version between )?(\d+\.\d+(?:\.\d+)?)[^\n]*? of (?:mod )?"
                               r"(?:'[^'\n]*' \()?fabric-?loader\b", text)
                need = mm.group(1) if mm else None
            add(_problem("loader", "Actualizando el loader", f"Un mod necesita una versión más nueva de "
                         f"{SERVER_TYPES.get(meta.get('type'), {}).get('label', 'loader')}.",
                         {"type": "update_loader", **({"min": need} if need else {})}, True,
                         "Actualizar el loader y reintentar"))
            return
        if missing:
            who = f" (lo pide {requester})" if requester else ""
            add(_problem(f"download:{dep}", f"Descargando {dep}{who}",
                         f"Falta el mod «{dep}»{who}. Lo busco en Modrinth para esta versión y lo agrego.",
                         {"type": "download_mod", "mod": dep, "for": requester}, True, f"Descargar {dep} y reintentar"))
        else:
            add(_problem(f"update:{dep}", f"Actualizando {dep}", f"El mod «{dep}» está en una versión que no sirve a "
                         f"otros mods. Busco otra versión en Modrinth.", {"type": "update_mod", "mod": dep}, True,
                         f"Actualizar {dep} y reintentar"))

    # --- EULA
    if re.search(r"agree to the EULA", text):
        add(_problem("eula", "Aceptando el EULA", "Falta aceptar el EULA de Minecraft.", {"type": "eula"},
                     bool(meta.get("eula")), "Aceptar el EULA y reintentar"))
    # --- puerto ocupado
    if re.search(r"FAILED TO BIND TO PORT|Address already in use", text):
        add(_problem("port", "Buscando un puerto libre", "Otro programa ya usa el puerto del servidor (quizás otro "
                     "servidor de Minecraft abierto). Lo paso a un puerto libre; la dirección de playit.gg no cambia.",
                     {"type": "port"}, True, "Usar otro puerto y reintentar"))
    # --- memoria
    if "OutOfMemoryError" in text:
        ram = int(meta.get("ram_mb") or 2048)
        cap = max(ram, (int(total_ram_mb() * 0.75) // 512) * 512)
        new = min(cap, ((ram + max(1024, ram // 2)) // 512) * 512)
        if new > ram:
            add(_problem(f"ram:{new}", f"Subiendo la RAM a {new // 1024 if new % 1024 == 0 else round(new / 1024, 1)} GB",
                         f"Al servidor le faltó memoria con {ram} MB. Le subo la RAM a {new} MB.",
                         {"type": "ram", "mb": new}, True, f"Subir la RAM a {new} MB y reintentar"))
        else:
            add(_problem("ram", "", "Al servidor le faltó memoria y este PC no tiene más RAM libre para darle. Cierra "
                         "otros programas o usa un modpack más liviano."))
    # --- Java
    m = re.search(r"class file version (\d+)(?:\.\d+)?\)", text)
    if m and "UnsupportedClassVersionError" in text:
        need = int(m.group(1)) - 44
        add(_problem(f"java:{need}", f"Descargando Java {need}", f"Un mod necesita Java {need}. Lo descargo y reintento.",
                     {"type": "java", "major": need}, need > int(meta.get("java_major") or 0), f"Usar Java {need} y reintentar"))
    elif re.search(r"Unsupported class file major version \d+", text) and meta.get("mc_version"):
        need = java_for_mc(meta["mc_version"])
        add(_problem(f"java:{need}", f"Usando Java {need}", f"La versión de Java no calza con este servidor: uso Java {need}, "
                     "la que pide esta versión de Minecraft.", {"type": "java", "major": need, "exact": True}, True,
                     f"Usar Java {need} y reintentar"))
    # --- Fabric Loader demasiado nuevo para mods antiguos: a un mod le falta algo que esa versión del loader ya no
    #     trae (la 0.15 quitó la librería de mapeos que usaba, por ejemplo, Not Enough Crashes 4.1)
    fabric_ran = bool(re.search(r"with Fabric Loader |at net\.fabricmc\.loader\.impl\.launch\.knot\.Knot\.", text))
    fatal = FATAL_RE.search(text)        # (desde la caída: antes puede haber avisos de mods que prueban si existe algo)
    lm = FABRIC_MISSING_RE.search(text, fatal.start() if fatal else 0) \
        if fabric_ran and meta.get("type") in ("fabric", None) else None
    if lm:
        missing = (lm.group(1) or lm.group(2)).replace("/", ".")
        cur = meta.get("loader_version") or running_fabric_loader(text)
        old_api = bool(FABRIC_OLD_API_RE.match(missing))
        mc = meta.get("mc_version")
        if old_api:
            below = FABRIC_ERA_LIMIT[1]
        elif cur and version_key(cur) >= version_key(FABRIC_ERA_LIMIT[1]):
            # otra parte del loader que cambió: se prueba con la versión anterior (o la 0.14 si el modpack es de esa época)
            old_pack = mc and version_key(mc) < version_key(FABRIC_ERA_LIMIT[0])
            below = FABRIC_ERA_LIMIT[1] if old_pack else ".".join(cur.split(".")[:2])
        else:
            below = None          # con un loader antiguo lo más probable es que el mod pida uno más nuevo
        if below and (not cur or version_key(cur) >= version_key(below)):
            who = _culprit_near(text, lm.start(), idx) if mods_dir else None
            f = idx().get(who) if who else None
            nombre = mod_label(scan_mod_jar(os.path.join(mods_dir, f)), who) if f else ""
            quien = f"El mod «{nombre}»" if f else "Un mod"
            porque = (f"es de antes de Fabric Loader {below} y usa una librería que Fabric dejó de traer desde esa versión"
                      if old_api else f"usa una parte de Fabric Loader que cambió en la versión {cur}")
            add(_problem(f"loader-old:{cur or '?'}", "Cambiando Fabric Loader a una versión que calce con los mods",
                         f"{quien} {porque}, así que el servidor no puede encender con Fabric Loader {cur or 'actual'}. "
                         "Cambio Fabric Loader por la versión más nueva que sirve para todos los mods (el mundo, los "
                         "mods y los ajustes no se tocan).",
                         {"type": "downgrade_loader", "below": below, "culprit": nombre}, True,
                         "Usar una versión anterior de Fabric Loader y reintentar", mod=nombre or None))
            if f:
                add(_problem(f"disable:{f}", "", f"Si prefieres quedarte con Fabric Loader {cur}, desactiva «{nombre}» "
                             f"({f}) en la pestaña Mods (lo que ese mod agregó al mundo se pierde; antes se hace un respaldo).",
                             {"type": "disable_content", "file": f}, False, f"Desactivar {f} y reintentar"))
    # --- mods que fallaron al cargar (NeoForge y Forge los listan todos juntos): los que son solo del jugador se
    #     desactivan todos de una vez; los demás se ven más abajo
    fails = [fl for fl in (failed_mods(text, idx, mods_dir) if mods_dir else []) if not fl["disabled"]]
    client_keys = set()
    for fl in fails:
        if not fl["client"]:
            continue
        if fl["file"]:
            client_keys.add(f"disable:{fl['file']}")
            add(_problem(f"disable:{fl['file']}", f"Desactivando {fl['name']} (es solo del jugador)",
                         f"El mod «{fl['name']}» ({fl['file']}) es solo para el jugador: usa partes del juego que el servidor "
                         "no tiene y lo botó. Se desactiva en el servidor; tus amigos lo pueden seguir usando en su juego.",
                         {"type": "disable_client", "file": fl["file"], "reason": "es solo del jugador"}, True,
                         f"Desactivar {fl['file']} y reintentar", mod=fl["name"]))
        else:
            add(_problem(f"client:{fl['id']}", "", f"El mod «{fl['name']}» ({fl['id']}) es solo para el jugador y botó el "
                         "servidor, pero no encontré su archivo en la carpeta mods: desactívalo en la pestaña Mods.",
                         mod=fl["name"]))
    # (Fabric sin lista de mods que fallaron: el que usó clases del cliente desde su entrada o un Mixin)
    culprit = _client_mod_culprit(text, idx()) if mods_dir and not fails else None
    if culprit:
        f = idx()[culprit]
        nombre = mod_label(scan_mod_jar(os.path.join(mods_dir, f)), culprit)
        add(_problem(f"disable:{f}", f"Desactivando {nombre} (es solo del jugador)",
                     f"El mod «{nombre}» ({f}) es solo para el jugador: usa partes del juego que el servidor no tiene y lo "
                     "botó. Se desactiva en el servidor; tus amigos lo pueden seguir usando en su juego.",
                     {"type": "disable_client", "file": f, "reason": "es solo del jugador"}, True,
                     f"Desactivar {f} y reintentar", mod=nombre))
    elif culprit == "":
        add(_problem("client", "", "Un mod solo para el cliente botó el servidor, pero el registro no dice cuál. Revisa "
                     "la consola (busca «invalid dist» o «client») y desactívalo en la pestaña Mods."))
    # --- Fabric: soluciones que propone el propio Fabric y detalles
    for m in re.finditer(r"Install ([\w\-]+), (?:any version|version [^\n]+?)\.?\s*$", text, re.M):
        dep_fix(m.group(1), None, True)
    for m in re.finditer(r"Replace mod '([^'\n]+)' \(([\w\-]+)\) \S+ with [^\n]+", text):
        dep_fix(m.group(2), None, False)
    # «... requires version 2.0 or later of libdep, which is missing!» / «... of mod 'Fabric API' (fabric-api), but only
    # the wrong version is present: 0.75.1!»
    for m in re.finditer(r"Mod '([^'\n]+)' \(([\w\-]+)\) \S+ requires [^\n]*? of (?:mod )?(?:'[^'\n]*' \()?([\w\-]+)\)?, "
                         r"which is missing", text):
        dep_fix(m.group(3), m.group(2), True)
    for m in re.finditer(r"Mod '([^'\n]+)' \(([\w\-]+)\) \S+ requires [^\n]*? of (?:mod )?(?:'[^'\n]*' \()?([\w\-]+)\)?, "
                         r"but only the wrong version is present", text):
        dep_fix(m.group(3), m.group(2), False)
    for m in re.finditer(r"Remove mod '([^'\n]+)' \(([\w\-]+)\)", text):
        mid = m.group(2)
        f = idx().get(mid)
        if f:
            info = scan_mod_jar(os.path.join(mods_dir, f))
            safe = bool(info.get("client_only")) or not has_world
            add(_problem(f"disable:{f}", f"Desactivando {mid} (no es compatible con otros mods)",
                         f"El mod «{mid}» no es compatible con otros mods del servidor." +
                         ("" if safe else " Si lo desactivas, lo que ese mod agregó al mundo se pierde: hay un respaldo antes."),
                         {"type": "disable_mod" if safe else "disable_content", "file": f}, safe, f"Desactivar {f} y reintentar"))
    # --- Forge / NeoForge: dependencias
    for m in re.finditer(r"Mod ID: '([\w\-]+)', Requested by: '([\w\-]+)', Expected range: '([^']*)', Actual version: '([^']*)'",
                         text):
        dep_fix(m.group(1), m.group(2), m.group(4).upper() in ("[MISSING]", "MISSING", ""))
    for m in re.finditer(r"Mod (.+?) requires ([\w\-]+) [^\n]*\n[^\n]*?Currently, \2 is (not installed|\S+)", text):
        dep_fix(m.group(2), mod_id_of(m.group(1)), m.group(3) == "not installed")
    # Forge 1.12: «Mod X (x) requires [y@[1.0,)]»
    for m in re.finditer(r"Mod [^\n(]*\(([\w\-]+)\) requires \[([\w\-]+)@", text):
        dep_fix(m.group(2), m.group(1).lower(), True)
    # --- dos mods que no funcionan juntos (Forge/NeoForge)
    for m in re.finditer(r"Mod (\S+) is incompatible with ([\w\-]+)", text):
        a, b = mod_id_of(m.group(1)), (m.group(2) or "").lower()
        fa, fb = idx().get(a or ""), idx().get(b)
        pick = None
        for mid, f in ((b, fb), (a, fa)):
            if f and (mid in KNOWN_CLIENT_ONLY or scan_mod_jar(os.path.join(mods_dir, f)).get("client_only")):
                pick = (mid, f)
                break
        if pick:
            add(_problem(f"disable:{pick[1]}", f"Desactivando {pick[0]} (es solo del jugador y choca con otro mod)",
                         f"«{a}» no funciona junto con «{b}». «{pick[0]}» es solo para el jugador: lo desactivo en el servidor.",
                         {"type": "disable_client", "file": pick[1], "reason": "chocaba con otro mod y es solo del jugador"},
                         True, f"Desactivar {pick[1]} y reintentar", mod=pick[0]))
        elif fb:
            add(_problem(f"disable:{fb}", "", f"«{a}» no funciona junto con «{b}». Desactiva uno de los dos en la pestaña "
                         "Mods (lo que ese mod agregó al mundo se pierde; antes se hace un respaldo).",
                         {"type": "disable_content", "file": fb}, False, f"Desactivar {fb} y reintentar"))
    # --- un .jar dañado (descarga cortada)
    for m in re.finditer(r"(?:ZipException|zip END header not found|invalid (?:LOC|CEN) header|Invalid or corrupt jarfile|"
                         r"error in opening zip file|zip file is empty|not a valid (?:zip|jar|mod) file)[^\n]*", text, re.I):
        near = text[max(0, m.start() - 400): m.end() + 400]
        for name in dict.fromkeys(re.findall(r"([^\s/\\'\"\[\]()]+\.jar)\b", near)):
            if mods_dir and os.path.isfile(os.path.join(mods_dir, name)):
                add(_problem(f"bad:{name}", f"Quitando {name} (el archivo está dañado)",
                             f"El archivo {name} está dañado (quizás la descarga se cortó). Lo desactivo; si otro mod lo "
                             "necesita, busco una copia buena.", {"type": "disable_bad", "file": name}, True,
                             f"Desactivar {name} y reintentar", mod=name))
                break
    # --- Java no pudo reservar la memoria pedida
    if re.search(r"Could not reserve enough space for|Invalid maximum heap size|Initial heap size set to a larger value|"
                 r"insufficient memory for the Java Runtime|Native memory allocation \(mmap\) failed|"
                 r"Too small (?:initial|maximum) heap", text):
        ram = int(meta.get("ram_mb") or 2048)
        new = max(1024, (min(int(ram * 0.75), int(total_ram_mb() * 0.6)) // 512) * 512)
        if new < ram:
            add(_problem(f"ram:{new}", f"Bajando la RAM a {fmt_gb(new)}", f"Java no pudo reservar {ram} MB de memoria "
                         f"(el PC no tiene tanta libre). Le bajo la RAM a {new} MB.", {"type": "ram", "mb": new}, True,
                         f"Bajar la RAM a {new} MB y reintentar"))
    # --- una opción de Java que esta versión no conoce
    m = re.search(r"Unrecognized VM option '([^'\n]+)'|Unrecognized option: (\S+)", text)
    if m and re.search(r"Could not create the Java Virtual Machine|Error: A fatal exception", text):
        opt = m.group(1) or m.group(2)
        add(_problem(f"jvmopt:{opt}", f"Quitando la opción de Java «{opt}»", f"Esta versión de Java no conoce la opción "
                     f"«{opt}» (de los argumentos extra de Java). La quito.", {"type": "jvm_option", "option": opt}, True,
                     f"Quitar «{opt}» y reintentar"))
    # --- faltan archivos del servidor o del loader (instalación incompleta)
    # (si Fabric Loader sí arrancó, que le falte una clase suya es cosa de un mod, no de la instalación)
    if (re.search(r"Could not find or load main class|Unable to access jarfile|could not open `[^'\n]*librar|"
                  r"ClassNotFoundException: (?:cpw\.mods|"
                  r"net\.minecraftforge\.(?:bootstrap|server)|net\.neoforged\.(?:fml|neoforge\.server))|"
                  r"NoSuchFileException: \S*librar|Missing (?:required )?librar(?:y|ies)|Failed to find system mod", text)
            or (not fabric_ran and re.search(r"ClassNotFoundException: net\.fabricmc\.loader", text))) \
            and meta.get("type"):
        add(_problem("reinstall", "Reinstalando los archivos del servidor", "Faltan archivos del servidor (la instalación "
                     "quedó a medias). Los vuelvo a instalar; el mundo y los mods no se tocan.", {"type": "reinstall"}, True,
                     "Reinstalar y reintentar"))
    # --- datos del modpack con errores
    if re.search(r"Failed to load datapacks|Errors in currently selected datapacks", text):
        add(_problem("datapacks", "", "Los datos del modpack (recetas, etiquetas o scripts) tienen errores y el mundo no "
                     "pudo cargar. Suele pasar si un mod no calza con la versión del modpack: busca en la consola el primer "
                     "error en rojo y el mod que nombra."))
    # --- mods repetidos
    if re.search(r"[Dd]uplicate mods?|Found \d+ duplicates? of|from mod files:", text):
        add(_problem("dedupe", "Quitando mods repetidos", "Hay mods repetidos (el mismo mod en dos archivos). Dejo solo "
                     "la versión más nueva.", {"type": "dedupe"}, True, "Quitar los repetidos y reintentar"))
    # --- archivo de configuración dañado
    if re.search(r"ParsingException|Failed loading config file|Failed to (?:load|parse|read) config", text):
        for name in dict.fromkeys(re.findall(r"([\w\-.]+\.(?:toml|json5?|cfg))", text)):
            rel = find_config_file(server.dir, name) if server else None
            if rel:
                add(_problem(f"config:{rel}", f"Reparando {name}", f"El archivo de configuración {name} está dañado. "
                             "Lo guardo aparte y el mod crea uno nuevo con los valores normales.",
                             {"type": "reset_config", "file": rel}, True, f"Restablecer {name} y reintentar"))
                break
    # --- el servidor se trabó (watchdog)
    if (re.search(r"A single server tick took|Considering it to be crashed", text)
            and not INJECTION_FAIL_RE.search(text)
            and not re.search(r"Exception in server tick loop|Exception ticking world", text)):
        # (si antes hubo un error de verdad, el vigilante solo saltó mientras el servidor se apagaba por ese error)
        add(_problem("maxtick", "Evitando que el vigilante corte el servidor", "Un momento de mucha carga (por ejemplo "
                     "generar terreno con mods) hizo que el vigilante de Minecraft cortara el servidor. Lo desactivo y reinicio.",
                     {"type": "max_tick"}, True, "Desactivar el vigilante y reiniciar"))
    # --- un mod con contenido falló al cargar: primero se busca una versión más nueva y, si no hay o sigue fallando,
    #     se desactiva (antes se respalda el mundo) para que el servidor encienda
    def broken(mid, f, nombre, err=""):
        porque = f" ({err})" if err else ""
        add(_problem(f"update:{mid}", f"Buscando una versión más nueva de {nombre}",
                     f"El mod «{nombre}» ({f}) falló al cargar{porque}. Busco una versión más nueva en Modrinth.",
                     {"type": "update_mod", "mod": mid}, True, f"Buscar otra versión de {nombre}", mod=nombre))
        add(_problem(f"disable:{f}", f"Desactivando {nombre} (falla al cargar)",
                     f"El mod «{nombre}» ({f}) falla al cargar{porque} y no hay una versión que funcione. Lo desactivo para "
                     "que el servidor encienda (antes respaldo el mundo); lo puedes volver a activar en la pestaña Mods. "
                     "Tus amigos también tienen que quitarlo de su juego para poder entrar.",
                     {"type": "disable_content", "file": f, "reason": "fallaba al cargar", "after": f"update:{mid}"}, True,
                     f"Desactivar {f} y reintentar", mod=nombre))

    content = [fl for fl in fails if not fl["client"]]
    if content and not any(p["fix"] for p in probs if p["key"] not in client_keys):
        for fl in content:
            if online or not fl["file"]:
                sospecha = _problem(f"suspect:{fl['id']}", "", f"El error viene del mod «{fl['name']}»" +
                                    (f" ({fl['file']})" if fl["file"] else f" ({fl['id']})") +
                                    (f": {fl['err']}" if fl["err"] else "") +
                                    (". Si se repite, desactívalo o busca una versión más nueva."
                                     if fl["file"] else ". No encontré su archivo: desactívalo en la pestaña Mods."),
                                    {"type": "disable_content", "file": fl["file"], "reason": "fallaba"} if fl["file"] else None,
                                    False, f"Desactivar {fl['file']} y reintentar", mod=fl["name"])
                sospecha["suspect"] = True
                add(sospecha)
            else:
                broken(fl["id"], fl["file"], fl["name"], fl["err"])
    elif not any(p["fix"] for p in probs):
        mid = _failed_mod(text, idx, mods_dir)
        suspect = None
        if not mid:
            m = re.search(r"Suspected Mods?:\s*\n?\s*[^\n(]*\(([a-z0-9_\-]+)\)", text)
            suspect = m.group(1) if m and m.group(1) in idx() and m.group(1) not in ("minecraft", "forge", "neoforge") else None
            if not suspect and mods_dir and FATAL_RE.search(text):
                suspect = _stack_suspect(text, idx, mods_dir)
        who = mid or suspect
        f = idx().get(who) if who else None
        nombre = mod_label(scan_mod_jar(os.path.join(mods_dir, f)), who) if f else who
        # una inyección de Mixin que falla bota el servidor la primera vez que se usa esa clase (puede ser justo
        # después de «Done» o al entrar un jugador) y siempre vuelve a pasar: se arregla igual que un mod que no carga
        definite = bool(mid and INJECTION_FAIL_RE.search(text))
        if mid and f and (not online or definite):
            if scan_mod_jar(os.path.join(mods_dir, f)).get("client_only"):
                add(_problem(f"disable:{f}", f"Desactivando {nombre} (es solo del jugador)",
                             f"El mod «{nombre}» ({f}) es solo para el jugador y falló en el servidor. Lo desactivo; tus "
                             "amigos lo pueden seguir usando en su juego.",
                             {"type": "disable_client", "file": f, "reason": "es solo del jugador y fallaba en el servidor"},
                             True, f"Desactivar {f} y reintentar", mod=nombre))
            else:
                broken(mid, f, nombre)
        elif who and f:
            # se ofrece desactivarlo con un botón (nunca solo: es lo que dice el rastro, no el loader); si el servidor
            # estaba encendido, primero se reinicia solo
            sospecha = _problem(f"suspect:{who}", "", f"El error apunta al mod «{nombre}» ({f}). Si se repite, busca una "
                                "versión más nueva de ese mod o desactívalo.",
                                {"type": "disable_content", "file": f, "reason": "el error de la caída apuntaba a este mod"},
                                False, f"Desactivar {f} y reintentar", mod=nombre)
            sospecha["suspect"] = True
            add(sospecha)
    # --- otros avisos
    if re.search(r"was saved in a newer version|Tried to load a DANGEROUS", text):
        add(_problem("world", "", "El mundo es de una versión más nueva de Minecraft que el servidor. Vuelve a la versión "
                     "anterior (Ajustes → Versión) o empieza un mundo nuevo."))
    if not probs:
        m = re.search(r"(?:This crash report has been saved to:|Crash report saved to:?)\s*(\S+)", text)
        if m:
            add(_problem("crash", "", f"El servidor se cayó. Revisa el informe: {m.group(1)}"))
    return probs


def _failed_mod(text, idx, mods_dir):
    """El mod que falló al cargar según el registro (por nombre, por su entrada o por su configuración de Mixin)."""
    pats = (r"\.json:[\w.$]+ from mod ([\w\-]+) failed injection check",
            r"([^\n\]]+?) \(([a-z0-9_\-]+)\) has failed to load correctly",
            r"Could not execute entrypoint stage '\w+' due to errors, provided by '([\w\-]+)'",
            r"Mixin \[[^\]]+\] from mod ([\w\-]+) ",
            r"Mixin apply for mod ([\w\-]+) failed",
            r"[Ee]rror (?:loading|constructing) (?:mod|class)[^\n]*?\(([a-z0-9_\-]+)\)")
    for p in pats:
        m = re.search(p, text)
        if m:
            mid = (m.group(m.lastindex) or "").lower()
            if mid in idx() and mid not in ("minecraft", "forge", "neoforge"):
                return mid
    m = re.search(r"(?:in config \[|Mixin \[)([\w.\-]+\.json)", text)
    if m and mods_dir:
        cfg = m.group(1)
        for f in list_mod_files(mods_dir):
            info = scan_mod_jar(os.path.join(mods_dir, f))
            if cfg in info.get("mixins", []) and info.get("ids"):
                return info["ids"][0] if info["ids"][0] in idx() else None
    # el error salió de una inyección de Mixin de un mod («handler$dmb000$notenoughcrashes$...»)
    m = FATAL_RE.search(text)
    if m:
        return _culprit_near(text, m.start(), idx, jars=False)
    return None


# Una inyección de Mixin que no encontró dónde entrar (siempre vuelve a fallar igual)
INJECTION_FAIL_RE = re.compile(r"Critical injection failure|failed injection check|InvalidInjectionException")
# Nombre que Fabric le pone a las inyecciones de Mixin de cada mod: handler$dmb000$<mod>$<método>
MIXIN_HANDLER_RE = re.compile(r"\b[A-Za-z]+\$[a-z]{3}\d{3}\$([a-z0-9_\-]+)\$\w")
# Dónde empieza la caída de verdad (lo de antes suelen ser avisos sin importancia)
FATAL_RE = re.compile(r"has crashed!|---- Minecraft Crash Report ----|Exception in server tick loop|Failed to start the "
                      r"minecraft server|Encountered an unexpected exception|Exception in thread \"main\"")
# A un mod le falta algo de Fabric Loader: la librería de mapeos que la 0.15 dejó de traer (Not Enough Crashes 4.1 y
# otros mods de esa época), una clase que ya no existe o un método que cambió
FABRIC_MISSING_RE = re.compile(r"(?:NoClassDefFoundError|ClassNotFoundException)[:\s]+(net[./]fabricmc[./](?:mapping|loader)[./][\w/.$]+)"
                               r"|NoSuchMethodError: '[\w.$\[\]<>]+ (net\.fabricmc\.loader\.[\w.$]+)\.[\w$<>]+\(")
FABRIC_OLD_API_RE = re.compile(r"^net[./]fabricmc[./](?:mapping[./]|loader[./]launch[./]common[./]MappingConfiguration)")


def _culprit_near(text, pos, idx, jars=True):
    """El mod que provocó un error, mirando el rastro que sigue al mensaje: el nombre de sus inyecciones de Mixin
    («handler$dmb000$notenoughcrashes$...») o (jars=True) su .jar en las líneas «at ... ~[mod.jar:?]»."""
    seg = text[pos: pos + 30000]
    ids = idx()
    for m in MIXIN_HANDLER_RE.finditer(seg):
        mid = m.group(1).lower()
        if mid in ids and mid not in ("minecraft", "fabricloader", "fabric-loader", "java", "__names__"):
            return mid
    if not jars:
        return None
    files = {f.lower(): mid for mid, f in ids.items() if mid != "__names__" and isinstance(f, str)}
    for m in re.finditer(r"\[([^\[\]\s:]+\.jar)(?::[^\]]*)?\]", seg):
        mid = files.get(m.group(1).lower())
        if mid:
            return mid
    return None


# El error de un mod es de «solo del jugador»: usa partes del juego que el servidor no tiene
CLIENT_ERR_RE = re.compile(r"invalid dist DEDICATED_SERVER|Environment type CLIENT is invalid|client-side-only|"
                           r"onlyIn\(Dist\.CLIENT\)|(?:NoClassDefFoundError|ClassNotFoundException)[:\s]+"
                           r"(?:net[./]minecraft[./](?:client[./]|class_\d+\b)|com[./]mojang[./]blaze3d)", re.I)
NOT_MODS = {"minecraft", "neoforge", "forge", "fml", "fml_loader", "javafml", "lowcodefml", "mixinextras",
            "fabricloader", "fabric-loader", "java", "mixin"}


def _trace(block, max_lines=40):
    """Las líneas de un error de Java (la excepción, «at ...», «Caused by») hasta la siguiente línea del registro."""
    out = []
    for line in block.splitlines()[:max_lines]:
        if out and re.match(r"^\[[^\]\n]*\] \[", line):
            break
        out.append(line)
    return "\n".join(out)


def _short_error(err):
    """La frase del error que mejor lo explica («NullPointerException: ...»), corta."""
    m = (re.search(r"Exception message: ([^\n]+)", err)
         or re.search(r"Caused by(?: \d+)?: ([^\n]+)", err)
         or re.search(r"\b((?:[\w$]+\.)+[\w$]*(?:Exception|Error)\b[^\n]*)", err))
    s = (m.group(1) if m else "").strip()
    s = re.sub(r"^(?:java\.lang\.|java\.util\.)", "", s)
    return (s[:157] + "…") if len(s) > 160 else s


def _jar_in(path, mods_dir):
    """El .jar de la carpeta mods que nombra una ruta del informe de error («Mod file: /C:/.../mods/x.jar»)."""
    path = urllib.parse.unquote(str(path or "")).replace("\\", "/")
    for m in re.finditer(r"/mods/([^/!]+?\.jar)", path):          # (si es un mod dentro de otro, el de afuera)
        if mods_dir and os.path.isfile(os.path.join(mods_dir, m.group(1))):
            return m.group(1)
    name = path.rsplit("/", 1)[-1]
    return name if name.endswith(".jar") and mods_dir and os.path.isfile(os.path.join(mods_dir, name)) else None


def _mod_list_file(text, mid, mods_dir):
    """El .jar de un mod según la tabla «Mod List» del informe de NeoForge/Forge (ahí el nombre puede venir cortado)."""
    if not mods_dir:
        return None
    m = re.search(r"^[ \t]+([^|\n]+?)[ \t]*\|[^|\n]*\|[ \t]*" + re.escape(mid) + r"[ \t]*\|", text, re.M)
    if not m:
        return None
    start = m.group(1).strip()
    files = list_mod_files(mods_dir)
    return next((f for f in files if f == start), None) or next((f for f in files if f.startswith(start)), None)


_pkg_cache = {}
# paquetes del juego, del loader y de librerías comunes: no son «el mod culpable»
NOT_MOD_PACKAGES = ("java.", "javax.", "jdk.", "sun.", "com.sun.", "net.minecraft.", "com.mojang.", "net.neoforged.",
                    "net.minecraftforge.", "cpw.mods.", "net.fabricmc.", "org.spongepowered.", "com.llamalad7.",
                    "com.google.", "it.unimi.", "io.netty.", "org.apache.", "org.slf4j.", "org.objectweb.", "kotlin.",
                    "kotlinx.", "scala.", "org.lwjgl.", "oshi.", "net.jodah.", "com.electronwill.", "org.openjdk.",
                    "MC-BOOTSTRAP", "TRANSFORMER")


def _jar_packages(path):
    """Los paquetes de clases que trae un .jar (se guarda en memoria mientras el archivo no cambie)."""
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return set()
    hit = _pkg_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    pk = set()
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.endswith(".class") and "/" in n and not n.startswith(("META-INF/", "META-INF\\")):
                    pk.add(n.rsplit("/", 1)[0].replace("/", "."))
    except (zipfile.BadZipFile, OSError, ValueError):
        pass
    if len(_pkg_cache) > 4000:
        _pkg_cache.clear()
    _pkg_cache[path] = (key, pk)
    return pk


def _stack_suspect(text, idx, mods_dir):
    """El mod que aparece primero en el rastro de la caída, empezando por la causa más de adentro («Caused by»):
    por su «TRANSFORMER/mod@», su .jar («~[mod.jar:?]») o el paquete de sus clases. None si no hay ninguno."""
    m = FATAL_RE.search(text)
    seg = text[m.start(): m.start() + 60000] if m else text[-60000:]
    ids = {k: v for k, v in idx().items() if k != "__names__"}
    files = {f.lower(): mid for mid, f in ids.items()}
    jars = list_mod_files(mods_dir) if mods_dir else []
    for block in reversed(re.split(r"\n\s*Caused by(?: \d+)?: ", seg)):
        for mm in re.finditer(r"TRANSFORMER/([a-z0-9_\-.]+)@", block):
            if mm.group(1) in ids and mm.group(1) not in NOT_MODS:
                return mm.group(1)
        for mm in re.finditer(r"\[([^\[\]\s:]+\.jar)(?::[^\]]*)?\]", block):
            if files.get(mm.group(1).lower()):
                return files[mm.group(1).lower()]
        for mm in re.finditer(r"^\s+at (?:[^\s/]+/)*([\w$.]+)\.[\w$<>]+\(", block, re.M):
            cls = mm.group(1)
            if cls.startswith(NOT_MOD_PACKAGES) or "." not in cls:
                continue
            pkg = cls.rsplit(".", 1)[0]
            for f in jars:
                if pkg in _jar_packages(os.path.join(mods_dir, f)):
                    got = scan_mod_jar(os.path.join(mods_dir, f)).get("ids") or []
                    if got and got[0] not in NOT_MODS:
                        return got[0]
    return None


def failed_mods(text, idx, mods_dir):
    """Los mods que el loader dice que fallaron al cargar: [{id, name, file, client, err}]. «client» = el error es
    porque el mod usa partes del juego que el servidor no tiene (es solo del jugador). Lee el resumen de NeoForge
    («Loading errors encountered: - X (x) has failed to load correctly»), las secciones del informe de error
    («-- Mod loading issue for: x --» / «-- MOD x --», con «Mod file: ...»), «Failed to create mod instance.
    ModID: x» y, en Fabric, «Could not execute entrypoint stage ... provided by 'x'»."""
    found = {}

    def put(mid, name=None, file=None, err=""):
        mid = (mid or "").strip().lower()
        if not mid or mid in NOT_MODS:
            return
        e = found.setdefault(mid, {"name": None, "file": None, "err": ""})
        name = re.sub(r"^[\s\-:]+", "", (name or "").split(": ")[-1]).strip().strip("'\"")
        if name and not e["name"]:
            e["name"] = name
        if file and not e["file"]:
            e["file"] = file
        if err and len(e["err"]) < 8000:
            e["err"] += "\n" + err

    # secciones del informe de error de NeoForge («-- Mod loading issue for: x --») y de Forge («-- MOD x --»)
    for m in re.finditer(r"^-- (?:Mod loading issue for: |MOD )([\w\-.]+) --[ \t]*\n(.*?)(?=^-- |^Stacktrace:|\Z)",
                         text, re.M | re.S):
        body = m.group(2)
        if "has failed to load correctly" not in body and "Exception message" not in body:
            continue                          # (las de dependencias que faltan las ve el resto de find_problems)
        fm = re.search(r"Mod [Ff]ile: ([^\n]+?\.jar)", body)
        nm = re.search(r"Failure message: (.+?) \([\w\-.]+\) has failed", body)
        put(m.group(1), nm.group(1) if nm else None, _jar_in(fm.group(1), mods_dir) if fm else None, body[:3000])
    # el resumen del final del registro de NeoForge, con la excepción de cada uno debajo
    for m in re.finditer(r"^[ \t]*- (.+?) \(([\w\-.]+)\) has failed to load correctly[ \t]*\n((?:[ \t]{2,}\S[^\n]*\n?){0,4})",
                         text, re.M):
        put(m.group(2), m.group(1), None, m.group(3))
    # líneas sueltas «X (x) has failed to load correctly» y el rastro que sigue
    for m in re.finditer(r"([^\n\]]+?) \(([\w\-.]+)\) has failed to load correctly[^\n]*\n((?:[^\n]*\n?){0,30})", text):
        put(m.group(2), m.group(1), None, _trace(m.group(3)))
    for m in re.finditer(r"Failed to create mod instance\. ModID: ([\w\-.]+)[^\n]*\n((?:[^\n]*\n?){0,40})", text):
        put(m.group(1), None, None, _trace(m.group(2)))
    # Fabric: el mod cuya entrada falló
    for m in re.finditer(r"Could not execute entrypoint stage '\w+' due to errors, provided by '([\w\-.]+)'[^\n]*\n"
                         r"((?:[^\n]*\n?){0,60})", text):
        put(m.group(1), None, None, _trace(m.group(2), 60))
    ids = idx()
    out = []
    for mid, e in found.items():
        f = e["file"] or (ids.get(mid) if mid != "__names__" else None) or _mod_list_file(text, mid, mods_dir)
        info = scan_mod_jar(os.path.join(mods_dir, f)) if f and mods_dir else {}
        client = bool(CLIENT_ERR_RE.search(e["err"])) or bool(info.get("client_only")) or mid in KNOWN_CLIENT_ONLY
        gone = not f and mods_dir and any(
            mid in scan_mod_jar(os.path.join(mods_dir, d)).get("ids", [])
            for d in os.listdir(mods_dir) if d.lower().endswith(".jar.disabled"))
        out.append({"id": mid, "name": e["name"] or (mod_label(info, mid) if info else mid), "file": f, "client": client,
                    "err": _short_error(e["err"]), "disabled": bool(gone)})
    return out


def diagnose_log(lines, mods_dir):
    """Compatibilidad: el primer problema como consejo {text, action}."""
    probs = find_problems(lines, None, mods_dir)
    return hint_of(probs)


def hint_of(probs):
    if not probs:
        return None
    first = next((p for p in probs if p["fix"]), probs[0])
    hint = {"text": first["text"]}
    if first["fix"]:
        hint["action"] = dict(first["fix"], label=first["label"] or "Arreglar y reintentar")
    return hint


def find_config_file(server_dir, name):
    for base in ("config", "defaultconfigs", os.path.join("world", "serverconfig"), "serverconfig"):
        root = os.path.join(server_dir, base)
        if not os.path.isdir(root):
            continue
        for r, _dirs, files in os.walk(root):
            if name in files:
                return os.path.relpath(os.path.join(r, name), server_dir)
    return None


def free_port(start=25566, avoid=()):
    for port in range(start, start + 200):
        if port in avoid:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
            try:
                sk.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No encontré un puerto libre.")


def dedupe_mods(mods_dir, log=None):
    """Si el mismo mod está dos veces, deja la versión más nueva y desactiva las otras."""
    by_id = {}
    for f in list_mod_files(mods_dir):
        info = scan_mod_jar(os.path.join(mods_dir, f))
        for i in info.get("ids", [])[:1]:
            if i and i not in LOADER_IDS:
                by_id.setdefault(i, []).append((f, info.get("version")))
    done = []
    for mod_id, files in by_id.items():
        if len(files) < 2:
            continue
        files.sort(key=lambda x: (version_key(x[1] or "0"), os.path.getmtime(os.path.join(mods_dir, x[0]))), reverse=True)
        keep = files[0][0]
        for f, _v in files[1:]:
            os.replace(os.path.join(mods_dir, f), os.path.join(mods_dir, f + ".disabled"))
            done.append(f"Quité {f} (repetido: me quedo con {keep})")
            if log:
                log(f"Mod repetido: {mod_id}. Dejo {keep} y desactivo {f}.")
    return done


def modrinth_projects(mod_id, loader):
    slugs = [MOD_ALIASES.get(mod_id), mod_id, mod_id.replace("_", "-")]
    try:
        q = urllib.parse.urlencode({"query": mod_id.replace("_", " "), "limit": 5,
                                    "facets": json.dumps([["project_type:mod"], [f"categories:{loader}"]])})
        slugs += [h.get("slug") for h in http_json(f"{MODRINTH_API}/search?{q}", timeout=20).get("hits", [])]
    except Exception:
        pass
    return [x for x in dict.fromkeys(slugs) if x]


def fetch_mod_from_modrinth(mod_id, loader, mc, mods_dir, log, skip_sha1=(), progress=None):
    """Descarga desde Modrinth el mod con ese id para ese loader y versión de Minecraft, y comprueba que el
    archivo sea de verdad ese mod. Devuelve (archivo, versión) o None."""
    ml = MODRINTH_LOADERS.get(loader)
    if not ml:
        return None
    tries = 0
    for slug in modrinth_projects(mod_id, ml):
        try:
            q = urllib.parse.urlencode({"loaders": json.dumps([ml]), "game_versions": json.dumps([mc])})
            vers = http_json(f"{MODRINTH_API}/project/{urllib.parse.quote(slug)}/version?{q}", timeout=20)
        except Exception:
            continue
        vers.sort(key=lambda v: (v.get("version_type") == "release", v.get("date_published") or ""), reverse=True)
        for v in vers[:2]:
            files = v.get("files") or []
            f = next((x for x in files if x.get("primary")), files[0] if files else None)
            if not f or not f.get("url"):
                continue
            sha1 = (f.get("hashes") or {}).get("sha1")
            if sha1 and sha1 in skip_sha1:
                continue                    # es el mismo archivo que ya tenemos
            if (urllib.parse.urlparse(f["url"]).hostname or "") not in MRPACK_HOSTS:
                continue
            name = os.path.basename(f.get("filename") or "")
            if not name.lower().endswith(".jar"):
                continue
            tries += 1
            tmp = os.path.join(mods_dir, name + ".descarga")
            ids = []
            try:
                download(f["url"], tmp, expected_sha1=sha1, progress=progress(name) if progress else None)
                ids = scan_mod_jar(tmp).get("ids", [])
            except Exception as e:
                log(f"  no se pudo descargar {name}: {e}", "err")
            if mod_id.lower() in ids:
                os.replace(tmp, os.path.join(mods_dir, name))
                return name, v.get("version_number") or ""
            try:
                os.remove(tmp)
            except OSError:
                pass
            if tries >= 4:
                return None
    return None


# --------------------------------------------------------------------------- #
# Instancia de servidor
# --------------------------------------------------------------------------- #

class ServerInstance:
    def __init__(self, sid):
        self.id = sid
        self.dir = os.path.join(SERVERS_DIR, sid)
        self.meta = {}
        self.proc = None
        self.status = "detenido"
        self.error = None
        self.hint = None
        self.console = Console()
        self.players = set()
        self.started_at = None
        self.lock = threading.RLock()
        self.restart_pending = False
        self.progress = None        # barra de carga (crear, instalar, encender, arreglar)
        self.repair = new_chain()   # arreglos del intento actual
        self.repairs_shown = []     # lo que se arregló solo (para mostrarlo en la interfaz)
        self.crash_restarts = []    # reinicios automáticos tras caídas con el servidor en línea
        self.repair_gen = 0         # cambia al cancelar o al empezar otra cadena: los arreglos viejos se descartan
        self.repair_busy = False    # un arreglo está tocando archivos del servidor
        self.stop_asked = False     # la persona escribió «stop» en la consola
        self.boot_failed = False    # el registro ya dijo que no pudo encender
        self.share = None           # zip de mods para los amigos (estado de la última vez)
        self.boot = None
        self.load_meta()

    @property
    def meta_path(self):
        return os.path.join(self.dir, META_FILE)

    def load_meta(self):
        if os.path.exists(self.meta_path):
            with open(self.meta_path, encoding="utf-8") as f:
                self.meta = json.load(f)
        if not self.meta.get("installed"):
            self.status = "sin instalar"

    def save_meta(self):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2, ensure_ascii=False)

    def log(self, msg, kind="app"):
        self.console.add(msg, kind)
        if kind in ("app", "err"):
            self._file_log(msg, kind)

    def _file_log(self, msg, kind="app"):
        """Lo que hace la app con este servidor (encender, arreglos, errores) queda también en
        servidor-home.log dentro de la carpeta del servidor, para poder revisarlo después."""
        path = os.path.join(self.dir, "servidor-home.log")
        try:
            if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:
                os.replace(path, path + ".1")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {'ERROR ' if kind == 'err' else ''}{msg}\n")
        except OSError:
            pass

    @property
    def mods_dir(self):
        return os.path.join(self.dir, "mods")

    @property
    def pid_file(self):
        return os.path.join(self.dir, ".servidor.pid")

    def close_orphan(self):
        """Si la app se cerró de golpe, el servidor pudo quedar abierto sin consola: lo apagamos bien
        (Minecraft guarda el mundo al recibir SIGTERM)."""
        if IS_WINDOWS:
            # En Windows los servidores van dentro de un 'Job' y se cierran con la app; esto es por si acaso.
            try:
                pid = int(_read_text(self.pid_file).strip() or 0)
            except ValueError:
                pid = 0
            if pid and windows_process_image(pid) in ("java.exe", "javaw.exe"):
                self.log("Encontré este servidor abierto desde la vez anterior y lo cerré. "
                         "Se conserva lo guardado hasta el último guardado automático.")
                windows_kill(pid)
            try:
                os.remove(self.pid_file)
            except OSError:
                pass
            return

        def is_ours(pid):
            return os.path.realpath(os.readlink(f"/proc/{pid}/cwd")) == os.path.realpath(self.dir)
        pid = stale_process(self.pid_file, is_ours) if os.path.isdir("/proc") else None
        if not pid:
            return
        self.status = "deteniendo"
        self.log("Encontré este servidor abierto desde la vez anterior; lo apago guardando el mundo…")

        def wait_close():
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(120):
                    if not pid_alive(pid):
                        break
                    time.sleep(0.5)
                else:
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.remove(self.pid_file)
            except OSError:
                pass
            self.status = "detenido" if self.meta.get("installed") else "sin instalar"
            self.log("Listo, ya puedes encenderlo desde aquí.")
        threading.Thread(target=wait_close, daemon=True).start()

    def port(self):
        props = read_properties_cached(os.path.join(self.dir, "server.properties"))
        try:
            return int(props.get("server-port") or DEFAULT_PORT)
        except ValueError:
            return DEFAULT_PORT

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def summary(self):
        props = read_properties_cached(os.path.join(self.dir, "server.properties"))
        t = self.meta.get("type")
        addons = SERVER_TYPES.get(t, {}).get("addons")
        return {
            "id": self.id,
            "name": self.meta.get("name", self.id),
            "type": t,
            "type_label": SERVER_TYPES.get(t, {}).get("label", "?"),
            "mc_version": self.meta.get("mc_version"),
            "loader_version": self.meta.get("loader_version"),
            "modpack": self.meta.get("modpack"),
            "ram_mb": self.meta.get("ram_mb", 2048),
            "jvm_args": self.meta.get("jvm_args", ""),
            "java": self.meta.get("java_major"),
            "port": self.port(),
            "status": self.status,
            "error": self.error,
            "hint": self.hint,
            "players": sorted(self.players),
            "max_players": props.get("max-players", ""),
            "online_mode": props.get("online-mode", "true"),
            "whitelist": props.get("white-list", "false"),
            "uptime": int(time.time() - self.started_at) if self.started_at and self.proc else 0,
            "addons_dir": addons,
            "mods_active": count_mod_files(os.path.join(self.dir, addons)) if addons else 0,
            "installed": bool(self.meta.get("installed")),
            "created": self.meta.get("created"),
            "path": self.dir,
            "progress": self.progress.to_json() if self.progress else None,
            "repairs": list(self.repairs_shown),
            "auto_fix": self.meta.get("auto_fix", True),
            "java_opt": self.meta.get("java_opt", True),
            "perf_mods": t in PERF_MODS,
            "icon": self.icon_version(),
            "share": self.share_state() if addons == "mods" else None,
        }

    # ---- jugadores ----
    def _seen(self, name):
        vistos = self.meta.setdefault("vistos", {})
        vistos[name] = int(time.time())
        try:
            self.save_meta()
        except OSError:
            pass

    def players_info(self):
        """Todos los jugadores que conoce el servidor (entraron alguna vez, son admin, están en la lista blanca o
        baneados), con su estado. Los archivos los escribe Minecraft; la app solo los lee (y los edita con el
        servidor apagado)."""
        rd = lambda n: _read_json_list(os.path.join(self.dir, n))
        people = {}

        def get(name, uuid=None):
            p = people.setdefault(name.lower(), {"name": name, "uuid": uuid, "online": False, "op": False, "op_level": 0,
                                                 "whitelisted": False, "banned": False, "ban_reason": "", "seen": None})
            if uuid and not p["uuid"]:
                p["uuid"] = uuid
            return p
        for e in rd("usercache.json"):
            if e.get("name"):
                get(e["name"], e.get("uuid"))
        for e in rd("ops.json"):
            if e.get("name"):
                p = get(e["name"], e.get("uuid"))
                p["op"], p["op_level"] = True, int(e.get("level") or 4)
        for e in rd("whitelist.json"):
            if e.get("name"):
                get(e["name"], e.get("uuid"))["whitelisted"] = True
        for e in rd("banned-players.json"):
            if e.get("name"):
                p = get(e["name"], e.get("uuid"))
                p["banned"], p["ban_reason"] = True, e.get("reason") or ""
        for n in self.players:
            get(n)["online"] = True
        for n, ts in (self.meta.get("vistos") or {}).items():
            if n.lower() in people:
                people[n.lower()]["seen"] = ts
        out = sorted(people.values(), key=lambda p: (not p["online"], -(p["seen"] or 0), p["name"].lower()))
        props = read_properties_cached(os.path.join(self.dir, "server.properties"))
        return {"players": out, "running": self.status == "en línea", "whitelist_on": props.get("white-list") == "true",
                "online_mode": props.get("online-mode", "true") != "false"}

    PLAYER_CMDS = {"op": "op {n}", "deop": "deop {n}", "kick": "kick {n}{r}", "ban": "ban {n}{r}", "pardon": "pardon {n}",
                   "whitelist_add": "whitelist add {n}", "whitelist_remove": "whitelist remove {n}"}

    def player_action(self, action, name, reason=""):
        name = (name or "").strip()
        if action not in self.PLAYER_CMDS:
            raise ValueError("Acción desconocida.")
        if not PLAYER_NAME_RE.match(name):
            raise ValueError("Ese no es un nombre de Minecraft válido (2 a 16 letras, números o _).")
        reason = re.sub(r"[\x00-\x1f\x7f]", " ", str(reason or "")).strip()[:120]     # una sola línea: nada de comandos extra
        if self.status == "en línea":
            self.send(self.PLAYER_CMDS[action].format(n=name, r=(" " + reason) if reason else ""))
            return {"ok": True, "via": "consola"}
        if self.status in ("iniciando", "deteniendo", "instalando", "reparando"):
            raise RuntimeError("Espera a que el servidor termine de encender o apagarse.")
        if action == "kick":
            raise RuntimeError("El servidor está apagado: no hay nadie conectado.")
        self._player_offline_edit(action, name, reason)
        return {"ok": True, "via": "archivos"}

    def _player_offline_edit(self, action, name, reason):
        """Con el servidor apagado se editan directo ops.json, whitelist.json y banned-players.json (el mismo formato
        que usa Minecraft), así el cambio vale desde el próximo encendido."""
        info = {p["name"].lower(): p for p in self.players_info()["players"]}
        uuid = (info.get(name.lower()) or {}).get("uuid")
        if not uuid:
            props = read_properties(os.path.join(self.dir, "server.properties"))
            uuid = offline_uuid(name) if props.get("online-mode") == "false" else mojang_uuid(name)
        if not uuid:
            raise RuntimeError(f"No encontré la cuenta «{name}» en Mojang. Revisa el nombre, o enciende el servidor y "
                               "vuelve a intentarlo.")
        files = {"op": "ops.json", "deop": "ops.json", "whitelist_add": "whitelist.json",
                 "whitelist_remove": "whitelist.json", "ban": "banned-players.json", "pardon": "banned-players.json"}
        path = os.path.join(self.dir, files[action])
        items = [e for e in _read_json_list(path) if (e.get("name") or "").lower() != name.lower()]
        if action == "op":
            items.append({"uuid": uuid, "name": name, "level": 4, "bypassesPlayerLimit": False})
        elif action == "whitelist_add":
            items.append({"uuid": uuid, "name": name})
        elif action == "ban":
            items.append({"uuid": uuid, "name": name, "created": time.strftime("%Y-%m-%d %H:%M:%S +0000", time.gmtime()),
                          "source": "Servidor Home", "expires": "forever", "reason": reason or "Baneado desde Servidor Home"})
        _write_json_list(path, items)
        if action in ("op", "whitelist_add", "ban"):         # que aparezca en la lista aunque nunca haya entrado
            cache = os.path.join(self.dir, "usercache.json")
            uc = _read_json_list(cache)
            if not any((e.get("name") or "").lower() == name.lower() for e in uc):
                uc.append({"name": name, "uuid": uuid, "expiresOn": time.strftime("%Y-%m-%d %H:%M:%S +0000",
                                                                                   time.gmtime(time.time() + 30 * 86400))})
                _write_json_list(cache, uc)
        verbos = {"op": "ahora es admin", "deop": "ya no es admin", "whitelist_add": "quedó en la lista blanca",
                  "whitelist_remove": "salió de la lista blanca", "ban": "quedó baneado", "pardon": "ya no está baneado"}
        self.log(f"{name} {verbos[action]} (se aplica al encender).")

    # ---- instalación ----
    def install(self, autostart=False):
        with self.lock:
            if self.repair_busy or self.status in ("instalando", "iniciando", "en línea", "deteniendo", "reparando"):
                raise RuntimeError("El servidor está ocupado.")
            self.status = "instalando"
            self.error = None
            self.hint = None
        threading.Thread(target=self._install_worker, args=(autostart,), daemon=True).start()

    def install_phases(self, autostart=False, preinstalled=None):
        """Fases de la barra de carga para instalar (y, si enciende al terminar, para el primer encendido)."""
        t = self.meta.get("type")
        if preinstalled is None:
            preinstalled = self.meta.get("preinstalled")
        label = SERVER_TYPES.get(t, {}).get("label", "")
        pi = self.meta.get("pending_import") or {}
        phases = []
        if pi.get("mrpack_files"):
            phases.append(("import", "Descargando los mods del modpack", 30))
        elif pi.get("copy_from"):
            phases.append(("import", "Copiando el modpack", 15))
        elif pi:
            phases.append(("import", "Preparando el modpack", 3))
        phases.append(("java", "Preparando Java", 15))
        if t in ("forge", "neoforge") and not preinstalled:
            phases += [("server", f"Descargando {label}", 4), ("install", f"Instalando {label}", 36)]
        else:
            phases.append(("server", f"Descargando el servidor de {label}" if t != "vanilla" else "Descargando el servidor de Minecraft", 20))
        phases.append(("final", "Últimos detalles", 1))
        if autostart:
            phases.append(("boot", "Encendiendo por primera vez", 30 if SERVER_TYPES.get(t, {}).get("addons") == "mods" else 15))
        return phases

    def _dl_progress(self, what):
        pr = self.progress
        return (lambda d, t: pr.update(d / t, f"{what}: {mb_text(d, t)}")) if pr else None

    def _install_worker(self, autostart, keep_progress=False, in_repair=False):
        """Instala el servidor. in_repair=True: lo llama un arreglo automático, que se encarga del estado
        y de la barra; los errores se lanzan en vez de dejar el servidor en «error»."""
        t = self.meta["type"]
        mc = self.meta["mc_version"]
        if not (keep_progress and self.progress):
            self.progress = Progress("instalando", self.install_phases(autostart))
        pr = self.progress
        try:
            pi = self.meta.get("pending_import")
            if pi:
                pr.begin("import")
                run_import_steps(self, pi, self.log)
                self.meta.pop("pending_import", None)
                self.save_meta()
            self.log(f"== Preparando {SERVER_TYPES[t]['label']} para Minecraft {mc} ==")
            need = java_for_mc(mc)
            pr.begin("java", f"Preparando Java {need}")
            self.meta["java_major"] = need
            java = ensure_java(need, self.log, progress=self._dl_progress(f"Descargando Java {need}"))
            self.meta["java_path"] = java
            pr.update(1)
            pr.begin("server")

            if t == "vanilla":
                if not os.path.exists(os.path.join(self.dir, "server.jar")):
                    info = mojang_version_info(mc)
                    srv = info.get("downloads", {}).get("server")
                    if not srv:
                        raise RuntimeError(f"Mojang no publica servidor para {mc}.")
                    download(srv["url"], os.path.join(self.dir, "server.jar"), self.log, expected_sha1=srv.get("sha1"),
                             progress=self._dl_progress(f"Minecraft {mc}"))
                self.meta["launch"] = {"jar": "server.jar"}

            elif t == "paper":
                url, name, sha = paper_download_info(mc)
                self.log(f"Build de Paper: {name}")
                download(url, os.path.join(self.dir, "server.jar"), self.log, expected_sha256=sha,
                         progress=self._dl_progress(name))
                self.meta["launch"] = {"jar": "server.jar"}

            elif t == "fabric":
                launch_jar = os.path.join(self.dir, "fabric-server-launch.jar")
                if not (self.meta.get("preinstalled") and os.path.exists(launch_jar)):
                    loader = self.meta.get("loader_version") or recommended_loader("fabric", mc)
                    inst = cached("fabric:installer", 600, lambda: http_json(f"{FABRIC_META}/installer"))
                    inst_v = next((i["version"] for i in inst if i.get("stable")), inst[0]["version"])
                    self.meta["loader_version"] = loader
                    self.log(f"Descargando Fabric Loader {loader}...")
                    download(f"{FABRIC_META}/loader/{mc}/{loader}/{inst_v}/server/jar", launch_jar, self.log,
                             progress=self._dl_progress(f"Fabric {loader}"))
                self.meta["launch"] = {"jar": "fabric-server-launch.jar"}

            elif t in ("forge", "neoforge"):
                launch = None
                if self.meta.get("preinstalled"):
                    try:
                        launch = self._detect_modded_launch()
                        self.log("El modpack ya trae el servidor instalado.")
                    except RuntimeError:
                        launch = None
                if not launch:
                    launch = self._run_modded_installer(java, t, mc)
                self.meta["launch"] = launch

            pr.begin("final")
            if self.meta.get("eula"):
                with open(os.path.join(self.dir, "eula.txt"), "w") as f:
                    f.write("# Aceptado desde Servidor Home (https://aka.ms/MinecraftEULA)\neula=true\n")
            for mark in (STAGING_MARK,):
                try:
                    os.remove(os.path.join(self.dir, mark))
                except OSError:
                    pass
            self.meta["installed"] = True
            self.save_meta()
            self.log("== Listo ==")
            pr.update(1)
            if in_repair:
                return
            if autostart:           # pasa directo de «instalando» a «encendiendo» (sin un «apagado» entremedio)
                try:
                    self.start()
                except RuntimeError as e:
                    self.progress = None
                    self.status = "detenido"
                    self.log(f"No se encendió automáticamente: {e}", "err")
            else:
                self.progress = None
                self.status = "detenido"
        except Exception as e:
            if in_repair:
                self.save_meta()
                raise
            self.progress = None
            self.status = "error"
            self.error = str(e)
            self.save_meta()
            self.log(f"ERROR: {e}", "err")
            traceback.print_exc()

    def _run_modded_installer(self, java, t, mc):
        lv = self.meta.get("loader_version") or recommended_loader(t, mc)
        self.meta["loader_version"] = lv
        installer = os.path.join(self.dir, "installer.jar")
        local = os.path.join(self.dir, f"neoforge-{lv}-installer.jar" if t == "neoforge" else f"forge-{mc}-{lv}-installer.jar")
        if os.path.exists(local):
            shutil.copy2(local, installer)
            self.log(f"Usando el instalador incluido en el modpack ({os.path.basename(local)}).")
        else:
            if t == "forge":
                url = f"{FORGE_MAVEN}/{mc}-{lv}/forge-{mc}-{lv}-installer.jar"
            else:
                url = f"{NEOFORGE_MAVEN}/{lv}/neoforge-{lv}-installer.jar"
            self.log(f"Descargando el instalador de {SERVER_TYPES[t]['label']} {lv}...")
            download(url, installer, self.log, progress=self._dl_progress(f"Instalador de {SERVER_TYPES[t]['label']} {lv}"))
        pr = self.progress
        if pr:
            pr.begin("install", f"Instalando {SERVER_TYPES[t]['label']} {lv}", "Descargando librerías…")
        self.log("Instalando el servidor (descarga librerías, puede tardar unos minutos)...")
        p = subprocess.Popen([java, "-jar", "installer.jar", "--installServer"], cwd=self.dir,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace", **child_kwargs())
        attach_to_job(p)
        count = 0
        for line in p.stdout:
            count += 1
            line = ANSI_RE.sub("", line.rstrip())
            if pr and count % 5 == 0:     # no se sabe el total: avanza cada vez más lento hasta el 95 %
                pr.update(min(0.95, 1 - math.exp(-count / 250)), f"{count} pasos del instalador")
            # El instalador es muy conversador: mostramos solo lo relevante.
            if count % 25 == 0 or re.search(r"(error|exception|fail|success|finished|done)", line, re.I):
                self.log(line, "out")
        if p.wait() != 0:
            raise RuntimeError(f"El instalador de {SERVER_TYPES[t]['label']} falló (código {p.returncode}). Revisa la consola.")
        for junk in ("installer.jar", "installer.jar.log"):
            try:
                os.remove(os.path.join(self.dir, junk))
            except OSError:
                pass
        return self._detect_modded_launch()

    def _detect_modded_launch(self):
        script = os.path.join(self.dir, "run.bat" if IS_WINDOWS else "run.sh")
        if os.path.exists(script):
            found = None
            with open(script, encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = re.split(r"\s(?:\|\||&&)\s", line.strip())[0]
                    if (re.match(r'^"?java"?\s', s) or s.startswith("java ")) and "--onlyCheckJava" not in s:
                        found = s  # nos quedamos con la última línea que lanza java
            if found:
                args = shlex.split(found, posix=not IS_WINDOWS)[1:]
                args = [a for a in args if a not in ('"$@"', "$@", "%*", "nogui")]
                if all(not a.startswith("@") or os.path.exists(os.path.join(self.dir, a[1:])) for a in args):
                    return {"args": args}
        for pat in ("libraries/net/neoforged/neoforge", "libraries/net/minecraftforge/forge"):
            base = os.path.join(self.dir, pat)
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), key=version_key, reverse=True):
                    f = os.path.join(pat, d, "win_args.txt" if IS_WINDOWS else "unix_args.txt")
                    if os.path.exists(os.path.join(self.dir, f)):
                        args = ["@" + f]
                        if os.path.exists(os.path.join(self.dir, "user_jvm_args.txt")):
                            args.insert(0, "@user_jvm_args.txt")
                        return {"args": args}
        jars = [j for j in os.listdir(self.dir) if j.endswith(".jar") and "installer" not in j
                and (j.startswith("forge") or j.startswith("neoforge"))]
        if jars:
            return {"jar": sorted(jars, key=len)[0]}
        raise RuntimeError("No pude determinar cómo arrancar el servidor.")

    # ---- ciclo de vida ----
    def build_command(self):
        java = self.meta.get("java_path") or "java"
        if java != "java" and not os.path.exists(java):
            java = ensure_java(self.meta.get("java_major", 21), self.log)
            self.meta["java_path"] = java
            self.save_meta()
        ram = int(self.meta.get("ram_mb", 2048))
        cmd = [java, f"-Xms{max(512, ram // 2)}M", f"-Xmx{ram}M"]
        if IS_WINDOWS:   # que la consola llegue en UTF-8 (tildes y ñ bien escritas)
            cmd += ["-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8"]
        if self.meta.get("java_opt", True):
            custom = self.meta.get("jvm_args", "") + "\n" + _read_text(os.path.join(self.dir, "user_jvm_args.txt"))
            cmd += java_tuning_flags(ram, custom)
        cmd += log4j_fix_args(self.meta.get("type"), self.meta.get("mc_version"), self.dir)
        extra = self.meta.get("jvm_args", "").strip()
        if extra:
            cmd += shlex.split(extra)
        launch = self.meta.get("launch", {})
        if "args" in launch:
            cmd += launch["args"]
        else:
            cmd += ["-jar", launch.get("jar", "server.jar")]
        cmd.append("nogui")
        return cmd

    def start(self, user=False):
        with self.lock:
            if not self.meta.get("installed"):
                raise RuntimeError("El servidor aún no está instalado.")
            if self.running():
                raise RuntimeError("El servidor ya está encendido.")
            if user:                     # lo pidió la persona: empieza una cadena nueva de arreglos
                if self.repair_busy or self.status in ("instalando", "reparando", "deteniendo"):
                    raise RuntimeError("Espera un momento: el servidor está terminando otra tarea.")
                self.repair_gen += 1
                self.repair = new_chain()
                self.repairs_shown = []
            eula = os.path.join(self.dir, "eula.txt")
            if not os.path.exists(eula) or "eula=true" not in _read_text(eula):
                raise RuntimeError("Debes aceptar el EULA de Minecraft (en Ajustes) antes de encender.")
            port = self.port()
            for other in manager.servers.values():
                if other is not self and other.running() and other.port() == port:
                    raise RuntimeError(f"«{other.meta.get('name')}» ya está encendido en el mismo puerto. Apágalo primero.")
            if SERVER_TYPES.get(self.meta.get("type"), {}).get("addons") == "mods":
                for what in self.revisar_mods() + dedupe_mods(self.mods_dir, self.log):
                    self.repair["log"].append(what)
            cmd = self.build_command()
            self.log("$ " + " ".join(cmd), "app")
            self.proc = subprocess.Popen(cmd, cwd=self.dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                         bufsize=1, **child_kwargs(detach=True))
            attach_to_job(self.proc)
            win_no_power_throttling(self.proc)
            try:
                with open(self.pid_file, "w") as f:
                    f.write(str(self.proc.pid))
            except OSError:
                pass
            self.status = "iniciando"
            self.error = None
            self.hint = None
            self.stop_asked = False
            self.boot_failed = False
            self.players.clear()
            self.started_at = time.time()
            if self.progress and self.progress.has("boot"):
                self.progress.begin("boot")
            else:
                self.progress = Progress("encendiendo", [("boot", "Encendiendo", 1)])
            self.boot = {"lines": 0, "floor": 0.0, "expected": int(self.meta.get("boot_lines") or 0)}
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        if manager and manager.playit:
            manager.playit.set_target_port(port)

    JOIN_RE = re.compile(r"\]: (\w{2,16}) joined the game")
    LEFT_RE = re.compile(r"\]: (\w{2,16}) left the game")

    def _reader(self, proc):
        recent, after_online = [], []
        t0 = time.time()
        for line in proc.stdout:
            line = ANSI_RE.sub("", line.rstrip("\r\n"))
            self.console.add(line, "out")
            recent.append(line)
            if len(recent) > 1500:
                del recent[:500]
            if self.status == "en línea":
                after_online.append(line)
                if len(after_online) > 600:
                    del after_online[:200]
            if self.status == "iniciando":
                self._boot_line(line)
                if not self.boot_failed and BOOT_FAIL_RE.search(line):
                    self.boot_failed = True          # falló al encender: si Java no se cierra solo, se cierra
                    threading.Thread(target=self._close_if_stuck, args=(proc,), daemon=True).start()
            if self.status == "iniciando" and re.search(r"Done \([\d.,]+s\)!", line):
                self.status = "en línea"
                if self.boot:
                    self.meta["boot_lines"] = self.boot["lines"]
                    self.meta["boot_seconds"] = int(time.time() - (self.started_at or time.time()))
                    try:
                        self.save_meta()
                    except OSError:
                        pass
                self.progress = None
                if self.repair["log"]:
                    self.repairs_shown = list(self.repair["log"])
                    self.log(f"Se arregló solo: {'; '.join(self.repair['log'])}.")
                self.repair = new_chain()
                self.log("Servidor encendido. ¡A jugar!")
            m = self.JOIN_RE.search(line)
            if m:
                self.players.add(m.group(1))
                self._seen(m.group(1))
            m = self.LEFT_RE.search(line)
            if m:
                self.players.discard(m.group(1))
                self._seen(m.group(1))
        code = proc.wait()
        try:
            os.remove(self.pid_file)
        except OSError:
            pass
        with self.lock:
            if proc is self.proc:
                was_online = self.status == "en línea"
                stopping = self.status == "deteniendo" or self.stop_asked
                self.proc = None
                self.started_at = None
                self.players.clear()
                self.progress = None
                # Código 0 no siempre es un apagado normal: NeoForge/Forge terminan con 0 cuando falla la carga de
                # mods, y Minecraft cuando falta el EULA. Si no llegó a encender, o dejó rastros de una caída, falló.
                crashed = not stopping and (code != 0 or not was_online
                                            or bool(BOOT_FAIL_RE.search("\n".join(after_online[-300:]))))
                if not crashed:
                    self.status = "detenido"
                    self.log(f"Servidor apagado (código {code}).")
                else:
                    self._handle_crash(recent[-1000:], was_online, code, t0)
        if self.restart_pending:
            self.restart_pending = False
            try:
                self.start()
            except Exception as e:
                self.log(f"No se pudo reiniciar: {e}", "err")

    def _close_if_stuck(self, proc):
        """El servidor dijo que no pudo encender pero Java sigue abierto (algún mod dejó un hilo vivo): se cierra
        para poder arreglarlo."""
        try:
            proc.wait(timeout=STUCK_WAIT)
            return
        except subprocess.TimeoutExpired:
            pass
        if proc is self.proc and self.status == "iniciando" and proc.poll() is None:
            self.log("El servidor no pudo encender pero Java quedó abierto; lo cierro para arreglarlo.", "err")
            try:
                proc.kill()
            except OSError:
                pass

    def send(self, command):
        with self.lock:
            if not self.running():
                raise RuntimeError("El servidor no está encendido.")
            command = command.strip().lstrip("/")
            if command.split(" ")[0].lower() == "stop":
                self.stop_asked = True           # lo apagó la persona desde la consola: no es una caída
            self.console.add("> " + command, "cmd")
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()

    def stop(self, restart=False, timeout=90):
        with self.lock:
            if self.status == "reparando" and not self.running():
                self.repair_gen += 1
                self.status = "detenido"
                self.progress = None
                self.log("Arreglo automático cancelado." + (" Termino el paso que estaba haciendo y no enciendo el servidor."
                                                            if self.repair_busy else ""))
                return
            if not self.running():
                if restart:
                    self.start()
                    return
                raise RuntimeError("El servidor no está encendido.")
            self.restart_pending = restart
            self.status = "deteniendo"
            proc = self.proc
            try:
                self.send("stop")
            except Exception:
                pass

        def watchdog():
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.log("No respondió a 'stop'; forzando cierre.", "err")
                self.kill()
        threading.Thread(target=watchdog, daemon=True).start()

    def kill(self):
        with self.lock:
            if self.running():
                self.status = "deteniendo"
                self.proc.kill()

    # ---- barra de encendido ----
    BOOT_STAGES = [
        (re.compile(r"ModLauncher running|with Fabric Loader|Environment:|Starting net\.minecraft|Loading Minecraft"), 0.03,
         "Arrancando"),
        (re.compile(r"Loading \d+ mods|Found \d+ mods|Mod file|Loading mods|Scanning mod", re.I), 0.08, "Cargando mods"),
        (re.compile(r"Starting minecraft server version"), 0.35, "Iniciando Minecraft"),
        (re.compile(r"Loading properties|Default game type"), 0.42, "Leyendo la configuración"),
        (re.compile(r"Preparing level"), 0.55, "Preparando el mundo"),
        (re.compile(r"Preparing start region|Preparing spawn area|Loading \d+ persistent chunks"), 0.62, "Generando el terreno"),
    ]
    SPAWN_RE = re.compile(r"Preparing spawn area: (\d+)%")

    def _boot_line(self, line):
        b, pr = self.boot, self.progress
        if not b or not pr:
            return
        b["lines"] += 1
        for rx, floor, label in self.BOOT_STAGES:
            if floor > b["floor"] and rx.search(line):
                b["floor"] = floor
                b["label"] = label
        m = self.SPAWN_RE.search(line)
        frac = b["floor"]
        if m:
            frac = max(frac, 0.62 + 0.35 * int(m.group(1)) / 100)
        if b["expected"] > 20:               # la vez anterior sabemos cuántas líneas hubo hasta «Done»
            frac = max(frac, min(0.97, b["lines"] / b["expected"]))
        elif b["floor"] < 0.35:              # cargando mods: avanza cada vez más lento
            frac = max(frac, 0.08 + 0.26 * (1 - math.exp(-b["lines"] / 1200)))
        label = b.get("label")
        detail = f"Terreno: {m.group(1)}%" if m else ("La primera vez con mods puede tardar unos minutos"
                                                        if label == "Cargando mods" and not b["expected"] else "")
        prefix = {"instalando": "Encendiendo por primera vez", "reparando": "Encendiendo de nuevo"}.get(pr.kind)
        if prefix:
            label = f"{prefix} · {label[0].lower() + label[1:]}" if label else prefix
        pr.update(frac, detail, label or "Encendiendo")

    # ---- arreglos automáticos ----
    def _crash_report_lines(self, since):
        """Las líneas del informe de error que Minecraft/NeoForge escribió en esta caída (si hay)."""
        folder = os.path.join(self.dir, "crash-reports")
        try:
            files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".txt")]
            files = [f for f in files if os.path.getmtime(f) >= since - 2]
        except OSError:
            return []
        if not files:
            return []
        # todos los de esta caída, del más viejo al más nuevo: si el servidor se trabó al apagarse después del error,
        # el último informe es el del vigilante y la causa de verdad está en el anterior
        out = []
        for f in sorted(files, key=os.path.getmtime)[-3:]:
            out += _read_text(f, limit=300000).splitlines()
        return out

    def _handle_crash(self, recent, was_online, code, t0=None):
        """El servidor falló: buscamos la causa y, si hay un arreglo seguro, lo aplicamos y reintentamos solos."""
        report = self._crash_report_lines(t0) if t0 else []
        probs = find_problems(recent + report, self, online=was_online)
        self.hint = hint_of(probs)
        self.error = crash_message(probs, was_online, code)
        self.log(self.error, "err")
        self._file_log("Últimas líneas de la consola:\n    " + "\n    ".join(recent[-60:]))
        for p in probs[:4]:
            self.log("Causa: " + p["text"], "err")
        auto = self.meta.get("auto_fix", True)
        chain = self.repair
        todo = [p for p in probs if p["auto"] and p["key"] not in chain["done"]] if auto else []
        if todo and chain["count"] < MAX_AUTO_FIXES:
            self.repair_gen += 1
            self.progress = Progress("reparando", [(p["key"], p["title"], 1) for p in todo] +
                                     self._backup_phase([p["fix"] for p in todo]) + [("boot", "Encendiendo de nuevo", 1)])
            self.status = "reparando"          # directo, sin pasar por «error» (la interfaz no parpadea)
            self.repair_busy = True
            threading.Thread(target=self._repair_worker, args=(todo, probs, self.repair_gen), daemon=True).start()
            return
        if auto and todo:
            self.log(f"Ya probé {MAX_AUTO_FIXES} arreglos automáticos; revisa el mensaje de arriba.", "err")
        elif auto and was_online and not any(p["fix"] for p in probs if not p.get("suspect")):
            now = time.time()
            self.crash_restarts = [t for t in self.crash_restarts if now - t < 1800] + [now]
            if len(self.crash_restarts) <= 3:
                self.log(f"El servidor se cayó mientras funcionaba; lo vuelvo a encender (intento {len(self.crash_restarts)} de 3).")
                self.repair_gen += 1
                self.progress = Progress("reparando", [("wait", "Reiniciando después de la caída", 1), ("boot", "Encendiendo de nuevo", 1)])
                self.status = "reparando"
                threading.Thread(target=self._restart_after_crash, args=(self.repair_gen,), daemon=True).start()
                return
            self.log("Se cayó 3 veces en media hora; no lo reinicio más solo. Revisa el mensaje de arriba.", "err")
        self.hint = self._final_hint(probs)
        self.status = "error"

    def _final_hint(self, probs):
        """Consejo cuando ya no queda nada que arreglar solo: si algún arreglo falló dice por qué; si se aplicaron
        arreglos y sigue fallando, lo cuenta; y ofrece el siguiente arreglo que la persona puede elegir
        (por ejemplo desactivar un mod con contenido)."""
        if not probs:
            return None
        chain = self.repair
        failed = [chain["failed"][p["key"]] for p in probs if p["key"] in chain["failed"]]
        tried = any(p["key"] in chain["done"] and p["key"] not in chain["failed"] for p in probs)
        rest = next((p for p in probs if p["fix"] and p["key"] not in chain["done"]), None)
        confirm = chain.get("confirm")
        if confirm and any(p["key"] == confirm["key"] for p in probs):
            # lo que no se hizo solo porque cambiaba mucho: se ofrece con el botón (el porqué ya va en «failed»)
            rest = dict(confirm, text="", label=f"Desactivar {confirm['fix'].get('file', 'el mod')} y los que lo necesitan")
        parts = []
        if failed:
            parts.append("No se pudo arreglar solo: " + " ".join(dict.fromkeys(failed)))
        elif tried:
            done = [x for x in chain["log"] if not x.startswith("respaldé")]
            parts.append(f"Ya probé arreglarlo solo ({'; '.join(done)}) y sigue fallando." if done
                         else "Ya probé arreglarlo solo y sigue fallando.")
        if rest:
            if rest["text"]:
                parts.append(rest["text"])
        elif not parts:
            parts.append(probs[0]["text"])
        elif tried and not failed:
            parts.append("Revisa la consola para ver el detalle.")
        hint = {"text": " ".join(parts)}
        if rest:
            hint["action"] = dict(rest["fix"], label=rest["label"] or "Arreglar y reintentar")
        return hint

    def _backup_phase(self, fixes):
        if any((f or {}).get("type") in FIX_RISKY for f in fixes) and not self.repair["backed_up"] and self.world_dirs():
            return [("backup", "Respaldando el mundo", 1)]
        return []

    def _restart_after_crash(self, gen):
        for i in range(1, 51):          # 5 segundos antes de volver a encender
            time.sleep(0.1)
            if gen != self.repair_gen:
                return
            if self.progress:
                self.progress.update(i / 50, "Vuelve a encender en unos segundos")
        self._retry_after_fix(["reinicio"], gen)

    def _repair_worker(self, todo, probs, gen):
        chain, applied, worked = self.repair, [], set()
        try:
            for p in todo:
                if chain["count"] >= MAX_AUTO_FIXES or gen != self.repair_gen:
                    break
                after = (p["fix"] or {}).get("after")
                if after and after in worked:
                    continue        # primero se prueba lo otro (por ejemplo una versión nueva del mod) y se ve si basta
                chain["done"].add(p["key"])
                chain["count"] += 1
                if self.progress:
                    self.progress.begin(p["key"], p["title"])
                self.log(f"Arreglo automático: {p['title']}…")
                try:
                    what = self.apply_fix(p["fix"], auto=True)
                    applied.append(what)
                    worked.add(p["key"])
                    chain["log"].append(what)
                    self.log(f"  Listo: {what}")
                except NeedsConfirmation as e:
                    chain["failed"][p["key"]] = str(e)
                    chain["confirm"] = p            # se ofrece con el botón
                    self.log(f"  No lo hice solo: {e}", "err")
                except Exception as e:
                    chain["failed"][p["key"]] = str(e)
                    self.log(f"  No se pudo: {e}", "err")
        finally:
            self.repair_busy = False
        if not applied and gen == self.repair_gen:
            self.hint = self._final_hint(probs)        # nada funcionó: por qué, y qué puede elegir la persona
        self._retry_after_fix(applied, gen)

    def _retry_after_fix(self, applied, gen):
        chain = self.repair
        if applied and gen == self.repair_gen and chain.get("needs_backup") and not chain["backed_up"] and self.world_dirs():
            pr = self.progress
            self.repair_busy = True
            try:
                if pr:
                    pr.begin("backup", "Respaldando el mundo")
                self.log("Respaldando el mundo antes de encender con los cambios...")
                name = self.backup(progress=(lambda d, t: pr.update(d / t, f"{d} de {t} archivos")) if pr else None)
                chain["backed_up"] = True
                chain["log"].append(f"respaldé el mundo antes de encender con los cambios ({name}, en Respaldos)")
            except Exception as e:
                self.log(f"No se pudo respaldar el mundo: {e}", "err")
                with self.lock:
                    if gen == self.repair_gen:
                        self.progress = None
                        self.status = "error"
                        self.error = (f"No se pudo respaldar el mundo ({e}), así que no lo encendí con los cambios. "
                                      "Libera espacio en el disco y vuelve a encenderlo.")
                return
            finally:
                self.repair_busy = False
        with self.lock:
            if gen != self.repair_gen:            # se canceló (Detener) o la persona hizo otra cosa
                return
            if not applied:
                self.progress = None
                self.status = "error"
                return
            self.hint = None
            self.error = None
            try:
                self.start()            # sigue en «reparando» hasta que start() lo pasa a «iniciando»
            except Exception as e:
                self.progress = None
                self.status = "error"
                self.error = str(e)
                self.log(f"No se pudo volver a encender: {e}", "err")

    def fix(self, action):
        """Arreglo pedido con el botón: se aplica y el servidor se enciende (y sigue arreglando solo si hace falta)."""
        with self.lock:
            if self.running() or self.repair_busy or self.status in ("instalando", "reparando", "deteniendo", "iniciando"):
                raise RuntimeError("Espera a que el servidor termine lo que está haciendo.")
            self.repair = new_chain()
            self.repairs_shown = []
            self.repair_gen += 1
            gen = self.repair_gen
            self.status = "reparando"
            self.repair_busy = True
            self.progress = Progress("reparando", [("fix", "Aplicando el arreglo", 1)] + self._backup_phase([action]) +
                                     [("boot", "Encendiendo de nuevo", 1)])

        def work():
            try:
                what = self.apply_fix(action)
            except Exception as e:
                self.repair_busy = False
                if gen == self.repair_gen:
                    self.progress = None
                    self.status = "error"
                    self.hint = {"text": f"No se pudo: {e}"}
                self.log(f"No se pudo: {e}", "err")
                return
            self.repair_busy = False
            self.repair["log"].append(what)
            self.log(f"Listo: {what}")
            self._retry_after_fix([what], gen)
        threading.Thread(target=work, daemon=True).start()

    def _disable_file(self, name):
        """Desactiva un .jar de la carpeta mods (lo renombra a .jar.disabled). Devuelve cómo quedó su nombre base."""
        path = os.path.join(self.mods_dir, name)
        target, n = path + ".disabled", 2
        while os.path.exists(target):             # ya hay una copia desactivada con el mismo nombre
            target, n = f"{path[:-4]}-{n}.jar.disabled", n + 1
        os.replace(path, target)
        return os.path.basename(target)[: -len(".disabled")]

    def _dependents(self, info, seen=None):
        """Los mods activos que necesitan sí o sí a este (y los que necesitan a esos): sin él no pueden cargar."""
        seen = set() if seen is None else seen
        gone = set(info.get("ids") or []) - seen
        seen |= gone
        if not gone:
            return []
        out = []
        for f in list_mod_files(self.mods_dir):
            other = scan_mod_jar(os.path.join(self.mods_dir, f))
            if other.get("ids") and not set(other["ids"]) & seen and gone & set(server_required_deps(other)):
                out.append(mod_label(other, f))
                out += [x for x in self._dependents(other, seen) if x not in out]
        return out

    def _disable_dependents(self, info, kind, depth=0):
        """Desactiva los mods activos que necesitan sí o sí al que se acaba de desactivar. Devuelve sus nombres."""
        gone = set(info.get("ids") or [])
        if not gone or depth > 6:
            return []
        gone -= set(mod_index(self.mods_dir))       # si otro archivo activo trae el mismo mod, nadie queda sin él
        label = mod_label(info)
        done = []
        for f in list_mod_files(self.mods_dir):
            if not gone or not os.path.isfile(os.path.join(self.mods_dir, f)):
                continue
            other = scan_mod_jar(os.path.join(self.mods_dir, f))
            if not gone & set(server_required_deps(other)):
                continue
            base = self._disable_file(f)
            if kind == "disable_client":
                self.meta.setdefault("client_mods", {})[base] = f"necesita {label}, que es solo del jugador"
            else:
                self.meta.setdefault("broken_mods", {})[base] = f"necesita {label}, que se desactivó porque fallaba"
            done.append(mod_label(other, f))
            done += self._disable_dependents(other, kind, depth + 1)
        return done

    def _enable_with_deps(self, name, depth=0, done=None):
        """Reactiva un mod desactivado y, si hace falta, los mods desactivados que ese mod necesita (por ejemplo JEI
        necesita MezzConfig). No reactiva mods que son solo del jugador."""
        done = [] if done is None else done
        src = os.path.join(self.mods_dir, name)
        dst = src[: -len(".disabled")]
        if os.path.exists(dst):
            raise RuntimeError(f"Ya hay un {os.path.basename(dst)} activo.")
        os.replace(src, dst)
        base = os.path.basename(dst)
        done.append(base)
        marks = self.meta.get("client_mods") or {}
        if base in marks:
            del marks[base]
            self.save_meta()
        if depth >= 4:
            return done
        active = set(mod_index(self.mods_dir))
        for dep in server_required_deps(scan_mod_jar(dst)):
            if dep in active:
                continue
            cands = []
            broken = self.meta.get("broken_mods") or {}
            for f in os.listdir(self.mods_dir):
                if f.lower().endswith(".jar.disabled") and f[: -len(".disabled")] not in marks \
                        and f[: -len(".disabled")] not in broken:
                    info = scan_mod_jar(os.path.join(self.mods_dir, f))
                    if dep in info.get("ids", []) and not info.get("bad") and not info.get("client_only"):
                        cands.append((version_key(info.get("version") or "0"), f))
            if cands and not os.path.exists(os.path.join(self.mods_dir, max(cands)[1][: -len(".disabled")])):
                self._enable_with_deps(max(cands)[1], depth + 1, done)
                active = set(mod_index(self.mods_dir))
        return done

    def modpack_path(self):
        """La carpeta del launcher de donde se importó el modpack, si se sabe y sigue existiendo (sirve para ver con
        qué versión del loader lo abre el launcher). Los servidores importados antes de guardarla la tienen en su
        registro («Copiando el modpack desde ...»)."""
        p = (self.meta.get("modpack") or {}).get("path")
        if not p:
            for name in ("servidor-home.log", "servidor-home.log.1"):
                m = re.search(r"Copiando el modpack desde (.+?) \.\.\.\s*$",        # (en Windows las líneas terminan en \r\n)
                              _read_text(os.path.join(self.dir, name), limit=4 * 1024 * 1024), re.M)
                if m:
                    p = m.group(1).strip()
                    break
        return p if p and os.path.isdir(p) else None

    def revisar_mods(self):
        """Una vez por servidor importado: hasta la versión 2.5.1, al importar se desactivaban por error mods que sí
        van en el servidor (los que dicen displayTest="IGNORE_SERVER_VERSION", como JEI, SmartBrainLib o
        FTB Essentials). Aquí se vuelven a activar. Devuelve lo que hizo, para mostrarlo en «Se arregló solo»."""
        if int(self.meta.get("revision_mods") or 0) >= MODS_REVISION:
            return []
        self.meta["revision_mods"] = MODS_REVISION
        done = []
        if self.meta.get("modpack") and os.path.isdir(self.mods_dir):
            active = set(mod_index(self.mods_dir))
            marks = self.meta.get("client_mods") or {}
            for f in sorted(os.listdir(self.mods_dir), key=str.lower):
                if not f.lower().endswith(".jar.disabled") or f[: -len(".disabled")] in marks:
                    continue
                path = os.path.join(self.mods_dir, f)
                info = scan_mod_jar(path)
                if info.get("bad") or info.get("client_only") or info.get("display_test") != "IGNORE_SERVER_VERSION":
                    continue
                if not info.get("ids") or any(i in active for i in info["ids"]) or os.path.exists(path[: -len(".disabled")]):
                    continue                    # es una copia repetida de un mod activo
                os.replace(path, path[: -len(".disabled")])
                active.update(info["ids"])
                done.append(mod_label(info, f))
        self.save_meta()
        if not done:
            return []
        msg = (f"reactivé {len(done)} mod{'s' if len(done) > 1 else ''} que la versión anterior de la app había "
               f"desactivado por error: {', '.join(done)}")
        self.log(msg[0].upper() + msg[1:] + ".")
        return [msg]

    def apply_fix(self, fix, auto=False):
        """Aplica un arreglo y devuelve una frase con lo que hizo (o lanza un error si no se pudo).
        auto=True: lo aplica la app sola (no con el botón)."""
        kind = (fix or {}).get("type")
        t, mc = self.meta.get("type"), self.meta.get("mc_version")
        what = self._apply_fix(kind, fix, t, mc, auto)
        if kind in FIX_RISKY:
            self.repair["needs_backup"] = True          # el mundo se respalda antes de volver a encender
        return what

    def _apply_fix(self, kind, fix, t, mc, auto=False):
        if kind in ("disable_mod", "disable_content", "disable_client", "disable_bad"):
            name = os.path.basename(fix.get("file", ""))
            path = os.path.join(self.mods_dir, name)
            if not name or not name.lower().endswith(".jar") or not os.path.isfile(path):
                raise RuntimeError("No encontré ese mod.")
            info = scan_mod_jar(path)
            cascade = kind in ("disable_client", "disable_content")
            if cascade and auto:
                deps = self._dependents(info)
                if len(deps) > MAX_CASCADE:
                    lista = ", ".join(deps[:5]) + (f" y {len(deps) - 5} más" if len(deps) > 5 else "")
                    raise NeedsConfirmation(
                        f"El mod «{mod_label(info, name)}» ({name}) falla al cargar y {len(deps)} mods lo necesitan ({lista}). "
                        "No lo desactivé solo porque cambiaría mucho el modpack: busca una versión más nueva de ese mod, o "
                        "desactívalo con el botón (se desactivan también los que lo necesitan).")
            base = self._disable_file(name)
            reason = fix.get("reason")
            if kind == "disable_client":
                reason = reason or "es solo del jugador"
                self.meta.setdefault("client_mods", {})[base] = reason
            elif kind == "disable_content":         # que no se vuelva a activar solo porque otro mod lo pide
                self.meta.setdefault("broken_mods", {})[base] = reason or "se desactivó para que el servidor encienda"
            also = self._disable_dependents(info, kind) if cascade else []
            self.save_meta()
            tail = (f"; también {'el mod que lo necesita' if len(also) == 1 else 'los mods que lo necesitan'}: "
                    f"{', '.join(also)}" if also else "")
            if kind == "disable_bad":
                return f"desactivé {name} (el archivo estaba dañado)"
            return f"desactivé {name}" + (f" ({reason})" if reason else "") + tail
        if kind == "enable_mod":
            name = os.path.basename(fix.get("file", ""))
            if not name.lower().endswith(".jar.disabled") or not os.path.isfile(os.path.join(self.mods_dir, name)):
                raise RuntimeError("No encontré ese mod desactivado.")
            done = self._enable_with_deps(name)
            return "reactivé " + ", ".join(done) + (f" (lo pedía {fix['for']})" if fix.get("for") else "")
        if kind == "jvm_option":
            opt = str(fix.get("option") or "").strip()
            if not opt:
                raise RuntimeError("Falta la opción.")
            where = []
            tokens = (self.meta.get("jvm_args") or "").split()
            kept = [a for a in tokens if opt not in a]
            if len(kept) != len(tokens):
                self.meta["jvm_args"] = " ".join(kept)
                self.save_meta()
                where.append("los argumentos extra de Java")
            ujvm = os.path.join(self.dir, "user_jvm_args.txt")
            if os.path.isfile(ujvm):
                lines = _read_text(ujvm).splitlines()
                new = [("# (quitado por Servidor Home) " + l) if opt in l and not l.lstrip().startswith("#") else l for l in lines]
                if new != lines:
                    with open(ujvm, "w", encoding="utf-8") as fh:
                        fh.write("\n".join(new) + "\n")
                    where.append("user_jvm_args.txt")
            if not where:
                raise RuntimeError(f"No encontré «{opt}» en los argumentos de Java de este servidor.")
            return f"quité la opción de Java «{opt}» de {' y '.join(where)}"
        if kind == "reinstall":
            if not self.meta.get("type") or not self.meta.get("mc_version"):
                raise RuntimeError("No sé qué servidor reinstalar.")
            self._remove_runtime(t)
            self.meta.update({"preinstalled": False, "installed": False})
            self.meta.pop("launch", None)
            self.save_meta()
            try:
                self._install_worker(autostart=False, keep_progress=True, in_repair=True)
            except Exception as e:
                raise RuntimeError(f"no se pudo reinstalar: {e}")
            return f"reinstalé los archivos de {SERVER_TYPES[t]['label']} (el mundo y los mods no se tocaron)"
        if kind == "download_mod":
            os.makedirs(self.mods_dir, exist_ok=True)
            got = fetch_mod_from_modrinth(fix["mod"], t, mc, self.mods_dir, self.log, progress=self._dl_progress)
            if not got:
                raise RuntimeError(f"No encontré «{fix['mod']}» para {SERVER_TYPES[t]['label']} {mc} en Modrinth. "
                                   "Búscalo en CurseForge o Modrinth y agrégalo en la pestaña Mods.")
            return f"descargué {got[0]}" + (f" (lo pedía {fix['for']})" if fix.get("for") else "")
        if kind == "update_mod":
            mod = fix["mod"].lower()
            cur = mod_index(self.mods_dir).get(mod)
            skip = set()
            if cur:
                with open(os.path.join(self.mods_dir, cur), "rb") as fh:
                    skip.add(hashlib.sha1(fh.read()).hexdigest())
                os.replace(os.path.join(self.mods_dir, cur), os.path.join(self.mods_dir, cur + ".disabled"))
            got = fetch_mod_from_modrinth(mod, t, mc, self.mods_dir, self.log, skip_sha1=skip, progress=self._dl_progress)
            if not got:
                if cur:
                    os.replace(os.path.join(self.mods_dir, cur + ".disabled"), os.path.join(self.mods_dir, cur))
                raise RuntimeError(f"No encontré otra versión de «{mod}» para {SERVER_TYPES[t]['label']} {mc} en Modrinth.")
            return f"cambié {cur or mod} por {got[0]}"
        if kind == "downgrade_loader":
            if t != "fabric":
                raise RuntimeError("Este arreglo es para servidores Fabric.")
            cur = self.meta.get("loader_version")
            below = fix.get("below") or cur
            infos = [scan_mod_jar(os.path.join(self.mods_dir, f)) for f in list_mod_files(self.mods_dir)]
            prefer = launcher_loader_version(self.modpack_path(), mc)
            try:
                new = pick_fabric_loader(mc, infos, below=below, prefer=prefer)
            except Exception as e:
                raise RuntimeError(f"No pude consultar las versiones de Fabric Loader ({e}). Revisa la conexión a internet.")
            if not new or (cur and version_key(new) >= version_key(cur)):
                lo, _hi, lo_mod, _hm = fabric_loader_bounds(infos, who=True)
                raise RuntimeError(f"No hay una versión de Fabric Loader anterior a la {below} que sirva para todos los mods"
                                   + (f" («{lo_mod}» pide la {lo} o más nueva)." if lo_mod else "."))
            # que un arreglo posterior («un mod pide un loader más nuevo») no lo vuelva a subir a una que no sirve
            self.meta["fabric_tope"] = {"below": below, "mod": fix.get("culprit") or ""}
            self._remove_runtime(t, keep_game=True)
            self.meta.update({"loader_version": new, "preinstalled": False, "installed": False})
            self.meta.pop("launch", None)
            self.save_meta()
            try:
                self._install_worker(autostart=False, keep_progress=True, in_repair=True)
            except Exception as e:
                raise RuntimeError(f"no se pudo instalar Fabric Loader {new}: {e}")
            why = " (la misma con la que tu launcher abre este modpack)" if new == prefer else ""
            return f"cambié Fabric Loader {cur} por {new}{why}"
        if kind == "update_loader":
            if t not in LOADERS:
                raise RuntimeError("Este servidor no usa loader.")
            cur = self.meta.get("loader_version")
            if t == "fabric":
                # la más nueva que calce con lo que piden los mods y con el tope que haya dejado un arreglo anterior
                tope = (self.meta.get("fabric_tope") or {}).get("below")
                infos = [scan_mod_jar(os.path.join(self.mods_dir, f)) for f in list_mod_files(self.mods_dir)]
                if fix.get("min"):          # la versión que pidió el error (puede venir de un mod dentro de otro)
                    infos.append({"names": ["el mod que falló"], "deps": [{"id": "fabricloader", "range": ">=" + fix["min"]}]})
                best = pick_fabric_loader(mc, infos, below=tope, newer_than=cur)
                newer = [best] if best else []
                if not newer and tope:
                    lo, _hi, lo_mod, _hm = fabric_loader_bounds(infos, who=True)
                    culprit = (self.meta.get("fabric_tope") or {}).get("mod")
                    raise RuntimeError(
                        (f"«{lo_mod}» pide Fabric Loader {lo} o más nueva" if lo_mod else "Un mod pide un Fabric Loader más nuevo")
                        + f", pero {('«' + culprit + '»') if culprit else 'otro mod'} no funciona desde la {tope}. "
                        "Desactiva uno de los dos en la pestaña Mods.")
            else:
                cands = [v["id"] for v in LOADERS[t](mc) if not re.search(r"beta|alpha|rc|pre", v["id"], re.I)]
                newer = sorted((v for v in cands if not cur or version_key(v) > version_key(cur)), key=version_key, reverse=True)
            if not newer:
                raise RuntimeError(f"Ya tienes la versión más nueva de {SERVER_TYPES[t]['label']} para Minecraft {mc}; "
                                   "algún mod pide una que todavía no existe o es para otra versión.")
            self._remove_runtime(t, keep_game=(t == "fabric"))
            self.meta.update({"loader_version": newer[0], "preinstalled": False, "installed": False})
            self.meta.pop("launch", None)
            self.save_meta()
            try:
                self._install_worker(autostart=False, keep_progress=True, in_repair=True)
            except Exception as e:
                raise RuntimeError(f"no se pudo instalar {SERVER_TYPES[t]['label']} {newer[0]}: {e}")
            return f"actualicé {SERVER_TYPES[t]['label']} de {cur} a {newer[0]}"
        if kind == "ram":
            old = self.meta.get("ram_mb")
            self.meta["ram_mb"] = int(fix["mb"])
            self.save_meta()
            return f"{'bajé' if old and int(fix['mb']) < int(old) else 'subí'} la RAM de {old} MB a {fix['mb']} MB"
        if kind == "java":
            major = int(fix["major"])
            java = ensure_java(major, self.log, progress=self._dl_progress(f"Descargando Java {major}"))
            self.meta.update({"java_major": major, "java_path": java})
            self.save_meta()
            return f"ahora usa Java {major}"
        if kind == "port":
            old = self.port()
            new = free_port(max(DEFAULT_PORT + 1, old + 1), avoid={o.port() for o in manager.servers.values()} if manager else ())
            write_properties(os.path.join(self.dir, "server.properties"), {"server-port": new})
            return f"cambié el puerto de {old} a {new} (en tu casa se entra con :{new}; la dirección de playit.gg no cambia)"
        if kind == "reset_config":
            rel = fix["file"]
            full = safe_join(self.dir, rel)
            if not full or not os.path.isfile(full):
                raise RuntimeError("No encontré ese archivo de configuración.")
            os.replace(full, full + time.strftime(".danado-%Y%m%d-%H%M%S"))
            return f"restablecí {os.path.basename(rel)} (el dañado quedó guardado al lado)"
        if kind == "max_tick":
            write_properties(os.path.join(self.dir, "server.properties"), {"max-tick-time": -1})
            return "desactivé el vigilante que cortaba el servidor en momentos de mucha carga"
        if kind == "eula":
            with open(os.path.join(self.dir, "eula.txt"), "w") as f:
                f.write("# Aceptado desde Servidor Home (https://aka.ms/MinecraftEULA)\neula=true\n")
            return "acepté el EULA"
        if kind == "dedupe":
            done = dedupe_mods(self.mods_dir, self.log)
            if not done:
                raise RuntimeError("No encontré mods repetidos.")
            return "; ".join(done)
        raise ValueError("Arreglo desconocido.")

    # ---- rendimiento ----
    def add_perf_mods(self):
        """Agrega desde Modrinth los mods de rendimiento que le falten (para esta versión y loader)."""
        t, mc = self.meta.get("type"), self.meta.get("mc_version")
        plan = PERF_MODS.get(t)
        if not plan:
            raise RuntimeError("Los mods de rendimiento son para servidores Fabric, Forge o NeoForge "
                               "(Paper ya viene optimizado).")
        with self.lock:
            if self.running() or self.repair_busy or self.status in ("instalando", "iniciando", "reparando", "deteniendo"):
                raise RuntimeError("Apaga el servidor antes de agregar mods.")
            prev = self.status
            self.status = "instalando"
            self.progress = Progress("optimizando", [(mid, f"Agregando {name}", 1) for mid, name, _alts in plan])
        added, had, missing = [], [], []
        try:
            os.makedirs(self.mods_dir, exist_ok=True)
            present = set(mod_index(self.mods_dir))
            for f in os.listdir(self.mods_dir):            # los que la persona desactivó a propósito también cuentan
                if f.endswith(".jar.disabled"):
                    present.update(scan_mod_jar(os.path.join(self.mods_dir, f)).get("ids", []))
            for mid, name, alts in plan:
                self.progress.begin(mid)
                if any(a in present for a in alts):
                    had.append(name)
                    continue
                self.log(f"Buscando {name} para {SERVER_TYPES[t]['label']} {mc} en Modrinth...")
                got = fetch_mod_from_modrinth(mid, t, mc, self.mods_dir, self.log, progress=self._dl_progress)
                if got:
                    added.append(f"{name} {got[1]}".strip())
                    self.log(f"  Listo: {got[0]}")
                else:
                    missing.append(name)
        finally:
            with self.lock:
                self.progress = None
                self.status = prev if prev in ("detenido", "error", "sin instalar") else "detenido"
        parts = []
        if added:
            parts.append("Agregué " + ", ".join(added) + ".")
        if had:
            parts.append("Ya tenía " + ", ".join(had) + ".")
        if missing:
            parts.append("No hay " + ", ".join(missing) + f" para Minecraft {mc} con {SERVER_TYPES[t]['label']}.")
        msg = " ".join(parts)
        self.log(msg)
        return {"added": added, "had": had, "missing": missing, "message": msg}

    # ---- cambiar de versión ----
    def world_dirs(self):
        props = read_properties(os.path.join(self.dir, "server.properties"))
        level = props.get("level-name", "world") or "world"
        return [d for d in (level, level + "_nether", level + "_the_end") if os.path.isdir(os.path.join(self.dir, d))]

    def change_version(self, mc, lv=None, new_world=False):
        """Pasa el servidor a otra versión de Minecraft (o del loader) conservando mundo, mods y ajustes.
        Antes respalda el mundo; con new_world el mundo actual se guarda aparte y se empieza uno nuevo."""
        t = self.meta.get("type")
        mc = (mc or "").strip()
        lv = (lv or "").strip() or None
        if t not in SERVER_TYPES:
            raise RuntimeError("Tipo de servidor desconocido.")
        if not mc:
            raise ValueError("Elige la versión de Minecraft.")
        if t not in LOADERS:
            lv = None
        old_mc, old_lv = self.meta.get("mc_version"), self.meta.get("loader_version")
        if mc == old_mc and (lv is None or lv == old_lv) and not new_world and self.meta.get("installed"):
            raise ValueError(f"El servidor ya está en Minecraft {mc}" + (f" con {SERVER_TYPES[t]['label']} {old_lv}." if old_lv else "."))
        check_version(t, mc, lv)
        with self.lock:
            if self.running() or self.repair_busy or self.status in ("instalando", "iniciando", "deteniendo", "reparando"):
                raise RuntimeError("Apaga el servidor antes de cambiar la versión.")
            self.status = "instalando"
            self.error = None
            self.hint = None
        threading.Thread(target=self._change_version_worker, args=(t, mc, lv, old_mc, old_lv, new_world),
                         daemon=True).start()

    def _change_version_worker(self, t, mc, lv, old_mc, old_lv, new_world):
        label = SERVER_TYPES[t]["label"]
        before = f"{label} {old_lv} · Minecraft {old_mc}" if old_lv else f"{label} · Minecraft {old_mc}"
        after = f"{label} {lv} · Minecraft {mc}" if lv else f"{label} · Minecraft {mc}"
        self.log(f"== Cambiando de versión: {before} → Minecraft {mc}" + (f" ({label} {lv})" if lv else "") + " ==")
        pr = self.progress = Progress("cambiando", [("backup", "Respaldando el mundo", 12)] +
                                      self.install_phases(preinstalled=False))
        try:
            worlds = self.world_dirs()
            if worlds:
                self.log("Respaldando el mundo antes del cambio...")
                self.backup(progress=lambda d, t: pr.update(d / t, f"Respaldando el mundo: {d} de {t} archivos"))
            if new_world and worlds:
                keep = os.path.join(self.dir, "mundos-anteriores",
                                    f"{slugify(old_mc or 'antes')}-{time.strftime('%Y%m%d-%H%M%S')}")
                os.makedirs(keep, exist_ok=True)
                for w in worlds:
                    shutil.move(os.path.join(self.dir, w), os.path.join(keep, w))
                self.log(f"El mundo anterior quedó guardado en mundos-anteriores\\{os.path.basename(keep)}"
                         if IS_WINDOWS else f"El mundo anterior quedó guardado en mundos-anteriores/{os.path.basename(keep)}")
            self._remove_runtime(t)
            if self.meta.get("name") == f"{label} {old_mc}":      # nombre automático: que siga a la versión
                self.meta["name"] = f"{label} {mc}"
            self.meta.update({"mc_version": mc, "loader_version": lv, "preinstalled": False, "installed": False})
            self.meta.pop("launch", None)
            hist = self.meta.setdefault("versiones_anteriores", [])
            hist.append({"de": before, "a": after, "fecha": time.strftime("%Y-%m-%d %H:%M")})
            del hist[:-10]
            self.save_meta()
        except Exception as e:
            self.progress = None
            self.status = "error" if not self.meta.get("installed") else "detenido"
            self.error = f"No se pudo cambiar la versión: {e}"
            self.log(self.error, "err")
            traceback.print_exc()
            return
        self._install_worker(autostart=False, keep_progress=True)
        if self.status == "detenido":
            self.log(f"Listo: ahora es {label} · Minecraft {mc}. Tus amigos deben entrar con Minecraft {mc}.")

    def _remove_runtime(self, t, keep_game=False):
        """Quita los archivos de arranque de la versión anterior (no toca mundo, mods ni configuración).
        keep_game=True (solo cambia la versión de Fabric Loader): deja el servidor de Minecraft ya descargado."""
        def rm(rel):
            full = os.path.join(self.dir, rel)
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            elif os.path.exists(full):
                os.remove(full)
        if t in ("vanilla", "paper"):
            rm("server.jar")
        elif t == "fabric" and keep_game:
            for rel in ("fabric-server-launch.jar", "fabric-server-launcher.properties",
                        os.path.join(".fabric", "remappedJars"), os.path.join(".fabric", "processedMods")):
                rm(rel)
            srv = os.path.join(self.dir, ".fabric", "server")
            for f in os.listdir(srv) if os.path.isdir(srv) else []:
                if f.startswith("fabric-loader-server-"):      # el arranque de la versión anterior del loader
                    rm(os.path.join(".fabric", "server", f))
        elif t == "fabric":
            for rel in ("fabric-server-launch.jar", "fabric-server-launcher.properties", "server.jar",
                        os.path.join(".fabric", "server"), os.path.join(".fabric", "remappedJars")):
                rm(rel)
        elif t in ("forge", "neoforge"):
            for f in os.listdir(self.dir):
                low = f.lower()
                if low in ("run.bat", "run.sh") or (low.endswith(".jar") and (
                        low.startswith(("forge-", "neoforge-", "minecraft_server")) or low == "server.jar")):
                    rm(f)
            for rel in (os.path.join("libraries", "net", "minecraftforge", "forge"),
                        os.path.join("libraries", "net", "neoforged", "neoforge"),
                        os.path.join("libraries", "net", "neoforged", "forge")):
                rm(rel)

    # ---- mods / plugins ----
    def addons_path(self):
        d = SERVER_TYPES.get(self.meta.get("type"), {}).get("addons")
        if not d:
            raise RuntimeError("Este tipo de servidor no usa mods ni plugins.")
        p = os.path.join(self.dir, d)
        os.makedirs(p, exist_ok=True)
        return p

    def list_addons(self):
        p = self.addons_path()
        client = self.meta.get("client_mods") or {}
        broken = self.meta.get("broken_mods") or {}
        out = []
        for f in sorted(os.listdir(p), key=str.lower):
            fp = os.path.join(p, f)
            if os.path.isfile(fp) and (f.endswith(".jar") or f.endswith(".jar.disabled") or f.endswith(".zip")):
                item = {"name": f, "size": os.path.getsize(fp), "enabled": not f.endswith(".disabled")}
                base = f[: -len(".disabled")] if f.endswith(".disabled") else None
                if base in broken:
                    item["why"] = "La app lo desactivó: " + broken[base]
                elif base in client:
                    item["why"] = "Solo del jugador: " + client[base]
                out.append(item)
        return out

    def forget_marks(self, name):
        """La persona activó o quitó un mod a mano: se olvida por qué lo había desactivado la app."""
        base = name[: -len(".disabled")] if name.endswith(".disabled") else name
        changed = False
        for key in ("broken_mods", "client_mods"):
            if base in (self.meta.get(key) or {}):
                del self.meta[key][base]
                changed = True
        if changed:
            self.save_meta()

    # ---- respaldos ----
    def backup(self, progress=None):
        props = read_properties(os.path.join(self.dir, "server.properties"))
        level = props.get("level-name", "world")
        worlds = [d for d in (level, level + "_nether", level + "_the_end") if os.path.isdir(os.path.join(self.dir, d))]
        if not worlds:
            raise RuntimeError("Todavía no hay mundo que respaldar (enciende el servidor al menos una vez).")
        running = self.running()
        if running:
            self.send("save-off")
            self.send("save-all flush")
            time.sleep(3)
        try:
            bdir = os.path.join(self.dir, "respaldos")
            os.makedirs(bdir, exist_ok=True)
            stem = time.strftime("respaldo-%Y%m%d-%H%M%S")
            dest, n = os.path.join(bdir, stem + ".zip"), 2
            while os.path.exists(dest):
                dest, n = os.path.join(bdir, f"{stem}-{n}.zip"), n + 1
            name = os.path.basename(dest)
            todo = []
            for w in worlds:
                for root, _dirs, files in os.walk(os.path.join(self.dir, w)):
                    todo += [os.path.join(root, f) for f in files if f != "session.lock"]
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for n, full in enumerate(todo, 1):
                    z.write(full, os.path.relpath(full, self.dir))
                    if progress and (n % 20 == 0 or n == len(todo)):
                        progress(n, len(todo))
            self.log(f"Respaldo creado: {name} ({os.path.getsize(dest) // 1048576} MB)")
            return name
        finally:
            if running and self.running():
                self.send("save-on")

    def list_backups(self):
        bdir = os.path.join(self.dir, "respaldos")
        if not os.path.isdir(bdir):
            return []
        return [{"name": f, "size": os.path.getsize(os.path.join(bdir, f))}
                for f in sorted(os.listdir(bdir), reverse=True) if f.endswith(".zip")]

    # ---- imagen del servidor (la que se ve en la lista de servidores de Minecraft) ----
    @property
    def icon_path(self):
        return os.path.join(self.dir, "server-icon.png")

    def icon_version(self):
        try:
            return int(os.path.getmtime(self.icon_path) * 1000)
        except OSError:
            return 0

    def set_icon(self, data):
        size = png_size(data)
        if not size:
            raise ValueError("La imagen tiene que ser un PNG.")
        if size != (64, 64):
            raise ValueError(f"La imagen tiene que medir 64×64 píxeles (esta mide {size[0]}×{size[1]}).")
        tmp = self.icon_path + ".nueva"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self.icon_path)
        self.log("Cambié la imagen del servidor." + (" Se verá en la lista de servidores después de reiniciarlo."
                                                     if self.running() else ""))

    def remove_icon(self):
        if os.path.exists(self.icon_path):
            os.remove(self.icon_path)
            self.log("Quité la imagen del servidor.")

    # ---- mods para los amigos ----
    def share_plan(self):
        """Lo que va en el zip para los amigos: [(ruta dentro del zip, archivo)] y cuántos mods de cada tipo.
        Van los mods activos (menos los que solo sirven en el servidor) y los mods del jugador que el servidor tiene
        desactivados (gráficos, interfaz...), que también son parte del modpack."""
        if SERVER_TYPES.get(self.meta.get("type"), {}).get("addons") != "mods":
            raise RuntimeError("Este servidor no usa mods: tus amigos entran con Minecraft normal.")
        md = self.mods_dir
        files = sorted(os.listdir(md), key=str.lower) if os.path.isdir(md) else []
        entries, names, ids = [], set(), set()
        counts = {"servidor": 0, "cliente": 0, "omitidos": []}
        for f in files:
            if not f.lower().endswith(".jar") or not os.path.isfile(os.path.join(md, f)):
                continue
            info = scan_mod_jar(os.path.join(md, f))
            if info.get("bad") or info.get("server_only"):
                counts["omitidos"].append(f)
                continue
            entries.append(("mods/" + f, os.path.join(md, f)))
            names.add(f.lower())
            ids.update(info.get("ids", []))
            counts["servidor"] += 1
        marks = self.meta.get("client_mods") or {}
        for f in files:
            if not f.lower().endswith(".jar.disabled"):
                continue
            base = f[: -len(".disabled")]
            info = scan_mod_jar(os.path.join(md, f))
            if info.get("bad") or not info.get("ids") or not (info.get("client_only") or base in marks):
                continue                    # desactivado por otra razón (repetido, dañado o a propósito)
            if base.lower() in names or any(i in ids for i in info["ids"]):
                continue                    # ya va otra versión de ese mod
            entries.append(("mods/" + base, os.path.join(md, f)))
            names.add(base.lower())
            ids.update(info["ids"])
            counts["cliente"] += 1
        # KubeJS: los ítems nuevos, las texturas y los scripts del jugador también hacen falta en el juego
        kj = os.path.join(self.dir, "kubejs")
        for sub in ("startup_scripts", "client_scripts", "assets"):
            for root, _dirs, fs in os.walk(os.path.join(kj, sub)):
                for x in sorted(fs):
                    full = os.path.join(root, x)
                    entries.append((os.path.relpath(full, self.dir).replace(os.sep, "/"), full))
        return entries, counts

    def share_readme(self, counts, has_kubejs):
        t, mc = self.meta.get("type"), self.meta.get("mc_version") or "?"
        lv = self.meta.get("loader_version") or ""
        label = SERVER_TYPES.get(t, {}).get("label", t or "")
        name = self.meta.get("name") or self.id
        if t == "neoforge" and lv:
            how = f"   Descarga el instalador: {NEOFORGE_MAVEN}/{lv}/neoforge-{lv}-installer.jar\n" \
                  "   Ábrelo, deja marcado «Install client» y presiona OK."
        elif t == "forge" and lv:
            how = f"   Descarga el instalador: {FORGE_MAVEN}/{mc}-{lv}/forge-{mc}-{lv}-installer.jar\n" \
                  "   Ábrelo, deja marcado «Install client» y presiona OK."
        elif t == "fabric":
            how = f"   Descarga el instalador de https://fabricmc.net/use/installer/ y elige Minecraft {mc}" + \
                  (f" y el loader {lv}." if lv else ".")
        else:
            how = f"   Instala {label} {lv} para Minecraft {mc}."
        addr = None
        try:
            addr = manager.playit.state().get("address") if manager and manager.playit else None
        except Exception:
            addr = None
        port = self.port()
        lines = [
            f"Mods para jugar en «{name}»",
            "=" * min(70, len(name) + 22),
            "",
            f"El servidor usa Minecraft {mc} con {label} {lv}. Para entrar necesitas lo mismo en tu juego,".replace("  ", " "),
            "con estos mods.",
            "",
            f"1) Instala {label} {lv} para Minecraft {mc}".replace("  ", " "),
            how,
            "   Si usas CurseForge, Prism Launcher, Modrinth App o SKLauncher: crea una instancia nueva de",
            f"   Minecraft {mc} con {label} {lv}.".replace("  ", " "),
            "",
            "2) Copia los mods",
            "   Copia todo lo que está en la carpeta «mods» de este zip dentro de la carpeta «mods» de tu juego:",
            "   - Launcher oficial: presiona Windows + R, escribe %appdata%\\.minecraft y entra a «mods»",
            "     (si no existe, créala).",
            "   - CurseForge, Prism o Modrinth App: en la instancia, «Abrir carpeta» y entra a «mods».",
            "   Si ya tenías otros mods ahí, sácalos antes (guárdalos en otra carpeta) para que no choquen.",
        ]
        if has_kubejs:
            lines.append("   Copia también la carpeta «kubejs» de este zip junto a la carpeta «mods».")
        lines += [
            "",
            f"3) Abre Minecraft con el perfil de {label} y entra al servidor:",
            f"   {addr}" if addr else f"   Pídele la dirección a quien tiene el servidor (en su misma red: su IP"
                                     f"{'' if port == DEFAULT_PORT else ':' + str(port)}).",
            "",
            f"Qué trae: {counts['servidor']} mods que también usa el servidor"
            + (f" y {counts['cliente']} que son solo para el jugador (gráficos, interfaz, sonido)." if counts["cliente"] else "."),
        ]
        pack = (self.meta.get("modpack") or {}).get("source")
        if pack:
            lines += ["", f"Este servidor viene del modpack «{pack}». Si ya lo tienes instalado en la misma versión,",
                      "no necesitas este zip."]
        lines += ["", f"Armado por Servidor Home el {time.strftime('%d-%m-%Y')}."]
        return "\r\n".join(lines) + "\r\n"

    def build_share_zip(self):
        if SERVER_TYPES.get(self.meta.get("type"), {}).get("addons") != "mods":
            raise RuntimeError("Este servidor no usa mods: tus amigos entran con Minecraft normal.")
        with self.lock:
            if self.share and self.share.get("estado") == "armando":
                raise RuntimeError("El zip ya se está armando.")
            if self.status in ("instalando", "reparando"):
                raise RuntimeError("Espera a que el servidor termine lo que está haciendo.")
            self.share = {"estado": "armando", "pct": 0, "detalle": "Revisando los mods…"}
        threading.Thread(target=self._share_worker, daemon=True).start()

    def _share_worker(self):
        tmp = None
        try:
            entries, counts = self.share_plan()
            if not counts["servidor"] + counts["cliente"]:
                raise RuntimeError("Este servidor todavía no tiene mods para compartir.")
            os.makedirs(SHARE_DIR, exist_ok=True)
            # sin tildes en el nombre del archivo: así llega bien por cualquier chat o programa para descomprimir
            plain = unicodedata.normalize("NFKD", self.meta.get("name") or "").encode("ascii", "ignore").decode("ascii")
            name = safe_filename(plain or self.id) + " - mods para amigos.zip"
            dest = os.path.join(SHARE_DIR, name)
            tmp = dest + ".armando"
            total = sum(os.path.getsize(p) for _a, p in entries) or 1
            done, n_mods, mods_total = 0, 0, counts["servidor"] + counts["cliente"]
            has_kubejs = any(a.startswith("kubejs/") for a, _p in entries)
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                z.writestr("LEEME.txt", self.share_readme(counts, has_kubejs).encode("utf-8"))
                for arc, path in entries:
                    is_jar = arc.lower().endswith(".jar")
                    z.write(path, arc, compress_type=zipfile.ZIP_STORED if is_jar else zipfile.ZIP_DEFLATED)
                    done += os.path.getsize(path)
                    n_mods += 1 if arc.startswith("mods/") else 0
                    self.share.update(pct=min(99, int(done * 100 / total)),
                                      detalle=f"{n_mods} de {mods_total} mods · {mb_text(done, total)}")
            os.replace(tmp, dest)
            tmp = None
            old = self.meta.get("share_zip")
            if old and old != name:
                try:
                    os.remove(os.path.join(SHARE_DIR, os.path.basename(old)))
                except OSError:
                    pass
            self.meta["share_zip"] = name
            self.save_meta()
            size = os.path.getsize(dest)
            self.share = {"estado": "listo", "archivo": name, "tamano": size, "mods": mods_total,
                          "servidor": counts["servidor"], "cliente": counts["cliente"], "t": int(time.time()),
                          "carpeta": SHARE_DIR}
            self.log(f"Zip de mods para tus amigos listo: {name} ({mods_total} mods, {size // 1048576} MB), "
                     f"en {SHARE_DIR}.")
        except Exception as e:
            self.share = {"estado": "error", "error": str(e)}
            self.log(f"No se pudo armar el zip de mods: {e}", "err")
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def share_file(self):
        name = os.path.basename(self.meta.get("share_zip") or "")
        path = os.path.join(SHARE_DIR, name)
        return path if name and os.path.isfile(path) else None

    def share_state(self):
        """Estado del zip para la interfaz (también si se armó en otra sesión de la app, o si alguien lo borró)."""
        sh = self.share
        if sh and sh.get("estado") in ("armando", "error"):
            return sh
        path = self.share_file()
        if not path:
            return None
        if sh and sh.get("archivo") == os.path.basename(path):
            return sh
        return {"estado": "listo", "archivo": os.path.basename(path), "tamano": os.path.getsize(path),
                "t": int(os.path.getmtime(path)), "carpeta": SHARE_DIR}


# --------------------------------------------------------------------------- #
# Importación de modpacks
# --------------------------------------------------------------------------- #

MRPACK_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
                "gitlab.com", "edge.forgecdn.net", "mediafilez.forgecdn.net"}


class ImportJob:
    def __init__(self, source_kind, path, original_name=None):
        self.id = "imp-" + secrets.token_hex(4)
        self.source_kind = source_kind          # "archivo" | "carpeta"
        self.path = path
        self.original_name = original_name or os.path.basename(path.rstrip(os.sep))
        self.status = "analizando"
        self.message = "Analizando…"
        self.progress = None
        self.error = None
        self.analysis = None
        self.stage_dir = None
        self.mrpack = None
        self.server_id = None
        self.created = time.time()
        self.fetch = None            # {"url", "name"}: el modpack se descarga antes de analizarlo (buscador)
        self.source_info = None      # de dónde vino (Modrinth/CurseForge), para mostrarlo

    def to_json(self):
        return {"id": self.id, "status": self.status, "message": self.message, "progress": self.progress,
                "error": self.error, "analysis": self.analysis, "source_kind": self.source_kind,
                "original_name": self.original_name, "server_id": self.server_id}

    def _fetch_pack(self):
        """Descarga el modpack elegido en el buscador (solo de los servidores permitidos) antes de analizarlo."""
        url, name = self.fetch["url"], self.fetch["name"]
        host = urllib.parse.urlparse(url).hostname or ""
        if host not in MRPACK_HOSTS:
            raise RuntimeError(f"No descargo modpacks desde {host}.")
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        dest = os.path.join(UPLOADS_DIR, secrets.token_hex(6) + "-" + re.sub(r"[^\w.\-]", "_", name))
        self.message = "Descargando el modpack…"

        def prog(done, total):
            self.progress = int(done * 100 / total) if total else None
            self.message = f"Descargando el modpack… {mb_text(done, total)}"
        try:
            download(url, dest, progress=prog)
        except Exception as e:
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            raise RuntimeError(f"No se pudo descargar el modpack: {e}")
        self.path = dest
        self.progress = None

    def run_analysis(self):
        try:
            if self.fetch:
                self._fetch_pack()
            if self.source_kind == "archivo":
                self._analyze_archive()
            else:
                self._analyze_folder()
            self.status = "listo"
            self.message = "Listo para importar."
            self.progress = None
            self._remove_upload()   # ya se descomprimió (en Windows solo se puede borrar con el zip cerrado)
        except Exception as e:
            if not isinstance(e, RuntimeError):
                traceback.print_exc()
            self.status = "error"
            self.error = str(e) if isinstance(e, RuntimeError) else f"No se pudo leer el modpack: {e}"
            self._cleanup_stage()

    def _remove_upload(self):
        if self.source_kind == "archivo" and self.path.startswith(UPLOADS_DIR) and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

    def _cleanup_stage(self):
        if self.stage_dir and os.path.exists(os.path.join(self.stage_dir, STAGING_MARK)):
            shutil.rmtree(self.stage_dir, ignore_errors=True)
        self._remove_upload()

    def _new_stage(self, name):
        base = slugify(name)
        sid, i = base, 2
        while os.path.exists(os.path.join(SERVERS_DIR, sid)):
            sid, i = f"{base}-{i}", i + 1
        d = os.path.join(SERVERS_DIR, sid)
        os.makedirs(d)
        open(os.path.join(d, STAGING_MARK), "w").close()
        self.stage_dir = d
        return d

    def _analyze_folder(self):
        path = os.path.abspath(os.path.expanduser(self.path))
        if os.path.isfile(path) and path.lower().endswith((".zip", ".mrpack")):
            self.source_kind = "archivo"
            self.path = path
            return self._analyze_archive()
        if not os.path.isdir(path):
            raise RuntimeError("Esa carpeta no existe.")
        gd = game_dir_of(path)
        if os.path.normpath(gd).startswith(os.path.normpath(SERVERS_DIR)):
            raise RuntimeError("Esa carpeta ya es un servidor de Servidor Home.")
        self.path = gd
        self.message = "Revisando los mods…"
        launcher = next((l for l, roots in launcher_roots() for r in roots if gd.startswith(r)), None)
        a = analyze_game_dir(gd, launcher=launcher)
        a["pack_kind"] = "instancia"
        a["name"] = a.get("name") or os.path.basename(path.rstrip(os.sep))
        if a["mods_count"] == 0 and a["type"] != "vanilla":
            raise RuntimeError("No encontré una carpeta mods en esa ruta.")
        if not a.get("installed"):
            choose_import_loader(a, os.path.join(gd, "mods"))
        self.analysis = a

    def _analyze_archive(self):
        path = self.path
        try:
            z = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise RuntimeError("El archivo no es un .zip válido (o está incompleto).")
        with z:
            names = [n for n in z.namelist() if n.strip("/")]
            base_name = re.sub(r"\.(zip|mrpack)$", "", self.original_name, flags=re.I)
            if "modrinth.index.json" in names:
                return self._analyze_mrpack(z, base_name)
            if "manifest.json" in names:
                try:
                    man = json.loads(z.read("manifest.json").decode("utf-8", "replace"))
                except ValueError:
                    man = {}
                if man.get("manifestType") == "minecraftModpack" and man.get("files"):
                    ov = man.get("overrides", "overrides")
                    jars_inside = sum(1 for n in names if n.startswith(ov + "/mods/") and n.endswith(".jar"))
                    if jars_inside < len(man["files"]) * 0.8 and cf_key():
                        return self._analyze_cf_manifest(z, man, base_name)
                    if jars_inside < len(man["files"]) * 0.8:
                        raise RuntimeError(
                            "Este zip es el modpack para el launcher de CurseForge: solo trae la lista de mods, "
                            "no los mods. Descarga los «Server Files» desde la página del modpack en CurseForge, "
                            "impórtalo «Desde mi launcher» si ya lo tienes instalado, o pon tu clave de la API de "
                            "CurseForge en «Buscar» para que la app descargue los mods sola.")
            # Pack de servidor: detectar si viene dentro de una carpeta
            tops = {n.split("/")[0] for n in names}
            prefix = ""
            if len(tops) == 1:
                top = next(iter(tops))
                if any(n.startswith(top + "/") for n in names) and top.lower() not in ("mods", "config", "world"):
                    prefix = top + "/"
            if "manifest.json" in names and any(n.startswith("overrides/") for n in names):
                prefix = "overrides/"
            stage = self._new_stage(base_name)
            self._extract(z, stage, prefix)
        # CurseForge (formato cliente con mods incluidos): manifest.json da la versión.
        if prefix == "overrides/":
            try:
                with zipfile.ZipFile(path) as z2:
                    with open(os.path.join(stage, "manifest.json"), "wb") as f:
                        f.write(z2.read("manifest.json"))
            except KeyError:
                pass
        self.message = "Revisando los mods…"
        a = analyze_game_dir(stage)
        a["pack_kind"] = "pack de servidor"
        a["name"] = a.get("name") or base_name
        if not a["type"]:
            a["warnings"].append("No pude reconocer el loader: elígelo abajo.")
        if not a.get("installed"):
            choose_import_loader(a, os.path.join(stage, "mods"))
        self.analysis = a

    def _extract(self, z, stage, prefix, only=None):
        infos = [i for i in z.infolist() if i.filename.startswith(prefix) and not i.is_dir()]
        if only:
            infos = [i for i in infos if only(i.filename)]
        total = sum(i.file_size for i in infos) or 1
        done, last = 0, -5
        for i in infos:
            rel = i.filename[len(prefix):]
            if not rel:
                continue
            out = safe_join(stage, rel)
            if not out:
                continue
            os.makedirs(lp(os.path.dirname(out)), exist_ok=True)
            with z.open(i) as src, open(lp(out), "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            done += i.file_size
            pct = int(done * 100 / total)
            if pct >= last + 5:
                last = pct
                self.progress = pct
                self.message = f"Descomprimiendo… {pct}%"
        self.progress = None

    def _analyze_cf_manifest(self, z, man, base_name):
        """Zip del launcher de CurseForge (solo trae la lista de mods): con la clave de la API se averigua de dónde
        bajar cada archivo y se importa igual que un .mrpack. Se dejan fuera los paquetes de texturas y shaders y
        los mods que CurseForge marca solo para el cliente (después se revisa cada .jar descargado)."""
        mc = (man.get("minecraft") or {}).get("version")
        t, lv = None, None
        for ml in (man.get("minecraft") or {}).get("modLoaders") or []:
            got = _loader_from_name(ml.get("id"))
            if got and (ml.get("primary") or not t):
                t, lv = got
        if t == "quilt":
            t = "fabric"
        ids = [int(f["fileID"]) for f in man["files"] if f.get("fileID")]
        self.message = f"Buscando los {len(ids)} mods en CurseForge…"
        files, mods_info = {}, {}
        for i in range(0, len(ids), 100):
            for f in cf_post("/mods/files", {"fileIds": ids[i:i + 100]}).get("data", []):
                files[f["id"]] = f
        pids = sorted({f["modId"] for f in files.values()})
        for i in range(0, len(pids), 100):
            for m in cf_post("/mods", {"modIds": pids[i:i + 100]}).get("data", []):
                mods_info[m["id"]] = m
        server_files, skipped, missing = [], [], []
        for fid in ids:
            f = files.get(fid)
            if not f:
                missing.append(str(fid))
                continue
            info = mods_info.get(f["modId"], {})
            if info.get("classId") not in (None, CF_CLASS_MODS):
                continue                      # texturas, shaders, mundos: el servidor no los usa
            gv = set(f.get("gameVersions") or [])
            sha1 = next((h["value"] for h in f.get("hashes") or [] if h.get("algo") == 1), None)
            entry = {"path": "mods/" + f["fileName"], "hashes": {"sha1": sha1} if sha1 else {},
                     "downloads": cf_file_urls(f), "fileSize": f.get("fileLength")}
            if "Client" in gv and "Server" not in gv:
                skipped.append({"file": f["fileName"], "name": info.get("name") or f["fileName"],
                                "reason": "CurseForge lo marca solo para el cliente (no se descargará).", "skip": True})
            else:
                server_files.append(entry)
        stage = self._new_stage(man.get("name") or base_name)
        self._extract(z, stage, (man.get("overrides") or "overrides") + "/",
                      only=lambda n: not n.lower().endswith((".zip",)) or "/mods/" in n)
        self.mrpack = {"files": server_files}
        warnings = []
        if missing:
            warnings.append(f"CurseForge no devolvió {len(missing)} archivos de la lista; quedarán fuera.")
        self.analysis = {
            "pack_kind": "CurseForge (lista de mods)", "name": man.get("name") or base_name, "type": t or "vanilla",
            "mc_version": mc, "loader_version": lv, "detected_from": "manifest.json + API de CurseForge",
            "installed": False, "mods_count": len(server_files) + len(list_mod_files(os.path.join(stage, "mods"))),
            "client_only": skipped, "warnings": warnings, "launcher": None,
            "ram_mb": 4096 if len(ids) < 60 else 6144 if len(ids) < 180 else 8192,
            "download_count": len(server_files),
        }

    def _analyze_mrpack(self, z, base_name):
        idx = json.loads(z.read("modrinth.index.json").decode("utf-8"))
        deps = idx.get("dependencies", {})
        mc = deps.get("minecraft")
        t, lv = None, None
        for key, typ in (("neoforge", "neoforge"), ("forge", "forge"), ("fabric-loader", "fabric"), ("quilt-loader", "quilt")):
            if deps.get(key):
                t, lv = typ, deps[key]
                break
        warnings = []
        if t == "quilt":
            warnings.append("Quilt no está soportado todavía; se usará Fabric.")
            t, lv = "fabric", None
        files = idx.get("files", [])
        server_files = [f for f in files if (f.get("env") or {}).get("server") != "unsupported"]
        skipped = [f for f in files if (f.get("env") or {}).get("server") == "unsupported"]
        stage = self._new_stage(idx.get("name") or base_name)
        # overrides primero, luego server-overrides (las del servidor mandan)
        for prefix in ("overrides/", "server-overrides/"):
            self._extract(z, stage, prefix)
        self.mrpack = {"files": server_files}
        mods_in_pack = sum(1 for f in server_files if f.get("path", "").startswith("mods/"))
        self.analysis = {
            "pack_kind": "Modrinth (.mrpack)", "name": idx.get("name") or base_name, "type": t or "vanilla",
            "mc_version": mc, "loader_version": lv, "detected_from": "modrinth.index.json",
            "installed": False, "mods_count": mods_in_pack + len(list_mod_files(os.path.join(stage, "mods"))),
            "client_only": [{"file": os.path.basename(f.get("path", "")), "name": os.path.basename(f.get("path", "")),
                             "reason": "Modrinth lo marca solo para el cliente (no se descargará).", "skip": True}
                            for f in skipped],
            "warnings": warnings, "launcher": None,
            "ram_mb": 4096 if len(files) < 60 else 6144 if len(files) < 180 else 8192,
            "download_count": len(server_files),
        }

def choose_import_loader(a, mods_dir):
    """Modpack de Fabric sin versión del loader conocida (por ejemplo una instancia que nunca se abrió): se elige la
    más nueva que calce con lo que piden sus mods, y si el modpack es de Minecraft 1.20.1 o anterior, la última 0.14
    (con la que se hicieron esos modpacks). Sin internet se deja como está: al instalar se usa la recomendada."""
    if a.get("type") != "fabric" or a.get("loader_version") or not a.get("mc_version"):
        return
    skip = {c.get("file") for c in a.get("client_only") or [] if isinstance(c, dict)}
    infos = [scan_mod_jar(os.path.join(mods_dir, f)) for f in list_mod_files(mods_dir) if f not in skip]
    try:
        lv = pick_fabric_loader(a["mc_version"], infos)
    except Exception:
        return
    if lv:
        a["loader_version"] = lv
        why = "Fabric Loader elegido según lo que piden los mods"
        a["detected_from"] = f"{a['detected_from']}, {why}" if a.get("detected_from") else why


def run_import_steps(server, pi, log):
    """Pasos de una importación: copiar/descargar el modpack y desactivar mods de cliente.
    Se guardan en los metadatos del servidor para poder reintentarlos si algo falla."""
    pr = server.progress
    if pi.get("copy_from"):
        log(f"Copiando el modpack desde {pi['copy_from']} ...")
        copy_instance(pi["copy_from"], server.dir, log, progress=(lambda d, t: pr.update(
            d / t, f"Copiando archivos: {mb_text(d, t)}")) if pr else None)
    if pi.get("mrpack_files"):
        n = len(pi["mrpack_files"])
        if pr:
            pr.update(0, f"0 de {n} mods")
        download_mrpack_files(pi["mrpack_files"], server.dir, log, progress=(lambda d, t: pr.update(
            d / t, f"Descargando mods: {d} de {t}")) if pr else None)
    disabled = 0
    reasons = pi.get("client_reasons") or {}
    todo = list(pi.get("disable") or [])
    if pi.get("mrpack_files"):
        # los modpacks descargados no siempre marcan bien los mods del jugador: se revisa cada .jar que bajó
        mods_dir = os.path.join(server.dir, "mods")
        for f in list_mod_files(mods_dir):
            why = scan_mod_jar(os.path.join(mods_dir, f)).get("client_only")
            if why and f not in todo:
                todo.append(f)
                reasons[f] = why
    for f in todo:
        f = os.path.basename(f)
        p = os.path.join(server.dir, "mods", f)
        if os.path.isfile(p):
            os.replace(p, p + ".disabled")
            disabled += 1
            server.meta.setdefault("client_mods", {})[f] = reasons.get(f) or "Solo para el jugador."
    if disabled:
        log(f"Desactivados {disabled} mods que son solo para el cliente (puedes reactivarlos en la pestaña Mods).")
    server.meta["revision_mods"] = MODS_REVISION         # importado con las reglas nuevas: nada que revisar
    props_path = os.path.join(server.dir, "server.properties")
    props = read_properties(props_path)
    updates = {}
    if "server-port" not in props:
        updates["server-port"] = DEFAULT_PORT
    if "motd" not in props:
        updates["motd"] = prop_escape(server.meta.get("name", "Servidor Home")[:59])
    if updates:
        write_properties(props_path, updates)


def download_mrpack_files(files, root, log, progress=None):
    total = len(files)
    log(f"Descargando {total} archivos del modpack desde Modrinth...")
    done = [0]
    lock = threading.Lock()

    def one(f):
        rel = f.get("path", "")
        out = safe_join(root, rel)
        if not out:
            raise RuntimeError(f"Ruta no válida en el modpack: {rel}")
        urls = f.get("downloads") or []
        last_err = None
        for url in urls:
            host = urllib.parse.urlparse(url).hostname or ""
            if host not in MRPACK_HOSTS:
                last_err = f"servidor de descarga no permitido ({host})"
                continue
            try:
                h = f.get("hashes") or {}
                download(url, lp(out), expected_sha1=h.get("sha1"), expected_sha512=None if h.get("sha1") else h.get("sha512"))
                last_err = None
                break
            except Exception as e:
                last_err = str(e)
        if last_err:
            raise RuntimeError(f"No se pudo descargar {rel}: {last_err}")
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], total)
            if done[0] % max(1, total // 10) == 0 or done[0] == total:
                log(f"  {done[0]}/{total} archivos")

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for fut in [ex.submit(one, f) for f in files]:
            fut.result()


# --------------------------------------------------------------------------- #
# Ajustes de la app (no de un servidor)
# --------------------------------------------------------------------------- #

APP_SETTINGS_FILE = os.path.join(APPDATA_DIR, "ajustes.json")
_settings_lock = threading.Lock()


def app_settings():
    try:
        with open(APP_SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def set_app_setting(key, value):
    with _settings_lock:
        d = app_settings()
        if value in (None, ""):
            d.pop(key, None)
        else:
            d[key] = value
        os.makedirs(os.path.dirname(APP_SETTINGS_FILE), exist_ok=True)
        tmp = APP_SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, APP_SETTINGS_FILE)


# --------------------------------------------------------------------------- #
# Buscador de modpacks: Modrinth (API abierta) y CurseForge (pide una clave de su API)
# --------------------------------------------------------------------------- #

CURSEFORGE_API = "https://api.curseforge.com/v1"
CF_GAME_MINECRAFT = 432
CF_CLASS_MODPACKS = 4471
CF_CLASS_MODS = 6
CF_LOADERS = {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}


def cf_key():
    return (app_settings().get("curseforge_key") or "").strip()


def _cf_request(path, body=None, key=None):
    key = key or cf_key()
    if not key:
        raise RuntimeError("Falta la clave de la API de CurseForge.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CURSEFORGE_API + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"User-Agent": USER_AGENT, "x-api-key": key, "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("CurseForge rechazó la clave de su API. Revisa que esté completa en «Buscar» → CurseForge "
                               "(si ya funcionaba, espera un rato: CurseForge limita las consultas seguidas).")
        raise RuntimeError(f"CurseForge respondió con un error ({e.code}).")
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"No me pude conectar con CurseForge: {e}")


def cf_get(path, key=None):
    return _cf_request(path, key=key)


def cf_post(path, body):
    return _cf_request(path, body)


def cf_file_urls(f):
    """Dónde bajar un archivo de CurseForge: la dirección que da la API y, si el autor no la entrega (o falla),
    la del CDN, que se arma con el número y el nombre del archivo."""
    fid, name = int(f["id"]), f.get("fileName") or ""
    cdn = [f"https://{h}/files/{fid // 1000}/{fid % 1000}/{urllib.parse.quote(name, safe='!~*()' + chr(39))}"
           for h in ("mediafilez.forgecdn.net", "edge.forgecdn.net")]
    api_url = f.get("downloadUrl")
    if api_url:
        u = urllib.parse.urlsplit(api_url)
        api_url = urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(urllib.parse.unquote(u.path),
                                                                                   safe="/!~*()" + chr(39)), u.query, ""))
    return ([api_url] if api_url and api_url not in cdn else []) + cdn


def _mr_json(path):
    try:
        return http_json(MODRINTH_API + path, timeout=25)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Modrinth respondió con un error ({e.code}).")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"No me pude conectar con Modrinth: {e}")


def packs_search(src, query="", offset=0):
    """Modpacks que calzan con la búsqueda (vacía = los más descargados)."""
    query = (query or "").strip()[:100]
    offset = max(0, int(offset or 0))
    if src == "modrinth":
        facets = urllib.parse.quote(json.dumps([["project_type:modpack"]]))
        index = "relevance" if query else "downloads"
        d = _mr_json(f"/search?query={urllib.parse.quote(query)}&facets={facets}&index={index}&limit=20&offset={offset}")
        items = []
        for h in d.get("hits", []):
            loaders = [c for c in h.get("categories", []) + h.get("display_categories", [])
                       if c in ("fabric", "forge", "neoforge", "quilt")]
            items.append({"id": h.get("project_id"), "slug": h.get("slug"), "title": h.get("title"),
                          "desc": h.get("description"), "icon": h.get("icon_url"), "downloads": h.get("downloads", 0),
                          "author": h.get("author"), "mc": (h.get("versions") or [None])[-1],
                          "loaders": sorted(set(loaders)), "server": h.get("server_side") != "unsupported",
                          "url": f"https://modrinth.com/modpack/{h.get('slug')}"})
        return {"items": items, "total": d.get("total_hits", len(items)), "offset": offset}
    if src == "curseforge":
        if not cf_key():
            return {"items": [], "total": 0, "offset": 0, "need_key": True}
        q = urllib.parse.urlencode({"gameId": CF_GAME_MINECRAFT, "classId": CF_CLASS_MODPACKS, "searchFilter": query,
                                    "sortField": 2 if not query else 1, "sortOrder": "desc", "pageSize": 20, "index": offset})
        d = cf_get("/mods/search?" + q)
        items = []
        for m in d.get("data", []):
            idx = m.get("latestFilesIndexes") or []
            items.append({"id": m.get("id"), "slug": m.get("slug"), "title": m.get("name"), "desc": m.get("summary"),
                          "icon": (m.get("logo") or {}).get("thumbnailUrl"), "downloads": m.get("downloadCount", 0),
                          "author": ((m.get("authors") or [{}])[0]).get("name"),
                          "mc": idx[0].get("gameVersion") if idx else None,
                          "loaders": sorted({CF_LOADERS[i["modLoader"]] for i in idx if i.get("modLoader") in CF_LOADERS}),
                          "server": True, "url": (m.get("links") or {}).get("websiteUrl")})
        pg = d.get("pagination") or {}
        return {"items": items, "total": pg.get("totalCount", len(items)), "offset": offset}
    raise ValueError("Fuente desconocida.")


def packs_versions(src, pid):
    """Las versiones de un modpack, de la más nueva a la más vieja, con lo que necesita el servidor."""
    pid = str(pid)
    if not re.match(r"^[\w\-]{1,64}$", pid):
        raise ValueError("Modpack no válido.")
    out = []
    if src == "modrinth":
        for v in _mr_json(f"/project/{pid}/version"):
            f = next((x for x in v.get("files", []) if x.get("primary")), (v.get("files") or [None])[0])
            if not f or not f.get("filename", "").endswith(".mrpack"):
                continue
            out.append({"id": v["id"], "name": v.get("name") or v.get("version_number"), "number": v.get("version_number"),
                        "mc": v.get("game_versions") or [], "loaders": v.get("loaders") or [],
                        "date": v.get("date_published"), "type": v.get("version_type"), "size": f.get("size"),
                        "server_pack": True})
    elif src == "curseforge":
        d = cf_get(f"/mods/{pid}/files?pageSize=50")
        for f in d.get("data", []):
            if f.get("isServerPack"):
                continue
            gv = f.get("gameVersions") or []
            out.append({"id": f["id"], "name": f.get("displayName") or f.get("fileName"),
                        "number": f.get("displayName"), "mc": [g for g in gv if re.match(r"^\d+\.\d+", g)],
                        "loaders": sorted({g.lower() for g in gv if g.lower() in ("forge", "neoforge", "fabric", "quilt")}),
                        "date": f.get("fileDate"), "type": {1: "release", 2: "beta", 3: "alpha"}.get(f.get("releaseType")),
                        "size": f.get("fileLength"), "server_pack": bool(f.get("serverPackFileId")),
                        "server_pack_id": f.get("serverPackFileId")})
    else:
        raise ValueError("Fuente desconocida.")
    out.sort(key=lambda v: v.get("date") or "", reverse=True)
    return out


def packs_import(src, pid, vid, title=None):
    """Prepara la importación del modpack elegido: el servidor se arma con el pack de servidor si lo hay; si no,
    con la lista de mods del modpack (sin los que son solo del jugador)."""
    pid, vid = str(pid), str(vid)
    if not re.match(r"^[\w\-]{1,64}$", pid) or not re.match(r"^[\w\-]{1,64}$", vid):
        raise ValueError("Versión no válida.")
    if src == "modrinth":
        v = _mr_json(f"/version/{vid}")
        f = next((x for x in v.get("files", []) if x.get("primary")), (v.get("files") or [None])[0])
        if not f:
            raise RuntimeError("Esa versión no tiene archivo.")
        job = ImportJob("archivo", "", f.get("filename") or "modpack.mrpack")
        job.fetch = {"url": f["url"], "name": f.get("filename") or "modpack.mrpack"}
    elif src == "curseforge":
        f = cf_get(f"/mods/{pid}/files/{vid}").get("data") or {}
        sp = f.get("serverPackFileId")
        if sp:
            f = cf_get(f"/mods/{pid}/files/{sp}").get("data") or {}
        name = f.get("fileName") or "modpack.zip"
        job = ImportJob("archivo", "", name)
        job.fetch = {"url": cf_file_urls(f)[0], "name": name}
    else:
        raise ValueError("Fuente desconocida.")
    job.source_info = {"src": src, "project": pid, "version": vid, "title": title}
    return job


# --------------------------------------------------------------------------- #
# Jugadores: quién entró alguna vez, quién está conectado y sus permisos
# --------------------------------------------------------------------------- #

PLAYER_NAME_RE = re.compile(r"^[A-Za-z0-9_]{2,16}$")


def _read_json_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _write_json_list(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def offline_uuid(name):
    """El UUID que Minecraft le da a un jugador no premium (UUID.nameUUIDFromBytes("OfflinePlayer:" + nombre))."""
    b = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    b[6] = (b[6] & 0x0F) | 0x30
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def mojang_uuid(name):
    try:
        d = http_json("https://api.mojang.com/users/profiles/minecraft/" + urllib.parse.quote(name), timeout=15)
    except Exception:
        return None
    h = (d or {}).get("id") or ""
    if len(h) != 32:
        return None
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


# --------------------------------------------------------------------------- #
# playit.gg: dirección fija para jugar por internet sin abrir puertos
# --------------------------------------------------------------------------- #

PLAYIT_API = "https://api.playit.gg"
PLAYIT_VERSION = "1.0.10"   # versión probada; si ya no existe se usa la última publicada
PLAYIT_DOWNLOAD = f"https://github.com/playit-cloud/playit-agent/releases/download/v{PLAYIT_VERSION}/"
PLAYIT_DOWNLOAD_LATEST = "https://github.com/playit-cloud/playit-agent/releases/latest/download/"
PLAYIT_ASSETS = {"x86_64": "playit-linux-amd64", "amd64": "playit-linux-amd64",
                 "aarch64": "playit-linux-aarch64", "arm64": "playit-linux-aarch64",
                 "armv7l": "playit-linux-armv7", "i686": "playit-linux-i686", "i386": "playit-linux-i686"}
# En Windows el programa es el mismo «playitd» (preferimos la versión firmada digitalmente).
PLAYIT_ASSETS_WINDOWS = {"amd64": ["playit-windows-x86_64-signed.exe", "playit-windows-x86_64.exe"],
                         "x86_64": ["playit-windows-x86_64-signed.exe", "playit-windows-x86_64.exe"],
                         "arm64": ["playit-windows-x86_64-signed.exe", "playit-windows-x86_64.exe"],
                         "x86": ["playit-windows-x86-signed.exe", "playit-windows-x86.exe"]}
PLAYIT_SUPPORTED = sys.platform.startswith("linux") or IS_WINDOWS
PLAYIT_ERRORS = {
    "RequiresVerifiedAccount": "playit.gg pide que verifiques tu cuenta (correo) antes de crear la dirección. "
                               "Entra a playit.gg, verifica tu correo y vuelve a intentar.",
    "RequiresPlayitPremium": "Esa opción necesita playit Premium.",
    "RegionRequiresPlayitPremium": "Esa región necesita playit Premium.",
    "PublicPortRequiresPlayitPremium": "Elegir el puerto público necesita playit Premium.",
    "AgentVersionTooOld": "El programa de playit está desactualizado: borra la carpeta playit/playitd y reinicia la app.",
    "AgentNotFound": "playit.gg no encuentra este equipo; desvincula y vuelve a vincular.",
}


class PlayitError(Exception):
    def __init__(self, kind, data):
        self.kind, self.data = kind, data
        super().__init__(f"{kind}: {data}")


class Playit:
    def __init__(self):
        self.dir = PLAYIT_DIR
        self.secret_file = os.path.join(self.dir, "playit.toml")
        self.bin = os.path.join(self.dir, "playitd.exe" if IS_WINDOWS else "playitd")
        self.console = Console(600)
        self.lock = threading.RLock()
        self.proc = None
        self.gen = 0
        self.phase = "desvinculado"      # desvinculado | vinculando | conectando | listo | error
        self.message = None
        self.error = None
        self.claim_url = None
        self.agent_id = None
        self.tunnels = []
        self.pending = []
        self.notices = []
        self.account_status = None
        self.connected = False
        self.agent_error = None
        self.target_port = DEFAULT_PORT
        self.tunnel_error = None
        self.last_create_attempt = 0
        self.mode = (_read_text(os.path.join(self.dir, "modo.txt")).strip() or "self-managed")
        if self.secret():
            self.start()

    # ---- utilidades ----
    def secret(self):
        text = _read_text(self.secret_file)
        m = re.search(r'secret_key\s*=\s*"([0-9a-fA-F]+)"', text) or re.match(r"^\s*([0-9a-fA-F]{16,})\s*$", text)
        return m.group(1) if m else None

    def call(self, path, body=None, auth=True, timeout=20):
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if auth:
            headers["Authorization"] = "Agent-Key " + (self.secret() or "")
        req = urllib.request.Request(PLAYIT_API + path, data=json.dumps(body or {}).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 429:
                raise PlayitError("rate", "Demasiadas solicitudes a playit.gg; reintentando.")
            if not raw:
                raise PlayitError("http", f"HTTP {e.code}")
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise PlayitError("http", "Respuesta no válida de playit.gg")
        st = data.get("status")
        if st == "success":
            return data.get("data")
        raise PlayitError("fail" if st == "fail" else "error", data.get("data"))

    def address(self):
        for t in self.tunnels:
            if t["type"] == "minecraft-java" and t["address"] and not t["disabled"]:
                return t["address"]
        return None

    def state(self):
        return {"phase": self.phase, "message": self.message, "error": self.error, "claim_url": self.claim_url,
                "address": self.address(), "tunnels": self.tunnels, "pending": self.pending,
                "notices": self.notices, "account_status": self.account_status, "connected": self.connected,
                "running": self.proc is not None and self.proc.poll() is None,
                "agent_error": self.agent_error, "mode": self.mode,
                "tunnel_error": self.tunnel_error, "target_port": self.target_port,
                "supported": PLAYIT_SUPPORTED}

    # ---- vinculación (claim) ----
    def setup(self, mode="self-managed"):
        """self-managed: la app crea la dirección sola. assignable: la dirección se crea en la web de playit."""
        if mode not in ("self-managed", "assignable"):
            raise ValueError("Modo no válido.")
        with self.lock:
            if self.phase == "vinculando":
                return
            if self.secret():
                if mode == self.mode:
                    raise RuntimeError("Ya está vinculado con playit.gg.")
                self.unlink()
            if not PLAYIT_SUPPORTED:
                raise RuntimeError("La conexión automática con playit.gg está disponible en Windows y Linux.")
            code = secrets.token_hex(5)
            self.gen += 1
            gen = self.gen
            self.mode = mode
            self.claim_url = f"https://playit.gg/claim/{code}"
            self.phase = "vinculando"
            self.error = None
            self.message = "Abre el enlace y aprueba el programa."
        threading.Thread(target=self._claim_worker, args=(code, gen), daemon=True).start()
        # Descargamos el programa mientras la persona aprueba en el navegador.
        threading.Thread(target=self._prefetch_binary, daemon=True).start()

    def _prefetch_binary(self):
        try:
            self.ensure_binary()
        except Exception as e:
            self.console.add(f"No se pudo descargar playit todavía: {e}", "err")

    def _claim_worker(self, code, gen):
        deadline = time.time() + 30 * 60
        try:
            while True:
                if gen != self.gen:
                    return
                if time.time() > deadline:
                    raise RuntimeError("Se acabó el tiempo para aprobar en playit.gg. Vuelve a intentarlo.")
                try:
                    st = self.call("/claim/setup", {"code": code, "agent_type": self.mode,
                                                    "version": f"playit {PLAYIT_VERSION} (Servidor Home)"}, auth=False)
                except PlayitError as e:
                    if e.kind == "fail":
                        raise RuntimeError(f"playit.gg rechazó el código de vinculación ({e.data}). Vuelve a intentarlo.")
                    self.message = "playit.gg no responde bien; reintentando…"
                    time.sleep(3)
                    continue
                except (urllib.error.URLError, OSError):
                    self.message = "Sin conexión con playit.gg; reintentando…"
                    time.sleep(3)
                    continue
                if st == "WaitingForUserVisit":
                    self.message = "Abre el enlace y aprueba el programa."
                elif st == "WaitingForUser":
                    self.message = "Ahora aprueba el programa en la página de playit.gg."
                elif st == "UserAccepted":
                    break
                elif st == "UserRejected":
                    raise RuntimeError("La vinculación fue rechazada en playit.gg.")
                time.sleep(1.5)
            self.message = "¡Aprobado! Terminando de vincular…"
            secret = None
            for _ in range(90):
                if gen != self.gen:
                    return
                try:
                    secret = (self.call("/claim/exchange", {"code": code}, auth=False) or {}).get("secret_key")
                    if secret:
                        break
                except PlayitError as e:
                    if e.data in ("UserRejected", "CodeExpired", "CodeNotFound"):
                        raise RuntimeError(f"No se pudo completar la vinculación ({e.data}).")
                except (urllib.error.URLError, OSError):
                    pass
                time.sleep(2)
            if not secret:
                raise RuntimeError("playit.gg no entregó la clave del programa. Vuelve a intentarlo.")
            os.makedirs(self.dir, exist_ok=True)
            fd = os.open(self.secret_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(f'secret_key = "{secret}"\n')
            with open(os.path.join(self.dir, "modo.txt"), "w") as f:
                f.write(self.mode + "\n")
            self.claim_url = None
            self.console.add("Vinculado con playit.gg.", "app")
            self.start()
        except Exception as e:
            if gen == self.gen:
                self.phase = "error"
                self.error = str(e)
                self.claim_url = None

    def cancel_setup(self):
        with self.lock:
            self.gen += 1
            self.claim_url = None
            self.phase = "desvinculado"
            self.message = None
            self.error = None

    # ---- agente (playitd) ----
    def ensure_binary(self):
        if os.path.isfile(self.bin) and (IS_WINDOWS or os.access(self.bin, os.X_OK)):
            return
        if not PLAYIT_SUPPORTED:
            raise RuntimeError("La conexión automática con playit.gg está disponible en Windows y Linux.")
        machine = platform.machine().lower()
        if IS_WINDOWS:
            assets = PLAYIT_ASSETS_WINDOWS.get(machine) or PLAYIT_ASSETS_WINDOWS["amd64"]
        else:
            assets = [PLAYIT_ASSETS[machine]] if machine in PLAYIT_ASSETS else []
        if not assets:
            raise RuntimeError(f"playit.gg no tiene programa para este procesador ({platform.machine()}).")
        os.makedirs(self.dir, exist_ok=True)
        log = lambda m: self.console.add(m, "app")  # noqa: E731
        last = None
        for base in (PLAYIT_DOWNLOAD, PLAYIT_DOWNLOAD_LATEST):
            for asset in assets:
                try:
                    self.console.add(f"Descargando el programa de playit.gg ({asset})...", "app")
                    download(base + asset, self.bin, log)
                    if not IS_WINDOWS:
                        os.chmod(self.bin, 0o755)
                    return
                except urllib.error.HTTPError as e:
                    last = e
        raise RuntimeError(f"No encontré el programa de playit.gg para descargar ({last}).")

    def socket_path(self):
        if IS_WINDOWS:
            return r"\\.\pipe\servidor-home-playitd"
        base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        return os.path.join(base, f"servidor-home-playitd-{os.getuid() if hasattr(os, 'getuid') else 0}.sock")

    @property
    def pid_file(self):
        return os.path.join(self.dir, "playitd.pid")

    def _kill_stale_agent(self):
        """Evita dos agentes con la misma clave si la app se cerró de golpe la vez anterior."""
        if IS_WINDOWS:
            try:
                pid = int(_read_text(self.pid_file).strip() or 0)
            except ValueError:
                pid = 0
            if pid and windows_process_image(pid) == os.path.basename(self.bin).lower():
                windows_kill(pid)
            return
        if not os.path.isdir("/proc"):
            return
        pid = stale_process(self.pid_file, lambda p: os.path.realpath(os.readlink(f"/proc/{p}/exe")) == os.path.realpath(self.bin))
        if pid:
            try:
                os.kill(pid, signal.SIGINT)
                for _ in range(20):
                    if not pid_alive(pid):
                        break
                    time.sleep(0.25)
                else:
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def start(self):
        with self.lock:
            self.gen += 1
            gen = self.gen
            self.phase = "conectando"
            self.error = None
            self.message = "Conectando con playit.gg…"
        threading.Thread(target=self._agent_loop, args=(gen,), daemon=True).start()
        threading.Thread(target=self._poll_loop, args=(gen,), daemon=True).start()

    def _agent_loop(self, gen):
        backoff = 5
        while gen == self.gen:
            try:
                self.ensure_binary()
            except Exception as e:
                self.message = f"No se pudo descargar playit: {e}. Reintentando…"
                self.console.add(self.message, "err")
                time.sleep(30)
                continue
            self._kill_stale_agent()
            sock = self.socket_path()
            if not IS_WINDOWS:
                try:
                    os.remove(sock)
                except OSError:
                    pass
            cmd = [self.bin, "--secret-path", self.secret_file, "--socket-path", sock]
            env = dict(os.environ, PLAYIT_LOG="info")
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace", env=env, **child_kwargs(detach=True))
            except OSError as e:
                self.console.add(f"No se pudo iniciar playit: {e}", "err")
                if IS_WINDOWS and getattr(e, "winerror", None) == 225:
                    self.agent_error = ("El antivirus bloqueó el programa de playit.gg. Permítelo en "
                                        "Seguridad de Windows → Protección contra virus → Historial de protección.")
                time.sleep(30)
                continue
            attach_to_job(proc)
            with self.lock:
                if gen != self.gen:
                    proc.kill()
                    return
                self.proc = proc
            try:
                with open(self.pid_file, "w") as f:
                    f.write(str(proc.pid))
            except OSError:
                pass
            started = time.time()
            last_err = None
            for line in proc.stdout:
                line = ANSI_RE.sub("", line.rstrip())
                self.console.add(line, "err" if " ERROR " in line else "out")
                if "playit connected" in line:
                    self.connected = True
                    self.agent_error = None
                m = re.search(r"playitd error: (?:Setup error: )?(.+)$", line)
                if m:
                    last_err = m.group(1).strip()
            code = proc.wait()
            self.connected = False
            if code != 0 and last_err:
                self.agent_error = last_err
            if IS_WINDOWS and last_err and "Another instance is already running" in last_err:
                stale = windows_pids_for_exe(self.bin)
                for pid in stale:
                    windows_kill(pid)
                if stale:
                    self.console.add("Cerré una copia anterior de playit que había quedado abierta.", "app")
                    self.agent_error = None
                    started = 0      # reintentar enseguida
            try:
                os.remove(self.pid_file)
            except OSError:
                pass
            with self.lock:
                if self.proc is proc:
                    self.proc = None
            if gen != self.gen:
                return
            self.console.add(f"playit se cerró (código {code}); se reinicia solo.", "err")
            backoff = 5 if time.time() - started > 120 else min(backoff * 2, 60)
            time.sleep(backoff)

    def _poll_loop(self, gen):
        while gen == self.gen:
            delay = 20 if self.address() else 5
            try:
                self.refresh()
            except PlayitError as e:
                if e.kind == "error" and isinstance(e.data, dict) and e.data.get("type") == "auth":
                    self.phase = "error"
                    self.error = "La vinculación con playit.gg ya no es válida. Desvincula y vuelve a vincular."
                    delay = 60
                else:
                    self.message = "playit.gg respondió con un error; reintentando…"
            except (urllib.error.URLError, OSError):
                self.message = "Sin conexión con playit.gg; reintentando…"
            except Exception as e:
                traceback.print_exc()
                self.message = f"Error revisando playit: {e}"
            time.sleep(delay)

    def refresh(self):
        data = self.call("/v1/agents/rundata", {})
        self.agent_id = data.get("agent_id")
        perms = data.get("permissions") or {}
        self.account_status = perms.get("account_status")
        tunnels = []
        for t in data.get("tunnels") or []:
            fields = {f.get("name"): f.get("value") for f in (t.get("agent_config") or {}).get("fields", [])}
            try:
                lp = int(fields.get("local_port") or 0) or None
            except ValueError:
                lp = None
            tunnels.append({"id": t.get("id"), "name": t.get("name"), "address": t.get("display_address"),
                            "type": t.get("tunnel_type"), "type_label": t.get("tunnel_type_display"),
                            "local_port": lp, "local_ip": fields.get("local_ip") or "127.0.0.1",
                            "disabled": t.get("disabled_reason")})
        self.tunnels = tunnels
        self.pending = [{"name": p.get("name"), "status": p.get("status_msg")} for p in data.get("pending") or []]
        self.notices = [{"priority": n.get("priority"), "message": n.get("message"), "link": n.get("resolve_link")}
                        for n in data.get("notices") or []]
        mc = [t for t in tunnels if t["type"] == "minecraft-java"]
        if not mc and self.mode == "assignable" and not self.pending:
            self.tunnel_error = (f"Crea la dirección en playit.gg: Tunnels → Add Tunnel → Minecraft Java, "
                                 f"elige este equipo y el puerto local {self.target_port}. Aparecerá aquí sola.")
        elif not mc and not self.pending and time.time() - self.last_create_attempt > 300:
            self.create_tunnel()
        elif mc and mc[0]["local_port"] and mc[0]["local_port"] != self.target_port:
            self.retarget(mc[0])
        if self.address():
            self.phase = "listo"
            self.message = None
            self.error = None
            self.tunnel_error = None
        elif self.phase != "error":
            self.phase = "conectando"
            self.message = (self.pending[0]["status"] if self.pending else None) or \
                ("Creando tu dirección en playit.gg…" if not self.tunnel_error else None)

    def create_tunnel(self):
        self.last_create_attempt = time.time()
        body = {
            "ports": {"type": "tunnel-type", "details": "minecraft-java"},
            "origin": {"type": "agent", "data": {"agent_id": self.agent_id, "config": {"fields": [
                {"name": "local_ip", "value": "127.0.0.1"},
                {"name": "local_port", "value": str(self.target_port)}]}}},
            "enabled": True, "alloc": None, "name": "servidor-home", "firewall_id": None,
        }
        try:
            self.call("/v1/tunnels/create", body)
            self.tunnel_error = None
            self.console.add("Túnel de Minecraft creado en playit.gg.", "app")
        except PlayitError as e:
            code = e.data if isinstance(e.data, str) else json.dumps(e.data, ensure_ascii=False)
            self.tunnel_error = PLAYIT_ERRORS.get(code) or (
                f"No se pudo crear la dirección automáticamente ({code}). Créala a mano en playit.gg: "
                f"Tunnels → Add Tunnel → Minecraft Java, con puerto local {self.target_port}.")
            self.console.add(self.tunnel_error, "err")

    def retarget(self, tunnel):
        try:
            self.call("/v1/tunnels/config", {"tunnel_id": tunnel["id"], "new_agent_id": None, "new_config": {"fields": [
                {"name": "local_ip", "value": tunnel.get("local_ip") or "127.0.0.1"},
                {"name": "local_port", "value": str(self.target_port)}]}})
            self.console.add(f"Dirección de playit apuntada al puerto {self.target_port}.", "app")
        except PlayitError as e:
            self.console.add(f"No se pudo cambiar el puerto del túnel: {e.data}", "err")

    def set_target_port(self, port):
        self.target_port = int(port)

    def retry(self):
        self.tunnel_error = None
        self.last_create_attempt = 0
        if self.secret():
            self.start()
        else:
            self.cancel_setup()

    def stop(self):
        with self.lock:
            self.gen += 1
            proc = self.proc
            self.proc = None
        if proc and proc.poll() is None:
            try:
                if IS_WINDOWS:
                    proc.terminate()          # Windows no tiene Ctrl+C para procesos sin consola
                else:
                    proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def unlink(self):
        self.stop()
        for f in (self.secret_file, os.path.join(self.dir, "modo.txt")):
            try:
                os.remove(f)
            except OSError:
                pass
        self.phase = "desvinculado"
        self.tunnels, self.pending, self.notices = [], [], []
        self.agent_id = None
        self.connected = False
        self.error = self.message = self.tunnel_error = self.agent_error = None
        self.console.add("Desvinculado de playit.gg.", "app")


# --------------------------------------------------------------------------- #
# Administración remota: alguien de otra ciudad modera UN servidor desde SU Servidor Home
# --------------------------------------------------------------------------- #
# El dueño crea una invitación para un servidor y le pasa un código a su amigo, que lo pega en «Servidores de amigos»
# de su propia app. Ninguno de los dos PC recibe conexiones de afuera (sin playit, sin abrir puertos ni tocar el
# router): las dos apps se conectan hacia afuera a un buzón público de mensajes (MQTT, sin cuentas) y se dejan ahí
# pedidos y respuestas. El código trae una clave de 256 bits que solo conocen las dos apps: de ella sale el nombre
# del buzón (el buzón no sabe de quién es) y con ella cada mensaje va cifrado y firmado (HMAC-SHA256 como cifrado en
# modo contador y como firma, solo con la biblioteca estándar). El buzón solo ve paquetes ilegibles; nadie puede
# leer, repetir, cambiar ni inventar pedidos. Si un buzón no responde, se usa el siguiente de REMOTE_BROKERS.
# Solo hay rutas sobre el servidor de la invitación: nada de mods, argumentos de Java, versiones ni borrar, porque
# eso permitiría ejecutar programas en el PC del dueño.

REMOTE_FILE = os.path.join(APPDATA_DIR, "acceso-remoto.json")
FRIENDS_FILE = os.path.join(APPDATA_DIR, "servidores-de-amigos.json")
# Buzones MQTT públicos y gratuitos (servidor, puerto, TLS). El dueño escucha en todos; el amigo usa el primero que
# conecte. Ninguno necesita cuenta.
REMOTE_BROKERS = [("broker.emqx.io", 8883, True), ("broker.hivemq.com", 8883, True), ("test.mosquitto.org", 8886, True)]
REMOTE_TOPIC = "servidorhome/v1/"
REMOTE_CLOCK_SKEW = 120            # segundos; si los relojes no calzan, la app del amigo se corrige sola
REMOTE_TIMEOUT = 25                # segundos esperando la respuesta del PC del dueño
REMOTE_PROPERTIES = [k for k in EDITABLE_PROPERTIES if k != "server-port"]
REMOTE_ID_RE = re.compile(r"^[0-9a-f]{12}$")
REMOTE_MAX_INVITES = 20
REMOTE_CODE_PREFIX = "SH2."
REMOTE_CONSOLE_LINES = 400         # un mensaje no debe ser enorme


def _remote_keys(key_hex):
    k = bytes.fromhex(key_hex)
    return hmac.new(k, b"cifrar", hashlib.sha256).digest(), hmac.new(k, b"firmar", hashlib.sha256).digest()


def remote_room(key_hex):
    """El buzón de una invitación: sale de la clave, así que solo lo conocen las dos apps."""
    return REMOTE_TOPIC + hmac.new(bytes.fromhex(key_hex), b"sala", hashlib.sha256).hexdigest()[:32]


def _remote_xor(key, nonce, data):
    """Cifrado en flujo: bloques HMAC-SHA256(clave, número al azar + contador) mezclados con XOR."""
    if not data:
        return b""
    blocks = (len(data) + 31) // 32
    stream = b"".join(hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest() for i in range(blocks))
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream[:len(data)], "big")).to_bytes(len(data), "big")


def remote_seal(key_hex, kind, iid, obj, bind=b"", ts=None):
    """Cifra y firma obj. kind es b"pedido" o b"respuesta"; bind ata una respuesta a su pedido."""
    enc, mac = _remote_keys(key_hex)
    ts = int(time.time()) if ts is None else int(ts)
    nonce = secrets.token_bytes(16)
    ct = _remote_xor(enc, kind + nonce, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    tag = hmac.new(mac, b"|".join([kind, iid.encode(), str(ts).encode(), nonce, bind, ct]), hashlib.sha256).hexdigest()
    return {"id": iid, "ts": ts, "nonce": nonce.hex(), "ct": base64.b64encode(ct).decode(), "mac": tag}


def remote_open(key_hex, kind, env, bind=b""):
    """Comprueba la firma y descifra. PermissionError si algo no calza."""
    try:
        iid, ts, nonce = str(env["id"]), int(env["ts"]), bytes.fromhex(env["nonce"])
        ct = base64.b64decode(env["ct"], validate=True)
        tag = str(env["mac"])
    except (KeyError, TypeError, ValueError):
        raise PermissionError("Mensaje no válido.")
    if len(nonce) != 16:
        raise PermissionError("Mensaje no válido.")
    enc, mac = _remote_keys(key_hex)
    want = hmac.new(mac, b"|".join([kind, iid.encode(), str(ts).encode(), nonce, bind, ct]), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, tag):
        raise PermissionError("Firma no válida. Pídele un código nuevo al dueño del servidor.")
    return json.loads(_remote_xor(enc, kind + nonce, ct).decode("utf-8")), ts, nonce


def remote_code(inv):
    raw = f"{inv['id']}|{inv['key']}".encode()
    return REMOTE_CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_remote_code(code):
    code = re.sub(r"\s+", "", str(code or ""))
    if not code.startswith(REMOTE_CODE_PREFIX):
        raise ValueError("Ese no es un código de acceso de Servidor Home (empieza con «SH2.»).")
    body = code[len(REMOTE_CODE_PREFIX):]
    try:
        iid, key = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode().split("|")
        bytes.fromhex(key)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("El código está incompleto. Cópialo entero de nuevo.")
    if not REMOTE_ID_RE.match(iid) or len(key) != 64:
        raise ValueError("El código está incompleto. Cópialo entero de nuevo.")
    return iid, key


# ---- cliente MQTT 3.1.1 mínimo (solo QoS 0), con la biblioteca estándar ----

def _mqtt_str(s):
    b = s.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


def _mqtt_packet(first, body):
    n, size = len(body), bytearray()
    while True:
        n, digit = n >> 7, n & 0x7F
        size.append(digit | (0x80 if n else 0))
        if not n:
            break
    return bytes([first]) + bytes(size) + body


class MqttClient:
    """Una conexión hacia afuera con un buzón MQTT. Se reconecta sola y vuelve a suscribirse a sus temas."""

    def __init__(self, host, port, tls, on_message, keepalive=30):
        self.host, self.port, self.tls, self.on_message, self.keepalive = host, port, tls, on_message, keepalive
        self.topics = set()
        self.sock = None
        self.lock = threading.Lock()          # para escribir en el socket
        self.connected = threading.Event()
        self.closed = False
        self.error = None
        self.pid = 0
        self.acks = {}
        threading.Thread(target=self._loop, daemon=True, name=f"mqtt-{host}").start()

    @property
    def name(self):
        return f"{self.host}:{self.port}"

    def _send(self, data):
        with self.lock:
            if not self.sock:
                raise ConnectionError("sin conexión")
            self.sock.sendall(data)

    def _recv_exact(self, sock, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except socket.timeout:
                if time.time() - self.last_rx > self.keepalive * 2:
                    raise ConnectionError("el buzón dejó de responder")
                if not buf:
                    raise
                continue
            if not chunk:
                raise ConnectionError("el buzón cerró la conexión")
            buf += chunk
        self.last_rx = time.time()
        return buf

    def _read_packet(self, sock):
        first = self._recv_exact(sock, 1)[0]
        n, shift = 0, 0
        while True:
            b = self._recv_exact(sock, 1)[0]
            n |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
            if shift > 21:
                raise ConnectionError("paquete MQTT no válido")
        return first, self._recv_exact(sock, n) if n else b""

    def _next_pid(self):
        self.pid = self.pid % 65535 + 1
        return self.pid

    def _subscribe_packet(self, topic):
        pid = self._next_pid()
        ev = threading.Event()
        self.acks[pid] = ev
        return pid, ev, _mqtt_packet(0x82, pid.to_bytes(2, "big") + _mqtt_str(topic) + b"\x00")

    def _connect(self):
        sock = socket.create_connection((self.host, self.port), timeout=10)
        if self.tls:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        self.last_rx = time.time()
        body = _mqtt_str("MQTT") + bytes([4, 0x02]) + self.keepalive.to_bytes(2, "big") + _mqtt_str("sh-" + secrets.token_hex(8))
        sock.sendall(_mqtt_packet(0x10, body))
        first, data = self._read_packet(sock)
        if first >> 4 != 2 or len(data) < 2 or data[1] != 0:
            sock.close()
            raise ConnectionError("el buzón rechazó la conexión")
        sock.settimeout(self.keepalive / 2)
        return sock

    def _loop(self):
        backoff = 2
        while not self.closed:
            try:
                sock = self._connect()
            except (OSError, ValueError, ssl.SSLError) as e:
                self.error = str(e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 15)
                continue
            with self.lock:
                self.sock = sock
            backoff, self.error = 2, None
            try:
                for t in list(self.topics):
                    self._send(self._subscribe_packet(t)[2])
                self.connected.set()
                while not self.closed:
                    try:
                        first, data = self._read_packet(sock)
                    except socket.timeout:
                        self._send(b"\xc0\x00")          # PINGREQ: seguimos aquí
                        continue
                    kind = first >> 4
                    if kind == 3:                         # PUBLISH
                        tl = int.from_bytes(data[:2], "big")
                        topic = data[2:2 + tl].decode("utf-8", "replace")
                        start = 2 + tl + (2 if (first >> 1) & 3 else 0)
                        try:
                            self.on_message(self, topic, data[start:])
                        except Exception:
                            traceback.print_exc()
                    elif kind == 9 and len(data) >= 2:     # SUBACK
                        ev = self.acks.pop(int.from_bytes(data[:2], "big"), None)
                        if ev:
                            ev.set()
            except (OSError, ValueError, ssl.SSLError) as e:
                self.error = str(e)
            finally:
                self.connected.clear()
                with self.lock:
                    self.sock = None
                try:
                    sock.close()
                except OSError:
                    pass
            if not self.closed:
                time.sleep(1)

    def subscribe(self, topic, wait=0):
        self.topics.add(topic)
        if self.connected.is_set():
            _pid, ev, pkt = self._subscribe_packet(topic)
            try:
                self._send(pkt)
            except OSError:
                return False
            return ev.wait(wait) if wait else True
        return False

    def unsubscribe(self, topic):
        self.topics.discard(topic)
        if self.connected.is_set():
            try:
                self._send(_mqtt_packet(0xA2, self._next_pid().to_bytes(2, "big") + _mqtt_str(topic)))
            except OSError:
                pass

    def publish(self, topic, payload):
        self._send(_mqtt_packet(0x30, _mqtt_str(topic) + payload))

    def close(self):
        self.closed = True
        with self.lock:
            sock, self.sock = self.sock, None
        if sock:
            try:
                sock.sendall(b"\xe0\x00")                 # DISCONNECT
                sock.close()
            except OSError:
                pass


class RemoteAccess:
    """Lado del dueño: las invitaciones y los buzones donde escucha los pedidos de las apps de sus amigos."""

    def __init__(self):
        self.lock = threading.Lock()
        self.invites = [i for i in _read_json_list(REMOTE_FILE)
                        if isinstance(i, dict) and REMOTE_ID_RE.match(str(i.get("id"))) and len(str(i.get("key"))) == 64]
        self.nonces = {}              # mensajes ya recibidos → cuándo vencen (contra pedidos repetidos)
        self.clients = []

    # ---- invitaciones ----
    def _save(self):
        os.makedirs(os.path.dirname(REMOTE_FILE), exist_ok=True)
        _write_json_list(REMOTE_FILE, self.invites)
        if not IS_WINDOWS:
            try:
                os.chmod(REMOTE_FILE, 0o600)
            except OSError:
                pass

    def wanted(self):
        return bool(self.invites)

    def create(self, sid, name):
        name = re.sub(r"[\x00-\x1f\x7f]", " ", str(name or "")).strip()[:40]
        if not name:
            raise ValueError("Escribe el nombre de la persona que va a administrar el servidor.")
        with self.lock:
            if len(self.invites) >= REMOTE_MAX_INVITES:
                raise RuntimeError("Hay demasiados accesos remotos. Quita alguno que ya no se use.")
            inv = {"id": secrets.token_hex(6), "key": secrets.token_hex(32), "server": sid, "name": name,
                   "created": int(time.time()), "used": 0}
            self.invites.append(inv)
            self._save()
        self.start()
        for c in self.clients:
            c.subscribe(remote_room(inv["key"]) + "/p")
        return inv

    def _forget(self, gone):
        for inv in gone:
            for c in self.clients:
                c.unsubscribe(remote_room(inv["key"]) + "/p")
        if not self.invites:
            self.stop()

    def revoke(self, sid, iid):
        with self.lock:
            gone = [i for i in self.invites if i["id"] == iid and i["server"] == sid]
            if not gone:
                raise KeyError(iid)
            self.invites = [i for i in self.invites if i not in gone]
            self._save()
        self._forget(gone)

    def revoke_server(self, sid):
        with self.lock:
            gone = [i for i in self.invites if i["server"] == sid]
            if gone:
                self.invites = [i for i in self.invites if i["server"] != sid]
                self._save()
        self._forget(gone)

    def state(self, sid):
        on = [c for c in self.clients if c.connected.is_set()]
        return {
            "invites": [{"id": i["id"], "name": i["name"], "created": i["created"], "used": i.get("used", 0),
                         "code": remote_code(i)} for i in self.invites if i["server"] == sid],
            "listening": bool(self.clients), "connected": len(on), "brokers": len(self.clients),
            "error": None if on or not self.clients else
            ("No pude conectarme con ningún buzón de mensajes (" + "; ".join(c.error or "conectando" for c in self.clients)
             + "). Revisa la conexión a internet de este PC."),
        }

    # ---- mensajes ----
    def open_request(self, inv, env):
        """Devuelve (pedido, número del pedido) o PermissionError."""
        if str(env.get("id")) != inv["id"]:
            raise PermissionError("Mensaje no válido.")
        req, ts, nonce = remote_open(inv["key"], b"pedido", env)
        now = time.time()
        if abs(now - ts) > REMOTE_CLOCK_SKEW:
            raise PermissionError("hora")
        with self.lock:
            for k in [k for k, exp in self.nonces.items() if exp < now]:
                del self.nonces[k]
            if nonce in self.nonces:
                raise PermissionError("Pedido repetido.")
            self.nonces[nonce] = now + 2 * REMOTE_CLOCK_SKEW
            if now - inv.get("used", 0) > 60:
                inv["used"] = int(now)
                try:
                    self._save()
                except OSError:
                    pass
        if not isinstance(req, dict):
            raise PermissionError("Mensaje no válido.")
        return req, nonce

    def _on_message(self, client, topic, payload):
        inv = next((i for i in self.invites if remote_room(i["key"]) + "/p" == topic), None)
        if inv:
            threading.Thread(target=self._handle, args=(client, inv, payload), daemon=True).start()

    def _handle(self, client, inv, payload):
        reply_to = remote_room(inv["key"]) + "/r"
        re_ = ""
        try:
            env = json.loads(payload.decode("utf-8"))
            if not isinstance(env, dict):
                return
            re_ = str(env.get("nonce") or "")[:32]
            req, nonce = self.open_request(inv, env)
        except PermissionError as e:
            try:
                client.publish(reply_to, json.dumps({"re": re_, "error": str(e), "auth": True,
                                                     "t": int(time.time())}).encode())
            except OSError:
                pass
            return
        except (ValueError, UnicodeDecodeError):
            return
        try:
            code, data = remote_action(inv, str(req.get("method") or "GET"), str(req.get("path") or ""),
                                       req.get("body") if isinstance(req.get("body"), dict) else {})
        except KeyError:
            code, data = 404, {"error": "No encontrado."}
        except (ValueError, RuntimeError, PermissionError) as e:
            code, data = 400, {"error": str(e)}
        except Exception as e:
            traceback.print_exc()
            code, data = 500, {"error": f"Error interno: {e}"}
        out = remote_seal(inv["key"], b"respuesta", inv["id"], {"status": code, "data": data}, bind=nonce)
        out["re"] = nonce.hex()
        try:
            client.publish(reply_to, json.dumps(out).encode())
        except OSError:
            pass

    # ---- buzones ----
    def start(self):
        with self.lock:
            if self.clients:
                return
            self.clients = [MqttClient(h, p, tls, self._on_message) for h, p, tls in REMOTE_BROKERS]
            for c in self.clients:
                for inv in self.invites:
                    c.topics.add(remote_room(inv["key"]) + "/p")

    def stop(self):
        with self.lock:
            clients, self.clients = self.clients, []
        for c in clients:
            c.close()


def remote_action(inv, method, path, data):
    """Lo único que se puede hacer desde afuera, siempre sobre el servidor de la invitación. Devuelve (código, datos)."""
    s = manager.servers.get(inv["server"])
    if not s:
        return 404, {"error": "Ese servidor ya no existe en el PC de tu amigo."}
    u = urllib.parse.urlparse(path)
    p = u.path.strip("/")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    who = inv["name"]

    if method == "GET" and p == "estado":
        d = s.summary()
        keep = ("name", "type_label", "mc_version", "loader_version", "status", "error", "hint", "players",
                "max_players", "online_mode", "whitelist", "uptime", "mods_active", "addons_dir", "installed", "progress")
        out = {k: d.get(k) for k in keep}
        out["admin"] = who
        out["address"] = manager.playit.address() if manager.playit else None
        return 200, out
    if method == "POST" and p in ("encender", "apagar", "reiniciar", "forzar"):
        if p == "encender":
            s.log(f"{who} enciende el servidor (acceso remoto).")
            s.start(user=True)
        elif p == "apagar":
            s.log(f"{who} apaga el servidor (acceso remoto).")
            s.stop()
        elif p == "reiniciar":
            s.log(f"{who} reinicia el servidor (acceso remoto).")
            s.stop(restart=True)
        else:
            s.log(f"{who} fuerza el cierre del servidor (acceso remoto).", "err")
            s.kill()
        return 200, {"ok": True, "status": s.status}
    if method == "GET" and p == "consola":
        last, lines = s.console.since(int(q.get("since", 0)))
        lines = lines[-REMOTE_CONSOLE_LINES:]
        return 200, {"last": last, "lines": lines, "status": s.status, "players": sorted(s.players)}
    if method == "POST" and p == "comando":
        cmd = re.sub(r"[\x00-\x1f\x7f]", " ", str(data.get("command") or "")).strip()[:300]
        if not cmd:
            raise ValueError("Escribe un comando.")
        s.console.add(f"({who} desde el acceso remoto)", "app")
        s.send(cmd)
        return 200, {"ok": True}
    if p == "jugadores":
        if method == "GET":
            return 200, s.players_info()
        if method == "POST":
            s.log(f"{who}: {data.get('action')} {data.get('name')} (acceso remoto).")
            return 200, s.player_action(data.get("action"), data.get("name"), data.get("reason", ""))
    if p == "propiedades":
        path = os.path.join(s.dir, "server.properties")
        if method == "GET":
            props = read_properties(path)
            out = {k: props.get(k, "") for k in REMOTE_PROPERTIES}
            out["motd"] = prop_unescape(out["motd"])
            return 200, out
        if method == "PUT":
            clean = {}
            for k, v in (data.get("properties") or {}).items():
                if k not in REMOTE_PROPERTIES:
                    raise ValueError(f"Ese ajuste solo lo puede cambiar el dueño: {k}")
                clean[k] = clean_prop_value(v)
            if "motd" in clean:
                clean["motd"] = prop_escape(clean["motd"])
            write_properties(path, clean)
            s.log(f"{who} cambió los ajustes ({', '.join(clean) or 'ninguno'}) desde el acceso remoto. "
                  "Se aplican la próxima vez que se encienda.")
            return 200, {"ok": True}
    if p == "respaldos":
        if method == "GET":
            return 200, s.list_backups()
        if method == "POST":
            name = s.backup()
            s.log(f"Respaldo pedido por {who} (acceso remoto).")
            return 200, {"name": name}
    raise KeyError()


class RemoteFriends:
    """Lado del amigo: los servidores de otras personas que puede administrar con un código."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = [f for f in _read_json_list(FRIENDS_FILE)
                      if isinstance(f, dict) and f.get("fid") and REMOTE_ID_RE.match(str(f.get("id"))) and f.get("key")]
        self.offsets = {}             # diferencia de reloj con el PC de cada amigo
        self.clients = {}             # buzón (índice en REMOTE_BROKERS) → MqttClient, abiertos cuando se usan
        self.best = 0                 # el último buzón que funcionó
        self.waiting = {}             # número de pedido → [Event, respuesta]

    def _save(self):
        os.makedirs(os.path.dirname(FRIENDS_FILE), exist_ok=True)
        _write_json_list(FRIENDS_FILE, self.items)
        if not IS_WINDOWS:
            try:
                os.chmod(FRIENDS_FILE, 0o600)
            except OSError:
                pass

    def list(self):
        return [{"id": f["fid"], "name": f.get("name") or "?", "admin": f.get("admin"), "added": f.get("added")}
                for f in self.items]

    def get(self, fid):
        f = next((f for f in self.items if f["fid"] == fid), None)
        if not f:
            raise KeyError(fid)
        return f

    def add(self, code):
        iid, key = parse_remote_code(code)
        entry = {"fid": secrets.token_hex(4), "id": iid, "key": key, "added": int(time.time())}
        status, d = self._call(entry, "GET", "estado")
        if status != 200:
            raise RuntimeError(d.get("error") or "El PC de tu amigo no aceptó el código.")
        entry["name"], entry["admin"] = d.get("name"), d.get("admin")
        with self.lock:
            old = next((f for f in self.items if f["id"] == iid), None)
            if old:
                entry["fid"] = old["fid"]
                self.items.remove(old)
            self.items.append(entry)
            self._save()
        return {"id": entry["fid"], "name": entry["name"]}

    def remove(self, fid):
        with self.lock:
            f = self.get(fid)
            self.items.remove(f)
            self._save()
        for c in self.clients.values():
            c.unsubscribe(remote_room(f["key"]) + "/r")

    def request(self, fid, method, path, body=None):
        f = self.get(fid)
        status, data = self._call(f, method, path, body)
        if status == 200 and path == "estado" and data.get("name") and data.get("name") != f.get("name"):
            f["name"] = data["name"]
            try:
                self._save()
            except OSError:
                pass
        return status, data

    def _on_message(self, client, topic, payload):
        try:
            msg = json.loads(payload.decode("utf-8"))
            slot = self.waiting.get(str(msg.get("re")))
        except (ValueError, UnicodeDecodeError, AttributeError):
            return
        if slot and slot[1] is None:
            slot[1] = msg
            slot[0].set()

    def _client(self, idx):
        c = self.clients.get(idx)
        if not c:
            h, p, tls = REMOTE_BROKERS[idx]
            c = self.clients[idx] = MqttClient(h, p, tls, self._on_message)
        return c

    def _broker_for(self, room):
        """El primer buzón que conecte (empezando por el que funcionó la última vez), ya suscrito a las respuestas."""
        errors = []
        order = [(self.best + i) % len(REMOTE_BROKERS) for i in range(len(REMOTE_BROKERS))]
        for idx in order:
            c = self._client(idx)
            if not c.connected.wait(8 if not errors else 5):
                errors.append(c.error or "no responde")
                continue
            if room not in c.topics or not c.connected.is_set():
                if not c.subscribe(room, wait=5):
                    errors.append("no aceptó la suscripción")
                    continue
            self.best = idx
            return c
        raise RuntimeError("No pude conectarme con ningún buzón de mensajes (" + "; ".join(errors) +
                           "). Revisa tu conexión a internet.")

    def _call(self, f, method, path, body=None, retry=True):
        room = remote_room(f["key"])
        c = self._broker_for(room + "/r")
        env = remote_seal(f["key"], b"pedido", f["id"], {"method": method, "path": path, "body": body or {}},
                          ts=time.time() + self.offsets.get(f["id"], 0))
        slot = self.waiting[env["nonce"]] = [threading.Event(), None]
        try:
            try:
                c.publish(room + "/p", json.dumps(env).encode())
            except OSError:
                raise RuntimeError("Se cortó la conexión con el buzón de mensajes. Inténtalo de nuevo.")
            wait = 120 if path.startswith("respaldos") and method == "POST" else REMOTE_TIMEOUT
            if not slot[0].wait(wait):
                raise RuntimeError("El PC de tu amigo no responde. Revisa que esté encendido y con Servidor Home "
                                   "abierto.")
        finally:
            self.waiting.pop(env["nonce"], None)
        reply = slot[1]
        if reply.get("auth"):
            if reply.get("error") == "hora" and retry and isinstance(reply.get("t"), int):
                self.offsets[f["id"]] = reply["t"] - time.time()        # relojes distintos: corregimos y reintentamos
                return self._call(f, method, path, body, retry=False)
            return 401, {"error": reply.get("error") or "El PC de tu amigo rechazó el acceso.", "auth": True}
        try:
            inner, _ts, _n = remote_open(f["key"], b"respuesta", reply, bind=bytes.fromhex(env["nonce"]))
        except (PermissionError, ValueError, AttributeError, TypeError):
            raise RuntimeError("La respuesta del PC de tu amigo llegó alterada o no es válida.")
        return int(inner.get("status") or 500), inner.get("data")

    def stop(self):
        for c in list(self.clients.values()):
            c.close()
        self.clients = {}


# --------------------------------------------------------------------------- #
# Actualizaciones automáticas
# --------------------------------------------------------------------------- #
# Cada versión nueva se publica en GitHub (Releases) con tres archivos:
#   actualizacion.json          {"manifiesto": "<json>", "firma": "<base64>"}   (el manifiesto va firmado)
#   servidor-home-X.Y.Z.zip     los archivos de la app (servidor_home.py, web/, README.md)
#   Instalar-Servidor-Home.exe  el instalador, para quien instala por primera vez
# La app revisa cada algunas horas si hay una versión más nueva, comprueba la firma con la clave pública
# de abajo (solo quien tiene la clave privada puede publicar), descarga el paquete y comprueba su SHA-256,
# prueba que el código nuevo cargue y lo instala cuando no molesta: al abrir la app o cuando no hay
# servidores encendidos ni ventana abierta. Si la versión nueva no arranca, vuelve sola a la anterior.

UPDATE_REPO = "maxglich272/server-home"     # usuario/repositorio en GitHub donde se publican las versiones
UPDATE_MANIFEST_URL = (f"https://github.com/{UPDATE_REPO}/releases/latest/download/actualizacion.json"
                       if UPDATE_REPO else "")
# Clave pública RSA de 3072 bits (firma PKCS#1 v1.5 con SHA-256) del autor de Servidor Home.
UPDATE_KEY_N = int(
    "b95ab53aa64b2e079ad1fe41c3c5351a558e309219bd81d93a3e99982b5b5ba44f660ab7cedd9583"
    "bc966a81ae4f05e200db4c0f762ec31fb6490a6f307abe8786f2d6e2a0dd7b87672733f83fc25350"
    "786980443d49070d258aa9f1ebef2dbd6742221007c8d9f526909493c5c6df12e232826f090eb245"
    "abc2e7d9b1d6111eb887e7027b7252cc7186c764a5ddca259c60b596b6dd6ac0b419b7f1391c595f"
    "c000ede7c7280479f332cd2a9a270c3ddcee77c907a0d5b4ad306c5d0ca6865a8644d3de18ee7eff"
    "7b35f5b68352eaa05b99069230da7452d8d6701b2125dccad016db9c7977d1de6e7d394a8db775ee"
    "71f8df41d166e5e60ed6be98f4fa88f59be13011cb4278162dcbe97e8dd9d5277fc830e97b0c2e1b"
    "a433710a69f912593d8bf3474e486424521088030dee70f1ceb8c4d92515c5eaa8bc96fe20daa6fb"
    "7dac8590f7b7b3e5f1313e6e448ac6204b9f10f8594a9e247038ecc07a180ef89a5829d8607e4a3f"
    "e5c4ef2dc1a41deccada767027b7a1a59a25b680a3dc11e7", 16)
UPDATE_KEY_E = 65537
UPDATES_ENABLED = INSTALLED        # la versión portable (carpeta suelta) no se actualiza sola
UPDATE_FIRST_CHECK = 20            # segundos después de abrir la app
UPDATE_EVERY = 6 * 3600            # cada cuánto se revisa
UPDATE_RETRY = 30 * 60             # si no hubo internet
UPDATE_TICK = 60                   # cada cuánto se mira si ya se puede instalar
UPDATE_UI_IDLE = 120               # «sin ventana abierta»: la interfaz no pregunta nada hace 2 minutos
UPDATE_DIR = os.path.join(APPDATA_DIR, "actualizaciones")
UPDATE_ALLOWED = re.compile(r"^(?:servidor_home\.py|README\.md|web/[\w.\-]+\.(?:html|svg|ico|png|js|css|woff2?))$")
UPDATE_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ServidorHome"
LAST_UI_SEEN = 0.0                 # última vez que la interfaz preguntó el estado
UPDATER = None
UPDATE_PROBE = r"""
import sys, importlib.util
spec = importlib.util.spec_from_file_location("servidor_home_nuevo", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert callable(getattr(mod, "main", None)) and callable(getattr(mod, "Updater", None))
print("VERSION", mod.APP_VERSION)
"""


def ui_seen():
    global LAST_UI_SEEN
    LAST_UI_SEEN = time.time()


def rsa_verify(message, signature, n=None, e=None):
    """Firma RSA PKCS#1 v1.5 con SHA-256 (se compara el bloque completo, sin interpretarlo)."""
    n = n or UPDATE_KEY_N
    e = e or UPDATE_KEY_E
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - 3 - len(digest_info)) + b"\x00" + digest_info
    return hmac.compare_digest(em, expected)


class Updater:
    def __init__(self, manifest_url=None):
        self.url = UPDATE_MANIFEST_URL if manifest_url is None else manifest_url
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.status = "al día"
        self.error = None
        self.restart_pending = False
        self.state = self._load()
        lista = self.state.get("lista")
        if lista and version_key(lista.get("version", "0")) > version_key(APP_VERSION):
            self.status = "lista"

    # ---- estado guardado ----
    @property
    def state_path(self):
        return os.path.join(UPDATE_DIR, "estado.json")

    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            os.makedirs(UPDATE_DIR, exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.state_path)
        except OSError as e:
            print(f"No pude guardar el estado de las actualizaciones: {e}")

    @property
    def enabled(self):
        return bool(UPDATES_ENABLED and self.url)

    @property
    def auto(self):
        return self.state.get("auto", True)

    def set_auto(self, value):
        with self.lock:
            self.state["auto"] = bool(value)
            self._save()
        self.wake.set()

    def to_json(self):
        lista = self.state.get("lista") or {}
        return {"enabled": self.enabled, "status": self.status, "actual": APP_VERSION, "auto": self.auto,
                "version": lista.get("version") if self.status in ("lista", "actualizando") else None,
                "novedades": lista.get("novedades", []) if self.status in ("lista", "actualizando") else [],
                "instalada": self.state.get("instalada"), "fallo": self.state.get("fallo"), "error": self.error,
                "revisada": self.state.get("revisada"), "repo": UPDATE_REPO}

    def seen(self):
        with self.lock:
            self.state.pop("instalada", None)
            self.state.pop("fallo", None)
            self._save()

    # ---- buscar y descargar ----
    def start(self):
        if self.enabled:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        next_check = time.time() + UPDATE_FIRST_CHECK
        while True:
            if time.time() >= next_check:
                ok = False
                try:
                    ok = self.check()
                except Exception as e:           # nunca debe botar la app
                    self.status, self.error = "error", f"No pude revisar si hay versiones nuevas: {e}"
                next_check = time.time() + (UPDATE_EVERY if ok else UPDATE_RETRY)
            try:
                self.maybe_apply()
            except Exception as e:
                print(f"No se pudo instalar la actualización: {e}")
            self.wake.wait(max(0.2, min(UPDATE_TICK, next_check - time.time())))
            if self.wake.is_set():
                self.wake.clear()
                if getattr(self, "_check_now", False):
                    self._check_now = False
                    next_check = 0

    def check_soon(self):
        self._check_now = True
        self.wake.set()

    def fetch_manifest(self):
        outer = json.loads(http_get(self.url, timeout=20).decode("utf-8"))
        text, firma = outer.get("manifiesto"), outer.get("firma")
        if not isinstance(text, str) or not isinstance(firma, str):
            raise RuntimeError("el archivo de la versión nueva no tiene el formato esperado")
        if not rsa_verify(text.encode("utf-8"), base64.b64decode(firma)):
            raise RuntimeError("la firma de la versión nueva no es válida (no la publicó el autor de Servidor Home)")
        man = json.loads(text)
        if (man.get("app") != APP_NAME or not UPDATE_VERSION_RE.match(str(man.get("version", "")))
                or not re.match(r"^[0-9a-f]{64}$", str(man.get("sha256", ""))) or not man.get("paquete")):
            raise RuntimeError("el manifiesto de la versión nueva está incompleto")
        return man

    def check(self):
        """Revisa si hay versión nueva y, si la hay, la deja lista. Devuelve False si no se pudo revisar."""
        with self.lock:
            if self.status in ("descargando", "actualizando"):
                return True
            prev = self.status
            self.status, self.error = "buscando", None
        try:
            man = self.fetch_manifest()
        except urllib.error.HTTPError as e:
            with self.lock:
                if e.code == 404:           # todavía no hay versiones publicadas
                    self.status = prev if prev == "lista" else "al día"
                    self.state["revisada"] = int(time.time())
                    self._save()
                    return True
                self.status = prev if prev == "lista" else "error"
                self.error = f"No pude revisar si hay versiones nuevas (GitHub respondió {e.code}). Vuelvo a intentar más tarde."
            return False
        except (urllib.error.URLError, OSError) as e:
            with self.lock:
                self.status = prev if prev == "lista" else "error"
                self.error = "No pude revisar si hay versiones nuevas (¿sin internet?). Vuelvo a intentar más tarde."
            print(f"Actualizaciones: {e}")
            return False
        except Exception as e:
            with self.lock:
                self.status = prev if prev == "lista" else "error"
                self.error = f"No pude revisar si hay versiones nuevas: {e}"
            return False
        v = man["version"]
        with self.lock:
            self.state["revisada"] = int(time.time())
            lista = self.state.get("lista")
            if version_key(v) <= version_key(APP_VERSION) or v in self.state.get("fallidas", []):
                if lista and version_key(lista.get("version", "0")) <= version_key(APP_VERSION):
                    self._discard_staged()
                self.status = "lista" if self.state.get("lista") else "al día"
                self._save()
                return True
            if lista and lista.get("version") == v and os.path.isfile(os.path.join(lista.get("dir", ""), "servidor_home.py")):
                self.status = "lista"
                self._save()
                return True
            self.status = "descargando"
        try:
            dest = self.download(man)
        except Exception as e:
            with self.lock:
                self.status = "error"
                self.error = f"No pude descargar la versión {v}: {e}"
                if isinstance(e, UpdateBroken):
                    self.state.setdefault("fallidas", []).append(v)
                self._save()
            return True
        with self.lock:
            self._discard_staged(keep=dest)
            self.state["lista"] = {"version": v, "dir": dest, "novedades": [str(x) for x in man.get("novedades", [])][:12],
                                   "fecha": man.get("fecha")}
            self.status = "lista"
            self._save()
        print(f"Versión {v} de {APP_NAME} descargada; se instala cuando no moleste.")
        self.wake.set()
        return True

    def download(self, man):
        v = man["version"]
        os.makedirs(UPDATE_DIR, exist_ok=True)
        url = urllib.parse.urljoin(self.url, man["paquete"])
        zpath = os.path.join(UPDATE_DIR, f"paquete-{v}.zip")
        download(url, zpath, expected_sha256=man["sha256"])
        dest = os.path.join(UPDATE_DIR, v)
        shutil.rmtree(dest, ignore_errors=True)
        try:
            with zipfile.ZipFile(zpath) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename.replace("\\", "/")
                    if not UPDATE_ALLOWED.match(name):
                        raise UpdateBroken(f"el paquete trae un archivo no permitido ({name})")
                    target = os.path.join(dest, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
            if not os.path.isfile(os.path.join(dest, "servidor_home.py")):
                raise UpdateBroken("el paquete no trae el programa")
            self.probe(dest, v)
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        finally:
            try:
                os.remove(zpath)
            except OSError:
                pass
        return dest

    def probe(self, dest, v):
        """Carga el código nuevo en un proceso aparte: si tiene un error, no se instala."""
        try:
            r = subprocess.run([sys.executable, "-c", UPDATE_PROBE, os.path.join(dest, "servidor_home.py")], cwd=dest,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                               stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                               **child_kwargs())
        except subprocess.TimeoutExpired:
            raise UpdateBroken("el código nuevo no terminó de cargar")
        if r.returncode != 0 or f"VERSION {v}" not in r.stdout:
            last = (r.stderr.strip().splitlines() or ["sin detalle"])[-1]
            raise UpdateBroken(f"el código nuevo no carga ({last[:200]})")

    def _discard_staged(self, keep=None):
        lista = self.state.pop("lista", None)
        if lista and lista.get("dir") and lista.get("dir") != keep:
            shutil.rmtree(lista["dir"], ignore_errors=True)
        if self.status == "lista":
            self.status = "al día"

    # ---- instalar ----
    def staged(self):
        lista = self.state.get("lista")
        if (lista and version_key(lista.get("version", "0")) > version_key(APP_VERSION)
                and lista.get("version") not in self.state.get("fallidas", [])
                and os.path.isfile(os.path.join(lista.get("dir", ""), "servidor_home.py"))):
            return lista
        return None

    @staticmethod
    def busy_reason():
        """Por qué no conviene reiniciar la app ahora (o None si se puede)."""
        for s in (manager.servers.values() if manager else []):
            if s.running() or s.repair_busy or s.status in ("instalando", "iniciando", "reparando", "deteniendo"):
                return f"«{s.meta.get('name', s.id)}» está encendido o trabajando"
        for j in (manager.imports.values() if manager else []):
            if j.status == "analizando":
                return "se está importando un modpack"
        if manager and manager.playit and manager.playit.state().get("phase") == "vinculando":
            return "se está conectando playit.gg"
        return None

    def maybe_apply(self):
        """Instala sola la versión lista si no molesta: sin servidores trabajando y sin la ventana abierta."""
        if not (self.status == "lista" and self.auto and self.staged()):
            return False
        if time.time() - LAST_UI_SEEN < UPDATE_UI_IDLE or self.busy_reason():
            return False
        return self.apply()

    def apply_now(self):
        """Botón «Actualizar ahora»."""
        if not self.staged():
            raise RuntimeError("No hay una versión nueva lista para instalar.")
        why = self.busy_reason()
        if why:
            raise RuntimeError(f"No se puede actualizar ahora porque {why}. Apágalo y vuelve a intentarlo "
                               "(o se instala sola cuando no haya servidores encendidos).")
        if not self.apply():
            raise RuntimeError(self.error or "No se pudo instalar la versión nueva.")

    def apply(self):
        """Reemplaza los archivos de la app y la reinicia (main() lanza la versión nueva y la vigila)."""
        with self.lock:
            lista = self.staged()
            if not lista or self.status == "actualizando":
                return False
            self.status = "actualizando"
        v = lista["version"]
        try:
            self.install_files(lista["dir"])
        except Exception as e:
            self.rollback()
            with self.lock:
                self.status, self.error = "error", f"No se pudo instalar la versión {v}: {e}"
            return False
        with self.lock:
            self.state["instalando"] = {"version": v, "desde": APP_VERSION, "novedades": lista.get("novedades", []),
                                        "t": int(time.time())}
            self._save()
            self.restart_pending = True
        print(f"Instalando {APP_NAME} {v}: la app se reinicia.")
        threading.Thread(target=lambda: (time.sleep(1.5), quit_app()), daemon=True).start()
        return True

    def install_files(self, src_dir):
        backup = os.path.join(UPDATE_DIR, "anterior")
        shutil.rmtree(backup, ignore_errors=True)
        rels = []
        for root, _dirs, files in os.walk(src_dir):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), src_dir).replace("\\", "/")
                if UPDATE_ALLOWED.match(rel):
                    rels.append(rel)
        existed = []
        for rel in rels:
            cur = os.path.join(BASE_DIR, *rel.split("/"))
            if os.path.isfile(cur):
                dst = os.path.join(backup, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(cur, dst)
                existed.append(rel)
        with open(os.path.join(UPDATE_DIR, "anterior.json"), "w", encoding="utf-8") as f:
            json.dump({"version": APP_VERSION, "archivos": existed, "nuevos": [r for r in rels if r not in existed]}, f)
        for rel in rels:
            dst = os.path.join(BASE_DIR, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".nuevo"
            shutil.copyfile(os.path.join(src_dir, *rel.split("/")), tmp)
            os.replace(tmp, dst)

    def rollback(self):
        """Vuelve a dejar los archivos de la versión anterior."""
        backup = os.path.join(UPDATE_DIR, "anterior")
        try:
            with open(os.path.join(UPDATE_DIR, "anterior.json"), encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            return False
        for rel in info.get("archivos", []):
            src = os.path.join(backup, *rel.split("/"))
            dst = os.path.join(BASE_DIR, *rel.split("/"))
            try:
                tmp = dst + ".nuevo"
                shutil.copyfile(src, tmp)
                os.replace(tmp, dst)
            except OSError as e:
                print(f"No pude restaurar {rel}: {e}")
        for rel in info.get("nuevos", []):
            try:
                os.remove(os.path.join(BASE_DIR, *rel.split("/")))
            except OSError:
                pass
        return True

    @staticmethod
    def mark_installed_version(v):
        """Deja la versión nueva a la vista de Windows (Configuración → Aplicaciones)."""
        if not INSTALLED:
            return
        try:
            with open(os.path.join(BASE_DIR, "instalado.txt"), "w", encoding="utf-8") as f:
                f.write(f"{APP_NAME} {v} (instalado)\r\n")
        except OSError:
            pass
        if IS_WINDOWS:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, v)
            except OSError:
                pass

    # ---- reinicio con la versión nueva ----
    def launch_and_wait(self, port, expect, extra_args, timeout=90):
        """Abre la app (ya con los archivos nuevos) y espera a que responda con la versión esperada."""
        cmd = [sys.executable, os.path.abspath(sys.argv[0])] + list(extra_args)
        try:
            os.makedirs(APPDATA_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as log:        # lo que escriba queda en servidor-home.log
                proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                        **child_kwargs(detach=True))
        except OSError as e:
            print(f"No pude abrir la versión nueva: {e}")
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                info = json.loads(_local_opener().open(f"http://127.0.0.1:{port}/api/info", timeout=3).read().decode("utf-8"))
                if info.get("app") == APP_NAME and info.get("version") == expect:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        try:
            proc.kill()
        except OSError:
            pass
        return False

    def handoff(self, port, extra_args):
        """La app vieja ya soltó el puerto: abre la nueva y, si no arranca, vuelve a la anterior."""
        inst = self.state.get("instalando") or {}
        v = inst.get("version")
        if v and self.launch_and_wait(port, v, list(extra_args) + ["--tras-actualizar"]):
            return True
        print(f"La versión {v} no arrancó; vuelvo a la {APP_VERSION}.")
        self.rollback()
        with self.lock:
            self.state.setdefault("fallidas", []).append(v)
            self.state.pop("instalando", None)
            self._discard_staged()
            self.state["fallo"] = {"version": v, "volvio": APP_VERSION, "t": int(time.time())}
            self._save()
        return self.launch_and_wait(port, APP_VERSION, list(extra_args))

    def after_update(self):
        """La versión nueva arrancó bien: se anota y se avisa en la interfaz."""
        with self.lock:
            inst = self.state.pop("instalando", None)
            if inst and inst.get("version") == APP_VERSION:
                self.state["instalada"] = inst
                self.state.pop("fallo", None)          # un fallo anterior ya no importa
                self.mark_installed_version(APP_VERSION)
            lista = self.state.get("lista")
            if lista and version_key(lista.get("version", "0")) <= version_key(APP_VERSION):
                self._discard_staged()
            shutil.rmtree(os.path.join(UPDATE_DIR, "anterior"), ignore_errors=True)
            self._save()

    def apply_at_startup(self, port, extra_args):
        """Al abrir la app: si hay una versión lista, se instala antes de mostrar nada. Devuelve True si la
        versión nueva quedó funcionando (entonces esta app vieja termina aquí)."""
        if not (self.enabled and self.auto):
            return False
        lista = self.staged()
        if not lista:
            return False
        v = lista["version"]
        try:
            self.install_files(lista["dir"])
        except Exception as e:
            print(f"No se pudo instalar la versión {v}: {e}")
            self.rollback()
            return False
        with self.lock:
            self.state["instalando"] = {"version": v, "desde": APP_VERSION, "novedades": lista.get("novedades", []),
                                        "t": int(time.time())}
            self._save()
        if self.launch_and_wait(port, v, list(extra_args) + ["--tras-actualizar"]):
            return True
        print(f"La versión {v} no arrancó; sigo con la {APP_VERSION}.")
        self.rollback()
        with self.lock:
            self.state.setdefault("fallidas", []).append(v)
            self.state.pop("instalando", None)
            self._discard_staged()
            self.state["fallo"] = {"version": v, "volvio": APP_VERSION, "t": int(time.time())}
            self._save()
        return False


class UpdateBroken(RuntimeError):
    """El paquete de la versión nueva está mal: no se vuelve a intentar con esa versión."""


# --------------------------------------------------------------------------- #
# Administrador
# --------------------------------------------------------------------------- #

class Manager:
    def __init__(self):
        os.makedirs(SERVERS_DIR, exist_ok=True)
        self.servers = {}
        self.imports = {}
        self.lock = threading.Lock()
        shutil.rmtree(UPLOADS_DIR, ignore_errors=True)
        for d in sorted(os.listdir(SERVERS_DIR)):
            full = os.path.join(SERVERS_DIR, d)
            if not os.path.isdir(full) or d.startswith("."):
                continue
            if os.path.exists(os.path.join(full, META_FILE)):
                self.servers[d] = ServerInstance(d)
                self.servers[d].close_orphan()
            elif os.path.exists(os.path.join(full, STAGING_MARK)):
                shutil.rmtree(full, ignore_errors=True)   # importación que quedó a medias
        self.playit = None
        self.remote = None
        self.friends = None

    def get(self, sid):
        s = self.servers.get(sid)
        if not s:
            raise KeyError(sid)
        return s

    def _unique_id(self, name):
        base = slugify(name)
        sid, i = base, 2
        while sid in self.servers or os.path.exists(os.path.join(SERVERS_DIR, sid)):
            sid, i = f"{base}-{i}", i + 1
        return sid

    def create(self, data):
        t = data.get("type")
        if t not in SERVER_TYPES:
            raise ValueError("Tipo de servidor no válido.")
        mc = (data.get("mc_version") or "").strip()
        if not mc:
            raise ValueError("Elige una versión de Minecraft.")
        name = (data.get("name") or "").strip() or f"{SERVER_TYPES[t]['label']} {mc}"
        if not data.get("eula"):
            raise ValueError("Debes aceptar el EULA de Minecraft para crear un servidor.")
        check_version(t, mc, (data.get("loader_version") or "").strip() or None)
        with self.lock:
            sid = self._unique_id(name)
            os.makedirs(os.path.join(SERVERS_DIR, sid))
            s = ServerInstance(sid)
            s.meta = {
                "name": name, "type": t, "mc_version": mc,
                "loader_version": (data.get("loader_version") or "").strip() or None,
                "ram_mb": int(data.get("ram_mb") or 3072),
                "jvm_args": data.get("jvm_args", ""),
                "eula": True, "installed": False,
                "created": time.strftime("%Y-%m-%d %H:%M"),
            }
            s.save_meta()
            props = {"server-port": int(data.get("port") or DEFAULT_PORT)}
            for k in EDITABLE_PROPERTIES:
                if k in data.get("properties", {}):
                    props[k] = clean_prop_value(data["properties"][k])
            if "motd" in props:
                props["motd"] = prop_escape(props["motd"])
            write_properties(os.path.join(s.dir, "server.properties"), props)
            s.status = "sin instalar"
            self.servers[sid] = s
        s.install(autostart=bool(data.get("autostart")))
        return s

    # ---- importaciones ----
    def start_import(self, job):
        with self.lock:
            # limpiamos importaciones viejas que nadie confirmó
            for k, j in list(self.imports.items()):
                if j.status in ("listo", "error") and time.time() - j.created > 6 * 3600:
                    j._cleanup_stage()
                    del self.imports[k]
            self.imports[job.id] = job
        threading.Thread(target=job.run_analysis, daemon=True).start()
        return job

    def confirm_import(self, job, data):
        if job.status != "listo":
            raise RuntimeError("La importación no está lista.")
        a = job.analysis
        t = data.get("type") or a.get("type")
        mc = (data.get("mc_version") or a.get("mc_version") or "").strip()
        if t not in SERVER_TYPES:
            raise ValueError("Elige el tipo de servidor (loader).")
        if not mc:
            raise ValueError("Falta la versión de Minecraft.")
        if not data.get("eula"):
            raise ValueError("Debes aceptar el EULA de Minecraft.")
        lv = (data.get("loader_version") or "").strip() or None
        same_loader = t == a.get("type") and mc == a.get("mc_version")
        if not lv and same_loader:
            lv = a.get("loader_version")
        if not same_loader or lv != a.get("loader_version"):
            check_version(t, mc, lv)        # el usuario eligió otra versión: que exista
            same_loader = same_loader and lv == a.get("loader_version")
        name = (data.get("name") or a.get("name") or "Modpack").strip()[:60]
        with self.lock:
            if job.stage_dir:
                sid = os.path.basename(job.stage_dir)
            else:
                sid = self._unique_id(name)
                os.makedirs(os.path.join(SERVERS_DIR, sid))
                open(os.path.join(SERVERS_DIR, sid, STAGING_MARK), "w").close()
            s = ServerInstance(sid)
            s.meta = {
                "name": name, "type": t, "mc_version": mc, "loader_version": lv,
                "ram_mb": max(1024, int(data.get("ram_mb") or a.get("ram_mb") or 4096)),
                "jvm_args": "", "eula": True, "installed": False,
                "preinstalled": bool(a.get("installed")) and same_loader,
                "created": time.strftime("%Y-%m-%d %H:%M"),
                "modpack": {"source": job.original_name, "kind": a.get("pack_kind"), "mods": a.get("mods_count"),
                            **({"path": job.path} if job.source_kind == "carpeta" else {})},
                "pending_import": {
                    "copy_from": job.path if job.source_kind == "carpeta" else None,
                    "mrpack_files": job.mrpack["files"] if job.mrpack else None,
                    "disable": [os.path.basename(f) for f in data.get("disable", []) if isinstance(f, str)],
                    "client_reasons": {c.get("file"): c.get("reason") for c in a.get("client_only") or []
                                       if isinstance(c, dict) and c.get("file") and not c.get("skip")},
                },
            }
            s.save_meta()
            self.servers[sid] = s
            job.status = "hecho"
            job.server_id = sid
            job.message = "Importado."
        s.install(autostart=bool(data.get("autostart", True)))
        return s

    def cancel_import(self, job):
        job._cleanup_stage()
        with self.lock:
            self.imports.pop(job.id, None)

    def delete(self, sid):
        """Borra el servidor, su mundo y sus respaldos. Si está encendido, primero lo apaga guardando el mundo."""
        s = self.get(sid)
        if s.repair_busy or s.status in ("instalando", "reparando"):
            raise RuntimeError("Espera a que termine la instalación o el arreglo antes de borrarlo.")
        if s.running():
            proc = s.proc
            s.log("Apagando el servidor para borrarlo…")
            try:
                s.stop(timeout=60)
            except RuntimeError:
                pass
            try:
                proc.wait(timeout=75)
            except subprocess.TimeoutExpired:
                s.kill()
                proc.wait(timeout=15)
            for _ in range(40):              # que termine de leer la consola antes de borrar la carpeta
                if s.status not in ("deteniendo", "en línea", "iniciando"):
                    break
                time.sleep(0.25)
        with self.lock:
            self.servers.pop(sid, None)
        if self.remote:
            self.remote.revoke_server(sid)
        for attempt in range(3):
            shutil.rmtree(s.dir, ignore_errors=True)
            if not os.path.exists(s.dir):
                return
            time.sleep(1 + attempt)          # Windows suelta los archivos de Java un momento después
        raise RuntimeError(f"El servidor se quitó de la lista, pero algunos archivos siguen en uso y no se "
                           f"pudieron borrar. Puedes borrar la carpeta a mano: {s.dir}")

    def shutdown_all(self):
        running = [s for s in self.servers.values() if s.running()]
        for s in running:
            print(f"Apagando {s.meta.get('name')} (guardando el mundo)...")
            try:
                s.send("stop")
            except Exception:
                pass
        for s in running:
            try:
                s.proc.wait(timeout=90)
            except Exception:
                s.proc.kill()
        if self.remote:
            self.remote.stop()
        if self.friends:
            self.friends.stop()
        if self.playit:
            self.playit.stop()


manager = None
HTTPD = None
WINDOW = None      # ventana de la aplicación
TRAY = None        # ícono junto al reloj (Windows)


# --------------------------------------------------------------------------- #
# Ventana propia de la aplicación (sin barra de direcciones ni pestañas)
# --------------------------------------------------------------------------- #

APP_WINDOW_TITLE = APP_NAME        # debe ser igual al <title> de web/index.html


def find_app_browser():
    """Motor para la ventana: Edge (viene con Windows), Chrome o Brave, en modo aplicación."""
    cands = []
    if IS_WINDOWS:
        for env in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                cands += [os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(root, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
        try:
            import winreg
            for exe in ("msedge.exe", "chrome.exe"):
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        cands.append(winreg.QueryValue(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"))
                    except OSError:
                        pass
        except ImportError:
            pass
    else:
        for name in ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
                     "chromium", "chromium-browser", "brave-browser"):
            found = shutil.which(name)
            if found:
                cands.append(found)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _win_find_app_window(pid=None):
    """Busca la ventana de la app: por su título exacto («Servidor Home», clase de Chromium) o, si se
    indica pid, la ventana principal de ese proceso del navegador (por si el título llega distinto)."""
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                if cls.value.startswith("Chrome_WidgetWin"):
                    title = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, title, 256)
                    if pid is None:
                        match = title.value == APP_WINDOW_TITLE
                    else:
                        owner = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                        match = owner.value == pid and bool(title.value)
                    if match:
                        found.append(hwnd)
                        return False
            return True
        user32.EnumWindows(proto(cb), 0)
        return found[0] if found else None
    except Exception:
        return None


def _win_post_close(hwnd):
    """Pide a una ventana que se cierre como si el usuario tocara la X (el navegador termina ordenado)."""
    try:
        import ctypes
        from ctypes import wintypes
        post = ctypes.windll.user32.PostMessageW
        post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        return bool(post(hwnd, 0x10, 0, 0))            # WM_CLOSE
    except Exception:
        return False


def _win_focus(hwnd):
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def focus_existing_window():
    """Si la ventana de la app ya está abierta, la trae al frente (lo usa la segunda apertura)."""
    hwnd = _win_find_app_window()
    return bool(hwnd) and _win_focus(hwnd)


def allow_other_to_focus():
    """Windows: deja que la app que ya estaba abierta ponga su ventana al frente."""
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)      # ASFW_ANY
        except Exception:
            pass


class AppWindow:
    """La interfaz en una ventana propia, como un programa: sin pestañas, sin barra de direcciones."""

    def __init__(self, url, on_closed):
        self.url = url
        self.on_closed = on_closed
        self.browser = find_app_browser()
        self.proc = None
        self.lock = threading.Lock()
        self.last_launch = 0
        self.title_ok = False       # ya vimos la ventana por su título (entonces no hace falta buscarla por proceso)
        self.tagged = set()         # ventanas a las que ya les pusimos la identidad de Servidor Home

    @property
    def available(self):
        return bool(self.browser)

    def _find(self, proc=None):
        """La ventana abierta de la app (Windows) o None."""
        hwnd = _win_find_app_window()
        if hwnd:
            self.title_ok = True
        elif not self.title_ok and proc is not None and proc.poll() is None:
            hwnd = _win_find_app_window(pid=proc.pid)
        if hwnd and hwnd not in self.tagged:
            self.tagged.add(hwnd)
            win_app_identity(hwnd)          # que se ancle y se agrupe como «Servidor Home», no como Edge
        return hwnd

    def open(self):
        with self.lock:
            hwnd = self._find(self.proc)
            if hwnd and _win_focus(hwnd):
                return
            if self.proc and self.proc.poll() is None and time.time() - self.last_launch < 8:
                return          # se está abriendo (doble clic en el ícono)
            if not self.browser:
                open_browser_later(self.url, delay=0)
                return
            os.makedirs(WINDOW_PROFILE, exist_ok=True)
            cmd = [self.browser, f"--app={self.url}", f"--user-data-dir={WINDOW_PROFILE}",
                   "--no-first-run", "--no-default-browser-check", "--disable-sync", "--hide-crash-restore-bubble",
                   "--window-size=1180,860", "--disable-features=Translate,msEdgeTranslate,msUndersideButton",
                   # la ventana es solo el panel: sin extensiones ni tareas de fondo del navegador (gasta menos)
                   "--disable-extensions", "--disable-background-networking", "--disable-component-update",
                   "--disable-domain-reliability", "--no-pings"]
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, **child_kwargs())
            except OSError as e:
                print(f"No pude abrir la ventana ({e}); uso el navegador.")
                open_browser_later(self.url, delay=0)
                return
            self.proc = proc
            self.last_launch = time.time()
            threading.Thread(target=self._watch, args=(proc,), daemon=True).start()

    def _watch(self, proc):
        """Vigila la ventana: cuando el usuario la cierra, avisa a la app (on_closed)."""
        started = time.time()
        if not IS_WINDOWS:
            proc.wait()
            if time.time() - started < 5:
                return      # la ventana quedó en otro proceso del navegador; no sabemos cuándo se cierra
        else:
            seen, misses, exited_at = False, 0, None
            while True:
                hwnd = self._find(proc)
                if hwnd:
                    seen, misses = True, 0
                elif seen:
                    misses += 1
                alive = proc.poll() is None
                if not alive and exited_at is None:
                    exited_at = time.time()
                if seen and misses >= 2:
                    break                       # la ventana se cerró (aunque el navegador siga en segundo plano)
                if not alive and not seen and time.time() - exited_at > 20:
                    break                       # el navegador terminó sin llegar a mostrar la ventana
                with self.lock:
                    if self.proc is not proc:
                        return                  # la cerró la propia app
                time.sleep(1)
            if proc.poll() is None:
                threading.Thread(target=self._reap, args=(proc,), daemon=True).start()
        with self.lock:
            if self.proc is not proc:
                return
            self.proc = None
        self.on_closed()

    def adopt(self):
        """Tras actualizarse, la ventana que abrió la versión anterior sigue abierta: se vigila por su título."""
        if not self._find():
            return False
        self.title_ok = True
        threading.Thread(target=self._watch_title, daemon=True).start()
        return True

    def _watch_title(self):
        misses = 0
        while misses < 2:
            misses = 0 if _win_find_app_window() else misses + 1
            with self.lock:
                if self.proc is not None:
                    return              # se abrió una ventana nueva (la vigila _watch)
            time.sleep(1)
        with self.lock:
            if self.proc is not None:
                return
        self.on_closed()

    def _reap(self, proc, grace=10):
        """El navegador suele terminar solo al cerrarse su última ventana; si queda colgado, lo cerramos."""
        deadline = time.time() + grace
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.5)
        with self.lock:
            if self.proc is not None or _win_find_app_window(pid=proc.pid):
                return          # mientras tanto se volvió a abrir la ventana
        try:
            proc.terminate()
        except OSError:
            pass

    def close(self):
        """La app se cierra: cerramos la ventana como si el usuario tocara la X y, si no responde, a la fuerza."""
        with self.lock:
            proc, self.proc = self.proc, None
        if not proc:
            hwnd = _win_find_app_window()       # la ventana adoptada tras una actualización
            if hwnd:
                _win_post_close(hwnd)
            return
        if proc.poll() is not None:
            return
        if IS_WINDOWS:
            hwnd = _win_find_app_window() or _win_find_app_window(pid=proc.pid)
            if hwnd and _win_post_close(hwnd):
                try:
                    proc.wait(timeout=6)
                    return
                except subprocess.TimeoutExpired:
                    pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass


def ask_yes_no(text, default_no=True):
    """Pregunta nativa Sí/No. Devuelve True, False o None si no se pudo preguntar."""
    if IS_WINDOWS:
        try:
            import ctypes
            flags = 0x4 | 0x20 | 0x10000 | 0x40000 | (0x100 if default_no else 0)
            # MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST | MB_DEFBUTTON2
            r = ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, flags)
            return {6: True, 7: False}.get(r)
        except Exception:
            return None
    zenity = shutil.which("zenity")
    if zenity:
        try:
            r = subprocess.run([zenity, "--question", "--title", APP_NAME, "--text", text, "--width", "420"],
                               timeout=600)
            return r.returncode == 0
        except Exception:
            return None
    return None


def notify(text):
    if TRAY:
        TRAY.notify(text)
    elif not IS_WINDOWS and shutil.which("notify-send"):
        try:
            subprocess.Popen(["notify-send", APP_NAME, text])
        except OSError:
            pass


def running_servers():
    return [s for s in (manager.servers.values() if manager else []) if s.running()]


def quit_app():
    if HTTPD:
        threading.Thread(target=HTTPD.shutdown, daemon=True).start()


def servers_text(running):
    names = ", ".join(f"«{s.meta.get('name', s.id)}»" for s in running)
    players = sum(len(s.players) for s in running)
    text = names + (" está encendido" if len(running) == 1 else " están encendidos")
    return text + (f" con {players} jugador{'es' if players != 1 else ''} conectado{'s' if players != 1 else ''}"
                   if players else "")


def on_window_closed():
    """Se cerró la ventana: si no hay servidores encendidos, la app se cierra; si hay, preguntamos."""
    running = running_servers()
    if not running:
        quit_app()
        return
    answer = ask_yes_no(servers_text(running) + ".\n\n¿Quieres apagarlo y cerrar Servidor Home?\n\n"
                        "Sí: se apaga guardando el mundo.\n"
                        "No: sigue funcionando; vuelve a abrir la ventana desde el ícono junto al reloj "
                        "o desde el acceso directo.")
    if answer:
        quit_app()
    else:
        notify("Servidor Home sigue funcionando en segundo plano.")


def tray_quit():
    running = running_servers()
    if running and not ask_yes_no(servers_text(running) + ".\n\n¿Apagarlo y cerrar Servidor Home?"):
        return
    quit_app()


class Tray:
    """Ícono de Servidor Home junto al reloj de Windows (Abrir / Salir)."""
    WM_TRAY = 0x8000 + 1     # WM_APP + 1

    def __init__(self, icon_path, on_open, on_quit):
        self.icon_path = icon_path
        self.on_open = on_open
        self.on_quit = on_quit
        self.hwnd = None
        self.ok = False
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(10)

    def _nid(self, flags):
        import ctypes
        from ctypes import wintypes

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                        ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                        ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
                        ("hBalloonIcon", wintypes.HICON)]
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = APP_NAME
        return nid

    def _run(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = LRESULT
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                               ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                               wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                                          ctypes.c_int, wintypes.UINT]
            user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                              ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
            user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
            shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
            WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_LBUTTONUP, WM_DESTROY, WM_CLOSE = 0x203, 0x205, 0x202, 0x2, 0x10
            NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
            NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
            taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

            def add_icon():
                nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
                self.ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

            def show_menu(hwnd):
                menu = user32.CreatePopupMenu()
                user32.AppendMenuW(menu, 0, 1, "Abrir Servidor Home")
                user32.AppendMenuW(menu, 0x800, 0, None)        # separador
                user32.AppendMenuW(menu, 0, 2, "Salir")
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.SetForegroundWindow(hwnd)
                cmd = user32.TrackPopupMenu(menu, 0x100 | 0x20, pt.x, pt.y, 0, hwnd, None)   # RETURNCMD|RIGHTBUTTON
                user32.DestroyMenu(menu)
                if cmd == 1:
                    threading.Thread(target=self.on_open, daemon=True).start()
                elif cmd == 2:
                    threading.Thread(target=self.on_quit, daemon=True).start()

            def wndproc(hwnd, msg, wparam, lparam):
                if msg == self.WM_TRAY:
                    if lparam in (WM_LBUTTONDBLCLK, WM_LBUTTONUP):
                        threading.Thread(target=self.on_open, daemon=True).start()
                    elif lparam == WM_RBUTTONUP:
                        show_menu(hwnd)
                    return 0
                if msg == taskbar_created:          # el Explorador se reinició: volver a poner el ícono
                    add_icon()
                    return 0
                if msg == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    nid = self._nid(0)
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            self._wndproc = WNDPROC(wndproc)        # evitar que Python lo libere

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                            ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            user32.CreatePopupMenu.restype = wintypes.HMENU
            user32.LoadIconW.restype = wintypes.HICON
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = "ServidorHomeTray"
            user32.RegisterClassW(ctypes.byref(wc))
            self.hwnd = user32.CreateWindowExW(0, "ServidorHomeTray", "Servidor Home (bandeja)", 0,
                                               0, 0, 0, 0, None, None, hinst, None)
            self.hicon = user32.LoadImageW(None, self.icon_path, 1, 16, 16, 0x10) if os.path.exists(self.icon_path) else None
            if not self.hicon:
                self.hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))       # IDI_APPLICATION
            self._NIM_MODIFY, self._NIF_INFO, self._shell32 = NIM_MODIFY, NIF_INFO, shell32
            add_icon()
        except Exception as e:
            print(f"No se pudo crear el ícono junto al reloj: {e}")
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def notify(self, text):
        if not (self.ok and self.hwnd):
            return
        try:
            import ctypes
            nid = self._nid(self._NIF_INFO)
            nid.szInfo = text[:255]
            nid.szInfoTitle = APP_NAME
            nid.dwInfoFlags = 1          # NIIF_INFO
            self._shell32.Shell_NotifyIconW(self._NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def stop(self):
        if self.hwnd:
            try:
                import ctypes
                from ctypes import wintypes
                post = ctypes.windll.user32.PostMessageW
                post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                post(self.hwnd, 0x10, 0, 0)        # WM_CLOSE
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# API HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = f"ServidorHome/{APP_VERSION}"

    def log_message(self, fmt, *args):
        pass  # silencio: la consola de cada servidor ya muestra lo importante

    # ---- helpers ----
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype, download_name=None, no_store=False):
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if download_name:
            ascii_name = re.sub(r'[^\w.\- ]', "_", download_name.encode("ascii", "replace").decode("ascii"))
            self.send_header("Content-Disposition", f'attachment; filename="{ascii_name}"; '
                                                    f"filename*=UTF-8''{urllib.parse.quote(download_name)}")
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def save_body(self, dest, limit=8 * 1024 ** 3):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ValueError("No llegó ningún archivo.")
        if n > limit:
            raise ValueError("Archivo demasiado grande.")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        remaining = n
        with open(dest, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("La subida se interrumpió.")
                f.write(chunk)
                remaining -= len(chunk)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5 * 1024 * 1024:
            raise ValueError("Solicitud demasiado grande.")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def route(self, method):
        u = urllib.parse.urlparse(self.path)
        parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            self.dispatch(method, parts, q)
        except KeyError:
            self.send_json({"error": "No encontrado."}, 404)
        except (ValueError, RuntimeError) as e:
            self.send_json({"error": str(e)}, 400)
        except urllib.error.URLError as e:
            self.send_json({"error": f"Sin conexión con el servicio de descargas: {e.reason}"}, 502)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except PermissionError:
            self.send_json({"error": "No se puede modificar ese archivo porque está en uso. Si el servidor está "
                                     "encendido, apágalo e inténtalo de nuevo."}, 400)
        except Exception as e:
            traceback.print_exc()
            self.send_json({"error": f"Error interno: {e}"}, 500)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    # ---- rutas ----
    def dispatch(self, method, parts, q):
        if method == "GET" and (not parts or parts == ["index.html"]):
            return self.send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
        if method == "GET" and parts == ["remoto"]:             # panel de un servidor de un amigo
            return self.send_file(os.path.join(WEB_DIR, "remoto.html"), "text/html; charset=utf-8", no_store=True)
        if not parts or parts[0] != "api":
            raise KeyError()
        p = parts[1:]

        if method == "GET" and p == ["info"]:
            return self.send_json({
                "app": APP_NAME, "version": APP_VERSION, "lan_ip": lan_ip(),
                "ram_total_mb": total_ram_mb(),
                "types": [{"id": k, **v} for k, v in SERVER_TYPES.items()],
                "platform": f"{platform.system()} {platform.machine()}",
                "os": "windows" if IS_WINDOWS else ("mac" if sys.platform == "darwin" else "linux"),
                "home": os.path.expanduser("~"),
                "app_window": bool(WINDOW and WINDOW.available),
                "data_dir": DATA_DIR, "installed": INSTALLED,
                "update": UPDATER.to_json() if UPDATER else None,
            })
        if method == "POST" and p == ["ventana"]:
            open_ui()
            return self.send_json({"ok": True})
        if method == "POST" and p == ["abrir"]:          # enlaces externos desde la ventana de la app
            url = str(self.body_json().get("url") or "")
            if not re.match(r"https?://\S+$", url, re.I) or self.client_address[0] not in ("127.0.0.1", "::1"):
                raise ValueError("Enlace no válido.")
            if not open_external(url):
                raise RuntimeError("No pude abrir el navegador.")
            return self.send_json({"ok": True})
        if method == "POST" and p == ["shutdown"]:
            self.send_json({"ok": True})
            if HTTPD:
                threading.Thread(target=HTTPD.shutdown, daemon=True).start()
            return None
        if method == "GET" and p == ["state"]:
            ui_seen()                           # la ventana está abierta (para no actualizar mientras la usan)
            return self.send_json({
                "servers": [s.summary() for s in manager.servers.values()],
                "playit": manager.playit.state(),
                "imports": [j.to_json() for j in manager.imports.values() if j.status != "hecho"],
                "app_version": APP_VERSION,
                "update": UPDATER.to_json() if UPDATER else None,
            })
        if p and p[0] == "actualizar":
            if not UPDATER:
                raise RuntimeError("Las actualizaciones no están disponibles.")
            if method == "POST" and p == ["actualizar"]:
                UPDATER.apply_now()
                return self.send_json({"ok": True, "update": UPDATER.to_json()})
            if method == "POST" and p == ["actualizar", "buscar"]:
                if not UPDATER.enabled:
                    raise RuntimeError("Esta copia de Servidor Home no se actualiza sola (es la versión portable).")
                UPDATER.check_soon()
                return self.send_json({"ok": True})
            if method == "POST" and p == ["actualizar", "visto"]:
                UPDATER.seen()
                return self.send_json({"ok": True})
            if method == "PUT" and p == ["actualizar"]:
                UPDATER.set_auto(bool(self.body_json().get("auto")))
                return self.send_json(UPDATER.to_json())
            raise KeyError()
        if method == "GET" and p == ["versions"]:
            t = q.get("type", "vanilla")
            if t not in LISTERS:
                raise ValueError("Tipo desconocido.")
            return self.send_json(version_list(t, q.get("snapshots") == "1"))
        if method == "GET" and p == ["loaders"]:
            t = q.get("type")
            if t not in LOADERS:
                return self.send_json([])
            return self.send_json(LOADERS[t](q.get("mc", "")))

        # ---- buscador de modpacks (Modrinth y CurseForge) ----
        if p and p[0] == "packs":
            if method == "GET" and p == ["packs", "search"]:
                return self.send_json(packs_search(q.get("src", "modrinth"), q.get("q", ""), q.get("offset", 0)))
            if method == "GET" and p == ["packs", "versions"]:
                return self.send_json(packs_versions(q.get("src", "modrinth"), q.get("id", "")))
            if method == "POST" and p == ["packs", "import"]:
                b = self.body_json()
                job = packs_import(b.get("src"), b.get("project"), b.get("version"), b.get("title"))
                return self.send_json(manager.start_import(job).to_json(), 201)
            if method == "GET" and p == ["packs", "curseforge-key"]:
                k = cf_key()
                return self.send_json({"set": bool(k), "hint": ("…" + k[-4:]) if k else ""})
            if method == "PUT" and p == ["packs", "curseforge-key"]:
                k = (self.body_json().get("key") or "").strip()
                if k:
                    if not re.match(r"^[\x21-\x7e]{16,200}$", k):
                        raise ValueError("Esa clave no parece una clave de la API de CurseForge.")
                    cf_get(f"/games/{CF_GAME_MINECRAFT}", key=k)          # que funcione antes de guardarla
                set_app_setting("curseforge_key", k or None)
                return self.send_json({"set": bool(k), "hint": ("…" + k[-4:]) if k else ""})
            raise KeyError()

        # ---- importar modpacks ----
        if p and p[0] == "import":
            if method == "GET" and p == ["import", "instances"]:
                return self.send_json(find_instances())
            if method == "POST" and p == ["import", "upload"]:
                name = os.path.basename(q.get("name", "modpack.zip")) or "modpack.zip"
                if not name.lower().endswith((".zip", ".mrpack")):
                    raise ValueError("Sube un archivo .zip o .mrpack.")
                dest = os.path.join(UPLOADS_DIR, secrets.token_hex(6) + "-" + re.sub(r"[^\w.\-]", "_", name))
                try:
                    self.save_body(dest)
                except Exception:
                    if os.path.exists(dest):
                        os.remove(dest)
                    raise
                job = manager.start_import(ImportJob("archivo", dest, name))
                return self.send_json(job.to_json(), 201)
            if method == "POST" and p == ["import", "folder"]:
                path = (self.body_json().get("path") or "").strip()
                if not path:
                    raise ValueError("Escribe la ruta de la carpeta.")
                job = manager.start_import(ImportJob("carpeta", os.path.expanduser(path)))
                return self.send_json(job.to_json(), 201)
            if len(p) >= 2:
                job = manager.imports.get(p[1])
                if not job:
                    raise KeyError()
                if method == "GET" and len(p) == 2:
                    return self.send_json(job.to_json())
                if method == "DELETE" and len(p) == 2:
                    manager.cancel_import(job)
                    return self.send_json({"ok": True})
                if method == "POST" and len(p) == 3 and p[2] == "confirm":
                    s = manager.confirm_import(job, self.body_json())
                    return self.send_json(s.summary(), 201)

        # ---- servidores de amigos (acceso remoto, lado del amigo) ----
        if p and p[0] == "amigos":
            fr = manager.friends
            if p == ["amigos"]:
                if method == "GET":
                    return self.send_json(fr.list())
                if method == "POST":
                    return self.send_json(fr.add(self.body_json().get("code")), 201)
            if method == "DELETE" and len(p) == 2:
                fr.remove(p[1])
                return self.send_json({"ok": True})
            if len(p) >= 3:
                query = urllib.parse.urlparse(self.path).query
                path = "/".join(p[2:]) + ("?" + query if query else "")
                body = self.body_json() if method in ("POST", "PUT") else None
                status, data = fr.request(p[1], method, path, body)
                return self.send_json(data if data is not None else {}, status)
            raise KeyError()

        # ---- playit.gg ----
        if p and p[0] == "playit":
            pl = manager.playit
            if method == "GET" and p == ["playit"]:
                return self.send_json(pl.state())
            if method == "GET" and p == ["playit", "log"]:
                last, lines = pl.console.since(int(q.get("since", 0)))
                return self.send_json({"last": last, "lines": lines})
            if method == "POST" and p == ["playit", "setup"]:
                pl.setup(self.body_json().get("mode") or "self-managed")
                return self.send_json(pl.state())
            if method == "POST" and p == ["playit", "cancel"]:
                pl.cancel_setup()
                return self.send_json(pl.state())
            if method == "POST" and p == ["playit", "retry"]:
                pl.retry()
                return self.send_json(pl.state())
            if method == "POST" and p == ["playit", "unlink"]:
                pl.unlink()
                return self.send_json(pl.state())

        if p == ["servers"]:
            if method == "GET":
                return self.send_json([s.summary() for s in manager.servers.values()])
            if method == "POST":
                s = manager.create(self.body_json())
                return self.send_json(s.summary(), 201)

        if len(p) >= 2 and p[0] == "servers":
            s = manager.get(p[1])
            action = p[2] if len(p) > 2 else None

            if action is None:
                if method == "GET":
                    d = s.summary()
                    d["properties"] = read_properties(os.path.join(s.dir, "server.properties"))
                    if "motd" in d["properties"]:
                        d["properties"]["motd"] = prop_unescape(d["properties"]["motd"])
                    eula = os.path.join(s.dir, "eula.txt")
                    d["eula"] = os.path.exists(eula) and "eula=true" in _read_text(eula)
                    d["has_world"] = bool(s.world_dirs())
                    d["version_history"] = s.meta.get("versiones_anteriores", [])
                    return self.send_json(d)
                if method == "DELETE":
                    manager.delete(s.id)
                    return self.send_json({"ok": True})

            if method == "POST" and action in ("start", "stop", "restart", "kill", "install"):
                if action == "start":
                    s.start(user=True)
                elif action == "stop":
                    s.stop()
                elif action == "restart":
                    s.stop(restart=True)
                elif action == "kill":
                    s.kill()
                elif action == "install":
                    s.install()
                return self.send_json(s.summary())

            if action == "remoto":
                ra = manager.remote
                if method == "GET" and len(p) == 3:
                    return self.send_json(ra.state(s.id))
                if method == "POST" and len(p) == 3:
                    ra.create(s.id, self.body_json().get("name"))
                    s.log("Se creó un acceso remoto para administrar este servidor.")
                    return self.send_json(ra.state(s.id), 201)
                if method == "DELETE" and len(p) == 4:
                    ra.revoke(s.id, p[3])
                    s.log("Se quitó un acceso remoto.")
                    return self.send_json(ra.state(s.id))

            if method == "POST" and action == "fix":
                s.fix(self.body_json().get("action") or {})
                return self.send_json(s.summary())
            if method == "POST" and action == "rendimiento":
                return self.send_json(s.add_perf_mods())
            if method == "POST" and action == "repairs-clear":
                s.repairs_shown = []
                return self.send_json(s.summary())

            if method == "POST" and action == "version":
                b = self.body_json()
                s.change_version(b.get("mc_version"), b.get("loader_version"), bool(b.get("new_world")))
                return self.send_json(s.summary())

            if action == "players":
                if method == "GET":
                    return self.send_json(s.players_info())
                if method == "POST":
                    b = self.body_json()
                    return self.send_json(s.player_action(b.get("action"), b.get("name"), b.get("reason", "")))

            if method == "GET" and action == "log":
                last, lines = s.console.since(int(q.get("since", 0)))
                return self.send_json({"last": last, "lines": lines, "status": s.status,
                                       "players": sorted(s.players), "error": s.error})
            if method == "POST" and action == "command":
                s.send(self.body_json().get("command", ""))
                return self.send_json({"ok": True})

            if method == "PUT" and action == "properties":
                props = self.body_json().get("properties", {})
                clean = {}
                for k, v in props.items():
                    if not re.match(r"^[a-zA-Z0-9.\-_]+$", k):
                        raise ValueError(f"Clave no válida: {k}")
                    clean[k] = clean_prop_value(v)
                    if k == "motd":
                        clean[k] = prop_escape(clean[k])
                if "server-port" in clean:
                    port = int(clean["server-port"])
                    if not 1024 <= port <= 65535:
                        raise ValueError("El puerto debe estar entre 1024 y 65535.")
                write_properties(os.path.join(s.dir, "server.properties"), clean)
                s.log("Ajustes guardados. Se aplican la próxima vez que enciendas el servidor.")
                return self.send_json({"ok": True})

            if method == "PUT" and action == "settings":
                d = self.body_json()
                if "name" in d and d["name"].strip():
                    s.meta["name"] = d["name"].strip()[:60]
                if "ram_mb" in d:
                    ram = int(d["ram_mb"])
                    if ram < 512:
                        raise ValueError("Asigna al menos 512 MB.")
                    s.meta["ram_mb"] = ram
                if "jvm_args" in d:
                    s.meta["jvm_args"] = d["jvm_args"]
                if "auto_fix" in d:
                    s.meta["auto_fix"] = bool(d["auto_fix"])
                if "java_opt" in d:
                    s.meta["java_opt"] = bool(d["java_opt"])
                if d.get("eula"):
                    s.meta["eula"] = True
                    with open(os.path.join(s.dir, "eula.txt"), "w") as f:
                        f.write("eula=true\n")
                s.save_meta()
                return self.send_json(s.summary())

            if action == "addons":
                path = s.addons_path()
                if method == "GET":
                    return self.send_json(s.list_addons())
                name = os.path.basename(q.get("name", ""))
                if not name or name.startswith("."):
                    raise ValueError("Nombre de archivo no válido.")
                target = os.path.join(path, name)
                if method == "POST":
                    if not name.endswith((".jar", ".zip")):
                        raise ValueError("Solo se admiten archivos .jar o .zip.")
                    self.save_body(target, limit=1024 ** 3)
                    s.log(f"Añadido {name}. Se carga la próxima vez que enciendas.")
                    return self.send_json({"ok": True})
                if method == "PUT":     # activar / desactivar
                    if not os.path.isfile(target):
                        raise KeyError()
                    if name.endswith(".disabled"):
                        os.rename(target, target[: -len(".disabled")])
                        s.forget_marks(name)
                    else:
                        os.rename(target, target + ".disabled")
                    return self.send_json({"ok": True})
                if method == "DELETE":
                    os.remove(target)
                    s.forget_marks(name)
                    return self.send_json({"ok": True})

            if action == "icono" and len(p) == 3:
                if method == "GET":
                    if not os.path.isfile(s.icon_path):
                        raise KeyError()
                    return self.send_file(s.icon_path, "image/png", no_store=True)
                if method == "PUT":
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0:
                        raise ValueError("No llegó ninguna imagen.")
                    if n > 1024 * 1024:
                        raise ValueError("La imagen pesa demasiado.")
                    s.set_icon(self.rfile.read(n))
                    return self.send_json(s.summary())
                if method == "DELETE":
                    s.remove_icon()
                    return self.send_json(s.summary())

            if action == "compartir":
                if method == "POST" and len(p) == 3:
                    s.build_share_zip()
                    return self.send_json(s.summary())
                if method == "GET" and len(p) == 3:
                    path = s.share_file()
                    if not path:
                        raise KeyError()
                    return self.send_file(path, "application/zip", os.path.basename(path))
                if method == "POST" and p[3:] == ["abrir"]:
                    if self.client_address[0] not in ("127.0.0.1", "::1"):
                        raise ValueError("La carpeta solo se puede abrir en el PC del servidor.")
                    path = s.share_file()
                    if not path:
                        raise RuntimeError("Primero arma el zip.")
                    if not show_in_folder(path):
                        raise RuntimeError(f"No pude abrir la carpeta. Está en: {SHARE_DIR}")
                    return self.send_json({"ok": True})

            if action == "backups":
                if method == "GET" and len(p) == 3:
                    return self.send_json(s.list_backups())
                if method == "POST":
                    return self.send_json({"name": s.backup()})
                if method == "GET" and len(p) == 4:
                    name = os.path.basename(p[3])
                    fp = os.path.join(s.dir, "respaldos", name)
                    if not os.path.isfile(fp):
                        raise KeyError()
                    return self.send_file(fp, "application/zip", name)
                if method == "DELETE" and len(p) == 4:
                    os.remove(os.path.join(s.dir, "respaldos", os.path.basename(p[3])))
                    return self.send_json({"ok": True})

        raise KeyError()


# --------------------------------------------------------------------------- #
# Arranque
# --------------------------------------------------------------------------- #

def open_browser_later(url, delay=0.8):
    def run():
        time.sleep(delay)
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def _win_grant_foreground():
    """Windows solo deja pasar al frente a quien recibió el último clic, y ese clic fue en la ventana de la
    app (que es del navegador, otro proceso). Compartimos un instante la entrada de esa ventana y damos
    permiso para que el navegador predeterminado se muestre al frente al abrir el enlace."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.WinDLL("user32"), ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        fg = user32.GetForegroundWindow()
        other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        attached = bool(other and other != me and user32.AttachThreadInput(me, other, True))
        try:
            user32.AllowSetForegroundWindow(-1)            # ASFW_ANY
        finally:
            if attached:
                user32.AttachThreadInput(me, other, False)
    except Exception:
        pass


def open_external(url):
    """Abre un enlace en el navegador predeterminado del usuario, como cualquier programa."""
    print(f"Abriendo en el navegador: {url}")
    if IS_WINDOWS:
        _win_grant_foreground()
        try:
            os.startfile(url)
            return True
        except OSError:
            pass
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False


def show_in_folder(path):
    """Abre el explorador de archivos en la carpeta de ese archivo (en Windows, con el archivo seleccionado)."""
    try:
        if IS_WINDOWS:
            _win_grant_foreground()
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"', **child_kwargs())
            return True
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen([opener, os.path.dirname(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **child_kwargs(detach=True))
            return True
    except OSError:
        pass
    return False


def _local_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def already_running(port):
    """¿Hay otra copia de la app abierta en ese puerto?"""
    try:
        info = json.loads(_local_opener().open(f"http://127.0.0.1:{port}/api/info", timeout=3).read().decode("utf-8"))
        return info.get("app") == APP_NAME
    except Exception:
        return False


APP_PID_FILE = os.path.join(APPDATA_DIR, "servidor-home.pid")


def _app_process_alive(pid):
    if IS_WINDOWS:
        return (windows_process_image(pid) or "").startswith("python")
    return pid_alive(pid)


def close_running(port):
    """Pide a la app abierta que se cierre (apagando los servidores) y espera a que termine.
    Lo usan el instalador y el desinstalador antes de reemplazar archivos."""
    try:
        pid = int(_read_text(APP_PID_FILE).strip() or 0)
    except ValueError:
        pid = 0
    if already_running(port):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            _local_opener().open(req, timeout=10)
        except Exception:
            pass
    if pid and pid != os.getpid():
        for _ in range(300):                 # hasta 2,5 minutos: los servidores se apagan guardando el mundo
            if not _app_process_alive(pid):
                return
            time.sleep(0.5)
        if IS_WINDOWS:
            windows_kill(pid)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def request_window(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ventana", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        _local_opener().open(req, timeout=10)
        return True
    except Exception:
        return False


APP_URL = "http://127.0.0.1:8765"


def open_ui():
    """Abre (o trae al frente) la ventana de la app; si no hay motor para la ventana, el navegador."""
    if WINDOW and WINDOW.available:
        WINDOW.open()
    else:
        open_browser_later(APP_URL, delay=0)


class AppHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # En Windows SO_REUSEADDR deja que dos programas usen el mismo puerto: pedimos uso exclusivo.
    allow_reuse_address = not IS_WINDOWS

    def server_bind(self):
        if IS_WINDOWS and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def setup_log_file():
    """Sin consola (Windows con pythonw o el acceso directo de Linux) guardamos todo en servidor-home.log."""
    if sys.stdout is not None and sys.stderr is not None:
        # Tras actualizarse, la app nueva escribe en servidor-home.log por la salida que le pasó la vieja: que cada
        # línea quede escrita al tiro (si no, se queda en memoria hasta que la app se cierra).
        if "--tras-actualizar" in sys.argv:
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.reconfigure(line_buffering=True)
                except (AttributeError, ValueError, OSError):
                    pass
            print(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} (versión nueva) ====")
        return
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 5 * 1024 * 1024:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
        print(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
    except OSError:
        pass


def adopt_portable_data():
    """Si antes se usó la versión portable (en Documentos\\servidor home), reutiliza su vínculo con playit.gg:
    así tus amigos siguen usando la misma dirección y no hay que vincular de nuevo."""
    old = os.path.join(DATA_DIR, "playit")
    if os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(PLAYIT_DIR)):
        return
    if not os.path.isfile(os.path.join(old, "playit.toml")) or os.path.isfile(os.path.join(PLAYIT_DIR, "playit.toml")):
        return
    try:
        os.makedirs(PLAYIT_DIR, exist_ok=True)
        for name in ("modo.txt", "playit.toml"):
            if os.path.isfile(os.path.join(old, name)):
                shutil.copyfile(os.path.join(old, name), os.path.join(PLAYIT_DIR, name))
        if not IS_WINDOWS:
            os.chmod(os.path.join(PLAYIT_DIR, "playit.toml"), 0o600)
        print("Se reutilizó el vínculo con playit.gg de la versión portable.")
    except OSError as e:
        print(f"No pude reutilizar el vínculo con playit.gg de la versión portable: {e}")


def show_error(msg):
    """Muestra un error aunque la app no tenga consola (ventana de aviso en Windows)."""
    print(msg)
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
        except Exception:
            pass


def main():
    global manager, HTTPD, WINDOW, TRAY, APP_URL, UPDATER
    setup_log_file()
    ap = argparse.ArgumentParser(description="Importa un modpack y enciende tu servidor de Minecraft.")
    ap.add_argument("--port", type=int, default=8765, help="puerto interno de la app (por defecto 8765)")
    ap.add_argument("--lan", action="store_true", help="permitir abrir el panel desde otros equipos de tu red")
    ap.add_argument("--navegador", action="store_true", help="abrir en el navegador en vez de una ventana propia")
    ap.add_argument("--no-browser", action="store_true", help="no abrir ninguna ventana (pruebas)")
    ap.add_argument("--cerrar", action="store_true", help="cerrar la app si está abierta (lo usa el instalador)")
    ap.add_argument("--sin-ventana", action="store_true", help=argparse.SUPPRESS)       # tras actualizarse
    ap.add_argument("--tras-actualizar", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    passthrough = [a for a in sys.argv[1:] if a not in ("--sin-ventana", "--tras-actualizar")]
    APP_URL = f"http://127.0.0.1:{args.port}"

    if args.cerrar:
        close_running(args.port)
        return
    # ¿Ya estaba abierta? Entonces solo mostramos su ventana.
    if already_running(args.port):
        print(f"{APP_NAME} ya estaba abierto: {APP_URL}")
        if not args.no_browser:
            allow_other_to_focus()
            if not focus_existing_window() and not request_window(args.port):
                open_browser_later(APP_URL, delay=0)
                time.sleep(1.5)
        return
    UPDATER = Updater()
    if args.tras_actualizar:
        UPDATER.after_update()
    elif UPDATER.apply_at_startup(args.port, passthrough):
        return          # la versión nueva quedó abierta en lugar de esta
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    try:
        httpd = AppHTTPServer((host, args.port), Handler)
    except OSError as e:
        show_error(f"No pude abrir el puerto {args.port} ({e}). Otro programa lo está usando; "
                   f"ciérralo o abre la app con --port 8766.")
        sys.exit(1)
    HTTPD = httpd
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        with open(APP_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    if INSTALLED:
        adopt_portable_data()
    manager = Manager()
    manager.playit = Playit()
    manager.remote = RemoteAccess()
    manager.friends = RemoteFriends()
    if manager.remote.wanted():
        manager.remote.start()
    UPDATER.start()
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
        KeepAwake()
    print(f"\n  {APP_NAME} v{APP_VERSION}")
    print(f"  Panel:            {APP_URL}")
    if args.lan:
        print(f"  Desde tu red:     http://{lan_ip()}:{args.port}   (sin contraseña: úsalo solo en redes de confianza)")
    print(f"  Servidores en:    {SERVERS_DIR}")
    print("  Para cerrar usa «Salir» (o Ctrl+C aquí): los servidores se apagan guardando el mundo.\n")

    if not args.no_browser:
        if not args.navegador:
            WINDOW = AppWindow(APP_URL, on_window_closed)
            if not WINDOW.available:
                print("No encontré Edge ni Chrome para la ventana propia; abro el navegador.")
        if IS_WINDOWS:
            TRAY = Tray(os.path.join(WEB_DIR, "icono.ico"), on_open=open_ui, on_quit=tray_quit)
        if args.sin_ventana:            # recién actualizada: la ventana que estaba abierta sigue ahí
            if WINDOW:
                WINDOW.adopt()
        else:
            open_ui()

    def on_signal(_sig, _frm):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_signal)
    for name in ("SIGHUP", "SIGBREAK"):          # se cerró la terminal / Ctrl+Pausa en Windows
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando...")
    finally:
        restarting = bool(UPDATER and UPDATER.restart_pending)
        manager.shutdown_all()
        if WINDOW and not restarting:
            WINDOW.close()
        if TRAY:
            TRAY.stop()
        httpd.server_close()
        try:
            os.remove(APP_PID_FILE)
        except OSError:
            pass
        if restarting:          # se instaló una versión nueva: se abre en lugar de esta
            UPDATER.handoff(args.port, passthrough + ["--sin-ventana"])


if __name__ == "__main__":
    main()
