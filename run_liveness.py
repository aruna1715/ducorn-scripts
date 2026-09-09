#!/usr/bin/env python3
"""
Which pipeline runs actually have a process. One definition.

    import run_liveness as rl
    procs = rl.snapshot()
    rl.pids_for("my-product", procs)     -> [12345]
    rl.live({"a", "b"}, procs)           -> {"a"}

Install as scripts/run_liveness.py. Self-test:

    python3 scripts/run_liveness.py            what is running now
    python3 scripts/run_liveness.py --test     the matching rules

── WHY IT IS ITS OWN MODULE ─────────────────────────────────────────────────

"Is this run alive" is asked from two processes that cannot share code any
other way: the API (pipeline_kill, to know what to signal) and the reaper (a
launchd job, to know what is a ghost). main.py cannot be imported by a
scheduled script — it is a FastAPI app with a database pool and side effects
at import.

Without this the reaper would carry its own copy of the matching rule, and
that rule has already been wrong once here in a way that cost real damage:

    pgrep -f "langgraph_flow.py " + slug

matched as a SUBSTRING, so stopping 'ducorn-spend-status' also killed
'ducorn-spend-status-web'. Three pairs of topics in this repo have one name
as a prefix of another. A second copy of that rule is a second chance to get
it wrong, in a process that runs unattended every five minutes.

── THE RULE ─────────────────────────────────────────────────────────────────

A process belongs to a run when one of its arguments is EXACTLY the slug.
Not a prefix, not a substring. The flow is always launched as

    <python> -u .../langgraph_flow.py <slug> --phase ... --type ...

from every launch site — /pipeline/start, /pipeline/resume and
start_phase.start_next — so the slug is always its own argument.
"""
from __future__ import annotations

import re
import subprocess

__all__ = ["snapshot", "pids_for", "live", "BadSlug", "SLUG_RE"]

# The same shape pipeline_kill validates. A slug that cannot appear in the
# database cannot be asked about, so a crafted string never reaches pgrep.
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")

FLOW_MARK = "langgraph_flow.py"


class BadSlug(ValueError):
    """A slug that is not a slug."""


def snapshot() -> list:
    """
    Every pipeline process, as (pid, [args]). Taken ONCE.

    The reaper asks about a dozen runs; calling pgrep per run would be a dozen
    process listings taken at a dozen different moments, which is how a run
    that finishes mid-loop gets two different answers.
    """
    try:
        out = subprocess.run(["pgrep", "-fl", FLOW_MARK],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        # No listing is NOT "nothing is running". Callers must be able to tell
        # those apart, so this raises rather than returning an empty list — a
        # reaper that reads a failure as "no processes" marks every live run
        # failed.
        raise

    procs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        procs.append((int(parts[0]), parts[1:]))
    return procs


def pids_for(slug: str, procs=None) -> list:
    """Pids whose argument list contains the slug as a WHOLE argument."""
    if not slug or not SLUG_RE.fullmatch(slug):
        raise BadSlug(f"{slug!r} is not a valid run slug")
    if procs is None:
        procs = snapshot()
    return [pid for pid, args in procs if slug in args]


def live(slugs, procs=None) -> set:
    """The subset of `slugs` that has a process. One listing for all of them."""
    if procs is None:
        procs = snapshot()
    running = set()
    for _pid, args in procs:
        running.update(args)
    return {s for s in slugs if s in running}


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        FAKE = [
            (101, ["/x/python", "-u", "/x/langgraph_flow.py",
                   "ducorn-spend-status", "--phase", "build"]),
            (102, ["/x/python", "-u", "/x/langgraph_flow.py",
                   "ducorn-admin-rebuild-p1-config", "--phase", "research"]),
        ]
        bad = []
        if pids_for("ducorn-spend-status", FAKE) != [101]:
            bad.append("an exact slug did not match its own process")
        # The bug this module exists to prevent.
        if pids_for("ducorn-spend-status-web", FAKE):
            bad.append("a LONGER slug matched a shorter one's process")
        if pids_for("ducorn-spend", FAKE):
            bad.append("a PREFIX matched — substring matching is back")
        if live({"ducorn-spend-status", "nope"}, FAKE) != {"ducorn-spend-status"}:
            bad.append("live() disagrees with pids_for()")
        try:
            pids_for("../../etc/passwd", FAKE)
            bad.append("a non-slug was accepted")
        except BadSlug:
            pass
        print("run_liveness OK" if not bad else "run_liveness BAD\n  "
              + "\n  ".join(bad))
        raise SystemExit(0 if not bad else 1)

    procs = snapshot()
    if not procs:
        print("no pipeline processes are running")
    for pid, args in procs:
        topic = args[args.index([a for a in args
                                 if a.endswith(FLOW_MARK)][0]) + 1] \
                if any(a.endswith(FLOW_MARK) for a in args) else "?"
        print(f"  {pid:>7}  {topic}")
