#!/usr/bin/env python3
"""
Import re at module level in skill_runner, and check nothing else has the bug.

── WHAT I BROKE ─────────────────────────────────────────────────────────────

    File "/Users/ducorn/DC/ducorn/skill_runner.py", line 505, in <module>
    UI_DRIVER_RE = re.compile(r"playwright|page\\.goto|sync_playwright|selenium",
    NameError: name 're' is not defined

skill_runner imports re twice — at line 95 and line 520 — and both are INSIDE
functions. My constant sits at module level, so it runs at import time when
nothing has bound the name. The module cannot load at all, which is why skill
01 died before it did anything.

I checked this exact condition for langgraph_flow.py when I put helpers at its
module scope a few hours ago, wrote a guard for it in that patch, and then did
not repeat the check one file over. Same class, same day.

── THE FIX, AND THE CHECK ───────────────────────────────────────────────────

`import re` joins the module imports. One line.

The rest of this file is the part worth having: an audit that finds every
module-level statement referencing a name that is only imported inside a
function. That is a NameError at import time, it cannot be caught by
ast.parse, and it takes the whole module down — the loudest possible failure
with the quietest possible cause.

It runs over the pipeline's own modules, not just this one, because the next
time I add a module-level constant it will be somewhere else.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DUCORN = Path("/Users/ducorn/DC/ducorn")
SKILL = DUCORN / "skill_runner.py"

AUDIT = [
    SKILL,
    DUCORN / "flows/langgraph_flow.py",
    DUCORN / "tools/generate_design.py",
    DUCORN / "tools/screenshot.py",
    DUCORN / "tools/product_jail.py",
    DUCORN / "tools/DuCornWriterTool.py",
]


def module_and_local_imports(tree):
    """(names imported at module level, names imported only inside functions)"""
    module_names, local_names = set(), set()

    def names_of(node):
        out = set()
        for a in node.names:
            out.add((a.asname or a.name).split(".")[0])
        return out

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_names |= names_of(node)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    local_names |= names_of(sub)

    return module_names, local_names - module_names


def module_level_uses(tree, names):
    """Module-level statements that reference one of `names`, with line numbers."""
    hits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Import, ast.ImportFrom)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in names:
                hits.append((getattr(node, "lineno", "?"), sub.id))
                break
    return hits


def audit(paths):
    problems = []
    for path in paths:
        if not path.is_file():
            print(f"  skip  {path.name} — not found")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _module, local_only = module_and_local_imports(tree)
        hits = module_level_uses(tree, local_only)
        if hits:
            for line, name in hits:
                print(f"  FAIL  {path.name}:{line} uses {name!r} at module "
                      f"level, but {name!r} is only imported inside a function")
                problems.append((path.name, line, name))
        else:
            print(f"  ok    {path.name}")
    return problems


print("\n── before ─────────────────────────────────────────────────────────")
before = audit(AUDIT)

s = SKILL.read_text(encoding="utf-8")
if "\nimport re\n" in s.split("def ", 1)[0]:
    print("\nskill_runner already imports re at module level.")
else:
    anchor = "import subprocess\n"
    if s.count(anchor) < 1:
        sys.exit("ANCHOR MISS: no module-level 'import subprocess' in "
                 "skill_runner.py. NOTHING WRITTEN.")
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    backup = SKILL.with_name(f"skill_runner.backup-importre-{stamp}.py")
    shutil.copy2(SKILL, backup)
    # re is used at module level (UI_DRIVER_RE) and inside several functions
    # that import it again harmlessly.
    SKILL.write_text(s.replace(anchor, "import subprocess\nimport re\n", 1),
                     encoding="utf-8")
    try:
        ast.parse(SKILL.read_text(encoding="utf-8"))
    except SyntaxError as e:
        shutil.copy2(backup, SKILL)
        sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")
    print(f"\napplied: import re at module level in skill_runner.py")
    print(f"backup:  {backup.name}")

print("\n── after ──────────────────────────────────────────────────────────")
after = audit(AUDIT)

print()
if after:
    print(f"{len(after)} module-level name(s) still unbound at import time:")
    for name, line, ident in after:
        print(f"  · {name}:{line} — {ident}")
    sys.exit(1)

if before:
    print(f"fixed {len(before)} import-time NameError(s).")
print("every module-level statement can reach the names it uses.")
print()
print("Nothing to restart. Re-run the build:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase build --engine gstack --coder crewai "
      "--complexity simple")
