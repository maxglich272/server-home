#!/usr/bin/env bash
# Ejecuta la batería completa con cada versión de Python.
cd /home/claude/t2
for PY in python3.10 python3.12 python3.13; do
  python3 /home/claude/mock2/build_fixtures.py >/dev/null
  kill $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; sleep 0.5
  (cd /home/claude/mock2 && nohup python3 mockserver.py > /tmp/mock.log 2>&1 & echo $! > /tmp/mock.pid); sleep 1
  rm -f ready /tmp/servidor-home-playitd-0.sock
  HARNESS_EXIT=1 timeout 240 $PY harness.py > out-$PY.log 2>&1
  kill $(cat /tmp/mock.pid) 2>/dev/null; sleep 1
  for p in $(ps -eo pid,args | awk '/[p]layit\/playitd --secret-path/{print $1}'); do kill $p; done
  for p in $(ps -eo pid,args | awk '/[f]akeserver.jar/{print $1}'); do kill $p; done
  ok=$(grep -c "^OK" out-$PY.log); fail=$(grep -c "^FAIL" out-$PY.log); tb=$(grep -c "Traceback" out-$PY.log)
  echo "$PY: OK=$ok FAIL=$fail tracebacks=$tb $(grep -o 'Python [0-9.]* — LISTO' out-$PY.log)"
done
