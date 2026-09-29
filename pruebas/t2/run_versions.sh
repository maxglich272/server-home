#!/usr/bin/env bash
# Prueba de versiones: backend (harness_versions.py) + interfaz (ui_versions.js)
cd /home/claude/t2
kill $(cat /tmp/harness.pid 2>/dev/null) 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver|playitd' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
kill $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; sleep 0.8
python3 /home/claude/mock2/build_fixtures.py >/dev/null
(cd /home/claude/mock2 && nohup python3 mockserver.py > /tmp/mock.log 2>&1 & echo $! > /tmp/mock.pid); sleep 1
rm -f ready; HARNESS_EXIT=0 nohup ${PY:-python3} -u harness_versions.py > out-versions.log 2>&1 &
echo $! > /tmp/harness.pid
for i in $(seq 1 300); do [ -f ready ] && break; sleep 1; done
echo "backend: $(grep -c '^OK' out-versions.log) OK, $(grep -c '^FAIL' out-versions.log) FAIL"; grep '^FAIL' out-versions.log
timeout 300 node ui_versions.js > out-ui-versions.log 2>&1; rc=$?
echo "interfaz: $(grep -c '^OK' out-ui-versions.log) OK, $(grep -c '^FAIL' out-ui-versions.log) FAIL (rc=$rc)"; grep -v '^OK' out-ui-versions.log
kill $(cat /tmp/harness.pid) 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
