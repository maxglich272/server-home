#!/usr/bin/env python3
"""Solo para pruebas: ajusta una copia de servidor_home.py para que se actualice desde el GitHub simulado
(http://127.0.0.1:9911/gh), con la clave de prueba y tiempos cortos.
    python3 prueba_constantes.py archivo.py [--version X.Y.Z] [--romper arranque|sintaxis]"""
import argparse, json, re
ap = argparse.ArgumentParser()
ap.add_argument("archivo")
ap.add_argument("--version")
ap.add_argument("--romper", choices=["arranque", "sintaxis"])
ap.add_argument("--clave", default="/home/claude/build/claves-prueba/clave-prueba.json")
a = ap.parse_args()
t = open(a.archivo, encoding="utf-8").read()
key = json.load(open(a.clave))
t = re.sub(r"^UPDATE_KEY_N = int\(.*?, 16\)", f'UPDATE_KEY_N = int("{key["n"]}", 16)', t, count=1, flags=re.S | re.M)
t = re.sub(r'^UPDATE_MANIFEST_URL = \(.*?if UPDATE_REPO else ""\)',
           'UPDATE_MANIFEST_URL = "http://127.0.0.1:9911/gh/latest/download/actualizacion.json"', t, count=1, flags=re.S | re.M)
for name, val in (("UPDATE_FIRST_CHECK", "2"), ("UPDATE_EVERY", "5"), ("UPDATE_RETRY", "3"), ("UPDATE_TICK", "1"),
                  ("UPDATE_UI_IDLE", "4")):
    t, n = re.subn(rf"^{name} = [^\n#]+", f"{name} = {val} ", t, count=1, flags=re.M)
    assert n == 1, name
if a.version:
    t = re.sub(r'^APP_VERSION = "[^"]+"', f'APP_VERSION = "{a.version}"', t, count=1, flags=re.M)
if a.romper == "arranque":
    t = t.replace("def main():\n", "def main():\n    raise SystemExit(3)\n", 1)
elif a.romper == "sintaxis":
    t += "\ndef roto(:\n"
assert "127.0.0.1:9911/gh/latest" in t
open(a.archivo, "w", encoding="utf-8").write(t)
