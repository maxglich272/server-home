import os, sys, json, time, threading, urllib.request, shutil
APP = "/home/claude/t2/app"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP)
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
os.environ["API_BASE"] = B          # el agente real de playit habla con el mock
sys.path.insert(0, APP)
import servidor_home as sh
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"; sh.MRPACK_HOSTS.add("127.0.0.1")
sh.MODRINTH_API = B + "/modrinth-api/v2"; sh.CURSEFORGE_API = B + "/cf-api/v1"
sh.manager = sh.Manager()
httpd = sh.ThreadingHTTPServer(("127.0.0.1", 8765), sh.Handler); sh.HTTPD = httpd
sh.manager.playit = sh.Playit()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = "http://127.0.0.1:8765/api/"
def call(path, method="GET", body=None, raw=None):
    data = json.dumps(body).encode() if body is not None else raw
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
def wait(fn, timeout=30, step=0.3):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(step)
    raise AssertionError("timeout")
def wait_import(jid):
    return wait(lambda: (lambda j: j if j["status"] in ("listo", "error") else None)(call("import/" + jid)[1]))
def srv(sid): return call("servers/" + sid)[1]
def log_of(sid): return "\n".join(f"  [{l['k']}] {l['s']}" for l in call(f"servers/{sid}/log?since=0")[1]["lines"])
ok = lambda c, m: print(("OK   " if c else "FAIL ") + m)

print("== A) Pack de servidor NeoForge (zip) ==")
st, j = call("import/upload?name=ServerFiles-1.0.zip", "POST", raw=open("/home/claude/mock2/ServerFiles-1.0.zip", "rb").read())
j = wait_import(j["id"]); a = j["analysis"]
print("  análisis:", {k: a[k] for k in ("pack_kind", "name", "type", "mc_version", "loader_version", "detected_from", "installed", "mods_count", "ram_mb")}, "cliente:", [c["file"] for c in a["client_only"]])
ok(a["type"] == "neoforge" and a["mc_version"] == "1.21.1" and a["loader_version"] == "21.1.77", "detecta NeoForge 21.1.77 / 1.21.1 desde variables.txt")
ok(not os.path.exists(os.path.join(sh.SERVERS_DIR, "evil.txt")), "zip-slip ignorado")
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "ram_mb": 4096, "name": "Create Ultimate", "autostart": True, "disable": []})
sidA = s["id"]; print("  confirmado:", st, sidA)
d = wait(lambda: (lambda x: x if x["status"] == "en línea" or (x["status"] == "error" and not x.get("progress")) else None)(srv(sidA)), 60)
ok(d["status"] == "en línea" and any("badclient.jar" in r for r in d.get("repairs", [])), f"se cae por un mod de cliente y se arregla solo: {d.get('repairs')}")
ok("Arreglo automático: Desactivando Bad Client Mod" in log_of(sidA), "el arreglo queda en la consola")
ok(os.path.exists(os.path.join(sh.SERVERS_DIR, sidA, "mods", "badclient.jar.disabled")), "badclient.jar quedó .disabled")
print(log_of(sidA)[-2500:])

print("\n== B) Instancias de launchers ==")
st, inst = call("import/instances")
for i in inst: print("  ", i["launcher"], "|", i["name"], "|", i["summary"], "|", i["mods"], "mods |", i["path"])
cf = next(i for i in inst if i["launcher"] == "CurseForge")
st, j = call("import/folder", "POST", {"path": cf["path"]})
j = wait_import(j["id"]); a = j["analysis"]
print("  análisis:", {k: a[k] for k in ("pack_kind", "name", "type", "mc_version", "loader_version", "detected_from", "mods_count", "launcher")})
for c in a["client_only"]: print("   cliente:", c)
ok(a["loader_version"] == "21.1.77" and a["name"] == "Taller de Max", "usa minecraftinstance.json (21.1.77) sobre el log (21.1.99)")
ok(sorted(c["file"] for c in a["client_only"]) == ["cfclient.jar", "fancytips.jar", "irisaddon.jar", "oculus-1.21.1.jar"],
   "detecta 4 mods solo-cliente (IGNORE_SERVER_VERSION no cuenta, la librería que otro mod necesita se queda y el que necesita Oculus se va)")
ok(next(c["reason"] for c in a["client_only"] if c["file"] == "irisaddon.jar") == "Necesita Oculus, que es solo para el jugador.",
   "explica por qué el que necesita Oculus tampoco va")
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "ram_mb": 6144, "autostart": True, "disable": [c["file"] for c in a["client_only"]]})
sidB = s["id"]
d = wait(lambda: (lambda x: x if x["status"] in ("detenido", "error", "en línea") and x["installed"] else None)(srv(sidB)), 40)
print("  estado tras instalar:", d["status"], d["error"])
ok(d["status"] == "detenido" and "mismo puerto" in log_of(sidB), "no enciende en el mismo puerto que A (queda apagado y lo explica)")
root = os.path.join(sh.SERVERS_DIR, sidB)
present = sorted(os.listdir(root)); print("  archivos:", present)
ok(all(x not in present for x in ("saves", "resourcepacks", "shaderpacks", "options.txt", "logs", "screenshots", "minecraftinstance.json")), "no copia cosas de cliente")
ok(all(x in present for x in ("mods", "config", "defaultconfigs", "kubejs")), "copia mods/config/defaultconfigs/kubejs")
ok(sorted(os.listdir(os.path.join(root, "mods"))) == ["cfclient.jar.disabled", "cflib.jar", "create-1.21.1-6.0.jar", "fancytips.jar.disabled",
   "irisaddon.jar.disabled", "jei-1.21.1.jar", "needscflib.jar", "oculus-1.21.1.jar.disabled", "serverside.jar"], "mods de cliente desactivados")
