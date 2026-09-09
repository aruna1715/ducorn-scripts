#!/usr/bin/env python3
"""
What a run has actually spent. The number the dashboard has been faking.

    python3 scripts/run_cost.py <slug>
    python3 scripts/run_cost.py --test

Install as scripts/run_cost.py.

── WHY ──────────────────────────────────────────────────────────────────────

pipeline_runs.cost_so_far is displayed beside every product on the dashboard
and in the Slack digest. It has never held a number.

    def _update_db_status(topic, status, phase=None, cost: float = 0):
        ... cost_so_far = cost_so_far + %s ...

Twenty-three call sites in langgraph_flow. Not one passes a cost. So every
run has shown "$0.00 spent" from the day the column was added, while phase 1
of the admin rebuild quietly went through about seventeen dollars.

A displayed zero is worse than no number at all: it answers the question
"is this getting expensive" with "no".

── HOW IT ATTRIBUTES ────────────────────────────────────────────────────────

LiteLLM_SpendLogs records every call with a startTime and a spend, and
nothing in it names the pipeline run — the keys are per AGENT (SAGE, REX),
not per run. So a run's cost is the spend in its own time window.

That is exact only when one run owned the window. When runs overlapped, the
window's spend belongs to several of them and this says so rather than
dividing it up:

    {"spend": 4.12, "exact": false, "overlapped_by": ["other-slug"]}

A number this cannot vouch for is labelled, not laundered. That rule is the
whole reason ducorn_spend raises SpendUnknown instead of returning 0, and it
applies twice as hard to a number a person uses to decide whether to press a
button that spends more.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))

__all__ = ["for_run", "CostUnknown"]


class CostUnknown(RuntimeError):
    """We could not find out. Never silently zero."""


def _window(slug: str):
    """(started, ended_or_none) for a run, from pipeline_runs."""
    sys.path.insert(0, str(DC / "scripts"))
    from ducorn_db import get_conn
    with get_conn() as c:
        cur = c.cursor()
        cur.execute("""SELECT created_at, updated_at, status
                         FROM pipeline_runs WHERE slug = %s""", (slug,))
        row = cur.fetchone()
    if not row:
        raise CostUnknown(f"no run called {slug!r}")
    started, updated, status = row[0], row[1], row[2]
    live = status in ("running", "started", "created", "awaiting_approval")
    return started, (None if live else updated), status


def _overlapping(slug: str, started, ended):
    """Other runs whose window overlaps this one's."""
    sys.path.insert(0, str(DC / "scripts"))
    from ducorn_db import get_conn
    with get_conn() as c:
        cur = c.cursor()
        cur.execute("""SELECT slug FROM pipeline_runs
                        WHERE slug <> %s
                          AND updated_at >= %s
                          AND (%s IS NULL OR created_at <= %s)""",
                    (slug, started, ended, ended))
        return [r[0] for r in cur.fetchall()]


def for_run(slug: str) -> dict:
    """
    Spend attributable to this run.

    Raises rather than guessing. A cost display that shows 0 when it does not
    know is how seventeen dollars went past unnoticed.
    """
    started, ended, status = _window(slug)

    try:
        import psycopg2
    except ImportError as e:
        raise CostUnknown(f"psycopg2 is not available: {e}") from e

    dsn = os.environ.get("LITELLM_DATABASE_URL",
                         "postgresql://ducorn@localhost/litellm_db")
    where = '"startTime" >= %s' + ('' if ended is None else ' AND "startTime" <= %s')
    params = [started] if ended is None else [started, ended]
    try:
        with psycopg2.connect(dsn) as c:
            cur = c.cursor()
            cur.execute(f'SELECT COALESCE(sum(spend), 0), count(*) '
                        f'FROM "LiteLLM_SpendLogs" WHERE {where}', params)
            spend, calls = cur.fetchone()
    except Exception as e:
        raise CostUnknown(f"{type(e).__name__}: {e}") from e

    others = _overlapping(slug, started, ended)
    return {
        "slug": slug,
        "spend": round(float(spend or 0), 4),
        "calls": int(calls or 0),
        "from": started.isoformat() if started else None,
        "to": ended.isoformat() if ended else None,
        "live": ended is None,
        "status": status,
        # The honesty flag. False means this window was shared and the number
        # is an upper bound for this run, not its bill.
        "exact": not others,
        "overlapped_by": others,
    }


def as_text(c: dict) -> str:
    head = f"{c['slug']}  ${c['spend']:.2f}  ({c['calls']} calls)"
    if c["live"]:
        head += "  — still running, so this is spend so far"
    if not c["exact"]:
        head += ("\n  NOT exact: " + ", ".join(c["overlapped_by"])
                 + " ran in the same window, so this is an upper bound.")
    return head


if __name__ == "__main__":
    if "--test" in sys.argv:
        # No database. What is tested is the honesty rule: a shared window is
        # never reported as exact, and a live run is never reported as final.
        bad = []
        shared = {"slug": "a", "spend": 4.0, "calls": 9, "from": "x", "to": None,
                  "live": True, "status": "running", "exact": False,
                  "overlapped_by": ["b"]}
        t = as_text(shared)
        if "NOT exact" not in t:
            bad.append("a shared window did not say so")
        if "spend so far" not in t:
            bad.append("a live run was reported as a final figure")
        clean = {**shared, "exact": True, "overlapped_by": [], "live": False,
                 "to": "y"}
        t2 = as_text(clean)
        if "NOT exact" in t2 or "so far" in t2:
            bad.append("a clean window was hedged anyway")
        print("run_cost OK" if not bad else "run_cost BAD\n  " + "\n  ".join(bad))
        raise SystemExit(0 if not bad else 1)

    try:
        from bootstrap_python import ensure_modules
        ensure_modules("psycopg2")
    except ImportError:
        pass
    for slug in sys.argv[1:] or ["ducorn-admin-rebuild-p1-config"]:
        try:
            print(as_text(for_run(slug)))
        except CostUnknown as e:
            print(f"{slug}: unknown — {e}")
