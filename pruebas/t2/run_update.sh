#!/usr/bin/env bash
# Actualizaciones automáticas de punta a punta (procesos reales) + interfaz del aviso (ui_update.js)
cd /home/claude/t2
pkill -f "[l]anzar_prueba[.]py" 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
kill $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; sleep 0.8
rm -f /tmp/fakeserver-slow
(cd /home/claude/mock2 && nohup python3 mockserver.py > /tmp/mock.log 2>&1 & echo $! > /tmp/mock.pid); sleep 1
rm -f ready
KEEP=${KEEP:-0} timeout 900 python3 -u harness_update.py > out-update.log 2>&1 &
H=$!
for i in $(seq 1 880); do [ -f ready ] && break; kill -0 $H 2>/dev/null || break; sleep 1; done
echo "actualizaciones: $(grep -c '^OK' out-update.log) OK, $(grep -c '^FAIL' out-update.log) FAIL"; grep -E '^FAIL|Traceback|Error' out-update.log | head -20
if [ -f ready ] && [ "$KEEP" = "1" ]; then
  timeout 300 node ui_update.js > out-ui-update.log 2>&1; rc=$?
  echo "interfaz: $(grep -c '^OK' out-ui-update.log) OK, $(grep -c '^FAIL' out-ui-update.log) FAIL (rc=$rc)"; grep -v '^OK' out-ui-update.log
fi
kill $H 2>/dev/null
pkill -f "[l]anzar_prueba[.]py" 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
