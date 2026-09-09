#!/usr/bin/env python3
"""
One matcher for "which process is this run", shared with the reaper.

    cd ~/DC && python3 scripts/patch_kill_liveness.py            show
    cd ~/DC && python3 scripts/patch_kill_liveness.py --apply    do it

Needs scripts/run_liveness.py and scripts/patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

pipeline_kill owns the only correct copy of this rule:

    a process belongs to a run when one of its ARGUMENTS is exactly the slug

It was earned. The version before it matched a substring, so stopping
'ducorn-spend-status' also killed 'ducorn-spend-status-web', and three pairs
of topics in this repo have one name as a prefix of another.

The reaper needs the same answer from a launchd job, which cannot import
main.py — it is a FastAPI app with a connection pool and side effects at
import. So the rule moved into scripts/run_liveness.py, and this points
pipeline_kill at it.

Without this patch there are two copies from the moment the reaper exists,
and the reaper's copy runs unattended every five minutes.

── WHAT DOES NOT CHANGE ─────────────────────────────────────────────────────

The slug validation, the SIGTERM-then-SIGKILL escalation, the response shape,
the approval cancellation. Only where the pid list comes from.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
API = DC / "ducorn-products" / "products" / "ducorn-activity-api" / "main.py"
RL = DC / "scripts" / "run_liveness.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "killlive"

OLD = '''    try:
        out = _sp.run(["pgrep", "-fl", "langgraph_flow.py"],
                      capture_output=True, text=True, timeout=10).stdout
    except Exception as e:
        return JSONResponse({"error": f"could not list processes: {e}"},
                            status_code=500)

    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        # Whole-argument match: stopping 'foo' must not kill a run of 'foo-v2'.
        if any(a == slug for a in " ".join(parts[1:]).split()):
            pids.append(int(parts[0]))'''

NEW = '''    # The matcher lives in scripts/run_liveness.py so the reaper — a launchd
    # job that cannot import this FastAPI app — asks the same question and
    # gets the same answer. Whole-argument matching, so stopping 'foo' still
    # does not kill 'foo-v2'; that rule was earned here and is now in one
    # place instead of two.
    import run_liveness as _rl
    try:
        pids = _rl.pids_for(slug)
    except _rl.BadSlug:
        return JSONResponse({"error": "bad slug"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"could not list processes: {e}"},
                            status_code=500)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (API, RL, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, calls_in, py_ok, PatchCheckFailed  # noqa: E402

# The module going in must pass its own tests before an endpoint depends on it.
import subprocess  # noqa: E402
r = subprocess.run([sys.executable, str(RL), "--test"],
                   capture_output=True, text=True)
if "run_liveness OK" not in r.stdout:
    sys.exit(f"NOTHING DONE — run_liveness fails its own tests:\n{r.stdout}"
             f"{r.stderr[-300:]}")
print("patch_kill_liveness\n")
print("  ok  run_liveness passes its self-test")

src = API.read_text(encoding="utf-8")
if "import run_liveness" in src:
    sys.exit("NOTHING DONE — pipeline_kill already uses run_liveness.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the pgrep block in pipeline_kill  "
      f"({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
API.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {API.name}, backup tagged {TAG}-{stamp}")

after = API.read_text(encoding="utf-8")
try:
    py_ok(after, "main.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# Scoped to the function changed, from the parse tree — not a count over the
# file, which is how a correct patch got reported as broken earlier today.
got = calls_in(after, "pipeline_kill", "pids_for")
if len(got) != 1:
    sys.exit(f"⚠️  pipeline_kill calls pids_for {len(got)} times — restore "
             f"the backup.")
code = code_only(after)
kill_body = code[code.find("def pipeline_kill"):code.find("def budget_check")]
if "pgrep" in kill_body:
    sys.exit("⚠️  pipeline_kill still runs pgrep itself — restore the backup.")
print("verified: main.py parses; pipeline_kill calls pids_for once and no "
      "longer runs pgrep.")

print("""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api

Then stopping something already stopped should still answer cleanly:

  curl -sX POST localhost:8000/pipeline/kill/no-such-run \\
       -H "x-api-key: $DUCORN_API_TOKEN"
""")
