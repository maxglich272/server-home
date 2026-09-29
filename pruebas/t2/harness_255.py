"""Pruebas de la 2.5.5: buscador de modpacks (Modrinth y CurseForge), jugadores, reiniciar y el diagnóstico de mixins."""
import os, sys, json, time, threading, urllib.request, shutil, glob
APP = "/home/claude/t2/app255"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__", "servidores", "ajustes.json"))
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
import servidor_home as sh
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"; sh.MRPACK_HOSTS.add("127.0.0.1")
sh.MODRINTH_API = B + "/modrinth-api/v2"; sh.CURSEFORGE_API = B + "/cf-api/v1"
sh.manager = sh.Manager()
PORT = int(os.environ.get("PORT", "8766"))
httpd = sh.ThreadingHTTPServer(("127.0.0.1", PORT), sh.Handler); sh.HTTPD = httpd
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = f"http://127.0.0.1:{PORT}/api/"
def call(path, method="GET", body=None, raw=None):
    data = json.dumps(body).encode() if body is not None else raw
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
def wait(fn, timeout=40, step=0.3):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(step)
    raise AssertionError("timeout")
def wait_import(jid):
    return wait(lambda: (lambda j: j if j["status"] in ("listo", "error") else None)(call("import/" + jid)[1]))
def srv(sid): return call("servers/" + sid)[1]
def online(sid, timeout=90): return wait(lambda: (lambda x: x if x["status"] == "en línea" or (x["status"] == "error" and not x.get("progress")) else None)(srv(sid)), timeout)
def log_of(sid): return "\n".join(f"  [{l['k']}] {l['s']}" for l in call(f"servers/{sid}/log?since=0")[1]["lines"])
ok = lambda c, m: print(("OK   " if c else "FAIL ") + m, flush=True)

print("== Modrinth ==")
st, r = call("packs/search?src=modrinth&q=volcanes")
ok(st == 200 and r["items"] and r["items"][0]["title"] == "Volcanes de Prueba" and r["items"][0]["loaders"] == ["neoforge"], f"busca modpacks: {r}")
st, r = call("packs/search?src=modrinth&q=")
ok(st == 200 and any(not i["server"] for i in r["items"]), "sin texto lista los más descargados y marca los que no sirven en servidor")
st, vs = call("packs/versions?src=modrinth&id=volcanes")
ok(st == 200 and vs[0]["id"] == "volc10" and vs[0]["mc"] == ["1.21.1"], f"lista versiones: {vs}")
st, r = call("packs/versions?src=modrinth&id=../../etc")
ok(st == 400, "rechaza ids raros")
st, j = call("packs/import", "POST", {"src": "modrinth", "project": "volcanes", "version": "volc10", "title": "Volcanes de Prueba"})
j = wait_import(j["id"]); a = j["analysis"]
ok(j["status"] == "listo" and a["type"] == "neoforge" and a["mc_version"] == "1.21.1" and a["download_count"] == 3, f"descarga el .mrpack y lo analiza: {a and {k: a[k] for k in ('type','mc_version','loader_version','download_count','mods_count')}} {j.get('error')}")
ok([c["file"] for c in a["client_only"]] == ["zoomify-neoforge-1.0.jar"], "no descarga lo que el pack marca solo-cliente")
ok(not glob.glob(os.path.join(sh.UPLOADS_DIR, "*volcanes*")), "borra el .mrpack descargado después de analizarlo")
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "ram_mb": 2048, "name": "Volcanes", "autostart": True, "disable": []})
sid = s["id"]
d = online(sid)
mods = sorted(os.listdir(os.path.join(sh.SERVERS_DIR, sid, "mods")))
ok(d["status"] == "en línea", "el servidor del buscador enciende: " + d["status"] + ("" if d["status"] == "en línea" else log_of(sid)[-2000:]))
ok("sodium-neoforge-9.9.jar.disabled" in mods and "balm-neoforge-1.21.1-21.0.20.jar" in mods and not any("zoomify" in m for m in mods),
   f"después de bajar los mods desactiva los del jugador que el pack no marcó: {mods}")
ok(os.path.exists(os.path.join(sh.SERVERS_DIR, sid, "config", "volcanes.toml")), "copia las overrides del pack")

