#!/usr/bin/env python3
"""
Record what each skill cost, at the moment it costs it.

    cd ~/DC && python3 scripts/patch_skill_cost.py            show
    cd ~/DC && python3 scripts/patch_skill_cost.py --apply    do it

Needs scripts/patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

Three columns exist to hold this and none has ever held anything:

    pipeline_runs.cost_so_far          always 0
    pipeline_skill_runs.cost           always 0
    pipeline_skill_runs.started_at     always null
    pipeline_skill_runs.completed_at   always null

langgraph_flow._update_db_status even takes a `cost` parameter — twenty-three
call sites, not one passes it. So the dashboard has printed "$0.00 spent"
beside every product since the column was added, while phase 1 of the admin
rebuild went through real money.

Trying to reconstruct it afterwards does not work. LiteLLM_SpendLogs records
spend per API KEY, and the keys are per agent, not per run — so the only
reconstruction available is "everything spent between this row's created_at
and updated_at", which for a run that sat failed overnight counts hours of
somebody else's work. Measured that way, this phase read $33 against about
$17 actually spent.

── THE FIX ──────────────────────────────────────────────────────────────────

Measure at the boundary. Total spend is readable at any instant from
LiteLLM_SpendLogs; a skill's cost is the difference across it:

    before = ducorn_spend.total_spend()
    ... the skill runs ...
    cost = ducorn_spend.total_spend() - before

Seconds-to-minutes windows instead of hours, recorded against the skill that
spent it, at the moment it happened. Concurrency can still blur a boundary,
but a run overlapping for the ninety seconds of one skill is a different
error from one overlapping for fourteen hours.

── FAILING HONESTLY ─────────────────────────────────────────────────────────

If the spend database cannot be read, the cost is recorded as NULL, not 0.
The whole reason this file exists is that a confident zero is worse than an
admitted gap: one of them answers "is this getting expensive" with "no".
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
SPEND = DC / "scripts" / "ducorn_spend.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "skillcost"

# ── 1. ducorn_spend gains an all-time total ──────────────────────────────────
SPEND_OLD = '''def today_spend() -> float:
    """Everything spent since local midnight. Raises SpendUnknown."""
    return _sum(_TODAY)'''

SPEND_NEW = '''def total_spend() -> float:
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
    return _sum(_TODAY)'''

# ── 2. skill_runner records it ───────────────────────────────────────────────
DB_OLD = '''def update_db_status(topic: str, skill_name: str, status: str):
    """Update pipeline skill status in DB."""'''

DB_NEW = '''def _spend_now():
    """
    The spend odometer, or None.

    None, never 0. A zero here would be recorded as "this skill was free",
    which is exactly the lie pipeline_runs.cost_so_far has been telling.
    """
    try:
        import ducorn_spend
        return ducorn_spend.total_spend()
    except Exception as e:
        print(f"💸 spend unreadable ({type(e).__name__}) — this skill's cost "
              f"will be recorded as unknown, not as zero", flush=True)
        return None


def update_db_status(topic: str, skill_name: str, status: str,
                     cost: float = None):
    """Update pipeline skill status in DB, and its cost when it is known."""'''

SQL_OLD = '''                UPDATE pipeline_skill_runs SET status=%s
                WHERE pipeline_id=(SELECT id FROM pipeline_runs WHERE slug=%s LIMIT 1)
                AND skill_name=%s
            """, (status, topic, skill_name))'''

SQL_NEW = '''                UPDATE pipeline_skill_runs
                   SET status=%s,
                       started_at   = COALESCE(started_at,
                                               CASE WHEN %s = 'running'
                                                    THEN NOW() END),
                       completed_at = CASE WHEN %s IN ('complete','failed')
                                           THEN NOW() ELSE completed_at END,
                       cost         = COALESCE(%s, cost)
                WHERE pipeline_id=(SELECT id FROM pipeline_runs WHERE slug=%s LIMIT 1)
                AND skill_name=%s
            """, (status, status, status, cost, topic, skill_name))
            # The run's total, from the same measurement. cost_so_far has read
            # 0.00 on every product on the dashboard since it was added,
            # because nothing ever added to it.
            if cost is not None:
                cur.execute("""
                    UPDATE pipeline_runs
                       SET cost_so_far = COALESCE(cost_so_far, 0) + %s,
                           updated_at = NOW()
                     WHERE slug = %s
                """, (cost, topic))'''

# ── 3. measure across the skill ──────────────────────────────────────────────
RUN_OLD = '''        if use_cursor:
            engine = os.environ.get("BUILD_ENGINE", "fast")
            output = run_with_cursor(skill_num, topic, context, engine=engine)
        else:
            output = run_with_crewai(skill_num, topic, context)'''

RUN_NEW = '''        # The odometer, either side of the only part that spends.
        _spend_before = _spend_now()
        if use_cursor:
            engine = os.environ.get("BUILD_ENGINE", "fast")
            output = run_with_cursor(skill_num, topic, context, engine=engine)
        else:
            output = run_with_crewai(skill_num, topic, context)
        _spend_after = _spend_now()
        _skill_cost = (None if _spend_before is None or _spend_after is None
                       else round(max(0.0, _spend_after - _spend_before), 4))
        if _skill_cost is not None:
            print(f"💸 {skill_name}: ${_skill_cost:.2f}", flush=True)'''

# ── 4. pass it where the outcome is recorded ─────────────────────────────────
PASS_OLD = '''        if status == "pass":
            update_db_status(topic, skill_name, "complete")'''
PASS_NEW = '''        if status == "pass":
            update_db_status(topic, skill_name, "complete", cost=_skill_cost)'''

FAIL_OLD = '''        else:
            update_db_status(topic, skill_name, "failed")'''
FAIL_NEW = '''        else:
            # A failed skill still spent the money. Recording cost only on
            # success would hide exactly the retries that cost the most.
            update_db_status(topic, skill_name, "failed", cost=_skill_cost)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, SPEND, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

print("patch_skill_cost\n")
sp = SPEND.read_text(encoding="utf-8")
sr = RUNNER.read_text(encoding="utf-8")

if "def total_spend" in sp and "_spend_now" in sr:
    sys.exit("NOTHING DONE — skills already record their cost.")

bad = False
for label, hay, a in [("ducorn_spend.today_spend", sp, SPEND_OLD),
                      ("update_db_status", sr, DB_OLD),
                      ("its UPDATE", sr, SQL_OLD),
                      ("the run site", sr, RUN_OLD),
                      ("the pass branch", sr, PASS_OLD),
                      ("the fail branch", sr, FAIL_OLD)]:
    n = hay.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(SPEND, SPEND.with_suffix(f".backup-{TAG}-{stamp}.py"))
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
SPEND.write_text(sp.replace(SPEND_OLD, SPEND_NEW, 1), encoding="utf-8")
out = (sr.replace(DB_OLD, DB_NEW, 1).replace(SQL_OLD, SQL_NEW, 1)
         .replace(RUN_OLD, RUN_NEW, 1).replace(PASS_OLD, PASS_NEW, 1)
         .replace(FAIL_OLD, FAIL_NEW, 1))
RUNNER.write_text(out, encoding="utf-8")
print(f"\nwrote ducorn_spend.py and skill_runner.py, backups tagged "
      f"{TAG}-{stamp}")

for f in (SPEND, RUNNER):
    try:
        py_ok(f.read_text(encoding="utf-8"), f.name)
    except PatchCheckFailed as e:
        sys.exit(f"⚠️  {e} — restore the backups.")

after = RUNNER.read_text(encoding="utf-8")
# BOTH outcomes must record. Recording only the passes would hide the retries.
recorded = [c for c in calls_in(after, "main", "update_db_status")
            if "cost=" in c]
if len(recorded) != 2:
    sys.exit(f"⚠️  {len(recorded)} of the outcome branches record a cost, "
             f"expected 2 (pass and fail) — restore the backups.")
if len(calls_in(after, "main", "_spend_now")) != 2:
    sys.exit("⚠️  the odometer is not read on both sides of the skill — "
             "restore the backups.")
print("verified: both files parse; the odometer is read either side, and "
      "pass AND fail both record.")

r = subprocess.run([str(DC / "ducorn" / ".venv" / "bin" / "python"), "-c",
                    "import sys; sys.path.insert(0,'/Users/ducorn/DC/scripts');"
                    "import ducorn_spend as s; print('TOTAL', s.total_spend())"],
                   capture_output=True, text=True)
print(f"  odometer reads: {(r.stdout or r.stderr).strip()[:80]}")

print("""
From the next skill onward, the log prints 💸 per skill and the run's
cost_so_far becomes a real number — which is what the dashboard has been
showing as $0.00 all along.

It cannot recover what the earlier skills cost. Those are gone; only the
window estimate exists for them, and that one over-counts.
""")
