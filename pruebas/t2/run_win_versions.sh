#!/usr/bin/env bash
# Batería completa con Python y Java de Windows (bajo Wine).
kill $(cat /tmp/mock.pid) $(ps -eo pid,args | awk '$2=="python3" && $3=="mockserver.py"{print $1}') 2>/dev/null; WINEPREFIX=/home/claude/win/prefix /usr/lib/wine/wineserver -k 2>/dev/null; sleep 1
rsync -a --delete --exclude java /home/claude/servidor-home/ /home/claude/wt/app/ 2>/dev/null || { rm -rf /home/claude/wt/app.tmp; cp -r /home/claude/servidor-home /home/claude/wt/app.tmp; mv /home/claude/wt/app/java /home/claude/wt/app.tmp/; rm -rf /home/claude/wt/app; mv /home/claude/wt/app.tmp /home/claude/wt/app; }
rm -rf /home/claude/wt/app/servidores /home/claude/wt/app/playit
cd /home/claude/mock2 && python3 build_fixtures.py >/dev/null && (nohup python3 mockserver.py > /tmp/mock.log 2>&1 & echo $! > /tmp/mock.pid); sleep 1
cd /home/claude/t2 && rm -f ready
export WINEDEBUG=-all WINEPREFIX=/home/claude/win/prefix HARNESS_EXIT=${HARNESS_EXIT-1} PYTHONIOENCODING=utf-8
echo "" | timeout 900 /usr/lib/wine/wine64 ${WINPY:-Z:/home/claude/win/py/python/python.exe} -u Z:/home/claude/t2/win_versions.py 2>&1 | cat > out-win-versions.log
