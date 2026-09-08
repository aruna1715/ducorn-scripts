#!/usr/bin/env python3
"""
Three endpoints so the dashboard can run a phase.

    cd ~/DC && python3 scripts/patch_epic_api.py            show
    cd ~/DC && python3 scripts/patch_epic_api.py --apply    do it

Needs scripts/product_epics.py and scripts/start_phase.py in place.

── WHY ──────────────────────────────────────────────────────────────────────

Phases could only be started from a terminal. That is not where this company
is operated from — the dashboard and Slack are — so a phase system reachable
only by CLI is a phase system that does not get used.

    GET  /epics                    every epic, with its phases
    GET  /epics/{name}             one epic, and what would start next
    POST /epics/{name}/start-next  start it

── WHAT THEY DO NOT CONTAIN ─────────────────────────────────────────────────

Any decision. Every one of them calls start_phase.plan_next or
start_phase.start_next, which is the same code the command line runs.

That matters more here than it sounds. "Which phase is next", "may it start",
"create the row, then launch detached" are four rules that a hand-written
endpoint would have restated, and the restatement would have drifted — which
is precisely how /pipeline/stop came to kill sibling runs while
/pipeline/kill did not.

── AUTHENTICATION ───────────────────────────────────────────────────────────

Nothing is added. main.py applies verify_token as GLOBAL http middleware:
every path except a short allowlist (/docs, the audio streams, /d/<token>)
requires x-api-key. New routes are covered the moment they exist.

The first draft of this patch attached a Depends(require_token) — which does
not exist, because the check is middleware and not a dependency. The guard
below is what caught that. It now asserts the middleware is present rather
than inventing a second door beside it.
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
NEEDED = [DC / "scripts" / "product_epics.py", DC / "scripts" / "start_phase.py"]
TAG = "epicapi"

ANCHOR = '''@app.post("/pipeline/stop/{slug}")'''

BLOCK = '''# ── EPICS ─────────────────────────────────────────────────────────────────────
# A product built over several runs. These endpoints hold no logic: every one
# calls scripts/start_phase.py, which is what the command line runs. Four
# rules live there — which phase is next, whether it may start, creating the
# row, launching detached — and an endpoint that restated them would drift,
# exactly as /pipeline/stop drifted from /pipeline/kill.


def _epic_tools():
    import importlib
    return (importlib.import_module("product_epics"),
            importlib.import_module("start_phase"))


@app.get("/epics")
def epics_list():
    """Every epic with its phases. Phase status comes from each phase's run."""
    try:
        pe, _ = _epic_tools()
    except ImportError as e:
        return JSONResponse({"error": f"epics are not installed: {e}",
                             "epics": []}, status_code=501)
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM product_epics ORDER BY created_at DESC")
            names = [r[0] for r in cur.fetchall()]
    except Exception as e:
        # Migration 009 not applied is a normal state, not a server fault.
        return JSONResponse({"error": str(e), "epics": []}, status_code=200)

    out = []
    for n in names:
        e = pe.get(n)
        if not e:
            continue
        out.append({
            "name": e["name"], "status": e["status"],
            "product_slug": e["product_slug"],
            "product_type": e["product_type"],
            "brief": (e["brief"] or "")[:400],
            "phases": [{"seq": p["seq"], "title": p["title"],
                        "slug": p["phase_slug"], "status": p["status"],
                        "depends_on": p["depends_on"]}
                       for p in e["phases"]],
        })
    return {"epics": out}


@app.get("/epics/{name}")
def epic_detail(name: str):
    """One epic, and what starting the next phase would do."""
    try:
        _, sp = _epic_tools()
    except ImportError as e:
        return JSONResponse({"error": str(e)}, status_code=501)
    try:
        return sp.plan_next(name)
    except Exception as e:
        # NotStartable is information, not a fault: "phase 2 is already
        # running" is the correct answer to "what is next", and the page
        # shows it rather than an error banner.
        return JSONResponse({"epic": name, "next": None, "blocked": str(e)},
                            status_code=200)


@app.post("/epics/{name}/start-next")
def epic_start_next(name: str):
    """
    Start the next phase of an epic.

    Spends money. No auth decoration here on purpose: verify_token is global
    middleware and already covers every path but its allowlist, so a check
    added here would be a second, weaker copy of one that already applies.

    The budget is checked inside start_next, by the same module
    /pipeline/start uses.
    """
    try:
        _, sp = _epic_tools()
    except ImportError as e:
        return JSONResponse({"error": str(e)}, status_code=501)
    try:
        result = sp.start_next(name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return result


'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in NEEDED + [API]:
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

src = API.read_text(encoding="utf-8")
print("patch_epic_api\n")

if "/epics/{name}/start-next" in src:
    sys.exit("NOTHING DONE — the epic endpoints are already there.")

n = src.count(ANCHOR)
print(f"  {'ok ' if n == 1 else '!! '}the insertion point  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# start-next spends money, so it must not be added unless the global auth
# middleware is really there and really global. This is checked, not assumed.
import re as _re
mw = _re.search(r'@app\.middleware\("http"\)\s*\n\s*async def (\w+)', src)
if not mw:
    sys.exit("""NOTHING DONE — no global http auth middleware found in main.py.

start-next spends money. Without the middleware these routes would be open,
and adding a check here instead would be a second copy of one that should be
global. Tell me how this API authenticates and I will match it.""")
if "x-api-key" not in src:
    sys.exit("NOTHING DONE — the middleware does not look for x-api-key; "
             "stop and check how this API authenticates.")
print(f"  ok  auth is global middleware {mw.group(1)}() — new routes are "
      f"covered by it")
block = BLOCK

# PYTHONPATH must reach scripts/ or the import fails at request time.
if "/Users/ducorn/DC/scripts" not in src:
    print("  note: main.py does not mention the scripts directory; it is on "
          "sys.path via the plist, which is how ducorn_env is already "
          "imported.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
API.write_text(src.replace(ANCHOR, block + ANCHOR, 1), encoding="utf-8")
print(f"\nwrote {API.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(API)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

print(f"""
verified: main.py parses.

  launchctl kickstart -k gui/$(id -u)/com.ducorn.api
  curl -s localhost:8000/epics | head -40
  curl -s localhost:8000/epics/ducorn-admin-rebuild

start-next needs the token, so from a terminal:
  curl -sX POST localhost:8000/epics/ducorn-admin-rebuild/start-next \\
       -H "x-api-key: $DUCORN_API_TOKEN"
""")
