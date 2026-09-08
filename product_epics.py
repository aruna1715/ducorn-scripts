#!/usr/bin/env python3
"""
A product built over several pipeline runs. One directory, ordered phases.

    python3 scripts/product_epics.py --list
    python3 scripts/product_epics.py --show ducorn-admin-rebuild
    python3 scripts/product_epics.py --define plans/admin-rebuild.json
    python3 scripts/product_epics.py --next ducorn-admin-rebuild

── WHY ──────────────────────────────────────────────────────────────────────

One pipeline run makes one product. Anything bigger has no way to be
expressed, so it is either not attempted or attempted as a single enormous
run that fails in the middle with nothing to resume.

The size limit is not a guess. A DOCUMENT — no code, no tests, no deploy —
took four QA attempts and $11 on its first try. Phases exist so that each
piece is the size of something this pipeline has actually finished.

── THE MODEL ────────────────────────────────────────────────────────────────

An epic owns ONE product directory. Each phase is an ordinary pipeline run
with its own slug, gates, checkpoints and cost, building into that same
directory.

    epic  ducorn-admin-rebuild        products/ducorn-admin-rebuild/
      1   ...-p1-config               builds
      2   ...-p2-services             continues, depends_on {1}
      3   ...-p3-health               continues, depends_on {1,2}

Phase 2 does not copy phase 1's work. It is handed a manifest of what is
already in the directory and the briefs of the phases that put it there, and
it reads the files itself — they are inside its jail.

That is why the handoff is cheap. A content dump would spend thousands of
tokens re-describing files the agent can open, and this codebase has already
paid for a context budget once.

── WHAT THIS DOES NOT DO ────────────────────────────────────────────────────

No execution. A phase is started exactly as any product is started. Every
gate, resume, budget check and pathway rule applies unchanged. This module
records what the phases are, what order they go in, and what each one is
allowed to read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
PRODUCTS = DC / "ducorn-products" / "products"
DOCS = DC / "ducorn-products" / "docs"

# Matches the CHECK constraints in migration 009. prove_db_contracts.py
# compares these against the catalog in both directions.
EPIC_STATUS = ("planned", "running", "complete", "failed", "abandoned")
PHASE_STATUS = ("pending", "running", "complete", "failed", "skipped")

# How much of the previous phases' output to describe. A manifest is cheap;
# the agent opens what it needs. This is a ceiling on the manifest itself so
# a phase following a 400-file build does not get 400 lines.
MANIFEST_FILES = 60


class EpicError(RuntimeError):
    pass


class EpicsNotInstalled(EpicError):
    """
    Migration 009 has not been applied, so no epic can exist.

    Distinct from every other failure on purpose. "The tables are not there"
    proves there are no epics, and a caller may safely treat every slug as a
    standalone product. "I could not reach the database" proves nothing, and
    a caller must not guess — which is why they are different exceptions
    rather than one.
    """


def _deps(value) -> list:
    """
    depends_on as a list of ints, whatever the driver handed back.

    psycopg2 turns INTEGER[] into a Python list, so in production this is a
    no-op. It exists because the value is read in three places and every one
    of them did `x or []` — which turns the string "[]" into the characters
    '[' and ']', and then reports that phase 1 is waiting on two phases
    named '[' and ']'. Found by a test harness, not by a run, and worth
    keeping so these functions can be tested without a live PostgreSQL.
    """
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    try:
        return [int(v) for v in value]
    except (TypeError, ValueError):
        return []


def _conn():
    from ducorn_db import get_conn
    return get_conn()


def _missing_tables(exc) -> bool:
    """Is this exception 'migration 009 has not run', specifically?"""
    name = type(exc).__name__
    text = str(exc).lower()
    return (name == "UndefinedTable"
            or ("does not exist" in text
                and ("product_epics" in text or "epic_phases" in text)))


# ─────────────────────────────────────────────────────────────────────────────
# Reading
# ─────────────────────────────────────────────────────────────────────────────
def get(name: str):
    """One epic and its phases, in order. None if there is no such epic."""
    with _conn() as c:
        cur = c.cursor()
        cur.execute("""SELECT id, name, product_slug, brief, product_type,
                              status, created_at
                         FROM product_epics WHERE name = %s""", (name,))
        row = cur.fetchone()
        if not row:
            return None
        epic = dict(zip(("id", "name", "product_slug", "brief", "product_type",
                         "status", "created_at"), row))
        cur.execute("""SELECT seq, phase_slug, title, brief, depends_on,
                              status, started_at, completed_at
                         FROM epic_phases WHERE epic_id = %s
                        ORDER BY seq""", (epic["id"],))
        epic["phases"] = []
        for r in cur.fetchall():
            p = dict(zip(("seq", "phase_slug", "title", "brief", "depends_on",
                          "status", "started_at", "completed_at"), r))
            p["depends_on"] = _deps(p["depends_on"])
            epic["phases"].append(p)
    return epic


def phase_for(slug: str):
    """
    The phase a pipeline slug belongs to, with its epic. None if the slug is
    an ordinary standalone product — which most are, and which must keep
    working exactly as before.
    """
    try:
        with _conn() as c:
            cur = c.cursor()
            cur.execute("""SELECT p.seq, p.phase_slug, p.title, p.brief,
                                  p.depends_on, p.status,
                                  e.id, e.name, e.product_slug, e.brief,
                                  e.product_type
                             FROM epic_phases p
                             JOIN product_epics e ON e.id = p.epic_id
                            WHERE p.phase_slug = %s""", (slug,))
            row = cur.fetchone()
    except Exception as e:
        if _missing_tables(e):
            raise EpicsNotInstalled(
                "migration 009 has not been applied; there are no epics") from e
        raise
    if not row:
        return None
    return {
        "seq": row[0], "phase_slug": row[1], "title": row[2],
        "brief": row[3], "depends_on": _deps(row[4]), "status": row[5],
        "epic": {"id": row[6], "name": row[7], "product_slug": row[8],
                 "brief": row[9], "product_type": row[10]},
    }


def build_dir(slug: str) -> Path:
    """
    Where this slug builds.

    A phase builds into its EPIC's directory. Everything else builds into a
    directory of its own name, which is what has always happened.

    product_jail asks this. It is the single place the mapping exists, so
    there is no second answer to "where does this topic write".
    """
    ph = phase_for(slug)
    if ph:
        return PRODUCTS / ph["epic"]["product_slug"]
    return PRODUCTS / slug


def readable_slugs(slug: str) -> list:
    """
    Which OTHER slugs' documents this slug may read.

    Only the phases it declares a dependency on, and only within its own
    epic. An epic is the one sanctioned widening of the jail; without this,
    phase 2 could not read the PRD phase 1 produced.

    A standalone product gets an empty list, which is the behaviour that has
    always applied.
    """
    ph = phase_for(slug)
    if not ph or not ph["depends_on"]:
        return []
    with _conn() as c:
        cur = c.cursor()
        cur.execute("""SELECT phase_slug FROM epic_phases
                        WHERE epic_id = %s AND seq = ANY(%s)""",
                    (ph["epic"]["id"], list(ph["depends_on"])))
        return [r[0] for r in cur.fetchall()]


def next_phase(name: str):
    """
    The phase that should run next: the lowest seq that is not complete or
    skipped, and whose dependencies are all complete.

    Returns None when the epic is finished, and raises when it is stuck —
    a phase waiting on a dependency that failed is not "finished", and
    saying so is the difference between a done epic and an abandoned one.
    """
    epic = get(name)
    if epic is None:
        raise EpicError(f"no epic named {name!r}")

    by_seq = {p["seq"]: p for p in epic["phases"]}
    for p in epic["phases"]:
        if p["status"] in ("complete", "skipped"):
            continue
        if p["status"] == "running":
            # Already in flight. Returning it as "next" invites starting the
            # same phase twice — two runs writing one product directory, and
            # the second one reading the first's half-written files as though
            # a previous phase had produced them.
            raise EpicError(
                f"phase {p['seq']} ({p['title']}) is already running as "
                f"'{p['phase_slug']}'. Wait for it, or if that run died:\n"
                f"  python3 scripts/product_epics.py --mark {p['phase_slug']} pending")
        unmet = [d for d in p["depends_on"]
                 if by_seq.get(d, {}).get("status") not in ("complete", "skipped")]
        if unmet:
            blockers = ", ".join(
                f"{d} ({by_seq.get(d, {}).get('status', 'missing')})"
                for d in unmet)
            raise EpicError(
                f"phase {p['seq']} ({p['title']}) waits on phase(s) {blockers}. "
                f"Nothing can run until those finish.")
        return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# The handoff
# ─────────────────────────────────────────────────────────────────────────────
def context_for(slug: str) -> str:
    """
    What a phase is told about the work it is continuing.

    A manifest and the earlier briefs — NOT the file contents. The files are
    in this phase's own jail; it can open them. Pasting them into the prompt
    would spend thousands of tokens describing what is one tool call away,
    and would go stale the moment the agent edited one.
    """
    ph = phase_for(slug)
    if not ph:
        return ""

    epic = ph["epic"]
    d = PRODUCTS / epic["product_slug"]
    lines = [
        "=" * 70,
        f"THIS IS PHASE {ph['seq']} OF '{epic['name']}'",
        "=" * 70,
        "",
        "The whole product, for context:",
        (epic["brief"] or "(no epic brief recorded)").strip(),
        "",
        f"YOUR phase — this is what you are asked to deliver now:",
        (ph["brief"] or ph["title"]).strip(),
        "",
    ]

    done = [p for p in (get(epic["name"]) or {}).get("phases", [])
            if p["seq"] in ph["depends_on"]]
    if done:
        lines.append("Phases already finished in this same directory:")
        for p in done:
            lines.append(f"  · phase {p['seq']} — {p['title']} [{p['status']}]")
            if p["brief"]:
                lines.append(f"      {p['brief'].strip()[:200]}")
        lines.append("")

    if d.is_dir():
        files = sorted(
            (p for p in d.rglob("*")
             if p.is_file() and ".venv" not in p.parts
             and "__pycache__" not in p.parts and not p.name.startswith(".")),
            key=lambda p: str(p))
        lines.append(f"What is already in your product directory "
                     f"({len(files)} file(s)):")
        for p in files[:MANIFEST_FILES]:
            lines.append(f"  {p.relative_to(d)}  ({p.stat().st_size:,} bytes)")
        if len(files) > MANIFEST_FILES:
            lines.append(f"  … and {len(files) - MANIFEST_FILES} more")
        lines += [
            "",
            "READ these before writing anything. You are extending working "
            "code, not starting again.",
            "Do NOT rewrite a file that already does its job. Do NOT rename "
            "or move what an earlier phase produced — a later phase and a "
            "person both depend on those names.",
        ]
    else:
        lines.append("Your product directory is empty — you are the first "
                     "phase.")

    lines += ["", "=" * 70, ""]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Writing
# ─────────────────────────────────────────────────────────────────────────────
def define(spec: dict) -> dict:
    """
    Create an epic and its phases from a plan. Idempotent on name.

    spec = {
      "name": "ducorn-admin-rebuild",
      "product_slug": "ducorn-admin-rebuild",     # optional, defaults to name
      "product_type": "webpage",
      "brief": "...",
      "phases": [
        {"title": "...", "slug": "...", "brief": "...", "depends_on": [1]},
      ]
    }

    depends_on defaults to the immediately preceding phase, because that is
    the common case — but it is WRITTEN OUT into the row rather than implied,
    so the jail reads a fact instead of re-deriving a convention.
    """
    name = (spec.get("name") or "").strip()
    if not name:
        raise EpicError("a spec needs a name")
    phases = spec.get("phases") or []
    if not phases:
        raise EpicError("a spec needs at least one phase")

    slugs = [(p.get("slug") or "").strip() for p in phases]
    if not all(slugs):
        raise EpicError("every phase needs a slug")
    if len(set(slugs)) != len(slugs):
        raise EpicError(f"duplicate phase slugs: {slugs}")

    product_slug = (spec.get("product_slug") or name).strip()

    with _conn() as c:
        cur = c.cursor()
        cur.execute("SELECT id FROM product_epics WHERE name = %s", (name,))
        if cur.fetchone():
            raise EpicError(
                f"an epic named {name!r} already exists. Rename the new one, "
                f"or drop the old one deliberately — this refuses rather than "
                f"merging two plans into one.")
        cur.execute("""INSERT INTO product_epics
                           (name, product_slug, brief, product_type, status)
                       VALUES (%s, %s, %s, %s, 'planned') RETURNING id""",
                    (name, product_slug, spec.get("brief"),
                     spec.get("product_type")))
        epic_id = cur.fetchone()[0]

        for i, p in enumerate(phases, start=1):
            deps = p.get("depends_on")
            if deps is None:
                deps = [i - 1] if i > 1 else []
            bad = [d for d in deps if d >= i or d < 1]
            if bad:
                raise EpicError(
                    f"phase {i} depends on {bad}, which is not an earlier "
                    f"phase. Dependencies point backwards only.")
            cur.execute("""INSERT INTO epic_phases
                               (epic_id, seq, phase_slug, title, brief,
                                depends_on, status)
                           VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
                        (epic_id, i, p["slug"].strip(),
                         p.get("title") or p["slug"], p.get("brief"),
                         list(deps)))
        c.commit()
    return get(name)


