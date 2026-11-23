#!/usr/bin/env python3
"""Heartbeat writer. usage: writer.py WRITER_ID TABLE OUT.csv [PAYLOAD_BYTES] [TPS_CAP]
One autocommit INSERT (writer, seq, payload) per txn; seq increments per attempt. Output rows: seq,t_end,outcome
(committed = COMMIT acknowledged to this client). Stops on SIGTERM/SIGINT. Multi-host DSN finds the current primary."""
import sys, os, time, signal, psycopg2
wid, table, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
pb = int(sys.argv[4]) if len(sys.argv) > 4 else 8000
tps = float(sys.argv[5]) if len(sys.argv) > 5 else 0   # per-writer rate cap, 0 = unthrottled
ports = os.environ.get("PG_PORTS", "6441,6442,6443")
DSN = (f"host={','.join(['127.0.0.1']*len(ports.split(',')))} port={ports} dbname=postgres user=postgres "
       "target_session_attrs=read-write connect_timeout=2 tcp_user_timeout=3000 options='-c statement_timeout=3000'")
payload = psycopg2.Binary(os.urandom(pb))
stop = False
def _s(*a):
    global stop; stop = True
signal.signal(signal.SIGTERM, _s); signal.signal(signal.SIGINT, _s)
f = open(out, "w", buffering=1); f.write("seq,t_end,outcome\n")
conn = None; seq = 0; nxt = time.time()
while not stop:
    seq += 1; outcome = "committed"
    try:
        if conn is None:
            conn = psycopg2.connect(DSN); conn.autocommit = True
        cur = conn.cursor(); cur.execute(f"INSERT INTO {table}(writer,seq,payload) VALUES (%s,%s,%s)", (wid, seq, payload)); cur.close()
    except Exception:
        outcome = "error"
        try:
            if conn is not None: conn.close()
        except Exception: pass
        conn = None; time.sleep(0.05)
    f.write(f"{seq},{time.time():.6f},{outcome}\n")
    if tps > 0:
        nxt += 1.0 / tps; d = nxt - time.time()
        if d > 0: time.sleep(d)
        else: nxt = time.time()
f.close()
