"""Pruebas de borrar servidores y del acceso remoto (un amigo administra UN servidor desde su navegador).
Necesita el mock encendido (mock2/mockserver.py) y el servidor falso compilado (mock2/construir_falso.sh)."""
import os, sys, json, time, threading, urllib.request, urllib.error, shutil, hashlib, hmac, secrets
APP = "/home/claude/t2/app-remoto"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__", "servidores", "ajustes.json"))
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
import servidor_home as sh
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"
sh.REMOTE_FILE = os.path.join(APP, "acceso-remoto.json")
sh.Playit.start = lambda self: None          # sin el agente real: las pruebas llaman a refresh() a mano
os.makedirs(sh.PLAYIT_DIR, exist_ok=True)
open(os.path.join(sh.PLAYIT_DIR, "playit.toml"), "w").write('secret_key = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"\n')
sh.manager = sh.Manager()
sh.manager.playit = sh.Playit()
PORT = int(os.environ.get("PORT", "8767"))
sh.manager.remote = sh.RemoteAccess(PORT + sh.REMOTE_PORT_OFFSET)
httpd = sh.ThreadingHTTPServer(("127.0.0.1", PORT), sh.Handler); sh.HTTPD = httpd
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = f"http://127.0.0.1:{PORT}/api/"
R = f"http://127.0.0.1:{PORT + sh.REMOTE_PORT_OFFSET}"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=200) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())


def rcall(inv, path, method="GET", body=None, tamper=None, ts=None, raw_headers=None):
    """Como la página remoto.html: firma cada pedido con la clave del enlace."""
    target = "/r/api/" + path
    data = json.dumps(body).encode() if body is not None else b""
    ts = str(int(time.time()) if ts is None else ts)
    nonce = secrets.token_hex(16)
    msg = "\n".join([method, target, ts, nonce, hashlib.sha256(data).hexdigest()]).encode()
    sig = hmac.new(bytes.fromhex(inv["key"]), msg, hashlib.sha256).hexdigest()
    headers = {"X-SH-Id": inv["id"], "X-SH-Ts": ts, "X-SH-Nonce": nonce, "X-SH-Firma": sig, "Content-Type": "application/json"}
    if tamper:
        target, data = tamper(target, data)
    if raw_headers is not None:
        headers = raw_headers
    req = urllib.request.Request(R + target, data=data or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read()), headers
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read()), headers


def wait(fn, timeout=40, step=0.3):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(step)
    raise AssertionError("timeout")


def srv(sid): return call("servers/" + sid)[1]
def status_is(sid, *st): return wait(lambda: (lambda x: x if x["status"] in st else None)(srv(sid)), 120)
ok = lambda c, m: print(("OK   " if c else "FAIL ") + m, flush=True)
FAILS = []
_ok = ok
def ok(c, m):
    _ok(c, m)
    if not c: FAILS.append(m)


print("== Servidores de prueba ==")
st, a = call("servers", "POST", {"type": "vanilla", "mc_version": "1.21.1", "name": "Mundo de Ana", "eula": True, "ram_mb": 1024})
ok(st == 201, f"crea el servidor A: {a}")
st, b = call("servers", "POST", {"type": "vanilla", "mc_version": "1.21.1", "name": "Mundo Secreto", "eula": True, "ram_mb": 1024, "port": 25570})
ok(st == 201, f"crea el servidor B: {b}")
SA, SB = a["id"], b["id"]
status_is(SA, "detenido"); status_is(SB, "detenido")

print("\n== Acceso remoto: invitaciones ==")
st, r = call(f"servers/{SA}/remoto")
ok(st == 200 and r["invites"] == [] and not r["listening"], f"sin invitaciones no abre la puerta: {r}")
ok(call(f"servers/{SA}/remoto", "POST", {"name": "  "})[0] == 400, "pide el nombre de la persona")
st, r = call(f"servers/{SA}/remoto", "POST", {"name": "Beto"})
ok(st == 201 and r["listening"] and len(r["invites"]) == 1 and r["invites"][0]["name"] == "Beto", f"crea la invitación y abre la puerta: {r}")
INV = sh.manager.remote.invites[0]
ok(sh.manager.playit.admin_port == PORT + sh.REMOTE_PORT_OFFSET, "le pide a playit la dirección del acceso remoto")
saved = json.load(open(sh.REMOTE_FILE))
ok(saved[0]["key"] == INV["key"] and oct(os.stat(sh.REMOTE_FILE).st_mode)[-3:] == "600", "guarda las invitaciones (permisos 600)")

