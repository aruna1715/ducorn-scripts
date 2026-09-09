#!/usr/bin/env python3
"""
NOVA can read every product on the machine. Jail it.

    cd ~/DC && python3 scripts/patch_nova_jail.py            show
    cd ~/DC && python3 scripts/patch_nova_jail.py --apply    do it

Needs scripts/patchlib.py.

── THE BREACH ───────────────────────────────────────────────────────────────

node_launch, line 1582:

    tools=[FileReadTool(base_dir=str(PRODUCTS_DIR)), DuCornWriterTool()],

PRODUCTS_DIR is the whole ducorn-products repository — every product, every
doc, every PRD. NOVA writes a launch announcement for ONE product with read
access to all twenty-three of them.

Every other agent in this pipeline is jailed. node_research uses
JailedFileReadTool(topic=topic); skill_runner uses that and
JailedDirectoryReadTool. This one node was missed, and it is the last node
before deploy — the point at which the most has been built.

DuCornWriterTool() with no topic is the same hole on the write side. Its own
signature says so: "topic: set for per-product runs; None for company docs".
A launch announcement for a named product is a per-product run.

── WHY IT MATTERS HERE SPECIFICALLY ─────────────────────────────────────────

    "I DONOT want product 1 to read product2's file EVER. We dont want any
     data overlapping between product runs - this is a showstopper for us."

The jail work already closed the research, build, review and QA paths. This
is the one that was left, and it was found by reading rather than by a run
tripping over it — which is the only way an over-permissive read is ever
found, because nothing fails when an agent reads too much.

── WHAT ELSE THE SWEEP FOUND ────────────────────────────────────────────────

ducorn/flows/main_flow.py has four more unjailed FileReadTool /
DirectoryReadTool pairs. It is the pre-LangGraph flow, nothing invokes it,
and langgraph_flow.py's own header says it replaces it. Dead code, so not
patched here — but dead code with a hole in it is a hole waiting for someone
to revive the file. It should be deleted, separately and deliberately.

── AFTER THIS ───────────────────────────────────────────────────────────────

NOVA reads its own product directory and the phases its epic declares — the
same view every other agent gets — and writes through the jail, which already
permits docs/<topic>-*.md because that is how SAGE saves a PRD.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "novajail"

OLD_IMPORT = '''        from crewai import Agent, Task, Crew
        from crewai_tools import FileReadTool
        from tools.DuCornWriterTool import DuCornWriterTool

        nova = Agent('''

NEW_IMPORT = '''        from crewai import Agent, Task, Crew
        from tools.jailed_tools import JailedFileReadTool
        from tools.DuCornWriterTool import DuCornWriterTool

        nova = Agent('''

OLD_TOOLS = '''            tools=[FileReadTool(base_dir=str(PRODUCTS_DIR)), DuCornWriterTool()],'''

NEW_TOOLS = '''            # JAILED, like every other agent in this pipeline.
            #
            # This was FileReadTool(base_dir=PRODUCTS_DIR) — the whole
            # repository — so NOVA wrote a launch announcement for one
            # product while able to read all of them. And DuCornWriterTool()
            # with no topic skips resolve_in_jail entirely; its own signature
            # says topic is "set for per-product runs", and this is one.
            tools=[JailedFileReadTool(topic=topic),
                   DuCornWriterTool(topic=topic)],'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (FLOW, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src = FLOW.read_text(encoding="utf-8")
print("patch_nova_jail\n")

if "JailedFileReadTool(topic=topic),\n                   DuCornWriterTool" in src:
    sys.exit("NOTHING DONE — NOVA is already jailed.")

bad = False
for label, a in [("NOVA's imports", OLD_IMPORT), ("NOVA's tools", OLD_TOOLS)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

jail = DC / "ducorn" / "tools" / "jailed_tools.py"
if not jail.is_file() or "class JailedFileReadTool" not in jail.read_text(
        encoding="utf-8"):
    sys.exit("NOTHING DONE — tools/jailed_tools.py has no JailedFileReadTool.")
print("  ok  JailedFileReadTool exists and is what the other nodes use")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(FLOW, FLOW.with_suffix(f".backup-{TAG}-{stamp}.py"))
FLOW.write_text(src.replace(OLD_IMPORT, NEW_IMPORT, 1)
                   .replace(OLD_TOOLS, NEW_TOOLS, 1), encoding="utf-8")
print(f"\nwrote {FLOW.name}, backup tagged {TAG}-{stamp}")

after = FLOW.read_text(encoding="utf-8")
try:
    py_ok(after, "langgraph_flow.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# In CODE. The comments above quote the old spelling, and checks in this repo
# have read their own prose four times.
code = code_only(after)
if "FileReadTool(base_dir=" in code:
    sys.exit("⚠️  an unjailed FileReadTool is still in this file — restore "
             "the backup.")
if "DuCornWriterTool()" in code:
    sys.exit("⚠️  an untopiced DuCornWriterTool is still in this file — "
             "restore the backup.")
print("verified: it parses; no unjailed read tool and no untopiced writer "
      "remain in code.")

print("""
  python3 scripts/prove_isolation.py

The launch node now reads through the same jail as research and build.
""")
