#!/usr/bin/env python3
"""
A rejection from a skill that no longer runs is a ghost, not feedback.

    python3 scripts/patch_stale_rejection.py

── WHAT HAPPENED ────────────────────────────────────────────────────────────

The tech-stack document was re-run on the document pathway — skills 01, 04, 07.
Skill 05 was correctly excluded. Two minutes into the build, REX created
tests/test_ui.py: a Playwright suite, for a document.

Because the checkpoint still holds this:

    05-05-code-review   fail   VERDICT: FAIL — no test suite (0 tests
                               collected; pipeline requires Playwright UI
                               tests for HTML products)

and prior_failure_context() walks every skill numbered ABOVE the current one
that failed, regardless of whether that skill is part of this run:

    for num in sorted(SKILL_FILES):
        if num <= skill_num:
            continue
        entry = results.get(...)
        if not entry or entry.get("status") != "fail":
            continue
        ... this report goes into REX's prompt as binding feedback

So the exact false demand the pathway work existed to remove was fed straight
back into the build by the one function nobody re-read. I gated which skills
RUN and never asked what the checkpoint still REMEMBERS.

It is the same defect as everything else in the census: a control that was
correct in isolation and reached the wrong thing. The pathway decides which
skills run; it did not decide whose opinion counts.

── THE FIX ──────────────────────────────────────────────────────────────────

A rejection counts only if the skill that wrote it is part of this pathway.
Everything else about the function is unchanged — skill 06's report still
reaches REX on a software build, which is the reason it was written.

Deliberately a superset: pw.skills plus pw.design_skills, so a skill that
COULD run at a different complexity still counts. Being over-inclusive here
costs a stale paragraph; being under-inclusive loses real QA feedback, which
is the failure this function was built to fix.
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

sys.path.insert(0, str(DC / "scripts"))
try:
    import product_pathways as _pw
except Exception as e:
    sys.exit(f"NOTHING WRITTEN — product_pathways will not import: {e}")

s = SKILL.read_text(encoding="utf-8")

if "_live_skills" in s:
    print("Already patched — only a live skill's rejection counts.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("only a live skill's rejection counts", s,
         '''    if skill_num not in FEEDBACK_SKILLS:
        return ""

    blocks = []
    for num in sorted(SKILL_FILES):
        if num <= skill_num:
            continue''',
         '''    if skill_num not in FEEDBACK_SKILLS:
        return ""

    # Only skills that are part of THIS pathway. The checkpoint outlives the
    # pathway change: a document re-run on skills 01/04/07 still carried skill
    # 05's "no Playwright tests" rejection from a previous run, and REX
    # obediently wrote a Playwright suite for a document two minutes into the
    # build. A rejection from a skill that no longer runs is a ghost.
    #
    # A superset on purpose — pw.skills plus pw.design_skills, so a skill that
    # could run at another complexity still counts. Over-inclusive costs a
    # stale paragraph; under-inclusive loses the real QA feedback this
    # function exists to deliver.
    _live_skills = _live_skill_numbers(topic)

    blocks = []
    for num in sorted(SKILL_FILES):
        if num <= skill_num or num not in _live_skills:
            continue''')

s = swap("the helper", s,
         '''def prior_failure_context(topic: str, skill_num: str, results: dict) -> str:''',
         '''def _live_skill_numbers(topic: str) -> set:
    """Which skills this product's pathway can run. Defensive: on any
    failure it returns every skill, which is exactly today's behaviour —
    a pathway lookup must never be able to silence real QA feedback."""
    try:
        pw = pathways.for_topic(topic, quiet=True)
        return set(pw.skills) | set(pw.design_skills)
    except Exception as e:
        print(f"⚠️  could not read the pathway for '{topic}' ({e}) — "
              f"treating every skill's report as relevant", flush=True)
        return set(SKILL_FILES)


def prior_failure_context(topic: str, skill_num: str, results: dict) -> str:''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-staleghost-{stamp}.py")
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

# ── whose opinion counts, per pathway ────────────────────────────────────────
ALL = {"01", "02", "03", "04", "05", "06", "07"}
print("\nwhose rejection reaches the build, per pathway:\n")
print(f"  {'pathway':10} {'skills that run':26} rejections honoured for skill 04")
print("  " + "─" * 72)
for name, pw in _pw.PATHWAYS.items():
    live = set(pw.skills) | set(pw.design_skills)
    honoured = sorted(n for n in live if n > "04")
    ignored = sorted(n for n in ALL - live if n > "04")
    print(f"  {name:10} {','.join(sorted(live)):26} "
          f"{','.join(honoured) or '(none)':12} "
          + (f" ignored: {','.join(ignored)}" if ignored else ""))

# ── against the real checkpoint for the document ─────────────────────────────
import json
slug = "ducorn-technology-stack-documentation"
ckpt = DC / "ducorn-products" / "docs" / f"{slug}-gstack-checkpoint.json"
if ckpt.is_file():
    try:
        data = json.loads(ckpt.read_text(errors="replace"))
    except ValueError:
        data = {}
    results = data.get("results", data)
    pw = _pw.PATHWAYS["document"]
    live = set(pw.skills) | set(pw.design_skills)
    print(f"\n{slug} — what the checkpoint holds:\n")
    for k, v in sorted(results.items()):
        if not isinstance(v, dict):
            continue
        num = k.split("-")[0]
        status = v.get("status", "?")
        fate = ("—" if status != "fail"
                else "reaches REX" if num in live else "IGNORED (not on this pathway)")
        print(f"  {k:26} {status:6} {fate}")
    ghosts = [k for k, v in results.items()
              if isinstance(v, dict) and v.get("status") == "fail"
              and k.split("-")[0] not in live]
    if ghosts:
        print(f"\n  {len(ghosts)} stale rejection(s) will no longer reach the "
              f"build: {', '.join(sorted(ghosts))}")
    else:
        print("\n  no stale rejections in this checkpoint")

src = SKILL.read_text(encoding="utf-8")
print()
for must, why in [
    ("_live_skills = _live_skill_numbers(topic)",
     "the pathway decides whose opinion counts"),
    ("num <= skill_num or num not in _live_skills",
     "a skill outside the pathway is skipped"),
    ("treating every skill's report as relevant",
     "a pathway failure cannot silence real feedback"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print("""
The stale files REX wrote under the ghost's instruction are still on disk.
For a document none of them belong:

  cd ~/DC/ducorn-products/products/ducorn-technology-stack-documentation
  rm -rf tests .pytest_cache .venv .env.example requirements.txt service.json

Then re-run. Skill 04 replays from a changed prompt fingerprint, so it will
rebuild rather than reuse the tainted result.
""")
