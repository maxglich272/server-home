# Pruebas de los arreglos automáticos (mods que faltan o no calzan, loader, RAM, Java, puerto, configuración,
# vigilante, caídas, mods repetidos) y de la barra de carga al crear, encender y arreglar.
import os, sys, json, time, threading, urllib.request, shutil, zipfile, re
APP = "/home/claude/t2/appr"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__"))
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
import servidor_home as sh
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.ADOPTIUM_API = B + "/adoptium"; sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"; sh.MRPACK_HOSTS.add("127.0.0.1")
sh.MODRINTH_API = B + "/modrinth-api/v2"; sh.CURSEFORGE_API = B + "/cf-api/v1"
sh.system_java_candidates = lambda: []      # todo Java viene del mock: un JRE falso que le dice al servidor qué versión simula
sh.manager = sh.Manager()
httpd = sh.ThreadingHTTPServer(("127.0.0.1", 8765), sh.Handler); sh.HTTPD = httpd
sh.manager.playit = sh.Playit()
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = "http://127.0.0.1:8765/api/"
FAILS = []
SLOW = "/tmp/fakeserver-slow"


def call(path, method="GET", body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(A + path, data=data, method=method,
                                 headers={"Content-Type": "application/octet-stream" if raw is not None else "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def mock(path, body):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Agent-Key a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"})
    return json.loads(urllib.request.urlopen(req).read())


def wait(fn, timeout=60, step=0.2):
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


def final(sid, timeout=90):
    """Espera a que termine: encendido o error definitivo (mientras arregla sigue en «reparando»)."""
    return wait(lambda: (lambda x: x if x["status"] in ("en línea", "error") else None)(srv(sid)), timeout)


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


def jar(sid, fname, mid, loader="fabric", version="1.0", name=None, deps=(), display_test=None, env="*", ranges=None, folder=None):
    with zipfile.ZipFile(os.path.join(folder or os.path.join(sdir(sid), "mods"), fname), "w") as z:
        if loader == "fabric":
            z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mid, "version": version, "name": name or mid,
                                                      "environment": env, "depends": dict({d: "*" for d in deps}, **(ranges or {}))}))
        else:
            z.writestr("META-INF/neoforge.mods.toml", f'modLoader="javafml" #mandatory\nloaderVersion="[4,)"\nlicense="MIT"\n[[mods]] #mandatory\n'
                                                       f'modId="{mid}" #mandatory\nversion="{version}"\ndisplayName="{name or mid}"\n'
                                                       + (f'displayTest="{display_test}"\n' if display_test else "")
                                                       + "".join(f'[[dependencies.{mid}]]\n    modId="{d}"\n    type="required"\n'
                                                                 f'    versionRange="[1.0,)"\n    side="BOTH"\n' for d in deps))
        z.writestr(f"com/example/{mid}/X.class", b"\xca\xfe\xba\xbe" + os.urandom(8))


def disable(sid, fname):
    p = os.path.join(sdir(sid), "mods", fname)
    os.replace(p, p + ".disabled")


def make_png(w, h, color=(200, 60, 40)):
    import zlib, struct
    raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Watch:
    """Mira el estado y la barra cada 80 ms."""
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
            time.sleep(0.08)

    def done(self):
        """Lecturas desde que empezó a encender (se descartan las de antes, cuando aún estaba apagado)."""
        self.on = False
        time.sleep(0.2)
        i = 0
        while i < len(self.snaps) and self.snaps[i][0] == "detenido":
            i += 1
        return self.snaps[i:]


def monotonic(prs):
    """La barra nunca retrocede mientras sea la misma tarea."""
    for a, b in zip(prs, prs[1:]):
        if a["kind"] == b["kind"] and b["pct"] < a["pct"] and b["elapsed"] >= a["elapsed"]:
            return False
    return True


print("== 0) Barra: cálculo de fases ==")
pr = sh.Progress("x", [("a", "A", 1), ("b", "B", 3)])
pr.begin("a"); pr.update(0.5)
ok(pr.pct() == 12 and pr.to_json()["label"] == "A" and pr.to_json()["step"] == 1 and pr.to_json()["steps"] == 2, f"fase A a medias = 12 % ({pr.pct()})")
pr.begin("b"); pr.update(0.5)
ok(pr.pct() == 62, f"fase B (pesa 3) a medias = 62 % ({pr.pct()})")
pr.update(0.2); pr.begin("a")
ok(pr.pct() == 62, "no retrocede aunque llegue un avance menor o una fase anterior")
pr.update(1); pr.begin("b"); pr.update(1)
ok(pr.pct() == 99, "no marca 100 % hasta terminar de verdad")

print("\n== P) Barra de carga al crear y al encender ==")
open(SLOW, "w").write("300 8")
mock("/__slow", {"java": 3})
st, s = call("servers", "POST", {"type": "fabric", "mc_version": "1.21.8", "name": "Barra", "eula": True, "autostart": True})
P = s["id"]
w = Watch(P)
d = wait(lambda: (lambda x: x if x["status"] in ("en línea", "error") else None)(srv(P)), 120)
snaps = w.done()
prs = [p for _s, p in snaps if p]
ok(d["status"] == "en línea", f"crea y enciende ({d['status']})")
ok(bool(prs) and all(p["kind"] == "instalando" for p in prs) and {p["steps"] for p in prs} == {4},
   f"una sola barra de 4 pasos desde que se crea hasta que enciende ({len(prs)} lecturas)")
ok(any(p["label"] == "Preparando Java 21" for p in prs), "paso «Preparando Java 21»")
ok(any(re.match(r"Descargando Java 21: \d+ de 3 MB", p["detail"] or "") for p in prs), "muestra los MB que lleva: " +
   str(next((p["detail"] for p in prs if "MB" in (p["detail"] or "")), None)))
ok(any(p["label"].startswith("Encendiendo por primera vez · cargando mods") for p in prs), "después «Encendiendo por primera vez · cargando mods»")
ok(any(p["label"] == "Encendiendo por primera vez · generando el terreno" and "Terreno:" in (p["detail"] or "") for p in prs),
   "y «generando el terreno» con el porcentaje del terreno")
pcts = [p["pct"] for p in prs]
ok(monotonic(prs), f"la barra nunca retrocede: {pcts[:3]}…{pcts[-3:]}")
ok(min(pcts) <= 15 and max(pcts) >= 70 and len(set(pcts)) >= 8, f"avanza de a poco: {min(pcts)} → {max(pcts)} en {len(set(pcts))} valores")
ok(d["progress"] is None, "al quedar encendido la barra desaparece")
m = meta(P)
ok(m.get("boot_lines", 0) >= 300 and "boot_seconds" in m, f"recuerda cuánto tardó el encendido ({m.get('boot_lines')} líneas, {m.get('boot_seconds')} s)")
stop(P)
w = Watch(P); start(P); d = final(P); snaps = w.done()
prs = [p for _s, p in snaps if p]
pcts = [p["pct"] for p in prs]
ok(d["status"] == "en línea" and prs and all(p["kind"] == "encendiendo" for p in prs), "al encender de nuevo: barra de encendido")
ok(monotonic(prs) and any(25 <= x <= 75 for x in pcts) and len(set(pcts)) >= 6,
   f"avanza según lo que tardó la vez anterior: {sorted(set(pcts))[:12]}")
stop(P)
os.remove(SLOW)
mock("/__slow", {})

print("\n== R1) Fabric: falta un mod que otro necesita → lo descarga de Modrinth ==")
F1 = mk("fabric", "1.21.8", "Falta dependencia")
jar(F1, "needslib.jar", "needslib", name="Needs Lib")
mock("/__slow", {"mr": 2})
w = Watch(F1); start(F1); d = final(F1); snaps = w.done()
mock("/__slow", {})
ok(d["status"] == "en línea" and "libdep-2.0.jar" in mods(F1), f"descargó libdep 2.0 (la estable, no la beta 2.1) y encendió: {mods(F1)}")
ok(d["repairs"] == ["descargué libdep-2.0.jar"], f"queda en «Se arregló solo»: {d['repairs']}")
seen = [s for s, _p in snaps]
ok("reparando" in seen and "error" not in seen and "detenido" not in seen, f"pasa por «reparando» sin mostrar error ni apagado: {sorted(set(seen))}")
rp = [p for _s, p in snaps if p and p["kind"] == "reparando"]
ok(any(p["label"] == "Descargando libdep" for p in rp) and any(p["label"].startswith("Encendiendo de nuevo") for p in rp),
   f"la barra muestra el arreglo y el reencendido: {sorted({p['label'] for p in rp})[:5]}")
ok(any(re.match(r"libdep-2\.0\.jar: \d+ de \d+ KB$", p["detail"] or "") for p in rp), "muestra cuánto lleva de la descarga del mod: " +
   str(next((p["detail"] for p in rp if "KB" in (p["detail"] or "")), None)))
