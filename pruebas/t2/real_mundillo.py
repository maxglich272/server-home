# Prueba con el modpack REAL de «un mundillo» de Max (146 mods, su configuración y sus scripts de KubeJS) y
# Fabric Loader de verdad (las librerías 0.14.9 y 0.18.4 que SKLauncher tiene en su PC).
#  A) El servidor como quedó en el PC de Max (Fabric Loader nuevo, se cae con TinyVisitor): la app lo arregla sola.
#  B) Importar la instancia de nuevo desde cero: la app elige Fabric Loader 0.14 y enciende a la primera.
# El mock de Fabric entrega un arranque de verdad: 0.14.x usa las librerías 0.14.9; 0.15 o más nueva, las 0.18.4.
import os, sys, json, time, threading, shutil, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

R = "/home/claude/realtest"
MUND = "/mnt/user-data/uploads/Documents/servidor home/servidores/un-mundillo"
SKLOG = "/mnt/user-data/uploads/valhelsia-enhanced-vanilla"          # el latest.log de SKLauncher (Fabric Loader 0.14.9)
APP = "/home/claude/t2/appreal"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__"))
HOME = "/tmp/real-home"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["HOME"] = HOME

# como la API real de Fabric: solo la más nueva viene marcada «stable»
LOADERS = [{"version": "0.18.4", "stable": True}, {"version": "0.14.25", "stable": False}, {"version": "0.14.9", "stable": False}]
SERVED = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def j(self, o):
        b = json.dumps(o).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path
        if p == "/fabric/loader":
            return self.j(LOADERS)
        if p == "/fabric/installer":
            return self.j([{"version": "1.0.1", "stable": True}])
        if p == "/fabric/game":
            return self.j([{"version": "1.18.2", "stable": True}])
        if p.startswith("/fabric/loader/") and p.endswith("/server/jar"):
            lv = p.split("/")[4]
            SERVED.append(lv)
            b = open(f"{R}/launchers/" + ("launch-0.14.9.jar" if lv.startswith("0.14") else "launch-0.18.4.jar"), "rb").read()
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); return self.wfile.write(b)
        self.send_response(404); self.end_headers()


threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", 9913), H).serve_forever, daemon=True).start()
sys.path.insert(0, APP)
import servidor_home as sh  # noqa: E402
B = "http://127.0.0.1:9913"
sh.FABRIC_META = B + "/fabric"
sh.MOJANG_MANIFEST = B + "/no-existe.json"         # Java: la tabla de la app (1.18.2 → 17)
JAVA17 = "/usr/lib/jvm/java-17-openjdk-amd64/bin/java"
sh.system_java_candidates = lambda: [JAVA17]
FAILS = []


def ok(c, m):
    print(("OK   " if c else "FAIL ") + m, flush=True)
    if not c:
        FAILS.append(m)


def wait(fn, timeout, step=1.0):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timeout")


def copy_pack(dst):
    for sub in ("mods", "config", "kubejs"):
        shutil.copytree(os.path.join(R, "srv", sub), os.path.join(dst, sub))
    for root, _d, files in os.walk(dst):
        os.chmod(root, 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)


def final(s, timeout=900):
    return wait(lambda: s.status if s.status in ("en línea", "error") else None, timeout)


def shut(s):
    if s.running():
        s.send("stop")
        wait(lambda: not s.running(), 180)


# ------------------------------------------------------------------ A
print("== A) «un mundillo» como quedó en el PC de Max: Fabric Loader nuevo y Not Enough Crashes ==", flush=True)
sid = "un-mundillo"
d = os.path.join(sh.SERVERS_DIR, sid)
os.makedirs(d)
copy_pack(d)
shutil.copy(os.path.join(MUND, "server.properties"), d)
open(os.path.join(d, "eula.txt"), "w").write("eula=true\n")
shutil.copy(os.path.join(R, "srv", ".fabric", "server", "1.18.2-server.jar"), os.path.join(d, "server.jar"))
shutil.copy(os.path.join(R, "launchers", "launch-0.18.4.jar"), os.path.join(d, "fabric-server-launch.jar"))
meta = json.load(open(os.path.join(MUND, "servidor-home.json"), encoding="utf-8"))
meta.update({"loader_version": "0.18.4", "java_path": JAVA17, "java_major": 17, "ram_mb": 4096,
             "launch": {"jar": "fabric-server-launch.jar"}, "installed": True, "preinstalled": False})
