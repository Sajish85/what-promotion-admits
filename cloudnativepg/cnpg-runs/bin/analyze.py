#!/usr/bin/env python3
"""Mac-side analysis: python3 -I analyze.py <failover-gate dir>. Recomputes loss from stored files."""
import sys, csv, os, statistics as st, hashlib, collections
D = sys.argv[1]
rows = list(csv.DictReader(open(f'{D}/cnpg-results.csv')))
RUNS = f'{D}/cnpg-runs/runs'
MiB = 1048576
def f(x):
    try: return float(x)
    except: return None
def mmm(v, fmt='{:.2f}'):
    v = [x for x in v if x is not None]
    return 'n/a' if not v else f"{fmt.format(min(v))} - {fmt.format(st.median(v))} - {fmt.format(max(v))}"
def cellname(r): return f"{r['scenario']} {r['target_mib']} MiB"
cells = collections.OrderedDict()
for r in rows: cells.setdefault(cellname(r), []).append(r)
out = []
P = out.append
P('### Per-cell results (valid runs only)\n')
P('| Cell | valid | promoted | refused / none | warned | silent | demoted after | verified gap MiB (min-med-max) | acked lost txns at promotion (min-med-max) | operator-view gap MiB (med) | operator-view error MiB (med abs) | time to promotion s (med) |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|')
for c, rs in cells.items():
    v = [r for r in rs if r['valid'] == '1']
    pr = [r for r in v if r['promoted'] == '1']
    warned = [r for r in pr if r['outcome'] == 'promoted_warned']; silent = [r for r in pr if r['outcome'] == 'promoted_silent']
    dem = [r for r in pr if r['post_state'] == 'demoted_after']
    gaps = [f(r['gap_cand_bytes']) / MiB for r in v if f(r['gap_cand_bytes']) is not None]
    lost = [f(r['lost_at_promotion']) for r in pr]
    ov = [f(r['opview_gap_cand_bytes']) / MiB for r in v if f(r['opview_gap_cand_bytes']) is not None]
    err = [abs(f(r['opview_gap_cand_bytes']) - f(r['gap_cand_bytes'])) / MiB for r in v if f(r['opview_gap_cand_bytes']) is not None]
    tp = [f(r['t_promoted_s']) for r in pr if f(r['t_promoted_s']) is not None]
    P(f"| {c} | {len(v)} | {len(pr)} | {len(v)-len(pr)} | {len(warned)} | {len(silent)} | {len(dem)} | {mmm(gaps)} | {mmm(lost, '{:.0f}')} | {st.median(ov):.2f} | {st.median(err) if err else float('nan'):.2f} | {st.median(tp) if tp else float('nan'):.1f} |" if ov else
      f"| {c} | {len(v)} | {len(pr)} | {len(v)-len(pr)} | {len(warned)} | {len(silent)} | {len(dem)} | {mmm(gaps)} | {mmm(lost, '{:.0f}')} | n/a | n/a | {st.median(tp) if tp else float('nan'):.1f} |")
P('\n### Denominators (valid runs; acked = COMMIT returned to a writer; lost = acked and absent from the promoted node at promotion)\n')
P('| Cell | valid runs | acked writes (sum) | acked lost at promotion (sum) | runs with loss | acked lost at end of run, final primary (sum; runs with a final read) |')
P('|---|---|---|---|---|---|')
for c, rs in cells.items():
    v = [r for r in rs if r['valid'] == '1']; pr = [r for r in v if r['promoted'] == '1']
    fin = [r for r in pr if r['lost_final'] != '']
    P(f"| {c} | {len(v)} | {sum(int(r['acked_total']) for r in v):,} | {sum(int(r['lost_at_promotion']) for r in pr):,} | {sum(1 for r in pr if int(r['lost_at_promotion'])>0)}/{len(pr)} | {sum(int(r['lost_final']) for r in fin):,} ({len(fin)} runs) |")
