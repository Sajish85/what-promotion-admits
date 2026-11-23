#!/bin/bash
# stop everything of the study rig: pg_autoctl, anything listening on the study ports (postmaster titles hide the data dir), proxies
source "$(dirname "$0")/env.sh"
pkill -9 -f pg_autoctl 2>/dev/null
for p in 6470 6471 6472 6473 6481 6482 6483 6491 6492 6493 6501 6502 6503 6511 6512 6513; do
  lsof -ti tcp:$p -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null
done
sleep 1
# any leftover postmaster whose cwd is under the rig
for pid in $(pgrep -x postgres); do
  d=$(lsof -a -p $pid -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-); case "$d" in "$ST/cluster"*) kill -9 $pid;; esac
done
sleep 1
rm -rf "$ST/cluster"
# reap orphaned SysV shm segments (nattch 0, creator dead): SIGKILLed postmasters leak them and macOS allows only 32 (kern.sysv.shmmni)
ipcs -m -a | awk 'NR>3 && $9==0 {print $2, $11}' | while read id cpid; do kill -0 $cpid 2>/dev/null || ipcrm -m $id 2>/dev/null; done
python3 -I $ST/bin/reap-ipc.py --do >> $ST/results/reap-ipc.log 2>&1
