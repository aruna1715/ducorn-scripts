#!/usr/bin/env python3
"""
KILL is broken on the runs you most want to kill. And the check that should
have caught it can be silenced by another table.

    python3 scripts/patch_status_truth.py            survey only
    python3 scripts/patch_status_truth.py --apply    fix it

── THE LIVE BUG ─────────────────────────────────────────────────────────────

POST /pipeline/stop/{slug} does this, in one transaction:

    UPDATE pipeline_runs SET status='stopped' ... WHERE slug=%s
    UPDATE approval_requests SET status='cancelled'
        WHERE product_slug=%s AND status='pending'

approval_requests_status_check allows pending, approved, rejected, superseded.
It does not allow 'cancelled'. So the second statement raises, the transaction
never commits, and the FIRST statement is rolled back with it — the run is not
even marked stopped.

That fails precisely when there IS a pending approval, which is the usual
reason to kill a run: it is parked at a gate and you have changed your mind.
KILL works on runs that do not need killing.

This is the gate-2 defect again, exactly: a writer added in one commit, a
constraint that was never widened to match. Same shape, same file, five days
later.

── WHY prove_db_contracts DID NOT CATCH IT ──────────────────────────────────

It scans main.py. It has a pattern for status literals. It reported "no status
literal outside the declared contracts" while this sat in the file. The reason:

    known = set()
    for vals in STATUS_CONTRACTS.values(): known |= set(vals)
    for info in live.values():             known |= info["allowed"]

`known` is the union across EVERY table. A literal is only flagged if no table
anywhere permits it. Some other table's constraint allows 'cancelled', so
writing 'cancelled' to approval_requests passed silently.

A check whose scope is "anywhere" cannot answer a question about "here". So the
scan becomes table-aware: `UPDATE <table> SET status='<value>'` is checked
against THAT table's allowed set, which is the question that was being asked
all along.

── AND THE TWO TABLES WITH NO CONSTRAINT ────────────────────────────────────

pipeline_runs and pipeline_skill_runs still have none, so any string is a valid
status and a typo produces a run that matches no dashboard filter. The survey
found 'archived' (4 rows) and 'cancelled' (1) in pipeline_runs, written by
nothing in the current code — historical, and real, so they go in the contract.
Anything already in the data is a fact, whatever I think of it.
"""
import argparse
import ast
import re
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
PROVE = Path("/Users/ducorn/DC/scripts/prove_db_contracts.py")

INTENDED = {
    "approval_requests": [
        "pending", "approved", "rejected", "superseded",
        # The stop endpoint has written this since the day it was added, and
        # the constraint has refused it every time.
        "cancelled",
    ],
    "pipeline_runs": [
        "created", "started", "running", "awaiting_approval",
        "needs_intervention", "stopped", "complete", "failed",
        # In the data, written by no current code. Historical and real.
        "archived", "cancelled",
    ],
    "pipeline_skill_runs": [
        "waiting", "running", "complete", "failed", "skipped",
    ],
}

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

found, live = {}, {}
with psycopg2.connect(DB) as conn:
    cur = conn.cursor()
    for table in INTENDED:
        cur.execute(f"SELECT status, count(*) FROM {table} GROUP BY status")
        found[table] = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("""
            SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = %s::regclass AND contype='c'
              AND pg_get_constraintdef(oid) ILIKE '%%status%%'
        """, (table,))
        row = cur.fetchone()
        live[table] = {"name": row[0],
                       "allowed": set(re.findall(r"'([^']+)'::", row[1]))} \
            if row else None

print("what the tables hold, and what they permit\n")
blocked, todo = False, []
for table, values in found.items():
    allowed = live[table]["allowed"] if live[table] else None
    print(f"── {table} " + "─" * max(0, 56 - len(table)))
    _c = live[table]["name"] if live[table] else "NONE — any string is valid"
    print(f"  constraint: {_c}")
    for v, n in sorted(values.items(), key=lambda kv: -kv[1]):
        state = "ok  " if v in INTENDED[table] else "NEW "
        print(f"  {state} {str(v):22} {n:5} row(s)")
    unexpected = [v for v in values if v is not None and v not in INTENDED[table]]
    if unexpected:
        print(f"  ⚠ not in the intended contract: {unexpected}")
        blocked = True
    if allowed is not None:
        missing = [v for v in INTENDED[table] if v not in allowed]
        if missing:
            print(f"  ⚠ the code writes {missing} and the constraint REFUSES it")
            todo.append(table)
        else:
            print("  the constraint already matches")
    else:
        todo.append(table)
    print()

if blocked:
    sys.exit("Stopped — a status is in the data that I did not anticipate.")
if not todo:
    print("Every table already agrees with the contract. Nothing to write.")
elif not args.apply:
    print(f"{len(todo)} table(s) need a constraint written or widened: "
          f"{', '.join(todo)}")
    print("Re-run with --apply.")
    sys.exit(0)

