# Pruebas de versiones: listas, validación, crear en cualquier versión, cambiar la versión de un servidor
# (respaldo, mundo nuevo, Java correcto, protección Log4Shell), importar eligiendo versión y diagnóstico Fabric.
import os, sys, json, time, threading, urllib.request, shutil, zipfile, glob
APP = "/home/claude/t2/appv"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__"))
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
import servidor_home as sh
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.ADOPTIUM_API = B + "/adoptium"; sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"; sh.MRPACK_HOSTS.add("127.0.0.1")
sh.MODRINTH_API = B + "/modrinth-api/v2"; sh.CURSEFORGE_API = B + "/cf-api/v1"
# El entorno de pruebas solo «tiene instalado» Java 21 (aunque el sistema tenga otros): así se prueba la descarga.
sh.system_java_candidates = lambda: ["/usr/lib/jvm/java-21-openjdk-amd64/bin/java"]
sh.manager = sh.Manager()
httpd = sh.ThreadingHTTPServer(("127.0.0.1", 8765), sh.Handler); sh.HTTPD = httpd
sh.manager.playit = sh.Playit()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = "http://127.0.0.1:8765/api/"
FAILS = []


def call(path, method="GET", body=None, raw=None):
    data = json.dumps(body).encode() if body is not None else raw
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait(fn, timeout=40, step=0.3):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timeout")


def ok(c, m):
    print(("OK   " if c else "FAIL ") + m)
    if not c:
        FAILS.append(m)


def srv(sid): return call("servers/" + sid)[1]
def meta(sid): return json.load(open(os.path.join(sh.SERVERS_DIR, sid, "servidor-home.json"), encoding="utf-8"))
def console(sid): return "\n".join(l["s"] for l in call(f"servers/{sid}/log?since=0")[1]["lines"])
def mock_state():
    req = urllib.request.Request(B + "/__state", data=b"{}", method="POST", headers={"Authorization": "Agent-Key a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"})
    return json.loads(urllib.request.urlopen(req).read())
def settle(sid, want=("detenido", "error", "en línea"), timeout=60):
    return wait(lambda: (lambda x: x if x["status"] in want and x["status"] != "instalando" else None)(srv(sid)), timeout)
def last_cmd(sid): return [l for l in console(sid).splitlines() if l.startswith("$ ")][-1]


print("== A) Listas de versiones ==")
st, v = call("versions?type=vanilla")
ok(v[0]["id"] == "26.3" and v[0].get("latest") and sum(1 for x in v if x.get("latest")) == 1, "vanilla: la primera es la más nueva (26.3)")
ok(not any(x.get("snapshot") for x in v) and "1.8.9" in [x["id"] for x in v], "sin snapshots e incluye versiones antiguas (1.8.9)")
st, v = call("versions?type=vanilla&snapshots=1")
ok(v[0]["id"] == "26.4-snapshot-2" and v[0].get("snapshot") and not v[0].get("latest") and v[1].get("latest"), "con snapshots: aparece 26.4-snapshot-2 marcada y 26.3 sigue siendo la más nueva")
st, v = call("versions?type=fabric")
ok(v[0]["id"] == "26.3" and v[0].get("latest") and all(not x.get("snapshot") for x in v), "fabric: estables, la más nueva marcada")

print("\n== B) Validación al crear ==")
st, r = call("servers", "POST", {"type": "vanilla", "mc_version": "1.99.9", "eula": True})
ok(st == 400 and "No encontré la versión 1.99.9" in r["error"], f"versión inexistente: {st} {r.get('error', '')[:70]}")
st, r = call("servers", "POST", {"type": "fabric", "mc_version": "1.21.8", "loader_version": "9.9.9", "eula": True})
ok(st == 400 and "No existe Fabric 9.9.9" in r["error"], f"loader inexistente: {st} {r.get('error', '')[:70]}")
ok(not os.listdir(sh.SERVERS_DIR) or all(not d.startswith("vanilla-1-99") for d in os.listdir(sh.SERVERS_DIR)), "no deja carpetas de servidores fallidos")

