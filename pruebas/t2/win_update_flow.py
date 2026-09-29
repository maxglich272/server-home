#!/usr/bin/env python3
# Actualizaciones automáticas en Windows (Wine) con la app INSTALADA por el instalador (Python y ventana reales):
#  A) versión nueva con la ventana abierta → «Actualizar ahora» → se reinicia en la versión nueva, conserva la
#     ventana, un solo ícono junto al reloj, versión nueva en el registro de Windows
#  B) la ventana conservada se sigue vigilando: al cerrarla, la app se cierra
#  C) sin nadie mirando: se instala sola
#  D) descargada con la ventana abierta: se instala al volver a abrir la app
#  E) la versión nueva no arranca: vuelve sola a la anterior
import json, os, re, shutil, subprocess, sys, threading, time, urllib.request

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", WINEDEBUG="-all", WINEPREFIX="/home/claude/win/prefix2", DISPLAY=":99")
WINE = "/usr/lib/wine/wine64"
PY = "Z:/home/claude/win/py/python/python.exe"
FAKE = "/home/claude/build/fake"
ARGS_FILE = os.path.join(FAKE, "edge-args.txt")
ROOT = "/home/claude/win/prefix2/drive_c/users/root/AppData/Local"
APPDIR = ROOT + "/Programs/Servidor Home"
UPDDIR = ROOT + "/Servidor Home/actualizaciones"
PUB = "/home/claude/mock2/www/gh"
SRC = "/home/claude/servidor-home"
KEY = "/home/claude/build/claves-prueba/clave-prueba.json"
T = "/home/claude/t2/wupd"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("OK  ", name, extra, flush=True)
    else:
        fail += 1
        print("FAIL", name, extra, flush=True)


