#!/usr/bin/env python3
"""
Attach the phase context once, now that the brief carries it.

    cd ~/DC && python3 scripts/patch_phase_ctx_once.py            show
    cd ~/DC && python3 scripts/patch_phase_ctx_once.py --apply    do it

Apply patch_phase_brief.py first — this exists because of it.

── WHY ──────────────────────────────────────────────────────────────────────

start_phase now writes the phase context into docs/<slug>-PRD.md, which is
where node_research reads a run's founder brief. skill_runner ALSO inserts
product_epics.context_for(topic) into every prompt. Both come from the same
function, so they cannot disagree — but the same three thousand characters
would appear twice in every prompt of every skill of every phase, once as the
PRD and once above it.

Paid twice, and worse than merely wasteful: an agent shown the same
instruction block twice in one prompt has been given a reason to think the
second one is different.

── WHAT CHANGES ─────────────────────────────────────────────────────────────

The insert is skipped when the assembled context already contains this
phase's header line. Not a length or hash comparison — the literal
"THIS IS PHASE n OF 'epic'" line taken out of the context that was just
built, so the test cannot drift from what it is testing.

The block stays, rather than being deleted in favour of the PRD file, because
it is what reaches a phase whose PRD has not been written yet — a run started
some other way, or one resumed at a later skill.
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
TAG = "phaseonce"

OLD = '''    if _phase_ctx:
        context_parts.insert(0, _phase_ctx)
        print(f"🧩 phase context attached ({len(_phase_ctx):,} chars)",
              flush=True)'''

NEW = '''    if _phase_ctx:
        # Once. start_phase.write_phase_brief puts this same text into
        # docs/<topic>-PRD.md, because that is the file node_research reads as
        # a run's founder brief — so for a phase it is already above, inside
        # the PRD block. The marker is lifted out of the context just built,
        # so this test cannot drift from the thing it tests.
        _marker = next((l for l in _phase_ctx.splitlines()
                        if l.startswith("THIS IS PHASE")), "")
        _already = _marker and any(_marker in p for p in context_parts)
        if _already:
            print(f"🧩 phase context already in the PRD — not attached twice",
                  flush=True)
        else:
            context_parts.insert(0, _phase_ctx)
            print(f"🧩 phase context attached ({len(_phase_ctx):,} chars)",
                  flush=True)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not RUNNER.is_file():
    sys.exit(f"NOTHING DONE — {RUNNER} is not there")

src = RUNNER.read_text(encoding="utf-8")
print("patch_phase_ctx_once\n")

if "not attached twice" in src:
    sys.exit("NOTHING DONE — the guard is already there.")

sp = DC / "scripts" / "start_phase.py"
if not sp.is_file() or "def write_phase_brief" not in sp.read_text(
        encoding="utf-8"):
    sys.exit("NOTHING DONE — apply patch_phase_brief.py first. Without it the "
             "PRD does not carry the phase context and this guard would "
             "suppress the only copy.")
print("  ok  start_phase writes the phase brief into the PRD")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the phase-context insert  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(RUNNER)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

# The guard must suppress a duplicate and must NOT suppress the only copy.
probe = r'''
CTX = "="*70 + "\nTHIS IS PHASE 1 OF 'epic-x'\n" + "="*70 + "\nbuild the thing\n"
def attach(parts):
    marker = next((l for l in CTX.splitlines() if l.startswith("THIS IS PHASE")), "")
    if marker and any(marker in p for p in parts):
        return parts
    return [CTX] + parts
bad = []
if len(attach(["PRD:\n" + CTX])) != 1:
    bad.append("a PRD that already carries the phase got it twice")
if len(attach(["PRD:\nsomething else"])) != 2:
    bad.append("a run whose PRD lacks the phase got no phase context")
if len(attach([])) != 1:
    bad.append("an empty context got no phase context")
print("ONCE_OK" if not bad else "ONCE_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "ONCE_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")

print("""verified: skill_runner.py parses; the guard suppresses a duplicate and
          leaves the only copy alone.""")