json.dump(meta, open(os.path.join(d, "servidor-home.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
# importado con la 2.5.2: la carpeta del launcher solo está en el registro del servidor
with open(os.path.join(d, "servidor-home.log"), "w", encoding="utf-8") as fh:
    fh.write(f"2026-09-24 21:27:53 Copiando el modpack desde {SKLOG} ...\n")
sh.manager = sh.Manager()
s = sh.manager.servers[sid]
t0 = time.time()
s.start(user=True)
st = final(s)
con = "\n".join(l["s"] for l in s.console.since(0)[1]) + open(os.path.join(d, "servidor-home.log"), encoding="utf-8").read()
print(f"  estado: {st} en {int(time.time() - t0)} s; arreglos: {s.repairs_shown}", flush=True)
ok(st == "en línea", "encendió solo")
ok(s.meta.get("loader_version") == "0.14.9", f"con Fabric Loader 0.14.9 (la de SKLauncher): {s.meta.get('loader_version')}")
ok(s.repairs_shown[:1] == ["cambié Fabric Loader 0.18.4 por 0.14.9 (la misma con la que tu launcher abre este modpack)"],
   f"lo que hizo: {s.repairs_shown}")
ok("TinyVisitor" in con and "Done (" in con and "Loading Minecraft 1.18.2 with Fabric Loader 0.14.9" in con,
   "primero la caída de verdad, después Minecraft encendido de verdad con 0.14.9")
ok(SERVED == ["0.14.9"], f"el mock entregó Fabric 0.14.9: {SERVED}")
ok(os.path.isfile(os.path.join(d, "server.jar")), "Minecraft no se volvió a descargar")
shut(s)
st = s.status
s.start(user=True)
st = final(s)
ok(st == "en línea" and not s.repairs_shown, f"la segunda vez enciende directo: {st} {s.repairs_shown}")
shut(s)

# ------------------------------------------------------------------ B
print("\n== B) Importar la misma instancia desde cero (nunca abierta en el launcher) ==", flush=True)
inst = os.path.join(HOME, ".sklauncher", "instances", "valhelsia-enhanced-vanilla")
os.makedirs(inst)
copy_pack(inst)
# el servidor de prueba lanza Fabric con el arranque clásico: que sepa dónde está el Minecraft de 1.18.2
open(os.path.join(inst, "fabric-server-launcher.properties"), "w").write(
    f"serverJar={os.path.join(R, 'srv', '.fabric', 'server', '1.18.2-server.jar')}\n")
job = sh.ImportJob("carpeta", inst)
sh.manager.imports[job.id] = job
job.run_analysis()
a = job.analysis
print("  análisis:", {k: a.get(k) for k in ("type", "mc_version", "loader_version", "detected_from", "mods_count", "launcher")}, flush=True)
ok(a["type"] == "fabric" and a["mc_version"] == "1.18.2" and a["loader_version"] == "0.14.25", "elige Fabric Loader 0.14.25")
SERVED.clear()
s2 = sh.manager.confirm_import(job, {"eula": True, "autostart": True, "ram_mb": 4096,
                                     "disable": [c["file"] for c in a.get("client_only") or []]})
st = final(s2)
con = "\n".join(l["s"] for l in s2.console.since(0)[1])
print(f"  estado: {st}; arreglos: {s2.repairs_shown}; loader: {s2.meta.get('loader_version')}", flush=True)
ok(st == "en línea" and not s2.repairs_shown and "Done (" in con, "encendió a la primera, sin arreglos")
ok(SERVED == ["0.14.25"] and s2.meta["modpack"].get("path") == inst, f"instaló la 0.14.25 y guardó la carpeta del launcher: {SERVED}")
shut(s2)

print("\nLISTO" if not FAILS else f"\n{len(FAILS)} FALLAS: {FAILS}", flush=True)
sh.manager.shutdown_all()
os._exit(1 if FAILS else 0)
