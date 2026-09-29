"""Pruebas de borrar servidores y del acceso remoto (un amigo administra UN servidor desde su propio Servidor Home).
Necesita el mock encendido (mock2/mockserver.py) y el servidor falso compilado (mock2/construir_falso.sh)."""
import os, sys, json, time, threading, urllib.request, urllib.error, shutil, base64
APP = "/home/claude/t2/app-remoto"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__", "servidores", "ajustes.json"))
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
import servidor_home as sh
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"
sh.REMOTE_FILE = os.path.join(APP, "acceso-remoto.json"); sh.FRIENDS_FILE = os.path.join(APP, "amigos.json")
sh.Playit.start = lambda self: None          # sin el agente real: las pruebas llaman a refresh() a mano
os.makedirs(sh.PLAYIT_DIR, exist_ok=True)
open(os.path.join(sh.PLAYIT_DIR, "playit.toml"), "w").write('secret_key = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"\n')
sh.manager = sh.Manager()
sh.manager.playit = sh.Playit()
PORT = int(os.environ.get("PORT", "8767"))
sh.manager.remote = sh.RemoteAccess(PORT + sh.REMOTE_PORT_OFFSET)
sh.manager.friends = sh.RemoteFriends()        # la app del amigo: en la prueba es la misma, hablando con su propia puerta
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


