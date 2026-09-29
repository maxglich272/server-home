# Actualizaciones automáticas de punta a punta, con procesos reales: una copia «instalada» de la app revisa un
# GitHub simulado, descarga la versión nueva, comprueba firma y SHA-256, prueba el código, la instala cuando
# corresponde (botón, al abrir, o sola sin ventana ni servidores), se reinicia, vuelve atrás si la versión
# nueva no arranca y rechaza paquetes falsos, alterados o rotos.
import os, sys, json, time, shutil, subprocess, threading, urllib.request, urllib.error, re, zipfile, hashlib, base64

T = "/home/claude/t2/upd"
APP = T + "/app"
SRC = "/home/claude/servidor-home"
PUB = "/home/claude/mock2/www/gh"
B = "http://127.0.0.1:9911"
PORT = 8781
A = f"http://127.0.0.1:{PORT}/api/"
FAILS = []
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
sys.path.insert(0, "/home/claude/build")
import publicar  # noqa: E402


def ok(c, m):
    print(("OK   " if c else "FAIL ") + m, flush=True)
    if not c:
        FAILS.append(m)


def wait(fn, timeout=60, step=0.3):
    t = time.time()
    while time.time() - t < timeout:
        try:
            v = fn()
        except Exception:
            v = None
        if v:
            return v
        time.sleep(step)
    return None


def call(path, method="GET", body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST", "PUT") else None)
    req = urllib.request.Request(A + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def info():
    try:
        return call("info", timeout=3)[1]
    except Exception:
        return None


def upd():
    return (info() or {}).get("update") or {}


def mock_state():
    req = urllib.request.Request(B + "/__state", data=b"{}", method="POST",
                                 headers={"Authorization": "Agent-Key a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"})
    return json.loads(OPENER.open(req).read())


# ---- claves de prueba (la real no se usa en las pruebas)
shutil.rmtree(T, ignore_errors=True)
os.makedirs(T + "/home")
shutil.rmtree(PUB, ignore_errors=True)
os.makedirs(PUB + "/latest")


def new_key(name):
    pem = f"{T}/{name}.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", pem], check=True, capture_output=True)
    txt = subprocess.run(["openssl", "rsa", "-in", pem, "-noout", "-text"], capture_output=True, text=True).stdout
    def field(f):
        m = re.search(f + r":\s*\n((?:\s+[0-9a-f:]+\n)+)", txt)
        return int(re.sub(r"[\s:]", "", m.group(1)), 16)
    key = {"n": format(field("modulus"), "x"), "d": format(field("privateExponent"), "x"), "e": 65537}
    json.dump(key, open(f"{T}/{name}.json", "w"))
    return key


KEY, OTHER = new_key("clave"), new_key("otra")


def with_key(text, n_hex):
    return re.sub(r"^UPDATE_KEY_N = int\(.*?, 16\)", f'UPDATE_KEY_N = int("{n_hex}", 16)', text, count=1, flags=re.S | re.M)


def make_source(version, breakage=None):
    d = f"{T}/src-{version}"
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__"))
    p = d + "/servidor_home.py"
    t = open(p, encoding="utf-8").read()
    t = re.sub(r'^APP_VERSION = "[^"]+"', f'APP_VERSION = "{version}"', t, count=1, flags=re.M)
    t = with_key(t, KEY["n"])
    if breakage == "arranque":        # carga bien, pero la app no llega a abrir
        t = t.replace("def main():\n", "def main():\n    raise SystemExit(3)\n", 1)
    if breakage == "sintaxis":
        t += "\ndef roto(:\n"
    open(p, "w", encoding="utf-8").write(t)
    return d


def resign(rel, man, key):
    text = json.dumps(man, ensure_ascii=False, indent=1)
    sig = publicar.rsa_sign(text.encode("utf-8"), key)
    json.dump({"manifiesto": text, "firma": base64.b64encode(sig).decode()}, open(rel + "/actualizacion.json", "w", encoding="utf-8"))


