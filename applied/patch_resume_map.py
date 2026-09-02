#!/usr/bin/env python3
"""
Teach resume about the design phases, and stop it guessing when it cannot.

── THE BUG ──────────────────────────────────────────────────────────────────

    curl -d '{"phase":"design"}' .../pipeline/resume/ducorn-spend-view
    → Phase: design
    → ⚠️  No predecessor mapped for phase 'design' — resuming from checkpoint
    → ❌ Gate 2: no design_variants rows

RESUME_AFTER maps a phase to the node that must be marked complete so the
graph re-enters at the phase you asked for. It was written before the design
node existed and has no entry for `design` or `gate_2`. With no mapping it
fell through to graph.update_state(config, values) — resume from wherever the
checkpoint happens to be — which was gate_2. node_design never ran.

This is the third hardcoded phase list in this codebase (main.py's resume
whitelist and langgraph_flow's argparse choices are the others), and the one I
missed when fixing the first two.

── TWO CHANGES ──────────────────────────────────────────────────────────────

1. design and gate_2 are mapped.

   `build` becomes conditional, and this is the subtle part: as_node marks a
   node COMPLETE and lets the graph route onward. For a has_ui product,
   as_node="gate_1" routes through route_after_gate_1 → design, so asking to
   resume at `build` would land on design instead. build's real predecessor is
   gate_2 when the product has a UI, gate_1 when it does not.

2. An unmapped phase now FAILS instead of resuming somewhere else.

   Silently resuming at a different phase than the one requested is exactly the
   failure this codebase keeps producing: a control that appears to work,
   reports success, and does something else. Asking for `design` and getting
   `gate_2` cost a founder's approved gate and two confusing runs.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if '"design": "gate_1"' in s:
    sys.exit("Already patched — design is in RESUME_AFTER.")

OLD = '''            RESUME_AFTER = {
                "gate_1": "research",
                "build":  "gate_1",
                "qa":     "build",
                "qa_fix": "qa",
                "gate_3": "qa",
                "launch": "gate_3",
                "gate_4": "launch",
                "deploy": "gate_4",
            }
            resume_after = RESUME_AFTER.get(phase)'''

NEW = '''            # build's predecessor depends on whether this product has a UI.
            # as_node marks a node COMPLETE and lets the graph route onward, so
            # as_node="gate_1" on a has_ui product routes through
            # route_after_gate_1 into design — not build. Getting this wrong
            # sends a resume to a different phase than the one asked for.
            _has_ui = bool(_load_run_settings(topic).get("has_ui"))
            RESUME_AFTER = {
                "gate_1": "research",
                "design": "gate_1",
                "gate_2": "design",
                "build":  "gate_2" if _has_ui else "gate_1",
                "qa":     "build",
                "qa_fix": "qa",
                "gate_3": "qa",
                "launch": "gate_3",
                "gate_4": "launch",
                "deploy": "gate_4",
            }
            resume_after = RESUME_AFTER.get(phase)'''

if s.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS [map]: found {s.count(OLD)}, expected 1. "
             f"NOTHING WRITTEN.")
s = s.replace(OLD, NEW, 1)

OLD2 = '''            else:
                print(f"   ⚠️  No predecessor mapped for phase '{phase}' — resuming from checkpoint position")
                graph.update_state(config, values)           '''

NEW2 = '''            else:
                # Do NOT resume somewhere else. A resume that silently lands on
                # a different phase than the one requested is how asking for
                # `design` ran gate_2 instead, wasting an approved gate and two
                # runs before anyone noticed.
                known = ", ".join(sorted(RESUME_AFTER))
                msg = (f"Cannot resume at '{phase}': no predecessor mapped. "
                       f"Known phases: {known}. Refusing to resume somewhere "
                       f"else instead.")
                print(f"❌ {msg}")
                _post_slack(f"❌ *ATLAS: Resume refused* — `{topic}`\\n{msg}")
                raise SystemExit(2)'''

if s.count(OLD2) != 1:
    # Trailing whitespace on that line has bitten four anchors today; match the
    # meaning and let the spaces be whatever they are.
    lines = s.splitlines(keepends=True)
    hits = [i for i, l in enumerate(lines) if "No predecessor mapped" in l]
    if len(hits) != 1:
        sys.exit(f"ANCHOR MISS [refuse]: {len(hits)} 'No predecessor mapped' "
                 f"lines. NOTHING WRITTEN.")
    i = hits[0]
    if "graph.update_state(config, values)" not in lines[i + 1]:
        sys.exit("ANCHOR MISS [refuse]: expected graph.update_state on the "
                 "line after. NOTHING WRITTEN.")
    lines[i:i + 2] = [NEW2.split("else:\n", 1)[1]]
    s = "".join(lines)
else:
    s = s.replace(OLD2, NEW2, 1)

backup = FLOW.with_name(f"langgraph_flow.backup-resumemap-"
                        f"{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, FLOW)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: RESUME_AFTER knows design/gate_2; unmapped phases refuse")
print(f"backup:  {backup}")
