# study rig paths and ports (own range 647x-651x; pilot used 644x-6463/9008+/22xxx; other projects hold 2379, 8008-8010, 5442/5443)
export ST=$HOME/invention-hunt/studies/failover-gate
export PGBIN=$HOME/tools/pg/17/bin
export VENV=$HOME/tools/venv
export PATH=$ST/bin:$VENV/bin:$PGBIN:/usr/bin:/bin:/usr/sbin:/sbin
export PYTHONWARNINGS=ignore
export PGAF_MON_PORT=6470
export MON_URI_DIRECT="postgres://autoctl_node@127.0.0.1:6470/pg_auto_failover?sslmode=disable"
NODES="n1 n2 n3"
pg_port()  { case $1 in n1) echo 6471;; n2) echo 6472;; n3) echo 6473;; esac; }   # real postgres port
rpx_port() { case $1 in n1) echo 6481;; n2) echo 6482;; n3) echo 6483;; esac; }   # registered nodeport = replication/health proxy
rpx_ctl()  { case $1 in n1) echo 6491;; n2) echo 6492;; n3) echo 6493;; esac; }
mpx_port() { case $1 in n1) echo 6501;; n2) echo 6502;; n3) echo 6503;; esac; }   # keeper -> monitor proxy
mpx_ctl()  { case $1 in n1) echo 6511;; n2) echo 6512;; n3) echo 6513;; esac; }

# keeper config/state live under XDG dirs keyed by pgdata path: keep them inside the rig dir so cluster-down wipes them
export XDG_CONFIG_HOME=$ST/cluster/xdg/config
export XDG_DATA_HOME=$ST/cluster/xdg/data
