#!/usr/bin/env python3
"""
Third revision of the fixture brief. This time it names nothing.

── THE TWO PREVIOUS ATTEMPTS ────────────────────────────────────────────────

    v1  "It reads one CSV and prints a total."
        → llama3.1 went looking for the CSV. Eighteen blocked reads.

    v2  "prints the ten phases of the DuCorn pipeline: research, gate 1, ..."
        → llama3.1 recognised DuCorn as the system it was running inside, took
          the stack context block as its source material, and wrote an
          inventory of our services and environment-variable names instead of
          a PRD.

I fixed v1 by removing the file and left in a reference to DuCorn. The rule I
should have written down after v1 is more general than "no files":

    A FIXTURE BRIEF MUST NAME NOTHING THE AGENT CAN GO AND LOOK AT.

Not a file, not a data source, and not the system the agent is running inside —
which is the one I missed, because it did not look like an input.

── v3 ───────────────────────────────────────────────────────────────────────

A temperature converter. It has no inputs, no dependencies, no relationship to
DuCorn, and nothing about it can be researched. It is deliberately boring: a
fixture exists to make the pipeline move, and every interesting noun in it is
a place the run can wander off to.

The constraints are also stated in the brief itself, in the imperative, because
that is the only part of the prompt a local model reliably obeys.

Note this is now belt AND braces. patch_research_context.py stops the stack
context reaching a brief like v2 in the first place; this makes the fixture
harmless even if something else starts handing agents things to read.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PIPE = Path("/Users/ducorn/DC/ducorn/test_pipeline.py")
p = PIPE.read_text(encoding="utf-8")

if "unitconv" in p:
    sys.exit("Already patched — the fixture brief is v3.")

OLD = '''    seed = (f"# {topic}\\n\\n"
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
            f"{BRIEF_CANARY}\\n{extra}\\n")'''

NEW = '''    # THE RULE, learned twice: a fixture brief must name nothing the agent can
    # go and look at. Not a file (v1 said "reads one CSV" and the model spent
    # eighteen tool calls hunting for it), and not the system the agent is
    # running inside (v2 said "the DuCorn pipeline" and the model wrote an
    # inventory of our own services instead of a PRD). A temperature converter
    # has no inputs, no dependencies and nothing to research — which is the
    # entire point of it.
    seed = (f"# {topic}\\n\\n"
            f"Fixture product for an automated test suite. Never shipped, "
            f"never seen by a user.\\n\\n"
            f"WHAT IT IS: a command-line tool called unitconv that converts a "
            f"temperature between Celsius and Fahrenheit. It takes a number "
            f"and a unit letter as arguments, prints the converted value to "
            f"one decimal place, and exits. Invalid input prints a usage line "
            f"and exits non-zero. That is the whole product.\\n\\n"
            f"BINDING CONSTRAINTS, all of them: no input files, no CSVs, no "
            f"data sources, no APIs, no database, no configuration, no "
            f"authentication, no user interface, no third-party libraries. "
            f"Everything needed to write the PRD is in this brief. Do not "
            f"look for files. Do not search the web. Do not describe the "
            f"system this test is running on. Write the PRD once and stop.\\n\\n"
            f"{BRIEF_CANARY}\\n{extra}\\n")'''

if p.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {p.count(OLD)} copies of the v2 brief, "
             f"expected 1. Has patch_test_brief.py been applied? "
             f"NOTHING WRITTEN.")

p = p.replace(OLD, NEW, 1)

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PIPE.with_name(f"test_pipeline.backup-brief3-{stamp}.py")
shutil.copy2(PIPE, backup)
PIPE.write_text(p, encoding="utf-8")

try:
    ast.parse(p)
except SyntaxError as e:
    shutil.copy2(backup, PIPE)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# Check it rather than trust it: this is the third attempt, and both previous
# ones failed on a noun in the WHAT IT IS sentence. That sentence must name
# nothing belonging to us.
what = NEW[NEW.index("WHAT IT IS"):NEW.index("BINDING CONSTRAINTS")]
for word in ("ducorn", "csv", "langgraph", "litellm", "ollama", "pipeline",
             "dashboard", "slack", "gate"):
    if word in what.lower():
        shutil.copy2(backup, PIPE)
        sys.exit(f"the new brief still names {word!r} in its description — "
                 f"that is what broke v1 and v2. Reverted from {backup}")

print("applied: fixture brief v3 — a temperature converter, nothing to explore")
print(f"backup:  {backup.name}")
print()
print("Clear the contaminated fixtures before re-running:")
print("  rm -f ~/DC/ducorn-products/docs/pipeline-test-product-*-PRD.md")