print("\n== C) Vanilla: crear en 26.3 y cambiar de versión ==")
st, s = call("servers", "POST", {"type": "vanilla", "mc_version": "26.3", "eula": True, "autostart": True, "ram_mb": 2048})
V = s["id"]
d = settle(V, ("en línea", "error"))
ok(d["status"] == "en línea", f"crea y enciende 26.3 ({d['status']})")
ok(25 in mock_state().get("java_downloads", []) and "/java/25/" in last_cmd(V), "descargó Java 25 para 26.3 y lo usa")
os.makedirs(os.path.join(sh.SERVERS_DIR, V, "world"), exist_ok=True)
open(os.path.join(sh.SERVERS_DIR, V, "world", "level.dat"), "w").write("mundo 26.3")
st, r = call(f"servers/{V}/version", "POST", {"mc_version": "1.21.11"})
ok(st == 400 and "Apaga el servidor" in r["error"], "no cambia con el servidor encendido")
call(f"servers/{V}/stop", "POST"); settle(V, ("detenido",))
st, r = call(f"servers/{V}/version", "POST", {"mc_version": "26.3"})
ok(st == 400 and "ya está en Minecraft 26.3" in r["error"], "avisa si ya está en esa versión")
st, r = call(f"servers/{V}/version", "POST", {"mc_version": "1.99"})
ok(st == 400 and "No encontré" in r["error"], "no cambia a una versión inexistente")
st, r = call(f"servers/{V}/version", "POST", {"mc_version": "1.21.11", "new_world": True})
ok(st == 200 and r["status"] == "instalando", "empieza el cambio a 1.21.11 con mundo nuevo")
d = settle(V, ("detenido", "error"))
m = meta(V)
ok(d["status"] == "detenido" and m["mc_version"] == "1.21.11" and m["installed"] and m["java_major"] == 21, f"quedó en 1.21.11 con Java 21 ({d['status']}, {d.get('error')})")
bk = sorted(os.listdir(os.path.join(sh.SERVERS_DIR, V, "respaldos")))
ok(len(bk) == 1 and "world/level.dat" in zipfile.ZipFile(os.path.join(sh.SERVERS_DIR, V, "respaldos", bk[0])).namelist(), "respaldó el mundo antes de cambiar")
old = glob.glob(os.path.join(sh.SERVERS_DIR, V, "mundos-anteriores", "26-3-*", "world", "level.dat"))
ok(len(old) == 1 and open(old[0]).read() == "mundo 26.3" and not os.path.exists(os.path.join(sh.SERVERS_DIR, V, "world")), "el mundo anterior quedó guardado aparte y empieza uno nuevo")
ok(os.path.exists(os.path.join(sh.SERVERS_DIR, V, "server.jar")), "descargó el server.jar de la nueva versión")
det = srv(V)
ok(det["version_history"] and det["version_history"][-1]["de"] == "Vanilla · Minecraft 26.3" and det["has_world"] is False, "guarda el historial de versiones")
ok(det["name"] == "Vanilla 1.21.11", f"el nombre automático sigue a la versión ({det['name']})")
print("   " + "\n   ".join(l for l in console(V).splitlines() if "Cambiando" in l or "Respaldo" in l or "mundo anterior" in l or "Listo:" in l))
call(f"servers/{V}/start", "POST"); d = settle(V)
ok(d["status"] == "en línea" and "/java/25/" not in last_cmd(V), "enciende en 1.21.11 con el Java del sistema (21)")
call(f"servers/{V}/stop", "POST"); settle(V, ("detenido",))
os.makedirs(os.path.join(sh.SERVERS_DIR, V, "world"), exist_ok=True)
open(os.path.join(sh.SERVERS_DIR, V, "world", "level.dat"), "w").write("mundo 1.21.11")
st, r = call(f"servers/{V}/version", "POST", {"mc_version": "1.8.9"})
d = settle(V, ("detenido", "error"))
ok(d["status"] == "detenido" and meta(V)["java_major"] == 8 and 8 in mock_state().get("java_downloads", []), "a 1.8.9: descarga Java 8")
ok(open(os.path.join(sh.SERVERS_DIR, V, "world", "level.dat")).read() == "mundo 1.21.11", "sin «mundo nuevo» conserva el mundo")
ok(len(os.listdir(os.path.join(sh.SERVERS_DIR, V, "respaldos"))) == 2, "otro respaldo antes del segundo cambio")
call(f"servers/{V}/start", "POST"); d = settle(V)
cmd = last_cmd(V)
ok(d["status"] == "en línea" and "/java/8/" in cmd and "-Dlog4j.configurationFile=log4j2_17-111.xml" in cmd, "1.8.9 enciende con Java 8 y la protección Log4Shell de Mojang")
ok(os.path.exists(os.path.join(sh.SERVERS_DIR, V, "log4j2_17-111.xml")), "escribió log4j2_17-111.xml")
call(f"servers/{V}/stop", "POST"); settle(V, ("detenido",))

