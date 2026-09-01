#!/usr/bin/env python3
"""
Give DuCorn a browser, so the UI gate stops being decorative.

    python3 scripts/install_playwright.py           # check what is missing
    python3 scripts/install_playwright.py --apply   # install it

── WHY ──────────────────────────────────────────────────────────────────────

skill_runner.check_ui_tests decides whether a product's tests exercise its
interface:

    drives_page = bool(re.search(r"playwright|page\\.goto|sync_playwright|selenium",
                                 blob, re.I))
    if drives_page and covered:
        return "pass", "UI tests drive the page; ..."
    if covered >= need:
        return "pass", "UI assertions reference N/M page elements"
    return "fail", "... never drive the rendered page — reading the HTML is
                    not testing it"

Playwright is not in ducorn/.venv. Neither is Selenium. So drives_page has been
False on every run there has ever been, and the only way a UI product can pass
that gate is the middle branch — the one whose own error message calls it
reading rather than testing.

The same shape as the rest of this week: a control that reads correctly in
isolation and never reaches what it is supposed to control.

── WHAT THIS INSTALLS, AND WHY EACH PIECE ───────────────────────────────────

  @playwright/cli (npm, global)
      The command-line browser for agents. A CLI rather than the MCP server
      on purpose: skill_runner launches subprocesses and reads exit codes,
      which is exactly the shape a CLI offers. MCP would need an agent holding
      a conversation, and there is no agent in that loop.

  playwright (pip, into ducorn/.venv)
      So the pipeline's own code — node_design screenshotting variants, and
      anything else we add — can drive a browser in-process.

  chromium browser binary
      Downloaded once into the shared cache and reused. Without it both of the
      above install cleanly and fail at first use, which is the failure mode
      this whole exercise is about.

  products/_shared/requirements-ui.txt
      The piece that is easy to forget. Generated tests run in each product's
      OWN venv, created by run_test_suite. Installing playwright globally makes
      OUR code work and leaves drives_page false for a second, quieter reason.
      This file is what run_test_suite installs into a UI product's venv.

Nothing here is wired into the pipeline yet — that is the next patch. This
step only makes the capability exist, and says plainly which parts are still
missing.
"""
import shutil
import subprocess
import sys
from pathlib import Path

DUCORN = Path("/Users/ducorn/DC/ducorn")
VENV_PY = DUCORN / ".venv/bin/python"
PRODUCTS = Path("/Users/ducorn/DC/ducorn-products")
SHARED = PRODUCTS / "products/_shared"
REQ_UI = SHARED / "requirements-ui.txt"

APPLY = "--apply" in sys.argv
results = []


def check(name, ok, detail="", fix=None, handled=False):
    """`fix` is a command --apply runs; `handled` means --apply deals with it
    some other way. Anything with neither is something only you can fix."""
    results.append({"name": name, "ok": bool(ok), "detail": detail,
                    "fix": fix, "handled": handled or bool(fix)})
    print(f"  {'ok  ' if ok else 'MISS'} {name}" + (f"   {detail}" if detail else ""))
    return bool(ok)


class _Failed:
    returncode, stdout = 127, ""

    def __init__(self, why):
        self.stderr = why


