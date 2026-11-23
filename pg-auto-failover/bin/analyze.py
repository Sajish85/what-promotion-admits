#!/usr/bin/env python3
"""analyze.py: generate results/summary.md from results/results.csv; recount acked - surviving from stored files (python3 -I)."""
import csv, os, hashlib, statistics as S, collections, json
ST = os.path.expanduser("~/invention-hunt/studies/failover-gate"); MIB = 1048576
rs = list(csv.DictReader(open(f"{ST}/results/results.csv")))
cells = collections.OrderedDict()
for r in rs: cells.setdefault((r["scenario"], int(r["target_mb"])), []).append(r)
def f(x): return float(x) if x not in ("", None) else None
def rng(v, d=2):
    v = [x for x in v if x is not None]
    return "n/a" if not v else f"{min(v):.{d}f} - {S.median(v):.{d}f} - {max(v):.{d}f}"
out = []
out.append("### Per-cell results (valid runs; invalid listed below)\n")
out.append("| Cell | valid | promoted | refused | promoted+warning | promoted silent | verified gap MiB (min-med-max) | acked lost txns (min-med-max) | WAL lost MiB (min-med-max) | monitor-reported lag MiB (med) | |reported-true| MiB (min-med-max) | time to promotion s (med) |")
out.append("|" + "---|" * 12)
for (s, mb), lst in sorted(cells.items(), key=lambda k: (k[0][1], k[0][0])):
    v = [r for r in lst if r["valid"] == "VALID"]
    pr = [r for r in v if r["promoted_node"]]
    ref = [r for r in v if not r["promoted_node"]]
    wn = [r for r in pr if r["outcome"] == "promoted_with_warning"]; si = [r for r in pr if r["outcome"] == "promoted_silent"]
    out.append(f"| {s} {mb} MB | {len(v)} | {len(pr)} | {len(ref)} | {len(wn)} | {len(si)} | {rng([f(r['gap_verified_bytes'])/MIB for r in v])} | "
               f"{rng([f(r['acked_lost_at_promotion']) for r in pr], 0)} | {rng([f(r['loss_bytes_wal'])/MIB if r['loss_bytes_wal'] else None for r in pr])} | "
               f"{S.median([f(r['mon_reported_lag_bytes'])/MIB for r in v]):.2f} | {rng([f(r['reported_err_abs_bytes'])/MIB for r in v])} | {rng([f(r['promotion_s']) for r in pr], 1)} |")
out.append("\n### Denominators (valid runs)\n")
out.append("| Cell | valid | acked writes (sum) | acked lost at promotion (sum) | runs with loss |"); out.append("|---|---|---|---|---|")
for (s, mb), lst in sorted(cells.items(), key=lambda k: (k[0][1], k[0][0])):
    v = [r for r in lst if r["valid"] == "VALID"]; pr = [r for r in v if r["promoted_node"]]
    out.append(f"| {s} {mb} MB | {len(v)} | {sum(int(r['acked_total']) for r in v):,} | {sum(int(r['acked_lost_at_promotion']) for r in pr):,} | {sum(int(r['acked_lost_at_promotion'])>0 for r in pr)}/{len(v)} |")
out.append("\n### Monitor-side view at decision time (MiB): monitor's reported primary LSN minus candidate's reported LSN vs true gap; threshold promote_wal_log_threshold = 16 MiB\n")
out.append("| Cell | true gap (med) | reported lag (min / med / max) | reported <= 16 MiB (would pass the monitor gate) |"); out.append("|---|---|---|---|")
for (s, mb), lst in sorted(cells.items(), key=lambda k: (k[0][1], k[0][0])):
    v = [r for r in lst if r["valid"] == "VALID"]
    g = [f(r["gap_verified_bytes"]) / MIB for r in v]; rl = [f(r["mon_reported_lag_bytes"]) / MIB for r in v]
    out.append(f"| {s} {mb} MB | {S.median(g):.1f} | {min(rl):.1f} / {S.median(rl):.1f} / {max(rl):.1f} | {sum(x <= 16 for x in rl)}/{len(v)} |")
out.append("\n### D: what the stack did after pg_promote() (15 s and 60 s later)\n")
for (s, mb), lst in sorted(cells.items(), key=lambda k: (k[0][1], k[0][0])):
    if s != "D": continue
    v = [r for r in lst if r["valid"] == "VALID"]
    c = collections.Counter((r["post_bypass_in_recovery_15s"], r["post_bypass_in_recovery_60s"]) for r in v)
    out.append(f"- D {mb} MB: (in_recovery at 15 s, at 60 s) counts: {dict(c)}")
    out.append(f"  - monitor states 60 s: {collections.Counter(r['post_bypass_mon_60s'] for r in v).most_common(3)}")
out.append("\n### Invalid runs\n")
inv = [r for r in rs if r["valid"] != "VALID"]
out.append(f"{len(inv)} invalid of {len(rs)} attempts.")
for r in inv: out.append(f"- {r['run_id']}: {r['invalid_reason']}")
out.append("\n### Run-level recount check (acked - surviving, from stored files)\n")
bad = 0; n = 0
for r in rs:
    if r["valid"] != "VALID" or not r["promoted_node"]: continue
    d = f"{ST}/runs/{r['run_id']}"; n += 1
    A = set(open(f"{d}/acked.txt").read().split()); Sv = set(open(f"{d}/surviving_at_promotion.txt").read().split())
    ok = (len(A - Sv) == int(r["acked_lost_at_promotion"]) and hashlib.sha256(open(f"{d}/acked.txt", "rb").read()).hexdigest() == r["sha_acked"]
          and hashlib.sha256(open(f"{d}/surviving_at_promotion.txt", "rb").read()).hexdigest() == r["sha_surviving_at_promotion"]
          and len(A) == int(r["acked_total"]))
    if not ok: bad += 1; out.append(f"- MISMATCH {r['run_id']}")
out.append(f"Recomputed loss and hashes for {n} promoted valid runs from files: " + ("all match." if bad == 0 else f"{bad} MISMATCH."))
# acked set vs primary rows
mm = [r["run_id"] for r in rs if r["valid"] == "VALID" and r["acked_total"] != r["primary_rows_before_fault"]]
out.append(f"acked_total vs primary_rows_before_fault: {'all equal' if not mm else 'DIFFER in ' + ', '.join(mm)} (valid runs).")
fk = [r for r in rs if r["valid"] == "VALID" and r["promoted_node"] and r["fork_lsn"]]
eq = [r for r in fk if int(r["fork_lsn"]) == int(json.loads(r["replica_recv_lsn"])[r["promoted_node"]])]
out.append(f"fork LSN == verified receive LSN of promoted node: {len(eq)}/{len(fk)} promoted valid runs.")
dif = [(r["run_id"], int(r["fork_lsn"]) - int(json.loads(r["replica_recv_lsn"])[r["promoted_node"]])) for r in fk if r not in eq]
out.append("differences (fork - recv bytes): " + (", ".join(f"{a}: {b}" for a, b in dif) if dif else "none"))
open(f"{ST}/results/summary.md", "w").write("\n".join(out) + "\n"); print("\n".join(out))
