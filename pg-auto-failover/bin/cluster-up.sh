#!/bin/bash
# Build monitor + 3 nodes (n1 primary first). Async: replication-quorum false on all nodes, number-sync-standbys 0 (labelled deviation).
source "$(dirname "$0")/env.sh"
C=$ST/cluster; mkdir -p $C/logs $C/xdg/config $C/xdg/data
for n in $NODES; do
  nohup python3 -I $ST/bin/tcpproxy.py $(rpx_port $n) $(pg_port $n) $(rpx_ctl $n) >$C/logs/rpx-$n.log 2>&1 &
  nohup python3 -I $ST/bin/tcpproxy.py $(mpx_port $n) $PGAF_MON_PORT $(mpx_ctl $n) >$C/logs/mpx-$n.log 2>&1 &
done
nohup pg_autoctl create monitor --pgdata $C/mon --pgport $PGAF_MON_PORT --hostname 127.0.0.1 --auth trust --no-ssl --run >$C/logs/monitor.log 2>&1 &
for i in $(seq 60); do psql -h 127.0.0.1 -p $PGAF_MON_PORT -U autoctl_node -d pg_auto_failover -Atc "select 1" >/dev/null 2>&1 && break; sleep 1; done
mq() { psql -h 127.0.0.1 -p $PGAF_MON_PORT -U $(whoami) -d pg_auto_failover -Atc "$1"; }
state_of() { mq "select reportedstate||'/'||goalstate from pgautofailover.node where nodename='$1'"; }
for n in $NODES; do
  MU="postgres://autoctl_node@127.0.0.1:$(mpx_port $n)/pg_auto_failover?sslmode=disable"
  pg_autoctl create postgres --pgdata $C/$n --pgport $(pg_port $n) --hostname 127.0.0.1 --name $n --auth trust --no-ssl \
     --monitor "$MU" --replication-quorum false --listen 127.0.0.1 >$C/logs/create-$n.log 2>&1 || { echo "create $n failed"; tail -20 $C/logs/create-$n.log; exit 1; }
  mq "update pgautofailover.node set nodeport=$(rpx_port $n) where nodename='$n'" >/dev/null
  nohup pg_autoctl run --pgdata $C/$n >$C/logs/$n.log 2>&1 &
  echo $! > $C/$n.agentpid
  # wait until this node is primary (n1) or secondary (others)
  want=secondary; [ $n = n1 ] && want=primary
  for i in $(seq 120); do s=$(state_of $n); [ "${s%%/*}" = $want ] && [ "${s##*/}" = $want ] && break; sleep 1; done
  echo "$n: $(state_of $n)"
done
pg_autoctl set formation number-sync-standbys 0 --pgdata $C/n1 2>&1 | tail -2
sleep 3
mq "select nodename,nodeport,reportedstate,goalstate,replicationquorum,candidatepriority from pgautofailover.node order by nodeid"
