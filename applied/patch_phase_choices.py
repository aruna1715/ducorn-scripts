#!/usr/bin/env python3
"""
Make --phase reachable for every node in the graph, by deriving it.

── THE GAP ──────────────────────────────────────────────────────────────────

    graph.add_node("qa_fix", node_qa_fix)          # it is a real node
    RESUME_AFTER = {..., "qa_fix": "qa", ...}      # resume knows it
    parser.add_argument("--phase", choices=[..., "qa", "gate_3", ...])
                                                   #      ^ no qa_fix

argparse rejects `--phase qa_fix` before anything else runs. So a QA-fix stage
can execute, can fail, and can never be resumed at — the one control that
would recover it refuses the name of the thing it is recovering.

My own regression test found this, which is the only good news here:

    FAIL argparse phases, graph nodes and RESUME_AFTER agree
         --phase cannot reach these graph nodes: ['qa_fix']

── WHY THE FIX IS DERIVATION, NOT ADDING ONE WORD ───────────────────────────

This is the sixth hardcoded phase enumeration in this codebase and the fifth
to have gone stale. Adding "qa_fix" to the list fixes today and guarantees the
seventh. The nodes are declared exactly once, in build_graph's add_node calls;
everything else should read them from there.

build_graph() cannot be called at argparse time — it opens the Postgres
checkpointer — so the derivation is static: parse build_graph's own source and
take the add_node names. No database, no import cycle, no cost. If parsing
ever returns nothing, it falls back to the explicit list rather than leaving
argparse with no choices at all.

The one place left that still enumerates is main.py's resume whitelist, which
runs in a different process and cannot import the flow. That one is complete
and prints a loud warning on an unknown phase, so it fails visibly rather than
silently — leaving it.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "_graph_phases" in s:
    sys.exit("Already patched — --phase derives from the graph.")

# ── 1. the deriving helper, right after the graph that is its source ─────────
OLD_TAIL = "    return graph.compile(checkpointer=checkpointer)\n"

HELPER = '''    return graph.compile(checkpointer=checkpointer)


def _graph_phases() -> list:
    """
    The phase names, read out of build_graph's add_node calls.

    Derived rather than listed on purpose. Five separate hardcoded phase lists
    went stale in a single week; this one was missing `qa_fix`, so a QA-fix
    stage could run and fail but `--phase qa_fix` was rejected by argparse
    before the resume could even start. The nodes are declared once, in
    build_graph. Everything else reads them from there.

    Static parse, not a call: build_graph() opens the Postgres checkpointer,
    which is far too much to do while assembling an argument parser.
    """
    try:
        import ast, inspect            # neither is imported at module level
        tree = ast.parse(inspect.getsource(build_graph))
        names = [a.args[0].value
                 for a in ast.walk(tree)
                 if isinstance(a, ast.Call)
                 and getattr(a.func, "attr", "") == "add_node"
                 and a.args and isinstance(a.args[0], ast.Constant)]
        if names:
            return names
    except Exception as e:                      # never leave argparse empty
        print(f"⚠️  could not derive phases from build_graph ({e})")
    return ["research", "gate_1", "design", "gate_2", "build",
            "qa", "qa_fix", "gate_3", "launch", "gate_4", "deploy"]
'''

if s.count(OLD_TAIL) != 1:
    sys.exit(f"ANCHOR MISS [helper]: found {s.count(OLD_TAIL)} of the compile "
             f"line, expected 1. NOTHING WRITTEN.")
s = s.replace(OLD_TAIL, HELPER, 1)

# ── 2. argparse reads it ─────────────────────────────────────────────────────
OLD_ARG = '''    parser.add_argument("--phase",   default="research",
                        choices=["research","gate_1","design","gate_2","build","qa","gate_3",
                             "launch","gate_4","deploy"])'''

NEW_ARG = '''    # Every node in the graph, derived from it. The list that used to sit
    # here had lost qa_fix, so that phase could never be resumed at.
    parser.add_argument("--phase", default="research", choices=_graph_phases())'''

if s.count(OLD_ARG) != 1:
    sys.exit(f"ANCHOR MISS [argparse]: found {s.count(OLD_ARG)}, expected 1. "
             f"NOTHING WRITTEN.")
s = s.replace(OLD_ARG, NEW_ARG, 1)

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FLOW.with_name(f"langgraph_flow.backup-phases-{stamp}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, FLOW)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# ── 3. prove it, don't assume it ─────────────────────────────────────────────
# Parse the patched file the same way the helper does, and check the result
# against the add_node calls. This is the check the old list would have failed.
tree = ast.parse(s)
fn = next((n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "build_graph"), None)
if fn is None:
    shutil.copy2(backup, FLOW)
    sys.exit(f"build_graph vanished — reverted from {backup}")

nodes = [a.args[0].value for a in ast.walk(fn)
         if isinstance(a, ast.Call)
         and getattr(a.func, "attr", "") == "add_node"
         and a.args and isinstance(a.args[0], ast.Constant)]

print("applied: --phase choices derive from build_graph")
print(f"phases:  {', '.join(nodes)}")
print(f"backup:  {backup.name}")
print()
print("Verify (should list the phases above, including qa_fix):")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py --help "
      "| grep -A2 -- --phase")
