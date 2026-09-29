#!/usr/bin/env bash
# Servidor Home: abre el panel en el navegador.
#   bash iniciar.sh         normal (deja esta ventana abierta)
#   bash iniciar.sh --lan   además se puede abrir desde el celular u otro PC de tu casa
#   --escritorio            lo usa el acceso directo del menú (guarda el registro en servidor-home.log)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
chmod +x "$DIR/iniciar.sh" "$DIR/servidor_home.py" 2>/dev/null   # por si se copió sin permiso de ejecución

if ! command -v python3 >/dev/null 2>&1; then
  msg="Servidor Home necesita Python 3. Instálalo con: sudo apt install python3  (o: sudo dnf install python3)"
  command -v notify-send >/dev/null 2>&1 && notify-send "Servidor Home" "$msg"
  echo "$msg"
  exit 1
fi

# Acceso directo en el menú de aplicaciones (se crea la primera vez o si moviste la carpeta).
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESK="$APPS/servidor-home.desktop"
if [ ! -f "$DESK" ] || ! grep -qF "$DIR/iniciar.sh" "$DESK"; then
  mkdir -p "$APPS"
  cat > "$DESK" <<EOF
[Desktop Entry]
Type=Application
Name=Servidor Home
Comment=Enciende tu servidor de Minecraft y compártelo con playit.gg
Exec=bash "$DIR/iniciar.sh" --escritorio
Path=$DIR
Icon=$DIR/web/icono.svg
Terminal=false
Categories=Game;
EOF
  chmod +x "$DESK"
  echo "Se agregó «Servidor Home» al menú de aplicaciones."
fi

if [ "$1" = "--escritorio" ]; then
  shift
  LOG="$DIR/servidor-home.log"
  if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ]; then
    mv -f "$LOG" "$LOG.1"
  fi
  exec python3 servidor_home.py "$@" >> "$LOG" 2>&1
fi

exec python3 servidor_home.py "$@"
