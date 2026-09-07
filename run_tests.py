#!/usr/bin/env python3
"""
Run the DuCorn test suite. Costs nothing.

    cd ~/DC && python3 scripts/run_tests.py            everything free
    cd ~/DC && python3 scripts/run_tests.py -k pathway just those
    cd ~/DC && python3 scripts/run_tests.py --list     what exists

── WHAT IT RUNS ─────────────────────────────────────────────────────────────

ducorn/tests/*.py — the cases from ducorn-pathway-tests.xlsx that need no
model, no network and no subprocess. No agent is invoked, so a full run
charges nothing and finishes in about a second.

── WHY IT IS NOT JUST `pytest` ──────────────────────────────────────────────

Three things you would otherwise have to remember every time, and one of
which has already caused an afternoon of confusion:

  · the interpreter. This Mac has four pythons. `python3` is 3.14 and has no
    psycopg2, so the tests that touch ducorn_db would error out on an import
    rather than on anything real. The pipeline runs on ducorn/.venv, and so
    does this.

  · the path. scripts/ and ducorn/ have to be importable, and the tests are
    not a package.

  · a missing pytest. Without it `python3 -m pytest` prints a module error
    that reads like the suite is broken. This says what to install.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
TESTS = DC / "ducorn" / "tests"


def interpreter() -> str:
    """The one the pipeline itself runs on."""
    for c in (DC / "ducorn" / ".venv" / "bin" / "python",
              Path("/opt/homebrew/bin/python3.12")):
        if c.exists():
            return str(c)
    return sys.executable


args = [a for a in sys.argv[1:]]

if not TESTS.is_dir():
    sys.exit(f"NOTHING TO RUN — {TESTS} does not exist.\n"
             f"The test files belong there, one per area group.")

files = sorted(p for p in TESTS.glob("test_*.py"))
if not files:
    sys.exit(f"NOTHING TO RUN — no test_*.py in {TESTS}")

if "--list" in args:
    print(f"{len(files)} test file(s) in {TESTS}:\n")
    for f in files:
        n = sum(1 for line in f.read_text(errors="replace").splitlines()
                if line.startswith("def test_"))
        print(f"  {f.name:28} {n:3} test function(s)")
    raise SystemExit(0)

py = interpreter()

# Is pytest actually there? `python -m pytest` on a venv without it prints
# "No module named pytest", which reads like the suite is broken rather than
# like a missing dependency.
probe = subprocess.run([py, "-c", "import pytest, sys; print(pytest.__version__)"],
                       capture_output=True, text=True)
if probe.returncode != 0:
    sys.exit(f"""NOTHING RUN — pytest is not installed in the interpreter the
pipeline uses:

  {py}

Install it there (this is the venv the agents run in, so it is the right
place for it):

  {py} -m pip install pytest
""")

print(f"DuCorn tests\n")
print(f"  interpreter  {py}")
print(f"  pytest       {probe.stdout.strip()}")
print(f"  files        {', '.join(f.name for f in files)}")
print(f"  cost         nothing — no model, no network, no subprocess\n")

env = {
    **os.environ,
    # The tests import product_pathways, ducorn_db and skill_runner directly.
    "PYTHONPATH": f"{DC / 'scripts'}:{DC / 'ducorn'}:{DC / 'ducorn' / 'tools'}",
    # Belt and braces: nothing here should reach a model, and if a test ever
    # does by accident it will fail on a bad address rather than spend.
    "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
    "OPENAI_API_KEY": "not-a-key-tests-must-not-call-models",
}

cmd = [py, "-m", "pytest", "-q", *[str(f) for f in files], *args]
r = subprocess.run(cmd, cwd=str(DC), env=env)
raise SystemExit(r.returncode)
