#!/usr/bin/env python3
"""
See exactly what a skill will be told, before spending anything.

    python3 scripts/patch_dry_run.py

    python3 ducorn/skill_runner.py --skill 04 \\
        --topic ducorn-technology-stack-documentation --dry-run

── WHY ──────────────────────────────────────────────────────────────────────

Three runs were started today to find out what REX would be told. Each one
cost real money and each was aborted on the first line of evidence:

    $0.60   REX writing Playwright tests   — a ghost rejection in the checkpoint
    $2.19   REX writing .env.example       — the pathway rules never reached 04
    $0.18   (stopped early)

About $3, and the documents were never touched — both .md files are still
dated 2 September. Every one of those was a property of THE PROMPT, which is
assembled entirely from files on disk. It costs nothing to look at.

I asserted what REX would receive and was wrong three times. This makes it
observable instead.

── HOW ──────────────────────────────────────────────────────────────────────

--dry-run runs the real assembly — the real _skill_text, the real pathway
lookup, the real PRD sizing, the real stack context, the real prior-skill
outputs — and stops at the moment before the model is called.

It composes the prompt inside run_with_crewai, where the live path composes
it. Not a copy in a preview function: a copy would drift, and drift is the
defect this whole exercise has been about.

── AND ONE THING IT IMMEDIATELY REVEALS ─────────────────────────────────────

    full_prompt = f"...CONTEXT:\\n{context[:20000]}"

The context is the stack context plus the PRD plus every prior skill output.
For the tech-stack document that is comfortably over 20,000 characters, so
something is being cut and nothing says what. The preview prints the budget
and what fell off the end.
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

if "--dry-run" in s:
    print("Already patched — you can preview a prompt for free.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the flag ──────────────────────────────────────────────────────────────
s = swap("the flag", s,
         "    parser.add_argument('--context-file', default=None, help='Path to context file')",
         """    parser.add_argument('--context-file', default=None, help='Path to context file')
    parser.add_argument('--dry-run', action='store_true',
                        help='assemble the prompt and print it; call no model')""")

# ── 2. run_with_crewai can stop one line before the model ────────────────────
s = swap("dry_run parameter", s,
         "def run_with_crewai(skill_num: str, topic: str, context: str) -> str:",
         "def run_with_crewai(skill_num: str, topic: str, context: str,\n"
         "                    dry_run: bool = False) -> str:")

s = swap("name the context budget in the f-string", s,
         '''    else:
        skill_prompt = _skill_text(skill_num, skill_name, topic)
        full_prompt = f"""{skill_prompt}