P('\n### Fork-LSN cross-check (promoted node\'s timeline fork LSN minus candidate\'s verified receive LSN, bytes)\n')
for c, rs in cells.items():
    pr = [r for r in rs if r['valid'] == '1' and r['promoted'] == '1' and r['fork_vs_recv_diff'] != '']
    d = [int(r['fork_vs_recv_diff']) for r in pr]
    P(f"- {c}: fork == verified receive LSN in {sum(1 for x in d if x == 0)}/{len(d)} promoted runs; other diffs: {sorted(x for x in d if x != 0)}")
P('\n### Invalid runs (none dropped)\n')
inv = [r for r in rows if r['valid'] != '1']
P(f'{len(inv)} invalid of {len(rows)} attempts.\n')
for r in inv: P(f"- {r['run_id']}: {r['invalid_reason']}")

# operator's own status path at decision time
import re, json
P('\n### Operator view at decision time (`kubectl cnpg status`, ~4 s after the primary was killed) vs true\n')
P('Primary is dead at this point, so the operator has no primary LSN to report lag against. Rows: how often the streaming-replication section was unavailable, and how far the reported Current LSN of the non-promoted replica was from its true received LSN.\n')
def lsni(x):
    a, b = x.split('/'); return (int(a, 16) << 32) + int(b, 16)
for c, rs in cells.items():
    v = [r for r in rs if r['valid'] == '1']
    na = 0; errs = []; n = 0
    for r in v:
        d = f"{RUNS}/{r['run_id']}"
        try: t = open(f'{d}/cnpg_status_after_fault.txt').read()
        except Exception: continue
        n += 1
        if 'Not available' in t.split('Instances status')[0].split('Streaming Replication status')[-1][:80]: na += 1
        try: gv = json.load(open(f'{d}/gap_verified.json'))
        except Exception: continue
        for ln in t.split('Instances status')[-1].splitlines():
            m = re.match(r'^(pg-\d+)\s+([0-9A-F]+/[0-9A-F]+)\s+(Standby[^\n]*?)\s{2,}', ln)
            if m and m.group(1) in gv['recv']:
                errs.append(abs(lsni(m.group(2)) - gv['recv'][m.group(1)]))
    P(f"- {c}: status captured in {n} runs; streaming-replication section 'Not available' in {na}; reported Current LSN of a still-standby replica vs its true received LSN: {len(errs)} readings, max abs error {max(errs) if errs else 'n/a'} bytes (reported value can exceed the stall-time receive LSN only if replay/receive advanced after)")
P('\n### Which replica was promoted (B / Bb)\n')
for c, rs in cells.items():
    if not c.startswith('B'): continue
    pr = [r for r in rs if r['valid'] == '1' and r['promoted'] == '1']
    P(f"- {c}: promoted node == replica with the smaller verified gap in {sum(1 for r in pr if r['promoted_node']==r['candidate'])}/{len(pr)}; gap difference between the two replicas (MiB, min-med-max): {mmm([abs(f(r['gap_cand_bytes'])-f(r['gap_other_bytes']))/MiB for r in pr])}")

# recount from stored files
P('\n### Run-level recount check (acked - surviving, from stored files)\n')
ok = bad = 0; badl = []
for r in rows:
    if r['valid'] != '1' or r['promoted'] != '1': continue
    d = f"{RUNS}/{r['run_id']}"
    try:
        a = [int(x) for x in open(f'{d}/acked.txt').read().split()]
        s = set(int(x) for x in open(f'{d}/surviving_at_promotion.txt').read().split())
        hs = hashlib.sha256(open(f'{d}/surviving_at_promotion.txt','rb').read()).hexdigest(); ha = hashlib.sha256(open(f'{d}/acked.txt','rb').read()).hexdigest()
        lost = sum(1 for x in a if x not in s)
        if lost == int(r['lost_at_promotion']) and len(a) == int(r['acked_total']) and hs == r['sha_surviving'] and ha == r['sha_acked']: ok += 1
        else: bad += 1; badl.append((r['run_id'], lost, r['lost_at_promotion']))
    except Exception as e: bad += 1; badl.append((r['run_id'], repr(e)))
P(f'Recomputed loss and SHA-256 for {ok+bad} promoted valid runs from files: {ok} match, {bad} mismatch. {badl}')
print('\n'.join(out))
