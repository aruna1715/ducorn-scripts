#!/usr/bin/env python3
"""
Put the interface guidelines in front of the two skills that review interfaces.

── WHAT REVIEWS A UI TODAY ──────────────────────────────────────────────────

design_spec.py checks WCAG contrast (4.5 body, 3.0 muted) and enforces hue
separation so three variants cannot collapse into one look. That is more than
most pipelines do, and it is the whole of it.

Nothing checks focus order, hit-target size, keyboard operability,
prefers-reduced-motion, form labelling, error placement, or any of the other
things that make an interface usable rather than merely pretty. Skill 03
reviews the design and skill 05 reviews the code, and both do it from their own
judgement with no checklist in front of them.

── THE CHANGE ───────────────────────────────────────────────────────────────

One helper, _skill_text(), reads a skill's markdown and — for 03 and 05 only —
appends the vendored guidelines as explicit review criteria. Both call sites
use it: the Cursor path and the CrewAI path, which had two separate copies of
`skill_file.read_text() if skill_file.exists()`. Two copies of a rule is how
one of them goes stale, and this codebase has produced five such pairs this
week.

The guidelines are INJECTED, not referenced. Telling an agent to "review
against references/web-interface-guidelines.md" would be one more instruction
pointing at something the agent cannot reach — its file tool is jailed to the
product directory, and gstack/references is not in it.

── WHEN THEY ARE MISSING ────────────────────────────────────────────────────

Loudly. The skill still runs, because a review without the checklist is what
we have today and is better than no review, but the log says exactly what is
missing and how to get it:

    ⚠️  skill 03: no interface guidelines vendored — review will not cover
        focus, hit targets or motion. Run scripts/vendor_web_guidelines.py

Run that script first; this patch only wires up what it downloads.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
s = SKILL.read_text(encoding="utf-8")

if "_skill_text" in s:
    sys.exit("Already patched — the review skills get the guidelines.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


# ── the helper ───────────────────────────────────────────────────────────────
s = swap("helper", s, '''def run_with_cursor(''',
         '''# The skills that judge an interface. 03 reviews the design, 05 reviews the
# code that implements it; both were doing it without a checklist.
UI_REVIEW_SKILLS = {"03", "05"}
GUIDELINES = Path("/Users/ducorn/DC/gstack/references/"
                  "web-interface-guidelines.md")

# Past this the checklist starts crowding out the thing being reviewed in a
# 32k local context. Warned about rather than silently trimmed — half a
# checklist that looks like a whole one is the failure this project keeps
# producing.
GUIDELINES_WARN_BYTES = 24000


def _skill_text(skill_num: str, skill_name: str, topic: str) -> str:
    """
    A skill's prompt, plus the interface guidelines for the two skills that
    review interfaces.

    Injected rather than referenced on purpose: the agent's file tool is
    jailed to the product directory, so telling it to go and read
    gstack/references would be an instruction pointing at something it cannot
    reach — this codebase's most reliable way of producing a control that does
    nothing.
    """
    skill_file = SKILLS_DIR / SKILL_FILES[skill_num]
    text = (skill_file.read_text() if skill_file.exists()
            else f"Complete {skill_name} for {topic}.")

    if skill_num not in UI_REVIEW_SKILLS:
        return text

    if not GUIDELINES.is_file():
        print(f"⚠️  skill {skill_num}: no interface guidelines vendored — "
              f"review will not cover focus, hit targets or motion. "
              f"Run scripts/vendor_web_guidelines.py", flush=True)
        return text

    rules = GUIDELINES.read_text(errors="replace")
    if len(rules) > GUIDELINES_WARN_BYTES:
        print(f"⚠️  interface guidelines are {len(rules):,} bytes — large "
              f"enough to crowd the review in a local model's context",
              flush=True)
    print(f"📐 skill {skill_num}: reviewing against the interface guidelines "
          f"({len(rules):,} bytes)", flush=True)

    return text + f"""

