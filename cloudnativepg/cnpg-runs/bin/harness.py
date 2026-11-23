#!/usr/bin/env python3
import sys, os, json, time, random, re, subprocess, threading, csv, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib
from lib import *
BIN = os.path.dirname(os.path.abspath(__file__))
RUNS = '/root/cnpg/runs'; os.makedirs(RUNS, exist_ok=True)
MiB = 1048576
BYTES_PER_TXN = float(open('/root/cnpg/bytes_per_txn').read()) if os.path.exists('/root/cnpg/bytes_per_txn') else 8850.0
NWRITERS = 4
PGYAML = '/root/cnpg/pg.yaml'
CSVF = '/root/cnpg/results.csv'
COLS = ['run_id','ts','scenario','target_mib','valid','invalid_reason','failover_delay','old_primary','candidate','promoted_node',
 'gap_cand_bytes','gap_other_bytes','gap_ratio','gap_grow_s','opview_gap_cand_bytes','opview_gap_other_bytes','pre_fault_in_sync_bytes',
 'fork_lsn','fork_vs_recv_diff','acked_total','primary_rows_before','surviving_at_promotion','lost_at_promotion','lost_bytes_est',
 'surviving_final','lost_final','sha_acked','sha_surviving','promoted','t_decision_s','t_promoted_s','outcome','post_state','cmd_output_flags','log_flags','notes']

def exec_node(node, cmd): return sh(f"docker exec {node} sh -c '{cmd}'")
def stall(node, P, Rs):
    for R in Rs:
        exec_node(node, f"iptables -I FORWARD 1 -s {R} -d {P} -p tcp --dport 5432 -m comment --comment cnpgstall -j DROP")
        exec_node(node, f"iptables -I FORWARD 1 -s {P} -d {R} -p tcp --sport 5432 -m comment --comment cnpgstall -j DROP")
def release_all():
    rc, o = sh("docker ps --format '{{.Names}}' --filter name=cnpg-")
    for node in o.split():
        while True:
            rc, o2 = exec_node(node, "iptables -S FORWARD | grep cnpgstall | head -1")
            line = o2.strip()
            if not line or not line.startswith('-A'): break
            exec_node(node, "iptables " + line.replace('-A', '-D', 1))
def stall_rule_count(node):
    rc, o = exec_node(node, "iptables -S FORWARD | grep -c cnpgstall"); return int(o.strip() or 0)

DESIRED_DELAY = [None]
def set_delay(n):
    DESIRED_DELAY[0] = n
    kc(f"patch cluster pg --type merge -p '{{\"spec\":{{\"failoverDelay\":{n}}}}}'")

