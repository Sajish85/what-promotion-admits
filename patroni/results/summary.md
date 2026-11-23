## Per-cell results (valid runs only; invalid listed separately)

| Cell | valid | promoted | refused/blocked | promoted + warning | promoted silent | verified gap MiB (min-med-max) | acked lost txns at promotion (min-med-max) | WAL bytes lost MiB (min-med-max) | Patroni reported lag MiB (med) | reported vs true error MiB (med abs) | time to promotion s (med) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B 10 MB | 10 | 0 | 10 | 0 | 0 | 10.00 - 10.00 - 10.03 | n/a | n/a | 6.3 | 3.7 | n/a |
| B 100 MB | 10 | 0 | 10 | 0 | 0 | 100.04 - 100.10 - 100.20 | n/a | n/a | 53.4 | 46.7 | n/a |
| C 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1191 | 10.00 - 10.00 - 10.03 | 9.6 | 0.4 | 29.65 |
| C 100 MB | 10 | 10 | 0 | 0 | 10 | 100.06 - 100.13 - 100.20 | 11881 - 11888 - 11898 | 100.06 - 100.13 - 100.20 | 94.7 | 5.4 | 29.45 |
| D 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1188 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 5.6 | 4.4 | 1.6 |
| D 100 MB | 10 | 10 | 0 | 0 | 10 | 100.04 - 100.08 - 100.16 | 11876 - 11884 - 11893 | 100.04 - 100.08 - 100.16 | 54.4 | 45.7 | 1.6 |
| E 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1180 - 1188 - 1190 | 10.00 - 10.00 - 10.03 | 9.6 | 0.4 | 29.75 |
| E 100 MB | 10 | 10 | 0 | 0 | 10 | 100.02 - 100.14 - 100.19 | 11877 - 11890 - 11897 | 100.02 - 100.14 - 100.19 | 94.3 | 5.8 | 29.299999999999997 |
| Ej 10 MB | 10 | 10 | 0 | 0 | 10 | 10.00 - 10.00 - 10.03 | 1180 - 1188 - 1188 | 10.00 - 10.00 - 10.03 | 7.1 | 2.9 | 25.85 |
| Ej 100 MB | 10 | 10 | 0 | 0 | 10 | 100.01 - 100.08 - 100.21 | 11875 - 11884 - 11897 | 100.01 - 100.08 - 100.21 | 76.0 | 24.1 | 26.0 |
| Bjb 10 MB | 10 | 10 | 0 | 0 | 10 | 10.06 - 10.64 - 10.99 | 1160 - 1264 - 1307 | 10.06 - 10.64 - 10.99 | 6.5 | 11.0 | 25.65 |

## Denominators (valid runs; acked = COMMIT acknowledged to a writer, lost = acked and absent from the promoted node at promotion)

| Cell | valid runs | acked writes (sum) | acked lost at promotion (sum) | runs with loss | acked lost at end of run, final leader (sum) |
|---|---|---|---|---|---|
| C 10 MB | 10 | 14,280 | 11,883 | 10/10 | 11,883 |
| C 100 MB | 10 | 141,897 | 118,886 | 10/10 | 118,886 |
| D 10 MB | 10 | 14,280 | 11,880 | 10/10 | n/a (cluster rebuilt) |
| D 100 MB | 10 | 141,714 | 118,838 | 10/10 | n/a (cluster rebuilt) |
| E 10 MB | 10 | 14,271 | 11,873 | 10/10 | 11,873 |
| E 100 MB | 10 | 141,874 | 118,873 | 10/10 | 118,873 |
| Ej 10 MB | 10 | 17,632 | 11,872 | 10/10 | 11,872 |
| Ej 100 MB | 10 | 179,289 | 118,843 | 10/10 | 118,843 |
| Bjb 10 MB | 10 | 393,410 | 12,531 | 10/10 | 12,531 |

## Patroni's two views of the candidate's lag at decision time (MiB)

DCS view = leader optime in DCS minus the member's published xlog_location (what `patronictl list` shows). Election view = leader optime in DCS minus the candidate's live received LSN (what `ha.py is_lagging` compares in the automatic path). True = primary LSN at fault minus candidate received LSN. Limit = `maximum_lag_on_failover` = 1 MiB. Candidate for B/Bjb = the replica with the smaller true gap.

| Cell | true gap (med) | DCS view (min / med / max) | election view (min / med / max) | election view <= 1 MiB (would pass the limit) |
|---|---|---|---|---|
| B 10 MB | 10.0 | 6.3 / 6.3 / 9.1 | 6.3 / 6.3 / 9.1 | 0/10 |
| B 100 MB | 100.1 | 52.8 / 53.4 / 60.7 | 52.8 / 53.4 / 60.7 | 0/10 |
| C 10 MB | 10.0 | 5.0 / 9.6 / 9.7 | 5.0 / 9.6 / 9.7 | 0/10 |
| C 100 MB | 100.1 | 53.9 / 94.7 / 95.7 | 53.9 / 94.7 / 95.7 | 0/10 |
| D 10 MB | 10.0 | 5.5 / 5.6 / 9.7 | 5.5 / 5.6 / 9.7 | 0/10 |
| D 100 MB | 100.1 | 54.1 / 54.4 / 54.8 | 54.1 / 54.4 / 54.8 | 0/10 |
| E 10 MB | 10.0 | 5.0 / 9.6 / 9.8 | 4.5 / 9.6 / 9.8 | 0/10 |
| E 100 MB | 100.1 | 73.2 / 94.3 / 95.8 | 73.2 / 94.3 / 95.8 | 0/10 |
| Ej 10 MB | 10.0 | 4.0 / 7.1 / 10.0 | 4.0 / 7.1 / 10.0 | 0/10 |
| Ej 100 MB | 100.1 | 38.4 / 76.0 / 99.9 | 38.4 / 74.5 / 99.9 | 0/10 |
| Bjb 10 MB | 10.6 | -0.2 / 6.5 / 72.1 | -287.3 / -133.5 / -24.6 | 10/10 |

