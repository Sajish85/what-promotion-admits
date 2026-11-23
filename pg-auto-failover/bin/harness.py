#!/usr/bin/env python3
"""Failover Gate full study, pg_auto_failover harness (mirrors the pilot's harness.py).
usage: harness.py SCEN TARGET_MB RUNNO     SCEN: B Bb C D E Ea   (b = unthrottled burst with random 0-10 s phase delay before the stall)
Each run builds a fresh rig (monitor + 3 nodes, async), runs one fault, tears the rig down. Evidence in runs/<id>/."""
import os, sys, json, time, subprocess, random, signal, hashlib, re, glob, csv, shutil
import psycopg2

ST = os.path.expanduser("~/invention-hunt/studies/failover-gate")
BIN = f"{ST}/bin"; CL = f"{ST}/cluster"
NODES = ["n1", "n2", "n3"]
PG = {"n1": 6471, "n2": 6472, "n3": 6473}
RPX_CTL = {"n1": 6491, "n2": 6492, "n3": 6493}
MPX_CTL = {"n1": 6511, "n2": 6512, "n3": 6513}
MON = 6470
USER = os.environ.get("USER")
MIB = 1048576
GROWTH_S = 15.0
WAL_PER_TXN = 8850.0
NWRITERS = 4; PAYLOAD = 8000
ENV = dict(os.environ)
ENV["PATH"] = f"{ST}/bin:{os.path.expanduser('~/tools/venv/bin')}:{os.path.expanduser('~/tools/pg/17/bin')}:/usr/bin:/bin:/usr/sbin:/sbin"
ENV["XDG_CONFIG_HOME"] = f"{CL}/xdg/config"; ENV["XDG_DATA_HOME"] = f"{CL}/xdg/data"
ENV["PYTHONWARNINGS"] = "ignore"