ok("Arreglo automático: Descargando libdep…" in console(F1) and "Se arregló solo: descargué libdep-2.0.jar." in console(F1), "queda anotado en la consola")
ok(not [f for f in mods(F1) if f.endswith((".descarga", ".part"))], "sin archivos a medias en mods")
stop(F1)

print("\n== R2) Fabric: la versión de una librería no sirve → la actualiza ==")
F2 = mk("fabric", "1.21.8", "Dependencia vieja")
jar(F2, "needslib.jar", "needslib"); jar(F2, "libdep-1.0.jar", "libdep", version="1.0", name="Lib Dep")
start(F2); d = final(F2)
ok(d["status"] == "en línea" and "libdep-1.0.jar.disabled" in mods(F2) and "libdep-2.0.jar" in mods(F2), f"cambia libdep 1.0 por 2.0: {mods(F2)}")
ok(d["repairs"] == ["cambié libdep-1.0.jar por libdep-2.0.jar"], f"{d['repairs']}")
stop(F2)

print("\n== R3) NeoForge: dos dependencias seguidas (GeckoLib por búsqueda y Balm) ==")
N1 = mk("neoforge", "1.21.1", "Dependencias Neo")
jar(N1, "needsgecko.jar", "needsgecko", "neoforge", name="Needs Gecko"); jar(N1, "needsbalm.jar", "needsbalm", "neoforge", name="Needs Balm")
mock("/__reset-mr", {})
w = Watch(N1); start(N1); d = final(N1, 120); snaps = w.done()
ok(d["status"] == "en línea" and "geckolib-neoforge-1.21.1-4.7.1.jar" in mods(N1) and "balm-neoforge-1.21.1-21.0.20.jar" in mods(N1),
   f"descargó GeckoLib y Balm para NeoForge 1.21.1 y encendió: {mods(N1)}")
st = mock("/__state", {})
ok("geckolib-addon-extra-1.0.jar" in st.get("mr_downloads", []) and "geckolib-addon-extra-1.0.jar" not in mods(N1),
   "probó un mod de nombre parecido (Gecko Extra), vio que no era GeckoLib y lo descartó")
ok(not any("fabric" in f for f in mods(N1)), "no bajó la versión de Fabric")
ok(d["repairs"] == ["descargué geckolib-neoforge-1.21.1-4.7.1.jar (lo pedía needsgecko)",
                    "descargué balm-neoforge-1.21.1-21.0.20.jar (lo pedía needsbalm)"], f"{d['repairs']}")
seen = {s for s, _p in snaps}
ok(seen <= {"iniciando", "reparando", "en línea"}, f"dos arreglos seguidos sin pasar por error ni apagado: {sorted(seen)}")
stop(N1)

print("\n== R4) NeoForge: un mod con contenido falla → versión más nueva, con respaldo del mundo ==")
N2 = mk("neoforge", "1.21.1", "Mod con fallas")
start(N2); d = final(N2); stop(N2)
ok(os.path.isdir(os.path.join(sdir(N2), "world")) and not backups(N2), "primero enciende normal (crea el mundo)")
jar(N2, "buggy-1.0.jar", "buggy", "neoforge", name="Buggy Mod")
w = Watch(N2); start(N2); d = final(N2); snaps = w.done()
ok(d["status"] == "en línea" and "buggy-1.1.jar" in mods(N2) and "buggy-1.0.jar.disabled" in mods(N2), f"actualizó buggy 1.0 → 1.1: {mods(N2)}")
ok(len(backups(N2)) == 1, f"respaldó el mundo antes de encender con el mod cambiado: {backups(N2)}")
ok(d["repairs"] == ["cambié buggy-1.0.jar por buggy-1.1.jar", f"respaldé el mundo antes de encender con los cambios ({backups(N2)[0]}, en Respaldos)"],
   f"y lo cuenta: {d['repairs']}")
ok(any(p and p["label"] == "Respaldando el mundo" for _s, p in snaps) or "Respaldando el mundo antes de encender" in console(N2),
   "el respaldo se ve en la barra y en la consola")
stop(N2)

print("\n== R5) Un mod falla y no hay versión nueva → lo desactiva solo (con respaldo) y dice cuál era ==")
jar(N2, "broken-stubborn.jar", "stubborn", "neoforge", name="Stubborn")
start(N2); d = final(N2)
ok(d["status"] == "en línea" and "broken-stubborn.jar.disabled" in mods(N2), f"lo desactivó y encendió: {d['status']} {mods(N2)}")
ok(d["repairs"] == ["desactivé broken-stubborn.jar (fallaba al cargar)", f"respaldé el mundo antes de encender con los cambios ({backups(N2)[-1]}, en Respaldos)"],
   f"lo cuenta: {d['repairs']}")
ok(len(backups(N2)) == 2, f"respaldó el mundo antes de encender sin ese mod: {backups(N2)}")
c = console(N2)
ok("El servidor no pudo encender por el mod «Broken stubborn»." in c and "No encontré otra versión de «stubborn»" in c,
   "en la consola: qué mod era y que primero buscó una versión nueva")
lst = {a["name"]: a for a in call(f"servers/{N2}/addons")[1]}
ok(lst["broken-stubborn.jar.disabled"].get("why") == "La app lo desactivó: fallaba al cargar", f"en la pestaña Mods dice por qué: {lst['broken-stubborn.jar.disabled']}")
stop(N2)

print("\n== R5b) La versión nueva también falla → la desactiva a la vuelta siguiente ==")
jar(N2, "broken-stubborn2.jar", "stubborn2", "neoforge", name="Stubborn Two")
start(N2); d = final(N2)
ok(d["status"] == "en línea" and "broken-stubborn2.jar.disabled" in mods(N2) and "broken-stubborn2-1.1.jar.disabled" in mods(N2),
   f"probó la versión nueva y, como también fallaba, la desactivó: {mods(N2)}")
ok([r for r in d["repairs"] if not r.startswith("respaldé")] == ["cambié broken-stubborn2.jar por broken-stubborn2-1.1.jar",
                                                                 "desactivé broken-stubborn2-1.1.jar (fallaba al cargar)"], f"{d['repairs']}")
stop(N2)

print("\n== R6) NeoForge: un mod pide un loader más nuevo → actualiza NeoForge ==")
N3 = mk("neoforge", "1.21.1", "Loader viejo", lv="21.1.66")
jar(N3, "needsneo.jar", "needsneo", "neoforge", name="Needs Neo")
w = Watch(N3); start(N3); d = final(N3, 120); snaps = w.done()
m = meta(N3)
ok(d["status"] == "en línea" and m["loader_version"] == "21.1.77" and "21.1.77" in " ".join(m["launch"]["args"]),
   f"pasó a NeoForge 21.1.77 (la estable, no la beta) y encendió: {m['loader_version']}")
ok(d["repairs"] == ["actualicé NeoForge de 21.1.66 a 21.1.77"], f"{d['repairs']}")
seen = {s for s, _p in snaps}
ok(seen <= {"iniciando", "reparando", "en línea"}, f"sin pasar por apagado ni error mientras reinstala: {sorted(seen)}")
ok(not os.path.isdir(os.path.join(sdir(N3), "libraries", "net", "neoforged", "neoforge", "21.1.66")), "quitó el loader anterior")
stop(N3)

print("\n== R7) Le faltó memoria → sube la RAM (dos veces si hace falta) ==")
F3 = mk("fabric", "1.21.8", "Memoria", ram=2048)
open(os.path.join(sdir(F3), "oom.txt"), "w").write("x")
start(F3); d = final(F3)
ok(d["status"] == "en línea" and meta(F3)["ram_mb"] == 4608 and "-Xmx4608M" in last_cmd(F3), f"2048 → 3072 → 4608 MB: {meta(F3)['ram_mb']}")
ok(d["repairs"] == ["subí la RAM de 2048 MB a 3072 MB", "subí la RAM de 3072 MB a 4608 MB"], f"{d['repairs']}")
stop(F3)

print("\n== R8) Puerto ocupado → usa otro ==")
F4 = mk("fabric", "1.21.8", "Puerto")
sh.write_properties(os.path.join(sdir(F4), "server.properties"), {"server-port": 25565})
open(os.path.join(sdir(F4), "port-busy"), "w").write("25565")
start(F4); d = final(F4)
ok(d["status"] == "en línea" and d["port"] != 25565, f"pasó al puerto {d['port']}")
ok(len(d["repairs"]) == 1 and d["repairs"][0].startswith(f"cambié el puerto de 25565 a {d['port']}"), f"{d['repairs']}")
stop(F4)

print("\n== R9) Un mod pide Java más nuevo → lo descarga ==")
F5 = mk("fabric", "1.21.8", "Java nuevo")
open(os.path.join(sdir(F5), "needs-java"), "w").write("25")
start(F5); d = final(F5)
ok(d["status"] == "en línea" and meta(F5)["java_major"] == 25 and "/java/25/" in last_cmd(F5), f"usa Java 25: {last_cmd(F5)[:80]}")
ok(25 in mock("/__state", {}).get("java_downloads", []) and d["repairs"] == ["ahora usa Java 25"], f"{d['repairs']}")
stop(F5)

