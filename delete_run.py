#!/usr/bin/env python3
"""
Remove a pipeline run completely: process, rows, checkpoints and files.

    python3 scripts/delete_run.py <slug>              # dry run
    python3 scripts/delete_run.py <slug> --apply

DRY RUN BY DEFAULT. Files are MOVED to ~/DC/_deleted/<slug>-<timestamp>/,
never unlinked, so a mistake is a mv away from being undone.

WHY THIS EXISTS
---------------
There was no delete. The only thing that removed a run anywhere in the repo
was a raw `DELETE FROM pipeline_runs` inside test_dashboard.py, which leaves:

  * the langgraph_flow.py process still running — it survives its own deleted
    row and carries on writing PRD files for a product that no longer exists.
    That happened on 29 August; two orphans had to be killed by PID.
  * pipeline_skill_runs (cascades, so this one is fine)
  * approval_requests and design_variants, which reference the product by TEXT,
    not by foreign key, so nothing cascades — pending approvals for a deleted
    run stay pending forever
  * LangGraph checkpoints in litellm_db across three tables, so re-creating a
    product with the same name resumes the DEAD run's state
  * docs/, pdfs/, products/ and the log

The checkpoint one is the nastiest: delete a test product, make another with
the same name, and it silently resumes mid-pipeline from the old run.

MATCHING FILES PRECISELY
------------------------
A glob of "<slug>-*" is wrong and dangerous. Deleting ducorn-run-history would
match ducorn-run-history-v2-PRD.md and take a different product's files with
it — a direct violation of "product 1 must never touch product 2's files".

So a file belongs to this run only if its stem is the slug exactly, or begins
with "<slug>-" AND no other known product slug is a longer prefix of it. Known
slugs come from pipeline_runs, so the rule derives from reality rather than
from me guessing at naming conventions.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap_python import ensure_modules  # noqa: E402

ensure_modules("psycopg2")
import psycopg2  # noqa: E402

DUCORN_DB  = os.environ.get("DUCORN_DATABASE_URL", "postgresql://localhost/ducorn")
LITELLM_DB = os.environ.get("LITELLM_DATABASE_URL",
                            "postgresql://ducorn@localhost/litellm_db")
ROOT     = Path("/Users/ducorn/DC")
PRODUCTS = ROOT / "ducorn-products"
TRASH    = ROOT / "_deleted"


def known_slugs():
    with psycopg2.connect(DUCORN_DB) as c, c.cursor() as cur:
        cur.execute("SELECT slug FROM pipeline_runs WHERE slug IS NOT NULL")
        return {r[0] for r in cur.fetchall()}


def owns(filename, slug, others):
    """Does this file belong to `slug` and not to a longer-named sibling?"""
    stem = Path(filename).stem
    # Strip a second extension, e.g. foo-gstack-checkpoint.json -> stem already ok
    if stem == slug:
        return True
    if not stem.startswith(slug + "-"):
        return False
    # A longer known slug that also prefixes this stem owns it, not us.
    for other in others:
        if other != slug and len(other) > len(slug) and stem.startswith(other):
            return False
    return True


def find_processes(slug):
    """PIDs of langgraph_flow.py running THIS slug."""
    try:
        out = subprocess.run(["pgrep", "-fl", "langgraph_flow.py"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception as e:
        print(f"  ⚠️  could not run pgrep ({e}) — check for orphans by hand")
        return []
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        pid, cmd = parts[0], " ".join(parts[1:])
        # The slug is a positional argument, so match it as a whole word —
        # otherwise deleting 'foo' would kill a run of 'foo-v2'.
        if any(a == slug for a in cmd.split()):
            pids.append(int(pid))
    return pids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    slug, apply = args.slug, args.apply

    if not slug or "/" in slug or slug.startswith("."):
        sys.exit(f"Refusing to act on slug {slug!r}")

    others = known_slugs()
    if slug not in others:
        print(f"⚠️  '{slug}' has no pipeline_runs row. Continuing — there may "
              f"still be files, checkpoints or a process to clean up.\n")

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    dest = TRASH / f"{slug}-{stamp}"
    print("=" * 68)
    print(f"{'APPLYING' if apply else 'DRY RUN — nothing will change'}: {slug}")
    print("=" * 68)

    # ── 1. Processes ─────────────────────────────────────────────────────────
    pids = find_processes(slug)
    print(f"\nprocesses ({len(pids)}):")
    for pid in pids:
        print(f"    PID {pid}  langgraph_flow.py {slug}")
    if not pids:
        print("    none running")
    if apply and pids:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
        time.sleep(3)
        for pid in pids:
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
                print(f"    PID {pid} ignored SIGTERM — killed")
            except ProcessLookupError:
                print(f"    PID {pid} stopped")

    # ── 2. Database rows ─────────────────────────────────────────────────────
    counts = {}
    with psycopg2.connect(DUCORN_DB) as c, c.cursor() as cur:
        for label, sql in [
            ("pipeline_skill_runs", "SELECT count(*) FROM pipeline_skill_runs "
                                    "WHERE pipeline_id=(SELECT id FROM "
                                    "pipeline_runs WHERE slug=%s)"),
            ("approval_requests",   "SELECT count(*) FROM approval_requests "
                                    "WHERE product_slug=%s"),
            ("design_variants",     "SELECT count(*) FROM design_variants "
                                    "WHERE slug=%s"),
            ("pipeline_runs",       "SELECT count(*) FROM pipeline_runs "
                                    "WHERE slug=%s"),
        ]:
            try:
                cur.execute(sql, (slug,))
                counts[label] = cur.fetchone()[0]
            except Exception as e:
                counts[label] = f"? ({e})"
                c.rollback()

    print(f"\nducorn rows:")
    for k, v in counts.items():
        print(f"    {k:<22} {v}")

    if apply:
        with psycopg2.connect(DUCORN_DB) as c, c.cursor() as cur:
            # approval_requests and design_variants reference the product by
            # text with no foreign key, so nothing cascades. Delete them first,
            # while pipeline_runs still exists to explain what they belonged to.
            cur.execute("DELETE FROM design_variants WHERE slug=%s", (slug,))
            cur.execute("DELETE FROM approval_requests WHERE product_slug=%s",
                        (slug,))
            # pipeline_skill_runs cascades from this one.
            cur.execute("DELETE FROM pipeline_runs WHERE slug=%s", (slug,))
        print("    deleted")

    # ── 3. Checkpoints ───────────────────────────────────────────────────────
    cp = {}
    with psycopg2.connect(LITELLM_DB) as c, c.cursor() as cur:
        for t in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            try:
                cur.execute(f"SELECT count(*) FROM {t} WHERE thread_id=%s", (slug,))
                cp[t] = cur.fetchone()[0]
            except Exception as e:
                cp[t] = f"? ({e})"
                c.rollback()

    print(f"\nlitellm_db checkpoints:")
    for k, v in cp.items():
        print(f"    {k:<22} {v}")
    if any(isinstance(v, int) and v for v in cp.values()):
        print("    (leaving these behind means a new product with the same name")
        print("     silently resumes this run's state)")

    if apply:
        with psycopg2.connect(LITELLM_DB) as c, c.cursor() as cur:
            for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                cur.execute(f"DELETE FROM {t} WHERE thread_id=%s", (slug,))
        print("    deleted")

    # ── 4. Files ─────────────────────────────────────────────────────────────
    moves = []
    for d in (PRODUCTS / "docs", PRODUCTS / "pdfs"):
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file() and owns(p.name, slug, others):
                    moves.append(p)
    product_dir = PRODUCTS / "products" / slug
    if product_dir.is_dir():
        moves.append(product_dir)
    log = ROOT / "logs" / f"flow_{slug}.log"
    if log.is_file():
        moves.append(log)

    print(f"\nfiles ({len(moves)}) -> {dest}:")
    for m in moves:
        kind = "dir " if m.is_dir() else "file"
        print(f"    {kind} {m.relative_to(ROOT)}")
    if not moves:
        print("    none")

    if apply and moves:
        dest.mkdir(parents=True, exist_ok=True)
        for m in moves:
            target = dest / m.name
            n = 1
            while target.exists():
                target = dest / f"{m.name}.{n}"
                n += 1
            shutil.move(str(m), str(target))
        print(f"    moved (not deleted — remove {dest} when you are sure)")

    print()
    if apply:
        print(f"'{slug}' removed. Files are in {dest}")
        print("\nNOT touched: Google Drive still holds this product's folder,")
        print("and agent_activity has no slug column so its rows stay.")
    else:
        print("Nothing was changed. Re-run with --apply.")


if __name__ == "__main__":
    main()
