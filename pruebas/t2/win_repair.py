# Arreglos automáticos y barra de carga con Python y Java de Windows (bajo Wine).
import os, sys, json, time, threading, urllib.request, shutil, zipfile, re
APP = "Z:/home/claude/wt/app"
os.environ["USERPROFILE"] = r"Z:\home\claude\mock2\winhome"
os.environ["APPDATA"] = r"Z:\home\claude\mock2\winhome\AppData\Roaming"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
def _copy2(src, dst, *, follow_symlinks=True):          # Wine 9 no implementa CopyFile2
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst); shutil.copystat(src, dst); return dst
shutil.copy2 = _copy2
import servidor_home as sh
assert sh.IS_WINDOWS, "este arnés es para Windows"
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"; sh.PLAYIT_DOWNLOAD_LATEST = B + "/playit-dl/"; sh.MRPACK_HOSTS.add("127.0.0.1")
sh.MODRINTH_API = B + "/modrinth-api/v2"
sh.manager = sh.Manager()
httpd = sh.AppHTTPServer(("127.0.0.1", 8765), sh.Handler); sh.HTTPD = httpd
sh.manager.playit = sh.Playit()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print("Python", sys.version.split()[0], "en", sys.platform)
A = "http://127.0.0.1:8765/api/"
FAILS = []


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def mock(path, body):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode(), method="POST")
    return json.loads(urllib.request.urlopen(req).read())


def wait(fn, timeout=60, step=0.25):
    timeout *= 3
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
def sdir(sid): return os.path.join(sh.SERVERS_DIR, sid)
def mods(sid): return sorted(os.listdir(os.path.join(sdir(sid), "mods")))
def meta(sid): return json.load(open(os.path.join(sdir(sid), "servidor-home.json"), encoding="utf-8"))
def console(sid): return "\n".join(l["s"] for l in call(f"servers/{sid}/log?since=0")[1]["lines"])
def last_cmd(sid): return [l for l in console(sid).splitlines() if l.startswith("$ ")][-1]
def backups(sid): return sorted(os.listdir(os.path.join(sdir(sid), "respaldos"))) if os.path.isdir(os.path.join(sdir(sid), "respaldos")) else []
def start(sid): return call(f"servers/{sid}/start", "POST")
def final(sid, timeout=90): return wait(lambda: (lambda x: x if x["status"] in ("en línea", "error") else None)(srv(sid)), timeout)


def stop(sid):
    call(f"servers/{sid}/stop", "POST")
    wait(lambda: srv(sid)["status"] in ("detenido", "error"), 60)


def mk(t, mc, name, lv=None, ram=2048):
    st, s = call("servers", "POST", {"type": t, "mc_version": mc, "loader_version": lv, "name": name, "eula": True,
                                     "autostart": False, "ram_mb": ram})
    assert st in (200, 201), (st, s)
    d = wait(lambda: (lambda x: x if x["status"] in ("detenido", "error") else None)(srv(s["id"])), 120)
    assert d["status"] == "detenido", d
    os.makedirs(os.path.join(sdir(s["id"]), "mods"), exist_ok=True)
    return s["id"]


def jar(sid, fname, mid, loader="fabric", version="1.0", name=None, deps=(), env="*", ranges=None):
    with zipfile.ZipFile(os.path.join(sdir(sid), "mods", fname), "w") as z:
        if loader == "fabric":
            z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mid, "version": version, "name": name or mid,
                                                      "environment": env, "depends": dict({d: "*" for d in deps}, **(ranges or {}))}))
        else:
            z.writestr("META-INF/neoforge.mods.toml", f'modLoader="javafml"\nloaderVersion="[4,)"\nlicense="MIT"\n[[mods]] #mandatory\n'
                                                       f'modId="{mid}"\nversion="{version}"\ndisplayName="{name or mid}"\n'
                                                       + "".join(f'[[dependencies.{mid}]]\n    modId="{d}"\n    type="required"\n    side="BOTH"\n' for d in deps))
        z.writestr(f"com/example/{mid}/X.class", b"\xca\xfe\xba\xbe" + os.urandom(8))


def disable(sid, fname):
    p = os.path.join(sdir(sid), "mods", fname)
    os.replace(p, p + ".disabled")


