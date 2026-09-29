#!/usr/bin/env bash
# Compila el servidor de Minecraft falso (src/fs/Main.java) y lo deja donde lo usan las pruebas:
# fakeserver.jar (NeoForge/Forge lo lanzan directo) y www/fabric-server.jar (lo descargan Vanilla y Fabric del mock).
set -e
cd "$(dirname "$0")"
javac --release 8 -nowarn -d out/fs src/fs/Main.java 2>&1 | grep -v "JAVA_TOOL_OPTIONS\|warning" || true
(cd out/fs && jar cfm ../../fakeserver.jar ../../src/fs/m.txt Main*.class)
cp fakeserver.jar www/fabric-server.jar
echo "servidor falso listo"
