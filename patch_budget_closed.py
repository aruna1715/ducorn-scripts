#!/usr/bin/env python3
"""
The budget check must not answer "$0 spent, go ahead" when it cannot see the spend.

    cd ~/DC && python3 scripts/patch_budget_closed.py            show
    cd ~/DC && python3 scripts/patch_budget_closed.py --apply    do it

Needs scripts/ducorn_spend.py beside it.

── THE DEFECT ───────────────────────────────────────────────────────────────

/budget/check is what /pipeline/start consults before spending money. It
fails open in three separate ways.

1. The parse stops at the first row:

       for entry in logs:
           if entry.get("date") == today:
               today_spend = float(entry.get("spend", 0))
               break

   LiteLLM returns spend logs per key and per model. The first matching row
   is a fraction of the day's total, and it is reported as the total. Not an
   error — a plausible, wrong number, which is the worse failure.

2. Every exception becomes permission:

       except Exception as e:
           return {"today_spend": 0, ..., "can_proceed": True}

   LiteLLM down, wrong master key, an unexpected shape: all of them mean
   "$0.00 spent today, start the run".

3. The caller swallows what is left:

       except:
           pass  # Don't block on budget check failure

   so a timeout or a 500 removes the check entirely.

── THE FIX ──────────────────────────────────────────────────────────────────

scripts/ducorn_spend.py reads LiteLLM_SpendLogs directly — the table LiteLLM
writes, the same source doctor.py already trusts — sums the whole day rather
than one row, and raises rather than guessing. /budget/check returns
can_proceed=false when the spend is unknown, and /pipeline/start returns 429
with the reason instead of passing.

Not knowing what has been spent is not permission to spend more.

── AND THE DRIFT ────────────────────────────────────────────────────────────

doctor.py computes today's spend with its own SQL, then asks /budget/check
for the verdict. Once both read the same table they must agree, so doctor now
compares them and fails if they differ by more than a cent. Two computations
of one fact, checked against each other, instead of quietly diverging.

── THE COST OF FAILING CLOSED ───────────────────────────────────────────────

If litellm_db is unreachable, the dashboard will refuse to start a pipeline
and say why. That database is on the same PostgreSQL as pipeline_runs, so a
real outage stops the pipeline regardless — this changes an unnoticed
mis-start into a clear refusal. A CLI run still does not consult the cap,
which was already true.
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
DOCTOR = DC / "scripts" / "doctor.py"
SPEND = DC / "scripts" / "ducorn_spend.py"
TAG = "budgetclosed"

OLD_CHECK = '''# ── BUDGET CHECK ──────────────────────────────────────────────────────────────
DAILY_BUDGET_LIMIT = float(os.environ.get("DUCORN_DAILY_BUDGET", "3.0"))

@app.get("/budget/check")
def budget_check():
    """Check today's spend vs daily limit before starting a pipeline"""
    import httpx
    try:
        resp = httpx.get(
            "http://localhost:4000/global/spend/logs",
            headers={"Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', 'ducorn-admin-2026')}"},
            timeout=5
        )
        logs = resp.json()
        from datetime import date
        today = date.today().isoformat()
        today_spend = 0.0
        for entry in logs:
            if entry.get("date") == today:
                today_spend = float(entry.get("spend", 0))
                break

        remaining = max(0, DAILY_BUDGET_LIMIT - today_spend)
        can_proceed = today_spend < DAILY_BUDGET_LIMIT

        return {
            "today_spend": round(today_spend, 4),
            "daily_limit": DAILY_BUDGET_LIMIT,
            "remaining": round(remaining, 4),
            "can_proceed": can_proceed,
            "message": f"${today_spend:.2f} spent today of ${DAILY_BUDGET_LIMIT:.2f} limit" if can_proceed
                      else f"⚠️ Daily budget limit reached (${today_spend:.2f} of ${DAILY_BUDGET_LIMIT:.2f})"
        }
    except Exception as e:
        return {
            "today_spend": 0,
            "daily_limit": DAILY_BUDGET_LIMIT,
            "remaining": DAILY_BUDGET_LIMIT,
            "can_proceed": True,
            "message": f"Budget check unavailable: {e}"
        }'''

NEW_CHECK = '''# ── BUDGET CHECK ──────────────────────────────────────────────────────────────
# The number comes from scripts/ducorn_spend.py, which reads
# LiteLLM_SpendLogs — the same table doctor.py reads. This endpoint used to
# call LiteLLM over HTTP and take the FIRST row whose date matched today,
# which is one key's spend reported as the whole day's, and turned every
# exception into {"today_spend": 0, "can_proceed": true}.
#
# The limit is no longer captured at import. It was, and the admin page can
# write DUCORN_DAILY_BUDGET into shared/.env — a limit frozen at process
# start is a limit that page cannot actually change.
import ducorn_spend as _spend


