### Per-cell results (valid runs; invalid listed below)

| Cell | valid | promoted | refused | promoted+warning | promoted silent | verified gap MiB (min-med-max) | acked lost txns (min-med-max) | WAL lost MiB (min-med-max) | monitor-reported lag MiB (med) | |reported-true| MiB (min-med-max) | time to promotion s (med) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 9.98 | 0.00 - 0.03 - 0.10 | 22.3 - 23.6 - 24.2 |
| Bb 10 MB | 10 | 10 | 0 | 0 | 10 | 10.04 - 10.57 - 11.68 | 1192 - 1255 - 1386 | 10.04 - 10.57 - 11.68 | 5.59 | 0.00 - 5.11 - 24.56 | 27.8 - 33.1 - 35.2 |
| C 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 9.92 | 0.03 - 0.08 - 0.13 | 53.0 - 54.6 - 55.2 |
| D 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 9.97 | 0.00 - 0.03 - 0.07 | 1.5 - 1.5 - 1.6 |
| E 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 10.54 | 0.03 - 0.54 - 0.55 | 53.6 - 54.5 - 55.4 |
| Ea 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 10.54 | 0.07 - 0.54 - 0.57 | 22.6 - 23.2 - 24.4 |
| B 100 MB | 10 | 0 | 10 | 0 | 0 | 100.03 - 100.07 - 100.17 | n/a | n/a | 97.46 | 1.85 - 2.66 - 3.06 | n/a |
| Bb 100 MB | 10 | 0 | 10 | 0 | 0 | 100.11 - 100.87 - 101.87 | n/a | n/a | 93.83 | 0.00 - 7.27 - 29.18 | n/a |
| C 100 MB | 10 | 0 | 10 | 0 | 0 | 100.01 - 100.15 - 100.20 | n/a | n/a | 97.70 | 1.82 - 2.37 - 3.70 | n/a |
| D 100 MB | 10 | 10 | 0 | 0 | 10 | 100.04 - 100.06 - 100.21 | 11879 - 11882 - 11899 | 100.04 - 100.06 - 100.21 | 97.67 | 2.02 - 2.47 - 3.15 | 1.5 - 1.5 - 1.5 |
| E 100 MB | 10 | 0 | 10 | 0 | 0 | 100.02 - 100.11 - 100.19 | n/a | n/a | 102.27 | 2.09 - 2.32 - 3.76 | n/a |
| Ea 100 MB | 10 | 0 | 10 | 0 | 0 | 100.01 - 100.11 - 100.17 | n/a | n/a | 102.53 | 2.23 - 2.78 - 3.13 | n/a |

### Denominators (valid runs)

| Cell | valid | acked writes (sum) | acked lost at promotion (sum) | runs with loss |
|---|---|---|---|---|
| B 10 MB | 10 | 14,280 | 11,880 | 10/10 |
| Bb 10 MB | 10 | 486,107 | 12,733 | 10/10 |
| C 10 MB | 10 | 14,288 | 11,880 | 10/10 |
| D 10 MB | 10 | 14,276 | 11,880 | 10/10 |
| E 10 MB | 10 | 14,280 | 11,880 | 10/10 |
| Ea 10 MB | 10 | 14,280 | 11,880 | 10/10 |
| B 100 MB | 10 | 142,184 | 0 | 0/10 |
| Bb 100 MB | 10 | 431,274 | 0 | 0/10 |
| C 100 MB | 10 | 142,234 | 0 | 0/10 |
| D 100 MB | 10 | 142,148 | 118,856 | 10/10 |
| E 100 MB | 10 | 142,311 | 0 | 0/10 |
| Ea 100 MB | 10 | 142,174 | 0 | 0/10 |

### Monitor-side view at decision time (MiB): monitor's reported primary LSN minus candidate's reported LSN vs true gap; threshold promote_wal_log_threshold = 16 MiB

| Cell | true gap (med) | reported lag (min / med / max) | reported <= 16 MiB (would pass the monitor gate) |
|---|---|---|---|
| B 10 MB | 10.0 | 9.9 / 10.0 / 10.0 | 10/10 |
| Bb 10 MB | 10.6 | -14.1 / 5.6 / 11.7 | 10/10 |
| C 10 MB | 10.0 | 9.9 / 9.9 / 10.0 | 10/10 |
| D 10 MB | 10.0 | 9.9 / 10.0 / 10.0 | 10/10 |
| E 10 MB | 10.0 | 10.0 / 10.5 / 10.6 | 10/10 |
| Ea 10 MB | 10.0 | 9.9 / 10.5 / 10.6 | 10/10 |
| B 100 MB | 100.1 | 97.0 / 97.5 / 98.2 | 0/10 |
| Bb 100 MB | 100.9 | 72.5 / 93.8 / 101.6 | 0/10 |
| C 100 MB | 100.1 | 96.4 / 97.7 / 98.4 | 0/10 |
| D 100 MB | 100.1 | 96.9 / 97.7 / 98.1 | 0/10 |
| E 100 MB | 100.1 | 96.3 / 102.3 / 102.9 | 0/10 |
| Ea 100 MB | 100.1 | 97.0 / 102.5 / 103.0 | 0/10 |

### D: what the stack did after pg_promote() (15 s and 60 s later)

- D 10 MB: (in_recovery at 15 s, at 60 s) counts: {('False', 'False'): 10}
  - monitor states 60 s: [('{"n1": "primary/demoted", "n2": "secondary/secondary", "n3": "primary/primary"}', 5), ('{"n1": "primary/demoted", "n2": "primary/primary", "n3": "secondary/secondary"}', 5)]
- D 100 MB: (in_recovery at 15 s, at 60 s) counts: {('False', 'True'): 10}
  - monitor states 60 s: [('{"n1": "primary/draining", "n2": "report_lsn/report_lsn", "n3": "report_lsn/report_lsn"}', 10)]

### Invalid runs

6 invalid of 126 attempts.
- C-100MB-r08: perform_promotion call failed with a monitor deadlock (rc 0 returned, promotion never requested); outcome reflects the automatic path, not C. Re-run. (reclassified after review; was logged VALID/no_promotion_refused)
- E-100MB-r03: rig: cluster did not become healthy after build
- E-100MB-r04: rig: cluster did not become healthy after build
- E-100MB-r05: rig: cluster did not become healthy after build
- E-100MB-r06: rig: cluster did not become healthy after build
- E-100MB-r07: rig: cluster did not become healthy after build

### Run-level recount check (acked - surviving, from stored files)

Recomputed loss and hashes for 70 promoted valid runs from files: all match.
acked_total vs primary_rows_before_fault: all equal (valid runs).
fork LSN == verified receive LSN of promoted node: 70/70 promoted valid runs.
differences (fork - recv bytes): none
