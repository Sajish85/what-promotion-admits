#!/usr/bin/env python3
"""Failover Gate pilot, round 2 harness. Run with the lab venv python.
usage: harness.py SCEN TARGET_MB RUNNO       (SCEN in B C D E)
One run = one fault on the shared 3-node cluster (see PILOT-REPORT.md). Evidence goes to runs/<SCEN>-<MB>MB-rNN/.
Lag = WAL the candidate has not RECEIVED: replication is stalled through the primary's TCP proxy while writers run;
writers stop when (primary pg_current_wal_lsn - candidate pg_last_wal_receive_lsn) reaches the target; the gap is
re-read from both servers right before the fault and stored."""
import os, sys, json, time, subprocess, random, signal, hashlib, re, glob, csv, shutil, urllib.request
import psycopg2

LAB = os.path.expanduser("~/invention-hunt/pilots/failover-gate")
BIN = f"{LAB}/bin"
NODES = ["pg1", "pg2", "pg3"]
PG = {"pg1": 6441, "pg2": 6442, "pg3": 6443}
RPX_CTL = {"pg1": 6461, "pg2": 6462, "pg3": 6463}
EPX_CTL = {"pg1": 22481, "pg2": 22482, "pg3": 22483}
REST = {"pg1": 9008, "pg2": 9009, "pg3": 9010}
ETCD = 22379
MIB = 1048576
GROWTH_S = 15.0            # designed time for the shipping gap to grow to target (all scenarios)
WAL_PER_TXN = 8850.0       # calibrated: WAL bytes per 8000-byte bytea insert (see PILOT-REPORT)
NWRITERS = 4
PAYLOAD = 8000
ENV = dict(os.environ)
ENV["PATH"] = f"{os.path.expanduser('~/tools/venv/bin')}:{os.path.expanduser('~/tools/pg/17/bin')}:{os.path.expanduser('~/tools/etcd/etcd-v3.7.3-darwin-arm64')}:" + ENV["PATH"]
ENV["PYTHONWARNINGS"] = "ignore"
CTL = f"{LAB}/cluster/ctl.yml"


