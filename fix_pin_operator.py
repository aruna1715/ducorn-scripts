#!/usr/bin/env python3
"""
A pin without its operator is not a pin.

    python3 scripts/fix_pin_operator.py

The new dependency table reads:

    crewai-tools      crewai-tools1.15.9
    psycopg2-binary   psycopg2-binary2.9.12
    @cursor/sdk       @cursor/sdklatest

The regex matches the comparison operator and does not capture it:

    r'"([A-Za-z0-9_.\\-]+)[><=~]{1,2}([^"]+)"'
                        ^^^^^^^^^^^^^ matched, discarded

So "crewai-tools>=1.15.9" and "crewai-tools==1.15.9" both render as
"crewai-tools1.15.9". In a document whose whole claim is that every fact comes
from the thing that defines it, a pin that cannot be told from a floor is a
fact quietly rounded off — and the reader has no way to know.

npm entries get a space instead: "@cursor/sdk latest" rather than
"@cursor/sdklatest", because "^2.8.5" already carries its own operator and
jamming the name against it reads as one token.
"""
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
FACTS = DC / "scripts" / "stack_facts.py"
s = FACTS.read_text(encoding="utf-8")

if 'm.group(1) + m.group(2) + m.group(3)' in s:
    print("Already fixed — pins carry their operator.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("capture the operator", s,
         '''        for m in re.finditer(r'"([A-Za-z0-9_.\\-]+)[><=~]{1,2}([^"]+)"',
                             pyproject.read_text(errors="replace")):
            k = m.group(1).lower()
            seen.setdefault(k, {"pin": set(), "where": set()})
            seen[k]["pin"].add(m.group(1) + m.group(2))''',
         '''        # The operator is part of the pin. Capturing the name and the
        # version but not the ">=" between them rendered every dependency as
        # an exact pin, whether or not it was one.
        for m in re.finditer(r'"([A-Za-z0-9_.\\-]+)([><=~]{1,2})([^"]+)"',
                             pyproject.read_text(errors="replace")):
            k = m.group(1).lower()
            seen.setdefault(k, {"pin": set(), "where": set()})
            seen[k]["pin"].add(m.group(1) + m.group(2) + m.group(3))''')

s = swap("npm pins are readable", s,
         '''                seen[name.lower()]["pin"].add(f"{name}{pin}")''',
         '''                # "@cursor/sdk latest", not "@cursor/sdklatest" — an npm
                # range like "^2.8.5" carries its own operator, so jamming the
                # name against it reads as a single token.
                seen[name.lower()]["pin"].add(f"{name} {pin}")''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FACTS.with_name(f"stack_facts.backup-pins-{stamp}.py")
shutil.copy2(FACTS, backup)
FACTS.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, FACTS)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")
r = subprocess.run([sys.executable, "-m", "pyflakes", str(FACTS)],
                   capture_output=True, text=True)
if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
    die("undefined name:\n" + r.stdout + r.stderr)
print("syntax and undefined-name checks: clean")

# ── the pins, from the patched collector, against the real tree ──────────────
src = FACTS.read_text(encoding="utf-8")
tree = ast.parse(src)
ns = {"DC": DC, "Path": Path, "ast": ast, "json": __import__("json"),
      "re": __import__("re"),
      "_SKIP_DIRS": {".venv", "node_modules", "__pycache__", ".git",
                     "site-packages"}}
for fname in ("_walk", "declared"):
    seg = next((ast.get_source_segment(src, n) for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == fname), None)
    if seg is None:
        die(f"{fname} not found — run patch_stack_facts_wide.py first")
    exec(seg, ns)

dec = ns["declared"]()
print("\npins that were missing their operator:\n")
CHECK = ["crewai-tools", "slack-sdk", "psycopg2-binary", "@cursor/sdk"]
bad = []
for name in CHECK:
    d = dec.get(name)
    if not d:
        print(f"  {name:18} (not declared here)")
        continue
    pins = ", ".join(sorted(d["pin"]))
    ok = any(c in pins for c in "><=~ ")
    bad += [] if ok else [name]
    print(f"  {'ok  ' if ok else 'FAIL'} {name:18} {pins[:52]}")
if bad:
    die("still rendering a pin without its operator: " + ", ".join(bad))

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print("""
Now write it — stack_facts.py prints unless you ask it to write:

  python3 scripts/stack_facts.py --write
  grep -ci playwright ducorn-products/docs/ducorn-stack-context.md
""")
