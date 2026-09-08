#!/usr/bin/env python3
"""
A phase must be told which phase it is. Nothing was telling it.

    cd ~/DC && python3 scripts/patch_epic_context.py            show
    cd ~/DC && python3 scripts/patch_epic_context.py --apply    do it

── THE GAP ──────────────────────────────────────────────────────────────────

product_epics.context_for() builds the handoff — what phase this is, what the
whole product is, what the earlier phases produced, and the instruction not
to start again. It is tested. Nothing calls it.

So starting phase 1 today would run it as an ordinary product with no brief
at all: the phase's brief lives in epic_phases.brief, and the only route into
a run is docs/<topic>-PRD.md, which does not exist for a phase that has not
run yet. The agent would be handed a slug and nothing else.

── WHERE IT GOES ────────────────────────────────────────────────────────────

Into context_parts in skill_runner.main(), beside where the stack context is
attached — deliberately the same place, for the same reason it was moved
there:

    "This used to be attached in node_research and nowhere else, so the
     researcher had the facts and the WRITER did not."

Every skill of a phase builds its prompt from context_parts. Attaching here
means 01 and 04 and 07 all know what they are continuing, whichever node
launched them and whether it was the CLI at all.

Inserted at position 0. The phase brief is the INSTRUCTION — what to build
now — and it belongs ahead of the background.

── FAILING ──────────────────────────────────────────────────────────────────

If the epic tables are absent or product_epics is not installed, every slug
is a standalone product and this adds nothing — which is what was true
before epics existed.

Any OTHER failure raises. A phase that runs without its brief does not
degrade; it builds the wrong product, passes its gates, and looks fine until
someone opens it.
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
EPICS = DC / "scripts" / "product_epics.py"
TAG = "epicctx"

OLD = '''    # Context file if provided
    if args.context_file and Path(args.context_file).exists():'''

NEW = '''    # WHICH PHASE THIS IS — first, because it is the instruction.
    #
    # A phase's brief lives in epic_phases.brief. The only other route into a
    # run is docs/<topic>-PRD.md, which does not exist for a phase that has
    # not run yet, so without this the agent gets a slug and nothing else.
    #
    # Attached here, beside the stack context, for the reason that block
    # records: attached at one node it reaches one agent, attached here it
    # reaches every skill of the run.
    try:
        import product_epics as _pe
        _phase_ctx = _pe.context_for(topic)
    except ImportError:
        _phase_ctx = ""          # no epics on this machine
    except Exception as _e:
        if type(_e).__name__ == "EpicsNotInstalled":
            _phase_ctx = ""      # migration 009 has not run; no epic exists
        else:
            # Not degraded — wrong. A phase without its brief builds the
            # wrong product, passes its gates, and looks fine until someone
            # opens it.
            raise RuntimeError(
                f"Could not read the phase context for '{topic}': {_e}\\n"
                f"Refusing to run a phase without knowing what it is."
            ) from _e
    if _phase_ctx:
        context_parts.insert(0, _phase_ctx)
        print(f"🧩 phase context attached ({len(_phase_ctx):,} chars)",
              flush=True)

    # Context file if provided
    if args.context_file and Path(args.context_file).exists():'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, EPICS):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

src = RUNNER.read_text(encoding="utf-8")
print("patch_epic_context\n")

if "phase context attached" in src:
    sys.exit("NOTHING DONE — skill_runner already attaches the phase context.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the context_parts block  ({n} match)")
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

print("""
verified: skill_runner.py parses.

See the real thing, for free, before spending anything:
  cd ~/DC/ducorn && .venv/bin/python skill_runner.py \\
      --topic ducorn-admin-rebuild-p1-config --skill 01 --dry-run

The prompt should open with THIS IS PHASE 1 OF 'ducorn-admin-rebuild'.
""")
