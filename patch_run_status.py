#!/usr/bin/env python3
"""
A failed run leaves pipeline_runs saying 'running' — forever.

    cd ~/DC && python3 scripts/patch_run_status.py            show
    cd ~/DC && python3 scripts/patch_run_status.py --apply    do it

Needs scripts/patchlib.py.

── HOW IT SURFACED ──────────────────────────────────────────────────────────

    NOTHING STARTED — phase 1 (Configuration) is already running as
    'ducorn-admin-rebuild-p1-config'.

It is not running. It died at the research node twenty minutes earlier. The
epic asked the database, and the database still said running.

── THE CAUSE ────────────────────────────────────────────────────────────────

node_research ends with

    return {**state, "status": "failed", "error": ...}

which is the GRAPH's status. The row is a separate act, and only two nodes of
eleven perform it — the skill runner (line ~1216) and qa (~1399) call
_update_db_status(topic, "failed"). Every other node returns failed and
writes nothing, so the last write to the row is the "running" that the node
set on entry.

That is the same shape as the bugs this session has been about: one fact kept
in two places, where only some of the writers know about the second.

What it costs, once a row is stuck:

  · the dashboard shows a live run that does not exist
  · /pipeline/start refuses the slug — "already running"
  · an epic refuses to restart the phase, because it looks in flight
  · the budget attributes nothing to it, because nothing closed it

── THE FIX ──────────────────────────────────────────────────────────────────

_stream_until_pause is the ONE place that observes every node's terminal
status — it already prints it. It now records it. No node has to remember,
and a node that forgets cannot leave a stuck row.

The write passes no phase argument on purpose. The RUN's status is this
loop's fact; the SKILL's status stays the node's. One writer per fact.

A process that dies of an unhandled exception never reaches the loop either,
so __main__ marks the run failed on the way out. Not a duplicate of the loop:
different failure, and the loop cannot see it.

── WHAT THIS DOES NOT FIX ───────────────────────────────────────────────────

kill -9, a power cut, or the Mac restarting mid-run still leave a row saying
running, because nothing gets to write anything. That needs a reaper — a run
whose pid is gone and whose row has not moved in N minutes is not running —
and a reaper is a scheduled job, not a patch. It is the next thing after this.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "runstatus"

OLD_LOOP = '''            elif status == "failed":
                print(f"❌ Pipeline failed at {node}: {state.get('error', 'unknown')}")
                return state
            elif status == "complete":
                print(f"✅ Pipeline complete!")
                return state'''

NEW_LOOP = '''            elif status == "failed":
                print(f"❌ Pipeline failed at {node}: {state.get('error', 'unknown')}")
                # The ROW, here, once.
                #
                # A node that returns failed used to leave pipeline_runs
                # saying 'running' unless that node also wrote the row itself
                # — two of eleven did. The row then said running forever: the
                # dashboard showed a live run, /pipeline/start refused the
                # slug, and an epic refused to restart the phase because it
                # looked in flight. That is what stopped
                # ducorn-admin-rebuild-p1-config from being retried.
                #
                # This loop sees every node's terminal status; it is the only
                # place that can record it without eleven nodes each
                # remembering to. No phase argument: the RUN's status is this
                # loop's fact, the SKILL's status stays the node's.
                _update_db_status(topic, "failed")
                return state
            elif status == "complete":
                print(f"✅ Pipeline complete!")
                _update_db_status(topic, "complete")
                return state'''

OLD_MAIN = '''    run_pipeline(
        topic=args.topic,
        product_type=args.type,
        build_engine=args.engine,
        coder=args.coder,
        complexity=args.complexity,
        phase=args.phase
    )'''

NEW_MAIN = '''    # A run that dies of an unhandled exception never reaches the loop that
    # records a terminal status, so it would leave the row saying running for
    # the same reason and with worse consequences — nobody even sees a
    # failure line. Not a duplicate of the loop's write: a different failure
    # the loop cannot observe.
    try:
        run_pipeline(
            topic=args.topic,
            product_type=args.type,
            build_engine=args.engine,
            coder=args.coder,
            complexity=args.complexity,
            phase=args.phase
        )
    except BaseException as _e:
        _clean_exit = isinstance(_e, SystemExit) and _e.code in (0, None)
        if not _clean_exit:
            print(f"❌ {args.topic} ended on {type(_e).__name__}: {_e}")
            _update_db_status(args.topic, "failed")
        raise'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (FLOW, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there"
                 + ("\nInstall scripts/patchlib.py first." if f is LIB else ""))

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src = FLOW.read_text(encoding="utf-8")
print("patch_run_status\n")

if "The ROW, here, once." in src:
    sys.exit("NOTHING DONE — the loop already records the terminal status.")

anchors = [("the terminal-status branches", OLD_LOOP),
           ("the run_pipeline call in __main__", OLD_MAIN)]
bad = False
for label, a in anchors:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

# _update_db_status must be reachable from both places, or this writes calls
# to a name that does not exist and the failure path raises inside the
# failure path.
if "def _update_db_status" not in src:
    sys.exit("NOTHING DONE — there is no _update_db_status in this file.")
print("  ok  _update_db_status is defined at module level")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(FLOW, FLOW.with_suffix(f".backup-{TAG}-{stamp}.py"))
out = src.replace(OLD_LOOP, NEW_LOOP, 1).replace(OLD_MAIN, NEW_MAIN, 1)
FLOW.write_text(out, encoding="utf-8")
print(f"\nwrote {FLOW.name}, backup tagged {TAG}-{stamp}")

after = FLOW.read_text(encoding="utf-8")
try:
    py_ok(after, "langgraph_flow.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# CODE, via patchlib — the comments above say "failed" and "running" a great
# many times, and three checks this session have passed or failed on their
# own prose. Counting call sites in the stripped source is the only reading
# that means anything.
code = code_only(after)
calls = code.count('_update_db_status(topic, "failed")')
if calls < 3:
    sys.exit(f"⚠️  expected the two existing failed-writes plus the new one; "
             f"found {calls} — restore the backup.")
if '_update_db_status(topic, "complete")' not in code:
    sys.exit("⚠️  the complete branch does not record — restore the backup.")
if '_update_db_status(args.topic, "failed")' not in code:
    sys.exit("⚠️  __main__ has no guard — restore the backup.")
print(f"verified: it parses; the loop records failed and complete "
      f"({calls} failed-writes in code, not comments),\n"
      f"          and __main__ marks a crashed run failed.")

print("""
The stuck row still says running — this stops the NEXT one, it does not
repair the last one. Clear it the supported way, which needs no SQL:

  curl -sX POST localhost:8000/pipeline/kill/ducorn-admin-rebuild-p1-config \\
       -H "x-api-key: $(grep '^DUCORN_API_TOKEN=' shared/.env | cut -d= -f2-)"

or press STOP on that run in the dashboard. It sets the row to 'stopped',
which the epic reads as failed, and the phase becomes startable again.
""")
