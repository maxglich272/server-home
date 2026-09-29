#!/usr/bin/env bash
# Interfaz general (ui_links.js y ui_smoke.js) sobre el arnés principal (harness.py) en Linux.
cd /home/claude/t2
kill $(cat /tmp/harness.pid 2>/dev/null) 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver|playitd' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
kill $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; sleep 0.8
python3 /home/claude/mock2/build_fixtures.py >/dev/null
(cd /home/claude/mock2 && nohup python3 mockserver.py > /tmp/mock.log 2>&1 & echo $! > /tmp/mock.pid); sleep 1
rm -f ready /tmp/servidor-home-playitd-0.sock; HARNESS_EXIT=0 nohup python3 -u harness.py > out-check.log 2>&1 &
echo $! > /tmp/harness.pid
for i in $(seq 1 300); do [ -f ready ] && break; kill -0 $(cat /tmp/harness.pid) 2>/dev/null || break; sleep 1; done
echo "backend: $(grep -c '^OK' out-check.log) OK, $(grep -c '^FAIL' out-check.log) FAIL"; grep -E '^FAIL|Traceback' out-check.log
timeout 120 node ui_links.js > out-ui-links.log 2>&1; echo "enlaces: $(grep -c '^OK' out-ui-links.log) OK, $(grep -c '^FAIL' out-ui-links.log) FAIL"; grep -v '^OK' out-ui-links.log
timeout 400 node ui_255.js > out-ui-255.log 2>&1; echo "2.5.5: $(grep -c "^OK" out-ui-255.log) OK, $(grep -c "^FAIL" out-ui-255.log) FAIL"; grep -v "^OK" out-ui-255.log
timeout 300 node ui_smoke.js > out-ui.log 2>&1; echo "interfaz: $(grep -c '^OK' out-ui.log) OK, $(grep -c '^FAIL' out-ui.log) FAIL"; grep -v '^OK' out-ui.log
kill $(cat /tmp/harness.pid) 2>/dev/null
ps -eo pid,args | grep -E 'fakeserver|playitd' | grep -v grep | awk '{print $1}' | xargs -r kill 2>/dev/null
