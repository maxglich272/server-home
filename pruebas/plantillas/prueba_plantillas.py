"""Pruebas de las plantillas (servidores que no son de Minecraft). Solo Linux, sin internet ni mock:
    python3 pruebas/plantillas/prueba_plantillas.py
Copia la app a una carpeta temporal (modo portable), sirve un paquete falso por HTTP local y lo instala, enciende y
apaga por la API como lo haría la interfaz."""
import hashlib
import http.server
import io
import json
import os
import shutil
import socket
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
TMP = tempfile.mkdtemp(prefix="plantillas-")
APP = os.path.join(TMP, "app")
shutil.copytree(os.path.join(RAIZ, "servidor-home"), APP)
sys.path.insert(0, APP)
import servidor_home as sh  # noqa: E402

FALLOS = []


def ok(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        FALLOS.append(msg)


def libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---- paquetes falsos servidos por HTTP ----
WWW = os.path.join(TMP, "www")
os.makedirs(WWW)
falso = open(os.path.join(AQUI, "servidor_falso.py"), "rb").read()
with tarfile.open(os.path.join(WWW, "falso-1.0.tar.gz"), "w:gz") as t:
    info = tarfile.TarInfo("falso-1.0/servidor_falso.py")
    info.size, info.mode = len(falso), 0o644
    t.addfile(info, io.BytesIO(falso))
    link = tarfile.TarInfo("falso-1.0/enlace")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    t.addfile(link)
with zipfile.ZipFile(os.path.join(WWW, "falso-1.0.zip"), "w") as z:
    z.writestr("falso-1.0/servidor_falso.py", falso)
    z.writestr("falso-1.0/../../escapado.txt", "no debería salir")


def sha(name):
    return hashlib.sha256(open(os.path.join(WWW, name), "rb").read()).hexdigest()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WWW, **k)

    def log_message(self, *a):
        pass


web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=web.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{web.server_address[1]}/"


def plantilla(id_, archivo="falso-1.0.tar.gz", stop=None, ready=None, extra_cfg=""):
    return {
        "meta": {"schema": 1, "id": id_, "name": f"Falso {id_}", "category": "juego", "version": "1.0"},
        "variables": [{"key": "mundo", "label": "Nombre del mundo", "type": "text", "default": "Tierra"},
                      {"key": "dificultad", "label": "Dificultad", "type": "choice", "default": "2",
                       "options": {"1": "Fácil", "2": "Normal"}}],
        "install": {"kind": "archive", "url": BASE + archivo, "sha256": sha(archivo), "strip": "falso-1.0"},
        "files": [{"path": "config.txt",
                   "content": "mundo={{ mundo }}\ndificultad={{ dificultad }}\npuerto={{ port_juego }}\n" + extra_cfg}],
        "run": {"command": [sys.executable, "-u", "servidor_falso.py", "--config", "config.txt"]},
        "stop": stop or {"stdin": "salir", "timeout_s": 10},
        "ready": ready or {"log": r"listo en el puerto \d+"},
        "ports": [{"name": "juego", "port": 7777, "protocol": "tcp", "expose": "playit"}],
        "resources": {"ram_mb": 512},
        "backup": {"paths": ["mundos"], "before": {"stdin": "guardar", "wait_s": 1}},
    }


print("== Revisión de plantillas ==")


def falla(data, texto):
    try:
        sh.Template(data)
    except sh.TemplateError as e:
        return texto in str(e)
    return False


base = plantilla("revision")
ok(sh.Template(base).id == "revision", "una plantilla correcta se acepta")
ok(falla({**base, "meta": {**base["meta"], "schema": 2}}, "Esquema"), "rechaza un esquema desconocido")
ok(falla({**base, "install": {**base["install"], "sha256": ""}}, "sha256"), "exige sha256 para descargar")
ok(falla({**base, "ports": [{"name": "juego", "port": 70000}]}, "65535"), "rechaza puertos fuera de rango")
ok(falla({**base, "files": [{"path": "../fuera.txt", "content": "x"}]}, "sale de la carpeta"),
   "rechaza archivos fuera de la carpeta del servidor")
ok(falla({**base, "run": {"command": "servidor --puerto 1"}}, "lista de textos"), "el comando tiene que ser una lista")
ok(falla({**base, "ready": {"port": "otro"}}, "no está en [[ports]]"), "ready.port tiene que ser un puerto declarado")
ok(falla({**base, "variables": [{"key": "port_x"}]}, "reservada"), "las claves port_* están reservadas")
try:
    sh.render_template_text("hola {{ nadie }}", {"os": "linux"})
    ok(False, "una variable desconocida falla al renderizar")
