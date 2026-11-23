# SETUP: inventory for the Failover Gate full study (2026-11-22)

## Summary
- **CloudNativePG: STOPPED. Cannot run on this Mac.** No Kubernetes cluster, and the only possible host (Docker Desktop) has a dead daemon. Nothing substituted.
- **pg_auto_failover: can run.** Not installed anywhere; built from source (v2.2) against the PG 17 in `~/tools/pg/17`. Binary works (`pg_autoctl --version` below).

## Evidence (commands run in this session)
| Check | Result |
|---|---|
| `which docker kind k3d minikube kubectl helm colima podman orb` | none on PATH |
| `/Applications/Docker.app` | present. Its `Contents/Resources/bin` holds `docker` and `kubectl` only (no kind, k3d, minikube, helm). |
| Docker daemon | `~/.docker/run/docker.sock` exists, dated Nov 19 22:29. `docker info`, `docker version`, `docker ps` each hung past 15 to 60 s and never returned (the shell moved them to background). A Docker Desktop process runs from an AppTranslocation path. Daemon: **unresponsive**. |
| Kubernetes | none. `kubectl` needs a cluster; kind/k3d/minikube are absent and would need a working Docker daemon. |
| Disk | `df /`: 10 GiB free at start (228 GiB volume, 65%). A kind cluster plus CNPG images would not fit comfortably, which is a second reason, not the main one. |
| `brew search pg_auto_failover` | no formula |
| GitHub release API | `hapostgres/pg_auto_failover` latest = **v2.2** (published 2025-04-03) |

Smallest next step to unblock CNPG (not done, outside this brief): get Docker Desktop to start with a responsive daemon (restart the app), install kind and helm, free about 10 GB. I did not restart Docker Desktop: it is a GUI app with unknown state, and substituting a different experiment is barred.

## pg_auto_failover build (labelled)
- Source: `https://github.com/hapostgres/pg_auto_failover/archive/refs/tags/v2.2.tar.gz`, unpacked in `src/pgaf/`.
- Built with the system clang against `~/tools/pg/17` (PostgreSQL 17.12, Postgres.app build, universal binary). Homebrew openssl and readline include paths added.
- The binary linked to a non-existent Postgres.app path for libpq; fixed with `install_name_tool -change` to `~/tools/pg/17/lib/libpq.5.dylib`. Result: `bin/pg_autoctl`.
- Deviation: the monitor extension (`pgautofailover.dylib`, control, SQL files) was copied into `~/tools/pg/17/lib/postgresql` and `share/postgresql/extension` (added files only; nothing existing changed). The pilot's PG 17 toolchain dir is shared, but `pilots/failover-gate/` itself is untouched.
- `bin/pg_autoctl --version`: `pg_autoctl extension version 2.2`, compiled with PostgreSQL 17.12, "compatible with Postgres 13, 14, 15, 16 and 17".

## Not touched
`~/postgres-failover-lab`, `patent-chaos`, `range-syndrome`, `pilots/failover-gate/`, the Windows rig.

## Addendum (later in the session)
- The `docker version`, `docker ps`, `docker info` calls I backgrounded were still hung when the harness killed them at its 10-minute limit. This confirms the daemon never answered.
- PG 17 binaries used are `~/tools/pg/17` (the pilot's toolchain): `postgres (PostgreSQL) 17.12 (Postgres.app)`. macOS 15.5, arm64 (`sw_vers`, `uname -m`).
- Host kernel limits hit during the study (see pg-auto-failover-report.md, Deviations): `kern.sysv.shmmni=32` and the SysV semaphore pool (`semmns` 87381) were exhausted by sets leaked from SIGKILLed postmasters (mine and older ones). I reaped only orphaned segments/sets (no live owner, and for semaphores no key match to any live postmaster data directory). Other projects' four live clusters were checked afterwards and still answered.
