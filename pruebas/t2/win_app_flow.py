#!/usr/bin/env python3
# Flujo completo de la app instalada bajo Wine con una ventana "Edge" falsa:
#  A) cerrar la ventana con un servidor encendido -> pregunta nativa -> No -> sigue funcionando
#  B) clic en el ícono de la bandeja -> vuelve a abrir la ventana
#  C) cerrar la ventana otra vez -> Sí -> apaga el servidor y la app termina
#  D) botón Salir del panel (/api/shutdown) -> apaga el servidor, cierra la ventana (WM_CLOSE) y termina
#  E) enlace externo (/api/abrir) desde la ventana
import json, os, subprocess, sys, time, urllib.request

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", WINEDEBUG="-all", WINEPREFIX="/home/claude/win/prefix2", DISPLAY=":99")
WINE = "/usr/lib/wine/wine64"
PY = "Z:/home/claude/win/py/python/python.exe"
FAKE = "/home/claude/build/fake"
ARGS_FILE = os.path.join(FAKE, "edge-args.txt")
SERVER = "serverfiles-1-0"
APPLOG = "/home/claude/win/prefix2/drive_c/users/root/AppData/Local/Servidor Home/servidor-home.log"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("OK  ", name, extra)
    else:
        fail += 1
        print("FAIL", name, extra)