print("\n== Jugadores con el servidor encendido ==")
call(f"servers/{sid}/command", "POST", {"command": "join Alex"}); call(f"servers/{sid}/command", "POST", {"command": "join Bea"})
time.sleep(1.2)
st, pl = call(f"servers/{sid}/players")
names = {p["name"]: p for p in pl["players"]}
ok(pl["running"] and names.get("Alex", {}).get("online") and names.get("Bea", {}).get("online") and names["Alex"]["seen"], f"lista a los conectados: {pl}")
st, r = call(f"servers/{sid}/players", "POST", {"action": "op", "name": "Alex"}); time.sleep(0.8)
st, r = call(f"servers/{sid}/players", "POST", {"action": "kick", "name": "Bea"}); time.sleep(0.8)
st, r = call(f"servers/{sid}/players", "POST", {"action": "ban", "name": "Pepito", "reason": "grifeo"}); time.sleep(0.8)
st, pl = call(f"servers/{sid}/players"); names = {p["name"]: p for p in pl["players"]}
ok(names["Alex"]["op"] and not names["Bea"]["online"] and names.get("Pepito", {}).get("banned"), f"admin, expulsar y banear por consola: {[(p['name'], p['online'], p['op'], p['banned']) for p in pl['players']]}")
ok(call(f"servers/{sid}/players", "POST", {"action": "op", "name": "a b"})[0] == 400, "rechaza nombres inválidos")
ok(call(f"servers/{sid}/players", "POST", {"action": "borrar", "name": "Alex"})[0] == 400, "rechaza acciones desconocidas")

print("\n== Reiniciar ==")
st, r = call(f"servers/{sid}/restart", "POST")
seen = set()
def reboot():
    x = srv(sid); seen.add(x["status"]); return x if x["status"] == "en línea" and ("iniciando" in seen or "deteniendo" in seen) else None
wait(reboot, 60, 0.2)
ok("deteniendo" in seen or "iniciando" in seen, f"reiniciar apaga y vuelve a encender: {seen}")
st, pl = call(f"servers/{sid}/players")
ok(not any(p["online"] for p in pl["players"]) and any(p["name"] == "Alex" for p in pl["players"]), "tras reiniciar nadie aparece conectado, pero se recuerda a los que entraron")

print("\n== Jugadores con el servidor apagado ==")
call(f"servers/{sid}/stop", "POST"); wait(lambda: srv(sid)["status"] == "detenido", 30)
call(f"servers/{sid}/properties", "PUT", {"properties": {"online-mode": "false"}})
st, r = call(f"servers/{sid}/players", "POST", {"action": "whitelist_add", "name": "Carla"})
ok(st == 200 and r["via"] == "archivos", "con el servidor apagado edita los archivos")
wl = json.load(open(os.path.join(sh.SERVERS_DIR, sid, "whitelist.json")))
ok(any(e["name"] == "Carla" and e["uuid"] == sh.offline_uuid("Carla") for e in wl), f"whitelist.json con el UUID no premium: {wl}")
import uuid as _u
ok(sh.offline_uuid("Carla") == str(_u.UUID(bytes=bytes(__import__('hashlib').md5(b'OfflinePlayer:Carla').digest()), version=3)), "UUID no premium igual al de Minecraft")
st, r = call(f"servers/{sid}/players", "POST", {"action": "pardon", "name": "Pepito"})
st, r = call(f"servers/{sid}/players", "POST", {"action": "deop", "name": "Alex"})
st, pl = call(f"servers/{sid}/players"); names = {p["name"]: p for p in pl["players"]}
ok(not names.get("Pepito", {}).get("banned") and not names["Alex"]["op"] and names["Carla"]["whitelisted"], "desbanear, quitar admin y lista blanca sin encender")
ok(call(f"servers/{sid}/players", "POST", {"action": "kick", "name": "Alex"})[0] == 400, "expulsar con el servidor apagado da un aviso")
call(f"servers/{sid}/start", "POST"); online(sid)
ok(any(e["name"] == "Carla" for e in json.load(open(os.path.join(sh.SERVERS_DIR, sid, "whitelist.json")))), "los cambios siguen al encender")
call(f"servers/{sid}/stop", "POST"); wait(lambda: srv(sid)["status"] == "detenido", 30)

