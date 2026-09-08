#!/usr/bin/env python3
"""
/epics ran its own SQL and got the cursor factory wrong.

    cd ~/DC && python3 scripts/fix_epics_endpoint.py            show
    cd ~/DC && python3 scripts/fix_epics_endpoint.py --apply    do it

Needs the updated scripts/product_epics.py (the one with all_names()).

── THE SYMPTOM ──────────────────────────────────────────────────────────────

    curl -s localhost:8000/epics -H "x-api-key: ..."
    {"error":"0","epics":[]}

── THE CAUSE ────────────────────────────────────────────────────────────────

The endpoint I added listed the epics with its own query:

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM product_epics ORDER BY created_at DESC")
        names = [r[0] for r in cur.fetchall()]

main.py's get_connection() builds its cursors with RealDictCursor, so a row
is a dict and r[0] raises KeyError: 0 — whose str() is "0". Hence an error
message that is a single digit and says nothing.

The bug was the SQL, not the subscript. Every other line of that block calls
product_epics, which owns this schema; those four lines put a second copy of
it in a file that knows nothing about epics, on a different connection with a
different cursor factory. Fixing r[0] to r["name"] would have left the second
copy in place to break again the next time a column moved.

product_epics.all_names() now does it, on the connection that module already
uses, and the endpoint has no SQL in it at all.
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
EPICS = DC / "scripts" / "product_epics.py"
TAG = "epicsql"

OLD = '''    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM product_epics ORDER BY created_at DESC")
            names = [r[0] for r in cur.fetchall()]
    except Exception as e:
        # Migration 009 not applied is a normal state, not a server fault.
        return JSONResponse({"error": str(e), "epics": []}, status_code=200)'''

NEW = '''    try:
        # NOT a SELECT here. product_epics owns this schema and this endpoint
        # knows nothing about it — the first version listed the epics with its
        # own query on get_connection(), whose RealDictCursor makes a row a
        # dict, so r[0] raised KeyError: 0 and the endpoint reported its error
        # as the string "0".
        names = pe.all_names()
    except Exception as e:
        # Migration 009 not applied is a normal state, not a server fault.
        return JSONResponse({"error": str(e), "epics": []}, status_code=200)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (API, EPICS):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

if "def all_names" not in EPICS.read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — scripts/product_epics.py has no all_names(). "
             "Install the updated module first; it is delivered alongside "
             "this patch.")

src = API.read_text(encoding="utf-8")
print("fix_epics_endpoint\n")
print("  ok  product_epics.all_names() is available")

if "pe.all_names()" in src:
    sys.exit("NOTHING DONE — the endpoint already uses all_names().")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the SQL block in /epics  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

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
i = after.find("def epics_list")
j = after.find("def epic_detail")

# CODE only. The first version of this check scanned the raw region and found
# the word SELECT inside the comment that says "NOT a SELECT here" — so it
# failed on its own explanation, having applied a correct patch.
#
# Second time in one session: patch_stop_siblings searched for "title LIKE"
# and matched the docstring describing the title-LIKE bug. A check that reads
# prose is checking the wrong thing; strip the comments first.
code = "\n".join(l for l in after[i:j].splitlines()
                 if not l.lstrip().startswith("#")
                 and not l.lstrip().startswith('"""'))
if "SELECT" in code.upper():
    sys.exit("⚠️  there is still SQL inside epics_list — restore the backup.")
print("verified: main.py parses and /epics contains no SQL.")

print(f"""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api
  curl -s localhost:8000/epics \\
       -H "x-api-key: $(grep '^DUCORN_API_TOKEN=' {DC}/shared/.env | cut -d= -f2-)"

It should list ducorn-admin-rebuild with three pending phases.
""")