print("\n== R10) Archivo de configuración dañado → lo restablece ==")
F6 = mk("fabric", "1.21.8", "Config")
os.makedirs(os.path.join(sdir(F6), "config"), exist_ok=True)
open(os.path.join(sdir(F6), "config", "roto.toml"), "w").write("ROTO\x00\x00")
start(F6); d = final(F6)
cfg = os.listdir(os.path.join(sdir(F6), "config"))
ok(d["status"] == "en línea" and "roto.toml" not in cfg and any(f.startswith("roto.toml.danado-") for f in cfg), f"guardó el dañado aparte: {cfg}")
stop(F6)

print("\n== R11) El vigilante corta el servidor ya encendido → lo desactiva y reinicia ==")
F7 = mk("fabric", "1.21.8", "Vigilante")
open(os.path.join(sdir(F7), "watchdog"), "w").write("x")
start(F7)
d = wait(lambda: (lambda x: x if (x["status"] == "en línea" and x["repairs"]) or x["status"] == "error" else None)(srv(F7)), 60)
props = sh.read_properties(os.path.join(sdir(F7), "server.properties"))
ok(d["status"] == "en línea" and props.get("max-tick-time") == "-1", f"max-tick-time={props.get('max-tick-time')}")
time.sleep(1.5)
ok(srv(F7)["status"] == "en línea", "y sigue encendido")
stop(F7)

print("\n== R12) Se cae una vez sin causa conocida → lo vuelve a encender ==")
open(os.path.join(sdir(F7), "crash-once"), "w").write("x")
w = Watch(F7); start(F7)
d = wait(lambda: (lambda x: x if x["status"] == "en línea" and "intento 1 de 3" in console(F7) else None)(srv(F7)), 60)
wait(lambda: srv(F7)["status"] == "en línea" and "Servidor encendido" in console(F7).split("intento 1 de 3")[-1], 30)
snaps = w.done()
ok(not os.path.exists(os.path.join(sdir(F7), "crash-once")), "se había caído una vez")
ok(any(p and p["label"] == "Reiniciando después de la caída" for _s, p in snaps), "la barra muestra el reinicio")
ok(srv(F7)["status"] == "en línea", "volvió a quedar encendido")
stop(F7)

print("\n== R13) Mods repetidos → deja el más nuevo antes de encender ==")
F8 = mk("fabric", "1.21.8", "Repetidos")
jar(F8, "dupe-1.0.jar", "dupe", version="1.0"); jar(F8, "dupe-2.0.jar", "dupe", version="2.0")
start(F8); d = final(F8)
ok(d["status"] == "en línea" and "dupe-1.0.jar.disabled" in mods(F8) and "dupe-2.0.jar" in mods(F8), f"{mods(F8)}")
ok(d["repairs"] == ["Quité dupe-1.0.jar (repetido: me quedo con dupe-2.0.jar)"], f"{d['repairs']}")
stop(F8)

print("\n== R14) No existe en Modrinth → lo explica sin botón inútil ==")
F9 = mk("fabric", "1.21.8", "Fantasma")
jar(F9, "ghost.jar", "ghost")
start(F9); d = final(F9)
h = d.get("hint") or {}
ok(d["status"] == "error" and h.get("text", "").startswith("No se pudo arreglar solo: No encontré «ghostlib» para Fabric 1.21.8 en Modrinth")
   and not h.get("action"), f"{h}")
ok(d["progress"] is None and "No se pudo:" in console(F9), "sin barra y con el motivo en la consola")
start(F9); d = final(F9)
ok(d["status"] == "error" and (d.get("hint") or {}).get("text", "").startswith("No se pudo arreglar solo"), "al reintentar, lo mismo (no se queda pegado)")

print("\n== R15) Arreglo automático apagado → no toca nada y ofrece el botón ==")
F10 = mk("fabric", "1.21.8", "Manual")
st, r = call(f"servers/{F10}/settings", "PUT", {"auto_fix": False})
ok(st == 200 and srv(F10)["auto_fix"] is False, "se puede apagar en Ajustes")
jar(F10, "needslib.jar", "needslib")
start(F10); d = final(F10)
h = d.get("hint") or {}
ok(d["status"] == "error" and (h.get("action") or {}).get("type") == "download_mod" and h["action"]["label"] == "Descargar libdep y reintentar"
   and "libdep-2.0.jar" not in mods(F10), f"no lo arregla solo y ofrece: {h.get('action')}")
call(f"servers/{F10}/fix", "POST", {"action": h["action"]}); d = final(F10)
ok(d["status"] == "en línea" and "libdep-2.0.jar" in mods(F10), "con el botón lo arregla y enciende")
stop(F10)
call(f"servers/{F10}/settings", "PUT", {"auto_fix": True})

print("\n== R16) Detener mientras arregla ==")
F11 = mk("fabric", "1.21.8", "Cancelar")
jar(F11, "needslib.jar", "needslib")
mock("/__slow", {"mr": 3})
start(F11)
wait(lambda: srv(F11)["status"] == "reparando", 30, 0.1)
time.sleep(0.5)
st, r = call(f"servers/{F11}/stop", "POST")
d = srv(F11)
ok(st == 200 and d["status"] == "detenido" and d["progress"] is None, f"Detener lo deja apagado al tiro ({d['status']})")
st2, r2 = call(f"servers/{F11}/start", "POST")
ok(st2 == 400 and "Espera un momento" in r2.get("error", ""), f"no enciende mientras termina el paso a medias: {r2.get('error')}")
time.sleep(4)
d = srv(F11)
ok(d["status"] == "detenido" and "Arreglo automático cancelado" in console(F11), "no se enciende solo después de cancelar")
mock("/__slow", {})
start(F11); d = final(F11)
ok(d["status"] == "en línea" and "libdep-2.0.jar" in mods(F11), "después enciende normal (el mod ya había quedado descargado)")
stop(F11)

print("\n== R17) Mod solo del jugador en un modpack de Fabric (log real) sigue funcionando ==")
dm = os.path.join("/tmp", "diag-mods"); shutil.rmtree(dm, ignore_errors=True); os.makedirs(dm)
with zipfile.ZipFile(os.path.join(dm, "enchantment-glint-outline-1.21.11-3.2.jar"), "w") as z:
    z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "enchant-outline", "version": "3.2", "environment": "*"}))
lines = open("/mnt/user-data/uploads/Documents/servidor home/servidores/prueba/logs/latest.log", encoding="utf-8", errors="replace").read().splitlines()
probs = sh.find_problems(lines[-800:], None, dm)
ok(probs and probs[0]["auto"] and probs[0]["fix"] == {"type": "disable_client", "file": "enchantment-glint-outline-1.21.11-3.2.jar",
                                                      "reason": "es solo del jugador"},
   f"lo desactivaría solo: {probs[0]['title'] if probs else None}")

print("\n== O1) Java optimizado: flags de Aikar al encender, sin romper modpacks con su propio recolector ==")
O = mk("fabric", "1.21.8", "Optimizado", ram=4096)
start(O); d = final(O)
cmd = last_cmd(O)
ok(d["status"] == "en línea" and "-XX:+UseG1GC" in cmd and "-XX:G1HeapRegionSize=8M" in cmd and "-XX:+IgnoreUnrecognizedVMOptions" in cmd,
   f"enciende con los ajustes de Java: {cmd[:160]}")
ok(d.get("java_opt") is True, "vienen activados")
stop(O)
open(os.path.join(sdir(O), "user_jvm_args.txt"), "w").write("# del modpack\n-XX:+UseZGC\n")
start(O); d = final(O)
ok(d["status"] == "en línea" and "-XX:+UseG1GC" not in last_cmd(O), "si el modpack elige otro recolector (ZGC), no agrega los suyos")
stop(O)
os.remove(os.path.join(sdir(O), "user_jvm_args.txt"))
st, r = call(f"servers/{O}/settings", "PUT", {"java_opt": False})
start(O); d = final(O)
ok(st == 200 and d["java_opt"] is False and "-XX:+UseG1GC" not in last_cmd(O) and d["status"] == "en línea", "se pueden apagar en Ajustes")
stop(O)
call(f"servers/{O}/settings", "PUT", {"java_opt": True})

print("\n== O2) Mods de rendimiento desde Modrinth ==")
st, r = call(f"servers/{O}/rendimiento", "POST")
ok(st == 200 and r["added"] == ["Lithium 0.18.0", "FerriteCore 8.0.0", "ModernFix 5.24.0"] and not r["missing"],
   f"Fabric 1.21.8: agrega Lithium, FerriteCore y ModernFix: {r.get('message') or r}")