---
TOPIC: {topic}
CONTEXT:
{context[:20000]}''',
         '''    else:
        skill_prompt = _skill_text(skill_num, skill_name, topic)
        full_prompt = f"""{skill_prompt}

---
TOPIC: {topic}
CONTEXT:
{context[:CONTEXT_BUDGET]}''')

# ── 3. one named budget instead of a bare literal ────────────────────────────
s = swap("name the budget", s,
         "def run_with_crewai(skill_num: str, topic: str, context: str,",
         '''# The context handed to a skill: stack context + PRD + every prior skill
# output. It was a bare 20000 inside an f-string, so a context that outgrew it
# was silently cut with nothing said — the third such truncation found today,
# after the PRD's 3,000 and the stack context that never arrived at all.
CONTEXT_BUDGET = 20000


def run_with_crewai(skill_num: str, topic: str, context: str,''')

# ── 4. the dry-run exit, immediately before the Agent is constructed ────────
# Anchored on the Agent construction rather than the prompt tail: that tail
# text appears three times (fast mode, the skill path, and run_with_cursor),
# and a count-based anchor refused to write at all. Correctly.
s = swap("stop before the model", s,
         '''    agent = Agent(
        role=f"DuCorn {agent_name}",''',
         '''    if dry_run:
        _report_prompt(skill_num, skill_name, topic, context, full_prompt)
        return "VERDICT: DRY RUN — no model was called"

    agent = Agent(
        role=f"DuCorn {agent_name}",''')

# ── 5. the report ────────────────────────────────────────────────────────────
s = swap("the report", s,
         "def run_with_crewai(skill_num: str, topic: str, context: str,",
         '''def _report_prompt(skill_num, skill_name, topic, context, full_prompt):
    """What the model would have been sent, and what fell off the end."""
    import re as _re
    cut = max(0, len(context) - CONTEXT_BUDGET)
    print("\\n" + "=" * 74)
    print(f"DRY RUN — {skill_name} for {topic}")
    print("=" * 74)
    sent_ctx = min(len(context), CONTEXT_BUDGET)
    print(f"  instructions         {len(full_prompt) - sent_ctx:>8,} chars")
    print(f"  context assembled    {len(context):>8,} chars")
    print(f"  context budget       {CONTEXT_BUDGET:>8,} chars"
          + (f"   ⚠️  {cut:,} CUT" if cut else "   (fits)"))
    print(f"  prompt sent          {len(full_prompt):>8,} chars"
          f"   ≈ {len(full_prompt)//4:,} tokens")

    print("\\n  what is in the prompt:")
    for label, pattern in [
        ("pathway rules", r"THIS IS A DOCUMENT|NO USER INTERFACE|COMMAND-LINE"),
        ("founder brief", r"## Founder Brief"),
        ("stack context", r"RULES FOR USING THE ABOVE"),
        ("deployment contract", r"DEPLOYMENT CONTRACT|service\\.json"),
        ("UI test contract", r"Playwright|test_ui\\.py"),
        ("a prior rejection", r"REJECTED|VERDICT: FAIL"),
    ]:
        hit = bool(_re.search(pattern, full_prompt, _re.I))
        print(f"    {'yes' if hit else ' no'}  {label}")

    if cut:
        print(f"\\n  ⚠️  the last {cut:,} characters of context were cut. "
              f"Tail of what survived:")
        print("      …" + context[CONTEXT_BUDGET - 200:CONTEXT_BUDGET]
              .replace("\\n", " ")[:180])

    out = (PRODUCTS_DIR / "docs" /
           f"{topic}-skill{skill_num}-DRYRUN-prompt.txt")
    try:
        out.write_text(full_prompt, encoding="utf-8")
        print(f"\\n  full prompt written to {out}")
    except OSError as e:
        print(f"\\n  could not write the prompt: {e}")
    print("=" * 74 + "\\n")


def run_with_crewai(skill_num: str, topic: str, context: str,''')

# ── 6. main() honours it ─────────────────────────────────────────────────────
s = swap("main honours the flag", s,
         "    # Run the skill\n    try:",
         '''    if args.dry_run:
        # The real assembly, stopped one line before the model. Nothing is
        # written to the checkpoint and no verdict is recorded.
        run_with_crewai(skill_num, topic, context, dry_run=True)
        sys.exit(0)

    # Run the skill
    try:''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-dryrun-{stamp}.py")
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

src = SKILL.read_text(encoding="utf-8")
print()
for must, why in [
    ("--dry-run", "the flag exists"),
    ("CONTEXT_BUDGET = 20000", "the budget has a name instead of being a literal"),
    ("if dry_run:", "composition stops one line before the model"),
    ("def _report_prompt", "the report exists"),
    ("run_with_crewai(skill_num, topic, context, dry_run=True)",
     "main honours it and exits without recording anything"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

if "{context[:20000]}" in src:
    die("the bare 20000 literal is still in the f-string")
print("  ok   no bare truncation literal left in the prompt")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print("""
Look before you spend:

  cd ~/DC && ducorn/.venv/bin/python ducorn/skill_runner.py --skill 04 \\
      --topic ducorn-technology-stack-documentation --dry-run

Costs nothing. It prints what REX would be told, flags anything the context
budget would cut, and writes the whole prompt to
docs/<topic>-skill04-DRYRUN-prompt.txt so you can read it.
""")
