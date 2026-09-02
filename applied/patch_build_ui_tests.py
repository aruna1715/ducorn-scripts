#!/usr/bin/env python3
"""
Tell REX what gate 3 is going to ask for, from the gate's own definition.

── THE ASYMMETRY ────────────────────────────────────────────────────────────

    🖥️  UI test coverage: FAIL — ships a UI but the tests reference only 0 of
        61 page elements (need 15) and never drive the rendered page —
        reading the HTML is not testing it

That is the gate doing exactly what it was fixed to do this morning, on its
first real build. Before today the id pattern could not see half of valid HTML,
finding no ids meant an automatic pass, and Playwright was installed nowhere,
so this product would have reached you as "QA passed".

But look at what REX was told to build. Skill 04, Step 3, in full:

    Every product must have:
    - README.md
    - .env.example
    - requirements.txt or package.json

Nothing about tests that render the page. Nothing saying a browser is
available. Skill 04 was written when it was not — Playwright went in this
morning, and the instructions did not move with it.

So the gate now asks for something the builder was never told to produce.
Raising a bar without handing over the ladder gives you a pipeline that fails
honestly and never passes.

── WHY THE FIX IS NOT "ADD A PARAGRAPH TO 04-build.md" ──────────────────────

A paragraph would work today and drift by Friday. The gate's bar is computed:

    need = max(3, len(ids) // 4)

If that changes, prose in a markdown file does not, and then the builder is
told one thing and judged by another — which is the same two-copies problem
that produced five separate bugs here this week.

So the thresholds become named constants, ui_test_coverage uses them, and the
instruction REX receives is GENERATED FROM THEM. Change the fraction and the
sentence in the prompt changes with it, because it is the same number.

── WHAT REX NOW GETS ────────────────────────────────────────────────────────

Injected into skill 04's prompt, and only when the product actually has a UI —
detected by APPROVED_DESIGN.html, which node_build writes exactly when a design
was chosen at gate 2:

    · a browser test is required, and pytest + playwright are ALREADY
      installed in this product's venv — do not add them to requirements.txt
    · the exact bar: reference at least one quarter of the page's ids, or
      drive the rendered page
    · a worked example that passes, using the same API prove_ui_gate.py uses
    · what the gate's failure message will say if it does not

The same mechanism as the interface guidelines this morning: injected into the
prompt rather than referenced by path, because REX's file tool is jailed to its
own product and cannot read gstack/.

A product with no UI gets none of this.
"""
import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
s = SKILL.read_text(encoding="utf-8")

if "UI_REFERENCE_FRACTION" in s:
    sys.exit("Already patched — the build skill is told the UI test bar.")