def sh(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        o = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, o + "TIMEOUT"


def px(ctl, cmd): return sh(f"{BIN}/pxctl.sh {ctl} {cmd}", 5)[1].strip()


def conn(port, db="postgres", timeout=3):
    c = psycopg2.connect(host="127.0.0.1", port=port, dbname=db, user=USER, connect_timeout=timeout); c.autocommit = True; return c


def q1(node, sql, timeout=3):
    c = conn(PG[node], timeout=timeout)
    try:
        cur = c.cursor(); cur.execute(sql)
        if cur.description is None: return None
        r = cur.fetchone(); return r[0] if r else None
    finally: c.close()


def mon_rows():
    c = conn(MON, "pg_auto_failover", 3)
    try:
        cur = c.cursor()
        cur.execute("select nodename, reportedstate::text, goalstate::text, reportedlsn::text, health, reporttime::text, candidatepriority, replicationquorum, reportedpgisrunning from pgautofailover.node order by nodeid")
        return [dict(zip(["nodename", "reported", "goal", "reportedlsn", "health", "reporttime", "prio", "quorum", "pgisrunning"], r)) for r in cur.fetchall()]
    finally: c.close()


def lsn_to_int(s): a, b = s.split("/"); return (int(a, 16) << 32) + int(b, 16)


def leader():
    try:
        for r in mon_rows():
            if r["reported"] == r["goal"] and r["reported"] in ("primary", "single", "wait_primary"): return r["nodename"]
    except Exception: return None


def healthy():
    try:
        rows = mon_rows()
        L = leader()
        if not L: return False
        for r in rows:
            if r["nodename"] != L and not (r["reported"] == "secondary" and r["goal"] == "secondary"): return False
        c = conn(PG[L]); cur = c.cursor()
        cur.execute("select count(*) from pg_stat_replication where state='streaming'"); n = cur.fetchone()[0]; c.close()
        return n == 2
    except Exception: return False


def ps_tree(root):
    out = sh("ps -A -o pid=,ppid=", 10)[1]; ch = {}
    for ln in out.splitlines():
        a = ln.split()
        if len(a) == 2: ch.setdefault(int(a[1]), []).append(int(a[0]))
    res = [root]; i = 0
    while i < len(res):
        res += ch.get(res[i], []); i += 1
    return res


def rebuild(log):
    log("REBUILD rig")
    sh(f"{BIN}/cluster-down.sh", 120)
    rc, out = sh(f"{BIN}/cluster-up.sh", 400)
    ok = False
    for _ in range(40):
        if healthy(): ok = True; break
        time.sleep(3)
    log(f"rebuild ok={ok}")
    return ok


def read_survivors(node, table):
    c = conn(PG[node], timeout=5)
    try:
        cur = c.cursor(); cur.execute(f"SELECT writer, seq FROM {table} ORDER BY 1,2")
        return {(w, s) for w, s in cur.fetchall()}
    finally: c.close()


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


def run(scn, target_mb, runno):
    rid = f"{scn}-{target_mb}MB-r{runno:02d}"
    outdir = f"{ST}/runs/{rid}"
    shutil.rmtree(outdir, ignore_errors=True); os.makedirs(outdir)
    evf = open(f"{outdir}/events.log", "w", buffering=1); T0 = time.time()
    def log(m): evf.write(f"{time.time() - T0:8.2f}s {m}\n")
    base = scn[0]; burst = "b" in scn[1:]
    res = dict(run_id=rid, scenario=scn, target_mb=target_mb, valid="", invalid_reason="")
    writers = []
    try:
        if not rebuild(log):
            res.update(valid="INVALID", invalid_reason="rig: cluster did not become healthy after build"); return res
        L = leader(); reps = [n for n in NODES if n != L]
        X = random.choice(reps) if base in "CDE" else None
        res.update(old_primary=L, candidate=X or "", replicas=",".join(reps))
        log(f"leader={L} replicas={reps} candidate={X}")
        moff = os.path.getsize(f"{CL}/logs/monitor.log")
        offs = {n: os.path.getsize(f"{CL}/logs/{n}.log") for n in NODES}
        table = f"hb_{rid.replace('-', '_').lower()}"
        c = conn(PG[L], timeout=5); cur = c.cursor()
        cur.execute(f"CREATE TABLE {table}(writer int, seq int, payload bytea)")
        cur.execute(f"ALTER TABLE {table} ALTER payload SET STORAGE EXTERNAL"); c.close()
        target = target_mb * MIB
        tps_total = target / (GROWTH_S * WAL_PER_TXN)
        tps_w = 0 if burst else tps_total / NWRITERS
        env = dict(ENV, PG_PORTS="6471,6472,6473")
        for w in range(1, NWRITERS + 1):
            writers.append(subprocess.Popen([f"{os.path.expanduser('~/tools/venv/bin/python')}", f"{BIN}/writer.py", str(w), table,
                                             f"{outdir}/acked_w{w}.csv", str(PAYLOAD), f"{tps_w:.3f}"], env=env))
        time.sleep(3)
        cL = conn(PG[L]); curL = cL.cursor()
        cands = [X] if X else reps
        creps = {n: conn(PG[n]) for n in cands}
        def lsn_primary(): curL.execute("SELECT pg_current_wal_lsn()"); return lsn_to_int(curL.fetchone()[0])
        def lsn_recv(n):
            cr = creps[n].cursor(); cr.execute("SELECT pg_last_wal_receive_lsn()"); return lsn_to_int(cr.fetchone()[0])
        log(f"pre-stall gap bytes={ {n: lsn_primary()-lsn_recv(n) for n in cands} } tps_total={tps_total:.1f}")
        if burst:
            jt = random.uniform(0, 10.0); res["jitter_s"] = f"{jt:.2f}"; log(f"phase jitter {jt:.2f}s"); time.sleep(jt)
        if base == "E": log("monitor-path cut (candidate keeper->monitor): " + px(MPX_CTL[X], "stall"))
        log("replication stall on primary proxy: " + px(RPX_CTL[L], "stall"))
        t_stall = time.time(); res["stall_t"] = f"{t_stall:.3f}"
        while True:
            P = lsn_primary(); gap = {n: P - lsn_recv(n) for n in cands}
            if min(gap.values()) >= target: break
            if time.time() - t_stall > 4 * GROWTH_S:
                res.update(valid="INVALID", invalid_reason=f"gap did not reach target in {4*GROWTH_S:.0f}s (gap={min(gap.values())})"); raise RuntimeError("slow")
            time.sleep(0.02)
        for w in writers: w.send_signal(signal.SIGTERM)
        for w in writers: w.wait(timeout=10)
        writers = []
        time.sleep(0.2)
        P_kill = lsn_primary()
        rcv_all = {n: lsn_to_int(q1(n, "SELECT pg_last_wal_receive_lsn()")) for n in reps}
        gap_all = {n: P_kill - rcv_all[n] for n in reps}
        replay_all = {n: lsn_to_int(q1(n, "SELECT pg_last_wal_replay_lsn()")) for n in reps}
        rows_primary = q1(L, f"SELECT count(*) FROM {table}")
        cand_gap = gap_all[X] if X else min(gap_all.values())
        res.update(gap_target_bytes=target, gap_verified_bytes=cand_gap, gap_ratio=f"{cand_gap/target:.3f}", gap_all_replicas=json.dumps(gap_all),
                   primary_lsn_at_fault=P_kill, replica_recv_lsn=json.dumps(rcv_all), replica_replay_lsn=json.dumps(replay_all), growth_s=f"{time.time()-t_stall:.1f}")
        log(f"VERIFIED gap: primary_lsn={P_kill} recv={rcv_all} gap={gap_all} candidate_gap={cand_gap} ratio={cand_gap/target:.3f}")
        cL.close(); [c.close() for c in creps.values()]
        if not (0.75 * target <= cand_gap <= 1.25 * target):
            res.update(valid="INVALID", invalid_reason=f"gap off target: {cand_gap} vs {target} (ratio {cand_gap/target:.3f})"); raise RuntimeError("off-target")
        acked = read_acked(outdir)
        res["acked_total"] = len(acked); res["primary_rows_before_fault"] = rows_primary
        if base == "E": log("monitor-path restore: " + px(MPX_CTL[X], "pass"))
        # --- fault: primary host dies (supervising pg_autoctl tree + postmaster)
        pm = int(open(f"{CL}/{L}/postmaster.pid").read().splitlines()[0])
        ap = int(open(f"{CL}/{L}.agentpid").read())
        tree = ps_tree(ap)
        t_kill = time.time()
        for p in tree + [pm]:
            try: os.kill(p, signal.SIGKILL)
            except Exception: pass
        log(f"KILL primary {L}: pg_autoctl tree {tree} + postmaster {pm}"); res["kill_t"] = f"{t_kill:.3f}"
        time.sleep(0.4)
        rows = mon_rows(); json.dump(rows, open(f"{outdir}/monitor_at_decision.json", "w"), indent=1)
        byname = {r["nodename"]: r for r in rows}
        cand_for_rep = X or min(gap_all, key=gap_all.get)
        pl = byname[L]["reportedlsn"]; cl_ = byname[cand_for_rep]["reportedlsn"]
        rep_lag = lsn_to_int(pl) - lsn_to_int(cl_)
        res.update(mon_primary_lsn=pl, mon_cand_lsn=cl_, mon_reported_lag_bytes=rep_lag, mon_rep_cand=cand_for_rep,
                   reported_minus_true_bytes=rep_lag - gap_all[cand_for_rep], reported_err_abs_bytes=abs(rep_lag - gap_all[cand_for_rep]))
        log(f"monitor view: primary_reported={pl} cand_reported={cl_} reported_lag={rep_lag} true={gap_all[cand_for_rep]}")
        cmd_out = ""; cmd_rc = None; promoted = None
        if base in ("C", "E"):
            t_c = time.time()
            cmd = f"pg_autoctl perform promotion --pgdata {CL}/{X} --name {X}"
            cmd_rc, cmd_out = sh(cmd, 150)
            res["cmd_s"] = f"{time.time()-t_c:.1f}"
            open(f"{outdir}/perform_promotion.txt", "w").write(f"$ {cmd}\nrc={cmd_rc}\n{cmd_out}")
            log(f"perform promotion rc={cmd_rc} in {res['cmd_s']}s: {cmd_out.strip()[-300:]}")
        elif base == "D":
            time.sleep(1.0); t_c = time.time()
            try:
                r = q1(X, "SELECT pg_promote(wait => true, wait_seconds => 60)", 70); cmd_out = f"pg_promote -> {r}"; cmd_rc = 0 if r else 1
            except Exception as e: cmd_out = f"pg_promote error: {e}"; cmd_rc = 1
            res["cmd_s"] = f"{time.time()-t_c:.1f}"; open(f"{outdir}/pg_promote.txt", "w").write(cmd_out); log(cmd_out)
        wait_limit = 150
        while time.time() - t_kill < wait_limit:
            for n in reps:
                try:
                    if q1(n, "SELECT pg_is_in_recovery()", 2) is False: promoted = n; break
                except Exception: pass
            if promoted: break
            time.sleep(0.25)
        res["promotion_s"] = f"{time.time() - t_kill:.1f}" if promoted else ""
        surv = set(); fork = None
        if promoted:
            surv = read_survivors(promoted, table)
            hist = sorted(glob.glob(f"{CL}/{promoted}/pg_wal/*.history"))
            if hist:
                fork = lsn_to_int(open(hist[-1]).read().strip().splitlines()[-1].split("\t")[1])
            log(f"PROMOTED {promoted} after {time.time()-t_kill:.1f}s; survivors={len(surv)} fork_lsn={fork}")
            res["fork_lsn"] = fork; res["loss_bytes_wal"] = (P_kill - fork) if fork else ""
        else: log(f"NO PROMOTION within {wait_limit}s")
        miss = acked - surv if promoted else set()
        res.update(promoted_node=promoted or "", candidate_promoted=("yes" if promoted == X else "no") if X and promoted else "",
                   acked_lost_at_promotion=len(miss) if promoted else "", survivors_at_promotion=len(surv) if promoted else "")
        res["sha_acked"] = write_set(f"{outdir}/acked.txt", acked)
        if promoted:
            res["sha_surviving_at_promotion"] = write_set(f"{outdir}/surviving_at_promotion.txt", surv); write_set(f"{outdir}/lost_ids.txt", miss)
        # --- classification
        time.sleep(1)
        mlog = open(f"{CL}/logs/monitor.log", "rb").read()[moff:].decode(errors="replace")
        open(f"{outdir}/monitor.log", "w").write(mlog)
        for n in NODES: open(f"{outdir}/keeper-{n}.log", "w").write(open(f"{CL}/logs/{n}.log", "rb").read()[offs[n]:].decode(errors="replace"))
        refl = [ln.strip()[:260] for ln in mlog.splitlines() if re.search(r"more than .*behind|pgautofailover\.enable_sync_wal_log_threshold|refus|cannot perform|not selecting|Not selecting", ln, re.I)]
        cmd_warn = [ln for ln in cmd_out.splitlines() if re.search(r"lag|behind|threshold|data.?loss|refus|cannot|unsafe|risk|WARN", ln, re.I) and "WARN  No encryption" not in ln]
        res["mon_refusal_msgs"] = len(refl); res["sample_msg"] = (refl[0] if refl else "")[:260]
        res["cmd_rc"] = cmd_rc if cmd_rc is not None else ""; res["cmd_msgs"] = " | ".join(cmd_warn)[:300]
        if not promoted: res["outcome"] = "no_promotion_" + ("refused" if refl or (cmd_rc not in (None, 0)) else "silent_block")
        elif refl or cmd_warn: res["outcome"] = "promoted_with_warning"
        else: res["outcome"] = "promoted_silent"
        res["valid"] = "VALID"
        if base == "D":
            time.sleep(15)
            try:
                res["post_bypass_in_recovery_15s"] = q1(X, "SELECT pg_is_in_recovery()", 3)
            except Exception as e: res["post_bypass_in_recovery_15s"] = f"unreadable: {type(e).__name__}"
            try: res["post_bypass_mon_15s"] = json.dumps({r["nodename"]: f'{r["reported"]}/{r["goal"]}' for r in mon_rows()})
            except Exception as e: res["post_bypass_mon_15s"] = "unreadable"
            time.sleep(45)
            try: res["post_bypass_in_recovery_60s"] = q1(X, "SELECT pg_is_in_recovery()", 3)
            except Exception as e: res["post_bypass_in_recovery_60s"] = f"unreadable: {type(e).__name__}"
            try: res["post_bypass_mon_60s"] = json.dumps({r["nodename"]: f'{r["reported"]}/{r["goal"]}' for r in mon_rows()})
            except Exception: res["post_bypass_mon_60s"] = "unreadable"
            open(f"{outdir}/keeper-{X}-after.log", "w").write(open(f"{CL}/logs/{X}.log", "rb").read()[offs[X]:].decode(errors="replace"))
        res["run_s"] = f"{time.time()-T0:.0f}"
        return res
    except Exception as e:
        log(f"EXCEPTION {type(e).__name__}: {e}")
        if not res.get("valid"): res.update(valid="INVALID", invalid_reason=f"rig exception: {type(e).__name__}: {e}")
        for w in writers:
            try: w.kill()
            except Exception: pass
        res["run_s"] = f"{time.time()-T0:.0f}"
        return res
    finally:
        evf.close()
        sh(f"{BIN}/cluster-down.sh", 120)


COLS = ["run_id", "scenario", "target_mb", "valid", "invalid_reason", "old_primary", "candidate", "promoted_node", "candidate_promoted",
        "gap_target_bytes", "gap_verified_bytes", "gap_ratio", "gap_all_replicas", "primary_lsn_at_fault", "fork_lsn", "loss_bytes_wal",
        "acked_total", "primary_rows_before_fault", "survivors_at_promotion", "acked_lost_at_promotion",
        "mon_rep_cand", "mon_primary_lsn", "mon_cand_lsn", "mon_reported_lag_bytes", "reported_minus_true_bytes", "reported_err_abs_bytes",
        "outcome", "cmd_rc", "cmd_msgs", "mon_refusal_msgs", "sample_msg", "promotion_s", "cmd_s", "growth_s", "run_s",
        "sha_acked", "sha_surviving_at_promotion", "replica_recv_lsn", "replica_replay_lsn", "stall_t", "kill_t", "jitter_s",
        "post_bypass_in_recovery_15s", "post_bypass_mon_15s", "post_bypass_in_recovery_60s", "post_bypass_mon_60s"]


def append_csv(res, path=f"{ST}/results/results.csv"):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if new: w.writeheader()
        w.writerow(res)


if __name__ == "__main__":
    scn, mb, no = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    r = run(scn, mb, no); append_csv(r)
    print(json.dumps({k: r.get(k) for k in ["run_id", "valid", "invalid_reason", "gap_ratio", "outcome", "acked_lost_at_promotion", "mon_reported_lag_bytes", "promotion_s", "run_s", "sample_msg"]}))
