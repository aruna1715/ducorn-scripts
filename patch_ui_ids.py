#!/usr/bin/env python3
"""
The UI gate cannot see a single-quoted id, and passes when it sees nothing.

── HOW THIS SURFACED ────────────────────────────────────────────────────────

install_playwright.py builds a probe page and asks the gate about it. The real
proof passed:

    ui_test_coverage: pass — UI tests drive the page; 4/4 elements referenced

while the probe reported:

    MISS ui_test_coverage reaches its drives_page branch
         UI present but declares no element ids to assert against

Same function, same kind of page, opposite answers. The only difference is that
my probe wrote its attributes with single quotes:

    <h1 id='title'>x</h1>          probe        → no ids found
    <h1 id="title">x</h1>          proof        → 4 ids found

because the gate looks for one quote style:

    ids |= set(re.findall(r'\\bid="([\\w\\-]+)"', text))
    ids |= set(re.findall(r'\\bdata-testid="([\\w\\-]+)"', text))

Single quotes are valid HTML and models emit both. This project's own design
tool already knows that — generate_design.py has

    TESTID_RE = re.compile(r'data-testid\\s*=\\s*["\\']([^"\\']+)["\\']')

so the two halves of the same pipeline disagree about what an attribute looks
like. The gate is the half that is wrong.

── WHY IT MATTERS MORE THAN A REGEX ─────────────────────────────────────────

    if not ids:
        return "pass", "UI present but declares no element ids to assert against"

Finding nothing is treated as nothing to check, and nothing to check is treated
as fine. So a generated page written with single quotes does not get a lenient
review — it skips review entirely, and reports a pass while doing it. That is
the same shape as everything else this week, and it is the one that reaches a
founder as "QA passed".

── THREE CHANGES ────────────────────────────────────────────────────────────

1. BOTH QUOTE STYLES, for id and data-testid, matching the pattern the design
   tool already uses.

2. drives_page IS CHECKED FIRST. A test that renders the page and interacts
   with it is real evidence whether or not the markup declares ids. It used to
   sit behind the id count, so a page with no visible ids never reached it.

3. NO IDS AND NO BROWSER TEST IS NOW A FAIL, not a pass. Nothing in that
   combination verifies anything, and saying so is the honest verdict.

   THIS IS A BEHAVIOUR CHANGE and you may want to push back on it. The lenient
   branch made sense when Playwright was not installed and driving the page was
   impossible — a product could not do better, so failing it would have been
   unfair. That is no longer true as of an hour ago. If it turns out to block
   something legitimate, the answer is to write the browser test, and the
   message says so.
"""
import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
s = SKILL.read_text(encoding="utf-8")

if "_ATTR_RE" in s:
    sys.exit("Already patched — the gate reads both quote styles.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


s = swap("id extraction", s, '''    ids = set()
    for p in html:
        text = p.read_text(errors="replace")
        ids |= set(re.findall(r'\\bid="([\\w\\-]+)"', text))
        ids |= set(re.findall(r'\\bdata-testid="([\\w\\-]+)"', text))''',
         '''    # Both quote styles. This matched only double quotes, so a page written
    # with single quotes — valid HTML, and models emit both — declared "no
    # ids", which the branch below then treated as nothing to check and passed.
    # generate_design.py's TESTID_RE has always allowed either; the two halves
    # of the pipeline disagreed about what an attribute looks like.
    #
    # The lookbehind is not decoration: \\b before `id` also matches inside
    # `data-id`, so a plain \\bid= pattern silently collects data-id values as
    # element ids. My own check below caught that in this patch.
    _ATTR_RE = re.compile(
        r'(?<![\\w-])(?:data-testid|id)\\s*=\\s*["\\\']([\\w\\-]+)["\\\']')

    ids = set()
    for p in html:
        text = p.read_text(errors="replace")
        ids |= set(_ATTR_RE.findall(text))''')

s = swap("verdict order", s, '''    if not ids:
        return "pass", "UI present but declares no element ids to assert against"
    need = max(3, len(ids) // 4)
    if drives_page and covered:
        return "pass", f"UI tests drive the page; {covered}/{len(ids)} elements referenced"
    if covered >= need:
        return "pass", f"UI assertions reference {covered}/{len(ids)} page elements"''',
         '''    # Rendering the page is evidence on its own. This used to sit BELOW the
    # id count, so a page whose ids were invisible to the regex never reached
    # it — the strongest signal was unreachable because of the weakest one.
    if drives_page:
        return "pass", (f"UI tests drive the page"
                        + (f"; {covered}/{len(ids)} elements referenced"
                           if ids else " (no ids declared, but it is rendered)"))

    if not ids:
        # Was a pass. Nothing here verifies the interface: no ids to assert
        # against and no test that renders it. Passing on an absence of
        # evidence is how a UI reaches a founder as "QA passed" unchecked.
        # Failing this only became fair once Playwright existed — before that
        # a product could not have done better.
        return "fail", (f"ships {len(html)} HTML file(s) whose elements declare "
                        f"no id or data-testid, and no test renders the page. "
                        f"Nothing here checks the interface. Add ids and assert "
                        f"on them, or drive the page with Playwright — it is "
                        f"installed and available in this product's venv.")

    need = max(3, len(ids) // 4)
    if covered >= need:
        return "pass", f"UI assertions reference {covered}/{len(ids)} page elements"''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-uiids-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, SKILL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# ── exercise the new pattern against real markup ─────────────────────────────
m = re.search(r"_ATTR_RE = re\.compile\(\s*(r'[^\n]*')\s*\)", s)
if not m:
    shutil.copy2(backup, SKILL)
    sys.exit(f"_ATTR_RE did not land — reverted from {backup}")
ATTR_RE = re.compile(eval(m.group(1)))

CASES = [
    ('<h1 id="title">x</h1>', {"title"}, "double quotes"),
    ("<h1 id='title'>x</h1>", {"title"}, "single quotes — the case that failed"),
    ('<p data-testid="total">1</p>', {"total"}, "data-testid, double"),
    ("<p data-testid='total'>1</p>", {"total"}, "data-testid, single"),
    ('<b id = "spaced">x</b>', {"spaced"}, "spaces around ="),
    ('<i id="a"></i><i id=\'b\'></i>', {"a", "b"}, "mixed in one file"),
    ('<div class="id-like">x</div>', set(), "class is not an id"),
    ('<div data-id="nope">x</div>', set(), "data-id is not id"),
    ('<div aria-labelledby="x" id="real">y</div>', {"real"}, "id beside another attr"),
    ('<div gridid="no">y</div>', set(), "a word ending in id is not id"),
]
print("\nchecking attribute matching:")
for markup, expect, label in CASES:
    got = set(ATTR_RE.findall(markup))
    ok = got == expect
    print(f"  {'ok  ' if ok else 'FAIL'} {label:38} {sorted(got) or '—'}")
    if not ok:
        shutil.copy2(backup, SKILL)
        sys.exit(f"expected {sorted(expect)}, got {sorted(got)} — reverted "
                 f"from {backup}")

print(f"\napplied: both quote styles; drives_page checked first; an "
      f"unverifiable UI fails")
print(f"backup:  {backup.name}")
print()
print("Re-run the proof and the installer's probe — both should pass now:")
print("  cd ~/DC/ducorn && .venv/bin/python ../scripts/prove_ui_gate.py")
print("  cd ~/DC && python3 scripts/install_playwright.py")