print("\n== playit.gg: segunda dirección (TCP) ==")
sh.manager.playit.refresh()           # crea el túnel de Minecraft y el del acceso remoto
time.sleep(2.3)
sh.manager.playit.refresh()
def mock_state():
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + "/__state", data=b"{}", method="POST", headers={"Authorization": "Agent-Key a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"})).read())
st_mock = mock_state()
kinds = sorted(t.get("kind") for t in st_mock["tunnels"])
ok(kinds == ["custom-tcp", "tunnel-type"], f"crea un túnel TCP aparte hacia la puerta remota: {kinds}")
adm = [t for t in st_mock["tunnels"] if t.get("kind") == "custom-tcp"][0]
ok({f["name"]: f["value"] for f in adm["fields"]} == {"local_ip": "127.0.0.1", "local_port": str(PORT + sh.REMOTE_PORT_OFFSET)}, f"el túnel apunta a 127.0.0.1:{PORT + sh.REMOTE_PORT_OFFSET}")
ok(sh.manager.playit.address() == "prueba-max.gl.joinmc.link", "la dirección de Minecraft sigue siendo la de Minecraft")
st, r = call(f"servers/{SA}/remoto")
link = r["invites"][0]["link"]
ok(r["address"] == "prueba-admin.gl.at.ply.gg:31337" and link == f"http://prueba-admin.gl.at.ply.gg:31337/#{INV['id']}.{INV['key']}", f"el enlace lleva la clave después del #: {link}")
sh.manager.playit.refresh()
ok(len(mock_state()["tunnels"]) == 2, "no crea túneles repetidos")

print("\n== La puerta remota ==")
html = urllib.request.urlopen(R + "/").read().decode()
ok("Acceso remoto" in html and "hmac256" in html, "sirve la página remoto.html")
for bad in ("/api/state", "/api/servers", "/index.html/../api/state", "/r/api/../api/servers"):
    try:
        urllib.request.urlopen(R + bad); code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    ok(code in (401, 404), f"no deja usar el panel del dueño por la puerta remota ({bad} → {code})")
st, r, _ = rcall(INV, "estado")
ok(st == 200 and r["name"] == "Mundo de Ana" and r["admin"] == "Beto" and "path" not in r and "jvm_args" not in r, f"estado del servidor concedido, sin rutas del PC: {r}")
st, r, _ = rcall({"id": INV["id"], "key": "00" * 16}, "estado")
ok(st == 401, "rechaza una firma con otra clave")
st, r, _ = rcall({"id": "abcdefabcdef", "key": INV["key"]}, "estado")
ok(st == 401 and "ya no existe" in r["error"], "rechaza invitaciones que no existen")
st, r, _ = rcall(INV, "estado", ts=int(time.time()) - 3600)
ok(st == 401, "rechaza pedidos viejos (hora)")
st, r, h = rcall(INV, "estado")
st2, r2, _ = rcall(INV, "estado", raw_headers=h)
ok(st == 200 and st2 == 401 and "repetido" in r2["error"], "rechaza un pedido repetido (la misma firma dos veces)")
st, r, _ = rcall(INV, "comando", "POST", {"command": "say hola"}, tamper=lambda t, d: (t, json.dumps({"command": "op Intruso"}).encode()))
ok(st == 401, "rechaza un cuerpo cambiado en el camino")
st, r, _ = rcall(INV, "consola?since=0", tamper=lambda t, d: ("/r/api/jugadores", d))
ok(st == 401, "rechaza una ruta cambiada en el camino")
try:
    urllib.request.urlopen(urllib.request.Request(R + "/r/api/estado")); code = 200
except urllib.error.HTTPError as e:
    code = e.code
ok(code == 401, "sin firma no entrega nada")