# ── the migration ────────────────────────────────────────────────────────────
if todo and args.apply:
    nxt = max((int(p.name[:3]) for p in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")),
              default=0) + 1
    path = MIGRATIONS / f"{nxt:03d}_status_truth.sql"
    lines = [f"-- {path.name}", "--",
             "-- One constraint per table, matching what the code writes.", "--",
             "-- approval_requests: /pipeline/stop writes 'cancelled' and the",
             "-- constraint refused it, so killing a run that was parked at a",
             "-- gate rolled back the whole transaction and the run was not even",
             "-- marked stopped. The same defect as gate 2, five days later.",
             "--",
             "-- pipeline_runs, pipeline_skill_runs: no constraint at all, so a",
             "-- typo produced a run that matched no dashboard filter. Values",
             "-- surveyed from the live tables before this was written.", ""]
    for table in todo:
        allowed = ", ".join(f"'{v}'" for v in INTENDED[table])
        lines += [f"ALTER TABLE {table}",
                  f"    DROP CONSTRAINT IF EXISTS {table}_status_check,",
                  f"    ADD CONSTRAINT {table}_status_check",
                  f"    CHECK (status IN ({allowed}));", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path.name}")

    # the contract in code
    src = DUCORN_DB.read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "STATUS_CONTRACTS")
    current = ast.literal_eval(node.value)
    merged = dict(current)
    for t, vals in INTENDED.items():
        merged[t] = tuple(vals)
    body = ["STATUS_CONTRACTS = {"]
    for t in sorted(merged):
        body.append(f'    "{t}": (')
        for v in merged[t]:
            body.append(f'        "{v}",')
        body.append("    ),")
    body.append("}")
    old_seg = ast.get_source_segment(src, node)
    backup = DUCORN_DB.with_name(
        f"ducorn_db.backup-statustruth-{datetime.now():%Y%m%d-%H%M%S}.py")
    backup.write_text(src, encoding="utf-8")
    DUCORN_DB.write_text(src.replace(old_seg, "\n".join(body), 1),
                         encoding="utf-8")
    try:
        ast.parse(DUCORN_DB.read_text(encoding="utf-8"))
    except SyntaxError as e:
        DUCORN_DB.write_text(src, encoding="utf-8")
        sys.exit(f"SYNTAX ERROR in ducorn_db.py ({e}) — reverted")
    print(f"ducorn_db.py: {len(merged)} tables under contract "
          f"(backup {backup.name})")

# ── the scan learns which table a literal is for ─────────────────────────────
psrc = PROVE.read_text(encoding="utf-8")
if "_UPDATE_STATUS" in psrc:
    print("prove_db_contracts is already table-aware")
else:
    anchor = '''stray = {}'''
    if psrc.count(anchor) != 1:
        print(f"could not extend the literal scan (anchor found "
              f"{psrc.count(anchor)}x) — do it by hand")
    else:
        addition = '''# Table-aware, because "is this word legal anywhere?" is not the question.
# `known` above is the union across every table, so 'cancelled' — legal on some
# other table — silenced this check while /pipeline/stop wrote it to
# approval_requests, which refuses it. The bug sat in a scanned file, matched by
# the pattern, and passed.
_UPDATE_STATUS = re.compile(
    r"UPDATE\\s+(\\w+)\\s+SET\\s+status\\s*=\\s*'([a-z_]+)'", re.I)

print("  · statuses written to a named table:")
_wrong = 0
for _src in SOURCES:
    if not _src.is_file():
        continue
    for _m in _UPDATE_STATUS.finditer(_src.read_text(errors="replace")):
        _table, _value = _m.group(1), _m.group(2).lower()
        _allowed = (live.get(_table, {}) or {}).get("allowed")
        if _allowed is None:
            _allowed = set(STATUS_CONTRACTS.get(_table, ()))
        if _allowed and _value not in _allowed:
            _wrong += 1
            print(f"       FAIL {_src.name}: UPDATE {_table} SET "
                  f"status='{_value}' — that table refuses it")
            failures.append(f"{_table} refuses {_value!r} written in {_src.name}")
if not _wrong:
    print("       ok   every table-qualified status write is permitted")

stray = {}'''
        backup = PROVE.with_name(
            f"prove_db_contracts.backup-tableaware-"
            f"{datetime.now():%Y%m%d-%H%M%S}.py")
        backup.write_text(psrc, encoding="utf-8")
        PROVE.write_text(psrc.replace(anchor, addition, 1), encoding="utf-8")
        try:
            ast.parse(PROVE.read_text(encoding="utf-8"))
        except SyntaxError as e:
            PROVE.write_text(psrc, encoding="utf-8")
            sys.exit(f"SYNTAX ERROR in prove_db_contracts.py ({e}) — reverted")
        print(f"prove_db_contracts.py: the literal scan is now table-aware "
              f"(backup {backup.name})")

print("""
Apply the migration, then prove it:

  python3 scripts/migrate.py
  python3 scripts/prove_db_contracts.py

Then KILL a run parked at a gate and it will actually stop. Before this, that
transaction rolled back and the run stayed exactly where it was.""")