print("\n== CurseForge ==")
st, r = call("packs/search?src=curseforge&q=")
ok(st == 200 and r.get("need_key"), "sin clave pide la clave")
st, r = call("packs/curseforge-key", "PUT", {"key": "clave-que-no-sirve-000"})
ok(st == 400 and "rechazó" in r.get("error", ""), f"una clave mala no se guarda: {r}")
st, r = call("packs/curseforge-key", "PUT", {"key": "clave-de-prueba-123456"})
ok(st == 200 and r["set"] and r["hint"] == "…3456", f"guarda la clave y solo muestra el final: {r}")
st, r = call("packs/curseforge-key")
ok(r == {"set": True, "hint": "…3456"}, "la clave no se devuelve completa")
st, r = call("packs/search?src=curseforge&q=pack")
ok(st == 200 and r["items"][0]["title"] == "Pack CF" and r["items"][0]["loaders"] == ["neoforge"], f"busca en CurseForge: {r}")
st, vs = call("packs/versions?src=curseforge&id=900")
ok([v["id"] for v in vs] == [9001, 9003] and vs[0]["server_pack"] and not vs[1]["server_pack"], f"versiones con y sin pack de servidor: {vs}")
st, j = call("packs/import", "POST", {"src": "curseforge", "project": 900, "version": 9001})
j = wait_import(j["id"]); a = j["analysis"]
ok(j["status"] == "listo" and a["pack_kind"] == "pack de servidor" and a["loader_version"] == "21.1.77", f"usa el pack de servidor: {a and a['pack_kind']} {j.get('error')}")
call("import/" + j["id"], "DELETE")
st, j = call("packs/import", "POST", {"src": "curseforge", "project": 900, "version": 9003})
j = wait_import(j["id"]); a = j["analysis"]
ok(j["status"] == "listo" and a["pack_kind"].startswith("CurseForge") and a["download_count"] == 2, f"sin pack de servidor arma la lista de mods: {a and {k: a[k] for k in ('pack_kind','download_count','type','loader_version')}} {j.get('error')}")
ok([c["file"] for c in a["client_only"]] == ["fancyhud-1.0.jar"], f"deja fuera lo que CurseForge marca solo-cliente: {a and a['client_only']}")
st, s = call(f"import/{j['id']}/confirm", "POST", {"eula": True, "ram_mb": 2048, "name": "Pack CF", "autostart": False, "disable": []})
sid2 = s["id"]
d = wait(lambda: (lambda x: x if x["status"] in ("detenido", "error") and not x.get("progress") else None)(srv(sid2)), 60)
mods = sorted(os.listdir(os.path.join(sh.SERVERS_DIR, sid2, "mods")))
ok(mods == ["Mod Con Espacios 1.0.jar", "balm-neoforge-1.21.1-21.0.20.jar"], f"descarga los mods (también con espacios en el nombre): {mods} {d['status']} {d.get('error')}")
ok(not any(n.endswith(".zip") for n in mods) and os.path.exists(os.path.join(sh.SERVERS_DIR, sid2, "config", "packcf.toml")), "sin texturas y con la configuración del pack")
# un zip de CurseForge subido a mano también funciona ahora (con la clave)
import zipfile, io
st, j = call("import/upload?name=PackCF-0.9.zip", "POST", raw=__import__("urllib.request").request.urlopen(B + "/cf-files/PackCF-0.9.zip").read())
j = wait_import(j["id"])
ok(j["status"] == "listo" and j["analysis"]["download_count"] == 2, "un .zip de CurseForge subido a mano se importa con la clave")
call("import/" + j["id"], "DELETE")
call("packs/curseforge-key", "PUT", {"key": ""})
st, j = call("import/upload?name=PackCF-0.9.zip", "POST", raw=urllib.request.urlopen(B + "/cf-files/PackCF-0.9.zip").read())
j = wait_import(j["id"])
ok(j["status"] == "error" and "clave" in j["error"], "sin clave explica cómo seguir: " + str(j.get("error")))

print("\n== Diagnóstico: mixin que falla al entrar un jugador ==")
D = "/mnt/user-data/uploads/Documents/servidor home/servidores/create-volcanes-y-estrellas"
if os.path.isdir(D):
    md = os.path.join(APP, "diag-mods"); os.makedirs(md, exist_ok=True)
    def mk(n, mid):
        with zipfile.ZipFile(os.path.join(md, n), "w") as z:
            z.writestr("META-INF/neoforge.mods.toml", f'modLoader="javafml"\nloaderVersion="[1,)"\nlicense="x"\n[[mods]]\nmodId="{mid}"\nversion="1"\n')
    mk("cbcmodernwarfare-0.0.6v+mc.1.21.1-neoforge.jar", "cbcmodernwarfare"); mk("modernfix-neoforge-5.27.24+mc1.21.1.jar", "modernfix")
    recent = open(D + "/logs/latest.log", encoding="utf-8", errors="replace").read().splitlines()[-400:]
    reps = []
    for f in sorted(glob.glob(D + "/crash-reports/*"))[-2:]:
        reps += open(f, encoding="utf-8", errors="replace").read().splitlines()
    probs = sh.find_problems(recent + reps, None, md, online=True)
    ok(probs and probs[0]["key"] == "update:cbcmodernwarfare" and not any(p["key"] == "maxtick" for p in probs),
       f"culpa a CBC Neo Warfare y no al vigilante ni a ModernFix: {[p['key'] for p in probs]}")
else:
    print("(sin los registros reales, se salta)")
print("FIN", flush=True)
os._exit(0)
