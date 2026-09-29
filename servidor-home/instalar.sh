#!/usr/bin/env bash
# Servidor Home para Linux: instala (o actualiza) el programa para este usuario, sin root.
#   bash instalar.sh               el programa queda en ~/.local/share/servidor-home/app y aparece en el menú
#   bash instalar.sh --desinstalar quita el programa y el acceso del menú (tus servidores y mundos se quedan)
# Los servidores y mundos van en Documentos/servidor home, igual que en Windows. Después de instalar,
# la app se actualiza sola con cada versión nueva.
set -e
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${XDG_DATA_HOME:-$HOME/.local/share}/servidor-home"
APP="$BASE/app"
DESK="${XDG_DATA_HOME:-$HOME/.local/share}/applications/servidor-home.desktop"

cerrar_si_abierta() {
  if [ -x "$APP/python/bin/python3" ] && [ -f "$APP/servidor_home.py" ]; then
    "$APP/python/bin/python3" "$APP/servidor_home.py" --cerrar >/dev/null 2>&1 || true
  fi
}

if [ "$1" = "--desinstalar" ]; then
  cerrar_si_abierta
  rm -rf "$APP" "$DESK"
  echo "Servidor Home quedó desinstalado. Tus servidores siguen en la carpeta «servidor home» de Documentos."
  exit 0
fi

if [ ! -f "$SRC/servidor_home.py" ] || [ ! -x "$SRC/python/bin/python3" ]; then
  echo "Ejecuta instalar.sh desde la carpeta que sale al descomprimir Servidor-Home-linux-*.tar.gz."
  exit 1
fi
if [ "$SRC" = "$APP" ]; then
  echo "Servidor Home ya está instalado aquí."
  exit 0
fi

cerrar_si_abierta
mkdir -p "$BASE"
rm -rf "$APP.nuevo"
cp -a "$SRC" "$APP.nuevo"
rm -f "$APP.nuevo/instalar.sh"
rm -rf "$APP.viejo"
[ -d "$APP" ] && mv "$APP" "$APP.viejo"
mv "$APP.nuevo" "$APP"
rm -rf "$APP.viejo"
cp "$SRC/instalar.sh" "$APP/instalar.sh"     # para poder desinstalar después

mkdir -p "$(dirname "$DESK")"
cat > "$DESK" <<EOF
[Desktop Entry]
Type=Application
Name=Servidor Home
Comment=Enciende tu servidor de Minecraft y compártelo con playit.gg
Exec=bash "$APP/iniciar.sh" --escritorio
Path=$APP
Icon=$APP/web/icono.svg
Terminal=false
Categories=Game;
EOF
chmod +x "$DESK" "$APP/iniciar.sh"

V=$("$APP/python/bin/python3" -c "import re; print(re.search(r'^APP_VERSION = \"(.+?)\"', open('$APP/servidor_home.py', encoding='utf-8').read(), re.M).group(1))")
echo "Servidor Home $V instalado. Ábrelo desde el menú de aplicaciones o con: bash \"$APP/iniciar.sh\""