def api(path, data=None, timeout=5):
    try:
        req = urllib.request.Request("http://127.0.0.1:8765/api/" + path,
                                     data=None if data is None else json.dumps(data).encode(), method="POST" if data is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        return json.loads(opener.open(req, timeout=timeout).read().decode())
    except Exception as e:
        return {"_error": str(e)}


def procs(word):
    out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout.splitlines()
    return [l for l in out if word in l and "win_app_flow" not in l and "grep" not in l]


def helper(*a, timeout=40):
    r = subprocess.run([WINE, PY, "-u", "Z:/home/claude/t2/win_helper.py", *a], env=ENV, capture_output=True,
                       text=True, timeout=timeout, input="")
    return r.stdout.strip()


def edge_lines():
    try:
        return len(open(ARGS_FILE, encoding="utf-8").read().splitlines())
    except FileNotFoundError:
        return 0


def wait(cond, limit, step=0.25):
    t = time.time()
    while time.time() - t < limit:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


def app_window_open():
    return "'Servidor Home'" in helper("windows") and "Chrome_WidgetWin" in helper("windows")


def launch():
    subprocess.Popen([WINE, "cmd", "/c", "Z:\\tmp\\lanzar.bat"], env=ENV, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wait(lambda: api("info").get("app") == "Servidor Home", 60)


def start_server():
    api(f"servers/{SERVER}/start", {})
    return wait(lambda: api(f"servers/{SERVER}").get("status") == "en línea", 120, 1)


def app_gone():
    return not procs("servidor_home.py") and "_error" in api("info", timeout=2)


# ---------------------------------------------------------------- preparación
for f in ("cerrar-ventana.txt",):
    try:
        os.remove(os.path.join(FAKE, f))
    except FileNotFoundError:
        pass
if "_error" not in api("info", timeout=2):
    api("shutdown", {})
    wait(app_gone, 60)

# ---------------------------------------------------------------- A
n0 = edge_lines()
t = time.time()
check("la app abre", launch(), f"({time.time() - t:.1f} s)")
check("se abre la ventana (Edge en modo app)", wait(lambda: edge_lines() > n0, 30))
args = open(ARGS_FILE, encoding="utf-8").read().splitlines()[-1]
check("argumentos de la ventana", "--app=http://127.0.0.1:8765" in args and "--hide-crash-restore-bubble" in args, args[:160])
check("ventana visible", wait(app_window_open, 20))
check("servidor encendido", start_server())
open(os.path.join(FAKE, "cerrar-ventana.txt"), "w").close()
t = time.time()
out = helper("msgbox", "no", "15")
print("     ", out.replace("\n", "\n      "))
check("al cerrar la ventana aparece la pregunta enseguida", "apareció" in out and float(out.split("esperé ")[1].split(" s")[0]) < 5)
check("la pregunta nombra el servidor", "Create Ultimate" in out and "¿Quieres apagarlo" in out)
time.sleep(3)
check("con No la app sigue abierta", api("info").get("app") == "Servidor Home")
check("con No el servidor sigue encendido", api(f"servers/{SERVER}").get("status") == "en línea")
check("no quedó ninguna ventana", not app_window_open())

# ---------------------------------------------------------------- B
n1 = edge_lines()
print("     ", helper("tray-open"))
check("clic en el ícono de la bandeja reabre la ventana", wait(lambda: edge_lines() > n1, 20))
check("ventana visible otra vez", wait(app_window_open, 20))
print("     segunda apertura (acceso directo) con la ventana abierta...")
n2 = edge_lines()
subprocess.run([WINE, "cmd", "/c", "Z:\\tmp\\lanzar.bat"], env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, timeout=60)
time.sleep(6)
check("la segunda apertura no abre otra ventana", edge_lines() == n2 and len(procs("servidor_home.py")) == 1,
      f"(ventanas nuevas: {edge_lines() - n2}, apps: {len(procs('servidor_home.py'))})")

# ---------------------------------------------------------------- E
r = api("abrir", {"url": "https://playit.gg/claim/prueba"})
check("enlace externo: la app lo manda al navegador predeterminado", r.get("ok") is True, str(r))
r = api("abrir", {"url": "file:///C:/Windows/notepad.exe"})
check("enlace externo: rechaza lo que no es http(s)", "_error" in r, str(r)[:80])
check("enlace externo: no abre ventanas de la app", edge_lines() == n2)

# ---------------------------------------------------------------- C
log_mark = len(open(APPLOG, encoding="utf-8", errors="replace").read())
open(os.path.join(FAKE, "cerrar-ventana.txt"), "w").close()
out = helper("msgbox", "si", "15")
print("     ", out.splitlines()[0] if out else out)
t = time.time()
check("con Sí la app se cierra", wait(app_gone, 90), f"({time.time() - t:.1f} s)")
new_log = open(APPLOG, encoding="utf-8", errors="replace").read()[log_mark:]
check("el servidor se apagó guardando el mundo", "Apagando Create Ultimate" in new_log, new_log.strip()[-160:].replace("\n", " | "))
check("no quedan procesos de Java", wait(lambda: not [l for l in procs("java.exe") if "defunct" not in l], 10), str(procs("java.exe")))

# ---------------------------------------------------------------- D
n3 = edge_lines()
check("la app abre de nuevo", launch())
check("ventana abierta", wait(lambda: edge_lines() > n3, 30) and wait(app_window_open, 20))
check("servidor encendido", start_server())
log_mark = len(open(APPLOG, encoding="utf-8", errors="replace").read())
t = time.time()
api("shutdown", {})
gone_window = wait(lambda: not app_window_open(), 90, 0.5)
t_window = time.time() - t
check("Salir: la app termina", wait(app_gone, 90), f"({time.time() - t:.1f} s)")
check("Salir: la ventana se cerró sola", gone_window, f"({t_window:.1f} s)")
check("Salir: no quedó el Edge falso", wait(lambda: not procs("fakewin.py") and not procs("msedge.exe"), 15))
check("Salir: no quedan procesos de Java", wait(lambda: not [l for l in procs("java.exe") if "defunct" not in l], 10), str(procs("java.exe")))
new_log = open(APPLOG, encoding="utf-8", errors="replace").read()[log_mark:]
check("Salir: el servidor se apagó guardando el mundo", "Apagando Create Ultimate" in new_log, new_log.strip()[-160:].replace("\n", " | "))
check("Salir: no quedó la pregunta abierta", "#32770" not in helper("windows"))

print(f"\n{ok} OK, {fail} fallas")
sys.exit(1 if fail else 0)
