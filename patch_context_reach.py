#!/usr/bin/env python3
"""
The source reaches the skill that writes, and the brief survives the cut.

    python3 scripts/patch_context_reach.py

── THREE CAUSES, ONE DOCUMENT ───────────────────────────────────────────────

Section 7.2 of the tech-stack document says "not recorded" for nine agents.
Every one of those values was in ducorn-stack-context.md for the whole run.

  1. The context was attached in node_research and nowhere else.
     langgraph_flow.py:681 gave it to SAGE. REX, who wrote the documents,
     got nothing. The run log says "📚 stack context attached" exactly once,
     2,006 lines before "SKILL RUNNER: Skill 04 — Build".

  2. The PRD was cut to 3,000 characters of 20,847 — 14%. "## Founder Brief"
     begins at 16,732, so REX was never shown the constraints it was being
     held to. The agent names at 6,252 were cut too; they survived only
     because skill 01's own output file is read in full.

  3. (patch_stack_facts_wide.py) The collector never read
     _shared/requirements-ui.txt, so Playwright is absent from the source.

REX was right to write "not recorded" — that is the rule that makes the
document trustworthy, and it worked. What failed was delivery.

── WHAT CHANGES ─────────────────────────────────────────────────────────────

scripts/stack_context.py is now the one definition. skill_runner attaches the
context beside the prompt every skill builds, so it no longer matters which
node launched the skill or whether it was launched from the CLI at all.

The PRD is sent as: the head, plus the founder brief IN FULL, always. Cutting
at a fixed offset kept the product definition and dropped the constraints,
which is exactly the wrong half to keep.

langgraph_flow's four local copies become thin delegates. Not deleted —
delegating keeps the call sites working and leaves one definition.

── WHAT IT COSTS ────────────────────────────────────────────────────────────

For the tech-stack document: the prompt grows by roughly 6,800 characters of
context and 4,100 of brief, about 2,700 tokens per skill. On the document
pathway that is three skills, so call it 8,000 extra input tokens for the run
— pennies. It is attached only to products whose brief names the stack; every
other product is unchanged.
"""
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
SKILL = DC / "ducorn" / "skill_runner.py"
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
MODULE = DC / "scripts" / "stack_context.py"

if not MODULE.is_file():
    sys.exit(f"NOTHING WRITTEN — copy stack_context.py to {MODULE} first.")

sys.path.insert(0, str(DC / "scripts"))
try:
    import stack_context as _sc
except Exception as e:
    sys.exit(f"NOTHING WRITTEN — stack_context.py will not import: {e}")
for name in ("context_for", "prd_for_prompt", "founder_brief", "is_subject"):
    if not hasattr(_sc, name):
        sys.exit(f"NOTHING WRITTEN — stack_context has no {name}().")

sk = SKILL.read_text(encoding="utf-8")
fl = FLOW.read_text(encoding="utf-8")