ok({"lithium-fabric-0.18.0+mc1.21.8.jar", "ferritecore-8.0.0-fabric.jar", "modernfix-fabric-5.24.0+mc1.21.8.jar"} <= set(mods(O)), f"{mods(O)}")
ok(srv(O)["status"] == "detenido" and srv(O)["progress"] is None, "vuelve a quedar apagado y sin barra")
st, r = call(f"servers/{O}/rendimiento", "POST")
ok(st == 200 and not r["added"] and r["had"] == ["Lithium", "FerriteCore", "ModernFix"], f"la segunda vez no duplica nada: {r.get('message')}")
start(O); d = final(O)
ok(d["status"] == "en línea", "y el servidor enciende con ellos")
st, r = call(f"servers/{O}/rendimiento", "POST")
ok(st == 400 and "Apaga el servidor" in r.get("error", ""), "con el servidor encendido no toca los mods")
stop(O)
NO = mk("neoforge", "1.21.1", "Neo optimizado")
jar(NO, "lithium-viejo.jar", "lithium", "neoforge", name="Lithium")
os.replace(os.path.join(sdir(NO), "mods", "lithium-viejo.jar"), os.path.join(sdir(NO), "mods", "lithium-viejo.jar.disabled"))
st, r = call(f"servers/{NO}/rendimiento", "POST")
ok(st == 200 and r["added"] == ["ModernFix 5.24.0", "FerriteCore 7.0.2"] and r["had"] == ["Lithium"],
   f"NeoForge 1.21.1: respeta Lithium desactivado a propósito y agrega los otros: {r.get('message')}")
VA = mk("vanilla", "1.21.8", "Solo vanilla")
st, r = call(f"servers/{VA}/rendimiento", "POST")
ok(st == 400 and "Fabric, Forge o NeoForge" in r.get("error", "") and srv(VA)["perf_mods"] is False, "en Vanilla lo explica (no aplica)")


print("\n== R18) NeoForge falla con código 0 (como el ATM10 de Max): igual se arregla y reactiva lo desactivado ==")
sh.STUCK_WAIT = 3
NJ = mk("neoforge", "1.21.1", "Codigo cero")
jar(NJ, "needsjei.jar", "needsjei", "neoforge", name="Needs Jei", deps=("jeidep",))
jar(NJ, "jeidep-1.0.jar", "jeidep", "neoforge", name="Jei Dep", deps=("jeiconfig",), display_test="IGNORE_SERVER_VERSION")
jar(NJ, "jeiconfig-1.0.jar", "jeiconfig", "neoforge", name="Jei Config")
disable(NJ, "jeidep-1.0.jar"); disable(NJ, "jeiconfig-1.0.jar")
w = Watch(NJ); start(NJ); d = final(NJ, 120); snaps = w.done()
ok(d["status"] == "en línea" and {"jeidep-1.0.jar", "jeiconfig-1.0.jar"} <= set(mods(NJ)),
   f"no lo tomó como un apagado normal: reactivó el mod que faltaba (y lo que ese mod necesita) y encendió: {mods(NJ)}")
ok(d["repairs"] == ["reactivé jeidep-1.0.jar, jeiconfig-1.0.jar (lo pedía needsjei)"], f"{d['repairs']}")
seen = {s for s, _p in snaps}
ok(seen <= {"iniciando", "reparando", "en línea"}, f"nunca muestra «Apagado» ni error: {sorted(seen)}")
ok("El servidor no pudo encender." in console(NJ) and "(código 0)" not in console(NJ), "dice que no pudo encender, sin el confuso «código 0»")
flog = open(os.path.join(sdir(NJ), "servidor-home.log"), encoding="utf-8").read()
ok("Arreglo automático: Reactivando jeidep" in flog and "Últimas líneas de la consola" in flog and "Failed to start the minecraft server" in flog,
   "queda todo anotado en servidor-home.log, en la carpeta del servidor")
stop(NJ)
st, _ = call(f"servers/{NJ}/command", "POST", {"command": "x"})
start(NJ); d = final(NJ); call(f"servers/{NJ}/command", "POST", {"command": "stop"})
d = wait(lambda: (lambda x: x if x["status"] in ("detenido", "error", "reparando") else None)(srv(NJ)), 30)
ok(d["status"] == "detenido" and not d.get("hint"), f"escribir «stop» en la consola sí es un apagado normal ({d['status']})")

print("\n== R19) Un mod necesita otro que es solo del jugador (Colorwheel → Iris) → desactiva el primero ==")
NS = mk("neoforge", "1.21.1", "Shaders")
jar(NS, "shaderaddon.jar", "shaderaddon", "neoforge", name="Shader Addon", deps=("iris",))
jar(NS, "iris-1.8.jar", "iris", "neoforge", name="Iris"); disable(NS, "iris-1.8.jar")
start(NS); d = final(NS)
ok(d["status"] == "en línea" and "shaderaddon.jar.disabled" in mods(NS) and "iris-1.8.jar.disabled" in mods(NS),
   f"no reactiva Iris en el servidor: desactiva el mod que lo pide: {mods(NS)}")
ok(d["repairs"] == ["desactivé shaderaddon.jar (necesita iris, que es solo del jugador)"], f"{d['repairs']}")
ok(meta(NS).get("client_mods", {}).get("shaderaddon.jar") == "necesita iris, que es solo del jugador", "lo recuerda como mod del jugador (va en el zip para los amigos)")
stop(NS)

print("\n== R20) Falla y Java queda abierto → lo cierra y lo arregla igual ==")
NH = mk("neoforge", "1.21.1", "Trabado")
jar(NH, "needsjei.jar", "needsjei", "neoforge", deps=("jeidep",)); jar(NH, "jeidep-1.0.jar", "jeidep", "neoforge"); jar(NH, "jeiconfig-1.0.jar", "jeiconfig", "neoforge")
disable(NH, "jeidep-1.0.jar")
open(os.path.join(sdir(NH), "hang-on-fail"), "w").write("x")
t0 = time.time(); start(NH); d = final(NH, 120)
ok(d["status"] == "en línea" and "jeidep-1.0.jar" in mods(NH) and "Java quedó abierto; lo cierro" in console(NH),
   f"cierra el Java trabado a los pocos segundos y sigue arreglando ({int(time.time() - t0)} s)")
stop(NH)

print("\n== R21) Dos mods que chocan y uno es solo del jugador → desactiva ese ==")
NI = mk("neoforge", "1.21.1", "Choque")
jar(NI, "choque.jar", "choque", "neoforge", name="Choque"); jar(NI, "oculus-1.0.jar", "oculus", "neoforge", name="Oculus")
start(NI); d = final(NI)
ok(d["status"] == "en línea" and "oculus-1.0.jar.disabled" in mods(NI) and "choque.jar" in mods(NI), f"{mods(NI)}")
ok(d["repairs"] == ["desactivé oculus-1.0.jar (chocaba con otro mod y es solo del jugador)"], f"{d['repairs']}")
stop(NI)

print("\n== R22) Un .jar dañado → lo desactiva ==")
FC = mk("fabric", "1.21.8", "Dañado")
jar(FC, "sano-1.0.jar", "sano")
open(os.path.join(sdir(FC), "mods", "roto-1.0.jar"), "wb").write(b"PK\x03\x04" + os.urandom(80))
start(FC); d = final(FC)
ok(d["status"] == "en línea" and "roto-1.0.jar.disabled" in mods(FC) and "sano-1.0.jar" in mods(FC), f"{mods(FC)}")
ok(d["repairs"] == ["desactivé roto-1.0.jar (el archivo estaba dañado)"], f"{d['repairs']}")
stop(FC)

