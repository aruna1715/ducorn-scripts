#!/usr/bin/env python3
"""
Re-judge a skill that was failed by a gate that was wrong. No model call.

    python3 scripts/regrade_skill.py <topic> <skill>          show
    python3 scripts/regrade_skill.py <topic> <skill> --apply  record it

    python3 scripts/regrade_skill.py ducorn-admin-rebuild-p1-config 04

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

Skill 04 built phase 1 of the admin rebuild correctly and was failed because
the build gate scraped a sentence out of the design document — a note saying
"phases 2 and 3 will add routers/services.py, routers/health.py …" — and
required those files of phase 1.

The gate is now fixed. The artefact never changed. Re-running the build to
satisfy a corrected gate would spend a claude-sonnet build call to reproduce
files that are already on disk, and would risk a second REX rewriting working
code — which is the expensive way to be wrong twice.

── WHAT IT IS NOT ───────────────────────────────────────────────────────────

Not a way to pass a skill. It runs THE GATE — the real function out of
skill_runner, not a copy — against what is on disk right now, and records
only what the gate says. If the gate still fails, this records nothing and
tells you why. There is no flag to override it, deliberately: a checkpoint
that can be hand-edited to "pass" is not a checkpoint.

── WHAT `since` MEANS HERE ──────────────────────────────────────────────────

The gate takes a `since` so that four-day-old files cannot satisfy it — REX
once confirmed documents written a week earlier and passed. Re-grading has no
run-start to hand it, so it uses the timestamp of the PREVIOUS skill in the
same checkpoint: files the build produced must be newer than the moment the
skill before it finished. That is a real bound, from the record, not a
waiver.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
DOCS = DC / "ducorn-products" / "docs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("skill", help="skill number, e.g. 04")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, str(DC / "ducorn"))
    sys.path.insert(0, str(DC / "scripts"))
    os.chdir(DC / "ducorn")

    import skill_runner as sr

    ck_path = DOCS / f"{a.topic}-gstack-checkpoint.json"
    if not ck_path.is_file():
        sys.exit(f"NOTHING DONE — no checkpoint at {ck_path}")
    ck = json.loads(ck_path.read_text())

    keys = [k for k in ck if k != "_version" and k.startswith(f"{a.skill}-")]
    if len(keys) != 1:
        sys.exit(f"NOTHING DONE — {len(keys)} checkpoint entries for skill "
                 f"{a.skill}: {keys}")
    key = keys[0]
    entry = ck[key]

    print(f"regrade_skill  {a.topic}  skill {a.skill}\n")
    print(f"  recorded   {entry.get('status')}  {entry.get('verdict','')[:90]}")
    print(f"  at         {entry.get('ts')}")

    if entry.get("status") == "pass":
        sys.exit("\nNOTHING DONE — it is already recorded as a pass.")

    # The bound: the previous skill's finish time. Files the build produced
    # must be newer than that.
    order = sorted(k for k in ck if k != "_version")
    prev = [k for k in order if k < key]
    since = None
    if prev:
        try:
            since = datetime.fromisoformat(ck[prev[-1]]["ts"]).timestamp()
            print(f"  since      {ck[prev[-1]]['ts']} (end of {prev[-1]})")
        except Exception:
            pass
    if since is None:
        print("  since      (none — no earlier skill to bound freshness by)")

    if a.skill != sr.BUILD_SKILL:
        sys.exit(f"\nNOTHING DONE — only the build skill ({sr.BUILD_SKILL}) "
                 f"has a gate that can be re-run against files on disk. Every "
                 f"other skill is judged on its text, and re-judging text "
                 f"without re-producing it would just be re-reading the same "
                 f"verdict.")

    # THE GATE ITSELF, not a copy of it.
    status, why = sr.build_produced_code(a.topic, since=since)
    print(f"\n  the gate, now: {status}")
    print(f"  {why}")

    if status != "pass":
        sys.exit("\nNOTHING RECORDED — the gate still fails. That is the "
                 "answer; there is no override.")

    if not a.apply:
        print("\nNothing written. Re-run with --apply to record the pass.")
        return 0

    ck[key] = sr.record(a.topic, "pass", why,
                        entry.get("output", ""),
                        prompt_sha=entry.get("prompt_sha", ""))
    ck[key]["regraded_from"] = entry.get("verdict", "")
    ck[key]["regraded_at"] = datetime.now().isoformat(timespec="seconds")
    results = {k: v for k, v in ck.items() if k != "_version"}
    sr.save_checkpoint(a.topic, results)
    print(f"\n  checkpoint {key} → pass")

    try:
        sr.update_db_status(a.topic, sr.SKILL_NAMES.get(a.skill, a.skill),
                            "complete")
        print("  pipeline_skill_runs → complete")
    except Exception as e:
        print(f"  (the database was not updated: {type(e).__name__}: {e})")

    print(f"""
The old verdict is kept in the entry as regraded_from, so the record says
what happened rather than pretending it did not.

Resume — it will pick up at the next skill, not rebuild:

  curl -sX POST localhost:8000/pipeline/resume/{a.topic} \\
       -H "x-api-key: $DUCORN_API_TOKEN"
""")
    return 0


if __name__ == "__main__":
    try:
        from bootstrap_python import ensure_modules
        ensure_modules("psycopg2")
    except ImportError:
        pass
    sys.exit(main())
