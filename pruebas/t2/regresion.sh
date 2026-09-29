#!/usr/bin/env bash
# Toda la batería: Linux (backend + interfaz) y Windows simulado (Wine), incluida la app instalada.
cd /home/claude/t2
S=/tmp/regresion.txt; : > $S
# las pruebas de ventanas (Wine) necesitan una pantalla virtual
if ! pgrep -x Xvfb > /dev/null; then rm -f /tmp/.X99-lock /tmp/.X11-unix/X99; (nohup Xvfb :99 -screen 0 1280x800x24 > /tmp/xvfb.log 2>&1 &); sleep 2; fi
say() { echo "$*" | tee -a $S; }
KEEP=1 ./run_update.sh > /tmp/r-update.out 2>&1;   say "[actualizaciones] $(cat /tmp/r-update.out | grep -E '^(actualizaciones|interfaz):' | tr '\n' ' ')"
./run_repair.sh > /tmp/r-repair.out 2>&1;          say "[arreglos] $(grep -E '^(backend|interfaz)' /tmp/r-repair.out | tr '\n' ' ')"
./run_ui.sh > /tmp/r-ui.out 2>&1;                  say "[principal] $(grep -E '^(backend|enlaces|interfaz):' /tmp/r-ui.out | tr '\n' ' ')"
./run_versions.sh > /tmp/r-versions.out 2>&1;      say "[versiones] $(grep -E '^(backend|interfaz):' /tmp/r-versions.out | tr '\n' ' ')"
./run_win_repair.sh > /dev/null 2>&1;              say "[win arreglos] $(grep -c '^OK' out-win-repair.log) OK $(grep -c '^FAIL' out-win-repair.log) FAIL $(grep -c LISTO out-win-repair.log) LISTO"
./run_win.sh > /dev/null 2>&1;                     say "[win principal] $(grep -c '^OK' out-win.log) OK $(grep -c '^FAIL' out-win.log) FAIL $(grep -c LISTO out-win.log) LISTO"
./run_win_versions.sh > /dev/null 2>&1;            say "[win versiones] $(grep -c '^OK' out-win-versions.log) OK $(grep -c '^FAIL' out-win-versions.log) FAIL $(grep -c LISTO out-win-versions.log) LISTO"
export DISPLAY=:99 WINEDEBUG=-all PYTHONIOENCODING=utf-8
echo "" | WINEPREFIX=/home/claude/win/prefix timeout 300 /usr/lib/wine/wine64 Z:/home/claude/win/py/python/python.exe -u Z:/home/claude/t2/win_window_test.py 2>&1 | cat > out-win-window.log
say "[win ventana] $(tail -1 out-win-window.log)"
echo "" | WINEPREFIX=/home/claude/win/prefix timeout 200 /usr/lib/wine/wine64 Z:/home/claude/win/py/python/python.exe -u Z:/home/claude/t2/win_perf_test.py 2>&1 | cat > out-win-perf.log
say "[win rendimiento] $(tail -1 out-win-perf.log)"
# la app instalada: primero con el instalador de prueba (actualizaciones), después con el instalador real
kill $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; sleep 0.5
(cd /home/claude/mock2 && nohup python3 mockserver.py > /tmp/mock.log 2>&1 &); sleep 1
VERSION=2.5.0 /home/claude/build/construir_prueba.sh > /tmp/r-build-prueba.out 2>&1
timeout 900 python3 -u win_update_flow.py > out-win-update.log 2>&1; say "[win instalada: actualizaciones] $(tail -1 out-win-update.log)"
/home/claude/build/construir.sh > /tmp/r-build.out 2>&1
WINEPREFIX=/home/claude/win/prefix2 timeout 240 /usr/lib/wine/wine64 "Z:\\home\\claude\\build\\Instalar Servidor Home.exe" /S < /dev/null
rm -rf "/home/claude/win/prefix2/drive_c/users/root/AppData/Local/Servidor Home/actualizaciones"
timeout 600 python3 -u win_app_flow.py > out-win-app.log 2>&1; say "[win instalada: flujo] $(tail -1 out-win-app.log)"
./run_matrix.sh > /tmp/r-matrix.out 2>&1; say "[python 3.10/3.12/3.13] $(grep -c 'FAIL=0 tracebacks=0' /tmp/r-matrix.out)/3 sin fallas"
say "FIN"