print("\n== R23) Java no puede reservar tanta memoria → baja la RAM ==")
FH = mk("fabric", "1.21.8", "Poca memoria", ram=4096)
open(os.path.join(sdir(FH), "heap-fail"), "w").write("x")
start(FH); d = final(FH)
exp = max(1024, (min(int(4096 * 0.75), int(sh.total_ram_mb() * 0.6)) // 512) * 512)
ok(d["status"] == "en línea" and meta(FH)["ram_mb"] == exp and f"-Xmx{exp}M" in last_cmd(FH), f"4096 → {meta(FH)['ram_mb']} MB")
ok(d["repairs"] == [f"bajé la RAM de 4096 MB a {exp} MB"], f"{d['repairs']}")
stop(FH)

print("\n== R24) Una opción de Java que no existe → la quita ==")
FV = mk("fabric", "1.21.8", "Opcion rara")
call(f"servers/{FV}/settings", "PUT", {"java_opt": False, "jvm_args": "-XX:+OpcionQueNoExiste -Dcosa=1"})
start(FV); d = final(FV)
ok(d["status"] == "en línea" and meta(FV)["jvm_args"] == "-Dcosa=1" and "-Dcosa=1" in last_cmd(FV), f"quedan solo las que sirven: {meta(FV)['jvm_args']!r}")
ok(d["repairs"] == ["quité la opción de Java «OpcionQueNoExiste» de los argumentos extra de Java"], f"{d['repairs']}")
stop(FV)

print("\n== R25) Faltan archivos del loader → lo reinstala ==")
NR = mk("neoforge", "1.21.1", "Reinstalar")
os.remove(os.path.join(sdir(NR), "libraries", "net", "neoforged", "neoforge", "21.1.77", "unix_args.txt"))
w = Watch(NR); start(NR); d = final(NR, 120); snaps = w.done()
ok(d["status"] == "en línea" and os.path.isfile(os.path.join(sdir(NR), "libraries", "net", "neoforged", "neoforge", "21.1.77", "unix_args.txt")),
   "volvió a instalar NeoForge 21.1.77 y encendió")
ok(d["repairs"] == ["reinstalé los archivos de NeoForge (el mundo y los mods no se tocaron)"], f"{d['repairs']}")
ok({s for s, _p in snaps} <= {"iniciando", "reparando", "en línea"}, "sin pasar por error")
stop(NR)

print("\n== R26) Servidor importado con la versión anterior: reactiva una vez lo que se desactivó por error ==")
NM = mk("neoforge", "1.21.1", "Importado antes")
jar(NM, "ftbess-1.0.jar", "ftbess", "neoforge", name="FTB Ess", display_test="IGNORE_SERVER_VERSION"); disable(NM, "ftbess-1.0.jar")
jar(NM, "oculus-1.0.jar", "oculus", "neoforge", name="Oculus", display_test="IGNORE_SERVER_VERSION"); disable(NM, "oculus-1.0.jar")
jar(NM, "manual-1.0.jar", "manual", "neoforge", name="Manual"); disable(NM, "manual-1.0.jar")
jar(NM, "viejo-1.0.jar", "viejo", "neoforge", version="1.0", display_test="IGNORE_SERVER_VERSION"); disable(NM, "viejo-1.0.jar")
jar(NM, "viejo-2.0.jar", "viejo", "neoforge", version="2.0")
inst = sh.manager.servers[NM]
inst.meta["modpack"] = {"source": "Pack de antes", "kind": "instancia", "mods": 5}
inst.meta.pop("revision_mods", None); inst.save_meta()
start(NM); d = final(NM)
ok(d["status"] == "en línea" and "ftbess-1.0.jar" in mods(NM) and {"oculus-1.0.jar.disabled", "manual-1.0.jar.disabled", "viejo-1.0.jar.disabled"} <= set(mods(NM)),
   f"reactiva solo el que sirve en el servidor (no Oculus, ni el que se apagó a mano, ni la copia vieja): {mods(NM)}")
ok(d["repairs"] == ["reactivé 1 mod que la versión anterior de la app había desactivado por error: FTB Ess"], f"{d['repairs']}")
stop(NM)
call(f"servers/{NM}/addons?name=ftbess-1.0.jar", "PUT")
start(NM); d = final(NM)
ok("ftbess-1.0.jar.disabled" in mods(NM) and not d["repairs"] and meta(NM)["revision_mods"] == 1, "lo hace una sola vez: si después lo apagas a mano, se respeta")
stop(NM)

print("\n== S) Zip de mods para los amigos ==")
FS = mk("fabric", "1.21.8", "Compártelo Máx")
jar(FS, "comun-1.0.jar", "comun"); jar(FS, "soloserver-1.0.jar", "soloserver", env="server")
jar(FS, "grafico-1.0.jar", "grafico", env="client"); disable(FS, "grafico-1.0.jar")
jar(FS, "dupe-1.0.jar", "dupe", version="1.0"); disable(FS, "dupe-1.0.jar"); jar(FS, "dupe-2.0.jar", "dupe", version="2.0")
jar(FS, "apagado-1.0.jar", "apagado"); disable(FS, "apagado-1.0.jar")
jar(FS, "marcado-1.0.jar", "marcado"); disable(FS, "marcado-1.0.jar")
sh.manager.servers[FS].meta["client_mods"] = {"marcado-1.0.jar": "necesita iris, que es solo del jugador"}
for sub, f in (("startup_scripts", "items.js"), ("client_scripts", "jei.js"), ("server_scripts", "recetas.js"), ("assets/kubejs/textures", "x.png")):
    os.makedirs(os.path.join(sdir(FS), "kubejs", sub), exist_ok=True); open(os.path.join(sdir(FS), "kubejs", sub, f), "w").write("// " + f)
ok(srv(FS)["share"] is None, "al principio no hay zip")
st, r = call(f"servers/{FS}/compartir", "POST")
ok(st == 200 and r["share"]["estado"] in ("armando", "listo"), f"empieza a armarlo: {r['share']}")
sh_ = wait(lambda: (lambda x: x if x and x["estado"] in ("listo", "error") else None)(srv(FS)["share"]), 30)
ok(sh_["estado"] == "listo" and sh_["archivo"] == "Compartelo Max - mods para amigos.zip" and sh_["mods"] == 4 and sh_["cliente"] == 2,
   f"listo: {sh_}")
zp = os.path.join(sh.SHARE_DIR, sh_["archivo"])
with urllib.request.urlopen(A + f"servers/{FS}/compartir") as resp:
    body = resp.read(); cd = resp.headers.get("Content-Disposition", "")
ok(body == open(zp, "rb").read() and "filename*=UTF-8''" in cd and "Compartelo%20Max" in cd, f"se descarga (con el nombre bien escrito): {cd}")
names = sorted(zipfile.ZipFile(zp).namelist())
ok(names == ["LEEME.txt", "kubejs/assets/kubejs/textures/x.png", "kubejs/client_scripts/jei.js", "kubejs/startup_scripts/items.js",
             "mods/comun-1.0.jar", "mods/dupe-2.0.jar", "mods/grafico-1.0.jar", "mods/marcado-1.0.jar"],
   f"trae los mods activos y los del jugador; no los del servidor, ni copias viejas, ni los apagados a mano: {names}")
leeme = zipfile.ZipFile(zp).read("LEEME.txt").decode("utf-8")
ok("Fabric" in leeme and "Minecraft 1.21.8" in leeme and "%appdata%\\.minecraft" in leeme and "kubejs" in leeme and "2 que son solo para el jugador" in leeme,
   "el LEEME explica qué instalar y dónde copiar los mods")
ok(zipfile.ZipFile(zp).getinfo("mods/comun-1.0.jar").compress_type == zipfile.ZIP_STORED, "los .jar no se vuelven a comprimir (arma rápido)")
st, r = call(f"servers/{FS}/compartir", "POST"); wait(lambda: srv(FS)["share"]["estado"] == "listo", 30)
ok(sorted(os.listdir(sh.SHARE_DIR)).count(sh_["archivo"]) == 1 and not [f for f in os.listdir(sh.SHARE_DIR) if f.endswith(".armando")],
   "armarlo de nuevo reemplaza el anterior (sin archivos a medias)")
st, r = call(f"servers/{VA}/compartir", "POST")
ok(st == 400 and "no usa mods" in r.get("error", ""), "en Vanilla lo explica")

print("\n== I) Imagen del servidor y mensaje con colores ==")
st, r = call(f"servers/{FS}/icono", "PUT", raw=b"no es una imagen")
ok(st == 400 and "PNG" in r.get("error", ""), f"solo PNG: {r.get('error')}")
st, r = call(f"servers/{FS}/icono", "PUT", raw=make_png(32, 32))
ok(st == 400 and "64×64" in r.get("error", "") and "32×32" in r.get("error", ""), f"solo 64×64: {r.get('error')}")
png = make_png(64, 64)
st, r = call(f"servers/{FS}/icono", "PUT", raw=png)
ok(st == 200 and r["icon"] > 0 and open(os.path.join(sdir(FS), "server-icon.png"), "rb").read() == png, "guarda server-icon.png")
with urllib.request.urlopen(A + f"servers/{FS}/icono") as resp:
    ok(resp.read() == png and resp.headers.get("Content-Type") == "image/png", "la interfaz la puede mostrar")
st, r = call(f"servers/{FS}/icono", "DELETE")
ok(st == 200 and r["icon"] == 0 and not os.path.exists(os.path.join(sdir(FS), "server-icon.png")), "se puede quitar")
st, r = call(f"servers/{FS}/icono")
ok(st == 404, "sin imagen: 404")
st, r = call(f"servers/{FS}/properties", "PUT", {"properties": {"motd": "§aHola Máx\\nlínea 2"}})
rawp = open(os.path.join(sdir(FS), "server.properties"), encoding="utf-8").read()
ok("motd=\\u00a7aHola M\\u00e1x\\nl\\u00ednea 2" in rawp, "el mensaje se guarda con \\uXXXX (Minecraft lo lee bien en cualquier versión)")
ok(srv(FS)["properties"]["motd"] == "§aHola Máx\\nlínea 2", "y se lee de vuelta tal cual")


print("\n== R27) El log real del ATM10 de Max (NeoForge 1.21.1) ==")
atm = "/mnt/user-data/uploads/Documents/servidor home/servidores/all-the-mods-10-atm10"
am = os.path.join("/tmp", "atm-mods"); shutil.rmtree(am, ignore_errors=True); shutil.copytree(os.path.join(atm, "mods"), am)
lines = open(os.path.join(atm, "logs", "latest.log"), encoding="utf-8", errors="replace").read().splitlines()
probs = sh.find_problems(lines[-1000:], None, am)
got = [(p["fix"] or {}).get("type") + ":" + (p["fix"] or {}).get("file", "") for p in probs if p["auto"]]
ok(got == ["enable_mod:jei-1.21.1-neoforge-19.57.0.446.jar.disabled", "enable_mod:SmartBrainLib-neoforge-1.21.1-1.16.11.jar.disabled",
           "disable_client:colorwheel-neoforge-1.3.0-beta3+mc1.21.1.jar"],
   f"reactiva JEI y SmartBrainLib y desactiva Colorwheel (necesita Iris): {got}")
ok(not any((p["fix"] or {}).get("type") == "download_mod" for p in probs), "no intenta descargar de Modrinth lo que ya está en la carpeta")
infos = {f: sh.scan_mod_jar(os.path.join(am, f)) for f in os.listdir(am)}
ok(not infos["jei-1.21.1-neoforge-19.57.0.446.jar.disabled"]["client_only"] and infos["jei-1.21.1-neoforge-19.57.0.446.jar.disabled"]["ids"] == ["jei"],
   "JEI ya no se toma como mod solo del jugador (y se lee su mods.toml con comentarios)")

print("\n== R28) El log real de «un mundillo» de Max (Fabric 1.18.2 con Fabric Loader 0.19.5 y Not Enough Crashes) ==")
mund = "/mnt/user-data/uploads/Documents/servidor home/servidores/un-mundillo"
mm = os.path.join("/tmp", "mundillo-mods"); shutil.rmtree(mm, ignore_errors=True); shutil.copytree(os.path.join(mund, "mods"), mm)
for src in (open(os.path.join(mund, "logs", "latest.log"), encoding="utf-8", errors="replace").read(),
            open(os.path.join(mund, "servidor-home.log"), encoding="utf-8", errors="replace").read().split("2026-09-25 14:52:23")[-1]):
    probs = sh.find_problems(src.splitlines()[-1000:], None, mm)
    ok(probs and probs[0]["auto"] and probs[0]["fix"] == {"type": "downgrade_loader", "below": "0.15", "culprit": "Not Enough Crashes"},
       f"lo primero: cambiar a un Fabric Loader anterior a la 0.15 (culpable: Not Enough Crashes): {probs[:1]}")
    ok("Not Enough Crashes" in probs[0]["text"] and "0.19.5" in probs[0]["text"], "lo explica con el nombre del mod y la versión que tenía")
    ok(not any(p["key"] in ("reinstall", "client") or (p["fix"] or {}).get("type") in ("disable_client", "update_mod") for p in probs),
       f"no lo confunde con archivos que faltan ni con mods del jugador: {[p['key'] for p in probs]}")
    ok(any(p["key"] == "disable:notenoughcrashes-4.1.6+1.18.2-fabric.jar" and not p["auto"] for p in probs), "y ofrece (sin hacerlo solo) desactivar ese mod")
infos = [sh.scan_mod_jar(os.path.join(mm, f)) for f in sh.list_mod_files(mm)]
ok(sh.fabric_loader_bounds(infos) == ("0.14.8", None), f"los 146 mods piden Fabric Loader 0.14.8 o más nuevo, sin tope: {sh.fabric_loader_bounds(infos)}")
ok(sh.pick_fabric_loader("1.18.2", infos) == "0.14.25", "elige la última 0.14 (el modpack es de Minecraft 1.18.2)")
ok(sh.pick_fabric_loader("1.18.2", infos, prefer="0.14.9") == "0.14.9", "o la del launcher si la sabe")
ok(sh.launcher_loader_version("/mnt/user-data/uploads/valhelsia-enhanced-vanilla", "1.18.2") == "0.14.9", "lee la versión del registro de SKLauncher (0.14.9)")
ok(sh.pick_fabric_loader("1.21.1", infos) == "0.16.14" and sh.pick_fabric_loader("1.18.2", infos, below="0.14.20") == "0.14.9",
   "para Minecraft nuevo, la más nueva estable; con tope, la que calza")
rb = sh.fabric_range_bounds
ok(rb(">=0.14.8") == ("0.14.8", None) and rb("0.14.x") == ("0.14", "0.15.0") and rb("~0.14.21") == ("0.14.21", "0.15.0")
   and rb("<0.15") == (None, "0.15") and rb([">=0.14.6", ">=0.15"]) == ("0.14.6", None) and rb("*") == (None, None)
   and rb(">=0.14.10 <0.16") == ("0.14.10", "0.16") and rb("^0.14.9") == ("0.14.9", "0.15.0"), "entiende los rangos de versiones de Fabric")
brk = [{"names": ["A"], "deps": [{"id": "fabricloader", "range": ">=0.15", "incompatible": True}]},
       {"names": ["B"], "deps": [{"id": "fabricloader", "range": "<0.14.10", "incompatible": True}]}]
ok(sh.fabric_loader_bounds(brk, who=True) == ("0.14.10", "0.15", "B", "A"), f"y los «breaks»: {sh.fabric_loader_bounds(brk, who=True)}")
FakeS = type("S", (), {"meta": {"type": "fabric", "loader_version": "0.16.14", "mc_version": "1.18.2"}, "mods_dir": mm, "dir": "/tmp",
                       "world_dirs": lambda self: []})
old_api = ["[main/INFO]: Loading Minecraft 1.18.2 with Fabric Loader 0.16.14", "[main/ERROR]: Minecraft has crashed!",
           "Caused by: java.lang.NoClassDefFoundError: net/fabricmc/loader/launch/common/MappingConfiguration",
           "\tat com.example.Old.init(Old.java:3) ~[notenoughcrashes-4.1.6+1.18.2-fabric.jar:?]",
           "Caused by: java.lang.ClassNotFoundException: net.fabricmc.loader.launch.common.MappingConfiguration"]
pr = sh.find_problems(old_api, FakeS(), mm)
ok([p["key"] for p in pr][:1] == ["loader-old:0.16.14"] and pr[0]["fix"]["below"] == "0.15" and not any(p["key"] == "reinstall" for p in pr),
   f"otra clase que Fabric quitó en la 0.15 (y el culpable por su .jar): {[(p['key'], p['fix']) for p in pr]}")
pr = sh.find_problems(["Error: Could not find or load main class net.fabricmc.loader.impl.launch.knot.KnotServer",
                       "Caused by: java.lang.ClassNotFoundException: net.fabricmc.loader.impl.launch.knot.KnotServer"], FakeS(), mm)
ok([p["key"] for p in pr] == ["reinstall"], f"si Fabric Loader ni alcanzó a arrancar, es una instalación incompleta: {[p['key'] for p in pr]}")
new_api = ["[main/INFO]: Loading Minecraft 1.18.2 with Fabric Loader 0.14.9", "[main/ERROR]: Minecraft has crashed!",
           "Caused by: java.lang.NoClassDefFoundError: net/fabricmc/loader/api/metadata/ModOrigin"]
FakeS.meta = {"type": "fabric", "loader_version": "0.14.9", "mc_version": "1.18.2"}
ok(not any((p["fix"] or {}).get("type") == "downgrade_loader" for p in sh.find_problems(new_api, FakeS(), mm)),
   "con un loader antiguo no lo baja más (ahí el mod pide uno más nuevo)")

print("\n== R29) Fabric Loader demasiado nuevo para un mod antiguo → usa la versión del launcher y sube lo justo ==")
FL = mk("fabric", "1.18.2", "Mundillo falso")
ok(meta(FL)["loader_version"] == "0.16.14", "se creó con la recomendada (0.16.14), como le pasó a Max con la 0.19.5")
jar(FL, "oldcrash.jar", "oldcrash", name="Old Crash", ranges={"fabricloader": ">=0.14.0", "minecraft": "1.18.2"})
jar(FL, "needsnewfabric.jar", "needsnewfabric", name="Needs New Fabric")
jar(FL, "createlike.jar", "createlike", name="Create", ranges={"fabricloader": ">=0.14.8"})
lanz = "/tmp/lanzador-mundillo"; shutil.rmtree(lanz, ignore_errors=True); os.makedirs(os.path.join(lanz, "logs"))
open(os.path.join(lanz, "logs", "latest.log"), "w").write("[14:48:50] [main/INFO]: Loading Minecraft 1.18.2 with Fabric Loader 0.14.9\n")
with open(os.path.join(sdir(FL), "servidor-home.log"), "a", encoding="utf-8") as fh:    # importado con la 2.5.2: sin «path»
    fh.write(f"2026-09-24 21:27:53 Copiando el modpack desde {lanz} ...\r\n")   # como lo escribe Windows
os.makedirs(os.path.join(sdir(FL), "world"), exist_ok=True); open(os.path.join(sdir(FL), "world", "level.dat"), "w").write("mundo")
game = os.path.join(sdir(FL), ".fabric", "server"); os.makedirs(game, exist_ok=True)
open(os.path.join(game, "1.18.2-server.jar"), "w").write("minecraft")
open(os.path.join(game, "fabric-loader-server-0.16.14-minecraft-1.18.2.jar"), "w").write("arranque viejo")
os.makedirs(os.path.join(sdir(FL), ".fabric", "remappedJars", "minecraft-1.18.2-0.16.14"), exist_ok=True)
mock("/__reset-mr", {})
w = Watch(FL); start(FL); d = final(FL, 180); snaps = w.done()
m = meta(FL)
ok(d["status"] == "en línea" and m["loader_version"] == "0.14.25", f"encendió con Fabric Loader 0.14.25: {d['status']} / {m['loader_version']}")
ok([r for r in d["repairs"] if not r.startswith("respaldé")] == ["cambié Fabric Loader 0.16.14 por 0.14.9 (la misma con la que tu launcher abre este modpack)",
                                                                 "actualicé Fabric de 0.14.9 a 0.14.25"],
   f"primero la del launcher (0.14.9) y, como otro mod pidió la 0.14.21, la última 0.14 sin pasarse a la 0.15: {d['repairs']}")
ok(any(r.startswith("respaldé el mundo") for r in d["repairs"]) and len(backups(FL)) == 1, "respaldó el mundo antes de cambiar el loader")
ok(m.get("fabric_tope") == {"below": "0.15", "mod": "Old Crash"}, f"recuerda que no debe pasar de la 0.15 por Old Crash: {m.get('fabric_tope')}")
ok(open(os.path.join(game, "1.18.2-server.jar")).read() == "minecraft" and not os.path.exists(os.path.join(game, "fabric-loader-server-0.16.14-minecraft-1.18.2.jar"))
   and not os.path.exists(os.path.join(sdir(FL), ".fabric", "remappedJars", "minecraft-1.18.2-0.16.14")),
   "no vuelve a descargar Minecraft y quita lo del loader anterior")
fj = mock("/__state", {}).get("fabric_jars", [])
ok(fj[-2:] == ["1.18.2/0.14.9", "1.18.2/0.14.25"], f"descargó Fabric 0.14.9 y después 0.14.25: {fj[-3:]}")
ok({s for s, _p in snaps} <= {"iniciando", "reparando", "en línea"}, f"sin pasar por error ni apagado: {sorted({s for s, _p in snaps})}")
c = console(FL)
ok("El mod «Old Crash» es de antes de Fabric Loader 0.15" in c and "Arreglo automático: Cambiando Fabric Loader" in c, "la consola explica qué pasó y qué hizo")
stop(FL)
start(FL); d = final(FL)
ok(d["status"] == "en línea" and not d["repairs"] and meta(FL)["loader_version"] == "0.14.25", "la próxima vez enciende directo")
stop(FL)

print("\n== R30) Un mod antiguo y otro que pide Fabric Loader 0.15 → no hay versión que sirva: lo explica y ofrece desactivar ==")
FC = mk("fabric", "1.18.2", "Choque de loaders")
jar(FC, "oldcrash.jar", "oldcrash", name="Old Crash")
jar(FC, "needs015.jar", "needs015", name="Needs 015", ranges={"fabricloader": ">=0.15.0"})
start(FC); d = final(FC, 120)
h = d.get("hint") or {}
ok(d["status"] == "error" and meta(FC)["loader_version"] == "0.16.14", f"no cambia el loader: {d['status']} {meta(FC)['loader_version']}")
ok("No hay una versión de Fabric Loader anterior a la 0.15 que sirva para todos los mods («Needs 015» pide la 0.15.0 o más nueva)" in h.get("text", ""),
   f"explica por qué: {h.get('text')}")
ok((h.get("action") or {}).get("type") == "disable_content" and h["action"].get("file") == "oldcrash.jar", f"ofrece desactivar el mod antiguo: {h.get('action')}")
st, _r = call(f"servers/{FC}/fix", "POST", {"action": h["action"]}); d = final(FC, 120)
ok(d["status"] == "en línea" and "oldcrash.jar.disabled" in mods(FC) and meta(FC)["loader_version"] == "0.16.14",
   f"con el botón lo desactiva y enciende con la 0.16.14: {d['status']} {mods(FC)}")
stop(FC)

print("\n== I2) Importar una instancia de Fabric 1.18.2 que nunca se abrió (como la de SKLauncher) → Fabric Loader 0.14 ==")
sk = "/tmp/instancias-sk/mundillo-sk"; shutil.rmtree(sk, ignore_errors=True); os.makedirs(os.path.join(sk, "mods"))
jar(None, "oldcrash.jar", "oldcrash", name="Old Crash", ranges={"fabricloader": ">=0.14.0", "minecraft": "1.18.2"}, folder=os.path.join(sk, "mods"))
jar(None, "createlike.jar", "createlike", name="Create", ranges={"fabricloader": ">=0.14.8", "minecraft": "~1.18.2"}, folder=os.path.join(sk, "mods"))
jar(None, "shaders-new.jar", "shadersnew", name="Shaders New", env="client", ranges={"fabricloader": ">=0.15.0"}, folder=os.path.join(sk, "mods"))
st, j = call("import/folder", "POST", {"path": sk}); j = wait(lambda: (lambda x: x if x["status"] in ("listo", "error") else None)(call("import/" + j["id"])[1]))
a = j.get("analysis") or {}
ok(a.get("type") == "fabric" and a.get("mc_version") == "1.18.2" and a.get("loader_version") == "0.14.25"
   and "Fabric Loader elegido según lo que piden los mods" in (a.get("detected_from") or ""),
   f"elige Fabric Loader 0.14.25 (sin contar el mod del jugador que pide la 0.15): {a.get('loader_version')} / {a.get('detected_from')}")
call("import/" + j["id"], "DELETE")
os.makedirs(os.path.join(sk, "logs")); open(os.path.join(sk, "logs", "latest.log"), "w").write("[14:48:50] [main/INFO]: Loading Minecraft 1.18.2 with Fabric Loader 0.14.9\n")
st, j = call("import/folder", "POST", {"path": sk}); j = wait(lambda: (lambda x: x if x["status"] in ("listo", "error") else None)(call("import/" + j["id"])[1]))
a = j.get("analysis") or {}
ok(a.get("loader_version") == "0.14.9" and "registro del juego" in (a.get("detected_from") or ""), f"si el launcher ya lo abrió, usa su versión: {a.get('loader_version')}")
st, s2 = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "autostart": False, "disable": [c["file"] for c in a["client_only"]]})
IMP = s2["id"]; d = wait(lambda: (lambda x: x if x["status"] in ("detenido", "error") else None)(srv(IMP)), 120)
ok(d["status"] == "detenido" and meta(IMP)["loader_version"] == "0.14.9" and meta(IMP)["modpack"].get("path") == sk,
   f"lo instala con la 0.14.9 y guarda de dónde vino: {meta(IMP).get('modpack')}")
