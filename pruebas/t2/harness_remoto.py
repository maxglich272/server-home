"""Pruebas de borrar servidores y del acceso remoto (un amigo administra UN servidor desde su propio Servidor Home,
con mensajes cifrados a través de un buzón MQTT; aquí, un buzón local de prueba: mini_broker.py).
Necesita el mock encendido (mock2/mockserver.py) y el servidor falso compilado (mock2/construir_falso.sh)."""
import os, sys, json, time, threading, urllib.request, urllib.error, shutil, base64, socket
APP = "/home/claude/t2/app-remoto"
shutil.rmtree(APP, ignore_errors=True)
shutil.copytree("/home/claude/servidor-home", APP, ignore=shutil.ignore_patterns("__pycache__", "servidores", "ajustes.json"))
os.environ["HOME"] = "/home/claude/mock2/home"
B = "http://127.0.0.1:9911"
sys.path.insert(0, APP)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import servidor_home as sh
from mini_broker import MiniBroker
sh.MOJANG_MANIFEST = B + "/manifest.json"; sh.FABRIC_META = B + "/fabric"; sh.NEOFORGE_MAVEN = B + "/neoforge"
sh.PLAYIT_API = B; sh.PLAYIT_DOWNLOAD = B + "/playit-dl/"
sh.REMOTE_FILE = os.path.join(APP, "acceso-remoto.json"); sh.FRIENDS_FILE = os.path.join(APP, "amigos.json")
BROKER = MiniBroker()
dead = socket.socket(); dead.bind(("127.0.0.1", 0)); DEAD_PORT = dead.getsockname()[1]; dead.close()
# el primer buzón no existe: la app del amigo tiene que pasar sola al segundo
sh.REMOTE_TIMEOUT = 4
sh.REMOTE_BROKERS = [("127.0.0.1", DEAD_PORT, False), ("127.0.0.1", BROKER.port, False)]
sh.manager = sh.Manager()
sh.manager.playit = sh.Playit()
sh.manager.remote = sh.RemoteAccess()
sh.manager.friends = sh.RemoteFriends()        # la app del amigo: en la prueba es la misma, hablando por el buzón
PORT = int(os.environ.get("PORT", "8767"))
httpd = sh.ThreadingHTTPServer(("127.0.0.1", PORT), sh.Handler); sh.HTTPD = httpd
threading.Thread(target=httpd.serve_forever, daemon=True).start()
A = f"http://127.0.0.1:{PORT}/api/"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=200) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())


class Spy:
    """Alguien con acceso al buzón que escribe mensajes a mano y lee las respuestas."""
    def __init__(self, room):
        self.got = []
        self.c = sh.MqttClient("127.0.0.1", BROKER.port, False, lambda c, t, p: self.got.append(json.loads(p)))
        assert self.c.connected.wait(5)
        self.c.subscribe(room + "/r", wait=5)
        self.room = room

    def send(self, env, wait=3):
        n = len(self.got)
        self.c.publish(self.room + "/p", json.dumps(env).encode())
        t = time.time()
        while time.time() - t < wait and len(self.got) == n:
            time.sleep(0.05)
        return self.got[n] if len(self.got) > n else None


def wait(fn, timeout=40, step=0.3):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        time.sleep(step)
    raise AssertionError("timeout")


def srv(sid): return call("servers/" + sid)[1]
def status_is(sid, *st): return wait(lambda: (lambda x: x if x["status"] in st else None)(srv(sid)), 120)
FAILS = []
def ok(c, m):
    print(("OK   " if c else "FAIL ") + m, flush=True)
    if not c: FAILS.append(m)


print("== Servidores de prueba ==")
st, a = call("servers", "POST", {"type": "vanilla", "mc_version": "1.21.1", "name": "Mundo de Ana", "eula": True, "ram_mb": 1024})
ok(st == 201, "crea el servidor A")
st, b = call("servers", "POST", {"type": "vanilla", "mc_version": "1.21.1", "name": "Mundo Secreto", "eula": True, "ram_mb": 1024, "port": 25570})
ok(st == 201, "crea el servidor B")
SA, SB = a["id"], b["id"]
status_is(SA, "detenido"); status_is(SB, "detenido")