print("\n== D) Fabric: cambiar Minecraft y loader ==")
st, s = call("servers", "POST", {"type": "fabric", "mc_version": "1.21.1", "eula": True, "autostart": False})
F = s["id"]; d = settle(F, ("detenido", "error"))
ok(d["status"] == "detenido" and meta(F)["loader_version"] == "0.16.14", "fabric 1.21.1 con el loader recomendado 0.16.14")
st, r = call(f"servers/{F}/version", "POST", {"mc_version": "1.21.8", "loader_version": "0.16.14"})
d = settle(F, ("detenido", "error")); m = meta(F)
ok(d["status"] == "detenido" and m["mc_version"] == "1.21.8" and m["loader_version"] == "0.16.14" and os.path.exists(os.path.join(sh.SERVERS_DIR, F, "fabric-server-launch.jar")), "pasa a 1.21.8")
st, r = call(f"servers/{F}/version", "POST", {"mc_version": "1.21.8", "loader_version": "0.17.0-beta"})
d = settle(F, ("detenido", "error"))
ok(d["status"] == "detenido" and meta(F)["loader_version"] == "0.17.0-beta", "cambia solo la versión del loader")
st, r = call(f"servers/{F}/version", "POST", {"mc_version": "1.21.8", "loader_version": "9.9"})
ok(st == 400 and "No existe Fabric 9.9" in r["error"], "rechaza un loader inexistente")
os.makedirs(os.path.join(sh.SERVERS_DIR, F, "world"), exist_ok=True)
open(os.path.join(sh.SERVERS_DIR, F, "world", "level.dat"), "w").write("mundo fabric")

print("\n== E) Importar eligiendo la versión ==")
st, j = call("import/upload?name=Fabulous.mrpack", "POST", raw=open("/home/claude/mock2/Fabulous.mrpack", "rb").read())
j = wait(lambda: (lambda x: x if x["status"] in ("listo", "error") else None)(call("import/" + j["id"])[1]))
st, r = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "autostart": False, "type": "fabric", "mc_version": "1.21.99"})
ok(st == 400 and "No encontré la versión 1.21.99" in r["error"], "no importa con una versión inexistente")
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "autostart": False, "type": "fabric", "mc_version": "1.21.8", "loader_version": "0.16.14"})
I = s["id"]; d = settle(I, ("detenido", "error")); m = meta(I)
ok(d["status"] == "detenido" and m["mc_version"] == "1.21.8" and m["loader_version"] == "0.16.14" and not m.get("preinstalled"), "importa en la versión elegida (1.21.8)")
ok(sorted(os.listdir(os.path.join(sh.SERVERS_DIR, I, "mods"))) == ["fabric-api.jar", "lithium.jar"], "con los mods del modpack")

