# Failover Gate pilot: PILOT-REPORT

Date: 2026-11-22. Status: **STOPPED AT STEP 0. No trials run.**

## Summary

- The author's failover paper **does report lost acknowledged writes per primary kill**, so the brief's stop condition is met on the evidence I could read.
- The version I read is the local internal draft v3 (18 Nov 2026), not the Zenodo record. I could not find the Zenodo record by web search. The published text may differ. This is the main caveat.
- The overlap is narrower than "already done". The paper's loss numbers come from loopback, near-zero replication lag, process kill only. It says induced-lag cells exist but are outside the paper and "not a bound on asynchronous loss". Lag-driven loss at 10 MB and 100 MB, and what the promotion safeguard admits, are not reported in it.
- PM must re-decide before any trials, per the brief. Separate from step 0: Docker is not usable from the shell here (see Blockers).

## Step-0 evidence

Source read: `~/external-review/papers/03-db-failover.txt` (802 lines), "Client-Observed Write Unavailability After a Primary Process Kill: Five Replicated Database Systems at Shipped Settings on a Single Host", Sajish Krishnan, "Internal draft v3, 18 November 2026. Not for circulation." Status of this file as a copy of the published paper: unverified.

| Claim | Where in the text (quoted or paraphrased from what I read) |
|---|---|
| Per-kill reconciliation of every acknowledged write | Sec. 2: "Acknowledged IDs were reconciled in every run of every system." Classes: acknowledged-and-present, acknowledged-but-lost, committed-but-unacknowledged. |
| Lost writes reported for PostgreSQL/Patroni defaults | Abstract: "The PostgreSQL defaults cell ... lost one acknowledged transaction in each of 2 of 30 runs." Sec. 3.1: 2 of 30 runs, out of 270,676 acknowledged writes. Tuned-timing cell: none of 270,941. |
| Sibling PG cells | 1 in 1 of 30 runs (PostgreSQL 16.16); 2 in 2 of 20 (fourth node); 1 in 1 of 10 (same-session control); none in 20 (read-heavy mix). |
| Other systems | MongoDB, MySQL GR, Redis, CockroachDB: zero acknowledged writes lost, with denominators. |
| Limits that matter for this pilot | Sec. 3.1: "Cells with heavier write load, induced replica delay, a second fault or a stop signal instead of a kill are outside this paper; several of them lost acknowledged writes, so the loss counts below are not a bound on asynchronous loss in PostgreSQL." Limitation 2: loopback, "Replication lag is close to zero". Limitation 4: one fault type, process kill. |

What the paper does not do (from what I read): inject controlled lag at 10 or 100 MB, test a promotion safeguard or a lag limit, compare reported lag to true lag, or test manual `patronictl failover`, DCS-partition, or `pg_promote()` paths. I did not search the full text for every one of those terms; this list is from the sections I read (abstract, 3.1, tables, limitations, conclusion).

Prior knowledge worth flagging to the PM: Sec. 3.1 says induced-delay cells exist in the author's own data (`~/postgres-failover-lab`, not opened). Those may already hold relevant loss numbers. I did not open them.

## Verdict against the brief

Brief: "If it already reports lost writes per kill, STOP ... the PM must re-decide." The paper reports lost writes per kill. Stopped. I applied the brief literally and did not judge whether the narrower overlap above should override it. That call is the PM's.

## Setup, results, bar verdict

Not run. No CSV produced. Verdict: **none (pilot not executed)**.

## Blockers

1. **Zenodo record not found.** Two web searches (standard and extended) returned only unrelated Zenodo incident posts and third-party Patroni blogs. Smallest next step: PM supplies the Zenodo DOI/URL, or confirms the local draft v3 matches the published text.
2. **Docker unavailable in this shell.** `docker` is not on PATH. `/Applications/Docker.app` exists; I did not launch it or search for its CLI, since step 0 ended the run. If the PM re-opens the pilot, first check whether Docker.app is running and its CLI is installed, and whether Patroni/PostgreSQL images exist for arm64 (unverified).

## Completion note

- **Did:** read the brief and the vetting; searched the web twice for the paper; found and read the local draft; wrote this report. No containers created, so nothing to clean up. No messages or posts.
- **Found:** the paper reports per-kill lost acknowledged writes (PG/Patroni defaults: 2 of 30 runs, 1 transaction each). Its limits exclude induced lag.
- **Blocked:** Zenodo version unverified; Docker CLI not on PATH.