def door(env, path=None, method="POST"):
    """Un mensaje crudo a la puerta del dueño, como lo vería alguien en el camino."""
    data = json.dumps(env).encode() if env is not None else None
    req = urllib.request.Request(R + (path or sh.REMOTE_PATH), data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()


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
code = r["invites"][0]["code"]
ok(r["address"] == "prueba-admin.gl.at.ply.gg:31337" and sh.parse_remote_code(code) == ("prueba-admin.gl.at.ply.gg:31337", INV["id"], INV["key"]), f"el código lleva la dirección y la clave: {code}")
ok(len(INV["key"]) == 64, "clave de 256 bits")
sh.manager.playit.refresh()
ok(len(mock_state()["tunnels"]) == 2, "no crea túneles repetidos")

print("\n== La puerta del dueño ==")
for path, method in (("/", "GET"), ("/index.html", "GET"), ("/api/state", "GET"), ("/r/api/estado", "GET"), ("/sh-remoto", "GET")):
    st, raw = door(None, path, method)
    ok(st == 404 and not raw, f"a un navegador no le responde nada ({method} {path} → {st})")
ok(door({"hola": 1})[0] == 401 and door(None)[0] == 401, "rechaza mensajes que no son de una app")
env = sh.remote_seal("00" * 32, b"pedido", INV["id"], {"method": "GET", "path": "estado"})
st, raw = door(env)
ok(st == 401 and b"Mundo" not in raw, "rechaza un mensaje cifrado con otra clave")
env = sh.remote_seal(INV["key"], b"pedido", "abcdefabcdef", {"method": "GET", "path": "estado"})
ok(door(env)[0] == 401, "rechaza invitaciones que no existen")
env = sh.remote_seal(INV["key"], b"pedido", INV["id"], {"method": "POST", "path": "comando", "body": {"command": "say secreto123"}})
wire = json.dumps(env)
ok("secreto123" not in wire and "comando" not in wire, "el pedido viaja cifrado (no se lee el comando)")
st, raw = door(env)
ok(st == 200 and b"Mundo" not in raw and b"status" not in raw, "la respuesta también viaja cifrada")
inner, _, _ = sh.remote_open(INV["key"], b"respuesta", json.loads(raw), bind=bytes.fromhex(env["nonce"]))
ok(inner["status"] == 400 and "encendido" in inner["data"]["error"], f"la respuesta se descifra con la clave: {inner}")
ok(door(env)[0] == 401, "rechaza un pedido repetido")
try:
    sh.remote_open(INV["key"], b"respuesta", json.loads(raw), bind=b"otro")
    ok(False, "una respuesta no sirve para otro pedido")
except PermissionError:
    ok(True, "una respuesta no sirve para otro pedido")
env = sh.remote_seal(INV["key"], b"pedido", INV["id"], {"method": "GET", "path": "estado"})
ct = bytearray(base64.b64decode(env["ct"])); ct[3] ^= 1; env["ct"] = base64.b64encode(bytes(ct)).decode()
ok(door(env)[0] == 401, "rechaza un mensaje cambiado en el camino")
env = sh.remote_seal(INV["key"], b"pedido", INV["id"], {"method": "GET", "path": "estado"}, ts=time.time() - 3600)
st, raw = door(env)
ok(st == 401 and json.loads(raw)["error"] == "hora", "rechaza pedidos con la hora muy distinta")

print("\n== La app del amigo ==")
LOCAL = sh.remote_code(f"127.0.0.1:{PORT + sh.REMOTE_PORT_OFFSET}", INV)      # el mismo código, apuntando a esta prueba
ok(call("amigos", "POST", {"code": "hola"})[0] == 400, "rechaza algo que no es un código")
ok(call("amigos", "POST", {"code": LOCAL[:40]})[0] == 400, "rechaza un código cortado")
st, r = call("amigos", "POST", {"code": "  " + LOCAL[:30] + "\n" + LOCAL[30:] + " "})
ok(st == 201 and r["name"] == "Mundo de Ana", f"agrega el servidor del amigo con el código (aunque venga con espacios): {r}")
FID = r["id"]
st, lst = call("amigos")
ok(st == 200 and len(lst) == 1 and lst[0]["admin"] == "Beto" and "key" not in lst[0], f"lo lista sin mostrar la clave: {lst}")
ok(call("amigos", "POST", {"code": LOCAL})[0] == 201 and len(call("amigos")[1]) == 1, "agregarlo dos veces no lo repite")
page = urllib.request.urlopen(A.replace("/api/", "/remoto")).read().decode()
ok("Servidor de un amigo" in page and "/api/amigos/" in page, "sirve el panel del servidor del amigo en /remoto")
st, r = call(f"amigos/{FID}/estado")
ok(st == 200 and r["name"] == "Mundo de Ana" and r["admin"] == "Beto" and "path" not in r and "jvm_args" not in r, f"estado del servidor, sin rutas del PC: {r}")
sh.manager.friends.offsets[INV["id"]] = -1000
st, r = call(f"amigos/{FID}/estado")
ok(st == 200 and abs(sh.manager.friends.offsets[INV["id"]]) < 5, "si los relojes no calzan, se corrige solo")

print("\n== Lo que puede hacer el amigo (solo en su servidor) ==")
st, r = call(f"amigos/{FID}/encender", "POST")
ok(st == 200, f"enciende: {r}")
status_is(SA, "en línea")
ok(srv(SB)["status"] == "detenido", "el otro servidor no se toca")
call(f"amigos/{FID}/comando", "POST", {"command": "join Alex"}); time.sleep(1)
st, r = call(f"amigos/{FID}/jugadores")
ok(st == 200 and any(p["name"] == "Alex" and p["online"] for p in r["players"]), "ve a los jugadores")
call(f"amigos/{FID}/jugadores", "POST", {"action": "op", "name": "Alex"}); time.sleep(0.8)
call(f"amigos/{FID}/jugadores", "POST", {"action": "ban", "name": "Pepito", "reason": "grifeo"}); time.sleep(0.8)
names = {p["name"]: p for p in call(f"amigos/{FID}/jugadores")[1]["players"]}
ok(names["Alex"]["op"] and names["Pepito"]["banned"], "hace admin y banea")
ok(call(f"amigos/{FID}/jugadores", "POST", {"action": "op", "name": "a b"})[0] == 400, "los errores llegan como errores")
text = "\n".join(l["s"] for l in call(f"amigos/{FID}/consola?since=0")[1]["lines"])
ok("Beto enciende el servidor" in text and "(Beto desde el acceso remoto)" in text, "la consola muestra quién hizo qué")
st, r = call(f"amigos/{FID}/propiedades")
ok(st == 200 and "server-port" not in r and "max-players" in r, "lee los ajustes del juego (sin el puerto)")
st, r = call(f"amigos/{FID}/propiedades", "PUT", {"properties": {"max-players": "7"}})
ok(st == 200 and sh.read_properties(os.path.join(sh.SERVERS_DIR, SA, "server.properties"))["max-players"] == "7", "cambia ajustes del juego")
for k in ("server-port", "enable-rcon", "rcon.password", "query.port"):
    ok(call(f"amigos/{FID}/propiedades", "PUT", {"properties": {k: "1"}})[0] == 400, f"no deja cambiar {k}")
st, r = call(f"amigos/{FID}/respaldos", "POST")
ok(st == 200 and r["name"].startswith("respaldo-"), "respalda el mundo")
for path, method in (("mods", "GET"), ("borrar", "POST"), ("version", "POST"), ("ajustes", "PUT"), (f"../servers/{SB}", "GET")):
    st, r = call(f"amigos/{FID}/{path}", method, {} if method != "GET" else None)
    ok(st == 404, f"no existe «{path}» en el acceso remoto ({st})")
ok(call(f"amigos/{FID}/reiniciar", "POST")[0] == 200, "reinicia")
time.sleep(1)
status_is(SA, "en línea")

print("\n== Quitar el acceso ==")
st, r = call(f"servers/{SA}/remoto", "POST", {"name": "Carla"})
INV2 = [i for i in sh.manager.remote.invites if i["name"] == "Carla"][0]
ok(call(f"servers/{SB}/remoto/{INV['id']}", "DELETE")[0] == 404, "no se quita un acceso desde otro servidor")
st, r = call(f"servers/{SA}/remoto/{INV['id']}", "DELETE")
ok(st == 200 and [i["name"] for i in r["invites"]] == ["Carla"], "quita el acceso de Beto")
st, r = call(f"amigos/{FID}/estado")
ok(st == 401 and r.get("auth") and "ya no existe" in r["error"], f"la app de Beto deja de entrar al tiro: {r}")
st, r = call("amigos", "POST", {"code": sh.remote_code(f"127.0.0.1:{PORT + sh.REMOTE_PORT_OFFSET}", INV2)})
FID2 = r["id"]
ok(call(f"amigos/{FID2}/estado")[0] == 200, "la de Carla sigue entrando")
ok(call(f"amigos/{FID}", "DELETE")[0] == 200 and [f["id"] for f in call("amigos")[1]] == [FID2], "el amigo quita un servidor de su lista")

print("\n== Borrar un servidor encendido ==")
st, r = call(f"servers/{SA}", "DELETE")
ok(st == 200 and not os.path.exists(os.path.join(sh.SERVERS_DIR, SA)), f"lo apaga guardando el mundo y lo borra: {r}")
ok(SA not in [s["id"] for s in call("servers")[1]], "ya no aparece en la lista")
ok(not any(i["server"] == SA for i in sh.manager.remote.invites), "se quitan sus accesos remotos")
ok(call(f"amigos/{FID2}/estado")[0] == 401, "la app de Carla ya no entra")
st, r = call(f"servers/{SB}", "DELETE")
ok(st == 200 and not os.path.exists(os.path.join(sh.SERVERS_DIR, SB)), "borra un servidor apagado")
ok(call(f"servers/{SB}", "DELETE")[0] == 404, "borrar dos veces responde «no encontrado»")
sh.manager.remote.stop()
st2, r2 = call(f"amigos/{FID2}/estado")
ok(st2 == 400 and "No pude conectarme" in r2["error"], f"si el PC del dueño no responde, lo dice: {r2}")

sh.manager.shutdown_all()
print(f"\n{len(FAILS)} fallas")
sys.exit(1 if FAILS else 0)
