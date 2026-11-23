#!/usr/bin/env python3
import sys, os, time, traceback, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
from lib import *
cells = [c.split(':') for c in sys.argv[1].split(',')]     # e.g. B:10,B:100,C:10
need = int(sys.argv[2]) if len(sys.argv) > 2 else 10
maxatt = need + 8
PROG = '/root/cnpg/progress-cells.log'
for sc, tg in cells:
    tg = int(tg)
    h.set_delay(0 if sc in ('B', 'Bb') else 300); time.sleep(3)
    valid = 0; att = 0
    existing = [d for d in os.listdir(h.RUNS) if d.startswith(f'{sc}-{tg}MB-r')] if os.path.isdir(h.RUNS) else []
    att = len(existing)
    while valid < need and att < maxatt + len(existing):
        att += 1
        rid = f'{sc}-{tg}MB-r{att:02d}'
        try:
            row = h.run_one(sc, tg, rid, f'{h.RUNS}/{rid}')
        except Exception as e:
            row = {c: '' for c in h.COLS}; row.update(run_id=rid, ts=ts(), scenario=sc, target_mib=tg, valid=0, invalid_reason='rig exception: ' + repr(e)[:200])
            open(f'{h.RUNS}/{rid}/exception.txt', 'a').write(traceback.format_exc()) if os.path.isdir(f'{h.RUNS}/{rid}') else None
            h.release_all()
        h.append_row(row)
        if str(row.get('valid')) == '1': valid += 1
        print(f"{ts()} {rid} valid={row.get('valid')} {row.get('invalid_reason','')} outcome={row.get('outcome')} lost={row.get('lost_at_promotion')} gap={row.get('gap_cand_bytes')}", flush=True)
    with open(PROG, 'a') as f:
        f.write(f"{ts()} CELL {sc} {tg}MiB done: {valid} valid of {att} attempts\n")
