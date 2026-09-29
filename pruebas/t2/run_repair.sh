#!/usr/bin/env bash
# Arreglos automáticos y barra de carga: backend (harness_repair.py) + interfaz (ui_repair.js)
cd /home/claude/t2
kill $(cat /tmp/harness.pid 2>/dev/null) 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver|playitd' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
kill $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; sleep 0.8
rm -f /tmp/fakeserver-slow
python3 /home/claude/mock2/build_fixtures.py >/dev/null
(cd /home/claude/mock2 && nohup python3 mockserver.py > /tmp/mock.log 2>&1 & echo $! > /tmp/mock.pid); sleep 1
rm -f ready; HARNESS_EXIT=${HARNESS_EXIT:-0} nohup ${PY:-python3} -u harness_repair.py > out-repair.log 2>&1 &
echo $! > /tmp/harness.pid
for i in $(seq 1 1500); do [ -f ready ] && break; kill -0 $(cat /tmp/harness.pid) 2>/dev/null || break; sleep 1; done
echo "backend: $(grep -c '^OK' out-repair.log) OK, $(grep -c '^FAIL' out-repair.log) FAIL"; grep -E '^FAIL|Traceback|Error' out-repair.log | head -30
if [ -f ready ] && [ -z "$NO_UI" ]; then
  timeout 400 node ui_repair.js > out-ui-repair.log 2>&1; rc=$?
  echo "interfaz: $(grep -c '^OK' out-ui-repair.log) OK, $(grep -c '^FAIL' out-ui-repair.log) FAIL (rc=$rc)"; grep -v '^OK' out-ui-repair.log
  timeout 300 node ui_look.js > out-ui-look.log 2>&1; rc=$?
  echo "interfaz (compartir e imagen): $(grep -c '^OK' out-ui-look.log) OK, $(grep -c '^FAIL' out-ui-look.log) FAIL (rc=$rc)"; grep -v '^OK' out-ui-look.log
fi
kill $(cat /tmp/harness.pid) 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
rm -f /tmp/fakeserver-slow