{'=' * 70}
INTERFACE GUIDELINES — REVIEW AGAINST THESE, NOT ONLY YOUR OWN JUDGEMENT
{'=' * 70}
These are binding review criteria for anything that ships a user interface.
Cite the specific rule when you raise a problem, so the fix is unambiguous.
They do not replace the rest of this skill; they are the part of it that was
previously left to memory.

If this product ships no interface, say so in one line and skip this section
rather than inventing findings.

{rules}
{'=' * 70}
END OF INTERFACE GUIDELINES
{'=' * 70}
"""


def run_with_cursor(''')

# ── both call sites use it ───────────────────────────────────────────────────
s = swap("cursor path", s, '''        skill_file = SKILLS_DIR / SKILL_FILES[skill_num]
        skill_prompt = skill_file.read_text() if skill_file.exists() else ""
        full_prompt = f"""{skill_prompt}''',
         '''        skill_prompt = _skill_text(skill_num, skill_name, topic)
        full_prompt = f"""{skill_prompt}''')

s = swap("crewai path", s, '''    skill_file = SKILLS_DIR / SKILL_FILES[skill_num]
    skill_prompt = skill_file.read_text() if skill_file.exists() else f"Complete {skill_name} for {topic}."

    full_prompt = f"""{skill_prompt}''',
         '''    skill_prompt = _skill_text(skill_num, skill_name, topic)

    full_prompt = f"""{skill_prompt}''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-guidelines-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, SKILL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# Nothing should still be reading a skill file the old way — that is how one
# of two copies goes stale.
leftover = s.count("SKILLS_DIR / SKILL_FILES[skill_num]")
if leftover != 1:
    shutil.copy2(backup, SKILL)
    sys.exit(f"{leftover} places still read the skill file directly; expected "
             f"1 (inside _skill_text). Reverted from {backup}")

# Exercise the helper rather than trusting the edit: skills that are not 03/05
# must come back unchanged, and 03/05 must carry the rules when the file is
# there and warn when it is not.
seg = next(ast.get_source_segment(s, n) for n in ast.parse(s).body
           if isinstance(n, ast.FunctionDef) and n.name == "_skill_text")
import tempfile
tmp = Path(tempfile.mkdtemp())
(tmp / "01.md").write_text("SKILL ONE BODY", encoding="utf-8")
(tmp / "03.md").write_text("SKILL THREE BODY", encoding="utf-8")
rules_file = tmp / "guidelines.md"

ns = {"SKILLS_DIR": tmp, "SKILL_FILES": {"01": "01.md", "03": "03.md"},
      "GUIDELINES": rules_file, "UI_REVIEW_SKILLS": {"03", "05"},
      "GUIDELINES_WARN_BYTES": 24000, "Path": Path}
exec(seg, ns)
fn = ns["_skill_text"]

print("\nchecking the injection:")
out = fn("01", "PRD Analysis", "x")
assert "SKILL ONE BODY" in out and "INTERFACE GUIDELINES" not in out, out[:200]
print("  ok   skill 01 is untouched")

out = fn("03", "Design Review", "x")
assert "SKILL THREE BODY" in out and "INTERFACE GUIDELINES" not in out
print("  ok   skill 03 warns and continues when nothing is vendored")

rules_file.write_text("## Interactions\n- visible focus rings\n", encoding="utf-8")
out = fn("03", "Design Review", "x")
assert "SKILL THREE BODY" in out, "the skill's own prompt was lost"
assert "visible focus rings" in out, "the rules did not reach the prompt"
assert "REVIEW AGAINST THESE" in out
print("  ok   skill 03 carries the rules when they are vendored")

print(f"\napplied: skills 03 and 05 review against the vendored guidelines")
print(f"backup:  {backup.name}")
print()
print("Vendor them first if you have not:")
print("  python3 scripts/vendor_web_guidelines.py")
