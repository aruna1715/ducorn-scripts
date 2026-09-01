#!/usr/bin/env python3
"""
Make the jail's refusal end the guessing instead of starting it.

── WHAT THE AGENT SEES TODAY ────────────────────────────────────────────────

    BLOCKED: '/Users/ducorn/DC/input.csv' is outside the jail for '<slug>'.
    Allowed: products/<slug>/** and docs/<slug>-*

    BLOCKED: '/products/<slug>/input.csv' is outside the jail for '<slug>'.
    Allowed: products/<slug>/** and docs/<slug>-*

Look at the second attempt. The model read "Allowed: products/<slug>/**",
prefixed a slash, and tried again — a reasonable reading of a relative path
presented with no base. It is refused for the same reason and told the same
thing, so it tries a third spelling, and a fourth. Eighteen blocked reads in
one research run; another run spent all fifteen of its iterations this way.

Three separate defects in one message:

  1. THE ALLOWED PATHS ARE RELATIVE, with no indication of what they are
     relative to. The one path the model cannot construct from this is the
     one that would work.

  2. IT DOES NOT SAY WHAT EXISTS. The agent is guessing filenames because
     nothing has ever told it which files are there. Almost every guess is
     for a file that does not exist under any spelling.

  3. IT DOES NOT SAY TO STOP. A refusal that only says "not that one" is an
     invitation to try another, and a local model will accept that invitation
     until max_iter cuts it off. Exceeding max_iter is not free: on Anthropic
     it is a hard 400, and on Ollama it is a mangled answer that still cost a
     stage.

The same three apply to JailedFileReadTool's other refusal —

    Error: 'input.csv' does not exist in this product.

— which is the one an agent gets after it finally guesses a legal path. It
also names no alternative and invites another guess.

── THE FIX ──────────────────────────────────────────────────────────────────

Both messages become absolute, specific and final: the two absolute
directories, the files that are actually in them, and an explicit instruction
that a file not on the list does not exist and the agent should continue
without it.

Listing is capped at 20 names and wrapped in its own try/except, because this
runs on the error path and an error path that can itself raise is worse than
the message it was trying to improve.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

JAIL = Path("/Users/ducorn/DC/ducorn/tools/product_jail.py")
TOOLS = Path("/Users/ducorn/DC/ducorn/tools/jailed_tools.py")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
applied = []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


# ═══════════════════════════════════════════════════════════════════════════
j = JAIL.read_text(encoding="utf-8")
if "def visible_files" in j:
    sys.exit("Already patched — visible_files exists.")

j = swap(JAIL, "listing helper", j, '''class PathEscape(Exception):
    pass''', '''class PathEscape(Exception):
    pass


def visible_files(topic: str, limit: int = 20) -> str:
    """
    The files this product can actually see, as one line.

    Exists because every refusal used to be a dead end: the agent was told
    where it may not look and never once told what is there, so it guessed
    filenames until it ran out of iterations. Capped, and defensive — this is
    called from an error path, and an error path that raises is worse than the
    message it was improving.
    """
    try:
        names = []
        product = PRODUCTS_DIR / "products" / topic
        if product.is_dir():
            names += [str(p.relative_to(product))
                      for p in sorted(product.rglob("*")) if p.is_file()]
        names += sorted(p.name for p in (PRODUCTS_DIR / "docs").glob(f"{topic}-*")
                        if p.is_file())
        if not names:
            return "(nothing yet — this product has no files)"
        if len(names) > limit:
            return ", ".join(names[:limit]) + f" … and {len(names) - limit} more"
        return ", ".join(names)
    except Exception:
        return "(could not list)"''')

j = swap(JAIL, "refusal message", j, '''    raise PathEscape(
        f"BLOCKED: '{path}' is outside the jail for '{topic}'. "
        f"Allowed: products/{topic}/** and docs/{topic}-*"
    )''', '''    # Absolute, specific, and final. The old message gave relative allowed
    # paths with no base, listed nothing that exists, and did not say to stop
    # — so the model re-spelled the same path over and over. One research run
    # was refused eighteen times before max_iter ended it.
    raise PathEscape(
        f"BLOCKED: '{path}' is outside the jail for '{topic}'.\\n"
        f"You may read and write ONLY inside these two locations:\\n"
        f"  {PRODUCTS_DIR / 'products' / topic}/\\n"
        f"  {PRODUCTS_DIR / 'docs'}/{topic}-*\\n"
        f"Files that exist right now: {visible_files(topic)}\\n"
        f"Do NOT guess another path. If what you need is not in that list, it "
        f"does not exist — continue without it instead of trying again."
    )''')

# ═══════════════════════════════════════════════════════════════════════════
t = TOOLS.read_text(encoding="utf-8")
if "visible_files" in t:
    sys.exit("Already patched — jailed_tools imports visible_files.")

t = swap(TOOLS, "import", t,
         "from tools.product_jail import resolve_in_jail, PathEscape",
         "from tools.product_jail import resolve_in_jail, PathEscape, visible_files")

t = swap(TOOLS, "missing file message", t,
         '''        if not p.is_file():
            return f"Error: '{file_path}' does not exist in this product."''',
         '''        if not p.is_file():
            # The refusal an agent gets once it finally guesses a LEGAL path.
            # Naming what is there ends the guessing; not naming it is how a
            # run spends fifteen iterations on a file that never existed.
            return (f"'{file_path}' does not exist in this product.\\n"
                    f"Files that do exist: {visible_files(self.topic)}\\n"
                    f"Do NOT guess another filename. If what you need is not "
                    f"listed, continue without it.")''')

# ═══════════════════════════════════════════════════════════════════════════
for path, text in ((JAIL, j), (TOOLS, t)):
    backup = path.with_name(f"{path.stem}.backup-jailmsg-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")
    try:
        ast.parse(text)
    except SyntaxError as e:
        shutil.copy2(backup, path)
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backups: *.backup-jailmsg-{stamp}.py")
print()
print("See the refusal an agent now gets:")
print("  cd ~/DC/ducorn && .venv/bin/python -c 'from tools.product_jail import "
      "resolve_in_jail, PathEscape\\ntry:\\n resolve_in_jail(\"ducorn-spend-view\", "
      "\"/Users/ducorn/DC/input.csv\")\\nexcept PathEscape as e:\\n print(e)'")