def wait_healthy(timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        cl = cluster(); ps = pods()
        if cl and cl['status'].get('phase') == 'Cluster in healthy state' and len(ps) == 3 and all(p['ready'] and not p['deleting'] and p['ip'] for p in ps.values()):
            prim = cl['status'].get('currentPrimary')
            try:
                pc = conn(ps[prim]['ip']); pl = prim_lsn(pc)
                ok = True
                for n, p in ps.items():
                    if n == prim: continue
                    rc_ = conn(p['ip']); rl = recv_lsn(rc_)
                    cu_ = rc_.cursor(); cu_.execute("select status from pg_stat_wal_receiver"); wr_ = cu_.fetchall(); rc_.close()
                    if abs(pl - rl) > 1*MiB or not wr_ or wr_[0][0] != 'streaming': ok = False
                pc.close()
                if ok: return True
            except Exception: pass
        time.sleep(3)
    return False

def rebuild(log):
    log('REBUILD cluster pg')
    kc('delete cluster pg --wait=true', 300); sh('kubectl delete pvc -l cnpg.io/cluster=pg --wait=true', 300)
    rc, o = sh(f'kubectl apply -f {PGYAML}'); log(o.strip())
    kc('wait --for=condition=Ready cluster/pg --timeout=600s', 620)
    rc, o = sh("kubectl get secret pg-superuser -o jsonpath='{.data.password}' | base64 -d > /root/cnpg/su.pw")
    lib.PW = open('/root/cnpg/su.pw').read().strip()
    if DESIRED_DELAY[0] is not None: set_delay(DESIRED_DELAY[0]); time.sleep(3)
    return wait_healthy(300)

def ensure_ready(log, diagdir=None):
    release_all()
    for n in [x for x in sh("kubectl get nodes -o name")[1].split()]:
        kc(f"uncordon {n.split('/')[1]}")
    t0 = time.time()
    if wait_healthy(420): log(f'healthy after {time.time()-t0:.0f}s'); return True
    if diagdir:
        os.makedirs(diagdir, exist_ok=True)
        for cmd, fn in [('kubectl get pods -o wide', 'diag_pods.txt'), ('kubectl get cluster pg -o yaml', 'diag_cluster.yaml'),
                        ('kubectl get events --sort-by=.lastTimestamp', 'diag_events.txt'), ('kubectl cnpg status pg', 'diag_status.txt'),
                        ('for p in $(kubectl get pods -o name); do echo == $p; kubectl logs $p -c postgres --tail=40 2>&1 | cut -c1-300; done', 'diag_podlogs.txt'),
                        ('kubectl -n cnpg-system logs deploy/cnpg-cloudnative-pg --tail=80', 'diag_operator.txt')]:
            open(f'{diagdir}/{fn}', 'w').write(sh(cmd, 90)[1])
    log('NOT healthy after 420s; diagnostics saved; rebuilding')
    return rebuild(log)

def parse_opview(txt):
    """Instances status table from `kubectl cnpg status`: name -> (role, current LSN int)"""
    out = {}; on = False
    for ln in txt.splitlines():
        if ln.startswith('Instances status'): on = True; continue
        if on:
            m = re.match(r'^(pg-\d+)\s+(\S+)\s+(Primary|Standby[^\n]*?)\s{2,}', ln)
            if m and re.match(r'^[0-9A-F]+/[0-9A-F]+$', m.group(2)):
                out[m.group(1)] = (m.group(3).strip(), lsn_str_to_int(m.group(2)))
    return out

LAGRE = re.compile(r'lag|behind|data ?loss|lose|lost|unsafe|not safe|refus|reject|cannot promote|can.t promote|not eligible|diverg|warning|aligned|advanced', re.I)

def run_one(scenario, target_mib, rid, rundir):
    os.makedirs(rundir, exist_ok=True)
    log = Log(rundir + '/events.log')
    row = {c: '' for c in COLS}; row.update(run_id=rid, ts=ts(), scenario=scenario, target_mib=target_mib, valid=0)
    target = target_mib * MiB
    tbl_ = [None]
    def invalid(why, **kw):
        log('INVALID: ' + why); row['invalid_reason'] = why; row.update(kw)
        try:
            open(f'{rundir}/STOP', 'w').write('1'); release_all()
            if tbl_[0]:
                cl_ = cluster(); pc_ = conn(pods()[cl_['status']['currentPrimary']]['ip']); pc_.cursor().execute(f'drop table if exists {tbl_[0]}'); pc_.close()
        except Exception as e: log('invalid-cleanup issue: ' + repr(e))
        return row
    # --- precheck
    if not ensure_ready(log, rundir): return invalid('cluster not healthy before run (rebuild failed)')
    cl = cluster(); old = cl['status']['currentPrimary']; ps = pods()
    delay = cl['spec'].get('failoverDelay', 0); row['failover_delay'] = delay; row['old_primary'] = old
    if DESIRED_DELAY[0] is not None and delay != DESIRED_DELAY[0]: return invalid(f'failoverDelay is {delay}, expected {DESIRED_DELAY[0]}')
    P = ps[old]['ip']; pnode = ps[old]['node']
    reps = {n: p for n, p in ps.items() if n != old}
    Rips = [p['ip'] for p in reps.values()]
    log(f'primary {old} {P} on {pnode}; replicas ' + ', '.join(f'{n}={p["ip"]}@{p["node"]}' for n, p in reps.items()) + f'; failoverDelay={delay}')
    pc = conn(P); rcs = {n: conn(p['ip']) for n, p in reps.items()}
    time.sleep(1)
    row['pre_fault_in_sync_bytes'] = prim_lsn(pc) - max(recv_lsn(c) for c in rcs.values())
    table = 't_' + re.sub(r'\W', '_', rid)
    q1(pc, f"create table {table}(id bigint primary key, w int, payload bytea)") if False else pc.cursor().execute(f"drop table if exists {table}"); pc.cursor().execute(f"create table {table}(id bigint primary key, w int, payload bytea)")
    tbl_[0] = table
    stopf = f'{rundir}/STOP'; ratef = f'{rundir}/RATE'
    if os.path.exists(stopf): os.remove(stopf)
    burst = scenario == 'Bb'
    slow_total = (target / BYTES_PER_TXN) / 15.0
    base_total = 40.0 if burst else slow_total
    open(ratef, 'w').write(str(base_total / NWRITERS))
    procs = []
    for w in range(NWRITERS):
        f = f'{rundir}/acked_w{w+1}.csv'
        if os.path.exists(f): os.remove(f)
        procs.append(subprocess.Popen(['python3', f'{BIN}/writer.py', P, table, str(w+1), str(base_total / NWRITERS), stopf, f, '/root/cnpg/su.pw', ratef]))
    time.sleep(3 + random.uniform(0, 5))
    log(f'writers started (base {base_total:.1f} txn/s total); jitter done')
    # --- pre-stall snapshot: both replicas must be streaming and in sync
    pl0 = prim_lsn(pc); pre = {}
    for n_, c_ in rcs.items():
        cur_ = c_.cursor(); cur_.execute("select status, sender_host, sender_port from pg_stat_wal_receiver"); wr = cur_.fetchall()
        pre[n_] = dict(gap=pl0 - recv_lsn(c_), walreceiver=wr)
    log(f'pre-stall snapshot: {pre}')
    json.dump(pre, open(rundir + '/pre_stall.json', 'w'))
    # --- stall
    t_stall = time.time()
    stall(pnode, P, Rips)
    if burst: open(ratef, 'w').write(str(3000.0 / NWRITERS))
    log(f'stall rules applied on {pnode}: {stall_rule_count(pnode)} rules')
    # --- grow
    gap = {}; last_log = time.time()
    deadline = t_stall + (120 if not burst else 60)
    while time.time() < deadline:
        pl = prim_lsn(pc)
        gap = {n: pl - recv_lsn(c) for n, c in rcs.items()}
        if min(gap.values()) >= target: break
        if time.time() - last_log > 5: last_log = time.time(); log(f'growing: {gap}')
        time.sleep(0.02)
    t_grow = time.time() - t_stall
    open(stopf, 'w').write('1')
    for p in procs:
        try: p.wait(15)
        except Exception: p.kill()
    log(f'gap reached {gap} in {t_grow:.2f}s; writers stopped')
    open(rundir + '/iptables_counters.txt', 'w').write(exec_node(pnode, "iptables -L FORWARD -v -n | grep -E 'cnpgstall|Chain'")[1])
    # --- verified gap
    time.sleep(0.2)
    pl = prim_lsn(pc)
    recv = {n: recv_lsn(c) for n, c in rcs.items()}; repl = {n: replay_lsn(c) for n, c in rcs.items()}
    gaps = {n: pl - r for n, r in recv.items()}
    cand = min(gaps, key=lambda n: gaps[n]); other = [n for n in gaps if n != cand][0]
    row.update(candidate=cand, gap_cand_bytes=gaps[cand], gap_other_bytes=gaps[other], gap_ratio=round(gaps[cand] / target, 3), gap_grow_s=round(t_grow, 2))
    log(f'VERIFIED primary_lsn={pl} recv={recv} replay={repl} gaps={gaps} ratio={row["gap_ratio"]}')
    json.dump(dict(primary_lsn=pl, recv=recv, replay=repl, gaps=gaps), open(rundir + '/gap_verified.json', 'w'))
    acked = []
    for w in range(NWRITERS):
        for ln in open(f'{rundir}/acked_w{w+1}.csv'):
            ln = ln.strip()
            if ln.startswith('ERR'): log('writer error: ' + ln)
            elif ln and not ln.startswith('DONE'): acked.append(int(ln))
    acked.sort()
    open(rundir + '/acked.txt', 'w').write('\n'.join(map(str, acked)) + '\n')
    row['acked_total'] = len(acked); row['sha_acked'] = sha_file(rundir + '/acked.txt')
    row['primary_rows_before'] = int(q1(pc, f"select count(*) from {table}"))
    if row['primary_rows_before'] != len(acked):
        return invalid(f'acked_total {len(acked)} != primary rows {row["primary_rows_before"]}')
    if any(v['gap'] > 1 * MiB or not v['walreceiver'] for v in pre.values()):
        return invalid(f'replicas not streaming/in sync at stall start: {pre}')
    if not burst and t_grow > 25:
        return invalid(f'gap grew too slowly ({t_grow:.1f}s vs ~15s): a replica kept receiving after the stall; see iptables_counters.txt')
    if not (0.75 <= gaps[cand] / target <= 1.25):
        return invalid(f'gap off target: {gaps[cand]} vs {target} (ratio {gaps[cand]/target:.3f})')
    # --- operator view (pre-fault, what the operator reports now)
    rc, st = sh('kubectl cnpg status pg', 60); open(rundir + '/cnpg_status_prefault.txt', 'w').write(st)
    ov = parse_opview(st)
    if old in ov:
        for n in reps:
            if n in ov:
                row['opview_gap_cand_bytes' if n == cand else 'opview_gap_other_bytes'] = ov[old][1] - ov[n][1]
    log(f'operator view (kubectl cnpg status, pre-fault): {ov}')
    # --- fault: primary loss
    pc.close()
    t_fault = time.time(); wall_fault = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_fault))
    kc(f'cordon {pnode}')
    rc, o = kc(f'delete pod {old} --grace-period=0 --force', 60); log('delete pod: ' + o.strip().replace('\n', ' | '))
    log('FAULT: node cordoned, primary pod force-deleted; stall rules stay in place')
    t0 = time.time(); promoted = None; cmd_out = ''; early = {}
    time.sleep(3)
    rc, st = sh('kubectl cnpg status pg', 60); open(rundir + '/cnpg_status_after_fault.txt', 'w').write(st)
    t_decision = None
    if scenario in ('B', 'Bb'):
        pass
    elif scenario == 'C':
        rc, cmd_out = sh(f'kubectl cnpg promote pg {cand}', 90); log('promote cmd: ' + cmd_out.strip().replace('\n', ' | '))
        open(rundir + '/promote_cmd.txt', 'w').write(cmd_out)
    elif scenario == 'D':
        try:
            cc = conn(reps[cand]['ip'], 10)
            t1 = time.time(); r = q1(cc, "select pg_promote(true, 60)"); cmd_out = f'pg_promote -> {r} in {time.time()-t1:.2f}s'
            log(cmd_out); open(rundir + '/pg_promote.txt', 'w').write(cmd_out)
            promoted = cand; t_decision = time.time() - t_fault
            # read survivors + timeline history NOW: the operator shuts the unauthorised primary down within seconds
            try:
                cur_ = cc.cursor(); cur_.execute(f"select id from {table} order by id"); early['sv'] = [r[0] for r in cur_.fetchall()]
                tli_ = q1(cc, "select ('x'||substring(pg_walfile_name(pg_current_wal_lsn()) for 8))::bit(32)::int")
                early['tli'] = tli_
                early['hist'] = q1(cc, f"select convert_from(pg_read_binary_file('pg_wal/'||lpad(to_hex({tli_}),8,'0')||'.history'),'UTF8')")
                early['t'] = time.time() - t_fault; log(f"early read on candidate ok: {len(early['sv'])} rows, tli {tli_}")
            except Exception as e: log('early read failed: ' + repr(e))
        except Exception as e:
            log('pg_promote failed: ' + str(e)); open(rundir + '/pg_promote.txt', 'w').write(str(e))
            return invalid('pg_promote failed: ' + str(e)[:150].replace(chr(10), ' ') + ' (operator may have promoted first); recovery follows in next run precheck')
    # --- wait for decision
    limit = 300 if scenario in ('B', 'Bb') else 180
    tgt_seen = None
    while promoted is None and time.time() - t_fault < limit:
        c2 = cluster()
        if c2:
            s = c2['status']
            if tgt_seen is None and s.get('targetPrimary') not in (None, old, 'pending'):
                tgt_seen = time.time() - t_fault; log(f'targetPrimary={s.get("targetPrimary")} phase={s.get("phase")}')
            if s.get('currentPrimary') not in (None, old) and s.get('currentPrimary') != 'pending':
                p2 = pods().get(s['currentPrimary'])
                if p2 and p2['ready']:
                    promoted = s['currentPrimary']; break
        time.sleep(1)
    t_prom = time.time() - t_fault
    row['promoted'] = int(promoted is not None); row['promoted_node'] = promoted or ''
    row['t_decision_s'] = round(tgt_seen, 1) if tgt_seen else (round(t_decision, 1) if t_decision else '')
    row['t_promoted_s'] = round(t_prom, 1) if promoted else ''
    log(f'decision: promoted={promoted} after {t_prom:.1f}s')
    # --- logs
    rc, ol = sh(f"kubectl -n cnpg-system logs deploy/cnpg-cloudnative-pg --since-time={wall_fault}", 60); open(rundir + '/operator.log', 'w').write(ol)
    rc, ev = sh(f"kubectl get events --sort-by=.lastTimestamp -o custom-columns=T:.lastTimestamp,R:.reason,O:.involvedObject.name,M:.message", 60); open(rundir + '/events_k8s.txt', 'w').write(ev)
    row['cmd_output_flags'] = ';'.join(sorted(set(m.lower() for m in LAGRE.findall(cmd_out))))
    row['log_flags'] = ';'.join(sorted(set(m.lower() for l in ol.splitlines() if re.search(r'promot|failover|switch|elect|target', l, re.I) for m in LAGRE.findall(l))))
    if promoted:
        # survivors at promotion
        newip = pods()[promoted]['ip'] if promoted in pods() else reps[promoted]['ip']
        sv = early.get('sv'); hist = early.get('hist', ''); tli = early.get('tli', '')
        for _ in range(0 if early.get('sv') is not None else 45):                       # survivors first; timeline history only exists once the node has left recovery
            try:
                nc = conn(newip)
                if sv is None:
                    rows_ = nc.cursor(); rows_.execute(f"select id from {table} order by id"); sv = [r[0] for r in rows_.fetchall()]
                if q1(nc, "select pg_is_in_recovery()"): nc.close(); time.sleep(2); continue
                tli = q1(nc, "select ('x'||substring(pg_walfile_name(pg_current_wal_lsn()) for 8))::bit(32)::int")
                hist = q1(nc, f"select convert_from(pg_read_binary_file('pg_wal/'||lpad(to_hex({tli}),8,'0')||'.history'),'UTF8')")
                nc.close(); break
            except Exception as e: time.sleep(2)
        if sv is not None:
            open(rundir + '/surviving_at_promotion.txt', 'w').write('\n'.join(map(str, sv)) + '\n')
            sset = set(sv); lost = [a for a in acked if a not in sset]
            open(rundir + '/lost_ids.txt', 'w').write('\n'.join(map(str, lost)) + '\n')
            open(rundir + '/timeline_history.txt', 'w').write(str(hist))
            row.update(surviving_at_promotion=len(sv), lost_at_promotion=len(lost), sha_surviving=sha_file(rundir + '/surviving_at_promotion.txt'))
            lines = [l for l in str(hist).splitlines() if re.match(r'^\d+\t', l)]
            if lines:
                fork = lines[-1].split('\t')[1]; row['fork_lsn'] = fork
                row['fork_vs_recv_diff'] = lsn_str_to_int(fork) - recv[promoted]
                row['lost_bytes_est'] = pl - lsn_str_to_int(fork)
            log(f'survivors at promotion: {len(sv)} of {len(acked)} acked; lost {len(lost)}; fork {row["fork_lsn"]}; tli {tli}')
    # --- outcome
    if not promoted: row['outcome'] = 'refused_or_no_promotion'
    else:
        row['outcome'] = 'promoted_warned' if (row['cmd_output_flags'] or row['log_flags']) else 'promoted_silent'
    # --- D: observe post-promotion behaviour
    if scenario == 'D' and promoted:
        obs = []; ds = None
        for i in range(30):
            try:
                cc2 = conn(reps[cand]['ip'], 5); rec = q1(cc2, 'select pg_is_in_recovery()'); cc2.close()
            except Exception as e: rec = 'conn_err'
            c3 = cluster(); s3 = c3['status'] if c3 else {}
            obs.append(dict(t=round(time.time() - t_fault, 1), in_recovery=rec, curP=s3.get('currentPrimary'), tgtP=s3.get('targetPrimary'), phase=s3.get('phase')))
            time.sleep(2)
        json.dump(obs, open(rundir + '/post_promote_obs.json', 'w'))
        states = [o['in_recovery'] for o in obs]
        row['post_state'] = 'demoted_after' if (True in states or 'conn_err' in states) else 'stayed_primary'
        rc, ol2 = sh(f"kubectl -n cnpg-system logs deploy/cnpg-cloudnative-pg --since-time={wall_fault}", 60); open(rundir + '/operator_after.log', 'w').write(ol2)
        rc, pj = kc(f"get pod {cand} -o jsonpath='{{.status.containerStatuses[0].restartCount}} {{.status.containerStatuses[0].lastState}}'"); open(rundir + '/cand_pod_state.txt', 'w').write(pj)
        rc, pv = sh(f"kubectl logs {cand} -c postgres --previous | tail -60 | cut -c1-400", 60); open(rundir + f'/{cand}_postgres_previous.log', 'w').write(pv)
        rc, pl_ = sh(f"kubectl logs {cand} -c postgres --since-time={wall_fault} | grep -v 'DB not available\\|startup probe' | head -60 | cut -c1-400", 60); open(rundir + f'/{cand}_postgres_after.log', 'w').write(pl_)
    # --- recover and final survivors
    release_all()
    fin = None
    if scenario == 'D':
        # the promoted-then-restarted candidate stays a diverged, non-streaming replica (observed); rebuild from scratch like the pilot did after D
        rc, st2 = sh('kubectl cnpg status pg', 60); open(rundir + '/cnpg_status_post_obs.txt', 'w').write(st2)
        for n_ in sh("kubectl get nodes -o name")[1].split(): kc(f"uncordon {n_.split('/')[1]}")
        ok = False
        log('D: rebuilding cluster after run'); rebuilt = rebuild(log)
        row['notes'] += 'cluster rebuilt after D run (by design); '
        row['valid'] = 1
        if row['promoted'] == 1 and row['lost_at_promotion'] == '': row['valid'] = 0; row['invalid_reason'] = 'survivors not read at promotion'
        log('run complete'); return row
    ok = ensure_ready(log, rundir)
    if ok:
        try:
            cl2 = cluster(); fp = pods()[cl2['status']['currentPrimary']]['ip']; fc = conn(fp)
            cur = fc.cursor(); cur.execute(f"select id from {table} order by id"); fin = [r[0] for r in cur.fetchall()]
            open(rundir + '/surviving_final.txt', 'w').write('\n'.join(map(str, fin)) + '\n')
            row['surviving_final'] = len(fin); row['lost_final'] = len(set(acked) - set(fin))
            cur.execute(f"drop table {table}"); fc.close()
        except Exception as e: log('final read failed: ' + str(e))
    else: log('cluster rebuilt (final survivors unavailable)'); row['notes'] += 'cluster rebuilt after run; '
    row['valid'] = 1
    if row['promoted'] == 1 and row['lost_at_promotion'] == '': row['valid'] = 0; row['invalid_reason'] = 'survivors not read at promotion'
    log('run complete')
    return row

def append_row(row):
    new = not os.path.exists(CSVF)
    with open(CSVF, 'a', newline='') as f:
        w = csv.DictWriter(f, COLS); 
        if new: w.writeheader()
        w.writerow({c: row.get(c, '') for c in COLS})

if __name__ == '__main__':
    scenario, tgt, rid = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    r = run_one(scenario, tgt, rid, f'{RUNS}/{rid}')
    print(json.dumps(r, indent=1))