if "stack_context" in sk and "stack_context as _sc" in fl:
    print("Already patched — the source reaches the skill that writes.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ skill_runner: the PRD keeps its brief, and the context arrives ══════════

sk = swap("import the module", sk,
          "import product_pathways as pathways",
          "import product_pathways as pathways\nimport stack_context")

sk = swap("brief survives, context attached", sk,
          '''    # PRD
    prd_path = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"
    if prd_path.exists():
        context_parts.append(f"PRD:\\n{prd_path.read_text()[:3000]}")''',
          '''    # PRD — head plus the founder brief IN FULL.
    #
    # This read [:3000] of a 20,847-character PRD. "## Founder Brief" begins
    # at 16,732, so every skill after research was held to constraints it had
    # never been shown. The head carries what the product is; the brief
    # carries what it must satisfy. A fixed cut kept the first and dropped the
    # second.
    prd_path = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"
    _prd_text = ""
    if prd_path.exists():
        _prd_text = prd_path.read_text(errors="replace")
        _sized = stack_context.prd_for_prompt(_prd_text)
        if len(_sized) > 3000:
            print(f"📋 PRD: {len(_sized):,} of {len(_prd_text):,} chars "
                  f"(founder brief included in full)", flush=True)
        context_parts.append(f"PRD:\\n{_sized}")

    # The stack context, for a product that is ABOUT the stack.
    #
    # This used to be attached in node_research and nowhere else, so the
    # researcher had the facts and the WRITER did not — which is why the
    # agent-to-model table came back as "not recorded" nine times with every
    # value sitting in the context file. Attached here, beside the prompt
    # every skill builds, it no longer depends on which node launched this or
    # whether it was launched from the CLI at all.
    _brief = stack_context.founder_brief(_prd_text) or _prd_text
    _ctx, _subject = stack_context.context_for(_brief)
    if _ctx:
        # main() has no `quiet` in scope — it is a parameter of _skill_text,
        # not of this function. Checked before writing rather than after
        # pyflakes reverted the patch.
        print(f"📚 stack context attached ({len(_ctx):,} chars) — "
              + ("the stack is this product's SUBJECT"
                 if _subject else "background"), flush=True)
        context_parts.insert(0, _ctx)''')

# ═══ langgraph_flow: four local copies become delegates ══════════════════════

fl = swap("flow delegates the context", fl,
          '''def _stack_context(max_chars: int = 2000) -> str:
    """ducorn-stack-context.md with the credential inventory removed."""
    path = PRODUCTS_DIR / "docs" / "ducorn-stack-context.md"
    if not path.exists():
        return ""
    kept, skipping = [], False
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("## "):
            skipping = any(w in line.lower() for w in _CONTEXT_SKIP)
        if not skipping:
            kept.append(line)
    return "\\n".join(kept).strip()[:max_chars]''',
          '''import stack_context as _sc


def _stack_context(max_chars: int = 2000) -> str:
    """ducorn-stack-context.md with the credential inventory removed.

    Delegates. This logic also existed in skill_runner's half of the pipeline
    — or rather it did NOT, which is how the writer came to have no source
    while the researcher had all of it. One definition, in scripts/.
    """
    return _sc.stack_context(max_chars)''')

fl = swap("flow delegates the subject test", fl,
          '''    if re.search(_STACK_IS_SUBJECT, brief, re.I):
        return _stack_context(SUBJECT_CONTEXT_CHARS)
    return _stack_context(max_chars)''',
          '''    if _sc.is_subject(brief):
        # All of it. Not a cap — SUBJECT_CONTEXT_CHARS was 20,000 and never
        # bit; the 6,051 in the log is the file with its two Credentials
        # sections stripped, which is correct.
        return _sc.stack_context()
    return _sc.stack_context(max_chars)''')

fl = swap("flow delegates stack_is_subject", fl,
          '''def stack_is_subject(brief: str) -> bool:
    """Is this product ABOUT the stack, rather than merely part of it?"""
    return bool(brief and re.search(_STACK_IS_SUBJECT, brief, re.I))''',
          '''def stack_is_subject(brief: str) -> bool:
    """Is this product ABOUT the stack, rather than merely part of it?"""
    return _sc.is_subject(brief)''')

# ═══ write both, or neither ══════════════════════════════════════════════════
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(SKILL, sk), (FLOW, fl)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-ctxreach-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — both files reverted")


for path, text in targets:
    path.write_text(text, encoding="utf-8")
for path, _ in targets:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                       capture_output=True, text=True)
    u = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
    if u:
        die(f"{path.name}: " + "; ".join(u))
print("syntax and undefined-name checks: clean on both")

# ── what the tech-stack document would now receive ───────────────────────────
slug = "ducorn-technology-stack-documentation"
prd = _sc.PRODUCTS_DIR / "docs" / f"{slug}-PRD.md"
if prd.is_file():
    t = prd.read_text(errors="replace")
    brief = _sc.founder_brief(t)
    sized = _sc.prd_for_prompt(t)
    ctx, subj = _sc.context_for(brief or t)
    print(f"\nwhat skill 04 would now be given for {slug}:\n")
    print(f"  {'PRD on disk':22} {len(t):>7,} chars")
    print(f"  {'was sent':22} {3000:>7,} chars   founder brief "
          f"{'included' if t.find('## Founder Brief') < 3000 else 'CUT'}")
    print(f"  {'now sent':22} {len(sized):>7,} chars   founder brief "
          f"{'included' if '## Founder Brief' in sized else 'CUT'}")
    print(f"  {'stack context':22} {len(ctx):>7,} chars   "
          f"{'SUBJECT — full file plus the rules' if subj else 'background'}")
    if "## Founder Brief" not in sized:
        die("the founder brief is still being cut")
    if not subj:
        die("the tech-stack document is not being treated as a stack subject")

# ── the properties, checked against the written files ────────────────────────
sk_src = SKILL.read_text(encoding="utf-8")
fl_src = FLOW.read_text(encoding="utf-8")
print()
for src, must, why in [
    (sk_src, "stack_context.prd_for_prompt",
     "the founder brief reaches every skill"),
    (sk_src, "stack_context.context_for",
     "the writer gets the same source the researcher got"),
    (fl_src, "import stack_context as _sc",
     "the flow reads the one definition"),
    (fl_src, "return _sc.is_subject(brief)",
     "one subject test, not two"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

if "prd_path.read_text()[:3000]" in sk_src:
    die("the 3,000-character PRD cut is still there")
print("  ok   the fixed 3,000-character cut is gone")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print("""
Next: widen what the collector gathers, then regenerate the context —
Playwright is absent from the source entirely, so the document could not
have mentioned it.

  python3 scripts/patch_stack_facts_wide.py
  python3 scripts/stack_facts.py
  python3 scripts/stack_context.py ducorn-technology-stack-documentation
""")