except sh.TemplateError:
    ok(True, "una variable desconocida falla al renderizar")
t = sh.Template(base)
v = t.values({"mundo": "Marte"}, {"juego": 9000})
ok(v["mundo"] == "Marte" and v["dificultad"] == "2" and v["port_juego"] == 9000 and v["os"] == "linux",
   f"valores con respuestas, valores por defecto y puertos: {v}")
for malo, msg in (({"dificultad": "9"}, "opción inválida"), ({"mundo": "a\nb"}, "salto de línea")):
    try:
        t.values(malo)
        ok(False, f"rechaza {msg}")
    except ValueError:
        ok(True, f"rechaza {msg}")
mc = sh.TEMPLATES["minecraft-java"]
ok(mc.handler == "minecraft" and mc.requires_eula, "Minecraft Java viene incluida como plantilla con handler minecraft")

if sys.version_info >= (3, 11):
    toml = '''
[meta]
schema = 1
id = "terraria"
name = "Terraria"
category = "juego"

[[variables]]
key = "world_name"
default = "MiMundo"

[install]
kind = "none"

[run]
linux = ["./TerrariaServer.bin.x86_64", "-port", "{{ port_juego }}"]
windows = ["TerrariaServer.exe", "-port", "{{ port_juego }}"]

[stop]
stdin = "exit"

[[ports]]
name = "juego"
port = 7777
'''
    tt = sh.parse_template(toml)
    ok(tt.run["command"][0] == "./TerrariaServer.bin.x86_64" and tt.stop["stdin"] == "exit",
       "lee un template.toml y elige el comando de este sistema")
    try:
        sh.parse_template("[meta\nschema=1")
        ok(False, "TOML roto da un error claro")
    except sh.TemplateError as e:
        ok("TOML" in str(e), "TOML roto da un error claro")

print("\n== Servidores existentes ==")
os.makedirs(os.path.join(sh.SERVERS_DIR, "viejo"))
with open(os.path.join(sh.SERVERS_DIR, "viejo", sh.META_FILE), "w") as f:
    json.dump({"name": "Viejo", "type": "vanilla", "mc_version": "1.21.1", "installed": True}, f)

P1, P2, P3, P4 = libre(), libre(), libre(), libre()
sh.TEMPLATES.update(sh.load_templates([
    plantilla("falso"),
    plantilla("falso-zip", archivo="falso-1.0.zip", stop={"signal": "term", "timeout_s": 10},
              ready={"port": "juego"}, extra_cfg="demora=1\n"),
    plantilla("terco", extra_cfg="terco=1\n", stop={"stdin": "salir", "timeout_s": 2}),
    plantilla("caer", extra_cfg="caer=1\n"),
]))
sh.manager = sh.Manager()
viejo = sh.manager.get("viejo")
ok(isinstance(viejo, sh.ServerInstance), "un servidor de antes sigue siendo de Minecraft")
ok(json.load(open(os.path.join(sh.SERVERS_DIR, "viejo", sh.META_FILE)))["template"] == "minecraft-java",
   "se le anota la plantilla minecraft-java")

