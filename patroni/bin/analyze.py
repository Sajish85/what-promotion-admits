#!/usr/bin/env python3
"""Tables and bar arithmetic from results/results.csv (all numbers recomputed here; per-run loss also recomputable
from runs/<id>/acked.txt and surviving_at_promotion.txt). Run: python3 -I bin/analyze.py"""
import csv, os, statistics as st, json, hashlib
LAB = os.path.expanduser("~/invention-hunt/pilots/failover-gate")
MIB = 1048576
rows = list(csv.DictReader(open(f"{LAB}/results/results.csv")))
def f(x):
    try: return float(x)
    except Exception: return None
def ev_lag(r):
    """Patroni's automatic-path view: DCS leader optime minus the candidate's LIVE received LSN (what ha.py is_lagging compares)."""
    rc = json.loads(r["replica_recv_lsn"])[r["patroni_rep_cand"]]
    return (int(r["patroni_optime"]) - rc) / MIB
def med(v): return f"{st.median(v):,.0f}" if v else "n/a"
out = []
def P(s=""): out.append(s)
cells = [(s, m) for s in ("B", "C", "D", "E", "Ej", "Bjb") for m in (10, 100)]
P("## Per-cell results (valid runs only; invalid listed separately)\n")
P("| Cell | valid | promoted | refused/blocked | promoted + warning | promoted silent | verified gap MiB (min-med-max) | acked lost txns at promotion (min-med-max) | WAL bytes lost MiB (min-med-max) | Patroni reported lag MiB (med) | reported vs true error MiB (med abs) | time to promotion s (med) |")
P("|---|---|---|---|---|---|---|---|---|---|---|---|")
summ = {}
for s, m in cells:
    rs = [r for r in rows if r["scenario"] == s and int(r["target_mb"]) == m]
    v = [r for r in rs if r["valid"] == "VALID"]
    if not rs: continue
    if s in ("Ej", "Bjb") and not v: continue
    pro = [r for r in v if r["promoted_node"]]
    ref = [r for r in v if not r["promoted_node"]]
    war = [r for r in pro if r["outcome"] == "promoted_with_warning"]
    sil = [r for r in pro if r["outcome"] == "promoted_silent"]
    gaps = [f(r["gap_verified_bytes"]) / MIB for r in v if f(r["gap_verified_bytes"])]
    lost = [f(r["acked_lost_at_promotion"]) for r in pro if f(r["acked_lost_at_promotion"]) is not None]
    lb = [f(r["loss_bytes_wal"]) / MIB for r in pro if f(r["loss_bytes_wal"]) is not None]
    rep = [f(r["patroni_reported_lag_bytes"]) / MIB for r in v if f(r["patroni_reported_lag_bytes"]) is not None]
    err = [abs(f(r["reported_minus_true_bytes"])) / MIB for r in v if f(r["reported_minus_true_bytes"]) is not None]
    ps = [f(r["promotion_s"]) for r in pro if f(r["promotion_s"]) is not None]
    def mm(x, d=1): return f"{min(x):.{d}f} - {st.median(x):.{d}f} - {max(x):.{d}f}" if x else "n/a"
    P(f"| {s} {m} MB | {len(v)} | {len(pro)} | {len(ref)} | {len(war)} | {len(sil)} | {mm(gaps,2)} | {mm(lost,0)} | {mm(lb,2)} | {st.median(rep):.1f} | {st.median(err):.1f} | {st.median(ps) if ps else 'n/a'} |" if rep else f"| {s} {m} MB | {len(v)} | {len(pro)} | {len(ref)} | {len(war)} | {len(sil)} | {mm(gaps,2)} | {mm(lost,0)} | {mm(lb,2)} | n/a | n/a | n/a |")
    summ[(s, m)] = dict(v=v, pro=pro, ref=ref, war=war, sil=sil, rs=rs)

P("\n## Denominators (valid runs; acked = COMMIT acknowledged to a writer, lost = acked and absent from the promoted node at promotion)\n")
P("| Cell | valid runs | acked writes (sum) | acked lost at promotion (sum) | runs with loss | acked lost at end of run, final leader (sum) |")
P("|---|---|---|---|---|---|")
for s, m in cells:
    c = summ.get((s, m))
    if not c or not c["pro"]: continue
    P(f"| {s} {m} MB | {len(c['v'])} | {sum(int(r['acked_total']) for r in c['pro']):,} | {sum(int(r['acked_lost_at_promotion']) for r in c['pro']):,} | {sum(1 for r in c['pro'] if int(r['acked_lost_at_promotion'])>0)}/{len(c['pro'])} | {('n/a (cluster rebuilt)' if s == 'D' else format(sum(int(r['acked_lost_final'] or 0) for r in c['pro']), ','))} |")