@app.get("/budget/check")
def budget_check():
    """
    Today's spend against the daily limit.

    can_proceed is FALSE when the spend cannot be determined. Not knowing
    what has been spent is not permission to spend more.
    """
    return _spend.budget_status()'''

OLD_CALLER = '''    try:
        budget = _httpx.get(
            "http://localhost:8000/budget/check",
            headers={"x-api-key": os.environ.get("DUCORN_API_TOKEN", "")},
            timeout=5
        ).json()
        if not budget.get("can_proceed", True):
            return JSONResponse({
                "error": budget["message"],
                "today_spend": budget["today_spend"],
                "daily_limit": budget["daily_limit"]
            }, status_code=429)
    except:
        pass  # Don't block on budget check failure'''

NEW_CALLER = '''    # In-process, not over HTTP to ourselves: a call from this service to this
    # service could time out, and the old `except: pass` below turned that
    # into no budget check at all.
    import ducorn_spend as _spend_gate
    budget = _spend_gate.budget_status()
    if not budget.get("can_proceed"):
        return JSONResponse({
            "error": budget["message"],
            "today_spend": budget["today_spend"],
            "daily_limit": budget["daily_limit"],
        }, status_code=429)'''

OLD_DOCTOR = '''    try:
        b = get_json(f"{API}/budget/check")
        limit = float(b.get("daily_limit", 0))
        spent = float(b.get("today_spend", today))
        can = bool(b.get("can_proceed", True))
        check("spend", "the pipeline can start", can,
              f"${spent:,.2f} of ${limit:,.2f} today",
              f"raise DUCORN_DAILY_BUDGET in ~/DC/shared/.env, then "
              f"launchctl kickstart -k gui/$(id -u)/com.ducorn.api")'''

NEW_DOCTOR = '''    try:
        b = get_json(f"{API}/budget/check")
        limit = float(b.get("daily_limit", 0))
        spent = b.get("today_spend")
        can = bool(b.get("can_proceed", False))
        check("spend", "the pipeline can start", can,
              (f"${float(spent):,.2f} of ${limit:,.2f} today"
               if spent is not None else b.get("message", "spend unknown")),
              f"raise DUCORN_DAILY_BUDGET in ~/DC/shared/.env, then "
              f"launchctl kickstart -k gui/$(id -u)/com.ducorn.api")

        # Two computations of one fact. doctor sums LiteLLM_SpendLogs above;
        # /budget/check now sums the same table through ducorn_spend.py. They
        # must agree, so say so when they do not, rather than letting the gate
        # and the report drift the way they did when the endpoint scanned
        # LiteLLM's HTTP logs and stopped at the first row.
        check("spend", "the gate and this report agree",
              spent is not None and abs(float(spent) - today) < 0.01,
              (f"doctor ${today:,.2f} · /budget/check ${float(spent):,.2f}"
               if spent is not None else "/budget/check cannot read the spend"),
              "both should read LiteLLM_SpendLogs via scripts/ducorn_spend.py")'''

