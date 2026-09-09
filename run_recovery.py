#!/usr/bin/env python3
"""
What to do about a failed run. One answer, for the log, the API and the page.

    python3 scripts/run_recovery.py <topic>            explain
    python3 scripts/run_recovery.py <topic> --apply    do it

Install as scripts/run_recovery.py.

── WHY ──────────────────────────────────────────────────────────────────────

Phase 1 of the admin rebuild failed at QA. Everything needed to recover was
already in the machine — the checkpoint knew which skills had passed,
skill_runner knew that a QA rejection invalidates the build and the review
(FEEDBACK_SKILLS), and langgraph_flow's qa_fix path already runs
`--invalidate`. None of it reached the person reading the log, who saw

    ❌ Pipeline failed at build: Skill 06 — QA + Run Test failed (exit 1)

and had no way to know that a plain resume would re-run only the failing
skill against unchanged code and fail identically, forever.

The knowledge existed and the operator could not get at it. That is the
recurring shape of every defect in this stack this week.

── WHAT IT DECIDES, AND FROM WHAT ───────────────────────────────────────────

    which skill failed          the checkpoint
    what must re-run            FEEDBACK_SKILLS for a QA rejection — the
                                constant skill_runner already defines. For
                                any other reviewer, the skill immediately
                                before it in this run's own recorded order.
    what must NOT be dropped    the failure record itself. That is what gets
                                handed to the builder as "here is why you
                                were rejected". Dropping it turns a targeted
                                retry into an identical rebuild.

Nothing here is a second copy: it imports skill_runner and calls
invalidate_checkpoint rather than deleting keys itself.

── WHAT IT WILL NOT DO ──────────────────────────────────────────────────────

Resume. Invalidating is free; resuming spends money. They are two decisions
and this makes only the first one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))

__all__ = ["plan", "apply_plan", "RecoveryError"]


class RecoveryError(RuntimeError):
    pass


def _sr():
    """
    skill_runner, which owns the checkpoint and FEEDBACK_SKILLS.

    Safe to import from the API: its module-level imports are stdlib plus
    DuCorn's own scripts — crewai is imported inside the functions that need
    it, so this does not drag the build stack into a web process.
    """
    for p in (DC / "ducorn", DC / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import skill_runner
    return skill_runner


def plan(topic: str) -> dict:
    """What is wrong and what would fix it. Reads only."""
    sr = _sr()
    ck = sr.load_checkpoint(topic)
    if not ck:
        return {"topic": topic, "state": "no checkpoint",
                "failed": None, "invalidate": [], "steps": [],
                "what": "There is no checkpoint for this run, so nothing has "
                        "been cached. A resume starts from the beginning."}

    ordered = sorted(ck)
    failed = [(k, v) for k, v in ck.items() if v.get("status") != "pass"]
    passed = [k for k in ordered if ck[k].get("status") == "pass"]

    if not failed:
        return {"topic": topic, "state": "nothing failed",
                "failed": None, "invalidate": [], "passed": passed, "steps": [],
                "what": "Every recorded skill passed. If the run stopped, it "
                        "stopped somewhere other than a skill — read the log "
                        "above this line."}

    key, entry = failed[0]
    num = key.split("-", 1)[0]
    name = sr.SKILL_NAMES.get(num, key)

    # WHICH SKILLS RE-RUN.
    #
    # QA has a documented answer already — FEEDBACK_SKILLS, "the builder, and
    # the reviewer who should know what QA found before passing the same code
    # again". Any other reviewer invalidates whatever produced the thing it
    # judged, which is the skill before it in this run's own order.
    if num == "06":
        targets = set(sr.FEEDBACK_SKILLS)
        why = ("QA rejected the build. The builder must fix it and the "
               "reviewer must judge the fix, so both re-run.")
    elif "Review" in name:
        earlier = [k for k in ordered if k < key]
        targets = {earlier[-1].split("-", 1)[0]} if earlier else set()
        why = (f"{name} rejected what the step before it produced, so that "
               f"step re-runs.")
    else:
        targets = set()
        why = (f"{name} failed on its own work. Resuming re-runs it; nothing "
               f"else needs dropping.")

    # Only what is actually cached as a pass. Invalidating a key that is not
    # there is a no-op that reads like an action.
    invalidate = sorted(n for n in targets
                        if any(k.startswith(f"{n}-") and
                               ck[k].get("status") == "pass" for k in ck))

    steps = []
    if invalidate:
        steps.append(
            f"python3 ducorn/skill_runner.py --topic {topic} "
            f"--invalidate {','.join(invalidate)}")
    steps.append(
        f'curl -sX POST localhost:8000/pipeline/resume/{topic} '
        f'-H "x-api-key: $DUCORN_API_TOKEN"')

    return {
        "topic": topic,
        "state": "failed",
        "failed": {"skill": num, "name": name,
                   "verdict": entry.get("verdict", ""),
                   "at": entry.get("ts", "")},
        "passed": passed,
        "invalidate": invalidate,
        "keep": [num],
        "why": why,
        "what": (
            f"{name} failed. "
            + (f"Skills {', '.join(invalidate)} are cached as passed, so a "
               f"plain resume would re-run only {num} against unchanged work "
               f"and fail the same way. Drop them first — and NOT {num}, "
               f"whose failure record is what the retry is told about."
               if invalidate else
               "A resume re-runs it; nothing is cached in the way.")),
        "steps": steps,
    }


def apply_plan(topic: str) -> dict:
    """Invalidate what plan() names. Does not resume — that spends money."""
    p = plan(topic)
    if not p.get("invalidate"):
        return {**p, "dropped": [],
                "note": "nothing needed dropping; resume when ready"}
    sr = _sr()
    dropped = sr.invalidate_checkpoint(topic, p["invalidate"])
    return {**p, "dropped": dropped}


def as_text(p: dict) -> str:
    """The same explanation in every place it is shown."""
    if p.get("state") != "failed":
        return f"── {p['topic']}\n{p.get('what', '')}"
    f = p["failed"]
    out = [
        "─" * 70,
        f"WHAT TO DO NEXT — {p['topic']}",
        "─" * 70,
        f"  failed     {f['name']}",
        f"  verdict    {f['verdict'][:160]}",
        "",
        f"  {p['why']}",
        "",
        f"  {p['what']}",
        "",
    ]
    for i, s in enumerate(p["steps"], 1):
        out.append(f"  {i}. {s}")
    out += ["",
            "  Or press RECOVER on this run in the dashboard, which does the "
            "same thing.",
            "─" * 70]
    return "\n".join(out)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--apply", action="store_true",
                    help="invalidate the cached skills (still does not resume)")
    a = ap.parse_args()

    p = plan(a.topic)
    print(as_text(p))
    if not a.apply:
        if p.get("invalidate"):
            print("\nNothing written. Re-run with --apply to drop "
                  f"{', '.join(p['invalidate'])}.")
        return 0
    r = apply_plan(a.topic)
    print(f"\ndropped: {r.get('dropped') or '(nothing)'}")
    print("Now resume. Invalidating is free; resuming spends money, so it is "
          "a separate decision.")
    return 0


if __name__ == "__main__":
    try:
        from bootstrap_python import ensure_modules
        ensure_modules("psycopg2")
    except ImportError:
        pass
    raise SystemExit(main())
