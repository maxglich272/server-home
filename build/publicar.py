#!/usr/bin/env python3
"""Prepara una versión de Servidor Home para publicarla en GitHub (Releases).

    python3 publicar.py --clave clave-privada.json [--app ../servidor-home] [--instalador "Instalar Servidor Home.exe"]
                        [--novedades novedades.txt] [--salida publicar]

Deja en <salida>/<versión>/ los archivos que hay que subir a la release:
    actualizacion.json            qué versión es, sus novedades y el SHA-256 del paquete (firmado con la clave)
    servidor-home-<versión>.zip   los archivos de la app que se reemplazan al actualizar
    Instalar-Servidor-Home.exe    el instalador, para quien instala por primera vez
y un LEEME.txt con los pasos. Solo usa la biblioteca estándar de Python.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import zipfile

DIGEST_INFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")
REPO_README = """# Servidor Home

Crea y enciende servidores de Minecraft (con o sin mods) en tu PC con Windows y compártelos con tus amigos
con una dirección fija de playit.gg, sin abrir puertos del router.

## Descargar

**[Descargar el instalador para Windows](https://{where}/releases/latest/download/Instalar-Servidor-Home.exe)**

1. Abre el archivo descargado. Como el instalador no tiene firma de Microsoft, Windows puede mostrar
   «Windows protegió su PC»: toca **Más información → Ejecutar de todas formas**.
2. *Siguiente* → *Terminar*. No pide permisos de administrador.

## Se actualiza solo

Cuando sale una versión nueva, cada Servidor Home instalado la descarga, comprueba con una firma digital que la
publicó el autor y la instala cuando no hay servidores encendidos, así que nunca corta una partida.
Las novedades de cada versión están en [Releases](https://{where}/releases).
"""
APP_FILES = ["servidor_home.py", "README.md", "web/index.html", "web/remoto.html", "web/icono.svg", "web/icono.ico"]


def rsa_sign(message, key):
    n, d = int(key["n"], 16), int(key["d"], 16)
    k = (n.bit_length() + 7) // 8
    info = DIGEST_INFO_SHA256 + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - 3 - len(info)) + b"\x00" + info
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def rsa_verify(message, sig, n, e):
    k = (n.bit_length() + 7) // 8
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    info = DIGEST_INFO_SHA256 + hashlib.sha256(message).digest()
    return em == b"\x00\x01" + b"\xff" * (k - 3 - len(info)) + b"\x00" + info


def app_constants(src):
    text = open(os.path.join(src, "servidor_home.py"), encoding="utf-8").read()
    version = re.search(r'^APP_VERSION = "([^"]+)"', text, re.M).group(1)
    repo = re.search(r'^UPDATE_REPO = "([^"]*)"', text, re.M).group(1)
    block = re.search(r"^UPDATE_KEY_N = int\((.*?), 16\)", text, re.M | re.S).group(1)
    n = int("".join(re.findall(r'"([0-9a-f]+)"', block)), 16)
    return version, repo, n


def build_zip(src):
    """Zip reproducible (mismas fechas y orden): el mismo código da el mismo SHA-256."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in APP_FILES:
            path = os.path.join(src, *rel.split("/"))
            if not os.path.isfile(path):
                sys.exit(f"Falta {path}")
            info = zipfile.ZipInfo(rel, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as f:
                z.writestr(info, f.read())
    return buf.getvalue()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clave", required=True, help="clave privada (clave-privada.json)")
    ap.add_argument("--app", default=os.path.join(here, "..", "servidor-home"), help="carpeta con servidor_home.py y web/")
    ap.add_argument("--instalador", default=os.path.join(here, "Instalar Servidor Home.exe"))
    ap.add_argument("--novedades", help="archivo de texto con una novedad por línea")
    ap.add_argument("--salida", default=os.path.join(here, "publicar"))
    ap.add_argument("--sin-instalador", action="store_true", help="no copiar el instalador (pruebas)")
    args = ap.parse_args()

    key = json.load(open(args.clave, encoding="utf-8"))
    version, repo, n_app = app_constants(args.app)
    if int(key["n"], 16) != n_app:
        sys.exit("La clave privada no corresponde a la clave pública que trae la app: las apps instaladas "
                 "rechazarían esta versión. Usa la clave correcta.")
    novedades = []
    if args.novedades:
        novedades = [l.strip(" -•\t") for l in open(args.novedades, encoding="utf-8").read().splitlines() if l.strip()]
    pkg = build_zip(args.app)
    pkg_name = f"servidor-home-{version}.zip"
    manifest = {"app": "Servidor Home", "version": version, "fecha": time.strftime("%Y-%m-%d"), "novedades": novedades,
                "paquete": pkg_name, "sha256": hashlib.sha256(pkg).hexdigest(), "tamano": len(pkg),
                "instalador": "Instalar-Servidor-Home.exe"}
    text = json.dumps(manifest, ensure_ascii=False, indent=1)
    sig = rsa_sign(text.encode("utf-8"), key)
    assert rsa_verify(text.encode("utf-8"), sig, n_app, int(key.get("e", 65537)))
    out = os.path.join(args.salida, version)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    with open(os.path.join(out, "actualizacion.json"), "w", encoding="utf-8") as f:
        json.dump({"manifiesto": text, "firma": base64.b64encode(sig).decode()}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, pkg_name), "wb") as f:
        f.write(pkg)
    files = ["actualizacion.json", pkg_name]
    if not args.sin_instalador:
        if not os.path.isfile(args.instalador):
            sys.exit(f"No encontré el instalador: {args.instalador}")
        shutil.copyfile(args.instalador, os.path.join(out, "Instalar-Servidor-Home.exe"))
        files.append("Instalar-Servidor-Home.exe")
    where = f"github.com/{repo}" if repo else "github.com/TU-USUARIO/servidor-home"
    lista = "\n".join(f"     - {f}" for f in files)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(REPO_README.format(where=where))
    with open(os.path.join(out, "LEEME.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(f"""Publicar Servidor Home {version}
================================

Solo la primera vez: GitHub necesita al menos un archivo en el repositorio para crear releases.
   Abre https://{where} → «uploading an existing file» (o Add file → Upload files),
   arrastra el README.md de esta carpeta y toca «Commit changes».

1. Abre https://{where}/releases/new
2. En «Choose a tag» escribe  v{version}  y elige «Create new tag».
3. Título: Servidor Home {version}
4. Arrastra estos {len(files)} archivos a la zona «Attach binaries»:
{lista}
5. Deja marcado «Set as the latest release» y toca «Publish release».

Listo: en las próximas horas cada Servidor Home instalado descarga la versión nueva, comprueba la firma
y se actualiza solo cuando no hay servidores encendidos.

Para instalarlo por primera vez, tus amigos descargan:
   https://{where}/releases/latest/download/Instalar-Servidor-Home.exe

Novedades de esta versión:
""" + "".join(f"  - {x}\n" for x in novedades))
    print(f"Versión {version} lista en {out}")
    for f_ in files:
        print(f"  {f_}  ({os.path.getsize(os.path.join(out, f_)):,} bytes)")


if __name__ == "__main__":
    main()
