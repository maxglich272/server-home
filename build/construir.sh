#!/usr/bin/env bash
# Arma la carpeta app/ con la última versión y compila el instalador.
set -e
cd /home/claude/build
cp /home/claude/servidor-home/servidor_home.py app/
cp /home/claude/servidor-home/web/index.html /home/claude/servidor-home/web/icono.svg /home/claude/servidor-home/web/icono.ico app/web/
cp /home/claude/servidor-home/README.md app/README.md
V=$(grep -m1 '^APP_VERSION' app/servidor_home.py | cut -d'"' -f2)
printf 'Servidor Home %s (instalado)\r\n' "$V" > app/instalado.txt
sed -i "s/^!define APPVERSION \".*\"/!define APPVERSION \"$V\"/" instalador.nsi
find app -name __pycache__ -type d -prune -exec rm -rf {} +
makensis -V2 instalador.nsi
ls -la "Instalar Servidor Home.exe"
