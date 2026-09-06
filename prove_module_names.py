#!/usr/bin/env python3
"""
Every name imported from a DuCorn module must be a name that module defines.

    cd ~/DC && python3 scripts/prove_module_names.py
    cd ~/DC && python3 scripts/prove_module_names.py --quiet   # failures only
    cd ~/DC && python3 scripts/prove_module_names.py --all     # + .backup-* files

Exit 0 when every cross-module import resolves. Exit 1 when one does not.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

    ImportError: cannot import name 'load_ducorn_env' from 'ducorn_env'
      (/Users/ducorn/DC/scripts/ducorn_env.py)

scripts/ducorn_env.py held load_ducorn_env() and was imported by nine files
across three repos. A new module was written under the same name. The name
was gone; nothing noticed. The pipeline, the Slack bot, the activity API and
doctor.py all failed at import — discovered when a dashboard tab returned
502, hours later.

Every piece was individually fine. The new module was correct. The nine
importers were correct. Nothing compared them. That is the same defect class
this stack keeps producing: two copies of one fact, drifting, with no check
that closes the gap.

── WHAT IT CHECKS ───────────────────────────────────────────────────────────

  1. `from M import a, b` where M is a file in this tree — a and b must be
     defined at module level in M. This is the failure above, caught
     statically, in under a second, for free.

  2. `import M` followed by `M.attr` — same rule. Catches the half of the
     defect that the from-import check misses.

  3. Two files in the tree sharing an importable basename, both on a search
     path something inserts into sys.path. Whichever is found first wins,
     silently, and the loser's callers get whatever the winner happens to
     define. This is how the failure above BECAME possible; (1) and (2) catch
     it once it bites, this catches it before.

Nothing is imported or executed: the tree is parsed. A module that needs
psycopg2, a database, or a running service is checked exactly like any other.

── WHAT IT DOES NOT DO ──────────────────────────────────────────────────────

Names created dynamically (setattr, globals()[...], exec) are invisible to a
parser and would read as missing. Modules that use them are listed as SKIPPED
rather than failed. `from M import *` makes M's surface unknowable at the
call site, so importers using it are skipped for M.

Third-party and standard-library imports are not checked — pip and the
interpreter own those.

foo.backup-<tag>-<timestamp>.py snapshots are skipped. Nothing imports them
and nothing runs them; including them turns a dozen live findings into a
hundred and thirty lines. --all puts them back if you want to audit them.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))

# Directories that end up on sys.path — via PYTHONPATH in the plists, via
# sys.path.insert in the scripts, or by being the working directory.
SEARCH_ROOTS = [
    DC / "scripts",
    DC / "ducorn",
    DC / "ducorn" / "flows",
    DC / "ducorn" / "tools",
]

SCAN_ROOTS = [DC / "scripts", DC / "ducorn", DC / "ducorn-products"]

SKIP_PARTS = {".venv", "__pycache__", "node_modules", ".git", "site-packages",
              ".superseded", "backups", "_backups"}

# Every patch script in this tree writes foo.backup-<tag>-<timestamp>.py beside
# the file it edits. Those are snapshots — nothing imports them and nothing
# runs them. Checking them turned 12 real findings into 132 lines and buried
# the signal, which is the failure mode this whole exercise is about.
# --all includes them.
BACKUP = re.compile(r"\.backup-[^.]*\.py$")

DYNAMIC = ("setattr(", "globals()[", "exec(", "importlib")


def is_backup(p: Path) -> bool:
    return bool(BACKUP.search(p.name))


def is_skipped_path(p: Path) -> bool:
    return any(part in SKIP_PARTS for part in p.parts)


def module_surface(path: Path):
    """(names defined at module level, uses_dynamic, has_star_import)."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return None, False, False

    names: set = set()
    star = False

    def collect(body):
        nonlocal star
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            names.add(n.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    names.add(node.target.id)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "*":
                        star = True
                    else:
                        names.add(a.asname or a.name)
            # module-level conditionals still define module-level names
            elif isinstance(node, ast.If):
                collect(node.body)
                collect(node.orelse)
            elif isinstance(node, ast.Try):
                collect(node.body)
                collect(node.orelse)
                collect(node.finalbody)
                for h in node.handlers:
                    collect(h.body)
            elif isinstance(node, (ast.With, ast.AsyncWith, ast.For,
                                   ast.AsyncFor, ast.While)):
                collect(node.body)
                collect(getattr(node, "orelse", []))

    collect(tree.body)

    # a name bound with `global` inside a function is still module-level
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)

    return names, any(d in src for d in DYNAMIC), star