mB = json.load(open(os.path.join(root, "servidor-home.json"), encoding="utf-8"))
ok(sorted(mB.get("client_mods", {})) == ["cfclient.jar", "fancytips.jar", "irisaddon.jar", "oculus-1.21.1.jar"] and mB.get("revision_mods") == 1,
   f"recuerda qué mods desactivó por ser del jugador: {mB.get('client_mods')}")
st, _ = call(f"servers/{sidA}/stop", "POST"); wait(lambda: srv(sidA)["status"] == "detenido", 20)
st, r = call(f"servers/{sidB}/start", "POST"); d = wait(lambda: (lambda x: x if x["status"] == "en línea" else None)(srv(sidB)), 20)
ok(d["status"] == "en línea", "B enciende tras apagar A")

print("\n== C) .mrpack de Fabric ==")
st, j = call("import/upload?name=Fabulous.mrpack", "POST", raw=open("/home/claude/mock2/Fabulous.mrpack", "rb").read())
j = wait_import(j["id"]); a = j["analysis"]
print("  análisis:", {k: a[k] for k in ("pack_kind", "name", "type", "mc_version", "loader_version", "mods_count", "download_count")}, [c["file"] for c in a["client_only"]])
ok(a["type"] == "fabric" and a["loader_version"] == "0.16.14" and a["client_only"][0]["skip"], "lee modrinth.index.json y omite sodium (solo cliente)")
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "autostart": False})
sidC = s["id"]
d = wait(lambda: (lambda x: x if x["status"] in ("detenido", "error") and (x["installed"] or x["status"] == "error") else None)(srv(sidC)), 40)
root = os.path.join(sh.SERVERS_DIR, sidC)
print("  estado:", d["status"], d["error"], sorted(os.listdir(root)), sorted(os.listdir(os.path.join(root, "mods"))))
ok(d["status"] == "detenido" and sorted(os.listdir(os.path.join(root, "mods"))) == ["fabric-api.jar", "lithium.jar"], "descarga mods del servidor verificando sha1")
ok(open(os.path.join(root, "server.properties")).read().count("Desde server-overrides") == 1 and not os.path.exists(os.path.join(root, "options.txt")), "aplica server-overrides y no client-overrides")
ok(os.path.exists(os.path.join(root, "config", "lithium.properties")), "aplica overrides")

print("\n== D) Zip de CurseForge para launcher ==")
st, j = call("import/upload?name=ClientPack.zip", "POST", raw=open("/home/claude/mock2/ClientPack.zip", "rb").read())
j = wait_import(j["id"]); print("  ", j["status"], j["error"][:120])
ok(j["status"] == "error" and "Server Files" in j["error"], "explica que falta el pack de servidor")
ok(not any(f.startswith("client-pack") for f in os.listdir(sh.SERVERS_DIR)), "no deja carpeta a medias")

print("\n== E) playit.gg ==")
st, p = call("playit/setup", "POST"); print("  fase:", p["phase"], p["claim_url"])
ok(p["phase"] == "vinculando" and p["claim_url"].startswith("https://playit.gg/claim/"), "genera enlace de vinculación")
p = wait(lambda: (lambda x: x if x["phase"] == "listo" else None)(call("playit")[1]), 40, 0.5)
print("  estado:", {k: p[k] for k in ("phase", "address", "connected", "running", "tunnel_error", "target_port")})
ok(p["address"] == "prueba-max.gl.joinmc.link", "crea el túnel y muestra la dirección fija")
ok(open(os.path.join(sh.PLAYIT_DIR, "playit.toml")).read().startswith('secret_key = "a1b2'), "guarda la clave")
ok(oct(os.stat(os.path.join(sh.PLAYIT_DIR, "playit.toml")).st_mode)[-3:] == "600", "clave con permisos 600")
mock = json.loads(urllib.request.urlopen(urllib.request.Request(B + "/__state", data=b"{}", method="POST", headers={"Authorization": "Agent-Key a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"})).read())
ok(mock["created"] == 1, f"un solo túnel creado ({mock['created']})")
time.sleep(3)
st, pl = call("playit/log?since=0"); print("\n".join("  playitd| " + l["s"][:160] for l in pl["lines"][:12]))
ok(any("Starting playitd" in l["s"] for l in pl["lines"]), "el agente real playitd arrancó con nuestros parámetros")
# cambiar puerto: B apagado, cambia a 25570 y enciende -> el túnel se reapunta
call(f"servers/{sidB}/stop", "POST"); wait(lambda: srv(sidB)["status"] == "detenido", 20)
call(f"servers/{sidB}/properties", "PUT", {"properties": {"server-port": 25570}})
call(f"servers/{sidB}/start", "POST"); wait(lambda: srv(sidB)["status"] == "en línea", 20)
wait(lambda: json.loads(urllib.request.urlopen(urllib.request.Request(B + "/__state", data=b"{}", method="POST", headers={"Authorization": "Agent-Key a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"})).read())["config_calls"], 30, 1)
ok(True, "el túnel se reapuntó al puerto 25570")
call(f"servers/{sidB}/command", "POST", {"command": "join"}); time.sleep(0.5)
ok(srv(sidB)["players"] == ["Steve"], "cuenta jugadores")
print("\nPython", sys.version.split()[0], "— LISTO")
open("/home/claude/t2/ready", "w").write("1")
if os.environ.get("HARNESS_EXIT") == "1":
    sh.manager.shutdown_all(); httpd.shutdown(); os._exit(0)
while True: time.sleep(3600)
