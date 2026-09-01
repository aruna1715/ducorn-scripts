#!/usr/bin/env python3
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
    print("running the real run_test_suite (venv + pip + browser)...\n")
    t0 = time.time()
    verdict, detail = run_test_suite(SLUG)
    print(detail[-3000:])
    print(f"\nrun_test_suite: {verdict}  ({time.time() - t0:.0f}s)")

    gate, why = ui_test_coverage(SLUG)
    print(f"ui_test_coverage: {gate} — {why}")

    ok = (verdict == "pass" and gate == "pass" and "drive the page" in why)
    if ok:
        print("\n✅ a generated Playwright test ran in the product's own venv "
              "and the gate took the drives_page branch")
    else:
        print("\n❌ not proven. The gate is still decorative for UI products.")
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