print("\n== Acceso remoto: invitaciones ==")
st, r = call(f"servers/{SA}/remoto")
ok(st == 200 and r["invites"] == [] and not r["listening"], f"sin invitaciones no se conecta a ningún buzón: {r}")
ok(call(f"servers/{SA}/remoto", "POST", {"name": "  "})[0] == 400, "pide el nombre de la persona")
st, r = call(f"servers/{SA}/remoto", "POST", {"name": "Beto"})
ok(st == 201 and r["listening"] and len(r["invites"]) == 1 and r["invites"][0]["name"] == "Beto", f"crea la invitación: {r}")
INV = sh.manager.remote.invites[0]
code = r["invites"][0]["code"]
ok(sh.parse_remote_code(code) == (INV["id"], INV["key"]) and len(INV["key"]) == 64, f"el código trae el id y una clave de 256 bits: {code}")
saved = json.load(open(sh.REMOTE_FILE))
ok(saved[0]["key"] == INV["key"] and oct(os.stat(sh.REMOTE_FILE).st_mode)[-3:] == "600", "guarda las invitaciones (permisos 600)")
r = wait(lambda: (lambda x: x if x["connected"] == 1 else None)(call(f"servers/{SA}/remoto")[1]), 15)
ok(r["connected"] == 1 and r["brokers"] == 2 and not r["error"], f"el dueño escucha en los buzones que responden: {r}")
ok(not sh.manager.playit.tunnels and "admin" not in json.dumps(sh.manager.playit.state()), "no toca playit.gg")
ROOM = sh.remote_room(INV["key"])
ok(INV["key"] not in ROOM and INV["id"] not in ROOM, "el nombre del buzón no revela la clave ni el id")

print("\n== Lo que ve alguien en el buzón ==")
spy = Spy(ROOM)
env = sh.remote_seal("00" * 32, b"pedido", INV["id"], {"method": "GET", "path": "estado"})
rep = spy.send(env)
ok(rep and rep.get("auth") and "ct" not in rep, f"rechaza un mensaje cifrado con otra clave: {rep}")
env = sh.remote_seal(INV["key"], b"pedido", "abcdefabcdef", {"method": "GET", "path": "estado"})
ok((spy.send(env) or {}).get("auth"), "rechaza un id que no es el de la invitación")
env = sh.remote_seal(INV["key"], b"pedido", INV["id"], {"method": "POST", "path": "comando", "body": {"command": "say secreto123"}})
wire = json.dumps(env)
ok("secreto123" not in wire and "comando" not in wire, "el pedido viaja cifrado (no se lee el comando)")
rep = spy.send(env)
ok(rep and "ct" in rep and "encendido" not in json.dumps(rep), "la respuesta también viaja cifrada")
inner, _, _ = sh.remote_open(INV["key"], b"respuesta", rep, bind=bytes.fromhex(env["nonce"]))
ok(inner["status"] == 400 and "encendido" in inner["data"]["error"], f"la respuesta se descifra con la clave: {inner}")
ok((spy.send(env) or {}).get("error") == "Pedido repetido.", "rechaza un pedido repetido")
try:
    sh.remote_open(INV["key"], b"respuesta", rep, bind=b"otro"); ok(False, "una respuesta no sirve para otro pedido")
except PermissionError:
    ok(True, "una respuesta no sirve para otro pedido")
env = sh.remote_seal(INV["key"], b"pedido", INV["id"], {"method": "GET", "path": "estado"})
ct = bytearray(base64.b64decode(env["ct"])); ct[3] ^= 1; env["ct"] = base64.b64encode(bytes(ct)).decode()
ok((spy.send(env) or {}).get("auth"), "rechaza un mensaje cambiado en el camino")
env = sh.remote_seal(INV["key"], b"pedido", INV["id"], {"method": "GET", "path": "estado"}, ts=time.time() - 3600)
ok((spy.send(env) or {}).get("error") == "hora", "rechaza pedidos con la hora muy distinta")
spy.c.close()

