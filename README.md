# What Promotion Admits: Acknowledged-Write Loss on PostgreSQL HA Promotion Paths When the Candidate Is Missing WAL

Data and harness supplement to the paper by Sajish Krishnan (independent researcher, GitHub [Sajish85](https://github.com/Sajish85), ORCID [0009-0009-7561-9290](https://orcid.org/0009-0009-7561-9290)).

- Paper: [10.5281/zenodo.24466482](https://doi.org/10.5281/zenodo.24466482)
- Prior work: S. Krishnan, *Client-Observed Write Unavailability After a Primary Process Kill: Five Replicated Database Systems at Shipped Settings on a Single Host*, Zenodo, DOI [10.5281/zenodo.24359723](https://doi.org/10.5281/zenodo.24359723). Earlier repository: [Sajish85/client-observed-write-unavailability](https://github.com/Sajish85/client-observed-write-unavailability).

## Abstract

A lag setting, such as Patroni's `maximum_lag_on_failover`, is naturally read as a bound on how much acknowledged data a failover can lose; we measured what each promotion path of three widely used stacks actually admits when the candidate replica has not received 10 MiB or 100 MiB of WAL: Patroni 4.1.5, pg_auto_failover 2.2 and CloudNativePG 1.30.2. We built each gap by stalling WAL shipping while the primary kept accepting writes, verified it per run against the primary's and the candidate's LSNs, killed the primary, and recomputed every acknowledged-write loss from stored lists of acknowledged and surviving transaction ids. Across 300 valid runs on three single-host rigs, the stacks gave three different answers. Patroni's operator-initiated `patronictl failover`, with the leader gone and a named candidate, promoted silently in 40 of 40 runs across the C and E scenarios (the command was scripted with `--force`, so its interactive confirmation was not exercised) and lost the whole gap (up to 11,898 acknowledged transactions at 100 MiB), while its automatic path refused 20 of 20 slowly formed gaps but, in a supplementary burst cell with unthrottled writers (gap formed in 0.5 to 1.5 s), promoted silently in 10 of 10 runs: the leader position stored in the DCS lagged the candidate's own position by 24 to 287 MiB, so the computed lag was negative in 10 of 10 runs. pg_auto_failover, when configured for asynchronous replication, gated both automatic and operator promotion at 16 MiB on last-reported LSNs: a 10 MiB gap passed silently in every run and a 100 MiB gap was refused in every run, with the refusal reason visible only in the monitor log; a direct `pg_promote()` bypassed the gate at both sizes. CloudNativePG showed no lag gate on any measured path: automatic failover promoted silently in 10 of 10 runs at 100 MiB and lost 11,763 to 11,778 acknowledged transactions. The lag figures the stacks used or displayed at decision time were themselves unreliable: Patroni's operator-visible view had a median error of 46.7 MiB in one slow cell, and pg_auto_failover's monitor-reported lag erred by up to 29.2 MiB in supplementary burst runs. In these three stacks, a lag setting bounds loss only on the path that consults it, and only when the position it compares against is fresh. All results come from one host per stack, asynchronous replication, and one version per stack.

## Headline results

Cross-stack matrix (paper Section 4.4). Each cell is the promotion result over 10 valid runs; loss is acknowledged transactions per run (min to max). "Silent" means no lag-related text in the command output or the stack's logs.

| Path | Target (MiB) | Patroni 4.1.5 | pg_auto_failover 2.2 | CloudNativePG 1.30.2 |
|---|---|---|---|---|
| Automatic, slow gap (B) | 10 | refused 10/10, 0 lost | promoted silent 10/10, 1,188 lost (below its 16 MiB gate) | promoted silent 10/10, 1,152 to 1,180 lost |
| Automatic, slow gap (B) | 100 | refused 10/10, 0 lost | refused 10/10, 0 lost | **promoted silent 10/10, 11,763 to 11,778 lost** |
| Automatic, burst (Bb, Bjb; supplementary cells) | 10 | **promoted silent 10/10, 1,160 to 1,307 lost** | promoted silent 10/10, 1,192 to 1,386 lost (below its gate) | promoted silent 10/10, 1,181 to 1,236 lost |
| Automatic, burst (Bb; supplementary cell) | 100 | not run | refused 10/10 (fastest gap 1.9 s) | not run |
| Operator-manual (C) | 10 | promoted silent 10/10, 1,188 to 1,191 lost | promoted silent 10/10, 1,188 lost (below its gate) | promoted silent 10/10, 1,176 to 1,181 lost |
| Operator-manual (C) | 100 | **promoted silent 10/10, 11,881 to 11,898 lost** | refused 10/10, exit 12 after 60 s | **promoted silent 10/10, 11,759 to 11,776 lost** |
| Status path cut, then manual (E) | 10 | promoted silent 10/10, 1,180 to 1,190 lost | promoted silent 10/10, 1,188 lost (below its gate; weaker analogue, keeper-to-monitor cut) | no E cell |
| Status path cut, then manual (E) | 100 | **promoted silent 10/10, 11,877 to 11,897 lost** | refused 10/10 (weaker analogue, keeper-to-monitor cut) | no E cell |
| Bypass `pg_promote()` (D) | 10 | promoted 10/10, 1,188 lost; node a replica again in 10/10 | promoted 10/10, 1,188 lost; monitor ratified the node 10/10 | promoted 10/10, 1,152 to 1,178 lost; node stopped by the instance manager in 10/10 |
| Bypass `pg_promote()` (D) | 100 | promoted 10/10, 11,876 to 11,893 lost; node a replica again in 10/10 | promoted 10/10, 11,879 to 11,899 lost; node back in recovery within 60 s in 10/10 | promoted 10/10, 11,736 to 11,773 lost; node stopped by the instance manager in 10/10 |

All results come from one host per stack, asynchronous replication, and one version per stack. This is a measurement report, not a ranking of the tools. See the paper for the full method, the equivalence notes under the matrix, and the threats to validity.

## Layout

```
CITATION.cff
README.md
patroni/
  PILOT-REPORT.md            report for the Patroni study (and setup notes: rig, versions, deviations)
  bin/                       cluster-up.sh, cluster-down.sh, env.sh, pxctl.sh, tcpproxy.py, writer.py, harness.py, driver.py, analyze.py
  results/                   results.csv (134 rows), summary.md, driver logs, shakedown/, earlier CSV and pilot report
  runs/<cell>-r<NN>/         per-run evidence (also shakedown/ and aborted-supp-ineffective-cut/)
pg-auto-failover/
  pg-auto-failover-report.md report for the pg_auto_failover study
  SETUP.md                   setup notes: rig, versions, deviations
  progress.log
  bin/                       cluster-up.sh, cluster-down.sh, env.sh, pxctl.sh, tcpproxy.py, writer.py, harness.py, driver.py, reap-ipc.py, analyze.py
  results/                   results.csv (126 rows), summary.md, driver logs
  runs/<cell>-r<NN>/         per-run evidence
cloudnativepg/
  cnpg-report.md             report for the CloudNativePG study
  cnpg-SETUP.md              setup notes: rig, versions, deviations
  progress-cnpg.log
  cnpg-results.csv           results CSV (76 rows); identical copy at cnpg-runs/results.csv
  cnpg-runs/
    bin/                     harness.py, driver.py, lib.py, writer.py, analyze.py
    pg.yaml, kind.yaml       cluster manifests
    runs/<cell>-r<NN>/       per-run evidence (including _partial_* attempts)
    logs/, shakedown-*.csv, progress-cells.log, bytes_per_txn
```

## Reproduce

Each stack has its own folder with the harness scripts, the results CSV (one row per attempt, including invalid runs and their reasons) and the per-run evidence (event logs, acknowledged and surviving id lists with SHA-256 hashes, lost-id lists, and the stack's own view at decision time).

`analyze.py` for each stack regenerates the per-cell tables, the denominators, the invalid-run list and the loss recount from the stored files without re-running anything. The setup notes for each stack describe the rig, the versions as read from the running systems, and every deviation from shipped defaults.

- CloudNativePG: from the repository root, `python3 -I cloudnativepg/cnpg-runs/bin/analyze.py cloudnativepg`. It reads `cloudnativepg/cnpg-results.csv` and the per-run files under `cloudnativepg/cnpg-runs/runs`.
- Patroni: `patroni/bin/analyze.py` reads `results/results.csv` and `runs/` under a path set in the `LAB` variable at the top of the file. Set it to the absolute path of your `patroni/` folder, then run `python3 -I patroni/bin/analyze.py`.
- pg_auto_failover: `pg-auto-failover/bin/analyze.py` reads `results/results.csv` and `runs/` under a path set in the `ST` variable at the top of the file. Set it to the absolute path of your `pg-auto-failover/` folder, then run `python3 -I pg-auto-failover/bin/analyze.py`.

## Licence

The paper is released under CC BY 4.0. [10.5281/zenodo.24466482](https://doi.org/10.5281/zenodo.24466482)

## Cite

See `CITATION.cff`.
