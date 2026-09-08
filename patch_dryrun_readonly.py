#!/usr/bin/env python3
"""
A dry run should not be refused because a phase is running.

    cd ~/DC && python3 scripts/patch_dryrun_readonly.py            show
    cd ~/DC && python3 scripts/patch_dryrun_readonly.py --apply    do it

Needs scripts/patchlib.py and patch_phase_brief.py.

── WHAT HAPPENED ────────────────────────────────────────────────────────────

    python3 scripts/start_phase.py ducorn-admin-rebuild --dry-run
    NOTHING STARTED — phase 1 (Configuration) is already running as
    'ducorn-admin-rebuild-p1-config'.

── WHY IT IS WRONG ──────────────────────────────────────────────────────────

--dry-run writes nothing, launches nothing and spends nothing. main() asked
next_phase() — "which phase may START now" — before it looked at what it had
been asked to do, so a read-only inspection inherited the start path's
refusals.

The moment you most want to read a phase's brief is right after a run of it
died, which is exactly when that question answers "no".

── THE FIX ──────────────────────────────────────────────────────────────────

The dry run answers its own question first: the lowest phase that is not
complete or skipped — the one in flight, or the one that would be next — and
prints its brief along with its status.

It does NOT re-implement next_phase. It deliberately asks something weaker:
"which phase is this about", not "which phase may start". The start path
below still asks next_phase and still refuses, because that is the question
that matters when something is about to spend money.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
SP = DC / "scripts" / "start_phase.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "dryro"

OLD_EARLY = '''    epic = pe.get(a.epic)
    if epic is None:
        die(f"no epic named {a.epic!r}. "
            f"python3 scripts/product_epics.py --list")

    try:
        phase = pe.next_phase(a.epic)'''

NEW_EARLY = '''    epic = pe.get(a.epic)
    if epic is None:
        die(f"no epic named {a.epic!r}. "
            f"python3 scripts/product_epics.py --list")

    # BEFORE the startability question. --dry-run writes nothing and spends
    # nothing, and asking next_phase() first meant "phase 1 is already
    # running" refused to SHOW the brief — at the one moment you want to read
    # it, which is after a run of that phase has died.
    #
    # This asks something weaker than next_phase on purpose: which phase is
    # this ABOUT, not which phase may start. The start path below still asks
    # the real question, because that is the one spending money.
    if a.dry_run:
        live = [p for p in epic["phases"]
                if p["status"] not in ("complete", "skipped")]
        if not live:
            print(f"{a.epic}: every phase is finished — nothing to show.")
            return 0
        p = live[0]
        dslug = p["phase_slug"]
        try:
            text = brief_text(dslug)
        except Exception as e:
            die(f"the brief could not be built: {e}")
        print(f"{a.epic}  →  phase {p['seq']} of {len(epic['phases'])} — "
              f"{p['title']}  [{p['status']}]")
        print(f"\\n── the brief start would write ({len(text):,} chars) ──")
        print(f"   to   {DOCS / (dslug + '-PRD.md')}")
        print(f"   read by node_research as the founder brief, first act of "
              f"the run\\n")
        head = text.splitlines()
        for line in head[:40]:
            print("   " + line)
        if len(head) > 40:
            print(f"   … and {len(head) - 40} more lines")
        print("""
Nothing was written and nothing was spent.

This proves the brief exists and is not empty — the thing the failed run
tripped on. It does not prove the run succeeds; only starting it does.
""")
        return 0

    try:
        phase = pe.next_phase(a.epic)'''

OLD_LATE = '''    if a.dry_run:
        # This used to run skill_runner --skill 01. skill_runner is not where
        # a run begins — langgraph_flow.node_research is — so the check
        # exercised an entry point the run does not use and passed on code
        # that could not start. It now shows the one thing node_research
        # reads, and claims nothing beyond that.
        try:
            text = brief_text(slug)
        except Exception as e:
            die(f"the brief could not be built: {e}")
        target = DOCS / f"{slug}-PRD.md"
        print(f"\\n── the brief start would write ({len(text):,} chars) ──")
        print(f"   to   {target}")
        print(f"   read by node_research as the founder brief, first act of "
              f"the run\\n")
        head = text.splitlines()
        for line in head[:40]:
            print("   " + line)
        if len(head) > 40:
            print(f"   … and {len(head) - 40} more lines")
        print(f"""
Nothing was written and nothing was spent.

This proves the brief exists and is not empty — the thing the failed run
tripped on. It does not prove the run succeeds; only starting it does.
""")
        return 0

'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (SP, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src = SP.read_text(encoding="utf-8")
print("patch_dryrun_readonly\n")

if "BEFORE the startability question" in src:
    sys.exit("NOTHING DONE — the dry run already runs before the gate.")
if "def brief_text" not in src:
    sys.exit("NOTHING DONE — apply patch_phase_brief.py first.")
print("  ok  brief_text() is available")

bad = False
for label, a in [("the epic lookup in main()", OLD_EARLY),
                 ("the current dry-run block", OLD_LATE)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(SP, SP.with_suffix(f".backup-{TAG}-{stamp}.py"))
out = src.replace(OLD_LATE, "", 1).replace(OLD_EARLY, NEW_EARLY, 1)
SP.write_text(out, encoding="utf-8")
print(f"\nwrote {SP.name}, backup tagged {TAG}-{stamp}")

after = SP.read_text(encoding="utf-8")
try:
    py_ok(after, "start_phase.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

code = code_only(after)
if code.count("if a.dry_run:") != 1:
    sys.exit(f"⚠️  {code.count('if a.dry_run:')} dry-run blocks in code — "
             f"restore the backup.")
# The order is the fix: the dry run must be decided before next_phase is
# asked, or it inherits the refusal again. Position in the STRIPPED source,
# so a comment mentioning next_phase cannot satisfy it.
i_dry, i_next = code.find("if a.dry_run:"), code.find("pe.next_phase(a.epic)")
if not (0 <= i_dry < i_next):
    sys.exit("⚠️  the dry run is still after the startability check — "
             "restore the backup.")
print("verified: it parses; one dry-run block, and it is decided before "
      "next_phase is asked.")

print("""
  python3 scripts/start_phase.py ducorn-admin-rebuild --dry-run

It will now print the phase-1 brief and show its status as running — which
is the stuck row, not a live process. patch_run_status.py explains that one.
""")
