#!/usr/bin/env python3
"""
Every status the code can write must be one the database will accept.

    cd ~/DC && python3 scripts/prove_db_contracts.py

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

    ❌ Approved, but I could not record the design choice
       new row for relation "approval_requests" violates check constraint
       "approval_requests_status_check"

Gate 2 marks the variants you did not pick as 'superseded'. The column to
record that (superseded_by) was added in migration 002, along with the code
that writes it. The CHECK constraint on the column being written was not
touched, and still read:

    CHECK (status IN ('pending', 'approved', 'rejected'))

Every piece was individually correct. Nothing compared them. It could not
surface until a real founder approved a real design, which was tonight, on a
paid run, at the gate.

Migration 005 fixes that instance. This closes the class.

── WHAT IT CHECKS ───────────────────────────────────────────────────────────

  1. It asks PostgreSQL for every CHECK constraint on a status column, in both
     databases. Discovered, not listed — a constraint added next month is
     covered without anyone editing this file.

  2. It reads the permitted values out of each constraint and compares them
     with the corresponding tuple in ducorn_db.py, in BOTH directions. A value
     the code can write that the database refuses is the bug we just had. A
     value the database allows that the code never writes is dead vocabulary,
     reported quietly.

  3. It scans the source for status literals near a write to one of those
     tables and flags any that are in neither set — the case where someone
     invents a status inline instead of using the constant.

Advisory where it must guess (3), authoritative where it cannot (1 and 2).

── WHAT IT DOES NOT DO ──────────────────────────────────────────────────────

It writes nothing and it fixes nothing. When it fails, the fix is a migration,
because a constraint is schema and schema changes belong in the chain where
they can be replayed onto a rebuilt machine. Loosening the constraint by hand
in psql would make this pass and leave the next disk without it.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from bootstrap_python import ensure_modules  # noqa

ensure_modules("psycopg2")

import psycopg2  # noqa

DC = Path("/Users/ducorn/DC")
DBS = {
    "ducorn": "postgresql://ducorn@localhost/ducorn",
    "litellm_db": "postgresql://ducorn@localhost/litellm_db",
}

# Where the code's side of each contract lives. One definition per column, so
# a status can be added in exactly one place and this check tells you the
# migration is missing.
from ducorn_db import STATUS_CONTRACTS  # noqa

SOURCES = [
    DC / "ducorn/flows/langgraph_flow.py",
    DC / "ducorn/skill_runner.py",
    DC / "ducorn/slack_bot.py",
    DC / "ducorn-products/products/ducorn-activity-api/main.py",
]

# 'x'::character varying inside a constraint body
_QUOTED = re.compile(r"'([^']+)'::")
# a quoted word within a few characters of a status assignment
_NEAR_STATUS = re.compile(r"status\s*(?:=|:)\s*['\"]([a-z_]+)['\"]", re.I)

failures, notes = [], []


def constraints(dsn):
    """Every CHECK constraint mentioning a status column, from the catalog."""
    out = {}
    with psycopg2.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            WHERE con.contype = 'c' AND ns.nspname = 'public'
            ORDER BY rel.relname
        """)
        for table, name, body in cur.fetchall():
            if "status" not in body:
                continue
            allowed = set(_QUOTED.findall(body))
            if not allowed:                       # a range check, not a list
                continue
            out[table] = {"constraint": name, "allowed": allowed}
    return out


print("\n── what the database will accept ───────────────────────────────────")
live = {}
for dbname, dsn in DBS.items():
    try:
        found = constraints(dsn)
    except Exception as e:
        failures.append(f"could not read {dbname}: {type(e).__name__}: {e}")
        print(f"  FAIL {dbname}: {type(e).__name__}: {e}")
        continue
    for table, info in found.items():
        live[table] = info
        print(f"  {table}.status  {sorted(info['allowed'])}")
if not live:
    failures.append("no status CHECK constraints found at all — is this the "
                    "right database?")

print("\n── against what the code declares ──────────────────────────────────")
for table, declared in sorted(STATUS_CONTRACTS.items()):
    declared = set(declared)
    if table not in live:
        print(f"  note {table}: declared in code, no CHECK constraint in the "
              f"database — nothing enforces it")
        notes.append(f"{table} has no constraint")
        continue

    allowed = live[table]["allowed"]
    unwritable = declared - allowed
    unused = allowed - declared

    if unwritable:
        failures.append(
            f"{table}: the code can write {sorted(unwritable)}, and "
            f"{live[table]['constraint']} will reject it. Add a migration "
            f"widening the constraint — this is the gate-2 failure exactly.")
        print(f"  FAIL {table}: code writes {sorted(unwritable)}, database "
              f"refuses it")
    else:
        print(f"  ok   {table}: all {len(declared)} declared statuses are "
              f"accepted")
    if unused:
        print(f"       (database also allows {sorted(unused)}, which the code "
              f"never writes)")
        notes.append(f"{table} allows unused {sorted(unused)}")

print("\n── status literals loose in the source ─────────────────────────────")
known = set()
for vals in STATUS_CONTRACTS.values():
    known |= set(vals)
for info in live.values():
    known |= info["allowed"]

# Advisory. It cannot tell which table a literal is destined for, so it only
# reports words that no constraint and no contract has heard of at all.
# Table-aware, because "is this word legal anywhere?" is not the question.
# `known` above is the union across every table, so 'cancelled' — legal on some
# other table — silenced this check while /pipeline/stop wrote it to
# approval_requests, which refuses it. The bug sat in a scanned file, matched by
# the pattern, and passed.
_UPDATE_STATUS = re.compile(
    r"UPDATE\s+(\w+)\s+SET\s+status\s*=\s*'([a-z_]+)'", re.I)

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

stray = {}
for src in SOURCES:
    if not src.is_file():
        continue
    for m in _NEAR_STATUS.finditer(src.read_text(errors="replace")):
        word = m.group(1).lower()
        if word not in known and word not in ("status", "none", "null"):
            stray.setdefault(word, set()).add(src.name)
if stray:
    for word, files in sorted(stray.items()):
        print(f"  ?    {word!r} written as a status in {', '.join(sorted(files))}"
              f" — in no contract and no constraint")
        notes.append(f"unknown status literal {word!r}")
else:
    print("  ok   no status literal outside the declared contracts")

print()
if failures:
    print(f"{len(failures)} FAILED:")
    for f in failures:
        print(f"  · {f}")
    print("\nThe fix is a migration in scripts/migrations/, not a hand edit in "
          "psql — a constraint changed by hand is absent from the next rebuild.")
    sys.exit(1)

print("code and schema agree on every status.")
if notes:
    print(f"({len(notes)} advisory note(s) above — none of them blocking.)")
sys.exit(0)
