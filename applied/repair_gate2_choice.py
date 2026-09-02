#!/usr/bin/env python3
"""
Finish a gate-2 approval that the status constraint interrupted.

    python3 scripts/repair_gate2_choice.py <slug>            # look
    python3 scripts/repair_gate2_choice.py <slug> --apply    # finish it

── WHAT HAPPENED ────────────────────────────────────────────────────────────

    ❌ Approved, but I could not record the design choice
       (new row ... violates check constraint "approval_requests_status_check")
       Build not started.

Approving one variant marks the other two superseded. 'superseded' was not in
the status constraint, so the approval landed and the bookkeeping after it did
not — leaving the run between two states: a decision made, and nothing that
knows which one.

Migration 005 widens the constraint. This finishes the row-work that was
interrupted, because the Slack command will not run it again: it sees an
approval already decided and declines to decide it twice, which is correct
behaviour and no help here.

── WHAT IT DOES ─────────────────────────────────────────────────────────────

Reads the gate-2 approvals for the product, works out which one you approved,
and then:

  · marks the losing variants superseded, pointing at the winner
  · sets pipeline_runs.design_choice to the winner's file, which is what
    node_build copies to APPROVED_DESIGN.html

It refuses to guess. If no variant is approved, or more than one is, it says so
and changes nothing — picking a design on your behalf is exactly the decision
this gate exists to put in front of you.

It does not start the build. Resume that from the dashboard or the CLI once
this reports the choice is recorded, so you can see the state before spending
anything.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from bootstrap_python import ensure_modules  # noqa

ensure_modules("psycopg2")

from ducorn_db import get_conn  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    slug = args.slug

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT id, variant_name, path, approval_id
                       FROM design_variants WHERE slug=%s ORDER BY id""",
                    (slug,))
        variants = cur.fetchall()
        if not variants:
            return f"no design_variants rows for {slug!r}"

        ids = [v[3] for v in variants if v[3]]
        cur.execute("""SELECT id, status, superseded_by FROM approval_requests
                       WHERE id = ANY(%s) ORDER BY id""", (ids,))
        approvals = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        cur.execute("SELECT design_choice, status FROM pipeline_runs WHERE slug=%s",
                    (slug,))
        row = cur.fetchone()
        design_choice, run_status = (row if row else (None, None))

    print(f"\n{slug} — run status {run_status!r}")
    print(f"design_choice: {design_choice or '(not set)'}\n")

    approved = []
    for vid, name, path, approval_id in variants:
        status, sup = approvals.get(approval_id, ("(no row)", None))
        mark = "  ← approved" if status == "approved" else ""
        print(f"  approval {approval_id}  {status:12} {name}{mark}")
        print(f"      {path}")
        if status == "approved":
            approved.append((approval_id, name, path))

    if len(approved) == 0:
        return ("no variant is approved — nothing to record. Approve one in "
                "Slack first.")
    if len(approved) > 1:
        return (f"{len(approved)} variants are marked approved "
                f"({', '.join(str(a[0]) for a in approved)}). Which one is the "
                f"design is your decision, not mine — set the others to "
                f"'superseded' by hand, then run this again.")

    winner_id, winner_name, winner_path = approved[0]
    losers = [(v[3], v[1]) for v in variants if v[3] != winner_id]

    if not Path(winner_path).is_file():
        return (f"the approved variant's file is missing:\n   {winner_path}\n"
                f"   Recording a choice that points at nothing would fail again "
                f"in node_build.")

    print(f"\nwinner: {winner_name}  (approval {winner_id})")
    print(f"to supersede: {', '.join(f'{i} ({n})' for i, n in losers) or 'none'}")

    if not args.apply:
        print("\nNothing changed. Re-run with --apply.")
        return 1

    with get_conn() as conn:
        cur = conn.cursor()
        for loser_id, _name in losers:
            cur.execute("""UPDATE approval_requests
                           SET status='superseded', superseded_by=%s
                           WHERE id=%s AND status <> 'approved'""",
                        (winner_id, loser_id))
        cur.execute("UPDATE pipeline_runs SET design_choice=%s WHERE slug=%s",
                    (winner_path, slug))

    # Read it back. An UPDATE that matched no rows and an UPDATE that worked
    # look identical from here otherwise, and that distinction has cost this
    # project a whole evening.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT design_choice FROM pipeline_runs WHERE slug=%s", (slug,))
        got = (cur.fetchone() or [None])[0]
        cur.execute("""SELECT count(*) FROM approval_requests
                       WHERE id = ANY(%s) AND status='superseded'""",
                    ([i for i, _ in losers],))
        n_sup = cur.fetchone()[0]

    if got != winner_path:
        return f"design_choice did not stick — reads back as {got!r}"
    print(f"\n✅ design_choice = {got}")
    print(f"✅ {n_sup} of {len(losers)} other variants marked superseded")
    print("\nNow start the build:")
    print(f"  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
          f"{slug} --phase build --engine gstack --coder crewai "
          f"--complexity simple")
    print("  (or press RESUME on the dashboard)")
    return 0


if __name__ == "__main__":
    r = main()
    if isinstance(r, str):
        sys.exit(f"❌ {r}")
    sys.exit(r)
