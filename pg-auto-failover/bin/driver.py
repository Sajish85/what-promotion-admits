#!/usr/bin/env python3
"""driver.py CELLS...   cell = SCN:MB  e.g. C:10 B:100 Bb:10. Runs until 10 valid per cell (max 16 attempts), resumable from results/results.csv."""
import sys, csv, os, subprocess, time
ST = os.path.expanduser("~/invention-hunt/studies/failover-gate")
PY = os.path.expanduser("~/tools/venv/bin/python")
def rows():
    p = f"{ST}/results/results.csv"
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []
for cell in sys.argv[1:]:
    scn, mb = cell.split(":")
    while True:
        rs = [r for r in rows() if r["scenario"] == scn and r["target_mb"] == mb]
        valid = sum(r["valid"] == "VALID" for r in rs)
        if valid >= 10 or len(rs) >= 16: break
        no = len(rs) + 1
        if no == 91: no += 1
        subprocess.run([PY, f"{ST}/bin/harness.py", scn, mb, str(no)], stdout=open(f"{ST}/results/driver.log", "a"), stderr=subprocess.STDOUT)
    rs = [r for r in rows() if r["scenario"] == scn and r["target_mb"] == mb]
    open(f"{ST}/progress.log", "a").write(f"{time.strftime('%H:%M')} pg_auto_failover {scn} {mb}MB valid={sum(r['valid']=='VALID' for r in rs)} attempts={len(rs)}\n")
