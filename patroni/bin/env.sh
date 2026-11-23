# pilot rig paths and ports (own port range; the lab's default ports are held by other projects' clusters)
export LAB=$HOME/invention-hunt/pilots/failover-gate
export PGBIN=$HOME/tools/pg/17/bin
export ETCD_DIR=$HOME/tools/etcd/etcd-v3.7.3-darwin-arm64
export VENV=$HOME/tools/venv
export PATH=$VENV/bin:$PGBIN:$ETCD_DIR:$PATH
export PYTHONWARNINGS=ignore
NODES="pg1 pg2 pg3"
# real PG port, replication-proxy port (the node's connect_address), replication-proxy control port,
# REST port, etcd-proxy port (the node's Patroni DCS path), etcd-proxy control port
pg_port()    { case $1 in pg1) echo 6441;; pg2) echo 6442;; pg3) echo 6443;; esac; }
rpx_port()   { case $1 in pg1) echo 6451;; pg2) echo 6452;; pg3) echo 6453;; esac; }
rpx_ctl()    { case $1 in pg1) echo 6461;; pg2) echo 6462;; pg3) echo 6463;; esac; }
rest_port()  { case $1 in pg1) echo 9008;; pg2) echo 9009;; pg3) echo 9010;; esac; }
epx_port()   { case $1 in pg1) echo 22391;; pg2) echo 22392;; pg3) echo 22393;; esac; }
epx_ctl()    { case $1 in pg1) echo 22481;; pg2) echo 22482;; pg3) echo 22483;; esac; }
export ETCD_PORT=22379