if "_skill_text" not in s:
    sys.exit("Apply patch_skill_guidelines.py first — this extends _skill_text. "
             "NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the bar, named once ───────────────────────────────────────────────────
s = swap("constants", s, '''UI_EXT = {".html", ".htm"}''',
         '''UI_EXT = {".html", ".htm"}

# The bar a UI product's tests must clear, in one place.
#
# ui_test_coverage enforces these and the build skill's prompt is generated
# from them, so the builder is told the same number it will be judged by. They
# used to be a literal in the gate and nothing at all in the instructions,
# which is how REX shipped a 61-element interface with zero tests touching it
# and was then failed for it.
UI_MIN_REFERENCED = 3          # floor, however small the page
UI_REFERENCE_FRACTION = 4      # or a quarter of the ids, whichever is larger
UI_DRIVER_RE = re.compile(r"playwright|page\\.goto|sync_playwright|selenium",
                          re.I)


def ui_elements_needed(total_ids: int) -> int:
    """How many of a page's ids the tests must reference to pass gate 3."""
    return max(UI_MIN_REFERENCED, total_ids // UI_REFERENCE_FRACTION)''')

# ── 2. the gate uses them ────────────────────────────────────────────────────
s = swap("gate uses constants", s,
         '''    drives_page = bool(re.search(r"playwright|page\\.goto|sync_playwright|selenium", blob, re.I))''',
         '''    drives_page = bool(UI_DRIVER_RE.search(blob))''')

s = swap("need from helper", s, '''    need = max(3, len(ids) // 4)''',
         '''    need = ui_elements_needed(len(ids))''')

# ── 3. the contract REX is handed ────────────────────────────────────────────
s = swap("contract builder", s, '''def _skill_text(skill_num: str, skill_name: str, topic: str) -> str:''',
         '''# Skill 04 builds; it is the one that has to satisfy the UI gate.
BUILD_SKILL = "04"


def _has_ui(topic: str) -> bool:
    """
    Does this product ship an interface?

    APPROVED_DESIGN.html is written by node_build exactly when a design was
    chosen at gate 2, which makes it a fact about this run rather than a guess
    from the file listing — at build time the HTML the product will ship does
    not exist yet.
    """
    try:
        return (PRODUCTS_DIR / "products" / topic / "APPROVED_DESIGN.html").is_file()
    except Exception:
        return False


def ui_test_contract(topic: str) -> str:
    """
    What gate 3 will require of this product's tests, in REX's words.

    Generated from UI_MIN_REFERENCED and UI_REFERENCE_FRACTION, the same
    constants ui_test_coverage enforces. Prose in a markdown file would say
    'a quarter' until someone changed the fraction and then quietly lie.
    """
    fraction = f"1/{UI_REFERENCE_FRACTION}"
    return f"""

{'=' * 70}
THIS PRODUCT SHIPS A USER INTERFACE — TESTS THAT RENDER IT ARE REQUIRED
{'=' * 70}
An approved design is in APPROVED_DESIGN.html. Gate 3 checks that the tests
you write actually exercise the interface, and it will REJECT this build
otherwise. The check is not a formality; it reads your tests.

TO PASS, the test suite must do ONE of these:

  A. Drive the rendered page with Playwright — load it in a browser, click
     things, assert on what appears. This is the one to write.

  B. Or reference at least {fraction} of the page's id / data-testid
     attributes (minimum {UI_MIN_REFERENCED}) in assertions.

PLAYWRIGHT IS ALREADY INSTALLED in this product's virtual environment, along
with pytest, from products/_shared/requirements-ui.txt. Do NOT add either to
requirements.txt and do NOT write a mock browser — the real one is there.

A test that passes gate 3:

    from pathlib import Path
    from playwright.sync_api import sync_playwright

    PAGE = Path(__file__).parent / "index.html"

    def test_page_renders_and_responds():
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(PAGE.as_uri())
            assert page.inner_text("#title")
            page.click("#refresh")
            assert page.query_selector("#results")
            browser.close()

If the page loads its data from an API, serve it from that API and navigate to
the served URL instead of a file:// path — a fetch from file:// is
cross-origin from a null origin and will fail, and you will be testing an
error state.

Give every element a test asserts on a stable id or data-testid, in
kebab-case. If you skip this, gate 3 reports:

    ships a UI but the tests reference only 0 of N page elements
    (need {{needed}}) and never drive the rendered page —
    reading the HTML is not testing it
{'=' * 70}
"""


def _skill_text(skill_num: str, skill_name: str, topic: str) -> str:''')

# ── 4. injected for the build skill, when there is a UI ──────────────────────
s = swap("inject", s, '''    if skill_num not in UI_REVIEW_SKILLS:
        return text''',
         '''    if skill_num == BUILD_SKILL:
        if _has_ui(topic):
            print(f"🖥️  skill {skill_num}: this product has an approved design "
                  f"— requiring browser tests", flush=True)
            return text + ui_test_contract(topic)
        return text

    if skill_num not in UI_REVIEW_SKILLS:
        return text''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-uibuild-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, SKILL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# ── exercise it ──────────────────────────────────────────────────────────────
src = SKILL.read_text(encoding="utf-8")
tree = ast.parse(src)


def seg(name):
    return next((ast.get_source_segment(src, n) for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)


ns = {"re": re, "UI_MIN_REFERENCED": 3, "UI_REFERENCE_FRACTION": 4}
exec(seg("ui_elements_needed"), ns)
exec(seg("ui_test_contract"), ns)
needed, contract = ns["ui_elements_needed"], ns["ui_test_contract"]

print("\nchecking the bar:")
for total, expect in [(0, 3), (4, 3), (12, 3), (16, 4), (61, 15), (200, 50)]:
    got = needed(total)
    ok = got == expect
    print(f"  {'ok  ' if ok else 'FAIL'} {total:3} ids on the page → "
          f"{got} must be referenced")
    if not ok:
        shutil.copy2(backup, SKILL)
        sys.exit(f"expected {expect}, got {got} — reverted from {backup}")

# 61 ids needing 15 is the number from tonight's failure. If the contract and
# the gate ever disagree, that is the whole bug this patch exists to prevent.
if needed(61) != 15:
    shutil.copy2(backup, SKILL)
    sys.exit("the helper disagrees with tonight's gate output — reverted")

text = contract("zz")
for must in ("playwright", "APPROVED_DESIGN.html", "1/4", "sync_playwright",
             "Do NOT add", "kebab-case"):
    if must not in text:
        shutil.copy2(backup, SKILL)
        sys.exit(f"the contract does not mention {must!r} — reverted")
print(f"  ok   the contract REX receives is {len(text):,} chars and names the "
      f"tooling")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Nothing to restart — skill_runner is imported fresh per subprocess.")
print("Re-run the build and REX will be told what gate 3 wants:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase build --engine gstack --coder crewai "
      "--complexity simple")
