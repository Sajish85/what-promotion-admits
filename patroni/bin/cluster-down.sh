#!/bin/bash
source "$(dirname "$0")/env.sh"
for n in $NODES; do [ -f $LAB/cluster/$n/patroni.pid ] && kill $(cat $LAB/cluster/$n/patroni.pid) 2>/dev/null; done
sleep 2
for n in $NODES; do
  [ -f $LAB/cluster/$n/data/postmaster.pid ] && pg_ctl -D $LAB/cluster/$n/data -m immediate stop >/dev/null 2>&1
  [ -f $LAB/cluster/$n/patroni.pid ] && kill -9 $(cat $LAB/cluster/$n/patroni.pid) 2>/dev/null
  for k in rpx epx; do [ -f $LAB/cluster/$k-$n.pid ] && kill $(cat $LAB/cluster/$k-$n.pid) 2>/dev/null; done
done
[ -f $LAB/cluster/etcd.pid ] && kill $(cat $LAB/cluster/etcd.pid) 2>/dev/null
sleep 1
pkill -9 -f "$LAB/cluster" 2>/dev/null
exit 0
