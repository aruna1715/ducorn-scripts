#!/usr/bin/env python3
"""
Start the next phase of an epic.

    python3 scripts/start_phase.py ducorn-admin-rebuild            show
    python3 scripts/start_phase.py ducorn-admin-rebuild --apply    start it
    python3 scripts/start_phase.py ducorn-admin-rebuild --dry-run  free: the prompt

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

A phase cannot be started the way a product is started from the command line,
because of something that only shows up when you look:

    _update_db_status() only ever UPDATEs pipeline_runs.

A CLI run for a slug with no row updates zero rows, silently. No recorded
product type — so the pathway is inferred from a PRD that does not exist yet,
and a document-shaped phase would take the software path. No cost tracking.
Nothing on the dashboard. The run works and every record of it is missing.

So the row has to exist first, carrying what the epic already knows: the
product type, the complexity, and a name a person will recognise.

This is also the thing a "start next phase" button would call. It is a
script first on purpose — an endpoint that wraps a script can be reviewed;
a script that duplicates an endpoint cannot.

── WHAT IT WILL NOT DO ──────────────────────────────────────────────────────

Start a phase whose dependencies have not finished, or one already running.
product_epics.next_phase decides both, and this asks rather than repeating
the reasoning.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
VENV = DC / "ducorn" / ".venv" / "bin" / "python"
LOGS = DC / "logs"
DOCS = DC / "ducorn-products" / "docs"


def die(msg: str):
    sys.exit(f"NOTHING STARTED — {msg}")


class NotStartable(RuntimeError):
    """Why this epic cannot start a phase right now."""


def _epics():
    sys.path.insert(0, str(DC / "scripts"))
    import product_epics
    return product_epics


def plan_next(epic_name: str) -> dict:
    """
    What starting the next phase WOULD do. No side effects.

    Separate from start_next so the dashboard can show the operator what is
    about to happen — and so the endpoint and the command line ask the same
    question rather than each deciding for themselves.
    """
    pe = _epics()
    epic = pe.get(epic_name)
    if epic is None:
        raise NotStartable(f"no epic named {epic_name!r}")
    try:
        phase = pe.next_phase(epic_name)
    except pe.EpicError as e:
        raise NotStartable(str(e)) from e

    out = {"epic": epic["name"], "status": epic["status"],
           "product_slug": epic["product_slug"],
           "product_type": epic["product_type"],
           "total_phases": len(epic["phases"]),
           "phases": [{"seq": p["seq"], "title": p["title"],
                       "slug": p["phase_slug"], "status": p["status"],
                       "depends_on": p["depends_on"]}
                      for p in epic["phases"]],
           "next": None, "blocked": None}
    if phase is None:
        out["blocked"] = "every phase is finished"
        return out
    if not epic["product_type"]:
        raise NotStartable(
            "the epic records no product_type, so the pathway would be "
            "inferred from a PRD that does not exist yet")
    out["next"] = {"seq": phase["seq"], "title": phase["title"],
                   "slug": phase["phase_slug"],
                   "depends_on": phase["depends_on"]}
    return out


def brief_text(slug: str) -> str:
    """
    What this phase is asked to build, as prose.

    One source: product_epics.context_for reads the epic, the phase, the
    finished dependencies and the product directory. This adds no words of
    its own — a second description of a phase would drift from the first.
    """
    pe = _epics()
    return pe.context_for(slug).strip()


def write_phase_brief(slug: str) -> Path:
    """
    Put the phase brief where a run's brief lives: docs/<slug>-PRD.md.

    THIS IS THE HALF THAT WAS MISSING. /pipeline/start writes this file and
    then launches; start_next created the pipeline_runs row and launched
    without it, and node_research — which reads this file as its first act —
    failed the run before any skill ran.

    Shape matches /pipeline/start: a header and the brief, with no
    "## Founder Brief" heading. node_research adds that heading itself when
    it re-appends the brief after research, and it is defined there. Writing
    it here would be a second copy of it.

    A phase that has already produced a researched PRD keeps it; only the
    brief section is refreshed, because the manifest of what is in the
    product directory has changed since it was written.
    """
    import stack_context as sc

    text = brief_text(slug)
    if not text:
        raise NotStartable(
            f"no brief could be built for {slug!r} — product_epics.context_for "
            f"returned nothing, so there is no phase by that slug")

    DOCS.mkdir(parents=True, exist_ok=True)
    prd = DOCS / f"{slug}-PRD.md"

    if prd.exists():
        raw = prd.read_text(errors="replace")
        i = raw.find(sc.BRIEF_MARKER)
        if i >= 0:
            # Keep the research, refresh the brief. The file's OWN heading
            # line is reused verbatim rather than reconstructed.
            heading = raw[i:].splitlines()[0]
            prd.write_text(f"{raw[:i].rstrip()}\n\n{heading}\n\n{text}\n",
                           encoding="utf-8")
            return prd

    prd.write_text(f"# {slug} — phase brief\n\n{text}\n", encoding="utf-8")
    return prd


def start_next(epic_name: str, *, engine="gstack", coder="crewai",
               complexity="medium", environment="test") -> dict:
    """
    Start the next phase. Creates its pipeline_runs row, then launches the
    flow detached.

    Refuses on an unreadable budget, exactly as /pipeline/start does — a run
    started when nobody can say what has been spent is the failure the budget
    work removed.
    """
    plan = plan_next(epic_name)
    if not plan["next"]:
        raise NotStartable(plan["blocked"] or "nothing to start")

    slug = plan["next"]["slug"]
    ptype = plan["product_type"]

    try:
        import ducorn_spend
        budget = ducorn_spend.budget_status()
    except Exception as e:
        raise NotStartable(f"the budget could not be read ({e})") from e
    if not budget.get("can_proceed"):
        raise NotStartable(budget["message"])

    from ducorn_db import get_conn
    with get_conn() as c:
        cur = c.cursor()
        cur.execute("SELECT status FROM pipeline_runs WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row and row[0] in ("running", "started", "created",
                              "awaiting_approval"):
            raise NotStartable(f"the run for {slug} is already {row[0]}")
        if not row:
            # TEST unless asked otherwise. _pin_local_for_test_runs reads
            # this column and pins every agent to the local model when it
            # says 'test' — same nodes, same gates, same jail, no bill.
            #
            # It used to be the literal 'production', so there was no way to
            # exercise the plumbing cheaply. Every plumbing fault phase 1
            # found would have surfaced the same way on local models.
            if environment not in ("test", "production"):
                raise NotStartable(
                    f"environment must be 'test' or 'production', not "
                    f"{environment!r}")
            cur.execute("""
                INSERT INTO pipeline_runs
                    (slug, product_name, complexity, status, product_type,
                     has_ui, build_engine, coder, environment)
                VALUES (%s, %s, %s, 'created', %s, %s, %s, %s, %s)
            """, (slug,
                  f"{plan['epic']} — phase {plan['next']['seq']}: "
                  f"{plan['next']['title']}",
                  complexity, ptype, ptype in ("webpage", "software"),
                  engine, coder, environment))
            c.commit()

    # The brief, BEFORE the launch. node_research reads docs/<slug>-PRD.md
    # as its first act and refuses an empty one; without this the run failed
    # in under two seconds, having created its row and its log.
    prd = write_phase_brief(slug)

    print(f"🏷️  {slug} is a {environment.upper()} run"
          + ("  — local models, nothing billed"
             if environment == "test" else "  — PAID models"), flush=True)

    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"flow_{slug}.log"
    cmd = [str(VENV), "-u", str(FLOW), slug, "--phase", "research",
           "--type", ptype, "--engine", engine, "--coder", coder,
           "--complexity", complexity]
    with log.open("w") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True,
                                cwd=str(DC / "ducorn"))
    return {"started": slug, "seq": plan["next"]["seq"],
            "title": plan["next"]["title"], "pid": proc.pid,
            "environment": environment,
            "log": str(log), "brief": str(prd), "budget": budget["message"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epic")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the prompt and print it; costs nothing")
    ap.add_argument("--engine", default="gstack", choices=["fast", "gstack"])
    ap.add_argument("--coder", default="crewai", choices=["crewai", "cursor"])
    ap.add_argument("--complexity", default="medium",
                    choices=["simple", "medium", "complex"])
    ap.add_argument("--environment", default="test",
                    choices=["test", "production"],
                    help="test pins every agent to the local model and costs "
                         "nothing; production spends. Default: test.")
    a = ap.parse_args()

    sys.path.insert(0, str(DC / "scripts"))
    import product_epics as pe

    epic = pe.get(a.epic)
    if epic is None:
        die(f"no epic named {a.epic!r}. "
            f"python3 scripts/product_epics.py --list")

    # BEFORE the startability question. --dry-run writes nothing and spends
    # nothing, and asking next_phase() first meant "phase 1 is already
    # running" refused to SHOW the brief — at the one moment you want to read
    # it, which is after a run of that phase has died.
    #
    # This asks something weaker than next_phase on purpose: which phase is
    # this ABOUT, not which phase may start. The start path below still asks
    # the real question, because that is the one spending money.
    if a.dry_run:
        live = [p for p in epic["phases"]
                if p["status"] not in ("complete", "skipped")]
        if not live:
            print(f"{a.epic}: every phase is finished — nothing to show.")
            return 0
        p = live[0]
        dslug = p["phase_slug"]
        try:
            text = brief_text(dslug)
        except Exception as e:
            die(f"the brief could not be built: {e}")
        print(f"{a.epic}  →  phase {p['seq']} of {len(epic['phases'])} — "
              f"{p['title']}  [{p['status']}]")
        print(f"\n── the brief start would write ({len(text):,} chars) ──")
        print(f"   to   {DOCS / (dslug + '-PRD.md')}")
        print(f"   read by node_research as the founder brief, first act of "
              f"the run\n")
        head = text.splitlines()
        for line in head[:40]:
            print("   " + line)
        if len(head) > 40:
            print(f"   … and {len(head) - 40} more lines")
        print("""
