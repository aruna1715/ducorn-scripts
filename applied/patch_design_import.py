#!/usr/bin/env python3
"""
Make generate_design.py importable, not just runnable.

    ATLAS DESIGN FAILED — ducorn-spend-view
    No module named 'design_spec'

generate_design.py line 21:

    from design_spec import (...)

A bare import of a sibling module. That resolves when the file is RUN from
inside ducorn/tools/ — which is how it was built and how every test exercises
it. node_design imports it as `tools.generate_design`, and at that point
`design_spec` is not on sys.path; `tools.design_spec` is.

So the module worked perfectly in every test and failed the first time
anything imported it. Being runnable and being importable are different
properties, and only one of them was ever checked.

THE FIX
-------
The module takes responsibility for its own imports rather than requiring
every caller to know how to set sys.path. Both forms are tried, so it keeps
working standalone (`python tools/generate_design.py`), under its tests, and
as `tools.generate_design` from the flow.

Belt and braces, deliberately: this is the one place where getting it wrong
costs a founder an approved gate and a re-run.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

GEN = Path("/Users/ducorn/DC/ducorn/tools/generate_design.py")
s = GEN.read_text(encoding="utf-8")

if "except ImportError" in s and "tools.design_spec" in s:
    sys.exit("Already patched.")

OLD = "from design_spec import ("
if s.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {s.count(OLD)} `{OLD}`, expected 1. "
             f"NOTHING WRITTEN.")

# Find the closing paren of that import so the whole statement can be wrapped.
lines = s.splitlines(keepends=True)
start = next(i for i, l in enumerate(lines) if l.startswith(OLD))
depth = 0
end = None
for i in range(start, len(lines)):
    depth += lines[i].count("(") - lines[i].count(")")
    if depth == 0 and i >= start:
        end = i
        break
if end is None:
    sys.exit("ANCHOR MISS: could not find the end of the import. NOTHING WRITTEN.")

names = "".join(lines[start:end + 1])
indented = "".join("    " + l if l.strip() else l for l in names.splitlines(keepends=True))
qualified = indented.replace("from design_spec import", "from tools.design_spec import", 1)

wrapped = (
    "# Importable as well as runnable. A bare `from design_spec import ...`\n"
    "# resolves only when this file is RUN from ducorn/tools/ — which is how\n"
    "# every test exercises it. Imported as `tools.generate_design` by the\n"
    "# flow, it raised: No module named 'design_spec', after a founder had\n"
    "# already approved gate 1.\n"
    "try:\n"
    + indented +
    "except ImportError:                      # imported as tools.generate_design\n"
    + qualified
)

lines[start:end + 1] = [wrapped]
s = "".join(lines)

backup = GEN.with_name(f"generate_design.backup-import-"
                       f"{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(GEN, backup)
GEN.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, GEN)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: generate_design imports design_spec both ways")
print(f"backup:  {backup}")
print()
print("Prove BOTH import styles before resuming — the point is that one of")
print("them was never tested:")
print("  cd ~/DC/ducorn/tools && ../.venv/bin/python -c "
      "'import generate_design; print(\"standalone OK\")'")
print("  cd ~/DC/ducorn       && .venv/bin/python -c "
      "'from tools.generate_design import generate_designs; print(\"package OK\")'")
