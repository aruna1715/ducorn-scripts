#!/usr/bin/env python3
"""
DuCorn schema migrations.

WHY
---
The DuCorn schema exists in exactly one place: the PostgreSQL data directory on
this Mac. There is no CREATE TABLE for pipeline_runs anywhere in the repo. If
that disk fails, the code survives in git and the shape of the data does not —
you would be reconstructing column names from SELECT statements.

That was a background worry until today, when adding a column to
approval_requests became the correct fix for the gate wiring. A schema change
needs somewhere to live.

HOW IT WORKS
------------
    python3 scripts/migrate.py --baseline   # once: capture what exists today
    python3 scripts/migrate.py --status     # what is applied, what is pending
    python3 scripts/migrate.py              # apply pending migrations

Files are scripts/migrations/NNN_name.sql, applied in filename order, each in
its own transaction — a migration that fails leaves nothing half-applied.
Applied versions are recorded in schema_migrations, so re-running is safe.

--baseline runs pg_dump --schema-only for both databases and records 000 as
already applied, because the objects it describes are already there. That file
is the disaster-recovery artifact: with it and the repo you can rebuild.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap_python import ensure_modules  # noqa: E402

# psycopg2 lives in ducorn/.venv, not in the python3 on PATH. Rather than
# telling you which interpreter to use, go and find one.
ensure_modules("psycopg2")

import psycopg2  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
DB_URL = os.environ.get("DUCORN_DATABASE_URL", "postgresql://localhost/ducorn")
# Checkpoints and LiteLLM spend live in a second database. No migrations are
# applied there — LangGraph and LiteLLM own those tables — but the baseline
# captures it, because losing it loses every paused run.
LITELLM_URL = os.environ.get("LITELLM_DATABASE_URL",
                             "postgresql://ducorn@localhost/litellm_db")


def conn():
    return psycopg2.connect(DB_URL)


def ensure_table():
    with conn() as c, c.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def applied():
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {r[0] for r in cur.fetchall()}


def is_baseline(path):
    return path.stem.startswith("000_baseline")


def available(include_baseline=False):
    """
    [(version, name, path)] sorted by version.

    Baseline dumps are excluded by default and never applied by do_apply().
    Two reasons, both of which only show up on the path you would be using in
    an emergency:

      * there are two of them (ducorn and litellm_db) sharing version 000, and
        schema_migrations.version is the primary key — applying both would
        violate it on the second insert
      * a baseline is a full CREATE TABLE dump. Replaying it against a live
        database fails on every object that already exists.

    Restoring from a baseline is a deliberate act: create the database, psql
    the file in, then run migrations from 001. It is not something that should
    happen because someone typed migrate.py on a machine with an empty
    schema_migrations table.
    """
    out = []
    for p in sorted(MIGRATIONS.glob("*.sql")):
        if is_baseline(p) and not include_baseline:
            continue
        version = p.stem.split("_", 1)[0]
        if not version.isdigit():
            print(f"⚠️  skipping {p.name} — filename must start with digits")
            continue
        out.append((version, p.stem, p))
    return out


def do_baseline():
    MIGRATIONS.mkdir(parents=True, exist_ok=True)
    ensure_table()
    stamp = f"{datetime.now():%Y-%m-%d}"
    wrote = []

    for label, url in (("ducorn", DB_URL), ("litellm_db", LITELLM_URL)):
        target = MIGRATIONS / f"000_baseline_{label}.sql"
        try:
            dump = subprocess.run(
                ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", url],
                capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            sys.exit("pg_dump not found. It ships with PostgreSQL — try\n"
                     "  export PATH=\"/opt/homebrew/opt/postgresql@16/bin:$PATH\"")
        if dump.returncode != 0:
            sys.exit(f"pg_dump failed for {label}:\n{dump.stderr.strip()}")

        header = (f"-- DuCorn schema baseline: {label}\n"
                  f"-- Captured {stamp} by scripts/migrate.py --baseline\n"
                  f"-- This describes objects that ALREADY EXIST. It is recorded as\n"
                  f"-- applied and is never replayed against a live database; its job\n"
                  f"-- is to let you rebuild from nothing.\n\n")
        target.write_text(header + dump.stdout, encoding="utf-8")
        wrote.append((target, len(dump.stdout)))
        print(f"wrote {target.name}  ({len(dump.stdout):,} bytes)")

    with conn() as c, c.cursor() as cur:
        cur.execute("INSERT INTO schema_migrations (version, name) VALUES "
                    "('000', 'baseline') ON CONFLICT (version) DO NOTHING")
    print("\nrecorded 000 baseline as applied")
    print("Commit these — they are the only copy of the schema outside that Mac.")


def do_status():
    ensure_table()
    done = applied()

    baselines = [p for p in sorted(MIGRATIONS.glob("*.sql")) if is_baseline(p)]
    if baselines:
        print("baseline (restore by hand; never auto-applied):")
        for p in baselines:
            print(f"  {p.name}  ({p.stat().st_size:,} bytes)")
        print()

    rows = available()
    if not rows:
        print(f"No migrations in {MIGRATIONS}")
        return
    print("migrations:")
    for version, name, _ in rows:
        mark = "applied" if version in done else "PENDING"
        print(f"  {version}  {mark:<8}  {name}")
    orphans = done - {v for v, _, _ in rows} - {"000"}
    if orphans:
        print(f"\n⚠️  recorded but no file: {', '.join(sorted(orphans))}")
        print("   Someone applied a migration whose file is gone. Do not "
              "renumber; find it in git history.")


def do_apply():
    ensure_table()
    done = applied()
    pending = [(v, n, p) for v, n, p in available() if v not in done]
    if not pending:
        print("Nothing to apply — schema is up to date.")
        return

    for version, name, path in pending:
        sql = path.read_text(encoding="utf-8")
        print(f"applying {version} {name} ...", end=" ", flush=True)
        # One transaction per migration. A failure leaves the database exactly
        # as it was and stops the run, rather than applying 3 of 5 and leaving
        # you to work out which.
        c = psycopg2.connect(DB_URL)
        try:
            with c, c.cursor() as cur:
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations (version, name) "
                            "VALUES (%s, %s)", (version, name))
            print("ok")
        except Exception as e:
            print("FAILED")
            sys.exit(f"\n{version} {name} failed and was rolled back:\n  {e}\n\n"
                     f"Nothing after it was attempted.")
        finally:
            c.close()
    print(f"\n{len(pending)} migration(s) applied.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--baseline", action="store_true",
                   help="capture the current schema as 000 and mark it applied")
    g.add_argument("--status", action="store_true", help="show applied/pending")
    args = ap.parse_args()

    if args.baseline:
        do_baseline()
    elif args.status:
        do_status()
    else:
        do_apply()
