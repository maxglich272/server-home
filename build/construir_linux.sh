#!/usr/bin/env bash
# Arma el paquete de Linux: Servidor-Home-linux-<arq>.tar.gz con el programa y su propio Python 3.12
# (python-build-standalone, el mismo que va en el instalador de Windows). Quien lo baja no necesita instalar nada:
#   tar xf Servidor-Home-linux-x86_64.tar.gz && bash servidor-home/instalar.sh
# Uso: build/construir_linux.sh [x86_64|aarch64]      (deja el .tar.gz en build/publicar/)
set -e
ARQ="${1:-x86_64}"
PBS_FECHA=20260901
PBS_PY=3.12.14
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$RAIZ/build/linux-tmp"
OUT="$RAIZ/build/publicar"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_FECHA/cpython-$PBS_PY+$PBS_FECHA-$ARQ-unknown-linux-gnu-install_only_stripped.tar.gz"
CACHE="$RAIZ/build/cache/$(basename "$URL")"

mkdir -p "$(dirname "$CACHE")" "$OUT"
[ -f "$CACHE" ] || curl -fL --retry 3 -o "$CACHE" "$URL"

rm -rf "$TMP"
mkdir -p "$TMP/servidor-home/web"
tar xf "$CACHE" -C "$TMP/servidor-home"                 # deja servidor-home/python/
S="$RAIZ/servidor-home"
cp "$S/servidor_home.py" "$S/iniciar.sh" "$S/instalar.sh" "$S/README.md" "$TMP/servidor-home/"
cp "$S/web/index.html" "$S/web/icono.svg" "$S/web/icono.ico" "$TMP/servidor-home/web/"
V=$(grep -m1 '^APP_VERSION' "$S/servidor_home.py" | cut -d'"' -f2)
printf 'Servidor Home %s (instalado)\n' "$V" > "$TMP/servidor-home/instalado.txt"
chmod +x "$TMP/servidor-home/iniciar.sh" "$TMP/servidor-home/instalar.sh"
find "$TMP" -name __pycache__ -type d -prune -exec rm -rf {} +

# Que el Python del paquete funcione y traiga lo que usa la app (ssl para descargar, sqlite3 no hace falta).
"$TMP/servidor-home/python/bin/python3" -c "import ssl, ctypes, tarfile, zipfile, json; print('python ok')"
"$TMP/servidor-home/python/bin/python3" -m py_compile "$TMP/servidor-home/servidor_home.py"
find "$TMP" -name __pycache__ -type d -prune -exec rm -rf {} +

tar czf "$OUT/Servidor-Home-linux-$ARQ.tar.gz" -C "$TMP" servidor-home
rm -rf "$TMP"
ls -la "$OUT/Servidor-Home-linux-$ARQ.tar.gz"
