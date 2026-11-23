# What Promotion Admits: Acknowledged-Write Loss on PostgreSQL HA Promotion Paths When the Candidate Is Missing WAL

Sajish Krishnan, Independent researcher

## Abstract

A lag setting, such as Patroni's `maximum_lag_on_failover`, is naturally read as a bound on how much acknowledged data a failover can lose; we measured what each promotion path of three widely used stacks actually admits when the candidate replica has not received 10 MiB or 100 MiB of WAL: Patroni 4.1.5, pg_auto_failover 2.2 and CloudNativePG 1.30.2. We built each gap by stalling WAL shipping while the primary kept accepting writes, verified it per run against the primary's and the candidate's LSNs, killed the primary, and recomputed every acknowledged-write loss from stored lists of acknowledged and surviving transaction ids. Across 300 valid runs on three single-host rigs, the stacks gave three different answers. Patroni's operator-initiated `patronictl failover`, with the leader gone and a named candidate, promoted silently in 40 of 40 runs across the C and E scenarios (the command was scripted with `--force`, so its interactive confirmation was not exercised) and lost the whole gap (up to 11,898 acknowledged transactions at 100 MiB), while its automatic path refused 20 of 20 slowly formed gaps but, in a supplementary burst cell with unthrottled writers (gap formed in 0.5 to 1.5 s), promoted silently in 10 of 10 runs: the leader position stored in the DCS lagged the candidate's own position by 24 to 287 MiB, so the computed lag was negative in 10 of 10 runs. pg_auto_failover, when configured for asynchronous replication, gated both automatic and operator promotion at 16 MiB on last-reported LSNs: a 10 MiB gap passed silently in every run and a 100 MiB gap was refused in every run, with the refusal reason visible only in the monitor log; a direct `pg_promote()` bypassed the gate at both sizes. CloudNativePG showed no lag gate on any measured path: automatic failover promoted silently in 10 of 10 runs at 100 MiB and lost 11,763 to 11,778 acknowledged transactions. The lag figures the stacks used or displayed at decision time were themselves unreliable: Patroni's operator-visible view had a median error of 46.7 MiB in one slow cell, and pg_auto_failover's monitor-reported lag erred by up to 29.2 MiB in supplementary burst runs. In these three stacks, a lag setting bounds loss only on the path that consults it, and only when the position it compares against is fresh. All results come from one host per stack, asynchronous replication, and one version per stack.

## 1. Introduction

A replica that has not received all of the primary's WAL is the normal state of an asynchronous PostgreSQL cluster. What a deployment expects to lose when the primary disappears is therefore a recovery point objective (RPO) question, and the answer on offer is a number in a configuration file. Patroni's documentation describes `maximum_lag_on_failover` as "the maximum bytes a follower may lag to be able to participate in leader election" and states that in asynchronous mode the amount of transactions that can be lost "is controlled via `maximum_lag_on_failover` parameter" [2]. pg_auto_failover has a threshold for the WAL difference it tolerates between a standby and the primary [4]. CloudNativePG documents that "some data loss is expected and accepted" when synchronous replication is not enabled [5]. Each statement is about a setting or a mode. None says which of the operator's promotion paths consult it.

This study measures the paths, not the settings. A promotion can be requested in at least four ways: the stack's automatic failover logic, an operator command issued while the primary is gone, the same command after the replica has lost contact with the stack's coordination store, and a direct call to PostgreSQL's `pg_promote()` that bypasses the stack. For each path on each stack we ask the same question: when the candidate is missing 10 MiB or 100 MiB of WAL and the primary is lost, does the stack refuse, warn, or promote, and how many acknowledged transactions are lost?

We contribute three things.

1. **A per-path admission matrix on three stacks.** Patroni 4.1.5, pg_auto_failover 2.2 and CloudNativePG 1.30.2, each tested on the same scenario definitions (Section 3) with 10 valid runs per cell and with the gap verified by LSN in every run.
2. **A stale-reference result for automatic safeguards.** Patroni's automatic lag check refused 20 of 20 gaps that grew over about 15 s and, in a supplementary burst cell with unthrottled writers (gap formed in 0.5 to 1.5 s), passed 10 of 10 gaps of the same size. The leader position stored in the DCS lagged the candidate's own position by 24 to 287 MiB, so the computed lag was negative in 10 of 10 runs, because the check compares the candidate with a leader position published once per control loop. We found the same kind of staleness in pg_auto_failover's reported LSNs (supplementary burst cell) but could not build a gap fast enough to cross its threshold.
3. **Reported lag versus true lag at decision time.** The lag figure each stack shows, or uses, when the decision is made was itself unreliable: Patroni's operator-visible (DCS) view had a median absolute error of up to 46.7 MiB in the slow 100 MiB cells, and pg_auto_failover's monitor-reported lag erred by up to 29.2 MiB in supplementary burst runs. In the primary Patroni E cell the DCS view was off by at least 10 MiB in 0 of 10 runs at 10 MiB and 3 of 10 at 100 MiB, and in 7 of 10 runs of the supplementary phase-jittered cell (Ej) at 100 MiB.

As a contrast point we use the author's earlier failover study on the same Patroni family [1]. That study killed the primary process at near-zero replication lag and found that PostgreSQL with Patroni at defaults lost one acknowledged transaction in each of 2 of 30 runs, out of 270,676 acknowledged writes. Here the gap is deliberately large, and every run that promoted lost 1,152 to 1,386 acknowledged transactions at the 10 MiB target and 11,736 to 11,899 at the 100 MiB target.

The framing is a measurement study. We compare behaviour at the same measured gap. We do not rank the tools: the three stacks have different promotion architectures and differ in more than their lag handling.

## 2. Background

### 2.1 Promotion paths

We use four path categories throughout.

- **Automatic.** The stack detects that the primary is gone and elects a replica without operator input.
- **Operator-manual.** An operator command requests promotion of a named replica while the primary is gone: `patronictl failover --candidate X --force`, `kubectl cnpg promote pg X`, `pg_autoctl perform promotion --name X`.
- **Status-path effect.** The same manual request after the candidate's path to the stack's coordination store has been cut and restored. This tests whether what the stack knew or did not know about the candidate changes the decision.
- **Direct bypass.** `pg_promote()` called on the replica through SQL, outside the stack's control. A gate cannot apply to this call; what matters is what the stack does afterwards.

