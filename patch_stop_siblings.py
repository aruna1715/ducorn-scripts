#!/usr/bin/env python3
"""
Stopping 'ducorn-spend-status' must not kill 'ducorn-spend-status-web'.

    cd ~/DC && python3 scripts/patch_stop_siblings.py            show
    cd ~/DC && python3 scripts/patch_stop_siblings.py --apply    do it

── THE DEFECT ───────────────────────────────────────────────────────────────

main.py has TWO endpoints that stop a pipeline. /pipeline/kill/{slug} is
careful. /pipeline/stop/{slug} is the older one, and it is the same defect as
the jail prefix bug, three times over:

    subprocess.run(["pgrep", "-f", "langgraph_flow.py " + slug])

  pgrep -f matches a SUBSTRING of the command line. Stopping
  "ducorn-pipeline-dashboard" matches the process running
  "langgraph_flow.py ducorn-pipeline-dashboard-v6" and kills it too. You have
  three pairs of topics where one name is a prefix of another.

    UPDATE approval_requests SET status='rejected'
     WHERE status='pending' AND title LIKE '%' || slug || '%'

  Same again in SQL: stopping one product rejects the sibling's pending
  approvals, sitting in Slack, belonging to a run that is still going.

    @app.post("/pipeline/stop/{slug}")
    async def pipeline_stop(slug: str):

  And no validation at all — /pipeline/kill checks the slug against a
  pattern before it goes anywhere near pgrep; this one does not.

It also sends only SIGTERM and never checks whether the process died, so a
wedged run reports "Pipeline stopped" while still running.

── THE FIX ──────────────────────────────────────────────────────────────────

/pipeline/stop delegates to pipeline_kill. Not a copy of its logic — the
call. Two endpoints doing one job is how one of them stayed wrong for weeks
while the other was fixed.

pipeline_kill already: validates the slug, matches whole arguments rather
than substrings, escalates SIGTERM to SIGKILL and reports which, and cancels
approvals by product_slug rather than a LIKE on the title.

The response keeps its existing shape — status, slug, killed_pids, message —
because the dashboard's stop button reads those keys.

── ONE BEHAVIOUR CHANGE WORTH KNOWING ───────────────────────────────────────

Pending approvals for a stopped run are now marked 'cancelled' rather than
'rejected', matching /pipeline/kill. 'rejected' means a founder said no;
'cancelled' means the run went away. The dashboard and Slack already handle
'cancelled' — /pipeline/kill has been writing it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
API = DC / "ducorn-products" / "products" / "ducorn-activity-api" / "main.py"
TAG = "stopsiblings"

OLD = '''@app.post("/pipeline/stop/{slug}")
async def pipeline_stop(slug: str):
    """Stop a running pipeline by slug."""
    import subprocess
    result = subprocess.run(
        ["pgrep", "-f", "langgraph_flow.py " + slug],
        capture_output=True, text=True
    )
    pids = [p for p in result.stdout.strip().split() if p.strip()]
    killed = []
    for pid in pids:
        subprocess.run(["kill", "-15", pid], capture_output=True)
        killed.append(pid)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE pipeline_runs SET status=%s, updated_at=NOW() WHERE slug=%s",
                        ("stopped", slug))
            cur.execute("UPDATE approval_requests SET status=%s WHERE status=%s AND title LIKE %s",
                        ("rejected", "pending", "%" + slug + "%"))
        conn.commit()
    finally:
        conn.close()
    return {
        "status": "ok",
        "slug": slug,
        "killed_pids": killed,
        "message": "Pipeline stopped" if killed else "No running pipeline found"
    }'''

NEW = '''@app.post("/pipeline/stop/{slug}")
async def pipeline_stop(slug: str):
    """
    Stop a running pipeline by slug.

    Delegates to pipeline_kill rather than repeating it. This endpoint used to
    have its own copy, and the copy matched loosely in two places:

        pgrep -f "langgraph_flow.py " + slug     substring, so stopping
                                                 'ducorn-spend-status' also
                                                 killed '-web'
        title LIKE '%<slug>%'                    same again in SQL, rejecting
                                                 a sibling's pending approvals

    Three pairs of topics in this repo have one name as a prefix of another,
    so both were live. pipeline_kill validates the slug, matches whole
    arguments, escalates SIGTERM to SIGKILL and reports which, and cancels
    approvals by product_slug.

    The response shape is unchanged — the dashboard's stop button reads
    status, slug, killed_pids and message.
    """
    result = pipeline_kill(slug)
    if isinstance(result, JSONResponse):        # bad slug: 400, passed through
        return result

    killed = [str(p) for p in (list(result.get("killed", []))
                               + list(result.get("force_killed", [])))]
    return {
        "status": "ok",
        "slug": slug,
        "killed_pids": killed,
        "message": result.get("message",
                              "Pipeline stopped" if killed
                              else "No running pipeline found"),
    }'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not API.is_file():
    sys.exit(f"NOTHING DONE — {API} is not there")

src = API.read_text(encoding="utf-8")

print("patch_stop_siblings\n")
n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the old /pipeline/stop body  ({n} match)")

# pipeline_kill must exist, and must be defined BEFORE the endpoint that will
# call it — a module-level name resolved at call time would still work, but a
# missing one would only show up when someone pressed stop.
i_kill = src.find("def pipeline_kill(")
i_stop = src.find('@app.post("/pipeline/stop/{slug}")')
print(f"  {'ok ' if i_kill != -1 else '!! '}pipeline_kill is defined"
      f"{'' if i_kill != -1 else ' — it is not; stop'}")
print(f"  {'ok ' if -1 < i_kill < i_stop else '!! '}it is defined above "
      f"/pipeline/stop")

if n != 1 or i_kill == -1 or not (i_kill < i_stop):
    sys.exit("\nNOTHING DONE — the file is not in the shape this patch expects.")

# Show the collisions that make this a live bug, not a theoretical one.
try:
    topics = sorted(d.name for d in
                    (DC / "ducorn-products" / "products").iterdir() if d.is_dir())
except OSError:
    topics = []
pairs = [(a, b) for a in topics for b in topics if a != b and b.startswith(a)]
print(f"\n  topic pairs where one name contains the other: {len(pairs)}")
for a, b in pairs:
    print(f"      stopping '{a}' currently also kills '{b}'")
if not pairs:
    print("      (none among deployed product directories right now)")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
API.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {API.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(API)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

after = API.read_text(encoding="utf-8")
# Look for the CODE, not the prose. The first version of this check searched
# for "title LIKE" and matched the docstring above, which describes the bug
# it was checking for — a verification that fails on its own explanation.
left = []
if '["pgrep", "-f", "langgraph_flow.py " + slug]' in after:
    left.append("the substring pgrep call is still there")
if '"%" + slug + "%"' in after:
    left.append("the LIKE '%slug%' match is still there")
if left:
    sys.exit("⚠️  " + "; ".join(left) + " — restore the backup")

print("""
verified: main.py parses, and neither the substring pgrep nor the title LIKE
match remains.

Restart the API and try it:
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api
  curl -sX POST localhost:8000/pipeline/stop/not-a-real-slug
  curl -sX POST localhost:8000/pipeline/stop/'bad slug!'     # now a 400
""")
