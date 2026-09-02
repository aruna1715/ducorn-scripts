#!/usr/bin/env python3
"""
Give pipeline_runs and pipeline_skill_runs the constraint approval_requests has.

    python3 scripts/patch_status_constraints.py            survey only
    python3 scripts/patch_status_constraints.py --apply    write the migration

── WHY ──────────────────────────────────────────────────────────────────────

At gate 2 the pipeline tried to write 'superseded' into approval_requests and
the database refused it: the column had a CHECK constraint and migration 002
had added the writer without widening it. That cost a stalled gate and a repair
script.

The lesson taken from it was STATUS_CONTRACTS in ducorn_db.py — the allowed
values written down once, with prove_db_contracts.py comparing them against
what the database actually enforces, in both directions.

Except two tables were never brought in. pipeline_runs and pipeline_skill_runs
have no CHECK constraint at all, so any string at all is a valid status. A typo
in a status literal is not a crash; it is a run that never matches the dashboard
filter and quietly does not exist.

── WHY THIS IS NOT A PLAIN .sql FILE ────────────────────────────────────────

A CHECK constraint is validated against every existing row. If any run carries a
status I did not anticipate, applying it fails — and the honest way to write
this is to look at the data first, not to guess a list from grepping the code
and hope.

So: survey, compare, and only write the migration when every value already in
the tables is accounted for. If something unexpected is in there, this prints it
and stops. That is information, not a failure.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from bootstrap_python import ensure_modules  # noqa: E402

ensure_modules("psycopg2")
import psycopg2  # noqa: E402

DB = "postgresql://ducorn@localhost/ducorn"
MIGRATIONS = Path("/Users/ducorn/DC/scripts/migrations")
DUCORN_DB = Path("/Users/ducorn/DC/scripts/ducorn_db.py")

# What the code writes, gathered from langgraph_flow, skill_runner and the API.
# The survey below is the authority on whether this is complete.
INTENDED = {
    "pipeline_runs": [
        "created",             # the row exists, nothing has run
        "started",             # a process was launched
        "running",             # a node is working
        "awaiting_approval",   # parked at a gate, process exited
        "needs_intervention",  # failed in a way a human must look at
        "stopped",             # killed deliberately
        "complete",
        "failed",
    ],
    "pipeline_skill_runs": [
        "waiting",
        "running",
        "complete",
        "failed",
        "skipped",
    ],
}

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true",
                help="write the migration (still run migrate.py after)")
args = ap.parse_args()

print("surveying what is actually in the tables\n")
found, existing_constraints = {}, {}
with psycopg2.connect(DB) as conn:
    cur = conn.cursor()
    for table in INTENDED:
        cur.execute(f"SELECT status, count(*) FROM {table} "
                    f"GROUP BY status ORDER BY 2 DESC")
        found[table] = {(r[0] if r[0] is not None else None): r[1]
                        for r in cur.fetchall()}
        cur.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = %s::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%%status%%'
        """, (table,))
        existing_constraints[table] = [r[0] for r in cur.fetchall()]

blocked = False
for table, values in found.items():
    print(f"── {table} " + "─" * (58 - len(table)))
    if existing_constraints[table]:
        print(f"  already constrained by "
              f"{', '.join(existing_constraints[table])} — nothing to do")
        continue
    if not values:
        print("  no rows")
    for v, n in values.items():
        mark = "ok  " if v in INTENDED[table] else ("NULL" if v is None
                                                    else "NEW ")
        print(f"  {mark} {str(v):22} {n:5} row(s)")
    unexpected = [v for v in values if v is not None and v not in INTENDED[table]]
    nulls = values.get(None, 0)
    if unexpected:
        print(f"\n  {len(unexpected)} status value(s) I did not anticipate: "
              f"{unexpected}")
        print("  Not applying. Either they are real and belong in the contract,")
        print("  or they are typos worth fixing before the constraint bites.")
        blocked = True
    if nulls:
        print(f"\n  {nulls} row(s) have a NULL status. The constraint will "
              f"allow NULL —")
        print("  a CHECK passes on NULL — so these are unaffected either way.")

if blocked:
    sys.exit("\nStopped. Tell me the unexpected values and I will widen the "
             "contract to match reality.")

todo = [t for t in INTENDED if not existing_constraints[t]]
if not todo:
    print("\nBoth tables are already constrained. Nothing to write.")
    sys.exit(0)

if not args.apply:
    print(f"\nEverything present is accounted for. {len(todo)} table(s) would "
          f"gain a constraint.")
    print("Re-run with --apply to write the migration.")
    sys.exit(0)

# ── the migration ────────────────────────────────────────────────────────────
existing = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
nxt = max((int(p.name[:3]) for p in existing), default=0) + 1
path = MIGRATIONS / f"{nxt:03d}_pipeline_status_check.sql"

lines = [f"-- {path.name}",
         "--",
         "-- The constraint approval_requests already had, for the two tables",
         "-- that never got one.",
         "--",
         "-- At gate 2 a status the database refused stalled a run, because the",
         "-- writer and the constraint were changed in different commits. These",
         "-- two tables had the opposite problem: no constraint at all, so a",
         "-- typo in a status literal produced a run that silently matched no",
         "-- dashboard filter and effectively did not exist.",
         "--",
         "-- The values below were surveyed from the live tables before this",
         "-- file was written; every status present is included.",
         ""]
for table in todo:
    allowed = ", ".join(f"'{v}'" for v in INTENDED[table])
    lines += [f"ALTER TABLE {table}",
              f"    DROP CONSTRAINT IF EXISTS {table}_status_check,",
              f"    ADD CONSTRAINT {table}_status_check",
              f"    CHECK (status IN ({allowed}));",
              ""]
path.write_text("\n".join(lines), encoding="utf-8")
print(f"\nwrote {path}")

# ── and the contract in code, so prove_db_contracts covers them ──────────────
src = DUCORN_DB.read_text(encoding="utf-8")
if "pipeline_runs" in src.split("STATUS_CONTRACTS", 1)[1][:1200]:
    print("ducorn_db.py already lists these tables")
else:
    entry = []
    for table in INTENDED:
        entry.append(f'    "{table}": (')
        for v in INTENDED[table]:
            entry.append(f'        "{v}",')
        entry.append("    ),")
    anchor = 'STATUS_CONTRACTS = {\n'
    if src.count(anchor) != 1:
        sys.exit(f"could not find STATUS_CONTRACTS in {DUCORN_DB} — the "
                 f"migration is written; add the entries by hand.")
    backup = DUCORN_DB.with_name(
        f"ducorn_db.backup-pipelinestatus-{datetime.now():%Y%m%d-%H%M%S}.py")
    backup.write_text(src, encoding="utf-8")
    DUCORN_DB.write_text(
        src.replace(anchor, anchor + "\n".join(entry) + "\n", 1),
        encoding="utf-8")
    import ast
    try:
        ast.parse(DUCORN_DB.read_text(encoding="utf-8"))
    except SyntaxError as e:
        DUCORN_DB.write_text(src, encoding="utf-8")
        sys.exit(f"SYNTAX ERROR in ducorn_db.py ({e}) — reverted. The "
                 f"migration is written; add the entries by hand.")
    print(f"added both tables to STATUS_CONTRACTS  (backup {backup.name})")

print(f"""
Apply it, then prove code and schema agree:

  python3 scripts/migrate.py
  python3 scripts/prove_db_contracts.py

prove_db_contracts compares both directions — a value the code writes that the
database refuses, and a value the database allows that no code writes. That is
what makes this a contract rather than two lists.""")
