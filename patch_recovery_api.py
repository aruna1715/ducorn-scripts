#!/usr/bin/env python3
"""
Two endpoints so the dashboard can explain and perform a recovery.

    cd ~/DC && python3 scripts/patch_recovery_api.py            show
    cd ~/DC && python3 scripts/patch_recovery_api.py --apply    do it

Needs scripts/run_recovery.py and scripts/patchlib.py.

    GET  /pipeline/recovery/{slug}   what failed, and what would fix it
    POST /pipeline/recovery/{slug}   drop the cached skills that must re-run

── WHY TWO, AND WHY NEITHER RESUMES ─────────────────────────────────────────

Invalidating a checkpoint is free and reversible in effect — the skills
simply run again. Resuming spends money. They are two decisions, so they are
two actions, and the second one already has an endpoint.

The dashboard's failure panel currently ends with the sentence

    "The builder is now given this report automatically. Press RESUME to
     rebuild with it in hand."

which is wrong whenever the failing skill is not the first thing that would
re-run. Phase 1 of the admin rebuild failed at QA with the build and the
review both cached as passed, so RESUME re-ran only QA against unchanged
code — the advice, followed exactly, loops forever.

── NO LOGIC HERE ────────────────────────────────────────────────────────────

Both call scripts/run_recovery.py, which is what the command line runs and
what a failing skill now prints into the log. An endpoint that worked out
which skills to drop would be a third opinion about a question that already
has an answer.
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
RR = DC / "scripts" / "run_recovery.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "recoveryapi"

ANCHOR = '''@app.post("/pipeline/resume/{slug}")'''

BLOCK = '''# ── RECOVERY ──────────────────────────────────────────────────────────────────
# What to do about a failed run. No logic here: scripts/run_recovery.py
# decides, the command line calls the same function, and a failing skill
# prints the same text into the log.


@app.get("/pipeline/recovery/{slug}")
def pipeline_recovery_plan(slug: str):
    """What failed and what would fix it. Reads only; changes nothing."""
    try:
        import run_recovery as _rr
        return _rr.plan(slug)
    except ImportError as e:
        return JSONResponse({"error": f"run_recovery is not installed: {e}"},
                            status_code=501)
    except Exception as e:
        return JSONResponse({"error": str(e), "state": "unknown"},
                            status_code=200)


@app.post("/pipeline/recovery/{slug}")
def pipeline_recovery_apply(slug: str):
    """
    Drop the cached skills that must re-run. Does NOT resume.

    Invalidating is free; resuming spends money. Keeping them apart means the
    button that costs nothing cannot become the button that costs something
    because someone added a convenience.
    """
    try:
        import run_recovery as _rr
        return _rr.apply_plan(slug)
    except ImportError as e:
        return JSONResponse({"error": f"run_recovery is not installed: {e}"},
                            status_code=501)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=409)


'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (API, RR, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

src = API.read_text(encoding="utf-8")
print("patch_recovery_api\n")

if "/pipeline/recovery/" in src:
    sys.exit("NOTHING DONE — the recovery endpoints are already there.")

n = src.count(ANCHOR)
print(f"  {'ok ' if n == 1 else '!! '}the insertion point  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# It must import under the API's OWN interpreter, which is homebrew python3.12
# and not the pipeline venv. run_recovery imports skill_runner, and if
# skill_runner ever grows a heavy module-level import this is where it breaks
# — as a 500 on a web request, at the worst moment.
r = subprocess.run(["/opt/homebrew/bin/python3.12", "-c",
                    "import sys; sys.path[:0]=['/Users/ducorn/DC/scripts',"
                    "'/Users/ducorn/DC/ducorn']; import run_recovery; "
                    "print('IMPORT_OK')"],
                   capture_output=True, text=True)
if "IMPORT_OK" not in r.stdout:
    sys.exit(f"NOTHING DONE — run_recovery does not import under the API's "
             f"interpreter:\n{(r.stdout + r.stderr)[-400:]}")
print("  ok  run_recovery imports under the API's own interpreter")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
API.write_text(src.replace(ANCHOR, BLOCK + ANCHOR, 1), encoding="utf-8")
print(f"\nwrote {API.name}, backup tagged {TAG}-{stamp}")

after = API.read_text(encoding="utf-8")
try:
    py_ok(after, "main.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

if len(calls_in(after, "pipeline_recovery_plan", "plan")) != 1:
    sys.exit("⚠️  the GET does not call run_recovery.plan once — restore the "
             "backup.")
if len(calls_in(after, "pipeline_recovery_apply", "apply_plan")) != 1:
    sys.exit("⚠️  the POST does not call apply_plan once — restore the "
             "backup.")
# The money line: neither endpoint may start a run.
for fn in ("pipeline_recovery_plan", "pipeline_recovery_apply"):
    if calls_in(after, fn, "Popen") or calls_in(after, fn, "run"):
        sys.exit(f"⚠️  {fn} launches something — recovery must not resume. "
                 f"Restore the backup.")
print("verified: main.py parses; both endpoints delegate, and neither starts "
      "a run.")

print("""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api
  curl -s localhost:8000/pipeline/recovery/ducorn-admin-rebuild-p1-config \\
       -H "x-api-key: $DUCORN_API_TOKEN"

Then apply patch_recovery_ui.py for the RECOVER button.
""")
