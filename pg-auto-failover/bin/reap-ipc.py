#!/usr/bin/env python3
"""Reap orphaned SysV semaphore sets (leaked by SIGKILLed postmasters; macOS kernel exhausts SEMMNS).
PG derives semaphore keys from the data directory inode (key in [ino, ino+N]); sets whose key matches no LIVE postmaster data dir
(cwd of every running postmaster, any project) are orphans. Own-user sets only. Dry run unless --do."""
import subprocess, sys, os
do = "--do" in sys.argv
live = []
pids = subprocess.run(["pgrep", "-x", "postgres"], capture_output=True, text=True).stdout.split()
for pid in pids:
    out = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
    for ln in out.splitlines():
        if ln.startswith("n") and os.path.isdir(ln[1:]):
            try: live.append(os.stat(ln[1:]).st_ino)
            except OSError: pass
live = sorted(set(live))
rows = subprocess.run(["ipcs", "-s", "-a"], capture_output=True, text=True).stdout.splitlines()[3:]
me = os.environ.get("USER"); keep = rm = 0
for ln in rows:
    a = ln.split()
    if len(a) < 5 or a[0] != "s" or a[4] != me: continue
    key = int(a[2], 16)
    if any(0 <= key - i <= 100000 for i in live): keep += 1; continue
    rm += 1
    if do: subprocess.run(["ipcrm", "-s", a[1]], capture_output=True)
print(f"live datadir inodes={len(live)} keep={keep} {'removed' if do else 'would remove'}={rm}")