# ── the local module map ─────────────────────────────────────────────────────
local: dict = {}                      # module name -> [paths]
by_name = defaultdict(list)

ap = argparse.ArgumentParser()
ap.add_argument("--quiet", action="store_true",
                help="failures only")
ap.add_argument("--all", action="store_true",
                help="include *.backup-*.py snapshots (normally skipped)")
args = ap.parse_args()

def excluded(p: Path) -> bool:
    return is_skipped_path(p) or (not args.all and is_backup(p))

for root in SEARCH_ROOTS:
    if not root.is_dir():
        continue
    for f in sorted(root.glob("*.py")):
        if excluded(f) or f.name == "__init__.py":
            continue
        by_name[f.stem].append(f)

for name, paths in by_name.items():
    local[name] = paths

stdlib = getattr(sys, "stdlib_module_names", frozenset())

surfaces: dict = {}


def surface_of(path: Path):
    if path not in surfaces:
        surfaces[path] = module_surface(path)
    return surfaces[path]


failures = []
skipped = []
checked = 0
files_scanned = 0
backups_skipped = 0

for root in SCAN_ROOTS:
    if not root.is_dir():
        continue
    for f in sorted(root.rglob("*.py")):
        if is_skipped_path(f):
            continue
        if not args.all and is_backup(f):
            backups_skipped += 1
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        files_scanned += 1

        aliases = {}          # local alias -> module path

        for node in ast.walk(tree):
            # ── from M import a, b ──────────────────────────────────────────
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                base = node.module.split(".")[-1]
                if base in stdlib or base not in local:
                    continue
                paths = local[base]
                if len(paths) != 1:
                    continue          # ambiguous; reported as shadowing below
                target = paths[0]
                if target == f:
                    continue
                names, dynamic, star = surface_of(target)
                if names is None:
                    continue
                if dynamic:
                    skipped.append((f, target, "target builds names at runtime"))
                    continue
                for a in node.names:
                    if a.name == "*":
                        continue
                    checked += 1
                    if a.name not in names:
                        failures.append((f, node.lineno, base, a.name, target))

            # ── import M [as N] ─────────────────────────────────────────────
            elif isinstance(node, ast.Import):
                for a in node.names:
                    base = a.name.split(".")[-1]
                    if base in stdlib or base not in local:
                        continue
                    paths = local[base]
                    if len(paths) == 1 and paths[0] != f:
                        aliases[a.asname or base] = paths[0]

        # ── M.attr ──────────────────────────────────────────────────────────
        if aliases:
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in aliases):
                    target = aliases[node.value.id]
                    names, dynamic, star = surface_of(target)
                    if names is None or dynamic or star:
                        continue
                    # attributes assigned onto the module by the caller
                    if isinstance(getattr(node, "ctx", None), ast.Store):
                        continue
                    checked += 1
                    if node.attr not in names:
                        failures.append((f, node.lineno, node.value.id,
                                         node.attr, target))

# ── shadowing ────────────────────────────────────────────────────────────────
shadowed = {n: p for n, p in local.items() if len(p) > 1}

# ── report ───────────────────────────────────────────────────────────────────
def rel(p: Path) -> str:
    try:
        return str(p.relative_to(DC))
    except ValueError:
        return str(p)


if not args.quiet:
    print(f"{files_scanned} files parsed · {len(local)} local modules · "
          f"{checked} imported names resolved"
          + (f" · {backups_skipped} .backup-* snapshots skipped (--all to include)"
             if backups_skipped else "") + "\n")

if shadowed:
    print(f"⚠️  {len(shadowed)} module name(s) exist in more than one place on "
          f"a search path.\n    Whichever is found first wins, silently:\n")
    for name, paths in sorted(shadowed.items()):
        print(f"      {name}")
        for p in paths:
            print(f"          {rel(p)}")
    print()

if skipped and not args.quiet:
    print(f"  {len(skipped)} import(s) not checked — the target builds names "
          f"at runtime:")
    seen = set()
    for src, tgt, why in skipped:
        if tgt in seen:
            continue
        seen.add(tgt)
        print(f"      {rel(tgt)}  ({why})")
    print()

if failures:
    print(f"❌ {len(failures)} import(s) name something that does not exist:\n")
    for src, line, mod, name, target in failures:
        print(f"    {rel(src)}:{line}")
        print(f"        imports  {name}  from  {mod}")
        print(f"        {rel(target)} does not define it")
        print()
    print("Every one of these is an ImportError the moment that file runs.")
    raise SystemExit(1)

print("✅ every cross-module import in the tree resolves to a name that exists."
      + ("  (see the shadowing warning above)" if shadowed else ""))