def publish(version, novedades=(), breakage=None, tamper=None):
    src = make_source(version, breakage)
    nov = f"{T}/nov-{version}.txt"
    open(nov, "w", encoding="utf-8").write("\n".join(novedades))
    out = f"{T}/pub"
    r = subprocess.run([sys.executable, "/home/claude/build/publicar.py", "--clave", f"{T}/clave.json", "--app", src,
                        "--sin-instalador", "--salida", out, "--novedades", nov], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rel = f"{out}/{version}"
    man = json.loads(json.load(open(rel + "/actualizacion.json", encoding="utf-8"))["manifiesto"])
    zpath = f"{rel}/{man['paquete']}"
    if tamper == "firma":             # firmado con otra clave
        resign(rel, man, OTHER)
    elif tamper == "sha":             # el paquete no es el que dice el manifiesto
        with open(zpath, "ab") as f:
            f.write(b"alterado")
    elif tamper == "extra":           # firmado bien, pero trae un archivo que no corresponde
        with zipfile.ZipFile(zpath, "a") as z:
            z.writestr("herramientas/otro.exe", b"MZ")
        data = open(zpath, "rb").read()
        man.update(sha256=hashlib.sha256(data).hexdigest(), tamano=len(data))
        resign(rel, man, KEY)
    dest = f"{PUB}/v{version}"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(rel, dest)
    open(PUB + "/latest/TAG", "w").write(f"v{version}")


# ---- la app «instalada» (2.5.0) con la clave de prueba
shutil.copytree(make_source("2.5.0"), APP)
shutil.copy("/home/claude/t2/lanzar_prueba.py", APP)
LOG = open(T + "/app-salida.log", "a")
PROCS = []


def start_app(*extra):
    env = dict(os.environ, HOME=T + "/home", PRUEBA_URL=f"{B}/gh/latest/download/actualizacion.json", PRUEBA_KEY_N=KEY["n"])
    p = subprocess.Popen([sys.executable, APP + "/lanzar_prueba.py", "--no-browser", "--port", str(PORT), *extra], cwd=APP,
                         env=env, stdout=LOG, stderr=LOG, start_new_session=True)
    PROCS.append(p)
    return p


def shutdown_app():
    try:
        call("shutdown", "POST")
    except Exception:
        pass
    return wait(lambda: info() is None, 30)


UI = {"on": False}


def ui_loop():          # la «ventana abierta»: pregunta el estado cada segundo como la interfaz
    while True:
        if UI["on"]:
            try:
                call("state", timeout=3)
            except Exception:
                pass
        time.sleep(1)


threading.Thread(target=ui_loop, daemon=True).start()


def version_is(v, timeout=60):
    return wait(lambda: (info() or {}).get("version") == v, timeout)


def app_version_file():
    return re.search(r'^APP_VERSION = "([^"]+)"', open(APP + "/servidor_home.py", encoding="utf-8").read(), re.M).group(1)


print("== U1) Con la ventana abierta: descarga la versión nueva y avisa, sin instalarla sola ==")
UI["on"] = True
start_app()
ok(version_is("2.5.0", 30), "la app instalada (2.5.0) abre")
time.sleep(3)
u = upd()
ok(u.get("status") == "al día" and not u.get("error") and u.get("revisada"), f"sin versiones publicadas todavía: «al día», sin error ({u.get('status')}, {u.get('error')})")
publish("2.5.1", ["Barra de carga al crear servidores", "Arreglo automático de errores"])
u = wait(lambda: (lambda u: u if u.get("status") == "lista" else None)(upd()), 40)
ok(bool(u) and u.get("version") == "2.5.1" and u.get("novedades") == ["Barra de carga al crear servidores", "Arreglo automático de errores"],
   f"la encuentra, la descarga y muestra las novedades: {u}")
ok(any(x.endswith("servidor-home-2.5.1.zip") for x in mock_state().get("gh_downloads", [])), "el paquete se bajó de la release (siguiendo la redirección de GitHub)")
time.sleep(5)
ok(info()["version"] == "2.5.0", "con la ventana abierta no se reinicia sola")

print("\n== U2) «Actualizar ahora»: no con un servidor encendido; sí al apagarlo ==")
st, s = call("servers", "POST", {"type": "vanilla", "mc_version": "1.21.8", "name": "Mundo de prueba", "eula": True, "autostart": True})
sid = s.get("id")
ok(st in (200, 201) and wait(lambda: call("servers/" + sid)[1]["status"] == "en línea", 90), "servidor encendido")
st, r = call("actualizar", "POST")
ok(st == 400 and "está encendido" in r.get("error", ""), f"no actualiza con el servidor encendido: {r.get('error', '')[:90]}")
call(f"servers/{sid}/stop", "POST")
wait(lambda: call("servers/" + sid)[1]["status"] == "detenido", 40)
first_pid = open(APP + "/servidor-home.pid").read().strip()
st, r = call("actualizar", "POST")
ok(st == 200, f"con todo apagado, «Actualizar ahora» empieza: {st} {r.get('error', '')}")
ok(version_is("2.5.1", 60), "la app se reinició sola con la versión 2.5.1")
ok(app_version_file() == "2.5.1" and open(APP + "/servidor-home.pid").read().strip() != first_pid, "los archivos son los nuevos y es otro proceso")
u = upd()
ok((u.get("instalada") or {}).get("version") == "2.5.1" and (u["instalada"].get("novedades") or [])[:1] == ["Barra de carga al crear servidores"],
   f"avisa «se actualizó» con las novedades: {u.get('instalada')}")
ok(call("servers/" + sid)[0] == 200, "el servidor y su mundo siguen ahí")
call("actualizar/visto", "POST")
ok(not upd().get("instalada"), "«Entendido» borra el aviso")
ok(not os.path.exists(f"{APP}/actualizaciones/2.5.1") and not any(f.endswith(".nuevo") for f in os.listdir(APP)), "no quedan archivos a medias")

print("\n== U3) Sin ventana ni servidores: se instala sola ==")
UI["on"] = False
publish("2.5.2", ["Arreglos menores"])
ok(version_is("2.5.2", 60), "se descargó, se instaló y se reinició sola")
ok((upd().get("instalada") or {}).get("version") == "2.5.2", "y deja el aviso para cuando abras la ventana")

print("\n== U4) Descargada con la ventana abierta: se instala al volver a abrir la app ==")
UI["on"] = True
call("state")               # la ventana ya está mirando (antes de que aparezca la versión nueva)
call("actualizar/visto", "POST")
publish("2.5.3", ["Cambio de prueba"])
ok(bool(wait(lambda: upd().get("status") == "lista" and upd().get("version") == "2.5.3", 40)), "queda lista")
ok(shutdown_app() is not None, "se cierra la app (Salir)")
p = start_app()
ok(version_is("2.5.3", 60), "al abrirla, instala la versión nueva antes de mostrar nada")
ok(wait(lambda: p.poll() is not None, 20) is not None, "la copia vieja se cerró sola (le dejó el lugar a la nueva)")

print("\n== U5) Con «Actualizar automáticamente» apagado ==")
st, r = call("actualizar", "PUT", {"auto": False})
ok(st == 200 and r.get("auto") is False, "se puede apagar")
UI["on"] = False
publish("2.5.4", ["Otra versión"])
ok(bool(wait(lambda: upd().get("status") == "lista", 40)), "igual avisa que hay versión nueva")
time.sleep(6)
ok(info()["version"] == "2.5.3", "pero no la instala sola")
shutdown_app(); start_app()
ok(version_is("2.5.3", 30) and info()["version"] == "2.5.3", "ni al volver a abrir la app")
st, r = call("actualizar", "POST")
ok(st == 200 and version_is("2.5.4", 60), "con el botón sí se instala")
call("actualizar", "PUT", {"auto": True})

print("\n== U6) La versión nueva no arranca → vuelve sola a la anterior ==")
downloads_before = len(mock_state().get("gh_downloads", []))
publish("2.5.5", ["Versión que no abre"], breakage="arranque")
ok(bool(wait(lambda: (upd().get("fallo") or {}).get("version") == "2.5.5", 90)), f"detectó que la 2.5.5 no arrancó: {upd().get('fallo')}")
ok(info()["version"] == "2.5.4" and app_version_file() == "2.5.4" and upd()["fallo"].get("volvio") == "2.5.4",
   "y volvió a la 2.5.4 (archivos restaurados)")
time.sleep(9)
zips = [x for x in mock_state().get("gh_downloads", [])[downloads_before:] if x.endswith(".zip")]
ok(zips == ["v2.5.5/servidor-home-2.5.5.zip"] and info()["version"] == "2.5.4", f"no la vuelve a intentar: {zips}")

print("\n== U7) Paquetes que no se instalan ==")
for v, how, msg in (("2.5.6", "firma", "firma"), ("2.5.7", "sha", "dañada"), ("2.5.8", "sintaxis", "no carga"),
                    ("2.5.9", "extra", "no permitido")):
    if how == "sintaxis":
        publish(v, breakage="sintaxis")
    else:
        publish(v, tamper=how)
    u = wait(lambda: (lambda u: u if u.get("status") == "error" and msg in (u.get("error") or "") else None)(upd()), 40)
    ok(bool(u) and info()["version"] == "2.5.4", f"{v} ({how}): la rechaza y sigue en 2.5.4 — {(u or upd()).get('error')}")
ok(not any(x.startswith("v2.5.6/servidor-home") for x in mock_state().get("gh_downloads", [])), "con la firma falsa ni siquiera baja el paquete")

print("\n== U8) Una versión más antigua publicada no se instala ==")
publish("2.4.9")
time.sleep(7)
ok(info()["version"] == "2.5.4" and upd().get("status") in ("al día", "buscando"), f"sigue en 2.5.4 ({upd().get('status')})")

print("\n== U9) Después de todo eso, la siguiente versión buena se instala sola ==")
publish("2.6.0", ["Versión buena"])
ok(version_is("2.6.0", 60), "instala la 2.6.0")
ok(not upd().get("fallo"), "y el aviso del fallo anterior ya no aparece")
left = sorted(os.listdir(APP + "/actualizaciones"))
ok(left == ["estado.json"] or set(left) <= {"estado.json", "anterior.json"}, f"carpeta de actualizaciones limpia: {left}")

print("\nLISTO" if not FAILS else f"\n{len(FAILS)} FALLAS: {FAILS}")
if os.environ.get("KEEP") != "1":
    open("/home/claude/t2/ready", "w").write("1")
    shutdown_app()
    sys.exit(1 if FAILS else 0)
# Para la prueba de la interfaz: la ventana «abierta» y una versión 2.6.1 lista para instalar con el botón.
UI["on"] = True
call("state")
publish("2.6.1", ["Aviso de versión nueva en la ventana", "Se actualiza sola cuando no molesta"])
wait(lambda: upd().get("status") == "lista" and upd().get("version") == "2.6.1", 40)
open("/home/claude/t2/ready", "w").write("1")
TRIGGER = T + "/publicar.txt"
while True:          # ui_update.js pide publicar otras versiones escribiendo su número en publicar.txt
    if os.path.exists(TRIGGER):
        v = open(TRIGGER).read().strip()
        os.remove(TRIGGER)
        publish(v, [f"Novedad de la {v}"])
    time.sleep(0.5)
