#!/usr/bin/env python3
"""Arma servidor-home-proyecto-<versión>.zip: todo lo necesario para seguir trabajando en Servidor Home
(programa, instalador, mod GPU Dedicada, pruebas y notas), SIN la clave privada de firma.

Uso: python3 armar_proyecto.py [--salida carpeta]
"""
import argparse
import os
import re
import sys
import zipfile

H = "/home/claude"
RAIZ = "servidor-home-proyecto"

# (carpeta de origen, carpeta dentro del zip, ¿qué incluir?)
PARTES = [
    (f"{H}/servidor-home", "servidor-home", lambda rel: "__pycache__" not in rel),
    (f"{H}/build", "build", lambda rel: not rel.startswith(("claves/", "publicar/", "__pycache__")) and "__pycache__" not in rel
     and not rel.endswith((".exe", ".zip")) and not rel.startswith("app/servidores") and not rel.startswith("app/playit")),
    (f"{H}/gpumod", "gpumod", lambda rel: not rel.startswith("out/") and "__pycache__" not in rel),
    (f"{H}/mock2", "pruebas/mock2", lambda rel: rel.split("/")[0] in ("src", "www", "jars") and "playitd" not in rel
     and not rel.startswith("www/gh/")
     or rel in ("mockserver.py", "build_fixtures.py", "fakeserver.jar", "construir_falso.sh")),
    (f"{H}/modpack", "modpack-volcanes-y-estrellas", lambda rel: "__pycache__" not in rel and ".v1" not in rel),
    (f"{H}/t2", "pruebas/t2", lambda rel: "/" not in rel and re.search(r"\.(py|js|sh)$", rel) and not rel.startswith("ui_repair_ids")),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=f"{H}/entregas")
    args = ap.parse_args()
    src = open(f"{H}/servidor-home/servidor_home.py", encoding="utf-8").read()
    version = re.search(r'^APP_VERSION = "([^"]+)"', src, re.M).group(1)
    os.makedirs(args.salida, exist_ok=True)
    dest = os.path.join(args.salida, f"servidor-home-proyecto-{version}.zip")
    secretos = []
    for k in ("clave-privada.json", "clave-privada.pem"):
        p = f"{H}/build/claves/{k}"
        if os.path.exists(p):
            texto = open(p, encoding="utf-8", errors="replace").read()
            secretos += [m for m in re.findall(r'"d"\s*:\s*"([0-9a-fA-F]{64,})"', texto)]
            secretos += [l for l in texto.splitlines() if len(l) > 60 and not l.startswith("-----")][:2]
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(f"{H}/proyecto-notas/COMO-CONTINUAR.md", f"{RAIZ}/COMO-CONTINUAR.md")
        for origen, dentro, incluir in PARTES:
            for root, dirs, files in os.walk(origen):
                dirs.sort()
                for f in sorted(files):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, origen).replace(os.sep, "/")
                    if os.path.abspath(full) == os.path.abspath(dest) or not incluir(rel):
                        continue
                    if ("clave-privada" in f or f.endswith(".pem")) and not rel.startswith("claves-prueba/"):
                        z.close()
                        os.remove(dest)
                        sys.exit(f"ALTO: {full} parece una clave privada; no se armó el zip.")
                    z.write(full, f"{RAIZ}/{dentro}/{rel}")
                    n += 1
    # comprobación final: la clave privada no puede estar en ninguna parte del zip
    with zipfile.ZipFile(dest) as z:
        for info in z.infolist():
            data = z.read(info.filename).decode("latin-1")
            for s in secretos:
                if s and s in data:
                    os.remove(dest)
                    sys.exit(f"ALTO: {info.filename} contiene la clave privada. Zip borrado.")
    print(f"{dest}: {n} archivos, {os.path.getsize(dest) // 1024} KB, sin la clave privada")


if __name__ == "__main__":
    main()
