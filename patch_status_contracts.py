#!/usr/bin/env python3
"""
One place that says which statuses exist, so the schema can be checked against it.

── THE GAP ──────────────────────────────────────────────────────────────────

Tonight's gate-2 failure was a status the code writes and the database
refuses. Nothing compared the two, because there was nothing to compare: the
permitted values live in a CHECK constraint inside PostgreSQL, and the values
the code writes are string literals scattered across four files.

    langgraph_flow.py   'running', 'awaiting_approval', 'failed', ...
    skill_runner.py     'running', 'complete', 'failed'
    slack_bot.py        'approved', 'rejected', 'superseded'
    main.py             'stopped', 'pending', ...

A comparison needs two sides. This adds the missing one.

── WHAT IT ADDS ─────────────────────────────────────────────────────────────

STATUS_CONTRACTS in ducorn_db.py: table → the statuses the code may write to
it. ducorn_db is already the module every writer imports get_conn from, so it
is where a shared fact about the database belongs.

That constant is not decoration. scripts/prove_db_contracts.py reads the live
CHECK constraints out of the catalog and compares them with it in both
directions — a value the code can write that the database refuses is tonight's
bug, and it now fails a check rather than a founder's approval.

── HONEST ABOUT WHAT THIS IS AND IS NOT ─────────────────────────────────────

The writers still use their own literals; they are not yet routed through this
constant. So today it is a declaration checked against the schema, not an
enforcement of the writers. That closes the failure we actually had — a
migration missing for a status the code uses — and leaves one gap: a status
invented inline in a file nobody updated here.

prove_db_contracts.py covers that gap the only way it can from outside, by
scanning for status literals that appear in no contract and no constraint and
reporting them. Advisory, and labelled as advisory.

Routing every writer through the constant is the complete version. It touches
four files and a lot of call sites, and doing it at the end of a long day, on
a machine mid-run, is how the next class of bug gets introduced. It belongs on
the list rather than in this patch.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DB = Path("/Users/ducorn/DC/scripts/ducorn_db.py")
s = DB.read_text(encoding="utf-8")

if "STATUS_CONTRACTS" in s:
    sys.exit("Already patched — ducorn_db declares the status contracts.")

# The decorator, not just the def. Anchoring on "def get_conn():" alone
# inserts between @contextmanager and the function it decorates, which is a
# syntax error — the patch's own read-back caught that and reverted, which is
# the only reason you are not reading a broken ducorn_db.py.
anchor = "@contextmanager\ndef get_conn():"
if s.count(anchor) != 1:
    sys.exit(f"ANCHOR MISS: found {s.count(anchor)} of the get_conn "
             f"definition, expected 1. NOTHING WRITTEN.")

CONTRACTS = '''# ── status contracts ─────────────────────────────────────────────────────────
#
# Which statuses the code may write to each table. The other side of this
# contract is a CHECK constraint inside PostgreSQL, and on 1 September the two
# disagreed: gate 2 marks losing design variants 'superseded', the constraint
# allowed only pending/approved/rejected, and the mismatch surfaced as a failed
# approval on a paid run — because nothing compared them.
#
# scripts/prove_db_contracts.py does that comparison now, in both directions,
# reading the constraints out of the catalog rather than from a list.
#
# Adding a status here without a migration makes that check fail, which is the
# point. Adding one to the database without adding it here makes it report
# dead vocabulary, which is milder and also worth knowing.
STATUS_CONTRACTS = {
    "approval_requests": (
        "pending",           # raised, waiting on a founder
        "approved",          # the decision that releases next_phase
        "rejected",          # the founder said no
        "superseded",        # another variant of the same gate was chosen
    ),
    "agent_activity": (
        "started",
        "completed",
        "failed",
        "blocked",
    ),
}


'''

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = DB.with_name(f"ducorn_db.backup-contracts-{stamp}.py")
shutil.copy2(DB, backup)
DB.write_text(s.replace(anchor, CONTRACTS + anchor, 1), encoding="utf-8")

try:
    ast.parse(DB.read_text(encoding="utf-8"))
except SyntaxError as e:
    shutil.copy2(backup, DB)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# Read it back as data, not as text: the whole point of this constant is that
# another program imports it.
src = DB.read_text(encoding="utf-8")
node = next((n for n in ast.parse(src).body
             if isinstance(n, ast.Assign)
             and getattr(n.targets[0], "id", "") == "STATUS_CONTRACTS"), None)
if node is None:
    shutil.copy2(backup, DB)
    sys.exit(f"STATUS_CONTRACTS did not land — reverted from {backup}")

contracts = ast.literal_eval(node.value)
if "superseded" not in contracts.get("approval_requests", ()):
    shutil.copy2(backup, DB)
    sys.exit(f"the status that caused tonight's failure is not in the "
             f"contract — reverted from {backup}")

print("applied: ducorn_db declares STATUS_CONTRACTS")
for table, values in sorted(contracts.items()):
    print(f"  {table}: {', '.join(values)}")
print(f"backup:  {backup.name}")
print()
print("Now check it against the live schema:")
print("  python3 scripts/prove_db_contracts.py")
print()
print("It should fail until migration 005 is applied, and pass after.")