def run(cmd, **kw):
    """Never raise. A missing binary is a MISS to report, not a traceback."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        return _Failed(f"{type(e).__name__}: {e}")


print("\n── what is here now ────────────────────────────────────────────────")

node = shutil.which("npm")
check("npm on PATH", node, node or "install Node first — brew install node")

cli = shutil.which("playwright-cli") or shutil.which("playwright")
r = run([cli, "--version"]) if cli else None
check("@playwright/cli", cli and r and r.returncode == 0,
      (r.stdout.strip() if r and r.returncode == 0 else "not installed"),
      fix=["npm", "install", "-g", "@playwright/cli@latest"])

def last_line(text, n=90):
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return lines[-1][:n] if lines else ""


r = run([str(VENV_PY), "-c", "import playwright; print(getattr(playwright, "
                             "'__version__', 'installed'))"])
check("playwright in ducorn/.venv", r.returncode == 0,
      last_line(r.stdout) or last_line(r.stderr),
      fix=[str(VENV_PY), "-m", "pip", "install", "playwright"])

r = run([str(VENV_PY), "-c",
         "from playwright.sync_api import sync_playwright\n"
         "with sync_playwright() as p:\n"
         "    b = p.chromium.launch()\n"
         "    pg = b.new_page(); pg.set_content('<h1 id=t>ok</h1>')\n"
         "    print(pg.inner_text('#t')); b.close()"])
check("chromium launches and renders", r.returncode == 0 and "ok" in r.stdout,
      last_line(r.stdout) or last_line(r.stderr),
      fix=[str(VENV_PY), "-m", "playwright", "install", "chromium"])

check("products/_shared/requirements-ui.txt", REQ_UI.exists(),
      str(REQ_UI) if REQ_UI.exists() else "not created yet", handled=True)

# ── the gate itself, exercised rather than read ──────────────────────────────
print("\n── does the gate's browser branch become reachable? ────────────────")

sys.path.insert(0, str(DUCORN))

# The gate's function is ui_test_coverage. I called it check_ui_tests in v1 of
# this script from memory rather than looking — the same mistake as
# _build_pdf_kwargs. If it is ever renamed again, this says what IS there
# instead of failing with a name nobody can find.
GATE_FN = "ui_test_coverage"
gate = None
try:
    import skill_runner                              # noqa
    gate = getattr(skill_runner, GATE_FN, None)
    if gate is None:
        near = [n for n in dir(skill_runner)
                if "ui" in n.lower() or "coverage" in n.lower()]
        check(f"skill_runner.{GATE_FN} exists", False,
              f"not found; closest names: {near or 'none'}")
except Exception as e:
    check("skill_runner imports", False, f"{type(e).__name__}: {e}")

have_gate = gate is not None

if have_gate:
    import tempfile
    probe = PRODUCTS / "products" / "zz-playwright-probe"
    try:
        probe.mkdir(parents=True, exist_ok=True)
        # Quote styles are mixed ON PURPOSE. The first version of this probe
        # used single quotes throughout and reported MISS while the real proof
        # passed — because the gate's id pattern only matched double quotes, so
        # a single-quoted page declared "no ids" and was passed unchecked
        # (patch_ui_ids.py). This markup keeps that regression visible.
        (probe / "index.html").write_text(
            '<h1 id="title">x</h1>'
            "<button id='go'>g</button>"
            "<p data-testid='out'>y</p>",
            encoding="utf-8")
        # A test that DRIVES the page. Under the old install this file exists,
        # mentions playwright, and could never actually run.
        (probe / "test_ui.py").write_text(
            "from playwright.sync_api import sync_playwright\n"
            "def test_page():\n"
            "    with sync_playwright() as p:\n"
            "        b = p.chromium.launch(); pg = b.new_page()\n"
            "        pg.goto('file://%s/index.html')\n"
            "        assert pg.inner_text('#title')\n"
            "        pg.click('#go'); assert pg.query_selector('#out')\n"
            "        b.close()\n" % probe, encoding="utf-8")
        verdict, why = gate("zz-playwright-probe")
        check(f"{GATE_FN} reaches its drives_page branch",
              verdict == "pass" and "drive the page" in why, why)
    finally:
        shutil.rmtree(probe, ignore_errors=True)

# ── apply ────────────────────────────────────────────────────────────────────
failed = [r for r in results if not r["ok"]]
missing = [r for r in failed if r.get("fix")]
unfixable = [r for r in failed if not r.get("handled")]

if not APPLY:
    print()
    if not failed:
        print("Everything is in place.")
        sys.exit(0)
    # v1 printed "Everything is in place" while a check was failing, because
    # only checks WITH an install command counted. A failing check is a
    # failing check whether or not this script knows how to fix it.
    if missing:
        print(f"{len(missing)} thing(s) to install. Re-run with --apply:")
        for r in missing:
            print(f"  {' '.join(r['fix'])}")
    if not REQ_UI.exists():
        print(f"  (and write {REQ_UI})")
    for r in unfixable:
        print(f"NOT INSTALLABLE FROM HERE — {r['name']}: {r['detail']}")
    sys.exit(1)

print("\n── installing ──────────────────────────────────────────────────────")
for r in missing:
    print(f"\n$ {' '.join(r['fix'])}")
    p = subprocess.run(r["fix"])
    if p.returncode != 0:
        sys.exit(f"\n{r['name']} failed to install (exit {p.returncode}). "
                 f"Nothing else attempted.")

SHARED.mkdir(parents=True, exist_ok=True)
REQ_UI.write_text(
    "# Installed into a UI product's own venv by run_test_suite.\n"
    "#\n"
    "# Generated tests run in products/<slug>/.venv, not in ducorn/.venv, so\n"
    "# installing playwright globally makes the PIPELINE able to drive a\n"
    "# browser and leaves the generated tests unable to. Both halves or the\n"
    "# UI gate stays decorative.\n"
    "pytest>=8.0\n"
    "playwright>=1.48\n", encoding="utf-8")
print(f"\nwrote {REQ_UI}")

print("\n── re-checking ─────────────────────────────────────────────────────")
again = subprocess.run([sys.executable, __file__])
if again.returncode != 0:
    sys.exit("still incomplete — see above")

print()
print("Browser is in place. Still to wire up, in order:")
print("  1. run_test_suite installs requirements-ui.txt for products with a UI")
print("  2. node_design screenshots each variant, gate 2 carries the images")
print("  3. the Web Interface Guidelines into skills 03 and 05")