class Watch:
    def __init__(self, sid):
        self.sid, self.snaps, self.on = sid, [], True
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while self.on:
            try:
                x = srv(self.sid)
                self.snaps.append((x["status"], x.get("progress")))
            except Exception:
                pass
            time.sleep(0.1)

    def done(self):
        self.on = False
        time.sleep(0.3)
        i = 0
        while i < len(self.snaps) and self.snaps[i][0] == "detenido":
            i += 1
        return self.snaps[i:]


print("== P) Barra al crear y encender ==")
open("Z:/tmp/fakeserver-slow", "w").write("200 10")
st, s = call("servers", "POST", {"type": "fabric", "mc_version": "1.21.8", "name": "Barra", "eula": True, "autostart": True})
P = s["id"]; w = Watch(P)
d = wait(lambda: (lambda x: x if x["status"] in ("en línea", "error") else None)(srv(P)), 120)
prs = [p for _s, p in w.done() if p]
pcts = [p["pct"] for p in prs]
ok(d["status"] == "en línea" and prs and all(p["kind"] == "instalando" for p in prs), f"una barra desde que se crea hasta que enciende ({len(prs)} lecturas)")
ok(all(b >= a for a, b in zip(pcts, pcts[1:])) and max(pcts) >= 70 and len(set(pcts)) >= 5, f"avanza sin retroceder: {sorted(set(pcts))}")
ok(any(p["label"].startswith("Encendiendo por primera vez") for p in prs) and d["progress"] is None, "llega al primer encendido y al final se va")
ok(meta(P).get("boot_lines", 0) >= 200, f"recuerda cuánto tardó: {meta(P).get('boot_lines')} líneas")
stop(P)
os.remove("Z:/tmp/fakeserver-slow")

print("\n== R1) Falta un mod → lo descarga de Modrinth ==")
F1 = mk("fabric", "1.21.8", "Falta dependencia")
jar(F1, "needslib.jar", "needslib")
mock("/__slow", {"mr": 2})
w = Watch(F1); start(F1); d = final(F1); snaps = w.done()
mock("/__slow", {})
ok(d["status"] == "en línea" and "libdep-2.0.jar" in mods(F1) and d["repairs"] == ["descargué libdep-2.0.jar"], f"{mods(F1)} {d['repairs']}")
seen = {s for s, _p in snaps}
ok(seen <= {"iniciando", "reparando", "en línea"} and "reparando" in seen, f"pasa por «reparando» sin error: {sorted(seen)}")
ok(not [f for f in mods(F1) if f.endswith((".descarga", ".part"))], "sin archivos a medias")
stop(F1)

print("\n== R2) Librería vieja → la cambia (renombrar en Windows) ==")
F2 = mk("fabric", "1.21.8", "Dependencia vieja")
jar(F2, "needslib.jar", "needslib"); jar(F2, "libdep-1.0.jar", "libdep", version="1.0", name="Lib Dep")
start(F2); d = final(F2)
ok(d["status"] == "en línea" and "libdep-1.0.jar.disabled" in mods(F2) and "libdep-2.0.jar" in mods(F2), f"{mods(F2)}")
stop(F2)

print("\n== R3) NeoForge: mod con fallas → versión nueva con respaldo del mundo ==")
N = mk("neoforge", "1.21.1", "Mod con fallas")
start(N); final(N); stop(N)
jar(N, "buggy-1.0.jar", "buggy", "neoforge", name="Buggy Mod")
start(N); d = final(N, 120)
ok(d["status"] == "en línea" and "buggy-1.1.jar" in mods(N) and "buggy-1.0.jar.disabled" in mods(N) and len(backups(N)) == 1,
   f"{mods(N)} respaldos={backups(N)}")
stop(N)

