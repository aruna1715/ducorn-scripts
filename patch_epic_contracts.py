#!/usr/bin/env python3
"""
Declare the epic statuses where prove_db_contracts.py looks for them.

    cd ~/DC && python3 scripts/patch_epic_contracts.py            show
    cd ~/DC && python3 scripts/patch_epic_contracts.py --apply    do it

Apply migration 009 first.

── WHY ──────────────────────────────────────────────────────────────────────

Migration 009 adds CHECK constraints on product_epics.status and
epic_phases.status. prove_db_contracts.py reads every status constraint out
of the catalog and compares it with STATUS_CONTRACTS in ducorn_db.py, in both
directions — so a constraint with no matching tuple is reported as vocabulary
the code never writes.

That check exists because gate 2 once failed on a real founder approval, on a
paid run: the code wrote 'superseded' and the constraint had never been told
about it. Adding two tables and not telling it is how the same thing happens
again with 'skipped'.

The values here must match 009 exactly. They are not a second opinion — they
are the code's half of a contract the prover compares against the database's
half.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
DB = DC / "scripts" / "ducorn_db.py"
TAG = "epiccontracts"

OLD = '''    "pipeline_skill_runs": (
        "waiting",
        "running",
        "complete",
        "failed",
        "skipped",
    ),
}'''

NEW = '''    "pipeline_skill_runs": (
        "waiting",
        "running",
        "complete",
        "failed",
        "skipped",
    ),
    # ── epics: a product built over several runs (migration 009) ──────────
    # An epic's status is DERIVED from its phases by product_epics.mark(),
    # never set by hand. Two places deciding whether an epic is finished is
    # how they come to disagree.
    "product_epics": (
        "planned",
        "running",
        "complete",
        "failed",
        "abandoned",
    ),
    # Same vocabulary as pipeline_skill_runs on purpose: a phase and a skill
    # are both "a unit of work inside something larger", and one word for one
    # idea is the whole argument of this file.
    "epic_phases": (
        "pending",
        "running",
        "complete",
        "failed",
        "skipped",
    ),
}'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not DB.is_file():
    sys.exit(f"NOTHING DONE — {DB} is not there")

src = DB.read_text(encoding="utf-8")
print("patch_epic_contracts\n")

if '"product_epics"' in src:
    sys.exit("NOTHING DONE — the epic contracts are already declared.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the end of STATUS_CONTRACTS  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(DB, DB.with_suffix(f".backup-{TAG}-{stamp}.py"))
DB.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {DB.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(DB)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

# The tuples here and the constants in product_epics.py are two statements of
# one fact. Compare them rather than trusting that I typed both the same.
probe = f'''
import sys
sys.path.insert(0, "{DC}/scripts")
from ducorn_db import STATUS_CONTRACTS
import product_epics as pe
bad = []
if tuple(STATUS_CONTRACTS["product_epics"]) != tuple(pe.EPIC_STATUS):
    bad.append("product_epics: ducorn_db %s vs product_epics %s"
               % (STATUS_CONTRACTS["product_epics"], pe.EPIC_STATUS))
if tuple(STATUS_CONTRACTS["epic_phases"]) != tuple(pe.PHASE_STATUS):
    bad.append("epic_phases: ducorn_db %s vs product_epics %s"
               % (STATUS_CONTRACTS["epic_phases"], pe.PHASE_STATUS))
print("MATCH_OK" if not bad else "MATCH_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "MATCH_OK" not in r.stdout:
    print("\n⚠️  " + (r.stdout + r.stderr).strip()[-400:])
    print("    (if this is only a missing psycopg2, run prove_db_contracts "
          "under ducorn/.venv instead)")
else:
    print("verified: ducorn_db.py and product_epics.py agree on both "
          "vocabularies.")

print("""
Now check the database's half:
  python3 scripts/prove_db_contracts.py
""")