shutil.rmtree("/tmp/instancias-sk", ignore_errors=True)
# los servidores de 1.18.2 descargaron Java 17: se quita para que la prueba de la interfaz vea la descarga desde cero
shutil.rmtree(os.path.join(sh.JAVA_DIR, "17"), ignore_errors=True)

print("\n== R31) Varios mods del jugador fallan a la vez (como en «kyalita world») → los desactiva todos de una vez ==")
NK = mk("neoforge", "1.21.1", "Kyalita falso")
jar(NK, "hudmod.jar", "hudmod", "neoforge", name="Hud Mod")
with zipfile.ZipFile(os.path.join(sdir(NK), "mods", "weatherfx.jar"), "w") as z:          # mods.toml con líneas de Windows
    z.writestr("META-INF/neoforge.mods.toml", 'modLoader = "javafml"\r\nloaderVersion = "[2,)"\r\nlicense = "ARR"\r\n\r\n[[mods]]\r\n'
               'modId = "weatherfx"\r\nversion = "1.4"\r\ndisplayName = "Weather FX"\r\ndescription = \'\'\'Lluvia bonita.\r\n\'\'\'\r\n')
    z.writestr("com/example/weatherfx/Main.class", b"\xca\xfe\xba\xbe")
jar(NK, "noisy.jar", "noisy", "neoforge", name="Noisy")
ok(sh.scan_mod_jar(os.path.join(sdir(NK), "mods", "weatherfx.jar"))["ids"] == ["weatherfx"], "lee el mods.toml aunque tenga líneas de Windows")
w = Watch(NK); start(NK); d = final(NK, 120); snaps = w.done()
ok(d["status"] == "en línea" and {"hudmod.jar.disabled", "weatherfx.jar.disabled", "noisy.jar"} <= set(mods(NK)),
   f"desactivó los dos de una vez (y no el que solo avisaba): {mods(NK)}")