print("\n== R4) Memoria, puerto y vigilante ==")
F3 = mk("fabric", "1.21.8", "Memoria", ram=2048)
open(os.path.join(sdir(F3), "oom.txt"), "w").write("x")
start(F3); d = final(F3)
ok(d["status"] == "en línea" and meta(F3)["ram_mb"] == 4608 and "-Xmx4608M" in last_cmd(F3), f"sube la RAM: {d['repairs']}")
stop(F3)
F4 = mk("fabric", "1.21.8", "Puerto")
sh.write_properties(os.path.join(sdir(F4), "server.properties"), {"server-port": 25565})
open(os.path.join(sdir(F4), "port-busy"), "w").write("25565")
start(F4); d = final(F4)
ok(d["status"] == "en línea" and d["port"] != 25565, f"otro puerto: {d['port']}")
stop(F4)
open(os.path.join(sdir(F4), "watchdog"), "w").write("x")
start(F4)
d = wait(lambda: (lambda x: x if (x["status"] == "en línea" and x["repairs"]) or x["status"] == "error" else None)(srv(F4)), 60)
ok(d["status"] == "en línea" and sh.read_properties(os.path.join(sdir(F4), "server.properties")).get("max-tick-time") == "-1", f"vigilante: {d['repairs']}")
stop(F4)

print("\n== R5) Detener mientras arregla ==")
F5 = mk("fabric", "1.21.8", "Cancelar")
jar(F5, "needslib.jar", "needslib")
mock("/__slow", {"mr": 4})
start(F5)
wait(lambda: srv(F5)["status"] == "reparando", 30, 0.1)
st, r = call(f"servers/{F5}/stop", "POST")
ok(st == 200 and srv(F5)["status"] == "detenido", "Detener lo deja apagado")
time.sleep(6)
ok(srv(F5)["status"] == "detenido", "y no se enciende solo")
mock("/__slow", {})


print("\n== R6) NeoForge falla con código 0: reactiva lo desactivado (y se cierra el Java trabado) ==")
sh.STUCK_WAIT = 4
NJ = mk("neoforge", "1.21.1", "Codigo cero")
jar(NJ, "needsjei.jar", "needsjei", "neoforge", deps=("jeidep",)); jar(NJ, "jeidep-1.0.jar", "jeidep", "neoforge", deps=("jeiconfig",))
jar(NJ, "jeiconfig-1.0.jar", "jeiconfig", "neoforge"); disable(NJ, "jeidep-1.0.jar"); disable(NJ, "jeiconfig-1.0.jar")
w = Watch(NJ); start(NJ); d = final(NJ, 120); snaps = w.done()
ok(d["status"] == "en línea" and d["repairs"] == ["reactivé jeidep-1.0.jar, jeiconfig-1.0.jar (lo pedía needsjei)"], f"{d['repairs']} {mods(NJ)}")
ok({s for s, _p in snaps} <= {"iniciando", "reparando", "en línea"}, "sin mostrar «Apagado» entremedio")
stop(NJ)
disable(NJ, "jeidep-1.0.jar")
open(os.path.join(sdir(NJ), "hang-on-fail"), "w").write("x")
start(NJ); d = final(NJ, 120)
ok(d["status"] == "en línea" and "Java quedó abierto; lo cierro" in console(NJ), "si Java queda abierto después de fallar, lo cierra y lo arregla")
stop(NJ)

print("\n== R7) Un mod necesita un mod de shaders → lo desactiva ==")
NS = mk("neoforge", "1.21.1", "Shaders")
jar(NS, "shaderaddon.jar", "shaderaddon", "neoforge", deps=("iris",)); jar(NS, "iris-1.8.jar", "iris", "neoforge"); disable(NS, "iris-1.8.jar")
start(NS); d = final(NS, 120)
ok(d["status"] == "en línea" and d["repairs"] == ["desactivé shaderaddon.jar (necesita iris, que es solo del jugador)"], f"{d['repairs']}")
stop(NS)

print("\n== R8) Zip de mods para los amigos e imagen del servidor ==")
FS = mk("fabric", "1.21.8", "Compártelo Máx")
jar(FS, "comun-1.0.jar", "comun"); jar(FS, "grafico-1.0.jar", "grafico", env="client"); disable(FS, "grafico-1.0.jar")
os.makedirs(os.path.join(sdir(FS), "kubejs", "startup_scripts"), exist_ok=True)
open(os.path.join(sdir(FS), "kubejs", "startup_scripts", "items.js"), "w").write("//")
st, r = call(f"servers/{FS}/compartir", "POST")
shs = wait(lambda: (lambda x: x if x and x["estado"] in ("listo", "error") else None)(srv(FS)["share"]), 30)
zp = os.path.join(sh.SHARE_DIR, shs.get("archivo", "?"))
names = sorted(zipfile.ZipFile(zp).namelist()) if os.path.isfile(zp) else []
ok(shs["estado"] == "listo" and names == ["LEEME.txt", "kubejs/startup_scripts/items.js", "mods/comun-1.0.jar", "mods/grafico-1.0.jar"],
   f"arma el zip con rutas de zip normales (/): {names}")