def sh(cmd, timeout=60, check=False):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV)
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        return 124, ((e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")) + "TIMEOUT"


def px(ctl, cmd):
    return sh(f"{BIN}/pxctl.sh {ctl} {cmd}", 5)[1].strip()


def conn(node, timeout=3):
    c = psycopg2.connect(host="127.0.0.1", port=PG[node], dbname="postgres", user="postgres", connect_timeout=timeout)
    c.autocommit = True
    return c


def q1(node, sql, timeout=3):
    c = conn(node, timeout)
    try:
        cur = c.cursor(); cur.execute(sql)
        if cur.description is None: return None
        r = cur.fetchone(); return r[0] if r else None
    finally:
        c.close()


def lsn_to_int(s):
    a, b = s.split("/"); return (int(a, 16) << 32) + int(b, 16)


def rest_cluster():
    for n in NODES:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{REST[n]}/cluster", timeout=2) as r:
                return json.loads(r.read())
        except Exception:
            continue
    return None


def leader_name(cl=None):
    cl = cl or rest_cluster()
    if not cl: return None
    for m in cl["members"]:
        if m["role"] in ("leader", "standby_leader") and m["state"] == "running":
            return m["name"]
    return None


def pid_alive(pid):
    try: os.kill(pid, 0); return True
    except Exception: return False


def agent_pid(n):
    try: return int(open(f"{LAB}/cluster/{n}/patroni.pid").read())
    except Exception: return None


def start_agent(n):
    lf = open(f"{LAB}/cluster/logs/{n}.log", "ab")
    p = subprocess.Popen([os.path.expanduser("~/tools/venv/bin/patroni"), f"{LAB}/cluster/{n}/patroni.yml"], stdout=lf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=ENV)
    open(f"{LAB}/cluster/{n}/patroni.pid", "w").write(str(p.pid))


def etcd_snapshot():
    out = {}
    rc, txt = sh(f"etcdctl --endpoints=127.0.0.1:{ETCD} get --prefix /service/pilot/ ", 5)
    lines = txt.splitlines(); i = 0
    while i + 1 < len(lines):
        if lines[i].startswith("/service/pilot/"):
            out[lines[i]] = lines[i + 1]; i += 2
        else: i += 1
    return out


def reported_lag(snap, cand):
    """Patroni's own number: DCS leader optime (/status) minus the member's published xlog_location."""
    try:
        optime = json.loads(snap["/service/pilot/status"])["optime"]
        mem = json.loads(snap[f"/service/pilot/members/{cand}"])
        return optime, mem.get("xlog_location"), optime - mem["xlog_location"]
    except Exception as e:
        return None, None, None


def healthy():
    cl = rest_cluster()
    if not cl: return False
    ld = leader_name(cl)
    if not ld: return False
    reps = [m for m in cl["members"] if m["name"] != ld]
    if len(reps) != 2: return False
    for m in reps:
        if m["state"] != "streaming" or m.get("receive_lag", 1) != 0 or (m.get("replay_lag") or 0) > MIB: return False
    return all(agent_pid(n) and pid_alive(agent_pid(n)) for n in NODES)


def ensure_healthy(log, timeout=240):
    for n in NODES:
        px(RPX_CTL[n], "pass"); px(EPX_CTL[n], "pass")
    t0 = time.time(); last = 0
    while time.time() - t0 < timeout:
        for n in NODES:
            p = agent_pid(n)
            if not (p and pid_alive(p)):
                log(f"restart agent {n}"); start_agent(n)
        if healthy():
            time.sleep(3)
            if healthy(): return True
        time.sleep(3)
    return False


def rebuild(log):
    log("REBUILD cluster")
    sh(f"{BIN}/cluster-up.sh", 300)
    return ensure_healthy(log, 300)


def log_offsets():
    return {n: os.path.getsize(f"{LAB}/cluster/logs/{n}.log") for n in NODES}


def log_slice(off, n):
    with open(f"{LAB}/cluster/logs/{n}.log", "rb") as f:
        f.seek(off[n]); return f.read().decode(errors="replace")


def read_survivors(node, table):
    c = conn(node, 5)
    try:
        cur = c.cursor(); cur.execute(f"SELECT writer, seq FROM {table} ORDER BY 1,2")
        return {(w, s) for w, s in cur.fetchall()}
    finally:
        c.close()


def read_acked(outdir):
    acked = set()
    for w in range(1, NWRITERS + 1):
        for line in open(f"{outdir}/acked_w{w}.csv").read().splitlines()[1:]:
            seq, t, oc = line.split(",")
            if oc == "committed": acked.add((w, int(seq)))
    return acked


def write_set(path, s):
    with open(path, "w") as f:
        for w, sq in sorted(s): f.write(f"{w}:{sq}\n")
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fork_lsn(node, newtl):
    p = f"{LAB}/cluster/{node}/data/pg_wal/{newtl:08X}.history"
    try:
        last = open(p).read().strip().splitlines()[-1].split("\t")
        return lsn_to_int(last[1])
    except Exception:
        return None


def run(scn, target_mb, runno):
    rid = f"{scn}-{target_mb}MB-r{runno:02d}"
    outdir = f"{LAB}/runs/{rid}"
    shutil.rmtree(outdir, ignore_errors=True); os.makedirs(outdir)
    evf = open(f"{outdir}/events.log", "w", buffering=1)
    T0 = time.time()
    def log(m): evf.write(f"{time.time() - T0:8.2f}s {m}\n")
    base = scn[0]; jitter = "j" in scn[1:]; burst = "b" in scn[1:]   # supplementary variants: j = random 0-10 s pre-stall delay, b = unthrottled burst
    res = dict(run_id=rid, scenario=scn, target_mb=target_mb, valid="", invalid_reason="")
    writers = []
    try:
        if not ensure_healthy(log):
            if not rebuild(log):
                res.update(valid="INVALID", invalid_reason="rig: cluster would not become healthy even after rebuild"); return res
            res["note_rebuilt"] = "yes"
        L = leader_name(); reps = [n for n in NODES if n != L]
        X = random.choice(reps) if base in "CDE" else None
        res.update(old_primary=L, candidate=X or "", replicas=",".join(reps))
        log(f"leader={L} replicas={reps} candidate={X}")
        off = log_offsets()
        table = f"hb_{rid.replace('-', '_').lower()}"
        c = conn(L, 5); cur = c.cursor()
        cur.execute(f"CREATE TABLE {table}(writer int, seq int, payload bytea)")
        cur.execute(f"ALTER TABLE {table} ALTER payload SET STORAGE EXTERNAL"); c.close()
        target = target_mb * MIB
        tps_total = target / (GROWTH_S * WAL_PER_TXN)
        tps_w = 0 if burst else tps_total / NWRITERS
        # writers; env keeps the DSN list of real PG ports
        env = dict(ENV, PG_PORTS="6441,6442,6443")
        for w in range(1, NWRITERS + 1):
            writers.append(subprocess.Popen([f"{os.path.expanduser('~/tools/venv/bin/python')}", f"{BIN}/writer.py", str(w), table,
                                             f"{outdir}/acked_w{w}.csv", str(PAYLOAD), f"{tps_w:.3f}"], env=env))
        time.sleep(3)
        # converge check before the fault window
        cL = conn(L, 3); curL = cL.cursor()
        cands = [X] if X else reps
        creps = {n: conn(n, 3) for n in cands}
        def lsn_primary():
            curL.execute("SELECT pg_current_wal_lsn()"); return lsn_to_int(curL.fetchone()[0])
        def lsn_recv(n):
            cr = creps[n].cursor(); cr.execute("SELECT pg_last_wal_receive_lsn()"); return lsn_to_int(cr.fetchone()[0])
        pre_gap = {n: lsn_primary() - lsn_recv(n) for n in cands}
        log(f"pre-stall gap (candidates) bytes={pre_gap} tps_total={tps_total:.1f}")
        if jitter:
            jt = random.uniform(0, 10.0); res["jitter_s"] = f"{jt:.2f}"; log(f"phase jitter {jt:.2f}s before stall"); time.sleep(jt)
            pre_gap = {n: lsn_primary() - lsn_recv(n) for n in cands}
        # --- start of fault window
        if base == "E":
            log("DCS cut: " + px(EPX_CTL[X], "stall"))
        log("replication stall on primary proxy: " + px(RPX_CTL[L], "stall"))
        t_stall = time.time()
        res["stall_t"] = f"{t_stall:.3f}"
        gap = {}
        while True:
            P = lsn_primary(); gap = {n: P - lsn_recv(n) for n in cands}
            g = min(gap.values())
            if g >= target: break
            if time.time() - t_stall > 4 * GROWTH_S:
                res.update(valid="INVALID", invalid_reason=f"gap did not reach target in {4*GROWTH_S:.0f}s (gap={g})"); raise RuntimeError("slow")
            time.sleep(0.02)
        for w in writers: w.send_signal(signal.SIGTERM)
        for w in writers: w.wait(timeout=10)
        writers = []
        time.sleep(0.2)
        P_kill = lsn_primary()
        recv = {n: lsn_recv(n) for n in cands}
        gap = {n: P_kill - recv[n] for n in cands}
        rcv_all = {n: lsn_to_int(q1(n, "SELECT pg_last_wal_receive_lsn()")) for n in reps}
        gap_all = {n: P_kill - rcv_all[n] for n in reps}
        replay_all = {n: lsn_to_int(q1(n, "SELECT pg_last_wal_replay_lsn()")) for n in reps}
        rows_primary = q1(L, f"SELECT count(*) FROM {table}")
        cand_gap = gap[X] if X else min(gap_all.values())
        res.update(gap_target_bytes=target, gap_verified_bytes=cand_gap, gap_ratio=f"{cand_gap/target:.3f}",
                   gap_all_replicas=json.dumps(gap_all), primary_lsn_at_fault=P_kill,
                   replica_recv_lsn=json.dumps(rcv_all), replica_replay_lsn=json.dumps(replay_all),
                   growth_s=f"{time.time()-t_stall:.1f}")
        log(f"VERIFIED gap: primary_lsn={P_kill} recv={rcv_all} gap={gap_all} candidate_gap={cand_gap} ratio={cand_gap/target:.3f}")
        cL.close(); [c.close() for c in creps.values()]
        if not (0.75 * target <= cand_gap <= 1.25 * target):
            res.update(valid="INVALID", invalid_reason=f"gap off target: {cand_gap} vs {target} (ratio {cand_gap/target:.3f})")
            raise RuntimeError("off-target")
        # acked set must equal rows on the primary before the fault
        acked = read_acked(outdir)
        res["acked_total"] = len(acked); res["primary_rows_before_fault"] = rows_primary
        if base == "E":
            log("DCS restore: " + px(EPX_CTL[X], "pass"))
        # --- the fault: primary host dies (postmaster + Patroni agent)
        pm = int(open(f"{LAB}/cluster/{L}/data/postmaster.pid").read().splitlines()[0])
        ap = agent_pid(L)
        t_kill = time.time()
        os.kill(ap, signal.SIGKILL); os.kill(pm, signal.SIGKILL)
        log(f"KILL primary {L}: agent {ap} + postmaster {pm}")
        res["kill_t"] = f"{t_kill:.3f}"
        time.sleep(0.4)
        snap = etcd_snapshot()
        json.dump(snap, open(f"{outdir}/dcs_at_decision.json", "w"), indent=1)
        cand_for_rep = X or min(gap_all, key=gap_all.get)
        optime, xlog, rep_lag = reported_lag(snap, cand_for_rep)
        res.update(patroni_optime=optime, patroni_cand_xlog=xlog, patroni_reported_lag_bytes=rep_lag,
                   patroni_rep_cand=cand_for_rep)
        if rep_lag is not None:
            res["reported_minus_true_bytes"] = rep_lag - gap_all[cand_for_rep]
            res["reported_err_abs_bytes"] = abs(rep_lag - gap_all[cand_for_rep])
        log(f"Patroni view at decision: optime={optime} cand={cand_for_rep} xlog={xlog} reported_lag={rep_lag} true={gap_all[cand_for_rep]}")
        # --- promotion path
        cmd_out = ""; cmd_rc = None
        promoted = None; t_promo = None
        if base == "C" or base == "E":
            t_c = time.time()
            cmd = f"patronictl -c {CTL} failover pilot --candidate {X} --force"
            cmd_rc, cmd_out = sh(cmd, 90)
            res["cmd_s"] = f"{time.time()-t_c:.1f}"
            open(f"{outdir}/patronictl_failover.txt", "w").write(f"$ {cmd}\nrc={cmd_rc}\n{cmd_out}")
            log(f"patronictl rc={cmd_rc} in {res['cmd_s']}s: {cmd_out.strip()[-300:]}")
        elif base == "D":
            time.sleep(1.0)
            t_c = time.time()
            try:
                r = q1(X, "SELECT pg_promote(wait => true, wait_seconds => 60)", 70)
                cmd_out = f"pg_promote -> {r}"; cmd_rc = 0 if r else 1
            except Exception as e:
                cmd_out = f"pg_promote error: {e}"; cmd_rc = 1
            res["cmd_s"] = f"{time.time()-t_c:.1f}"
            open(f"{outdir}/pg_promote.txt", "w").write(cmd_out)
            log(cmd_out)
        wait_limit = 90
        while time.time() - t_kill < wait_limit:
            for n in reps:
                try:
                    if q1(n, "SELECT pg_is_in_recovery()", 2) is False:
                        promoted = n; break
                except Exception:
                    pass
            if promoted: break
            time.sleep(0.25)
        t_promo = time.time()
        res["promotion_s"] = f"{t_promo - t_kill:.1f}" if promoted else ""
        surv = set(); fork = None
        if promoted:
            surv = read_survivors(promoted, table)
            tl = int(q1(promoted, "SELECT timeline_id FROM pg_control_checkpoint()")) if False else None
            hist = sorted(glob.glob(f"{LAB}/cluster/{promoted}/data/pg_wal/*.history"))
            if hist:
                last = open(hist[-1]).read().strip().splitlines()[-1].split("\t")
                fork = lsn_to_int(last[1])
            log(f"PROMOTED {promoted} after {t_promo - t_kill:.1f}s; survivors={len(surv)} fork_lsn={fork}")
            res["fork_lsn"] = fork
            res["loss_bytes_wal"] = (P_kill - fork) if fork else ""
        else:
            log(f"NO PROMOTION within {wait_limit}s")
        miss = acked - surv if promoted else set()
        res.update(promoted_node=promoted or "", candidate_promoted=("yes" if promoted == X else "no") if X and promoted else "",
                   acked_lost_at_promotion=len(miss) if promoted else "", survivors_at_promotion=len(surv) if promoted else "")
        res["sha_acked"] = write_set(f"{outdir}/acked.txt", acked)
        if promoted:
            res["sha_surviving_at_promotion"] = write_set(f"{outdir}/surviving_at_promotion.txt", surv)
            write_set(f"{outdir}/lost_ids.txt", miss)
        # --- classification text
        time.sleep(1)
        logtxt = {n: log_slice(off, n) for n in NODES}
        for n in NODES: open(f"{outdir}/patroni-{n}.log", "w").write(logtxt[n])
        pat = re.compile(r"exceeds maximum replication lag|not possible|no good candidates|refus|lag|behind|WARNING|warn", re.I)
        msgs = []
        for n in reps:
            for ln in logtxt[n].splitlines():
                if re.search(r"exceeds maximum replication lag|no good candidates|is not possible|My wal position exceeds|Timeline .* behind", ln):
                    msgs.append(f"{n}: {ln.strip()[:200]}")
        noise = re.compile(r"Retrying|Connection refused|Failing over to DCS|Could not failover using Patroni api|NewConnectionError|MaxRetryError|Traceback|^\s+File |^\s+raise|^\s+(sock|self|r|conn|retries|return|response)\b|^urllib3|^ConnectionRefused|^The above exception|ERROR - None|^\s*$|^\s+\^+", re.I)
        cmd_warn = [ln for ln in cmd_out.splitlines() if not ln.startswith(("|", "+", "$", "rc=")) and not noise.search(ln)
                    and re.search(r"lag|behind|exceed|up.to.date|data.?loss|stale|diverg|not possible|refus|cannot|can't|unsafe|risk", ln, re.I)]
        tbl = [ln for ln in cmd_out.splitlines() if ln.startswith(f"| {X} ")] if X else []
        if tbl:
            cols = [c.strip() for c in tbl[0].strip("|").split("|")]
            res["cmd_table_lag_mb"] = cols[6] if len(cols) > 6 else ""
        res["patroni_lag_msgs"] = len(msgs); res["cmd_rc"] = cmd_rc if cmd_rc is not None else ""
        res["cmd_msgs"] = " | ".join(cmd_warn)[:300]
        if not promoted:
            res["outcome"] = "no_promotion_" + ("refused" if (msgs or (cmd_rc not in (None, 0))) else "silent_block")
        elif msgs or cmd_warn:
            res["outcome"] = "promoted_with_warning"
        else:
            res["outcome"] = "promoted_silent"
        res["sample_msg"] = (msgs[0] if msgs else "")[:200]
        res["valid"] = "VALID"
        # --- recovery: bring everything back
        if base == "D":
            # Patroni's reaction to the bypass promotion, 15 s later (the externally promoted node is still primary-in-DCS-terms unknown)
            time.sleep(15)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{REST[X]}/patroni", timeout=3) as r:
                    st = json.loads(r.read())
                res["post_bypass_role_15s"] = st.get("role"); res["post_bypass_state_15s"] = st.get("state")
            except Exception as e:
                res["post_bypass_role_15s"] = f"unreadable: {type(e).__name__}"
            snap2 = etcd_snapshot(); json.dump(snap2, open(f"{outdir}/dcs_15s_after_bypass.json", "w"), indent=1)
            res["post_bypass_leader_key"] = snap2.get("/service/pilot/leader", "")
            for n in NODES: open(f"{outdir}/patroni-{n}.log", "w").write(log_slice(off, n))
            log("D: rebuild cluster (bypass leaves a diverged node; fresh cluster is the deterministic reset)")
            res["valid"] = "VALID"
            sh(f"{BIN}/cluster-down.sh", 60)
            if not rebuild(log): res["note_recovery"] = "rebuild failed"
            res["run_s"] = f"{time.time()-T0:.0f}"
            return res
        log("recover: restore proxies, restart old primary agent")
        for n in NODES:
            px(RPX_CTL[n], "pass"); px(EPX_CTL[n], "pass")
        start_agent(L)
        ok = ensure_healthy(log, 200)
        if not ok:
            res["note_recovery"] = "cluster not healthy in 200s; rebuilt"
            ok = rebuild(log)
        fl = leader_name()
        if fl and ok:
            try:
                fs = read_survivors(fl, table)
                res["final_leader"] = fl
                res["acked_lost_final"] = len(acked - fs)
                res["sha_surviving_final"] = write_set(f"{outdir}/surviving_final.txt", fs)
                q1(fl, f"DROP TABLE IF EXISTS {table}")
            except Exception as e:
                res["note_final"] = f"final read failed: {e}"
        res["run_s"] = f"{time.time()-T0:.0f}"
        return res
    except Exception as e:
        log(f"EXCEPTION {type(e).__name__}: {e}")
        if not res.get("valid"):
            res.update(valid="INVALID", invalid_reason=f"rig exception: {type(e).__name__}: {e}")
        # clean up after invalid / failed runs
        for w in writers:
            try: w.kill()
            except Exception: pass
        try:
            for n in NODES:
                px(RPX_CTL[n], "pass"); px(EPX_CTL[n], "pass")
            for n in NODES:
                p = agent_pid(n)
                if not (p and pid_alive(p)): start_agent(n)
        except Exception: pass
        res["run_s"] = f"{time.time()-T0:.0f}"
        return res
    finally:
        evf.close()


COLS = ["run_id", "scenario", "target_mb", "valid", "invalid_reason", "old_primary", "candidate", "promoted_node", "candidate_promoted",
        "gap_target_bytes", "gap_verified_bytes", "gap_ratio", "gap_all_replicas", "primary_lsn_at_fault", "fork_lsn", "loss_bytes_wal",
        "acked_total", "primary_rows_before_fault", "survivors_at_promotion", "acked_lost_at_promotion", "acked_lost_final", "final_leader",
        "patroni_rep_cand", "patroni_optime", "patroni_cand_xlog", "patroni_reported_lag_bytes", "reported_minus_true_bytes", "reported_err_abs_bytes",
        "outcome", "cmd_rc", "cmd_table_lag_mb", "cmd_msgs", "patroni_lag_msgs", "sample_msg", "promotion_s", "cmd_s", "growth_s", "run_s",
        "sha_acked", "sha_surviving_at_promotion", "sha_surviving_final", "replica_recv_lsn", "replica_replay_lsn", "stall_t", "kill_t", "jitter_s",
        "post_bypass_role_15s", "post_bypass_state_15s", "post_bypass_leader_key", "note_rebuilt", "note_recovery", "note_final"]


def append_csv(res, path=f"{LAB}/results/results.csv"):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if new: w.writeheader()
        w.writerow(res)


if __name__ == "__main__":
    scn, mb, no = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    r = run(scn, mb, no)
    append_csv(r)
    print(json.dumps({k: r.get(k) for k in ["run_id", "valid", "invalid_reason", "gap_verified_bytes", "gap_ratio", "outcome", "acked_lost_at_promotion", "patroni_reported_lag_bytes", "promotion_s", "run_s"]}))
