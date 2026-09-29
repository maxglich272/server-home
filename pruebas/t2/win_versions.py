# Cambio de versión en Windows (Wine): Vanilla con mundo nuevo, NeoForge con run.bat nuevo, Fabric.
import os, sys, json, time, threading, urllib.request, shutil, zipfile, glob, tempfile
APP = "Z:/home/claude/wt/app"
os.environ["USERPROFILE"] = r"Z:\home\claude\mock2\winhome"
os.environ["APPDATA"] = r"Z:\home\claude\mock2\winhome\AppData\Roaming"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
def _copy2(src, dst, *, follow_symlinks=True):
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst); shutil.copystat(src, dst); return dst
shutil.copy2 = _copy2
import servidor_home as sh
assert sh.IS_WINDOWS
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.MRPACK_HOSTS.add("127.0.0.1")
sh.manager = sh.Manager()
httpd = sh.AppHTTPServer(("127.0.0.1", 8765), sh.Handler); sh.HTTPD = httpd
sh.manager.playit = sh.Playit()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = "http://127.0.0.1:8765/api/"
FAILS = []
def call(path, method="GET", body=None, raw=None):
    data = json.dumps(body).encode() if body is not None else raw
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
def wait(fn, timeout=120, step=0.5):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(step)
    raise AssertionError("timeout")
def ok(c, m):
    print(("OK   " if c else "FAIL ") + m)
    if not c: FAILS.append(m)
def srv(sid): return call("servers/" + sid)[1]
def meta(sid): return json.load(open(os.path.join(sh.SERVERS_DIR, sid, "servidor-home.json"), encoding="utf-8"))
def console(sid): return "\n".join(l["s"] for l in call(f"servers/{sid}/log?since=0")[1]["lines"])
def settle(sid, want=("detenido", "error", "en línea")):
    return wait(lambda: (lambda x: x if x["status"] in want and x["status"] != "instalando" else None)(srv(sid)))
print("Python", sys.version.split()[0], sys.platform)
st, v = call("versions?type=vanilla")
ok(v[0]["id"] == "26.3" and v[0].get("latest"), "lista de versiones con la más nueva marcada")

print("== Vanilla ==")
st, s = call("servers", "POST", {"type": "vanilla", "mc_version": "1.21.8", "eula": True, "autostart": True, "ram_mb": 1024})
V = s["id"]; d = settle(V, ("en línea", "error"))
ok(d["status"] == "en línea", f"vanilla 1.21.8 enciende ({d['status']} {d.get('error')})")
os.makedirs(os.path.join(sh.SERVERS_DIR, V, "world"), exist_ok=True)
open(os.path.join(sh.SERVERS_DIR, V, "world", "level.dat"), "w").write("mundo 1.21.8")
call(f"servers/{V}/stop", "POST"); settle(V, ("detenido",))
st, r = call(f"servers/{V}/version", "POST", {"mc_version": "1.21.1", "new_world": True})
d = settle(V, ("detenido", "error")); m = meta(V)
ok(d["status"] == "detenido" and m["mc_version"] == "1.21.1" and d["name"] == "Vanilla 1.21.1", f"pasa a 1.21.1 y el nombre lo sigue ({d['status']} {d.get('error')} {d['name']})")
old = glob.glob(os.path.join(sh.SERVERS_DIR, V, "mundos-anteriores", "1-21-8-*", "world", "level.dat"))
ok(len(old) == 1 and len(os.listdir(os.path.join(sh.SERVERS_DIR, V, "respaldos"))) == 1, "respaldo + mundo anterior guardado aparte")
ok("mundos-anteriores\\" in console(V), "mensaje con la ruta de Windows")
call(f"servers/{V}/start", "POST"); d = settle(V)
ok(d["status"] == "en línea", "enciende en 1.21.1")
call(f"servers/{V}/stop", "POST"); settle(V, ("detenido",))

print("== NeoForge (run.bat) ==")
st, j = call("import/upload?name=ServerFiles-1.0.zip", "POST", raw=open("Z:/home/claude/mock2/ServerFiles-1.0.zip", "rb").read())
j = wait(lambda: (lambda x: x if x["status"] in ("listo", "error") else None)(call("import/" + j["id"])[1]))
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "autostart": False, "name": "Neo", "disable": ["badclient.jar"]})
N = s["id"]; d = settle(N, ("detenido", "error")); root = os.path.join(sh.SERVERS_DIR, N)
ok(d["status"] == "detenido" and "21.1.77" in open(os.path.join(root, "run.bat")).read(), f"NeoForge 21.1.77 instalado ({d['status']} {d.get('error')})")
st, r = call(f"servers/{N}/version", "POST", {"mc_version": "1.21.1", "loader_version": "21.1.66"})
d = settle(N, ("detenido", "error")); m = meta(N)
ok(d["status"] == "detenido" and m["loader_version"] == "21.1.66" and "21.1.66" in " ".join(m["launch"].get("args", [])) and "21.1.66" in open(os.path.join(root, "run.bat")).read(), f"pasa a 21.1.66 con su run.bat: {m.get('launch')}")
ok(not os.path.exists(os.path.join(root, "libraries", "net", "neoforged", "neoforge", "21.1.77")), "quita la versión anterior")
call(f"servers/{N}/start", "POST"); d = settle(N)
ok(d["status"] == "en línea", f"enciende con el loader nuevo ({d['status']} {d.get('error')})")
call(f"servers/{N}/stop", "POST"); settle(N, ("detenido",))

print("== Fabric ==")
st, s = call("servers", "POST", {"type": "fabric", "mc_version": "1.21.1", "eula": True, "autostart": False})
F = s["id"]; settle(F, ("detenido", "error"))
st, r = call(f"servers/{F}/version", "POST", {"mc_version": "1.21.8"})
d = settle(F, ("detenido", "error")); m = meta(F)
ok(d["status"] == "detenido" and m["mc_version"] == "1.21.8" and m["loader_version"] == "0.16.14" and os.path.exists(os.path.join(sh.SERVERS_DIR, F, "fabric-server-launch.jar")), "fabric 1.21.1 → 1.21.8")

tmp = tempfile.mkdtemp()
args = sh.log4j_fix_args("vanilla", "1.12.2", tmp)
ok(args == ["-Dlog4j.configurationFile=log4j2_112-116.xml"] and "%msg{nolookups}" in open(os.path.join(tmp, "log4j2_112-116.xml"), encoding="utf-8").read(), "protección Log4Shell en Windows")
print("\nLISTO" if not FAILS else f"\n{len(FAILS)} FALLAS: {FAILS}")
sh.manager.shutdown_all(); httpd.shutdown(); os._exit(1 if FAILS else 0)