ok(d["repairs"] == ["desactivé hudmod.jar (es solo del jugador)", "desactivé weatherfx.jar (es solo del jugador)"], f"{d['repairs']}")
ok(console(NK).count("$ ") == 2, "con un solo reintento")
ok("El servidor no pudo encender por los mods «Hud Mod» y «Weather FX»." in console(NK), "el mensaje de error dice qué mods eran")
lst = {a["name"]: a for a in call(f"servers/{NK}/addons")[1]}
ok(lst["hudmod.jar.disabled"].get("why") == "Solo del jugador: es solo del jugador", f"la pestaña Mods dice por qué: {lst['hudmod.jar.disabled']}")
st, _r = call(f"servers/{NK}/addons?name=weatherfx.jar.disabled", "PUT")
ok("weatherfx.jar" not in (meta(NK).get("client_mods") or {}) and "weatherfx.jar" in mods(NK), "si lo activas a mano, la app olvida por qué lo había desactivado")
stop(NK)

print("\n== R32) Un mod con contenido falla y otro lo necesita → los desactiva a los dos (con respaldo) ==")
NC = mk("neoforge", "1.21.1", "Cascada")
start(NC); final(NC); stop(NC)
jar(NC, "broken-core.jar", "core", "neoforge", name="Core Lib")
jar(NC, "needscore.jar", "needscore", "neoforge", name="Needs Core", deps=("core",))
jar(NC, "otro.jar", "otro", "neoforge", name="Otro")
start(NC); d = final(NC, 120)
ok(d["status"] == "en línea" and {"broken-core.jar.disabled", "needscore.jar.disabled", "otro.jar"} <= set(mods(NC)),
   f"desactivó el que falla y el que lo necesita, nada más: {mods(NC)}")
