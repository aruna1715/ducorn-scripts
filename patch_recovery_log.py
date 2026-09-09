#!/usr/bin/env python3
"""
A failing skill says what to do about it.

    cd ~/DC && python3 scripts/patch_recovery_log.py            show
    cd ~/DC && python3 scripts/patch_recovery_log.py --apply    do it

Needs scripts/run_recovery.py and scripts/patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

    ❌ Skill 06 — QA + Run Test FAILED
    VERDICT: FAIL — 14/25 tests failed …

True, and it leaves the operator with no idea that a plain resume re-runs
only skill 06 against unchanged code and fails identically. Everything
needed to say so was already in the machine — the checkpoint, FEEDBACK_SKILLS,
the --invalidate flag. None of it reached the log.

Now the same failure ends with the recovery plan, from run_recovery, which is
also what the API returns and what the dashboard's RECOVER button does. One
answer in three places rather than three that drift.

── AND IN SLACK ─────────────────────────────────────────────────────────────

The Slack message gains the one line that matters — which skills re-run — so
a failure read on a phone says what to press rather than only what broke.

── WHY IT CANNOT MAKE THINGS WORSE ──────────────────────────────────────────

It runs after the verdict is recorded and the exit code is decided, and it is
wrapped: if run_recovery raises for any reason, the original failure is still
printed and the exit code is unchanged. A helper that explains failures must
never become a way for them to be reported differently.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
RR = DC / "scripts" / "run_recovery.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "recoverylog"

OLD = '''        else:
            update_db_status(topic, skill_name, "failed")
            post_slack(f"❌ *{skill_name}* FAILED — `{topic}`\\n> {verdict}")
            print(f"\\n❌ {skill_name} FAILED")
            print(verdict)
            sys.exit(1)'''

NEW = '''        else:
            update_db_status(topic, skill_name, "failed")
            print(f"\\n❌ {skill_name} FAILED")
            print(verdict)

            # WHAT TO DO ABOUT IT, in the log, from the one module that
            # decides it. The operator used to be told only what broke — and
            # a plain resume re-runs just the failing skill against unchanged
            # work, so without this the obvious next action is the one that
            # loops forever.
            #
            # Wrapped: an explanation must never change how a failure is
            # reported. If this raises, the verdict above still stands and
            # the exit code below is unchanged.
            _next = ""
            try:
                import run_recovery as _rr
                _p = _rr.plan(topic)
                print("\\n" + _rr.as_text(_p), flush=True)
                if _p.get("invalidate"):
                    _next = ("\\n> Re-runs on recovery: skills "
                             + ", ".join(_p["invalidate"])
                             + " — press RECOVER in the dashboard.")
            except Exception as _e:
                print(f"\\n(could not build a recovery plan: "
                      f"{type(_e).__name__}: {_e})", flush=True)

            post_slack(f"❌ *{skill_name}* FAILED — `{topic}`\\n> {verdict}"
                       + _next)
            sys.exit(1)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, RR, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

src = RUNNER.read_text(encoding="utf-8")
print("patch_recovery_log\n")

if "run_recovery" in src:
    sys.exit("NOTHING DONE — the failure branch already explains itself.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the failure branch  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# run_recovery must actually load under the interpreter the pipeline uses,
# or every failure gains a second, confusing failure.
venv = DC / "ducorn" / ".venv" / "bin" / "python"
py = str(venv) if venv.exists() else sys.executable
r = subprocess.run([py, "-c",
                    "import sys; sys.path[:0]=['/Users/ducorn/DC/scripts',"
                    "'/Users/ducorn/DC/ducorn']; import run_recovery; "
                    "print('IMPORT_OK', bool(run_recovery.plan))"],
                   capture_output=True, text=True)
if "IMPORT_OK" not in r.stdout:
    sys.exit(f"NOTHING DONE — run_recovery does not import under "
             f"{py}:\n{(r.stdout + r.stderr)[-400:]}")
print("  ok  run_recovery imports under the pipeline's interpreter")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

after = RUNNER.read_text(encoding="utf-8")
try:
    py_ok(after, "skill_runner.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# Scoped to main(): the explanation must be there, and the exit code must not
# have moved.
if len(calls_in(after, "main", "as_text")) != 1:
    sys.exit("⚠️  main() does not print the plan exactly once — restore the "
             "backup.")
exits = [c for c in calls_in(after, "main", "exit")]
if not any("1" in c for c in exits):
    sys.exit("⚠️  the failure branch no longer exits non-zero — restore the "
             "backup. Explaining a failure must not stop it failing.")
print("verified: skill_runner.py parses, prints the plan once, and still "
      "exits non-zero on failure.")

print("""
  python3 scripts/run_recovery.py ducorn-admin-rebuild-p1-config

That is the block a failing skill will now print, and what the dashboard's
RECOVER button will do.
""")
