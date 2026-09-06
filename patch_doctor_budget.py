#!/usr/bin/env python3
"""
Ask the thing that decides, instead of keeping a second opinion.

── MY BUG ───────────────────────────────────────────────────────────────────

    check("spend", "today's spend under $25", today < 25, ...)

I typed 25 into doctor.py. The machine's actual limit is DUCORN_DAILY_BUDGET,
set to 5.0 in shared/.env and read by the API, which refuses to start a
pipeline once today's spend reaches it.

So doctor reported "today's spend under $25 — $27.22" as a mild overage while
/pipeline/start was hard-blocking every new run. The check was not merely
wrong; it was reassuring about the wrong thing. A person reading doctor would
conclude they were slightly over a soft line, and then find the start button
refusing them with no idea why.

That is the two-copies defect, in the tool built to catch it, put there by me
about four hours ago.

── THE FIX ──────────────────────────────────────────────────────────────────

Doctor calls /budget/check — the same endpoint /pipeline/start calls — and
reports what it says. One source. If the limit changes, doctor changes with it,
because doctor is not the one holding the number.

And the check becomes the question that matters:

    ok   the pipeline can start   $4.20 of $50.00 today
    FAIL the pipeline is BLOCKED  $27.22 of $5.00 — raise DUCORN_DAILY_BUDGET

"Can a run start" is what somebody needs to know before opening the dashboard.
"Is spend under an arbitrary number" is trivia.

── WHAT IT DOES NOT DO ──────────────────────────────────────────────────────

It does not change the limit. That is a decision, it lives in shared/.env, and
a health check that edits your budget would be worse than one that misreports
it. It prints the command.

Worth knowing, and now printed: the limit gates the dashboard's start button
only. A CLI run does not consult it — which is how tonight reached $27.22
against a $5 cap.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DOCTOR = Path("/Users/ducorn/DC/scripts/doctor.py")
s = DOCTOR.read_text(encoding="utf-8")

if "budget/check" in s:
    print("Already patched — doctor asks the endpoint that decides.")
    sys.exit(0)

anchor = '''    # Not a pass/fail — a number a person judges. Flagged only when it is
    # large enough that nobody should discover it by accident.
    check("spend", "today's spend under $25", today < 25,
          f"${today:,.2f}",
          "python3 scripts/litellm_budget.py --key ducorn-rex   (per-agent caps)")'''
if s.count(anchor) != 1:
    # The comment may differ; fall back to the check itself.
    anchor = '''    check("spend", "today's spend under $25", today < 25,
          f"${today:,.2f}",
          "python3 scripts/litellm_budget.py --key ducorn-rex   (per-agent caps)")'''
    if s.count(anchor) != 1:
        sys.exit(f"ANCHOR MISS: the $25 check appears {s.count(anchor)} times. "
                 f"NOTHING WRITTEN.")

NEW = '''    # The question is not "is spend high", it is "will the pipeline start".
    # /budget/check is what /pipeline/start consults, so doctor asks that
    # rather than holding a number of its own — which it did, set to 25, while
    # the real limit was 5 and the start button was refusing every run.
    try:
        b = get_json(f"{API}/budget/check")
        limit = float(b.get("daily_limit", 0))
        spent = float(b.get("today_spend", today))
        can = bool(b.get("can_proceed", True))
        check("spend", "the pipeline can start", can,
              f"${spent:,.2f} of ${limit:,.2f} today",
              f"raise DUCORN_DAILY_BUDGET in ~/DC/shared/.env, then "
              f"launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
        if not can and not _quiet:
            # Said out loud because it surprises people: the cap gates the
            # dashboard's start button, not spending. A CLI run ignores it.
            print("       this blocks the dashboard's start button only — "
                  "a CLI run does not consult it")
    except Exception as e:
        check("spend", "the pipeline can start", False,
              f"could not ask /budget/check ({type(e).__name__})",
              "is the API up? launchctl kickstart -k gui/$(id -u)/com.ducorn.api")'''

applied = ["budget from the endpoint"]
s = s.replace(anchor, NEW, 1)

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = DOCTOR.with_name(f"doctor.backup-budget-{stamp}.py")
shutil.copy2(DOCTOR, backup)
DOCTOR.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, DOCTOR)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(DOCTOR)],
                   capture_output=True, text=True)
if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
    die("undefined name:\\n" + r.stdout + r.stderr)
print("syntax and undefined-name checks: clean")

src = DOCTOR.read_text(encoding="utf-8")
for must, why in [
    ("/budget/check", "doctor asks the endpoint that decides"),
    ("the pipeline can start", "the check is the question that matters"),
    ("DUCORN_DAILY_BUDGET", "the fix names the real setting"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

if "today < 25" in src:
    die("doctor still holds its own threshold")
print("  ok   doctor no longer holds a number of its own")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("The limit itself is yours to set, in ~/DC/shared/.env:")
print("  DUCORN_DAILY_BUDGET=5.0     ← what it is now")
print()
print("A production document run costs roughly $4-8, so 5.0 blocks essentially")
print("every real run. Change it, then:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
print("  python3 scripts/doctor.py --quiet")