def api(path, data=None, timeout=5, method=None):
    try:
        req = urllib.request.Request("http://127.0.0.1:8765/api/" + path,
                                     data=None if data is None else json.dumps(data).encode(),
                                     method=method or ("POST" if data is not None else "GET"),
                                     headers={"Content-Type": "application/json"})
        return json.loads(opener.open(req, timeout=timeout).read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", **json.loads(e.read() or b"{}")}
    except Exception as e:
        return {"_error": str(e)}


def wait(cond, limit, step=0.5):
    t = time.time()
    while time.time() - t < limit:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


def procs(word):
    out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout.splitlines()
    return [l for l in out if word in l and "win_update_flow" not in l and "grep" not in l and "defunct" not in l]


def helper(*a, timeout=40):
    r = subprocess.run([WINE, PY, "-u", "Z:/home/claude/t2/win_helper.py", *a], env=ENV, capture_output=True, text=True,
                       timeout=timeout, input="")
    return r.stdout.strip()


def edge_lines():
    try:
        return len(open(ARGS_FILE, encoding="utf-8").read().splitlines())
    except FileNotFoundError:
        return 0


def app_window_open():
    return "'Servidor Home'" in helper("windows")


def launch():
    subprocess.Popen([WINE, "cmd", "/c", "Z:\\tmp\\lanzar.bat"], env=ENV, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wait(lambda: api("info").get("app") == "Servidor Home", 90)


def app_gone():
    return not procs("servidor_home.py") and "_error" in api("info", timeout=2)


def version():
    return api("info", timeout=3).get("version")


def upd():
    return api("info", timeout=3).get("update") or {}


def reg_version():
    r = subprocess.run([WINE, "reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ServidorHome",
                        "/v", "DisplayVersion"], env=ENV, capture_output=True, text=True, timeout=60)
    m = re.search(r"DisplayVersion\s+REG_SZ\s+(\S+)", r.stdout)
    return m.group(1) if m else None


def file_version():
    return re.search(r'^APP_VERSION = "([^"]+)"', open(APPDIR + "/servidor_home.py", encoding="utf-8").read(), re.M).group(1)


def publish(version, novedades=(), romper=None):
    src = f"{T}/src-{version}"
    shutil.rmtree(src, ignore_errors=True)
    os.makedirs(src + "/web")
    for rel in ("servidor_home.py", "README.md", "web/index.html", "web/icono.svg", "web/icono.ico"):
        shutil.copy(f"{SRC}/{rel}", f"{src}/{rel}")
    cmd = [sys.executable, "/home/claude/build/prueba_constantes.py", src + "/servidor_home.py", "--version", version]
    subprocess.run(cmd + (["--romper", romper] if romper else []), check=True)
    open(f"{T}/nov.txt", "w", encoding="utf-8").write("\n".join(novedades))
    subprocess.run([sys.executable, "/home/claude/build/publicar.py", "--clave", KEY, "--app", src, "--sin-instalador",
                    "--salida", T + "/pub", "--novedades", T + "/nov.txt"], check=True, capture_output=True)
    shutil.rmtree(f"{PUB}/v{version}", ignore_errors=True)
    shutil.copytree(f"{T}/pub/{version}", f"{PUB}/v{version}")
    open(PUB + "/latest/TAG", "w").write(f"v{version}")


UI = {"on": False}


def ui_loop():          # la ventana «mirando»: pregunta el estado cada segundo como la interfaz real
    while True:
        if UI["on"]:
            api("state", timeout=3)
        time.sleep(1)


threading.Thread(target=ui_loop, daemon=True).start()

# ---------------------------------------------------------------- preparación
shutil.rmtree(T, ignore_errors=True)
os.makedirs(T)
shutil.rmtree(PUB, ignore_errors=True)
os.makedirs(PUB + "/latest")
if "_error" not in api("info", timeout=2):
    api("shutdown", {})
    wait(app_gone, 90)
shutil.rmtree(UPDDIR, ignore_errors=True)
r = subprocess.run([WINE, "Z:\\home\\claude\\build-prueba\\Instalar Servidor Home (prueba).exe", "/S"], env=ENV,
                   capture_output=True, timeout=240)
check("instala la versión de prueba 2.5.0", r.returncode == 0 and file_version() == "2.5.0" and reg_version() == "2.5.0",
      f"(registro: {reg_version()})")

# ---------------------------------------------------------------- A
UI["on"] = True
n0 = edge_lines()
check("la app abre con su ventana", launch() and wait(lambda: edge_lines() > n0, 30) and wait(app_window_open, 30))
api("state")
publish("2.5.1", ["Primera actualización automática"])
u = wait(lambda: (lambda u: u if u.get("status") == "lista" else None)(upd()), 90)
check("encuentra la versión 2.5.1 y la deja lista", bool(u) and u.get("version") == "2.5.1", str(u)[:160])
pid_before = [l.split()[0] for l in procs("servidor_home.py")]
n1 = edge_lines()
r = api("actualizar", {})
check("«Actualizar ahora»", r.get("ok") is True, str(r)[:160])
check("se reinicia en la versión 2.5.1", wait(lambda: version() == "2.5.1", 120), f"({version()})")
time.sleep(4)
pids = [l.split()[0] for l in procs("servidor_home.py")]
check("queda una sola app abierta, y es otro proceso", len(pids) == 1 and pids != pid_before, f"{pid_before} → {pids}")
check("archivos, instalado.txt y registro de Windows en 2.5.1",
      file_version() == "2.5.1" and "2.5.1" in open(APPDIR + "/instalado.txt", encoding="utf-8").read() and reg_version() == "2.5.1",
      f"(registro: {reg_version()})")
check("conserva la ventana (no abrió otra)", app_window_open() and edge_lines() == n1, f"(ventanas nuevas: {edge_lines() - n1})")
check("un solo ícono junto al reloj", "bandejas: 1" in helper("tray-count"), helper("tray-count"))
check("avisa que se actualizó", (upd().get("instalada") or {}).get("version") == "2.5.1")

# ---------------------------------------------------------------- B
UI["on"] = False
open(os.path.join(FAKE, "cerrar-ventana.txt"), "w").close()
check("al cerrar la ventana conservada, la app se cierra (la sigue vigilando)", wait(app_gone, 60))

# ---------------------------------------------------------------- C
check("abre de nuevo", launch())
publish("2.5.2", ["Se instala sola"])
check("sin nadie mirando, se instala sola la 2.5.2", wait(lambda: version() == "2.5.2", 150), f"({version()})")
check("registro en 2.5.2", wait(lambda: reg_version() == "2.5.2", 20), f"({reg_version()})")

# ---------------------------------------------------------------- D
UI["on"] = True
api("state")
publish("2.5.3", ["Al abrir"])
check("con la ventana abierta queda lista", bool(wait(lambda: upd().get("status") == "lista" and upd().get("version") == "2.5.3", 90)))
UI["on"] = False
api("shutdown", {})
check("Salir", wait(app_gone, 90))
n3 = edge_lines()
check("al abrirla instala la 2.5.3 antes de mostrar nada", launch() and wait(lambda: version() == "2.5.3", 120), f"({version()})")
check("y abre su ventana normal", wait(lambda: edge_lines() > n3, 30) and wait(app_window_open, 30))
check("una sola app", wait(lambda: len(procs("servidor_home.py")) == 1, 20), str(procs("servidor_home.py")))

# ---------------------------------------------------------------- E
publish("2.5.4", ["No abre"], romper="arranque")
f = wait(lambda: (upd().get("fallo") or {}).get("version") == "2.5.4" and upd(), 180)
check("la 2.5.4 no arranca: vuelve sola a la 2.5.3", bool(f) and version() == "2.5.3" and file_version() == "2.5.3"
      and reg_version() == "2.5.3", f"({version()}, archivos {file_version()}, registro {reg_version()})")

api("shutdown", {})
wait(app_gone, 90)
print(f"\n{ok} OK, {fail} fallas")
sys.exit(1 if fail else 0)
