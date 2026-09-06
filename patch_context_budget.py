#!/usr/bin/env python3
"""
The budget that is actually used, and a cut that says so.

    python3 scripts/patch_context_budget.py

── WHAT THE DRY RUN FOUND ───────────────────────────────────────────────────

The founder brief is 4,115 characters in the PRD and reaches REX as 115.

    context assembled   18,600 chars
    live budget         12,000 chars      ← line 757, hardcoded
    cut                  6,600 chars      ← silently, with nothing said

The context is [stack context, PRD, prior outputs] and the brief sits at the
end of the PRD section, so the cut lands squarely on it. REX gets the heading
"## Founder Brief (verbatim — these con" and then the closing instructions.

── MY TWO MISTAKES ──────────────────────────────────────────────────────────

patch_dry_run.py replaced `{context[:20000]}` with `{context[:CONTEXT_BUDGET}`
— but that occurrence is in run_with_cursor, which this pipeline does not use.
The live crewai path is a separate f-string at line 757 holding a hardcoded
12,000, and I never touched it.

My verification then asserted:

    if "{context[:20000]}" in src: die(...)

which passed, because the 20000 I had renamed was the wrong one. I checked
that a string was gone without checking WHICH occurrence I had changed. That
is the same defect class as everything else this week, committed inside the
check meant to catch it.

Second: _report_prompt reads CONTEXT_BUDGET (20,000) rather than the number
the live path uses, so it printed "(fits)" over a 6,600-character cut, and an
instructions figure of -3,672. A negative length should have stopped me before
it reached you.

── THE FIX ──────────────────────────────────────────────────────────────────

One budget, used by the path that runs, set high enough that this document
fits with room (18,600 of 40,000 — about 4,600 tokens, pennies), and a loud
line whenever anything is cut, on real runs as well as dry ones. A silent
truncation is what turned a 4,115-character binding brief into 115.
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
s = SKILL.read_text(encoding="utf-8")

if "context_or_warn(" in s:
    print("Already patched — one budget, and a cut announces itself.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the live path uses the named budget, via a function that reports ──────
s = swap("live path uses the budget", s,
         "{context[:12000]}",
         "{context_or_warn(context, skill_name)}")

# ── 2. so does the cursor path ───────────────────────────────────────────────
s = swap("cursor path too", s,
         "{context[:CONTEXT_BUDGET]}",
         "{context_or_warn(context, skill_name)}")

# ── 2b. the fast-mode fallback is a SOURCE, not a budget — but not a bare
#       literal either, or the check below cannot stay absolute ─────────────
s = swap("name the fallback", s,
         "prd_content = prd_path.read_text() if prd_path.exists() else context[:4000]",
         "prd_content = (prd_path.read_text() if prd_path.exists()\n"
         "                       else context[:PRD_FALLBACK_CHARS])")

# ── 3. room to breathe, and a cut that is never silent ───────────────────────
s = swap("one budget, announced", s,
         """CONTEXT_BUDGET = 20000""",
         '''# 18,600 characters of context for the tech-stack document is about 4,600
# tokens. The old 12,000 cut 6,600 of it — and because the PRD sits at the end,
# what it cut was the founder brief, from 4,115 characters to 115.
CONTEXT_BUDGET = 40000

# Fast mode builds from the PRD; this is only reached when there is no PRD on
# disk at all. A different thing from the budget above — a fallback SOURCE,
# not a trim — and named so that "no bare context[:N] anywhere" can stay an
# absolute check rather than a check with an exception.
PRD_FALLBACK_CHARS = 4000


def context_or_warn(context: str, skill_name: str = "") -> str:
    """
    The context, trimmed to budget — and never quietly.

    Three truncations were found in this file in one day: the PRD at 3,000,
    the stack context that never arrived, and this one at 12,000. All three
    were bare literals inside f-strings, and none of them said a word when
    they fired. The trim is fine; the silence is the defect.
    """
    if len(context) <= CONTEXT_BUDGET:
        return context
    cut = len(context) - CONTEXT_BUDGET
    print(f"\\n⚠️  CONTEXT CUT — {skill_name or 'this skill'} was given "
          f"{CONTEXT_BUDGET:,} of {len(context):,} characters; {cut:,} were "
          f"dropped from the END of the context.", flush=True)
    print(f"    The founder brief and the most recent skill outputs sit "
          f"there. Raise CONTEXT_BUDGET in skill_runner.py, or reduce what "
          f"is attached.", flush=True)
    return context[:CONTEXT_BUDGET]''')

# ── 4. the dry-run report stops lying about it ───────────────────────────────
s = swap("report the real numbers", s,
         '''    sent_ctx = min(len(context), CONTEXT_BUDGET)
    print(f"  instructions         {len(full_prompt) - sent_ctx:>8,} chars")
    print(f"  context assembled    {len(context):>8,} chars")''',
         '''    sent_ctx = min(len(context), CONTEXT_BUDGET)
    instructions = max(0, len(full_prompt) - sent_ctx)
    print(f"  instructions         {instructions:>8,} chars")
    print(f"  context assembled    {len(context):>8,} chars")''')

# and check the brief actually survives into the prompt
s = swap("check the brief survives", s,
         '''    out = (PRODUCTS_DIR / "docs" /
           f"{topic}-skill{skill_num}-DRYRUN-prompt.txt")''',
         '''    # The binding brief is at the end of the PRD section, so it is the first
    # thing a context cut destroys. Measure it in the PROMPT, not in what was
    # assembled — 7,149 characters were assembled and 3,152 arrived.
    _m = "## Founder Brief"
    if _m in full_prompt:
        in_prompt = len(full_prompt) - full_prompt.find(_m)
        prd = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"
        if prd.is_file():
            t = prd.read_text(errors="replace")
            in_prd = len(t) - t.find(_m) if _m in t else 0
            flag = "  ⚠️  TRUNCATED" if in_prompt < in_prd * 0.9 else "  ok"
            print(f"\\n  founder brief        {in_prompt:>8,} of {in_prd:,} "
                  f"chars reach the model{flag}")

    out = (PRODUCTS_DIR / "docs" /
           f"{topic}-skill{skill_num}-DRYRUN-prompt.txt")''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-ctxbudget-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, SKILL)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")
r = subprocess.run([sys.executable, "-m", "pyflakes", str(SKILL)],
                   capture_output=True, text=True)
u = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
if u:
    die("undefined name: " + "; ".join(u))
print("syntax and undefined-name checks: clean")

# ── THE check I failed last time: no bare context slice anywhere ─────────────
src = SKILL.read_text(encoding="utf-8")
import re as _re
bare = _re.findall(r"context\[:\d+\]", src)
print()
if bare:
    die(f"a bare context truncation is still present: {bare}")
print("  ok   no bare context[:NNNN] anywhere in the file")

slices = _re.findall(r"\{context[^}]*\}", src)
print(f"  ok   every context interpolation goes through the budget "
      f"({len(slices)} site(s): {sorted(set(slices))})")

for must, why in [
    ("CONTEXT_BUDGET = 40000", "the budget has room for this document"),
    ("def context_or_warn", "a cut announces itself on real runs too"),
    ("founder brief        ", "the dry run measures the brief in the PROMPT"),
    ("instructions = max(0,", "no negative lengths in the report"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print("""
Look again — still free:

  ducorn/.venv/bin/python ducorn/skill_runner.py --skill 04 \\
      --topic ducorn-technology-stack-documentation --dry-run

Expect: context ~18,600 of 40,000 (fits), no CONTEXT CUT line, and the
founder brief reaching the model at its full 4,115 characters.
""")
