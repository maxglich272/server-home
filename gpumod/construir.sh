#!/usr/bin/env bash
# Compila el mod GPU Dedicada (Java 8, sirve en Fabric, Forge y NeoForge) sin descargar Minecraft:
# las clases de los loaders se reemplazan por «stubs» solo para compilar (no van dentro del .jar).
set -e
cd "$(dirname "$0")"
rm -rf build && mkdir -p build/stubs build/classes
javac --release 8 -nowarn -Xlint:-options -encoding UTF-8 -d build/stubs $(find stubs -name '*.java')
javac --release 8 -nowarn -Xlint:-options -encoding UTF-8 -cp build/stubs -d build/classes $(find src -name '*.java')
cp -r res/* build/classes/
rm -f gpu-dedicada-1.0.0.jar
jar cfm gpu-dedicada-1.0.0.jar manifest.txt -C build/classes .
ls -la gpu-dedicada-1.0.0.jar
