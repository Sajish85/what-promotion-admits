#!/usr/bin/env python3
"""Run every (scenario, target) cell until 10 VALID runs; invalid runs are logged in results.csv, never dropped.
Resumable: counts existing rows in results/results.csv. Order: B, C, D, E; 10 MB then 100 MB within each."""
import csv, os, sys, time, json
sys.path.insert(0, os.path.dirname(__file__))
import harness
CELLS = [("Ej", 10)]   # replacement for the contaminated Ej-10MB-r03
CSV = f"{harness.LAB}/results/results.csv"
def rows():
    return list(csv.DictReader(open(CSV))) if os.path.exists(CSV) else []
for scn, mb in CELLS:
    while True:
        rs = [r for r in rows() if r["scenario"] == scn and int(r["target_mb"]) == mb]
        valid = sum(1 for r in rs if r["valid"] == "VALID")
        if valid >= 10: break
        if len(rs) >= 22:
            print(f"BLOCKED {scn} {mb}MB: {len(rs)} attempts, {valid} valid", flush=True); break
        tail = rs[-5:]
        if len(tail) == 5 and all(r["valid"] != "VALID" for r in tail):
            print(f"BLOCKED {scn} {mb}MB: last 5 attempts invalid", flush=True); break
        no = len(rs) + 1
        t = time.time()
        r = harness.run(scn, mb, no); harness.append_csv(r)
        print(time.strftime("%H:%M:%S"), r["run_id"], r.get("valid"), r.get("invalid_reason", ""), r.get("outcome", ""), "gap=", r.get("gap_verified_bytes"), "lost=", r.get("acked_lost_at_promotion"), f"{time.time()-t:.0f}s", flush=True)
print("DRIVER DONE", flush=True)
