#!/usr/bin/env python3
"""
Put the browser where the generated tests actually run.

── THE HALF THAT IS STILL MISSING ───────────────────────────────────────────

Installing playwright fixed OUR half. run_test_suite builds a venv per product
and runs pytest inside it:

    venv = d / ".venv"
    py   = venv / "bin" / "python"
    if req.exists():
        pip install -r requirements.txt
    pytest -v

A generated test that does `from playwright.sync_api import sync_playwright`
runs in THAT interpreter, not in ducorn/.venv. Unless the product's own
requirements.txt happens to name playwright — and REX has never had a reason to
put it there — the import fails, the test errors, and ui_test_coverage's
drives_page branch stays exactly as unreachable as it was before we installed
anything.

That is why install_playwright.py wrote products/_shared/requirements-ui.txt.
This is the patch that uses it.

── WHAT CHANGES ─────────────────────────────────────────────────────────────

Before pytest runs, if the product ships any HTML, its venv also gets
_shared/requirements-ui.txt — pytest and playwright — and then
`playwright install chromium`, which is a no-op against the shared browser
cache that ducorn/.venv already populated.

The chromium step is allowed to fail without failing the build, and that is a
deliberate exception to how I have been treating silent fallbacks all evening:
if the browser genuinely is not there, pytest fails a moment later with
playwright's own message, which names the problem far better than anything I
would write here. The step is still recorded in the output either way.

Products with no UI are untouched — no venv bloat, no download, no delay.

Also writes scripts/prove_ui_gate.py, which builds a throwaway UI product with
a real Playwright test, runs the actual run_test_suite over it, and checks the
gate reaches its drives_page branch. Run it once. Every previous claim about
this gate has been made by reading code, including two of mine that were
wrong.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
PROVE = Path("/Users/ducorn/DC/scripts/prove_ui_gate.py")

s = SKILL.read_text(encoding="utf-8")
if "requirements-ui.txt" in s:
    sys.exit("Already patched — UI products get a browser in their venv.")

OLD = '''        else:
            steps.append("(no requirements.txt — skipped install)")

        r = subprocess.run([str(py), "-m", "pytest", "-v", "--tb=short"],'''

NEW = '''        else:
            steps.append("(no requirements.txt — skipped install)")

        # A product that ships a UI needs a browser in ITS OWN venv.
        #
        # ui_test_coverage has a branch for tests that drive the rendered page,
        # and it was unreachable for months because playwright was installed
        # nowhere. Installing it in ducorn/.venv fixes the pipeline's half and
        # leaves the generated tests — which run in THIS interpreter — still
        # unable to import it. Both halves, or the gate stays decorative.
        ui_files = [p for p in d.rglob("*")
                    if p.is_file() and p.suffix.lower() in UI_EXT
                    and ".venv" not in p.parts]
        shared_ui_req = PRODUCTS_DIR / "products" / "_shared" / "requirements-ui.txt"
        if ui_files and shared_ui_req.exists():
            r = subprocess.run([str(py), "-m", "pip", "install", "-q",
                                "-r", str(shared_ui_req)],
                               capture_output=True, text=True,
                               timeout=SOURCE_TIMEOUT, cwd=str(d))
            steps.append(f"$ pip install -r _shared/requirements-ui.txt "
                         f"({len(ui_files)} HTML file(s))  (exit {r.returncode})\\n"
                         f"{r.stderr[-800:]}")
            if r.returncode != 0:
                return "fail", "\\n\\n".join(steps)

            # Against the browser cache ducorn/.venv already populated this is
            # a no-op. Not fatal if it fails: pytest will fail a moment later
            # with playwright's own message, which describes a missing browser
            # better than anything written here — and the step above is in the
            # output either way.
            r = subprocess.run([str(py), "-m", "playwright", "install", "chromium"],
                               capture_output=True, text=True, timeout=300,
                               cwd=str(d))
            steps.append(f"$ playwright install chromium  (exit {r.returncode})"
                         + (f"\\n{r.stderr[-400:]}" if r.returncode else ""))
        elif ui_files:
            steps.append(f"⚠️  {len(ui_files)} HTML file(s) but no "
                         f"{shared_ui_req} — UI tests cannot drive a browser. "
                         f"Run scripts/install_playwright.py --apply.")

        r = subprocess.run([str(py), "-m", "pytest", "-v", "--tb=short"],'''

if s.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {s.count(OLD)}, expected 1. NOTHING WRITTEN.")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-uivenv-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")

try:
    ast.parse(SKILL.read_text(encoding="utf-8"))
except SyntaxError as e:
    shutil.copy2(backup, SKILL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

PROVE.write_text('''#!/usr/bin/env python3
"""
Prove the UI gate end to end, once, with a real browser.

    cd ~/DC/ducorn && .venv/bin/python ../scripts/prove_ui_gate.py

Builds a throwaway product that ships an HTML page and a Playwright test,
runs the REAL run_test_suite over it — venv, pip, pytest, browser — and then
asks ui_test_coverage for its verdict.

This exists because every claim made about this gate so far has been made by
reading code, and two of those claims were mine and wrong: the function is
ui_test_coverage, not check_ui_tests, and installing playwright in ducorn/.venv
does nothing for tests that run in the product's own venv. Takes a minute or
two the first time, mostly pip.
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/ducorn")

from skill_runner import run_test_suite, ui_test_coverage, PRODUCTS_DIR  # noqa

SLUG = "zz-ui-gate-proof"
d = PRODUCTS_DIR / "products" / SLUG

PAGE = """<!doctype html>
<html><body>
  <h1 id="title">Unit Converter</h1>
  <input id="celsius" value="100">
  <button id="convert">Convert</button>
  <p id="result">212.0</p>
</body></html>
"""

TEST = """from pathlib import Path
from playwright.sync_api import sync_playwright

PAGE = Path(__file__).parent / "index.html"


def test_page_renders_and_responds():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(PAGE.as_uri())
        assert page.inner_text("#title") == "Unit Converter"
        assert page.input_value("#celsius") == "100"
        page.click("#convert")
        assert page.inner_text("#result") == "212.0"
        browser.close()
"""


def main():
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "index.html").write_text(PAGE, encoding="utf-8")
    (d / "test_ui.py").write_text(TEST, encoding="utf-8")
    (d / "requirements.txt").write_text("", encoding="utf-8")

    print(f"product: {d}")
    print("running the real run_test_suite (venv + pip + browser)...\\n")
    t0 = time.time()
    verdict, detail = run_test_suite(SLUG)
    print(detail[-3000:])
    print(f"\\nrun_test_suite: {verdict}  ({time.time() - t0:.0f}s)")

    gate, why = ui_test_coverage(SLUG)
    print(f"ui_test_coverage: {gate} — {why}")

    ok = (verdict == "pass" and gate == "pass" and "drive the page" in why)
    if ok:
        print("\\n✅ a generated Playwright test ran in the product's own venv "
              "and the gate took the drives_page branch")
    else:
        print("\\n❌ not proven. The gate is still decorative for UI products.")
        if verdict != "pass":
            print("   pytest did not pass — read the output above; a "
                  "ModuleNotFoundError for playwright means the product venv "
                  "did not get _shared/requirements-ui.txt")
        elif "drive the page" not in why:
            print(f"   the gate passed on the wrong branch: {why}")

    shutil.rmtree(d, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
''', encoding="utf-8")

print("applied: UI products get playwright in their own venv before pytest")
print(f"created: {PROVE}")
print(f"backup:  {backup.name}")
print()
print("Prove it, once:")
print("  cd ~/DC/ducorn && .venv/bin/python ../scripts/prove_ui_gate.py")