### 2.2 What each stack documents

**Patroni.** The documentation defines `maximum_lag_on_failover` as "the maximum bytes a follower may lag to be able to participate in leader election" [2]. It states that in asynchronous mode the worst case loss is bounded by that setting "plus the amount that is written in the last `ttl` seconds", and that "the primary transaction log position is not sampled in real time" [2]. For manual failover the documentation says that `patronictl failover` "is designed to be used when the cluster is not healthy", that it can be run in a healthy cluster, and that "triggering a failover can cause data loss depending on how up-to-date the promoted replica is in comparison to the primary" [2]. It states no lag limit for it. The documentation quoted here is the repository documentation at tag v4.1.5 [2].

The source of the exact version we ran (4.1.5, the installed package) shows where the setting is consulted [3]. `Ha.is_lagging` computes the leader position last stored in the DCS minus the node's own WAL position and compares it with `maximum_lag_on_failover`. `Ha._is_healthiest_node` applies that check when `check_replication_lag` is true, and logs "My wal position exceeds maximum replication lag" when it fails. In `Ha.manual_failover_process_no_leader`, which handles a manual failover when the old leader is gone, a node that is the named candidate returns true without a lag check. The fallback path that considers all members calls `_is_healthiest_node(members, check_replication_lag=False)`. The REST handler's pre-check (`is_failover_possible` in `api.py`) filters members through `failover_limitation()`, which tests reachability, the `nofailover` tag and watchdog capability, not lag. `Ha.is_failover_possible` does apply `is_lagging` to other candidates, but it is called from the branch taken when the node was the leader, so it is not on the tested path (leader gone, named candidate). The leader's position in the DCS is written by the leader's own control loop (`update_leader`, fed from the leader's last WAL position), not sampled when a candidate evaluates itself [3].

**pg_auto_failover.** A monitor orchestrates failover and promotion through a state machine. The documentation says that in the `report_lsn` state the monitor needs "a fresh report of the current LSN position reached on each standby node" in order to pick the furthest standby, and describes `perform promotion` as a promotion orchestrated in the background by the monitor, which the client waits for up to 60 s by default (the `--wait` default); the monitor's orchestration continues after the client gives up [4]. In the v2.2 monitor source, the candidate-selection function refuses to select a standby when `WalDifferenceWithin(mostAdvancedNode, primaryNode, PromoteXlogThreshold)` is false; that function compares the absolute difference between two reported LSNs with a byte threshold and treats an unreported (zero) LSN as not within it [4]. The comparison is between the most advanced standby and the primary, not the named candidate, so with `--name X` the refusal depends on the other standby's reported position; the study's group had three data nodes, and a two-node branch in the source was not tested [4]. `pgautofailover.promote_wal_log_threshold` is registered in `src/monitor/pg_auto_failover.c` bound to the variable `PromoteXlogThreshold` [4]. The refusal log text names `pgautofailover.enable_sync_wal_log_threshold` while the comparison passes `PromoteXlogThreshold` [4], an upstream message inconsistency. The documentation does not name the setting, but describes the candidate as "within 16MB or 1 WAL segment of the primary" (`docs/failover-state-machine.rst`) [4]; our value of 16 MiB for `pgautofailover.promote_wal_log_threshold` is read from the running monitor with `psql`.

**CloudNativePG.** An operator reconciles a `Cluster` resource and runs an instance manager in each pod. The failover documentation says that the operator names a new primary after a leader election and that an instance "must acquire and hold" a lease before it promotes [5]. It describes `.spec.failoverDelay` (default 0 s) as the delay before the failover procedure starts after the primary is detected unhealthy [5]. It states that "when synchronous replication is not enabled, some data loss is expected and accepted during failover" and describes no lag bound on the default asynchronous path [5]. An optional readiness probe of type `streaming` with `maximumLag` can exclude a replica from promotion during failover [5]; it is not enabled by default and we did not enable it. For manual promotion, the Promote section of the plugin documentation describes `kubectl cnpg promote CLUSTER INSTANCE` as promoting a pod to primary and documents no lag or LSN check [5]. The documentation pages we read do not mention `pg_promote()` or promotion outside the operator.

## 3. Method

### 3.1 Rigs

Patroni and pg_auto_failover ran on one Mac (macOS 15.5, arm64) over loopback, with PostgreSQL 17.12. The Patroni rig used Patroni 4.1.5 and etcd 3.7.3, three data nodes, and Patroni defaults (`ttl` 30, `loop_wait` 10, `retry_timeout` 10, `maximum_lag_on_failover` 1,048,576 bytes, `primary_start_timeout` 300, asynchronous replication). The pg_auto_failover rig used release v2.2 built from source, one monitor and three data nodes. CloudNativePG ran on a separate machine (Windows 10 host, WSL2 Ubuntu 24.04, Docker Engine 29.1.3, kind v0.33.0 with Kubernetes v1.34.11): one control-plane node and three workers, operator 1.30.2, PostgreSQL 17.11 from the project's image, three instances with required anti-affinity so that each instance sits on its own worker. Versions were read from the running systems.

In all three rigs the primary and the two replicas run on one physical host. Replication and coordination traffic never leaves the machine.

### 3.2 Gap construction

The quantity under test is WAL the candidate has not received. We build it by **stalling WAL shipping** while the primary keeps accepting writes. We did not use replay delay: a delayed-replay replica has already received the WAL, which sits in its own log where promotion can still use it, so it would not put the candidate in the condition under test. We state this as design reasoning, not a tested claim.

On Patroni and pg_auto_failover, a small TCP proxy sits on each node's registered replication address. In stall mode it stops reading on every open connection in both directions, so bytes stay in kernel buffers, holds new connections without opening the upstream leg, and defers close propagation. The replica's agent stays live, so nothing in the stack sees a dead replica. On CloudNativePG, `iptables` DROP rules on the primary's kind node block replica-to-primary traffic to port 5432 in both directions. Replicas stay up and their instance managers keep running.

The rate of gap formation is a scenario variable. In the slow cells the writer rate is derived from the target bytes, the measured WAL bytes per transaction and a 15 s growth time, so the gap forms over about 15 s (15.2 to 16.3 s on Patroni, 15.3 to 15.7 s on pg_auto_failover, 15.27 to 15.82 s on CloudNativePG). In the burst cells the writers run unthrottled after a random delay of 0 to 10 s before the stall (Patroni and pg_auto_failover) or at the rig's unthrottled rate from the moment of the stall (CloudNativePG). The burst gap formed in 0.4 to 0.7 s at 10 MiB on pg_auto_failover, 1.07 to 1.30 s at 10 MiB on CloudNativePG, and 1.9 to 4.6 s at 100 MiB on pg_auto_failover. The Patroni burst cell was designed for sub-second formation; its measured formation times over the 10 valid runs were 0.5 to 1.5 s.

### 3.3 Scenarios

| Scenario | Action | Patroni | pg_auto_failover | CloudNativePG |
|---|---|---|---|---|
| B | automatic failover, gap grows over about 15 s | yes | yes | yes |
| Bb | automatic failover, gap forms in seconds or less (supplementary) | yes (called Bjb), 10 MiB only | yes, 10 and 100 MiB | yes, 10 MiB only |
| C | operator-manual promotion of the named replica, primary gone | `patronictl failover --candidate X --force` | `pg_autoctl perform promotion --name X` | `kubectl cnpg promote pg X` |
| D | direct `pg_promote()` on the replica, primary gone | yes | yes | yes |
| E | replica's coordination path cut during the gap, restored, then manual promotion | DCS path cut | keeper-to-monitor path cut | not run |
| Ej | E with a random 0 to 10 s delay before the stall (supplementary) | yes | not run | not run |

For each cell the target gap is 10 MiB or 100 MiB, with 10 valid runs per cell. The fault is loss of the primary: SIGKILL of the primary's agent and postmaster together on Patroni and pg_auto_failover, and cordon plus force-deletion of the primary's pod on CloudNativePG. The stall stays in place during the fault.

E is not the same fault on all stacks. Patroni's E cuts the replica's path to etcd. pg_auto_failover's E cuts the keeper-to-monitor path, which is a weaker analogue because the monitor is not a separable coordination store. The cut was effective in all 40 valid E and Ea runs: the keeper logs show repeated monitor-connection timeouts during the cut. CloudNativePG has no E cell. Its coordination runs through the Kubernetes API rather than a separable store, and we did not construct an analogue that cuts the API path independently of replication; that is a scope limit of this study, not a claim that such a cut is impossible. Patroni's burst cell is labelled Bjb in the pilot data (burst, with a jittered pre-stall delay); the other stacks' equivalent burst cells are labelled Bb.

On CloudNativePG, `failoverDelay` was 0 for B and Bb, and 300 s for C and D so that the automatic path did not race the manual action. On Patroni, the timing and lag settings were the shipped defaults in every cell.

### 3.4 Workload and what counts as acknowledged

Four writer processes each issue one autocommit `INSERT` of an 8,000-byte `bytea` row per transaction. A transaction is acknowledged only when the writer's `COMMIT` returns, and its id is logged by the writer after that point. Loss is counted in acknowledged transactions. Because each transaction writes about 8.8 KB of WAL, transaction counts scale with that row size; 10 MiB of gap is about 1,190 transactions. MiB figures are comparable across systems, transaction counts depend on the row size.

### 3.5 Per-run verification of the gap

After the gap reaches its target the writers stop and the harness waits for them to exit. It then re-reads the primary's current WAL LSN and every replica's receive and replay LSNs. This reading is the verified gap and is taken a few tenths of a second before the fault. A run whose verified gap falls outside 0.75 to 1.25 of the target is invalid. In the slow cells the verified-to-target ratio was 1.000 to 1.003 in all valid Patroni and pg_auto_failover primary runs and 1.000 to 1.003 in the CloudNativePG slow cells; the burst cells ranged to 1.05 on CloudNativePG and to 1.17 on pg_auto_failover (11.68 MiB verified at the 10 MiB target).

After promotion the harness reads the promoted node's timeline history file. The fork LSN it records should equal the promoted node's verified receive LSN. It did in 88 of 90 promoted Patroni runs (one differed by 160 bytes, one was a burst run where a proxy buffer was still draining when the receive LSN was read), in 70 of 70 pg_auto_failover runs, and in 52 of 52 CloudNativePG runs for which it was read; 18 valid CloudNativePG runs have no fork LSN because an early version of the harness failed to read it (their loss counts are unaffected).

### 3.6 Recomputing loss

For every promoted valid run we store the acknowledged id list (`acked.txt`), the id list read from the promoted node at promotion (`surviving_at_promotion.txt`), their SHA-256 hashes, and the lost-id list. Loss is the number of acknowledged ids absent from the survivors. The analysis script recomputes this from the files and checks that the counts and hashes match the results CSV, and that the number of acknowledged ids equals the number of rows on the primary before the fault. The recount matched in all 90 promoted valid Patroni runs, all 70 promoted valid pg_auto_failover runs and all 70 promoted valid CloudNativePG runs.

### 3.7 Silent versus warned versus refused

Each run's command output and the stack's logs are searched with a fixed case-insensitive pattern for refusal and lag-related wording (terms include "lag", "behind", "refus", "warn", "data loss", "not eligible" and "exceeds maximum replication lag"; the exact per-stack patterns are part of the deposited harness, Section 7). A promotion with no match is "silent". Time to promotion is measured from fault injection to the first observation of the promoted node in the primary role (for the bypass cells, to the promoted node accepting writes); where the text quotes the return time of the `pg_promote()` call itself, that is measured from the call. A run in which no promotion occurs within the observation window (90 s for Patroni B, 150 s for pg_auto_failover, 300 s for CloudNativePG automatic cells) is "refused". "Silent" means no matching text in those two places. It does not exclude that a person reading the full logs would find a relevant line. Patroni's manual runs used `--force`, so its confirmation prompt was not exercised.

### 3.8 Validity and invalid runs

A run is valid only if the gap is within the ±25% window, the harness completed without exception, the evidence recounts, and the rig was healthy at the start (on CloudNativePG the harness also required both replicas to be streaming and in sync at stall start). Invalid runs are logged with their reasons and replaced; none was dropped. Patroni had 24 invalid of 134 attempts, pg_auto_failover 6 of 126, CloudNativePG 6 of 76 (plus 6 aborted partial runs with no result row). Section 4.6 lists the reasons.

### 3.9 Deviations, by stack

- **Patroni.** Replication goes through a proxy on the node's `connect_address`; the etcd client runs through a per-node proxy with `use_proxies: true` in the E, Ej and burst runs and in the final cluster builds, and ran without it in B, C and D (60 runs) where no DCS cut occurs. `use_pg_rewind` is on and `initdb` runs with data checksums. Runs reuse one cluster, rebuilt after each D run.
- **pg_auto_failover.** Nodes are created asynchronous (`--replication-quorum false`, `number-sync-standbys` 0), because at the shipped synchronous default the primary would block commits during a stall and no gap could form. The monitor's registered port for each node was edited by SQL so that standbys connect through the replication proxy; this is not a supported operation, and as a side effect the monitor's health checks to a node also pass through the proxy. A fresh rig is built for every run.
- **CloudNativePG.** Storage is a tmpfs mounted over the local-path provisioner on each worker, because the host's only disk is a 7200 rpm HDD that measured about 93 ms per `fsync` and capped four writers near 20 transactions per second. PostgreSQL parameters are defaults with `fsync` on. The cluster is reused across runs and rebuilt after each D run.

## 4. Results

### 4.1 Patroni 4.1.5

Source: the Patroni runs of this study, 110 valid runs (80 in the primary cells, 30 supplementary).

| Cell | Result | Silent | Acked txns lost per run | WAL lost (MiB) | Time to promotion (s, median) |
|---|---|---|---|---|---|
| B 10 | refused 10/10 | n/a | 0 | 0 | n/a |
| B 100 | refused 10/10 | n/a | 0 | 0 | n/a |
| Bjb 10 (burst, supplementary) | promoted 10/10 | yes | 1,160 to 1,307 | 10.06 to 10.99 | 25.65 |
| C 10 | promoted 10/10 | yes | 1,188 to 1,191 | 10.00 to 10.03 | 29.65 |
| C 100 | promoted 10/10 | yes | 11,881 to 11,898 | 100.06 to 100.20 | 29.45 |
| D 10 | promoted 10/10; node a replica again 15 s later in 10/10 | yes | 1,188 | 10.00 to 10.03 | 1.6 |
| D 100 | promoted 10/10; node a replica again 15 s later in 10/10 | yes | 11,876 to 11,893 | 100.04 to 100.16 | 1.6 |
| E 10 | promoted 10/10 | yes | 1,180 to 1,190 | 10.00 to 10.03 | 29.75 |
| E 100 | promoted 10/10 | yes | 11,877 to 11,897 | 100.02 to 100.19 | 29.3 |
| Ej 10 (phase-jittered, supplementary) | promoted 10/10 | yes | 1,180 to 1,188 | 10.00 to 10.03 | 25.85 |
| Ej 100 (phase-jittered, supplementary) | promoted 10/10 | yes | 11,875 to 11,897 | 100.01 to 100.21 | 26.0 |

In the B cells both replicas logged "My wal position exceeds maximum replication lag" every loop until the 90 s limit and neither promoted. The old primary's agent was then restarted and the final leader held every acknowledged write (zero lost in 20 of 20). The safeguard held only because the DCS leader position was recent enough to put the replicas more than 1 MiB behind it.

In the supplementary burst cell the same safeguard failed. All 10 runs promoted silently with 10.06 to 10.99 MiB lost. The mechanism was measured: the candidate's position was compared with the leader position last written to the DCS, and that value was 24 to 287 MiB older than the candidate's own, so the computed lag was negative (election view of -287.3 to -24.6 MiB, below the 1 MiB limit in 10 of 10 runs). In the slow B cells the same view was 6.3 to 60.7 MiB, above the limit in 20 of 20.

The manual path (C) promoted the named replica after the request was written to the DCS (`patronictl` could not reach the dead leader's REST API and fell back to the DCS) and the candidate promoted in 22.7 to 29.8 s, which we infer is the remaining life of the 30 s leader key. The topology table printed before the request shows the candidate's lag column (5 to 10 at 10 MiB, 54 to 96 at 100 MiB) with no gate or warning. This agrees with the source reading in Section 2.2: a named candidate returns true without a lag check [3]. E behaved like C. Its DCS cut was effective (1 to 5 DCS errors in the candidate agent's log during the cut in all valid E and Ej runs), but a stalled receiver freezes the candidate's published position at the same point as its true position, so the DCS view and the promotion are essentially C's.

The bypass (D) returned in 1.6 s with the full loss. Patroni demoted the node again about 2 s later in the run read in detail, and the node reported role replica 15 s later in 20 of 20 runs while the dead primary's leader key was still held. We did not test the bypass after the leader key has expired.

### 4.2 pg_auto_failover 2.2

Source: 120 valid runs (80 in the primary cells, 40 supplementary) from 126 attempts. The monitor's gate is `pgautofailover.promote_wal_log_threshold`, 16 MiB (16,777,216 bytes) as read from the running monitor; it compares the last-reported LSNs of the most advanced standby and the primary. The 10 MiB cells are below the threshold by construction, so they show what passes the gate rather than test it.

| Cell | Result | Silent | Acked txns lost per run | Verified gap (MiB, min to max) | Time to promotion (s, median) |
|---|---|---|---|---|---|
| B 10 | promoted 10/10 | yes | 1,188 | 10.00 to 10.03 | 23.6 |
| B 100 | refused 10/10 | n/a | 0 | 100.03 to 100.17 | n/a |
| Bb 10 (supplementary) | promoted 10/10 | yes | 1,192 to 1,386 | 10.04 to 11.68 | 33.1 |
| Bb 100 (supplementary) | refused 10/10 | n/a | 0 | 100.11 to 101.87 | n/a |
| C 10 | promoted 10/10 | yes | 1,188 | 10.00 to 10.03 | 54.6 |
| C 100 | refused 10/10 (exit 12 after 60 s) | refusal reason not in CLI output | 0 | 100.01 to 100.20 | n/a |
| D 10 | promoted 10/10; monitor ratified the node in 10/10 | yes | 1,188 | 10.00 to 10.03 | 1.5 |
| D 100 | promoted 10/10; keeper returned the node to recovery within 60 s in 10/10 | yes | 11,879 to 11,899 | 100.04 to 100.21 | 1.5 |
| E 10 | promoted 10/10 | yes | 1,188 | 10.00 to 10.03 | 54.5 |
| E 100 | refused 10/10 (exit 12 after 60 s) | n/a | 0 | 100.02 to 100.19 | n/a |
| Ea 10 (E cut, automatic path; supplementary) | promoted 10/10 | yes | 1,188 | 10.00 to 10.03 | 23.2 |
| Ea 100 (supplementary) | refused 10/10 | n/a | 0 | 100.01 to 100.17 | n/a |

The gate applied uniformly to the automatic path (B) and to the operator path (C, E): 30 of 30 runs at 100 MiB across B, C and E were refused with zero acknowledged loss because the old primary was never replaced. This is the evidence for the gate. Separately, 30 of 30 runs at 10 MiB across B, C and E promoted silently and lost every unshipped transaction (1,188 per run); that shows what passes below the threshold and does not test it. The 16 MiB value itself is established by the monitor reading and the source, with the data bracketing it between 10 and 100 MiB. The comparison is between the most advanced standby and the primary, not the named candidate, so with `--name X` the refusal depends on the other standby's reported position, and the group had three data nodes. Every refusal produced the same line in the monitor log, repeated 240 to 251 times in a refused E run, naming the threshold and the two reported LSNs. The refused `perform promotion` printed the nodes moving to `report_lsn` and staying there, waited its 60 s and exited with status 12 ("Failed to wait until a new primary has been notified"), with no lag text in the command output (checked by regular expression in 20 of 20 refused C and E runs). A person who does not read the monitor log sees a hung failover.

The bypass was not gated: `pg_promote()` promoted in 1.5 s in 20 of 20 runs. What the stack did afterwards depended on the gap. At 10 MiB the monitor ended up ratifying the bypassed node as primary in 10 of 10 runs, keeping the full loss. At 100 MiB the node's keeper put it back into recovery within 60 s in 10 of 10 runs and no node reached primary state; the old primary showed as draining and the standbys sat in `report_lsn`; we observed only the state at 60 s.

The supplementary burst variant did not defeat the gate in what we could build. At 10 MiB the gap formed in 0.4 to 0.7 s, but that is under the 16 MiB threshold, so promotion is allowed anyway. At 100 MiB the fastest burst took 1.9 s (1.9 to 4.6 s over the cell), with the monitor-reported lag at least 72.5 MiB, so the gate refused 10 of 10. Whether a gap of more than 16 MiB formed in less than the reporting interval can pass the gate is open: we neither replicated nor refuted the Patroni burst result here.

### 4.3 CloudNativePG 1.30.2 (PostgreSQL 17.11)

Source: 70 valid runs from 76 attempts. No lag gate showed on any measured path.

| Cell | Result | Silent | Acked txns lost per run | Verified gap (MiB, min to max) | Time to promotion (s, median) |
|---|---|---|---|---|---|
| B 10 | promoted 10/10 | yes | 1,152 to 1,180 | 10.00 to 10.03 | 5.0 |
| B 100 | promoted 10/10 | yes | 11,763 to 11,778 | 100.02 to 100.14 | 5.4 |
| Bb 10 (supplementary) | promoted 10/10 | yes | 1,181 to 1,236 | 10.04 to 10.50 | 22.8 |
| C 10 | promoted 10/10 | yes | 1,176 to 1,181 | 10.00 to 10.03 | 6.1 |
| C 100 | promoted 10/10 | yes | 11,759 to 11,776 | 100.01 to 100.13 | 6.2 |
| D 10 | promoted 10/10; node stopped by the instance manager 10/10 | yes | 1,152 to 1,178 | 10.00 to 10.02 | 4.9 |
| D 100 | promoted 10/10; node stopped by the instance manager 10/10 | yes | 11,736 to 11,773 | 100.00 to 100.19 | 4.8 |

The burst cell's longer time to promotion (median 22.8 s against 5.0 s for B 10) was not investigated.

On the automatic path the operator promoted the replica with the smaller verified gap in 10 of 10 runs in each of B 10, B 100 and Bb 10; the two replicas differed by 0.09 to 3.25 MiB. The operator therefore chooses between candidates by position, but nothing bounded how far behind the better one was. In 100 MiB runs of B it promoted a replica that was missing about 100 MiB and lost 11,763 to 11,778 acknowledged transactions with no refusal. This is the result that most separates CloudNativePG from the other two stacks: at 100 MiB, Patroni's automatic path refused 10 of 10, pg_auto_failover's refused 10 of 10, and CloudNativePG's promoted 10 of 10.

The operator-manual path was no different. `kubectl cnpg promote pg X` returned a single line, "Node pg-3 in cluster pg will be promoted", plus an informational log line, and the promotion completed in 5.7 to 7.6 s at 100 MiB. Nothing in the output or in the operator log was lag-related by the regular expression, in any of the 70 runs.

For the bypass, `pg_promote()` returned true in under a second and the candidate accepted writes. (The table's time to promotion runs from fault injection, Section 3.7, and so includes the harness steps before the call.) In 20 of 20 runs the harness then lost contact with the candidate for the whole 30-poll observation (about 68 s): every one of the 600 polls was a connection error, and the first came 5.6 to 7.4 s after the fault at 10 MiB and 5.7 to 6.5 s at 100 MiB. The candidate pod's restart count was 1 in 20 of 20 runs. In all 20 valid D runs the stored previous-container log of the promoted pod contains "Old primary shutdown complete"; the instance-manager log we read in full also shows "postmaster exited" and "server stopped", while the cluster status still named the deleted pod as primary. The label `demoted_after` in the results file is set from these connection errors, not from observing the node re-enter recovery, so what the data show is that the operator stopped the node, not that it became a replica.

### 4.4 Cross-stack matrix

Each cell is the promotion result over 10 valid runs; loss is acknowledged transactions per run (min to max). "Silent" is as defined in Section 3.7.

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

Notes on equivalence between the columns:

- (a) CloudNativePG C and D ran with `failoverDelay` 300 s; B and Bb ran with 0.
- (b) The burst constructions differ per stack: a random unthrottled pre-stall delay on Patroni and pg_auto_failover, a raised writer rate at the stall on CloudNativePG. Formation times were 0.5 to 1.5 s, 0.4 to 0.7 s and 1.07 to 1.30 s respectively.
- (c) The stacks' harnesses and faults differ (Section 3.9).

Read by row, the three stacks give three answers. Patroni, with the leader gone and a named candidate, has no gate on its manual path, and a gate on its automatic path that a fast-forming gap defeated through a stale stored leader position (Section 5.2). pg_auto_failover has one gate, on last-reported LSNs, applied to both the automatic and the operator path and absent on the bypass. CloudNativePG showed no gate on any measured path. The 10 MiB cells of pg_auto_failover pass its gate by construction and should not be read as the absence of a gate.

Totals: 110 valid Patroni runs, 120 valid pg_auto_failover runs and 70 valid CloudNativePG runs, 300 in all.

### 4.5 Reported lag versus true lag at decision time

Each stack shows or uses a lag figure when the decision is made. We compared it with the LSN-verified gap.

| Stack | Figure | Source of figure | Median absolute error vs verified gap (MiB) | Notes |
|---|---|---|---|---|
| Patroni | DCS view (what `patronictl list` shows) | leader position in the DCS minus the member's published position, read 0.4 s after the kill | B 10: 3.7; B 100: 46.7; C: 0.4 and 5.4; D: 4.4 and 45.7; E: 0.4 and 5.8; Bjb 10 (supplementary): 11.0 | primary E error at least 10 MiB in 0/10 (10 MiB) and 3/10 (100 MiB) |
| Patroni | phase-jittered E (Ej, supplementary) | same | 2.9 (10 MiB), 24.1 (100 MiB) | error at least 10 MiB in 0/10 (10 MiB) and **7/10 (100 MiB)** |
| pg_auto_failover | monitor-reported lag | difference of last-reported LSNs, read 0.4 s after the kill | slow cells 0.03 to 0.54 (10 MiB) and 2.3 to 2.8 (100 MiB); supplementary burst cells 5.1 (Bb 10) and 7.3 (Bb 100) | burst maximum 24.6 (Bb 10) and 29.2 (Bb 100); four negative readings in the Bb 10 cell (-3.4, -5.7, -9.7 and -14.1 MiB) |
| CloudNativePG | `kubectl cnpg status` Current LSN | each instance's own position | 0.00 | not a staleness test (read live, writers stopped); 0-byte error in 70/70 runs; read before the fault with writers stopped |

The Patroni figure in this table is the operator-visible DCS view: the stored leader position minus the member's published position. It is not the election computation of Section 4.1, which subtracts the candidate's live received LSN from the same stored leader position. In the burst cell the member's published position had frozen with the stall, so the staleness of the two published positions largely cancels in the displayed view (median error 11.0 MiB), while the election view went negative (-287.3 to -24.6 MiB) because the candidate's live position had run ahead of the stored leader position during the unthrottled pre-stall interval. For Patroni the error in either view depends on where the fault falls in the leader's control loop. At 100 MiB, with a true gap of 100.1 MiB, the median DCS view was 94.7 (C) and 94.3 (E), but 54.4 (D) and 53.4 (B). The primary runs repeat on a fixed cycle of about 60 s, so part of that spread is phase locking to the 10 s loop; the supplementary jittered E cell, with a random delay before the stall, shows the error at least 10 MiB in 7 of 10 runs at 100 MiB. For pg_auto_failover the error was small for slowly growing gaps (the primary's report is at most about one keeper cycle old) and larger in bursts. In every refused cell the reported lag stayed above 16 MiB (lowest 72.5 MiB, in Bb 100), so the staleness never flipped a decision. The Patroni DCS view is frozen once the leader is dead, so the 0.4 s reading is the value the decision used; for pg_auto_failover the gate's own refusal log lines were also checked (smallest evaluated gap 72.5 MiB).

For CloudNativePG the operator's own figure was exact in the readings we took, but those were taken with writers stopped and before the fault, so the comparison does not test staleness under load. At decision time the primary is gone, and the operator has no primary position to compute lag against: in the status output captured about 3 s after the fault, the streaming replication section read "Not available" in 8 of 10 B 10 runs and 5 of 10 B 100 runs, and in none of the Bb, C or D runs.

### 4.6 Invalid runs and harness flaws

| Stack | Invalid / attempts | Reasons |
|---|---|---|
| Patroni | 24 / 134 | 20 E runs where the etcd client discovered etcd's real address and bypassed the proxy, so the "cut" was ineffective (fixed with `use_proxies: true`, E re-run from scratch); 1 Ej run contaminated by orphan writer processes (primary held 1,956 rows against 964 acknowledged, caught by the row-count check); 2 burst runs outside the gap window (17.8 and 43.4 MiB against 10.0); 1 burst run with no space left on the device |
| pg_auto_failover | 6 / 126 | 5 E runs where cluster build failed with `could not create semaphores: No space left on device` (macOS SysV semaphore pool exhausted by leaked sets from killed postmasters; fixed by reaping orphans); 1 C run where `perform promotion` hit a monitor deadlock and never requested the promotion |
| CloudNativePG | 6 / 76, plus 6 aborted partial runs | 2 rig exceptions (table already existed); 3 runs where the operator shut the promoted candidate down within about 4 s, before survivors could be read; 1 run where a replica was not streaming at stall start. All six are in D 10 |

Two further flaws are disclosed. On pg_auto_failover, our first 20 E runs never issued the promotion command and so measured automatic failover with the cut; we relabelled them Ea, kept them as supplementary, and re-ran true E. The first Patroni E attempts, whose cut was ineffective (the 20 invalid runs above), likewise promoted silently with the loss of C and are effectively extra C runs. On CloudNativePG, the harness fix that allowed survivors to be read before the operator stopped a bypass-promoted node was introduced at the boundary between C 100 and D; D runs use the fixed harness, B, Bb and C ran under the earlier one.

## 5. Discussion

### 5.1 What a lag setting does and does not buy

The common reading of `maximum_lag_on_failover` is that it bounds acknowledged loss on failover. Our Patroni results support a narrower statement. The setting bounded loss on the automatic path when the leader's published position was recent enough, and it was not consulted when an operator named a candidate with the leader gone. The documentation's own wording is consistent with this: the setting governs which followers may "participate in leader election", the worst case is bounded "plus the amount that is written in the last `ttl` seconds", and the primary's position "is not sampled in real time" [2]. Our source reading shows the second half of that sentence is not hypothetical, because the leader position is written once per loop and the check uses the last written value [3].

For pg_auto_failover the threshold applies to both paths, which makes the operator's choice of command irrelevant to the outcome in our runs, where both standbys were stalled together and the two targets bracket the threshold; the region between 16 and 100 MiB was not tested (Section 6). The consequence is a cliff rather than a graded bound: a 10 MiB gap and a 100 MiB gap were treated oppositely, and below the threshold the stack promoted silently and lost the whole gap. We did not test gaps between 16 and 100 MiB.

For CloudNativePG, we found no lag-based gate. The behaviour is consistent with the documentation, which says some data loss is expected and accepted when synchronous replication is not enabled and describes the optional readiness-probe setting separately [5]. The surprise is only for an operator who assumed a lag-based safeguard from the other stacks. The loss we measured equals the unshipped gap.

### 5.2 The hidden parameter: how often the reference position is published

The automatic safeguards in Patroni and in pg_auto_failover compare the candidate with the primary's last published or reported position, not with the primary's actual position at the instant it fails. Once the primary is dead there is no other source, so a lag decision in these designs necessarily compares against a position that was recorded earlier. How much earlier is set by the publication interval, which Patroni ties to its 10 s `loop_wait`, and the writing rate during that interval. Patroni's documentation states its worst-case bound in terms of `ttl` and gives `loop_wait`/2 seconds as the average-case figure [2]. In Patroni's supplementary burst cell the writers were unthrottled and the recorded position was 24 to 287 MiB older than the candidate's own, and the safeguard passed in 10 of 10 runs. A gap of the same size built slowly at the same write rate would pass the check in the same way, and no cell in this study separates formation time from write volume during the publication interval. The same structural staleness is present in pg_auto_failover (reported-minus-true errors up to 29.2 MiB and four negative values, all in the 10 MiB burst cell), but at the rates we could generate it never moved a decision across the 16 MiB line. Because the comparison uses the absolute difference of the two reported positions, the same staleness could in principle produce the opposite error, a spurious refusal of a candidate whose true gap is within the threshold; we did not observe one. A burst that outruns the reporting interval while building more than 16 MiB of gap was not producible on our host; this is the main open item for that stack.

### 5.3 Operator display lag and the refusal experience

The lag shown to an operator is itself a lagging indicator. Patroni's topology table showed a lag column with no gate, and the figure was off by at least 10 MiB in 7 of 10 supplementary phase-jittered runs at 100 MiB. An operator who decides on the strength of that column is working from a number whose error depends on the phase of the control loop at the moment of failure.

When a stack does refuse, the operator may not learn why. pg_auto_failover's refused `perform promotion` ended after 60 s with exit status 12 and no explanation, and the reason was repeated 240 to 251 times in a monitor log the operator may not be reading. Patroni's automatic refusals appear as a repeated line in the replicas' logs. CloudNativePG's silent promotions give the operator no indication of how much was lost. We did not test the stacks' alerting or metrics, which might surface more.

### 5.4 The bypass

Direct `pg_promote()` shows what each stack does with a promotion it did not authorise. Patroni demoted the node again (about 2 s after the promote in the run read in detail, and the node was a replica again 15 s later in 20 of 20 runs) while the dead primary still held the DCS leader key; CloudNativePG's instance manager stopped the pod within about five seconds; pg_auto_failover's outcome depended on the gap, ratifying the node at 10 MiB and putting it back into recovery at 100 MiB. In every case the call itself succeeded in a second or less, the node accepted writes during that window, and every transaction acknowledged by the original primary but not received by the candidate was absent. None of this measures what a client wrote to the bypassed node in that window; our writers had stopped before the fault.

### 5.5 The baseline contrast

The author's earlier study killed the primary process under a write load with replication lag close to zero and found that PostgreSQL with Patroni at defaults lost one acknowledged transaction in each of 2 of 30 runs, out of 270,676 acknowledged writes [1]. Here, with a gap of 10 or 100 MiB, every run that promoted lost 1,152 to 1,386 acknowledged transactions at the 10 MiB target and 11,736 to 11,899 at the 100 MiB target. The two studies used different faults, loads and Patroni cells, so the comparison is a scale contrast and not a like-for-like measurement.

### 5.6 What this study does not claim

We do not rank the three tools. Patroni, pg_auto_failover and CloudNativePG differ in their promotion architectures: a DCS-backed agent per node, a separate monitor, and a Kubernetes operator. The matrix compares behaviour at the same measured gap. An absence of a gate in these runs is not evidence that the software has none under other configurations, for example synchronous replication, the optional CloudNativePG readiness probe, or a changed pg_auto_failover threshold, none of which we ran. CloudNativePG's quorum-based failover was not enabled; its documented statement that some data loss is expected and accepted appears in that feature's section [5]. All three stacks were measured at their shipped defaults, with one exception: pg_auto_failover's replication mode was set asynchronous, because its synchronous default blocks writers under a stall and the condition under test cannot arise. That default is itself a protection, and it is reported here rather than treated as a defect; CloudNativePG's optional probe was likewise left at its default, off.

## 6. Threats to validity

- **One host per stack.** Patroni and pg_auto_failover ran on the same Mac; CloudNativePG ran on a different machine in WSL2 under kind. Replication and coordination traffic never left the host. No real network faults were injected; the lag is created by stalling a proxy or dropping packets on the primary's node.
- **Loopback and WSL2 networking.** The behaviour of timeouts and connection teardown on a real network may differ.
- **Asynchronous replication only.** pg_auto_failover is asynchronous by our configuration choice; its shipped default is synchronous, under which a stall would block writers and no gap would form. We ran no default-sync cell on any stack.
- **One version per stack.** Patroni 4.1.5, pg_auto_failover 2.2, CloudNativePG 1.30.2. PostgreSQL 17.12 on the Mac and 17.11 in the CloudNativePG image.
- **CloudNativePG storage is tmpfs**, with PostgreSQL defaults and `fsync` on. The admission measurement does not depend on the medium: the gap is created by dropping replication traffic, so its size is the WAL written during the stall, verified by LSN in every run; storage speed can affect the write rate, which is measured, not assumed. Post-promotion behaviour and recovery timing may well differ on durable storage, and we did not test on it.
- **Gaps between 16 and 100 MiB were not tested on pg_auto_failover**, so the point at which its gate switches is known only to lie between our two targets and at 16 MiB by configuration. Gaps that form in under one second at 100 MiB were not produced on any stack; the fastest on pg_auto_failover was 1.9 s, and CloudNativePG's burst cell reached only 10 MiB, in 1.07 to 1.30 s.
- **The pg_auto_failover registered ports were edited by SQL**, which is unsupported, and the monitor's health checks pass through the replication proxy. Routing the health checks through the proxy may also have affected failure-detection timing during a stall; we did not isolate that effect.
- **Patroni runs are phase-locked.** Back-to-back runs repeat on a roughly 60 s cycle, which partly determines the DCS-view error in the primary cells. The jittered E cell was added to show how much.
- **Fault type.** Loss of the primary's agent and postmaster together (Patroni, pg_auto_failover) or of its pod and node (CloudNativePG). We did not test killing only the postmaster.
- **Row size.** Transactions are 8,000-byte rows; transaction counts scale with that and are not typical of OLTP.
- **"Silent" is a regular-expression result** over command output and logs, not a reading of every log line. Patroni's manual runs used `--force`.
- **Time to promotion** includes control-loop waits and, on Patroni, a 30 s leader-key lifetime that we infer but did not isolate. It is not comparable across stacks as a detection speed: the faults differ (a process kill against pod deletion on a single host), and real node-loss detection, for example Kubernetes node-lease expiry, is slower than anything measured here.
- **Patroni E, pg_auto_failover E and CloudNativePG E are not the same fault**, and CloudNativePG has no E cell.
- **The bypass observation windows were short**: 15 s on Patroni, 60 s on pg_auto_failover, about 68 s on CloudNativePG. We did not follow any cluster to a final state after a bypass, and we did not test the Patroni bypass after the dead primary's leader key had expired.

## 7. Artefact availability

The study's artefacts are the three stacks' folders as deposited with this record; the file sets differ by stack where listed below.

- **Harness.** The scripts that build the rig, stall and release replication, run the writers, verify the gap, inject the fault, trigger the promotion path, collect evidence and recompute loss. Patroni and pg_auto_failover: `cluster-up.sh`, `cluster-down.sh`, `tcpproxy.py`, `writer.py`, `harness.py`, `driver.py`, `analyze.py`, and for pg_auto_failover `reap-ipc.py`. CloudNativePG: `harness.py`, `driver.py`, `lib.py`, `writer.py`, `analyze.py`, `pg.yaml` and `kind.yaml`.
- **Results CSVs.** One row per attempt, including invalid runs and their reasons: 134 rows for Patroni, 126 for pg_auto_failover and 76 for CloudNativePG, with the SHA-256 of each stored list.
- **Per-run data.** For every run: an event log with timestamps; each writer's acknowledged-id log; the acknowledged list, the surviving list at promotion and the lost-id list; the timeline history from the promoted node; the stack's own view at decision time (DCS snapshot for Patroni, monitor row for pg_auto_failover, `kubectl cnpg status` for CloudNativePG); and the relevant stack and operator logs.
- **Generated tables.** `analyze.py` regenerates the per-cell tables, the denominators, the invalid-run list and the recount from the stored files without re-running anything.
- **Setup notes.** Rig descriptions, versions as read from the running systems and all deviations.

The harness, data and CSVs are deposited with this record (DOI: 10.5281/zenodo.24466483) and mirrored at https://github.com/Sajish85/what-promotion-admits. The deposit contains the files listed above; credentials and host-specific identifiers were removed before deposit.

## References

[1] S. Krishnan. *Client-Observed Write Unavailability After a Primary Process Kill: Five Replicated Database Systems at Shipped Settings on a Single Host.* 2026. Zenodo. DOI: 10.5281/zenodo.24359723.

[2] Patroni documentation: dynamic configuration settings (`https://patroni.readthedocs.io/en/latest/dynamic_configuration.html`), replication modes (`https://patroni.readthedocs.io/en/latest/replication_modes.html`) and `patronictl` (`https://patroni.readthedocs.io/en/latest/patronictl.html`). The quoted wording is the same in the repository documentation at tag v4.1.5 (`https://github.com/patroni/patroni`): `docs/dynamic_configuration.rst`, `docs/replication_modes.rst` and `docs/patronictl.rst`. Accessed 23 November 2026.

[3] Patroni 4.1.5 source, `patroni/ha.py` (`is_lagging`, `_is_healthiest_node`, `is_failover_possible`, `manual_failover_process_no_leader`, `update_leader` call) and `patroni/api.py` (`is_failover_possible`), read from the installed 4.1.5 package.

[4] pg_auto_failover v2.2: documentation `docs/failover-state-machine.rst` and `docs/ref/pg_autoctl_perform_promotion.rst`, and source `src/monitor/group_state_machine.c`, `src/monitor/node_active_protocol.c` and `src/monitor/pg_auto_failover.c`, `https://github.com/hapostgres/pg_auto_failover` (tag v2.2). Accessed 23 November 2026.

[5] CloudNativePG v1.30.2 documentation sources `docs/src/failover.md`, `docs/src/instance_manager.md`, `docs/src/replication.md`, `docs/src/kubectl-plugin.md` and `docs/src/rolling_update.md`, `https://github.com/cloudnative-pg/cloudnative-pg` (tag v1.30.2). Accessed 23 November 2026.