def mark(slug: str, status: str) -> None:
    """Record where a phase got to, and roll the epic's status up."""
    if status not in PHASE_STATUS:
        raise EpicError(f"{status!r} is not a phase status. "
                        f"Known: {', '.join(PHASE_STATUS)}")
    with _conn() as c:
        cur = c.cursor()
        stamp = ("started_at = now()" if status == "running"
                 else "completed_at = now()" if status in
                 ("complete", "failed", "skipped") else "id = id")
        cur.execute(f"""UPDATE epic_phases SET status = %s, {stamp}
                         WHERE phase_slug = %s RETURNING epic_id""",
                    (status, slug))
        row = cur.fetchone()
        if not row:
            raise EpicError(f"{slug!r} is not a phase of any epic")
        epic_id = row[0]

        # The epic's status is derived, never set by hand — two places
        # deciding whether an epic is finished is how they disagree.
        cur.execute("""SELECT status, count(*) FROM epic_phases
                        WHERE epic_id = %s GROUP BY status""", (epic_id,))
        counts = dict(cur.fetchall())
        total = sum(counts.values())
        if counts.get("failed"):
            new = "failed"
        elif counts.get("complete", 0) + counts.get("skipped", 0) == total:
            new = "complete"
        elif counts.get("running") or counts.get("complete"):
            new = "running"
        else:
            new = "planned"
        cur.execute("""UPDATE product_epics SET status = %s, updated_at = now()
                        WHERE id = %s""", (new, epic_id))
        c.commit()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", metavar="NAME")
    ap.add_argument("--define", metavar="PLAN.json")
    ap.add_argument("--next", metavar="NAME")
    ap.add_argument("--context", metavar="PHASE_SLUG",
                    help="print the handoff a phase would receive")
    ap.add_argument("--mark", nargs=2, metavar=("PHASE_SLUG", "STATUS"))
    a = ap.parse_args()

    if a.define:
        spec = json.loads(Path(a.define).read_text())
        e = define(spec)
        print(f"epic {e['name']} — {len(e['phases'])} phase(s), "
              f"building into products/{e['product_slug']}/")
        for p in e["phases"]:
            dep = f" after {p['depends_on']}" if p["depends_on"] else ""
            print(f"  {p['seq']}. {p['title']:36} {p['phase_slug']}{dep}")
        return

    if a.mark:
        mark(a.mark[0], a.mark[1])
        print(f"{a.mark[0]} → {a.mark[1]}")
        return

    if a.context:
        print(context_for(a.context) or "(not a phase of any epic)")
        return

    if a.next:
        p = next_phase(a.next)
        if p is None:
            print(f"{a.next}: every phase is finished")
        else:
            print(f"next: phase {p['seq']} — {p['title']}")
            print(f"      slug {p['phase_slug']}")
        return

    if a.show:
        e = get(a.show)
        if e is None:
            raise SystemExit(f"no epic named {a.show!r}")
        print(f"{e['name']}  [{e['status']}]  → products/{e['product_slug']}/")
        print(f"  type {e['product_type'] or '(not set)'}")
        if e["brief"]:
            print(f"  {e['brief'].strip()[:300]}")
        print()
        for p in e["phases"]:
            dep = f"  after {p['depends_on']}" if p["depends_on"] else ""
            print(f"  {p['seq']}. [{p['status']:8}] {p['title']:36} "
                  f"{p['phase_slug']}{dep}")
        return

    with _conn() as c:
        cur = c.cursor()
        cur.execute("""SELECT e.name, e.status, e.product_slug,
                              count(p.id),
                              count(*) FILTER (WHERE p.status = 'complete')
                         FROM product_epics e
                    LEFT JOIN epic_phases p ON p.epic_id = e.id
                     GROUP BY e.id, e.name, e.status, e.product_slug
                     ORDER BY e.created_at DESC""")
        rows = cur.fetchall()
    if not rows:
        print("no epics yet.\n\n  python3 scripts/product_epics.py "
              "--define plans/your-plan.json")
        return
    print(f"{'epic':34} {'status':10} {'phases':>8}  directory")
    for name, status, slug, total, done in rows:
        print(f"{name:34} {status:10} {done}/{total:>6}  products/{slug}/")


if __name__ == "__main__":
    # Inside __main__ only: ensure_modules re-execs, and this module is
    # imported by product_jail, which runs inside every agent subprocess.
    from bootstrap_python import ensure_modules
    ensure_modules("psycopg2")
    _main()