P("\n## Patroni's two views of the candidate's lag at decision time (MiB)\n")
P("DCS view = leader optime in DCS minus the member's published xlog_location (what `patronictl list` shows). Election view = leader optime in DCS minus the candidate's live received LSN (what `ha.py is_lagging` compares in the automatic path). True = primary LSN at fault minus candidate received LSN. Limit = `maximum_lag_on_failover` = 1 MiB. Candidate for B/Bjb = the replica with the smaller true gap.\n")
P("| Cell | true gap (med) | DCS view (min / med / max) | election view (min / med / max) | election view <= 1 MiB (would pass the limit) |")
P("|---|---|---|---|---|")
for s_, m in cells:
    c = summ.get((s_, m))
    if not c: continue
    dv = [f(r["patroni_reported_lag_bytes"]) / MIB for r in c["v"] if f(r["patroni_reported_lag_bytes"]) is not None]
    evs = [ev_lag(r) for r in c["v"]]
    tg = [f(r["gap_verified_bytes"]) / MIB for r in c["v"]]
    P(f"| {s_} {m} MB | {st.median(tg):.1f} | {min(dv):.1f} / {st.median(dv):.1f} / {max(dv):.1f} | {min(evs):.1f} / {st.median(evs):.1f} / {max(evs):.1f} | {sum(1 for x in evs if x <= 1.0)}/{len(evs)} |")
P("\n## Bar arithmetic\n")
for m in (10, 100):
    P(f"### Target {m} MB")
    for s in "CE":
        c = summ.get((s, m))
        if not c: continue
        v = c["v"]; n = len(v)
        ok = [r for r in c["sil"] if f(r["loss_bytes_wal"]) is not None and f(r["loss_bytes_wal"]) >= 10 * MIB]
        P(f"- {s}: promoted, no refusal/warning, true loss >= 10 MiB: **{len(ok)}/{n}** (bar needs >= 8/10)")
    e = summ.get(("E", m))
    if e:
        n = len(e["v"]); big = [r for r in e["v"] if f(r["reported_err_abs_bytes"]) is not None and f(r["reported_err_abs_bytes"]) >= 10 * MIB]
        small = [r for r in e["v"] if f(r["reported_err_abs_bytes"]) is not None and f(r["reported_err_abs_bytes"]) <= MIB]
        P(f"- E: |reported - true| lag >= 10 MiB: **{len(big)}/{n}** (CONTINUE alt. needs >= 5/10); within 1 MiB of truth: **{len(small)}/{n}** (KILL needs >= 8/10)")
    c = summ.get(("C", m))
    if c:
        n = len(c["v"]); rw = [r for r in c["v"] if (not r["promoted_node"]) or r["outcome"] == "promoted_with_warning"]
        P(f"- C: refused or warned: **{len(rw)}/{n}** (KILL needs >= 8/10 at >= 10 MB)")

P("\n## Reported vs true lag, per run (abs error, MiB, sorted)\n")
for s, m in cells:
    c = summ.get((s, m))
    if not c: continue
    e = sorted(abs(f(r["reported_minus_true_bytes"])) / MIB for r in c["v"] if f(r["reported_minus_true_bytes"]) is not None)
    P(f"- {s} {m} MB: " + ", ".join(f"{x:.1f}" for x in e))
P("\n## Supplementary cells (not part of the bar)\n")
for s in ("Ej", "Bjb"):
    for m in (10, 100):
        c = summ.get((s, m))
        if not c: continue
        n = len(c["v"]); big = [r for r in c["v"] if f(r["reported_err_abs_bytes"]) is not None and f(r["reported_err_abs_bytes"]) >= 10 * MIB]
        small = [r for r in c["v"] if f(r["reported_err_abs_bytes"]) is not None and f(r["reported_err_abs_bytes"]) <= MIB]
        P(f"- {s} {m} MB: valid {n}; promoted {len(c['pro'])}; refused {len(c['ref'])}; |reported-true| >= 10 MiB in {len(big)}/{n}; within 1 MiB in {len(small)}/{n}")
P("\n## E: was the DCS cut effective? (candidate agent log lines 'Request to server ... failed' / 'Error communicating' per run)\n")
for s in ("E", "Ej"):
    for m in (10, 100):
        c = summ.get((s, m))
        if not c: continue
        cnt = []
        for r in c["v"]:
            lg = open(f"{LAB}/runs/{r['run_id']}/patroni-{r['candidate']}.log", errors="replace").read()
            cnt.append(sum(1 for ln in lg.splitlines() if "Request to server" in ln or "Error communicating" in ln))
        P(f"- {s} {m} MB: runs with >= 1 DCS error on the candidate's agent: {sum(1 for x in cnt if x>=1)}/{len(cnt)} (counts {cnt})")
P("\n## Invalid runs\n")
bad = [r for r in rows if r["valid"] != "VALID"]
P(f"{len(bad)} invalid of {len(rows)} attempts." if bad else "None invalid.")
import collections
for k, n in collections.Counter((r["scenario"], r["invalid_reason"]) for r in bad).items(): P(f"- {n} runs, scenario {k[0]}: {k[1]}")
P("\n## Run-level recount check (acked - surviving, from stored files)\n")
chk = 0; badc = []
for r in rows:
    if r["valid"] != "VALID" or not r["promoted_node"]: continue
    d = f"{LAB}/runs/{r['run_id']}"
    a = set(open(f"{d}/acked.txt").read().split()); s_ = set(open(f"{d}/surviving_at_promotion.txt").read().split())
    chk += 1
    if len(a - s_) != int(r["acked_lost_at_promotion"]) or hashlib.sha256(open(f"{d}/acked.txt","rb").read()).hexdigest() != r["sha_acked"]: badc.append(r["run_id"])
P(f"Recomputed loss and hashes for {chk} promoted runs from files: {'all match' if not badc else 'MISMATCH ' + ', '.join(badc)}.")
open(f"{LAB}/results/summary.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
