#!/usr/bin/env python3
"""One writer: one INSERT of an 8000-byte bytea per autocommit txn; logs an id only after COMMIT returns."""
import os, sys, time, psycopg2
host, table, wid, rate, stopfile, outfile, pwfile, ratefile = sys.argv[1:9]
wid = int(wid); rate = float(rate)           # rate = txn/s for this writer, 0 = uncapped
pw = open(pwfile).read().strip()
c = psycopg2.connect(host=host, user='postgres', password=pw, dbname='app', connect_timeout=5, sslmode='disable')
c.autocommit = True
cur = c.cursor()
payload = psycopg2.Binary(os.urandom(8000))
out = open(outfile, 'a', buffering=1)
n = 0
t0 = time.time(); n0 = 0; lastchk = 0.0
while not os.path.exists(stopfile):
    i = wid * 10**9 + n
    try:
        cur.execute(f"INSERT INTO {table}(id,w,payload) VALUES (%s,%s,%s)", (i, wid, payload))
    except Exception as e:
        out.write(f"ERR,{i},{type(e).__name__}\n"); break
    out.write(f"{i}\n"); n += 1          # acked: COMMIT returned
    if time.time() - lastchk > 0.05:
        lastchk = time.time()
        try:
            nr = float(open(ratefile).read())
            if nr != rate: rate = nr; t0 = time.time(); n0 = n
        except Exception: pass
    if rate > 0:
        d = t0 + (n - n0) / rate - time.time()
        if d > 0: time.sleep(d)
out.write(f"DONE,{n}\n")
