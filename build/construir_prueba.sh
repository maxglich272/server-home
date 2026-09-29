#!/usr/bin/env bash
# Instalador de PRUEBA: igual al real, pero se actualiza desde el GitHub simulado (mock) con la clave de prueba.
set -e
B=/home/claude/build; P=/home/claude/build-prueba
rm -rf "$P"; mkdir -p "$P"
cp -r "$B/app" "$P/app"
cp "$B/instalador.nsi" "$B/instalador.bmp" "$P/"
cp /home/claude/servidor-home/servidor_home.py "$P/app/"
cp /home/claude/servidor-home/web/index.html /home/claude/servidor-home/web/icono.svg /home/claude/servidor-home/web/icono.ico "$P/app/web/"
cp /home/claude/servidor-home/README.md "$P/app/README.md"
python3 "$B/prueba_constantes.py" "$P/app/servidor_home.py" ${VERSION:+--version $VERSION}
V=$(grep -m1 '^APP_VERSION' "$P/app/servidor_home.py" | cut -d'"' -f2)
printf 'Servidor Home %s (instalado)\r\n' "$V" > "$P/app/instalado.txt"
sed -i "s/^!define APPVERSION \".*\"/!define APPVERSION \"$V\"/" "$P/instalador.nsi"
find "$P/app" -name __pycache__ -type d -prune -exec rm -rf {} +
cd "$P" && makensis -V2 -DOUTFILE="Instalar Servidor Home (prueba).exe" instalador.nsi
ls -la "$P/Instalar Servidor Home (prueba).exe"