print("\n== Lo que puede hacer el amigo (solo en su servidor) ==")
st, r, _ = rcall(INV, "encender", "POST")
ok(st == 200, f"enciende: {r}")
status_is(SA, "en línea")
ok(srv(SB)["status"] == "detenido", "el otro servidor no se toca")
st, r, _ = rcall(INV, "comando", "POST", {"command": "join Alex"}); time.sleep(1)
st, r, _ = rcall(INV, "jugadores")
ok(st == 200 and any(p["name"] == "Alex" and p["online"] for p in r["players"]), f"ve a los jugadores: {r}")
st, r, _ = rcall(INV, "jugadores", "POST", {"action": "op", "name": "Alex"}); time.sleep(0.8)
st, r, _ = rcall(INV, "jugadores", "POST", {"action": "ban", "name": "Pepito", "reason": "grifeo"}); time.sleep(0.8)
st, r, _ = rcall(INV, "jugadores")
names = {p["name"]: p for p in r["players"]}
ok(names["Alex"]["op"] and names["Pepito"]["banned"], "hace admin y banea")
st, r, _ = rcall(INV, "consola?since=0")
text = "\n".join(l["s"] for l in r["lines"])
ok(st == 200 and "Beto enciende el servidor" in text and "(Beto desde el acceso remoto)" in text, "la consola muestra quién hizo qué")
st, r, _ = rcall(INV, "propiedades")
ok(st == 200 and "server-port" not in r and "max-players" in r, f"lee los ajustes del juego (sin el puerto): {sorted(r)}")
st, r, _ = rcall(INV, "propiedades", "PUT", {"properties": {"max-players": "7", "motd": "Hola §aAna"}})
props = sh.read_properties(os.path.join(sh.SERVERS_DIR, SA, "server.properties"))
ok(st == 200 and props["max-players"] == "7", "cambia ajustes del juego")
for k in ("server-port", "enable-rcon", "rcon.password", "query.port"):
    st, r, _ = rcall(INV, "propiedades", "PUT", {"properties": {k: "1"}})
    ok(st == 400, f"no deja cambiar {k}")
st, r, _ = rcall(INV, "respaldos", "POST")
ok(st == 200 and r["name"].startswith("respaldo-"), f"respalda el mundo: {r}")
for path, method in (("mods", "GET"), ("borrar", "POST"), ("version", "POST"), ("ajustes", "PUT"), (f"../servers/{SB}", "GET")):
    st, r, _ = rcall(INV, path, method, {} if method != "GET" else None)
    ok(st in (401, 404), f"no existe «{path}» en el acceso remoto ({st})")
st, r, _ = rcall(INV, "reiniciar", "POST")
ok(st == 200, "reinicia")
time.sleep(1)
status_is(SA, "en línea")

print("\n== Quitar el acceso ==")
st, r = call(f"servers/{SA}/remoto", "POST", {"name": "Carla"})
INV2 = [i for i in sh.manager.remote.invites if i["name"] == "Carla"][0]
ok(call(f"servers/{SB}/remoto/{INV['id']}", "DELETE")[0] == 404, "no se quita un acceso desde otro servidor")
st, r = call(f"servers/{SA}/remoto/{INV['id']}", "DELETE")
ok(st == 200 and [i["name"] for i in r["invites"]] == ["Carla"], "quita el acceso de Beto")
st, r, _ = rcall(INV, "estado")
ok(st == 401 and "ya no existe" in r["error"], "el enlace de Beto deja de funcionar al tiro")
ok(rcall(INV2, "estado")[0] == 200, "el de Carla sigue funcionando")

print("\n== Borrar un servidor encendido ==")
st, r = call(f"servers/{SA}", "DELETE")
ok(st == 200 and not os.path.exists(os.path.join(sh.SERVERS_DIR, SA)), f"lo apaga guardando el mundo y lo borra: {r}")
ok(SA not in [s["id"] for s in call("servers")[1]], "ya no aparece en la lista")
ok(not any(i["server"] == SA for i in sh.manager.remote.invites), "se quitan sus accesos remotos")
st, r, _ = rcall(INV2, "estado")
ok(st == 401, "el enlace de su servidor deja de funcionar")
st, r = call(f"servers/{SB}", "DELETE")
ok(st == 200 and not os.path.exists(os.path.join(sh.SERVERS_DIR, SB)), "borra un servidor apagado")
ok(call(f"servers/{SB}", "DELETE")[0] == 404, "borrar dos veces responde «no encontrado»")

sh.manager.shutdown_all()
print(f"\n{len(FAILS)} fallas")
sys.exit(1 if FAILS else 0)