print("\n== La app del amigo ==")
ok(call("amigos", "POST", {"code": "hola"})[0] == 400, "rechaza algo que no es un código")
ok(call("amigos", "POST", {"code": code[:40]})[0] == 400, "rechaza un código cortado")
t0 = time.time()
st, r = call("amigos", "POST", {"code": "  " + code[:30] + "\n" + code[30:] + " "})
ok(st == 201 and r["name"] == "Mundo de Ana", f"agrega el servidor con el código (aunque venga con espacios), pasando solo al buzón que funciona: {r}")
ok(sh.manager.friends.best == 1, "recuerda el buzón que funcionó")
FID = r["id"]
st, lst = call("amigos")
ok(st == 200 and len(lst) == 1 and lst[0]["admin"] == "Beto" and "key" not in json.dumps(lst), f"lo lista sin mostrar la clave: {lst}")
ok(call("amigos", "POST", {"code": code})[0] == 201 and len(call("amigos")[1]) == 1, "agregarlo dos veces no lo repite")
page = urllib.request.urlopen(A.replace("/api/", "/remoto")).read().decode()
ok("Servidor de un amigo" in page and "/api/amigos/" in page, "sirve el panel del servidor del amigo en /remoto")
t0 = time.time(); st, r = call(f"amigos/{FID}/estado"); dt = time.time() - t0
ok(st == 200 and r["name"] == "Mundo de Ana" and r["admin"] == "Beto" and "path" not in r and "jvm_args" not in r, f"estado del servidor, sin rutas del PC: {r}")
ok(dt < 1, f"responde rápido ({dt:.2f} s)")
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
leaks = [t for t, p in BROKER.LOG if any(w in p for w in (b"Mundo", b"Alex", b"Pepito", b"max-players", b"Beto", b"join"))]
ok(BROKER.LOG and not leaks, f"en el buzón no se lee nada de lo que pasó ({len(BROKER.LOG)} mensajes)")
ok(all(t.startswith(sh.REMOTE_TOPIC) and INV["id"] not in t for t, _ in BROKER.LOG), "los temas del buzón no dicen de quién es")

print("\n== Buzón caído y vuelta ==")
BROKER.stop()
st, r = call(f"amigos/{FID}/estado")
ok(st == 400 and "buzón" in r["error"], f"si no hay buzón, lo dice: {r}")
BROKER2 = MiniBroker(BROKER.port)
BROKER = BROKER2
wait(lambda: sh.manager.remote.clients and any(c.connected.is_set() for c in sh.manager.remote.clients), 20)
st, r = wait(lambda: (lambda x: x if x[0] == 200 else None)(call(f"amigos/{FID}/estado")), 60, 1)
ok(st == 200, "cuando el buzón vuelve, las dos apps se reconectan solas")

print("\n== Quitar el acceso ==")
st, r = call(f"servers/{SA}/remoto", "POST", {"name": "Carla"})
INV2 = [i for i in sh.manager.remote.invites if i["name"] == "Carla"][0]
ok(call(f"servers/{SB}/remoto/{INV['id']}", "DELETE")[0] == 404, "no se quita un acceso desde otro servidor")
st, r = call(f"servers/{SA}/remoto/{INV['id']}", "DELETE")
ok(st == 200 and [i["name"] for i in r["invites"]] == ["Carla"], "quita el acceso de Beto")
st, r = call(f"amigos/{FID}/estado")
ok(st == 400 and "no responde" in r["error"], f"la app de Beto deja de recibir respuestas al tiro: {r}")
st, r = call("amigos", "POST", {"code": sh.remote_code(INV2)})
FID2 = r["id"]
ok(call(f"amigos/{FID2}/estado")[0] == 200, "la de Carla sigue entrando")
ok(call(f"amigos/{FID}", "DELETE")[0] == 200 and [f["id"] for f in call("amigos")[1]] == [FID2], "el amigo quita un servidor de su lista")

print("\n== Borrar un servidor encendido ==")
st, r = call(f"servers/{SA}", "DELETE")
ok(st == 200 and not os.path.exists(os.path.join(sh.SERVERS_DIR, SA)), f"lo apaga guardando el mundo y lo borra: {r}")
ok(SA not in [s["id"] for s in call("servers")[1]], "ya no aparece en la lista")
ok(not sh.manager.remote.invites and not sh.manager.remote.clients, "se quitan sus accesos remotos y, sin invitaciones, se desconecta de los buzones")
ok(call(f"amigos/{FID2}/estado")[0] == 400, "la app de Carla ya no recibe respuestas")
st, r = call(f"servers/{SB}", "DELETE")
ok(st == 200 and not os.path.exists(os.path.join(sh.SERVERS_DIR, SB)), "borra un servidor apagado")
ok(call(f"servers/{SB}", "DELETE")[0] == 404, "borrar dos veces responde «no encontrado»")

sh.manager.shutdown_all()
print(f"\n{len(FAILS)} fallas")
sys.exit(1 if FAILS else 0)