Nothing was written and nothing was spent.

This proves the brief exists and is not empty — the thing the failed run
tripped on. It does not prove the run succeeds; only starting it does.
""")
        return 0

    try:
        phase = pe.next_phase(a.epic)
    except pe.EpicError as e:
        die(str(e))
    if phase is None:
        print(f"{a.epic}: every phase is finished.")
        return 0

    slug = phase["phase_slug"]
    ptype = epic["product_type"]

    print(f"{a.epic}  [{epic['status']}]  → products/{epic['product_slug']}/\n")
    print(f"  phase        {phase['seq']} of {len(epic['phases'])} — {phase['title']}")
    print(f"  slug         {slug}")
    print(f"  type         {ptype or '(none recorded — the pathway would be inferred)'}")
    print(f"  engine       {a.engine} · coder {a.coder} · {a.complexity}")
    print(f"  depends on   {phase['depends_on'] or '(nothing)'}")

    if not ptype:
        die("the epic records no product_type, so the pathway would be "
            "inferred from a PRD that does not exist yet. Set it in the plan "
            "and redefine the epic.")

    # ── the row ─────────────────────────────────────────────────────────────
    from ducorn_db import get_conn
    with get_conn() as c:
        cur = c.cursor()
        cur.execute("SELECT id, status FROM pipeline_runs WHERE slug = %s",
                    (slug,))
        row = cur.fetchone()

    if row:
        print(f"\n  pipeline_runs row exists (status {row[1]})")
        if row[1] in ("running", "started", "created", "awaiting_approval"):
            die(f"the run for {slug} is already {row[1]}. Stop it first, or "
                f"resume it from the dashboard.")
    else:
        print(f"\n  pipeline_runs row will be CREATED — a CLI run cannot "
              f"create one for itself")

    budget = None
    try:
        import ducorn_spend
        budget = ducorn_spend.budget_status()
        print(f"  budget       {budget['message']}")
    except Exception as e:
        print(f"  budget       could not be read ({type(e).__name__})")

    if not a.apply:
        print("\nRe-run with --apply to start it, or --dry-run to see the "
              "prompt for free.")
        return 0

    # One implementation. The endpoint calls start_next too — a CLI that
    # repeated the insert-and-launch would be a second place for "how a phase
    # starts" to be defined, and they would differ within a fortnight.
    try:
        r = start_next(a.epic, engine=a.engine, coder=a.coder,
                       complexity=a.complexity, environment=a.environment)
    except NotStartable as e:
        die(str(e))

    print(f"""
started phase {r['seq']} — {r['title']} — pid {r['pid']}

  watch    tail -f {r['log']}
  status   python3 scripts/product_epics.py --show {a.epic}
  stop     curl -sX POST localhost:8000/pipeline/kill/{r['started']}

The phase's status follows its run: nothing has to mark it finished.
""")
    return 0


if __name__ == "__main__":
    from bootstrap_python import ensure_modules
    ensure_modules("psycopg2")
    sys.exit(main())
