#!/usr/bin/env python3
"""
What has DuCorn spent today. One definition, one source.

    python3 scripts/ducorn_spend.py           today, and whether a run may start
    python3 scripts/ducorn_spend.py --json    the same, as JSON

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

There were three answers to "what have we spent today":

  doctor.py            SELECT sum(spend) FROM "LiteLLM_SpendLogs"
                       WHERE "startTime" >= date_trunc('day', now())

  spend_breakdown.py   the same query, written out again

  /budget/check        an HTTP call to LiteLLM's /global/spend/logs, parsed
                       by scanning for an entry whose "date" equals today and
                       stopping at the FIRST one

The third is the one that decides whether the dashboard will start a
pipeline, and it was the least reliable of the three:

  · it stopped at the first matching entry, so with more than one row for
    today it reported a fraction of the real spend and called it the total;
  · any exception — LiteLLM down, wrong master key, a shape it did not
    expect — was caught and turned into {"today_spend": 0, "can_proceed":
    true}. A budget check that cannot see the spend said "£0 spent, go
    ahead";
  · /pipeline/start then wrapped the whole call in `except: pass`, so even
    that answer could vanish silently.

Three chances to fail open, on the one control that stands between a bug and
a day's credits.

── WHAT THIS DOES ───────────────────────────────────────────────────────────

Reads LiteLLM_SpendLogs directly — the table LiteLLM itself writes, the same
source doctor already trusts — and raises SpendUnknown when it cannot. It
never returns a number it is not sure of, because a wrong number here is
worse than an error: an error stops the run, and a wrong number spends.
"""
from __future__ import annotations

import os

DSN = os.environ.get("LITELLM_DATABASE_URL",
                     "postgresql://ducorn@localhost/litellm_db")

# The window. Written once, here, so doctor and the API cannot disagree about
# what "today" means — local midnight, per the database's own clock.
_TODAY = '"startTime" >= date_trunc(\'day\', now())'
_WEEK = ('"startTime" >= date_trunc(\'day\', now()) - interval \'7 days\'')


class SpendUnknown(RuntimeError):
    """We could not find out. Never silently zero."""


def _sum(where: str) -> float:
    try:
        import psycopg2
    except ImportError as e:                       # pragma: no cover
        raise SpendUnknown(f"psycopg2 is not available: {e}") from e
    try:
        with psycopg2.connect(DSN) as c:
            cur = c.cursor()
            cur.execute(f'SELECT COALESCE(sum(spend), 0) '
                        f'FROM "LiteLLM_SpendLogs" WHERE {where}')
            return float(cur.fetchone()[0] or 0)
    except SpendUnknown:
        raise
    except Exception as e:
        raise SpendUnknown(f"{type(e).__name__}: {e}") from e


def total_spend() -> float:
    """
    Everything ever spent, as a running odometer.

    Not interesting on its own — it exists to be subtracted. Read before and
    after a skill, the difference is what that skill cost, which is the only
    per-skill figure this stack can produce: LiteLLM_SpendLogs records spend
    per API key, and the keys are per AGENT, not per run.
    """
    return _sum("1=1")


def today_spend() -> float:
    """Everything spent since local midnight. Raises SpendUnknown."""
    return _sum(_TODAY)


def week_spend() -> float:
    return _sum(_WEEK)


def daily_limit() -> float:
    """
    The cap. One answer, whoever asks.

    Read on every call rather than captured at import: the admin page writes
    DUCORN_DAILY_BUDGET into shared/.env, and a limit frozen at process start
    is a limit that page cannot actually change.

    shared/.env is consulted when the variable is not already in the
    environment. Without this the API said $50.00 — it loads shared/.env at
    startup — while `python3 scripts/ducorn_spend.py` in a shell said $3.00,
    the built-in default. Two answers to "what is the limit", decided by who
    was asking, which is the whole failure mode this module exists to remove.
    """
    raw = os.environ.get("DUCORN_DAILY_BUDGET")
    if raw is None:
        try:
            from ducorn_env import load_ducorn_env
            load_ducorn_env()
            raw = os.environ.get("DUCORN_DAILY_BUDGET")
        except Exception:
            pass
    try:
        return float(raw) if raw is not None else 3.0
    except (TypeError, ValueError):
        return 3.0


def budget_status(limit: float = None) -> dict:
    """
    Can a pipeline start?

    can_proceed is False when the spend cannot be determined. That is the
    whole point of this module: not knowing is not permission.
    """
    lim = daily_limit() if limit is None else float(limit)
    try:
        spent = today_spend()
    except SpendUnknown as e:
        return {
            "today_spend": None,
            "daily_limit": lim,
            "remaining": None,
            "can_proceed": False,
            "known": False,
            "message": (f"Refusing to start: today's spend could not be read "
                        f"({e}). Not knowing what has been spent is not "
                        f"permission to spend more. Check litellm_db, then "
                        f"try again."),
        }
    return {
        "today_spend": round(spent, 4),
        "daily_limit": lim,
        "remaining": round(max(0.0, lim - spent), 4),
        "can_proceed": spent < lim,
        "known": True,
        "message": (f"${spent:,.2f} spent today of ${lim:,.2f} limit"
                    if spent < lim else
                    f"⚠️ Daily budget reached (${spent:,.2f} of ${lim:,.2f})"),
    }


if __name__ == "__main__":
    # DELIBERATELY inside __main__ and nowhere else. ensure_modules RE-EXECS
    # the interpreter, and this module is imported by the activity API — a
    # re-exec at import time would restart the service.
    #
    # It belongs here because this file has a command line and imports
    # psycopg2, and `python3` on this Mac is 3.14, which does not have it.
    # Without this, `python3 scripts/ducorn_spend.py` reports "spend could not
    # be read: psycopg2 is not available" — an interpreter problem wearing the
    # costume of a database problem. I worked around that in the patch script
    # by choosing an interpreter there, which fixed the caller and left the
    # module broken for everyone else.
    from bootstrap_python import ensure_modules
    ensure_modules("psycopg2")

    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    s = budget_status()
    if a.json:
        print(json.dumps(s, indent=2))
    else:
        print(s["message"])
        if s["known"]:
            try:
                print(f"last 7 days ${week_spend():,.2f}")
            except SpendUnknown:
                pass
    sys.exit(0 if s["can_proceed"] else 1)