print("\n== G) NeoForge: cambiar la versión del loader ==")
st, j = call("import/upload?name=ServerFiles-1.0.zip", "POST", raw=open("/home/claude/mock2/ServerFiles-1.0.zip", "rb").read())
j = wait(lambda: (lambda x: x if x["status"] in ("listo", "error") else None)(call("import/" + j["id"])[1]))
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "autostart": False, "name": "Neo", "disable": ["badclient.jar"]})
N = s["id"]; d = settle(N, ("detenido", "error")); root = os.path.join(sh.SERVERS_DIR, N)
ok(d["status"] == "detenido" and os.path.isdir(os.path.join(root, "libraries", "net", "neoforged", "neoforge", "21.1.77")), "NeoForge 21.1.77 instalado")
st, r = call(f"servers/{N}/version", "POST", {"mc_version": "1.21.1", "loader_version": "21.1.66"})
d = settle(N, ("detenido", "error")); m = meta(N)
ok(d["status"] == "detenido" and m["loader_version"] == "21.1.66" and "21.1.66" in " ".join(m["launch"].get("args", [])), f"pasa a NeoForge 21.1.66: {m.get('launch')}")
ok(not os.path.exists(os.path.join(root, "libraries", "net", "neoforged", "neoforge", "21.1.77")) and os.path.exists(os.path.join(root, "mods", "create-1.21.1-6.0.jar"))
   and os.path.exists(os.path.join(root, "mods", "badclient.jar.disabled")), "quita la versión anterior del loader y conserva los mods (y los desactivados)")
call(f"servers/{N}/start", "POST"); d = settle(N)
ok(d["status"] == "en línea", "enciende con el nuevo loader")
call(f"servers/{N}/stop", "POST"); settle(N, ("detenido",))

print("\n== H) Varios mods del jugador seguidos: se desactivan solos, uno tras otro ==")
st, s = call("servers", "POST", {"type": "fabric", "mc_version": "1.21.8", "eula": True, "autostart": False, "name": "Cliente"})
C = s["id"]; settle(C, ("detenido", "error"))
mdir = os.path.join(sh.SERVERS_DIR, C, "mods"); os.makedirs(mdir, exist_ok=True)
for mid in ("clientmod1", "clientmod2", "clientmod3"):
    with zipfile.ZipFile(os.path.join(mdir, mid + ".jar"), "w") as z:
        z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mid, "version": "1", "environment": "*"}))
call(f"servers/{C}/start", "POST"); d = settle(C, ("error", "en línea"), 90)
ok(d["status"] == "en línea" and sorted(os.listdir(mdir)) == ["clientmod1.jar.disabled", "clientmod2.jar.disabled", "clientmod3.jar.disabled"],
   f"desactivó los tres y encendió sin tocar nada: {sorted(os.listdir(mdir))}")
ok(d["repairs"] == [f"desactivé clientmod{i}.jar (es solo del jugador)" for i in (1, 2, 3)], f"y lo cuenta: {d['repairs']}")
log = console(C)
ok(all(f"Arreglo automático: Desactivando clientmod{i} (es solo del jugador)" in log for i in (1, 2, 3)), "cada paso queda en la consola")
call(f"servers/{C}/stop", "POST"); settle(C, ("detenido",))
with zipfile.ZipFile("/tmp/clientmod4.jar", "w") as z:          # para la prueba de interfaz
    z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "clientmod4", "version": "1", "environment": "*"}))

print("\n== F) Diagnóstico: mod de cliente en Fabric (log real del PC de Max) ==")
mods = os.path.join("/tmp", "diag-mods"); shutil.rmtree(mods, ignore_errors=True); os.makedirs(mods)
with zipfile.ZipFile(os.path.join(mods, "enchantment-glint-outline-1.21.11-3.2.jar"), "w") as z:
    z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "enchant-outline", "version": "3.2", "environment": "*"}))
with zipfile.ZipFile(os.path.join(mods, "fabric-api.jar"), "w") as z:
    z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "fabric-api", "version": "1", "environment": "*"}))
lines = open("/mnt/user-data/uploads/Documents/servidor home/servidores/prueba/logs/latest.log", encoding="utf-8", errors="replace").read().splitlines()
h = sh.diagnose_log(lines[-800:], mods)
ok(h and h.get("action", {}).get("file") == "enchantment-glint-outline-1.21.11-3.2.jar", f"propone desactivar enchant-outline: {h}")

print("\nLISTO" if not FAILS else f"\n{len(FAILS)} FALLAS: {FAILS}")
open("/home/claude/t2/ready", "w").write("1")
if os.environ.get("HARNESS_EXIT") == "1":
    sh.manager.shutdown_all(); httpd.shutdown(); os._exit(1 if FAILS else 0)
while True:
    time.sleep(1)