def probe_python() -> str:
    """
    An interpreter that can actually reach PostgreSQL.

    This script is run as `python3 scripts/...`, which on this Mac is 3.14 and
    has no psycopg2. Probing with it would report "spend UNKNOWN" for every
    run and prove nothing — the API runs on 3.12. doctor.py re-executes itself
    for the same reason.
    """
    for c in (DC / "ducorn" / ".venv" / "bin" / "python",
              Path("/opt/homebrew/bin/python3.12")):
        if c.exists():
            return str(c)
    return sys.executable


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()
PY = probe_python()

edits = [(API, "budget_check reads the table, not the first HTTP row",
          OLD_CHECK, NEW_CHECK),
         (API, "/pipeline/start stops swallowing the check",
          OLD_CALLER, NEW_CALLER),
         (DOCTOR, "doctor compares the gate against its own sum",
          OLD_DOCTOR, NEW_DOCTOR)]

print("patch_budget_closed\n")

if not SPEND.is_file():
    sys.exit(f"NOTHING DONE — {SPEND} must be in place first "
             f"(it is delivered alongside this patch).")
print(f"  ok  {SPEND.name} is present")

src = {}
ok = True
for path, what, old, _new in edits:
    if not path.is_file():
        sys.exit(f"NOTHING DONE — {path} is not there")
    src.setdefault(path, path.read_text(encoding="utf-8"))
    n = src[path].count(old)
    print(f"  {'ok ' if n == 1 else '!! '}{path.name:12} {what}  ({n} match)")
    ok = ok and n == 1
if not ok:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

# What the module says right now, before anything changes.
probe = f'''
import sys
sys.path.insert(0, "{DC}/scripts")
import ducorn_spend as s
st = s.budget_status()
print("  today  %s  ·  limit $%.2f  ·  can_proceed %s"
      % (("$%.2f" % st["today_spend"]) if st["known"] else "UNKNOWN",
         st["daily_limit"], st["can_proceed"]))
if not st["known"]:
    print("  " + st["message"])
'''
r = subprocess.run([PY, "-c", probe], capture_output=True, text=True)
print(f"\n  ducorn_spend.py under {PY}, right now, against litellm_db:")
print((r.stdout or r.stderr).rstrip() or "  (no output)")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
for path in src:
    shutil.copy2(path, path.with_suffix(f".backup-{TAG}-{stamp}.py"))

out = dict(src)
for path, _what, old, new in edits:
    out[path] = out[path].replace(old, new, 1)
for path, text in out.items():
    path.write_text(text, encoding="utf-8")
print(f"\nwrote {len(out)} file(s), backups tagged {TAG}-{stamp}")

fails = []
for path in out:
    r = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append(f"{path.name} does not parse:\n{r.stderr[-400:]}")

# Fail-closed, proven: point the module at a database that is not there.
probe2 = f'''
import os, sys
os.environ["LITELLM_DATABASE_URL"] = "postgresql://nobody@127.0.0.1:1/nope"
sys.path.insert(0, "{DC}/scripts")
import ducorn_spend as s
st = s.budget_status()
print("CLOSED_OK" if st["can_proceed"] is False and st["known"] is False
      else "CLOSED_BAD " + repr(st))
'''
r = subprocess.run([PY, "-c", probe2], capture_output=True, text=True)
if "CLOSED_OK" not in r.stdout:
    fails.append("it does not fail closed: " + (r.stdout + r.stderr).strip()[-300:])

if fails:
    print("\n⚠️  VERIFICATION FAILED — backups are beside each file:\n")
    for f in fails:
        print("   " + f + "\n")
    raise SystemExit(1)

print("""
verified: all files parse, and with the database made unreachable the status
comes back can_proceed=False, known=False — it refuses rather than reporting
$0.00 and starting.

The API must restart to pick this up:
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api
  python3 scripts/doctor.py        two new checks in the spend section
  curl -s localhost:8000/budget/check
""")
