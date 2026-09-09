#!/usr/bin/env python3
"""
Close out runs whose process is gone.

    python3 scripts/reap_runs.py               show what it would do
    python3 scripts/reap_runs.py --apply       do it
    python3 scripts/reap_runs.py --grace 20    wait 20 minutes, not 10

Needs scripts/run_liveness.py.

── WHY ──────────────────────────────────────────────────────────────────────

patch_run_status made a run record its own terminal status: a node that fails
now writes 'failed', and __main__ writes it when the process dies of an
exception. Both need the process to still be alive to write anything.

kill -9, a power cut, the Mac restarting, launchd stopping the world — none
of those get to write, and the row keeps saying 'running' forever. That
happened on 8 September to ducorn-admin-rebuild-p1-config, and the row sat
wrong for twenty minutes until someone asked why the epic would not restart.

A stuck row is not cosmetic:

  · the dashboard shows a live run that does not exist
  · /pipeline/start refuses that slug — "already running"
  · an epic will not restart the phase, because it looks in flight
  · the run is never attributed a final cost

── THE RULE ─────────────────────────────────────────────────────────────────

A run is reaped when ALL of these hold:

    status is created, started or running
    no process has its slug as an argument
    the row has not been touched for GRACE minutes

Each clause is doing work:

  STATUS   awaiting_approval is NOT reaped. A run parked at a gate has
           deliberately exited — no process is the CORRECT state for it, and
           reaping it would destroy an approval you are about to give.
           needs_intervention is not reaped either: it is waiting for a
           person, and turning it into 'failed' loses that.

  PROCESS  asked through run_liveness, which is the same matcher
           /pipeline/kill uses. Whole-argument, so 'ducorn-spend-status' does
           not match '-web'.

  GRACE    start_next writes the row and THEN launches. Between those two
           moments a run is legitimately rowed and processless, and a reaper
           with no grace period would kill it in the cradle.

── WHAT IT WRITES ───────────────────────────────────────────────────────────

status = 'failed', and error_message says why and since when. A state change
nobody can see is its own bug: the reason belongs where you already look,
which is the run's own row on the dashboard, not in a log for this script.

The UPDATE re-checks the status it expects. Between reading and writing, a
run can reach a gate — and reaping a run that just started waiting for your
approval would be worse than the ghost it was cleaning up.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
sys.path.insert(0, str(DC / "scripts"))

# Reaped only from these. See the module docstring for why the two
# person-waiting states are absent — it is the whole safety of this script.
REAPABLE = ("created", "started", "running")


def find(grace_min: int):
    """Candidates: rowed as running, no process, and stale. No writes."""
    import run_liveness

    from ducorn_db import get_conn
    with get_conn() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT slug, status, updated_at,
                      EXTRACT(EPOCH FROM (now() - updated_at)) / 60
                 FROM pipeline_runs
                WHERE status = ANY(%s)
                  AND updated_at < now() - (%s || ' minutes')::interval
             ORDER BY updated_at""",
            (list(REAPABLE), str(int(grace_min))))
        rows = [(r[0], r[1], r[2], float(r[3])) for r in cur.fetchall()]

    if not rows:
        return []

    # ONE process listing for every candidate. Per-row pgrep would answer
    # different questions at different moments.
    procs = run_liveness.snapshot()
    alive = run_liveness.live({r[0] for r in rows}, procs)
    return [r for r in rows if r[0] not in alive]


def reap(rows) -> list:
    """Mark them failed. Returns the slugs actually changed."""
    from ducorn_db import get_conn
    done = []
    with get_conn() as c:
        cur = c.cursor()
        for slug, status, updated, mins in rows:
            reason = (f"No process for this run and the row had not moved for "
                      f"{int(mins)} minutes (last {updated:%Y-%m-%d %H:%M}). "
                      f"Marked failed by reap_runs at "
                      f"{datetime.now():%Y-%m-%d %H:%M}.")
            # The status is re-checked HERE, not trusted from the read above.
            # A run can reach a gate between the two, and reaping a run that
            # has just started waiting for an approval is worse than the ghost
            # this is cleaning up.
            cur.execute(
                """UPDATE pipeline_runs
                      SET status = 'failed', error_message = %s,
                          updated_at = now()
                    WHERE slug = %s AND status = ANY(%s)""",
                (reason, slug, list(REAPABLE)))
            if cur.rowcount:
                done.append(slug)
        c.commit()
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--grace", type=int, default=10,
                    help="minutes a row may sit untouched before it counts "
                         "as abandoned (default 10)")
    a = ap.parse_args()

    try:
        rows = find(a.grace)
    except Exception as e:
        # Loud, and NOT a reap. A reaper that cannot list processes must do
        # nothing at all — reading a failed listing as "nothing is running"
        # would mark every live run failed.
        print(f"reap_runs: could not look — {type(e).__name__}: {e}")
        return 1

    stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    if not rows:
        print(f"[{stamp}] nothing to reap "
              f"(grace {a.grace}m, statuses {', '.join(REAPABLE)})")
        return 0

    print(f"[{stamp}] {len(rows)} run(s) with no process:")
    for slug, status, updated, mins in rows:
        print(f"    {slug}  [{status}]  idle {int(mins)}m  "
              f"last {updated:%Y-%m-%d %H:%M}")

    if not a.apply:
        print("\nNothing written. Re-run with --apply.")
        return 0

    done = reap(rows)
    for slug in done:
        print(f"  reaped {slug} → failed")
    skipped = [r[0] for r in rows if r[0] not in done]
    for slug in skipped:
        # Not an error: it means the run moved on while we were looking, which
        # is exactly what the re-check is for.
        print(f"  left {slug} — its status changed while this ran")
    return 0


if __name__ == "__main__":
    try:
        from bootstrap_python import ensure_modules
        ensure_modules("psycopg2")
    except ImportError:
        pass
    sys.exit(main())