httpd = sh.ThreadingHTTPServer(("127.0.0.1", 0), sh.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = f"http://127.0.0.1:{httpd.server_address[1]}/api/"


def call(path, method="GET", body=None):
    req = urllib.request.Request(A + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait(fn, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return None


def status(sid):
    return call("servers/" + sid)[1]["status"]


def log_of(sid):
    return "\n".join(l["s"] for l in call(f"servers/{sid}/log?since=0")[1]["lines"])


st, lista = call("templates")
ok(st == 200 and {"minecraft-java", "falso"} <= {t["id"] for t in lista}, "GET /api/templates lista las plantillas")

print("\n== Instalar, encender y apagar (consola) ==")
st, s = call("servers", "POST", {"template": "falso", "name": "Mi falso", "values": {"mundo": "Marte"},
                                 "ports": {"juego": P1}})
sid = s["id"]
ok(st == 201 and s["type_label"] == "Falso falso", f"crea el servidor desde la plantilla ({st})")
ok(wait(lambda: status(sid) == "detenido"), f"se instala solo: {status(sid)}")
cfg = open(os.path.join(sh.SERVERS_DIR, sid, "config.txt")).read()
ok(f"mundo=Marte\ndificultad=2\npuerto={P1}" in cfg, "escribe config.txt con los valores del formulario")
ok(not os.path.exists(os.path.join(sh.SERVERS_DIR, sid, "enlace")), "no extrae enlaces simbólicos del .tar")
st, _ = call(f"servers/{sid}/start", "POST", {})
ok(wait(lambda: status(sid) == "en línea"), "enciende y queda en línea al ver la línea de listo")
with socket.create_connection(("127.0.0.1", P1), timeout=3):
    ok(True, "el servidor escucha en su puerto")
st, _ = call(f"servers/{sid}/command", "POST", {"command": "hola"})
ok(wait(lambda: "recibido: hola" in log_of(sid)), "manda comandos por la consola")
st, e = call(f"servers/{sid}/players")
ok(st == 400 and "Minecraft" in e["error"], "las opciones de Minecraft responden con un error claro")
st, s2 = call("servers", "POST", {"template": "falso", "name": "Otro", "ports": {"juego": P1}})
wait(lambda: status(s2["id"]) == "detenido")
st, e = call(f"servers/{s2['id']}/start", "POST", {})
ok(st == 400 and "Mi falso" in e["error"], f"no enciende dos servidores en el mismo puerto: {e.get('error')}")
call(f"servers/{sid}/stop", "POST", {})
ok(wait(lambda: status(sid) == "detenido"), "se apaga con el comando de la plantilla")
ok("Guardando y saliendo" in log_of(sid), "el servidor alcanzó a guardar")
ok(os.path.exists(os.path.join(sh.TEMPLATE_DOWNLOADS, "falso")), "la descarga queda guardada para reutilizarla")
call(f"servers/{s2['id']}/install", "POST", {})
ok(wait(lambda: "Uso la descarga guardada" in log_of(s2["id"])), "reinstalar usa la descarga guardada")

print("\n== Zip, listo por puerto y apagado por señal ==")
st, s = call("servers", "POST", {"template": "falso-zip", "ports": {"juego": P2}, "autostart": True})
zid = s["id"]
ok(wait(lambda: status(zid) == "en línea"), "con autostart se instala y enciende; listo cuando abre el puerto")
ok(not os.path.exists(os.path.join(sh.SERVERS_DIR, "escapado.txt"))
   and not os.path.exists(os.path.join(sh.DATA_DIR, "escapado.txt")), "ignora rutas que salen del zip")
call(f"servers/{zid}/restart", "POST", {})
ok(wait(lambda: "Apagando por señal" in log_of(zid)) and wait(lambda: status(zid) == "en línea"),
   "reiniciar apaga con SIGTERM y vuelve a encender")
call(f"servers/{zid}/stop", "POST", {})
ok(wait(lambda: status(zid) == "detenido"), "se apaga por señal")

print("\n== Servidor que no se apaga y servidor que se cae ==")
st, s = call("servers", "POST", {"template": "terco", "ports": {"juego": P3}, "autostart": True})
tid = s["id"]
ok(wait(lambda: status(tid) == "en línea"), "el servidor terco enciende")
call(f"servers/{tid}/stop", "POST", {})
ok(wait(lambda: status(tid) == "detenido", 10) and "a la fuerza" in log_of(tid),
   "si no se apaga a tiempo se cierra a la fuerza")
st, s = call("servers", "POST", {"template": "caer", "ports": {"juego": P4}, "autostart": True})
cid = s["id"]
ok(wait(lambda: status(cid) == "error"), "si se cae queda en error")
ok("código 3" in call("servers/" + cid)[1]["error"], "el error dice el código de salida")

print("\n== Puerto ocupado por otro programa ==")
ocupa = socket.socket()
ocupa.bind(("0.0.0.0", P1))
ocupa.listen()
st, e = call(f"servers/{sid}/start", "POST", {})
ok(st == 400 and str(P1) in e["error"], f"avisa si otro programa usa el puerto: {e.get('error')}")
ocupa.close()

print("\n== Cerrar la app ==")
call(f"servers/{sid}/start", "POST", {})
wait(lambda: status(sid) == "en línea")
sh.manager.shutdown_all()
ok(not sh.manager.get(sid).running(), "cerrar la app apaga los servidores de plantilla")

httpd.shutdown()
web.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'TODO BIEN' if not FALLOS else f'{len(FALLOS)} FALLAS'}")
sys.exit(1 if FALLOS else 0)
