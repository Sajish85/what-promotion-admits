import json, subprocess, time, hashlib, re, os, psycopg2
PW = open('/root/cnpg/su.pw').read().strip()
def sh(cmd, timeout=120, check=False):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode: raise RuntimeError(f"{cmd}: {r.stderr[:300]}")
    return r.returncode, (r.stdout + r.stderr)
def kc(args, timeout=60): return sh('kubectl ' + args, timeout)
def cluster():
    rc, o = kc('get cluster pg -o json')
    return json.loads(o) if rc == 0 else None
def pods():
    rc, o = kc('get pods -l cnpg.io/cluster=pg,cnpg.io/podRole=instance -o json')
    d = {}
    if rc: return d
    for p in json.loads(o)['items']:
        n = p['metadata']['name']
        ready = any(c['type'] == 'Ready' and c['status'] == 'True' for c in p['status'].get('conditions', []))
        d[n] = dict(ip=p['status'].get('podIP'), node=p['spec'].get('nodeName'), ready=ready,
                    deleting=bool(p['metadata'].get('deletionTimestamp')), role=p['metadata'].get('labels', {}).get('cnpg.io/instanceRole'))
    return d
def conn(ip, timeout=5):
    c = psycopg2.connect(host=ip, user='postgres', password=PW, dbname='app', connect_timeout=timeout, sslmode='disable')
    c.autocommit = True
    return c
def q1(c, sql):
    cur = c.cursor(); cur.execute(sql); r = cur.fetchone(); cur.close(); return r[0] if r else None
LSN0 = "'0/0'"
def prim_lsn(c): return int(q1(c, f"select pg_wal_lsn_diff(pg_current_wal_lsn(),{LSN0})"))
def recv_lsn(c): return int(q1(c, f"select pg_wal_lsn_diff(pg_last_wal_receive_lsn(),{LSN0})"))
def replay_lsn(c): return int(q1(c, f"select pg_wal_lsn_diff(pg_last_wal_replay_lsn(),{LSN0})"))
def lsn_str_to_int(s):
    a, b = s.split('/'); return (int(a, 16) << 32) + int(b, 16)
def sha_file(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def ts(): return time.strftime('%Y-%m-%dT%H:%M:%S')
class Log:
    def __init__(s, p): s.f = open(p, 'a', buffering=1); s.t0 = time.time()
    def __call__(s, m): s.f.write(f"{time.time():.3f} +{time.time()-s.t0:7.2f}s {m}\n")
