#!/usr/bin/env python3
"""
When pytest has already failed, do not pay a model to say so.

    cd ~/DC && python3 scripts/patch_tests_decide.py            show
    cd ~/DC && python3 scripts/patch_tests_decide.py --apply    do it

Needs scripts/patchlib.py.

── THE WASTE ────────────────────────────────────────────────────────────────

Skill 06 already runs the test suite itself, in code, for nothing:

    test_status, test_report = run_test_suite(topic)     # pytest. free.

Then it calls the model:

    output = run_with_crewai(skill_num, topic, context)  # paid. every time.

Then it throws the model's verdict away when the tests failed:

    if test_status == "fail":
        status = "fail"
        verdict = f"VERDICT: FAIL — test suite failed. {verdict}"

So on a failing suite the paid call cannot change the outcome. It is billed
to restate a result the pipeline already holds. That happened on every QA run
of the admin rebuild, including three laps inside one press of QA ONLY —
because route_after_qa sends a failure to qa_fix, which runs REX and comes
back to QA, up to three times.

── THE RULE ─────────────────────────────────────────────────────────────────

If a free check has already decided the verdict, the paid one does not run.

Tests failing is exactly that: deterministic, already computed, and
overriding. So skill 06 now records the failure from the pytest output and
exits before the model.

── WHAT STILL CALLS THE MODEL ───────────────────────────────────────────────

A PASSING suite. That is where IRIS has something to add that pytest cannot —
whether the tests cover what the product claims, whether the coverage is
honest. A judgement, not a restatement.

── WHAT THE NEXT ATTEMPT READS ──────────────────────────────────────────────

The pytest output itself: failing test names, assertions, tracebacks. That is
more use to a builder than prose describing it, and it is what REX needs to
fix the thing. Nothing is lost by not paying for the commentary.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "testsdecide"

OLD = '''    if args.dry_run:
        # The real assembly, stopped one line before the model. Nothing is
        # written to the checkpoint and no verdict is recorded.
        run_with_crewai(skill_num, topic, context, dry_run=True)
        sys.exit(0)

    # Run the skill
    try:'''

NEW = '''    if args.dry_run:
        # The real assembly, stopped one line before the model. Nothing is
        # written to the checkpoint and no verdict is recorded.
        run_with_crewai(skill_num, topic, context, dry_run=True)
        sys.exit(0)

    # ── THE TESTS ALREADY DECIDED ────────────────────────────────────────
    #
    # run_test_suite ran pytest above, in code, for nothing. When it fails,
    # the verdict logic below forces "fail" whatever the model returns:
    #
    #     if test_status == "fail": status = "fail"
    #
    # so the paid call cannot change the outcome. It would be billed to
    # restate a result this process is already holding in a variable. Every
    # QA lap of the admin rebuild paid for one of those, three of them inside
    # a single press of QA ONLY.
    #
    # A PASSING suite still goes to the model: judging whether the tests
    # cover what the product claims is a judgement, not a restatement.
    if skill_num == "06" and (test_status == "fail" or ui_status == "fail"):
        _why = "the test suite failed" if test_status == "fail" else ui_note
        verdict = (f"VERDICT: FAIL — {_why}. No model was called: pytest had "
                   f"already decided this.")
        # The report the next attempt reads is the pytest output — failing
        # tests, assertions, tracebacks. More use to a builder than prose
        # about them.
        output = (f"{verdict}\\n\\n"
                  f"TEST EXECUTION RESULTS (pytest, run by the pipeline — no "
                  f"model was called)\\n"
                  f"STATUS: {str(test_status).upper()}\\n\\n{test_report}\\n\\n"
                  f"UI TEST COVERAGE: {str(ui_status).upper()} — {ui_note}\\n")
        output_file.write_text(output)
        results[skill_key] = record(topic, "fail", verdict, output,
                                    prompt_sha=current_sha)
        save_checkpoint(topic, results)
        update_db_status(topic, skill_name, "failed")
        print(f"\\n❌ {skill_name} FAILED")
        print(verdict)
        print("💸 nothing was spent on this step — the tests decided it.")
        print("   Run them yourself, free, as many times as you like:")
        print(f"   {_venv_python(_product_dir(topic))} -m pytest "
              f"{_product_dir(topic)}/tests -q")
        try:
            import run_recovery as _rr
            print("\\n" + _rr.as_text(_rr.plan(topic)), flush=True)
        except Exception:
            pass
        post_slack(f"❌ *{skill_name}* FAILED — `{topic}`\\n> {verdict}")
        sys.exit(1)

    # Run the skill
    try:'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, ifs_in, py_ok, PatchCheckFailed   # noqa: E402

src = RUNNER.read_text(encoding="utf-8")
print("patch_tests_decide\n")

if "pytest had" in src and "already decided this" in src:
    sys.exit("NOTHING DONE — the short circuit is already there.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the point before the model  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# Everything the block leans on must be in scope at that point.
for needed in ("test_status, test_report = run_test_suite(topic)",
               "ui_status, ui_note = ui_test_coverage(topic)",
               "output_file = PRODUCTS_DIR",
               "def record(", "def save_checkpoint(",
               "_venv_python", "_product_dir"):
    if needed not in src:
        sys.exit(f"NOTHING DONE — {needed!r} is not in skill_runner; the "
                 f"block would raise NameError at the worst moment.")
print("  ok  test_status, ui_status, output_file, record, save_checkpoint "
      "and the venv helpers are all in scope")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

after = RUNNER.read_text(encoding="utf-8")
try:
    py_ok(after, "skill_runner.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# The short circuit must come BEFORE the model call, or it saves nothing.
# Position in the parse tree, scoped to main().
import ast  # noqa: E402
fn = next(n for n in ast.walk(py_ok(after, "main"))
          if isinstance(n, ast.FunctionDef) and n.name == "main")
dump = ast.dump(fn)
i_guard = dump.find("already decided this")
i_model = dump.find("run_with_crewai")
# the dry-run call is the first run_with_crewai; find the one after the guard
i_paid = dump.find("run_with_crewai", i_guard)
if not (0 <= i_guard < i_paid):
    sys.exit("⚠️  the short circuit is not before the paid call — restore "
             "the backup.")
print("verified: it parses, and the guard sits before the model call.")

# And it must still CALL the model when the tests pass.
if len(calls_in(after, "main", "run_with_crewai")) < 2:
    sys.exit("⚠️  the model call is gone entirely — a passing suite must "
             "still be judged. Restore the backup.")
print("          a passing suite still reaches the model.")

print("""
From now on a failing test suite costs nothing.

The loop that cost the most — qa → qa_fix → qa, up to three laps — now pays
for REX's fix attempts only, not a QA report on each lap that pytest had
already settled.

And you can run the tests yourself as often as you like, for free:

  ~/DC/ducorn/.venv/bin/python -m pytest \\
      ~/DC/ducorn-products/products/ducorn-admin-rebuild/tests -q
""")
