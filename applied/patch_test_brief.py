#!/usr/bin/env python3
"""
Fix the seed brief I wrote an hour ago. It sent SAGE hunting for a file.

── WHAT HAPPENED ────────────────────────────────────────────────────────────

My seed brief said, in full innocence:

    "A small internal tool used only by the DuCorn test suite.
     It reads one CSV and prints a total."

llama3.1 took "reads one CSV" literally and went looking for the CSV:

    Tool: file_read_tool  {'file_path': '/Users/ducorn/DC/input.csv'}
    → BLOCKED: outside the jail for 'pipeline-test-product-c1'
    Tool: file_read_tool  {'file_path': '/products/pipeline-test-product-c1/input.csv'}
    → BLOCKED: outside the jail
    ... 18 blocked reads in c1, and the e2e run burned all 15 iterations.

So the combo tests did not hang on anything structural. They hung because the
brief described an input that does not exist, and a local model will keep
guessing paths until max_iter stops it. These tests used to finish inside 600s
researching from the product name alone; the seed made them slower, not
faster, which is entirely on me.

── TWO CHANGES ──────────────────────────────────────────────────────────────

1. The brief describes a product with nothing to fetch, and says so in the
   words the agent will read: no files, no data sources, no web. A fixture
   exists to exercise the pipeline, not to be an interesting product.

2. A timeout now reports WHY. What surfaced was a bare TimeoutExpired
   traceback pointing at subprocess.py — nothing about the run. The flow
   writes logs/flow_<slug>.log, so on a timeout the test now prints the tail
   of it and counts the blocked tool calls, which is the exact signal that
   would have named this in ten seconds instead of ten minutes.

── SEPARATELY, AND WORTH A LOOK LATER ───────────────────────────────────────

The jail's refusal is a dead end for the agent:

    BLOCKED: '/Users/ducorn/DC/input.csv' is outside the jail for '<slug>'.
    Allowed: products/<slug>/** and docs/<slug>-*

Those allowed paths are relative, so the model's next guess was
'/products/<slug>/input.csv' — absolute, still wrong, still blocked. A refusal
that gave the absolute base directory, and listed what is actually in it,
would end the guessing on the first try. That is production behaviour, not
test behaviour, and it is not in this patch — flagging it, not fixing it.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PIPE = Path("/Users/ducorn/DC/ducorn/test_pipeline.py")
p = PIPE.read_text(encoding="utf-8")

if "_run_flow" in p:
    sys.exit("Already patched — _run_flow exists.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. a brief with nothing to go looking for ────────────────────────────────
p = swap("seed text", p, '''    seed = (f"# {topic}\\n\\n"
            f"A small internal tool used only by the DuCorn test suite. "
            f"It reads one CSV and prints a total. No UI, no users, no "
            f"integrations. {BRIEF_CANARY}\\n{extra}\\n")''',
         '''    # Every noun here is deliberate. The first version of this brief said
    # the tool "reads one CSV", and llama3.1 spent all fifteen of its
    # iterations guessing paths to a CSV that does not exist, each one
    # refused by the jail. A fixture brief exists to exercise the pipeline,
    # so it must describe something that needs nothing fetched — and say so
    # in words the agent reads, since it will otherwise invent an input.
    seed = (f"# {topic}\\n\\n"
            f"Fixture product for the DuCorn test suite. Never shipped, never "
            f"seen by a user.\\n\\n"
            f"WHAT IT IS: a single command that prints the ten phases of the "
            f"DuCorn pipeline, in order, one per line: research, gate 1, "
            f"design, gate 2, build, QA, gate 3, launch, gate 4, deploy. "
            f"That is the whole product.\\n\\n"
            f"BINDING CONSTRAINTS: it takes no arguments and no input. There "
            f"are no files to read, no CSVs, no data sources, no APIs, no "
            f"database, no configuration and no authentication. Everything "
            f"needed to write the PRD is in this brief — do not look for "
            f"files and do not search the web.\\n\\n"
            f"{BRIEF_CANARY}\\n{extra}\\n")''')

# ── 2. a timeout that says what the run was doing ────────────────────────────
p = swap("run helper", p, '''def test(name):
    """Decorator for test functions."""''', '''def _run_flow(argv, env, timeout=600):
    """
    Run langgraph_flow.py and, on a timeout, say what it was stuck on.

    A bare TimeoutExpired points at subprocess.py and tells you nothing. The
    flow writes logs/flow_<slug>.log, and the useful signal — an agent
    guessing file paths against the jail — is right at the end of it.
    """
    slug = argv[2]
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, env=env,
                              cwd="/Users/ducorn/DC/ducorn")
    except subprocess.TimeoutExpired as e:
        log = Path("/Users/ducorn/DC/logs") / f"flow_{slug}.log"
        tail, blocked = "(no log)", 0
        if log.exists():
            text = log.read_text(errors="replace")
            blocked = text.count("BLOCKED:")
            tail = "\\n".join(text.splitlines()[-25:])
        raise AssertionError(
            f"{slug} did not finish in {timeout}s.\\n"
            f"  blocked tool calls in the log: {blocked}"
            f"{'  ← the agent is hunting for a file that does not exist' if blocked > 3 else ''}\\n"
            f"  log: {log}\\n"
            f"  --- last 25 lines ---\\n{tail}") from e


def test(name):
    """Decorator for test functions."""''')

# ── 3. both callers use it ───────────────────────────────────────────────────
p = swap("e2e caller", p, '''    result = subprocess.run(
        ["/Users/ducorn/DC/ducorn/.venv/bin/python",
         "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
         topic, "--phase", "research", "--engine", "fast", "--coder", "crewai"],
        capture_output=True, text=True, timeout=600, env=env,
        cwd="/Users/ducorn/DC/ducorn"
    )''', '''    result = _run_flow(
        ["/Users/ducorn/DC/ducorn/.venv/bin/python",
         "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
         topic, "--phase", "research", "--engine", "fast", "--coder", "crewai"],
        env)''')

p = swap("combo caller", p, '''    result = subprocess.run(
        ["/Users/ducorn/DC/ducorn/.venv/bin/python",
         "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
         topic, "--phase", "research",
         "--engine", engine, "--coder", coder, "--complexity", complexity],
        capture_output=True, text=True, timeout=600, env=env,
        cwd="/Users/ducorn/DC/ducorn"
    )''', '''    result = _run_flow(
        ["/Users/ducorn/DC/ducorn/.venv/bin/python",
         "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
         topic, "--phase", "research",
         "--engine", engine, "--coder", coder, "--complexity", complexity],
        env)''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PIPE.with_name(f"test_pipeline.backup-brief-{stamp}.py")
shutil.copy2(PIPE, backup)
PIPE.write_text(p, encoding="utf-8")

try:
    ast.parse(p)
except SyntaxError as e:
    shutil.copy2(backup, PIPE)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Clear the half-written fixtures from the timed-out run first:")
print("  rm -f ~/DC/ducorn-products/docs/pipeline-test-product-c*-PRD.md")
print("  rm -f ~/DC/ducorn-products/docs/pipeline-test-product-e2e-PRD.md")
print()
print("Then:  cd ~/DC/ducorn && .venv/bin/python test_pipeline.py")
