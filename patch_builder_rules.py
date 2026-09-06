#!/usr/bin/env python3
"""
The builder gets the rules, and a dead reviewer's report stops giving orders.

    python3 scripts/patch_builder_rules.py

── ONE: the writer was the only skill not told what it was writing ──────────

_skill_text(), in order:

    17:    if skill_num == BUILD_SKILL:
    23:        text = text + deployment_contract(topic)     gated, correctly
    29:        return text                                  ← returns HERE
    34:    pw = pathways.for_topic(topic, quiet=True)
    35:    if pw.prompt_rules:
    36:        text = text + pw.prompt_rules                 ← unreachable for 04

So "THIS IS A DOCUMENT. IT SHIPS NO CODE. Do NOT require Playwright, pytest,
requirements.txt, .env.example" reached skills 03, 05 and 07 — the reviewers —
and never reached REX, the skill that actually writes the thing.

Which left 04-build.md's own checklist unopposed:

    - `.env.example` — all required env vars with descriptions, no values
    - `requirements.txt` or `package.json` — all dependencies with versions

and REX dutifully produced a .env.example for a document explaining that the
document has no environment variables.

My ordering. I put the early return above the rules, in the patch whose whole
purpose was making the pathway reach the skills — and it reached every skill
except the one that matters most. Exactly the shape of the stack-context bug
it was written alongside.

── TWO: the previous run's reviewer is still on disk ────────────────────────

patch_stale_rejection.py stopped a dead skill's verdict reaching the build
through the CHECKPOINT. It is also sitting in the product directory as a file,
and REX reads that directory:

    products/<topic>/code-review.md   Sep 2 19:48
        | `tests/` | ❌ Required for HTML products | ❌ ABSENT — CRITICAL |
        **[Missing: tests/test_ui.py] — No test files present.

    products/<topic>/qa-report.md     Sep 2 19:46
        **[CRITICAL] No test suite — 0 tests collected

REX wrote a 13 KB Playwright suite for a document, correctly following a
written instruction from a reviewer that no longer runs. Closing one channel
and leaving the other open is not closing it.

Before a build, a previous run's review artifacts are moved to
`.superseded/`. Moved, not deleted — they are the record of why the last
attempt failed, and on a software product they are exactly what you want to
read. They are simply not instructions any more.
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
    import product_pathways as _pw          # noqa: F401  (import-time check)
except Exception as e:
    sys.exit(f"NOTHING WRITTEN — product_pathways will not import: {e}")

s = SKILL.read_text(encoding="utf-8")

if "def supersede_stale_reviews" in s:
    print("Already patched — the builder gets the rules.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ 1. the rules come first, for every skill ════════════════════════════════
s = swap("rules before the build branch", s,
         '''    skill_file = SKILLS_DIR / SKILL_FILES[skill_num]
    text = (skill_file.read_text() if skill_file.exists()
            else f"Complete {skill_name} for {topic}.")

    if skill_num == BUILD_SKILL:''',
         '''    skill_file = SKILLS_DIR / SKILL_FILES[skill_num]
    text = (skill_file.read_text() if skill_file.exists()
            else f"Complete {skill_name} for {topic}.")

    # What this product IS — before anything else, so it reaches EVERY skill.
    #
    # This block used to sit below the BUILD_SKILL branch, which returns. So
    # the document rules went to the reviewers and never to the writer, and
    # REX built against 04-build.md's software checklist unopposed —
    # producing a .env.example for a document to explain that the document
    # has no environment variables.
    pw = pathways.for_topic(topic, quiet=True)
    if pw.prompt_rules:
        text = text + pw.prompt_rules

    if skill_num == BUILD_SKILL:''')

# the later lookup is now redundant — one call, one answer
s = swap("one pathway lookup", s,
         '''    # What this product actually is, said out loud to every reviewer. The
    # pathway carries the wording, so a new type is added in one file rather
    # than by appending another paragraph here.
    pw = pathways.for_topic(topic, quiet=True)
    if pw.prompt_rules:
        text = text + pw.prompt_rules

    if skill_num not in UI_REVIEW_SKILLS:''',
         '''    if skill_num not in UI_REVIEW_SKILLS:''')

# ═══ 2. a previous run's reviewer stops giving orders ════════════════════════
s = swap("supersede stale reviews", s,
         '''def _has_ui(topic: str) -> bool:''',
         '''# Files a REVIEWER wrote about a previous attempt. Useful history; not
# instructions. REX reads the product directory, so a code review demanding
# "tests/test_ui.py — ABSENT, CRITICAL" is an order as far as the builder is
# concerned, however dead the skill that wrote it.
_REVIEW_ARTIFACTS = ("code-review.md", "qa-report.md", "qa-report-skill-06.md",
                     "content-review.md")


def supersede_stale_reviews(topic: str) -> list:
    """
    Move a previous run's review reports out of the builder's reach.

    Moved to .superseded/, not deleted: they are the record of why the last
    attempt failed and on a software product they are worth reading. They
    just stop being instructions.

    patch_stale_rejection.py closed the same ghost in the checkpoint. Closing
    one channel and leaving the other open is not closing it.
    """
    d = PRODUCTS_DIR / "products" / topic
    if not d.is_dir():
        return []
    moved = []
    dest = d / ".superseded"
    for name in _REVIEW_ARTIFACTS:
        p = d / name
        if not p.is_file():
            continue
        try:
            dest.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            p.rename(dest / f"{p.stem}-{stamp}{p.suffix}")
            moved.append(name)
        except OSError as e:
            print(f"⚠️  could not supersede {name}: {e}", flush=True)
    return moved


def _has_ui(topic: str) -> bool:''')

# call it at the top of a build
s = swap("reuse the resolved pathway", s,
         "        if pathways.for_topic(topic, quiet=True).deploys:",
         "        if pw.deploys:")

s = swap("call it before building", s,
         '''    if skill_num == BUILD_SKILL:
        # NOT every product is deployed.''',
         '''    if skill_num == BUILD_SKILL:
        _superseded = supersede_stale_reviews(topic)
        if _superseded and not quiet:
            print(f"🗃️  superseded {len(_superseded)} report(s) from a "
                  f"previous attempt: {', '.join(_superseded)} — history, "
                  f"not instructions", flush=True)

        # NOT every product is deployed.''')

# datetime is used by the new helper; skill_runner must have it at module level
if "\nfrom datetime import datetime" not in s and "\nimport datetime" not in s:
    s = swap("import datetime", s, "\nfrom pathlib import Path\n",
             "\nfrom datetime import datetime\nfrom pathlib import Path\n")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-builderrules-{stamp}.py")
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

# ── the property that matters: does the BUILD skill get the rules? ───────────
src = SKILL.read_text(encoding="utf-8")
tree = ast.parse(src)
fn = next((n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_skill_text"), None)
if fn is None:
    die("_skill_text not found")

# line of the prompt_rules append, and of the BUILD_SKILL early return
lines = ast.unparse(fn).splitlines()
i_rules = next((i for i, l in enumerate(lines) if "pw.prompt_rules" in l), None)
i_build = next((i for i, l in enumerate(lines) if "BUILD_SKILL" in l), None)
if i_rules is None or i_build is None:
    die("could not locate the rules block or the build branch")
print(f"\n  prompt_rules at statement {i_rules}, BUILD_SKILL branch at "
      f"{i_build}")
if i_rules > i_build:
    die("the rules still come AFTER the build branch — 04 would miss them")
print("  ok   the rules are added before the build branch returns")

_body = ast.unparse(fn)
_lookups = _body.count("pathways.for_topic(")
if _lookups != 1:
    die(f"{_lookups} pathway lookups inside _skill_text — expected 1")
print("  ok   one pathway lookup inside _skill_text, one answer")

for must, why in [
    ("def supersede_stale_reviews", "a previous run's reports are moved aside"),
    ("_superseded = supersede_stale_reviews(topic)", "it runs before a build"),
    ('p.rename(dest / f"{p.stem}-{stamp}{p.suffix}")',
     "moved to .superseded/, not deleted"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

# ── what skill 04 would now be told, for each pathway ────────────────────────
print("\nwhat the BUILD skill is told, per pathway:\n")
for name, pw in _pw.PATHWAYS.items():
    first = (pw.prompt_rules.strip().splitlines() or ["(no extra rules)"])[1:2]
    print(f"  {name:10} {(first[0] if first else '(no extra rules)')[:58]}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print("""
Clear what the last two attempts left behind, then re-run:

  cd ~/DC/ducorn-products/products/ducorn-technology-stack-documentation
  rm -rf tests .pytest_cache .venv .env.example requirements.txt service.json

The review reports are moved to .superseded/ automatically on the next build —
you do not need to delete those.
""")