ok(d["repairs"][:1] == ["desactivé broken-core.jar (fallaba al cargar); también el mod que lo necesita: Needs Core"] and len(backups(NC)) == 1,
   f"lo cuenta y respaldó el mundo: {d['repairs']}")
ok(meta(NC).get("broken_mods") == {"broken-core.jar": "fallaba al cargar", "needscore.jar": "necesita Core Lib, que se desactivó porque fallaba"},
   f"recuerda por qué: {meta(NC).get('broken_mods')}")
stop(NC)

print("\n== R33) Falla una librería que necesitan muchos mods → no la quita sola: lo explica y ofrece el botón ==")
NH = mk("neoforge", "1.21.1", "Librería")
jar(NH, "broken-hub.jar", "hub", "neoforge", name="Hub Lib")
for i in range(1, 10):
    jar(NH, f"hubdep{i}.jar", f"hubdep{i}", "neoforge", name=f"Hub Dep {i}", deps=("hub",))
start(NH); d = final(NH, 120)
h = d.get("hint") or {}
ok(d["status"] == "error" and d["error"] == "El servidor no pudo encender por el mod «Broken hub».", f"el error dice qué mod: {d['error']}")
ok("9 mods lo necesitan" in h.get("text", "") and "No lo desactivé solo" in h.get("text", ""), f"explica por qué no lo hizo solo: {h.get('text', '')[:220]}")
ok((h.get("action") or {}).get("label") == "Desactivar broken-hub.jar y los que lo necesitan" and all(f"hubdep{i}.jar" in mods(NH) for i in range(1, 10)),
   f"ofrece el botón y no tocó nada: {h.get('action')}")
call(f"servers/{NH}/fix", "POST", {"action": h["action"]}); d = final(NH, 120)
ok(d["status"] == "en línea" and "broken-hub.jar.disabled" in mods(NH) and all(f"hubdep{i}.jar.disabled" in mods(NH) for i in range(1, 10)),
   "con el botón desactiva todo y enciende")
stop(NH)

print("\n== R34) Sin lista de mods que fallaron: el rastro del error dice qué mod fue ==")
sm = "/tmp/stack-mods"; shutil.rmtree(sm, ignore_errors=True); os.makedirs(sm)
with zipfile.ZipFile(os.path.join(sm, "stackmod-2.0.jar"), "w") as z:
    z.writestr("META-INF/neoforge.mods.toml", '[[mods]]\nmodId="stackmod"\nversion="2.0"\ndisplayName="Stack Mod"\n')
    z.writestr("com/example/stackmod/Thing.class", b"\xca\xfe\xba\xbe")
tick = ["[Server thread/ERROR] [net.minecraft.server.MinecraftServer/]: Encountered an unexpected exception",
        "net.minecraft.ReportedException: Exception ticking world",
        "\tat net.minecraft.server.MinecraftServer.tickChildren(MinecraftServer.java:1000) ~[server-1.21.1.jar:?]",
        "Caused by: java.lang.NullPointerException: Cannot invoke \"Object.hashCode()\" because \"key\" is null",
        "\tat java.base/java.util.HashMap.hash(Unknown Source) ~[?:?]",
        "\tat com.example.stackmod.Thing.tick(Thing.java:5) ~[?:?]",
        "\tat net.minecraft.world.level.Level.tick(Level.java:10) ~[server-1.21.1.jar:?]"]
pr = sh.find_problems(tick, None, sm)
ok(pr and pr[0].get("mod") == "Stack Mod" and (pr[0]["fix"] or {}).get("type") == "disable_content" and not pr[0]["auto"],
   f"al encender: nombra el mod y ofrece desactivarlo con un botón: {[(p['key'], p.get('mod'), p['auto']) for p in pr]}")
ok(sh.crash_message(pr) == "El servidor no pudo encender; el error apunta al mod «Stack Mod».", sh.crash_message(pr))
pr = sh.find_problems(tick, None, sm, online=True)
ok(pr and pr[0].get("mod") == "Stack Mod" and not pr[0]["auto"] and sh.crash_message(pr, True) == "El servidor se cayó; el error apunta al mod «Stack Mod».",
   "con el servidor encendido: lo nombra y no lo toca solo (se reinicia)")
ky = "/mnt/user-data/uploads/Documents/servidor home/servidores/kyalita-world"
km = "/tmp/kyalita-mods"; shutil.rmtree(km, ignore_errors=True); shutil.copytree(os.path.join(ky, "mods"), km)
kl = open(os.path.join(ky, "logs", "latest.log"), encoding="utf-8", errors="replace").read().splitlines()
kr = open(os.path.join(ky, "crash-reports", "crash-2026-09-25_21.17.32-fml.txt"), encoding="utf-8", errors="replace").read().splitlines()
pr = sh.find_problems(kl[-1000:] + kr, None, km)
ok([((p["fix"] or {}).get("file"), p["auto"]) for p in pr] == [("WeatherRefind-neoforge-1.21.1-v1.4.jar", True), ("armor_hud-neoforge-1.1.1+mc1.21.1.jar", True)]
   and sh.crash_message(pr) == "El servidor no pudo encender por los mods «WeatherRefind» y «guy's Armor HUD».",
   f"el registro real de «kyalita world»: desactiva WeatherRefind y guy's Armor HUD y los nombra: {[(p['key'], p.get('mod')) for p in pr]}")
ok(sh.scan_mod_jar(os.path.join(km, "WeatherRefind-neoforge-1.21.1-v1.4.jar"))["client_only"], "y WeatherRefind ya se reconoce como mod del jugador al importar")

# Para la prueba de la interfaz: dos servidores que se arreglan solos (uno para dejarlo terminar y otro para cancelar)
UI = {"repair": mk("fabric", "1.21.8", "Reparable"), "cancel": mk("fabric", "1.21.8", "Cancelable"), "share": FS,
      "culprit": mk("neoforge", "1.21.1", "Con culpable")}
for k in (UI["repair"], UI["cancel"]):
    jar(k, "needslib.jar", "needslib")
jar(UI["culprit"], "broken-hubx.jar", "hubx", "neoforge", name="Hub X")          # queda en error, nombrando al mod
for i in range(1, 10):
    jar(UI["culprit"], f"hubxdep{i}.jar", f"hubxdep{i}", "neoforge", name=f"Hub X Dep {i}", deps=("hubx",))
start(UI["culprit"]); final(UI["culprit"], 120)
json.dump(UI, open("/home/claude/t2/ui_repair_ids.json", "w"))

print("\nLISTO" if not FAILS else f"\n{len(FAILS)} FALLAS: {FAILS}")
open("/home/claude/t2/ready", "w").write("1")
if os.environ.get("HARNESS_EXIT") == "1":
    sh.manager.shutdown_all(); httpd.shutdown(); os._exit(1 if FAILS else 0)
while True:
    time.sleep(1)