## Bar arithmetic

### Target 10 MB
- C: promoted, no refusal/warning, true loss >= 10 MiB: **10/10** (bar needs >= 8/10)
- E: promoted, no refusal/warning, true loss >= 10 MiB: **10/10** (bar needs >= 8/10)
- E: |reported - true| lag >= 10 MiB: **0/10** (CONTINUE alt. needs >= 5/10); within 1 MiB of truth: **7/10** (KILL needs >= 8/10)
- C: refused or warned: **0/10** (KILL needs >= 8/10 at >= 10 MB)
### Target 100 MB
- C: promoted, no refusal/warning, true loss >= 10 MiB: **10/10** (bar needs >= 8/10)
- E: promoted, no refusal/warning, true loss >= 10 MiB: **10/10** (bar needs >= 8/10)
- E: |reported - true| lag >= 10 MiB: **3/10** (CONTINUE alt. needs >= 5/10); within 1 MiB of truth: **0/10** (KILL needs >= 8/10)
- C: refused or warned: **0/10** (KILL needs >= 8/10 at >= 10 MB)

## Reported vs true lag, per run (abs error, MiB, sorted)

- B 10 MB: 1.0, 3.6, 3.6, 3.6, 3.7, 3.7, 3.7, 3.7, 3.7, 3.7
- B 100 MB: 39.4, 45.1, 45.5, 46.5, 46.6, 46.9, 46.9, 47.0, 47.1, 47.3
- C 10 MB: 0.3, 0.3, 0.3, 0.3, 0.4, 0.4, 3.4, 4.9, 4.9, 5.1
- C 100 MB: 4.4, 5.0, 5.1, 5.3, 5.3, 5.4, 5.6, 5.9, 6.0, 46.2
- D 10 MB: 0.3, 1.5, 4.3, 4.4, 4.4, 4.4, 4.4, 4.4, 4.4, 4.5
- D 100 MB: 45.2, 45.4, 45.6, 45.6, 45.6, 45.7, 45.7, 45.8, 45.9, 46.0
- E 10 MB: 0.2, 0.3, 0.3, 0.3, 0.4, 0.4, 0.4, 3.3, 5.0, 5.0
- E 100 MB: 4.3, 4.5, 4.5, 5.1, 5.1, 6.4, 7.3, 25.2, 26.0, 26.8
- Ej 10 MB: 0.0, 0.2, 0.8, 2.8, 2.8, 3.0, 4.2, 4.3, 5.8, 6.1
- Ej 100 MB: 0.1, 2.7, 4.9, 11.5, 13.3, 35.0, 53.4, 53.7, 54.3, 61.7
- Bjb 10 MB: 2.8, 10.3, 10.5, 10.8, 10.9, 11.1, 18.6, 34.3, 50.3, 61.6

## Supplementary cells (not part of the bar)

- Ej 10 MB: valid 10; promoted 10; refused 0; |reported-true| >= 10 MiB in 0/10; within 1 MiB in 3/10
- Ej 100 MB: valid 10; promoted 10; refused 0; |reported-true| >= 10 MiB in 7/10; within 1 MiB in 1/10
- Bjb 10 MB: valid 10; promoted 10; refused 0; |reported-true| >= 10 MiB in 9/10; within 1 MiB in 0/10

## E: was the DCS cut effective? (candidate agent log lines 'Request to server ... failed' / 'Error communicating' per run)

- E 10 MB: runs with >= 1 DCS error on the candidate's agent: 10/10 (counts [3, 4, 4, 2, 4, 4, 4, 2, 4, 4])
- E 100 MB: runs with >= 1 DCS error on the candidate's agent: 10/10 (counts [3, 4, 4, 4, 4, 5, 5, 4, 4, 4])
- Ej 10 MB: runs with >= 1 DCS error on the candidate's agent: 10/10 (counts [5, 3, 5, 3, 2, 1, 3, 4, 5, 3])
- Ej 100 MB: runs with >= 1 DCS error on the candidate's agent: 10/10 (counts [4, 2, 3, 3, 4, 3, 3, 4, 4, 3])

## Invalid runs

24 invalid of 134 attempts.
- 20 runs, scenario E0: DCS cut ineffective: Patroni etcd3 discovered the real etcd member URL and bypassed the proxy (replica agent kept heartbeating during the "cut")
- 1 runs, scenario Ej: evidence contaminated: primary had 1956 rows vs 964 acked; orphan writer processes from an earlier aborted attempt (killed driver) kept inserting into the same-named table. Detected by the acked_total vs primary_rows_before_fault check; all other runs match
- 1 runs, scenario Bjb: gap off target: 18688456 vs 10485760 (ratio 1.782)
- 1 runs, scenario Bjb: gap off target: 45558176 vs 10485760 (ratio 4.345)
- 1 runs, scenario Bjb: rig exception: OSError: [Errno 28] No space left on device

## Run-level recount check (acked - surviving, from stored files)

Recomputed loss and hashes for 90 promoted runs from files: all match.