with urllib.request.urlopen(A + f"servers/{FS}/compartir") as resp:
    ok(resp.read() == open(zp, "rb").read(), "se descarga")
import zlib, struct
def chunk(t, dd): return struct.pack(">I", len(dd)) + t + dd + struct.pack(">I", zlib.crc32(t + dd) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x10\x80\x20" * 64 * 64)) + chunk(b"IEND", b"")
req = urllib.request.Request(A + f"servers/{FS}/icono", data=png, method="PUT")
with urllib.request.urlopen(req) as resp:
    ok(json.loads(resp.read())["icon"] > 0 and open(os.path.join(sdir(FS), "server-icon.png"), "rb").read() == png, "guarda la imagen del servidor")

print("\n== R9) Fabric Loader demasiado nuevo para un mod antiguo (como «un mundillo») → vuelve a la 0.14 del launcher ==")
FL = mk("fabric", "1.21.1", "Mundillo")      # (Java 21: es el único Java de Windows que hay en las pruebas)
jar(FL, "oldcrash.jar", "oldcrash", name="Old Crash", ranges={"fabricloader": ">=0.14.0"})
lanz = os.path.join(os.environ.get("TEMP") or "C:\\", "lanzador mundillo")
shutil.rmtree(lanz, ignore_errors=True); os.makedirs(os.path.join(lanz, "logs"))
open(os.path.join(lanz, "logs", "latest.log"), "w").write("[14:48:50] [main/INFO]: Loading Minecraft 1.21.1 with Fabric Loader 0.14.9\n")
with open(os.path.join(sdir(FL), "servidor-home.log"), "a", encoding="utf-8") as fh:
    fh.write(f"2026-09-24 21:27:53 Copiando el modpack desde {lanz} ...\n")
start(FL); d = final(FL, 180)
ok(d["status"] == "en línea" and meta(FL)["loader_version"] == "0.14.9"
   and d["repairs"] == ["cambié Fabric Loader 0.16.14 por 0.14.9 (la misma con la que tu launcher abre este modpack)"],
   f"lee la carpeta del launcher (ruta de Windows con espacios) y usa su Fabric Loader: {d['status']} {d['repairs']}")
stop(FL)

print("\n== R10) Varios mods del jugador fallan a la vez → los desactiva juntos y el error dice cuáles ==")
NK = mk("neoforge", "1.21.1", "Kyalita")
jar(NK, "hudmod.jar", "hudmod", "neoforge", name="Hud Mod")
with zipfile.ZipFile(os.path.join(sdir(NK), "mods", "weatherfx.jar"), "w") as z:
    z.writestr("META-INF/neoforge.mods.toml", 'modLoader = "javafml"\r\nloaderVersion = "[2,)"\r\nlicense = "ARR"\r\n\r\n[[mods]]\r\n'
               'modId = "weatherfx"\r\nversion = "1.4"\r\ndisplayName = "Weather FX"\r\n')
    z.writestr("com/example/weatherfx/Main.class", b"\xca\xfe\xba\xbe")
start(NK); d = final(NK, 120)
ok(d["status"] == "en línea" and d["repairs"] == ["desactivé hudmod.jar (es solo del jugador)", "desactivé weatherfx.jar (es solo del jugador)"]
   and "El servidor no pudo encender por los mods «Hud Mod» y «Weather FX»." in console(NK), f"{d['status']} {d['repairs']}")
stop(NK)

print("\nLISTO" if not FAILS else f"\n{len(FAILS)} FALLAS: {FAILS}")
sh.manager.shutdown_all(); httpd.shutdown(); os._exit(1 if FAILS else 0)
