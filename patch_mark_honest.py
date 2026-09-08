#!/usr/bin/env python3
"""
An error message that recommends a command which cannot work.

    cd ~/DC && python3 scripts/patch_mark_honest.py            show
    cd ~/DC && python3 scripts/patch_mark_honest.py --apply    do it

Needs scripts/patchlib.py.

── WHAT IT SAYS ─────────────────────────────────────────────────────────────

    phase 1 (Configuration) is already running as '...-p1-config'.
    Wait for it, or if that run died:
      python3 scripts/product_epics.py --mark ...-p1-config pending

── WHY IT CANNOT WORK ───────────────────────────────────────────────────────

_effective() decides what a phase's status IS:

    if stored == "skipped": return "skipped"
    if run_status: return RUN_TO_PHASE.get(run_status, stored)
    return stored

The run wins wherever there is one. So --mark pending writes 'pending' into
epic_phases, the run row still says 'running', and the phase still reads
running. The command succeeds, prints nothing alarming, and changes nothing.

mark()'s own docstring already says so — "writing 'complete' or 'failed' here
is allowed but has no effect once a run exists" — and the message I wrote
recommends exactly that, for 'pending'. The documentation was right and
nothing enforced it.

── THE FIX, IN TWO PARTS ────────────────────────────────────────────────────

1. mark() refuses a write the run would override, and names the action that
   actually works. A command that silently does nothing is worse than one
   that fails: it costs a person the time to find out.

2. next_phase()'s message recommends stopping the run — the supported path,
   from the dashboard or /pipeline/kill — instead of a no-op.

'skipped' is untouched: it is a decision a person made and _effective()
honours it over any run. That is the one case where writing the stored value
is the whole point.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
PE = DC / "scripts" / "product_epics.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "markhonest"

OLD_MSG = '''            raise EpicError(
                f"phase {p['seq']} ({p['title']}) is already running as "
                f"'{p['phase_slug']}'. Wait for it, or if that run died:\\n"
                f"  python3 scripts/product_epics.py --mark {p['phase_slug']} pending")'''

NEW_MSG = '''            # NOT --mark pending. The run wins over the stored status
            # (see _effective), so marking it pending changes nothing while
            # the row says running. Stopping the run is what moves it.
            raise EpicError(
                f"phase {p['seq']} ({p['title']}) is already running as "
                f"'{p['phase_slug']}'.\\n"
                f"Wait for it — or if that run is dead, stop it, which sets "
                f"the row to 'stopped' and frees the phase:\\n"
                f"  press STOP on that run in the dashboard, or\\n"
                f"  curl -sX POST localhost:8000/pipeline/kill/{p['phase_slug']} "
                f"-H \\"x-api-key: $DUCORN_API_TOKEN\\"")'''

OLD_MARK = '''    with _conn() as c:
        cur = c.cursor()
        stamp = ("started_at = now()" if status == "running"'''

NEW_MARK = '''    with _conn() as c:
        cur = c.cursor()

        # Refuse a write the run would override.
        #
        # _effective() gives the run the last word wherever there is one, so
        # marking a phase 'pending' while its run row says 'running' writes a
        # value nothing will ever read. That is what next_phase used to
        # recommend, and it looked like it worked.
        #
        # 'skipped' is exempt because _effective exempts it: a person's
        # decision outranks any run, which is the entire reason that status
        # exists.
        if status != "skipped":
            cur.execute("SELECT status FROM pipeline_runs WHERE slug = %s",
                        (slug,))
            _r = cur.fetchone()
            _run = _r[0] if _r else None
            if _run and _effective("pending", _run) != status:
                raise EpicError(
                    f"{slug!r} has a pipeline run with status {_run!r}, and a "
                    f"run outranks the stored status — writing {status!r} "
                    f"here would change nothing.\\n"
                    f"Change the RUN instead:\\n"
                    f"  press STOP on it in the dashboard, or\\n"
                    f"  curl -sX POST localhost:8000/pipeline/kill/{slug} "
                    f"-H \\"x-api-key: $DUCORN_API_TOKEN\\"\\n"
                    f"To override regardless of any run, mark it 'skipped'.")

        stamp = ("started_at = now()" if status == "running"'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (PE, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src = PE.read_text(encoding="utf-8")
print("patch_mark_honest\n")

if "Refuse a write the run would override" in src:
    sys.exit("NOTHING DONE — mark() already refuses a no-op.")

bad = False
for label, a in [("the already-running message", OLD_MSG),
                 ("the write block in mark()", OLD_MARK)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if "def _effective" not in src:
    sys.exit("NOTHING DONE — _effective is not in this module; the refusal "
             "would be guessing at the rule instead of asking it.")
print("  ok  _effective() is in this module and is what decides")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PE, PE.with_suffix(f".backup-{TAG}-{stamp}.py"))
PE.write_text(src.replace(OLD_MSG, NEW_MSG, 1).replace(OLD_MARK, NEW_MARK, 1),
              encoding="utf-8")
print(f"\nwrote {PE.name}, backup tagged {TAG}-{stamp}")

after = PE.read_text(encoding="utf-8")
try:
    py_ok(after, "product_epics.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# The advice must be gone from CODE. Both comments above quote it, and a
# check that reads comments is how three patches this session failed on their
# own explanations.
code = code_only(after)
if "--mark" in code and "pending" in code.split("--mark", 1)[1][:80]:
    sys.exit("⚠️  the message still recommends --mark pending — restore the "
             "backup.")
if "_effective(\"pending\", _run)" not in code:
    sys.exit("⚠️  mark() does not consult _effective — restore the backup.")
print("verified: it parses; mark() asks _effective, and no message "
      "recommends --mark pending.")

print("""
  python3 scripts/product_epics.py --mark ducorn-admin-rebuild-p1-config pending

should now REFUSE, and say to stop the run instead. That refusal is the
patch working — the command was doing nothing before.
""")
