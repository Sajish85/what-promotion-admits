#!/bin/bash
# Fresh 3-node async Patroni cluster (Patroni defaults; see PILOT-REPORT for the listed deviations).
source "$(dirname "$0")/env.sh"
"$LAB/bin/cluster-down.sh" >/dev/null 2>&1
rm -rf "$LAB/cluster" && mkdir -p "$LAB/cluster/etcd" "$LAB/cluster/logs"
nohup etcd --name pilot --data-dir "$LAB/cluster/etcd/data" \
  --listen-client-urls http://127.0.0.1:$ETCD_PORT --advertise-client-urls http://127.0.0.1:$ETCD_PORT \
  --listen-peer-urls http://127.0.0.1:22380 --initial-advertise-peer-urls http://127.0.0.1:22380 \
  --initial-cluster pilot=http://127.0.0.1:22380 > "$LAB/cluster/logs/etcd.log" 2>&1 &
echo $! > "$LAB/cluster/etcd.pid"
for i in $(seq 30); do etcdctl --endpoints=127.0.0.1:$ETCD_PORT endpoint health >/dev/null 2>&1 && break; sleep 0.5; done
for n in $NODES; do
  nohup python3 "$LAB/bin/tcpproxy.py" $(rpx_port $n) $(pg_port $n) $(rpx_ctl $n) > "$LAB/cluster/logs/rpx-$n.log" 2>&1 &
  echo $! > "$LAB/cluster/rpx-$n.pid"
  nohup python3 "$LAB/bin/tcpproxy.py" $(epx_port $n) $ETCD_PORT $(epx_ctl $n) > "$LAB/cluster/logs/epx-$n.log" 2>&1 &
  echo $! > "$LAB/cluster/epx-$n.pid"
done
sleep 1
for n in $NODES; do
  d=$LAB/cluster/$n; mkdir -p $d
  cat > $d/patroni.yml <<YML
scope: pilot
name: $n
restapi:
  listen: 127.0.0.1:$(rest_port $n)
  connect_address: 127.0.0.1:$(rest_port $n)
etcd3:
  use_proxies: true
  host: 127.0.0.1:$(epx_port $n)
bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    primary_start_timeout: 300
    synchronous_mode: false
    postgresql:
      use_pg_rewind: true
  initdb:
    - encoding: UTF8
    - data-checksums
  pg_hba:
    - host replication replicator 127.0.0.1/32 trust
    - host all all 127.0.0.1/32 trust
postgresql:
  listen: 127.0.0.1:$(pg_port $n)
  connect_address: 127.0.0.1:$(rpx_port $n)
  data_dir: $d/data
  bin_dir: $PGBIN
  pgpass: $d/pgpass
  authentication:
    replication: {username: replicator, password: CHANGEME}
    superuser: {username: postgres, password: CHANGEME}
  parameters:
    unix_socket_directories: $d
tags:
  nofailover: false
  noloadbalance: false
YML
  nohup patroni $d/patroni.yml > $LAB/cluster/logs/$n.log 2>&1 &
  echo $! > $d/patroni.pid
  [ $n = pg1 ] && sleep 12
done
# control config for patronictl (direct to etcd, no proxy)
cat > $LAB/cluster/ctl.yml <<YML
scope: pilot
name: ctl
restapi:
  listen: 127.0.0.1:9099
  connect_address: 127.0.0.1:9099
etcd3:
  use_proxies: true
  host: 127.0.0.1:$ETCD_PORT
postgresql:
  data_dir: $LAB/cluster/ctl-data
  listen: 127.0.0.1:6499
  connect_address: 127.0.0.1:6499
YML
echo up
