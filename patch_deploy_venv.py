#!/usr/bin/env python3
"""
Deploy the product with the interpreter it was built and tested against.

── WHY THE API DIED AT EXIT 256 ─────────────────────────────────────────────

    File ".../ducorn-spend-status/api/main.py", line 21, in <module>
        import asyncpg
    ModuleNotFoundError: No module named 'asyncpg'

asyncpg is installed. It is right there:

    products/ducorn-spend-status/.venv/lib/python3.12/site-packages/
        asyncpg/
        asyncpg-0.29.0.dist-info/
        fastapi/  uvicorn/  ...

REX declared it in requirements.txt, the product's venv has it pinned at the
requested 0.29.0, and IRIS ran 41 tests against that venv and passed them.
Then the deploy tool wrote this into the plist:

    program_args = ["/opt/homebrew/bin/python3.12", "-m", "uvicorn", ...]

The system interpreter. Not the product's. So every dependency the product
declares, installs, and is tested with is invisible the moment it is deployed —
and the failure arrives as a launchd exit code and a stack trace tail, twenty
seconds later, rather than as "this product's environment is not the one you
are starting it in".

This is the same shape as everything else this week: QA validated one thing
and deploy ran another. The venv exists, is correct, and nothing reached for
it. It has been true of every product with a third-party dependency; the ones
that deployed before were static pages and a hello-world.

── THE FIX ──────────────────────────────────────────────────────────────────

1. A product with a .venv is started with that .venv's python. It is the
   interpreter its tests passed under, which is the only interpreter its
   passing tests say anything about.

2. A product with requirements.txt and no .venv gets one, built at deploy
   time. Deploying a product whose dependencies were never installed is not a
   deployment.

3. Before launchd is touched, the app module is imported once with the chosen
   interpreter. A ModuleNotFoundError here is answered by installing
   requirements.txt and trying once more — and if it still fails, the deploy
   stops with the actual import error and the actual interpreter path, in the
   first second rather than after a smoke-test timeout.

The preflight is the part worth keeping. `launchctl` reporting exit 256 tells
you a process died; importing the module yourself tells you why, before
anything is registered.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
s = TOOL.read_text(encoding="utf-8")

if "def product_python" in s:
    sys.exit("Already patched — products deploy with their own interpreter.")
if "def plan_services" not in s:
    sys.exit("Apply patch_deploy_services.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new, count=1):
    if text.count(old) != count:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected "
                 f"{count}. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, count)


# ── the interpreter, and how to be sure it works ─────────────────────────────
s = swap("helpers", s, "def _used_ports() -> set:",
         '''SYSTEM_PYTHON = "/opt/homebrew/bin/python3.12"


def product_python(product_dir: Path) -> tuple:
    """
    The interpreter this product was built and tested against.

    A product's .venv is not an implementation detail — it is where its
    declared dependencies actually are. Starting it with the system python
    instead means requirements.txt described an environment nobody ever runs.
    """
    venv = product_dir / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv), "product venv"
    return SYSTEM_PYTHON, "system python"


def install_requirements(python: str, product_dir: Path) -> tuple:
    """pip install -r requirements.txt with the given interpreter."""
    req = product_dir / "requirements.txt"
    if not req.is_file():
        return False, "no requirements.txt"
    print(f"📦 installing {req.name} into {python}", flush=True)
    r = subprocess.run([python, "-m", "pip", "install", "-q", "-r", str(req)],
                       capture_output=True, text=True, cwd=str(product_dir))
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[-500:]
    return True, "installed"


def ensure_product_python(product_dir: Path) -> tuple:
    """
    Give the product an interpreter that has its dependencies.

    Builds the venv when requirements.txt exists and .venv does not — a
    product whose dependencies were never installed is not deployable, and
    discovering that from a launchd exit code is the slow way to find out.
    """
    python, how = product_python(product_dir)
    if how == "product venv" or not (product_dir / "requirements.txt").is_file():
        return python, how

    venv_dir = product_dir / ".venv"
    print(f"📦 no venv for {product_dir.name} — creating one", flush=True)
    r = subprocess.run([SYSTEM_PYTHON, "-m", "venv", str(venv_dir)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return python, f"system python (venv creation failed: {r.stderr[-200:]})"
    python = str(venv_dir / "bin" / "python")
    ok, detail = install_requirements(python, product_dir)
    return python, ("product venv (created)" if ok
                    else f"product venv (install failed: {detail})")


def preflight_import(python: str, product_dir: Path, module: str) -> tuple:
    """
    Import the app module before launchd ever sees it.

    launchctl says a process exited 256. This says which import failed, with
    which interpreter, in about a second — and lets one missing dependency be
    repaired rather than reported.
    """
    r = subprocess.run([python, "-c", f"import {module}"],
                       capture_output=True, text=True, cwd=str(product_dir))
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr or r.stdout).strip()[-700:]


def _used_ports() -> set:''')

# ── plan_services takes the interpreter rather than assuming one ─────────────
s = swap("planner signature", s,
         '''def plan_services(slug: str, product_dir: Path, product_type: str,
                  entry_point: str, first_port: int) -> list:''',
         '''def plan_services(slug: str, product_dir: Path, product_type: str,
                  entry_point: str, first_port: int,
                  python: str = SYSTEM_PYTHON) -> list:''')

s = swap("api interpreter", s,
         '''            "args": ["/opt/homebrew/bin/python3.12", "-m", "uvicorn",
                     api_module, "--host", "0.0.0.0", "--port", str(first_port)],''',
         '''            "args": [python, "-m", "uvicorn",
                     api_module, "--host", "0.0.0.0", "--port", str(first_port)],
            "module": api_module.split(":")[0],''')

s = swap("web interpreter", s,
         '''            "args": ["/opt/homebrew/bin/python3.12", "-m", "http.server",
                     str(page_port), "--directory", str(product_dir)],''',
         '''            "args": [python, "-m", "http.server",
                     str(page_port), "--directory", str(product_dir)],''')

s = swap("script interpreter", s,
         '''            "args": ["/opt/homebrew/bin/python3.12", str(product_dir / ep)],''',
         '''            "args": [python, str(product_dir / ep)],''')

# ── and _run resolves it, then proves it before registering anything ─────────
s = swap("resolve", s, '''            services = plan_services(slug, product_dir, product_type,
                                     entry_point, port)''',
         '''            python, how = ensure_product_python(product_dir)
            print(f"🐍 {slug}: {how} — {python}", flush=True)

            services = plan_services(slug, product_dir, product_type,
                                     entry_point, port, python)''')

s = swap("preflight", s, '''            LAUNCHD_DIR.mkdir(exist_ok=True)
            started = []''',
         '''            # Import it here, before launchd is involved. This is where
            # `ModuleNotFoundError: No module named 'asyncpg'` belongs — with
            # the interpreter named — not in a log tail after a 20s timeout.
            for spec in services:
                if not spec.get("module"):
                    continue
                ok, err = preflight_import(python, product_dir, spec["module"])
                if not ok and "ModuleNotFoundError" in err:
                    installed, detail = install_requirements(python, product_dir)
                    if installed:
                        ok, err = preflight_import(python, product_dir,
                                                   spec["module"])
                if not ok:
                    return (
                        f"❌ Deploy aborted — {spec['module']} cannot be "
                        f"imported by the interpreter it would run under.\\n"
                        f"Interpreter: {python} ({how})\\n"
                        f"Product:     {product_dir}\\n\\n{err}\\n\\n"
                        "If a package is missing, add it to requirements.txt "
                        "and redeploy — the deployer installs it into the "
                        "product's own venv.")
                print(f"✅ {spec['module']} imports cleanly", flush=True)

            LAUNCHD_DIR.mkdir(exist_ok=True)
            started = []''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = TOOL.with_name(f"DuCornDeployTool.backup-venv-{stamp}.py")
shutil.copy2(TOOL, backup)
TOOL.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, TOOL)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

src = TOOL.read_text(encoding="utf-8")
if "/opt/homebrew/bin/python3.12" in src.split("SYSTEM_PYTHON =", 1)[1]:
    leftovers = [l.strip() for l in src.splitlines()
                 if "/opt/homebrew/bin/python3.12" in l and "SYSTEM_PYTHON" not in l]
    if leftovers:
        die("a hardcoded interpreter survived: " + " | ".join(leftovers))

t = ast.parse(src)
seg = {n.name: ast.get_source_segment(src, n) for n in t.body
       if isinstance(n, ast.FunctionDef)}
for need in ("product_python", "ensure_product_python", "preflight_import",
             "plan_services"):
    if need not in seg:
        die(f"{need} did not land")

# ── exercise it, including against this machine's real venv layout ───────────
import tempfile
ns = {"Path": Path, "SYSTEM_PYTHON": "/opt/homebrew/bin/python3.12"}
exec(seg["product_python"], ns)
pp = ns["product_python"]

root = Path(tempfile.mkdtemp())
withvenv = root / "withvenv"
(withvenv / ".venv" / "bin").mkdir(parents=True)
(withvenv / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
bare = root / "bare"
bare.mkdir()

print("\nwhich interpreter starts the product:")
for d, want_how in [(withvenv, "product venv"), (bare, "system python")]:
    got_py, got_how = pp(d)
    ok = got_how == want_how
    print(f"  {'ok  ' if ok else 'FAIL'} {d.name:10} → {got_how:14} {got_py}")
    if not ok:
        die(f"{d.name}: expected {want_how}, got {got_how}")

ns2 = {"Path": Path, "SYSTEM_PYTHON": "/opt/homebrew/bin/python3.12",
       "PORT_REGISTRY": {}, "re": __import__("re"),
       "_used_ports": lambda: set(), "_free_port": lambda a, b: a}
exec(seg["plan_services"], ns2)
both = root / "both"
(both / "api").mkdir(parents=True)
(both / "api" / "main.py").write_text("from fastapi import FastAPI\napp=FastAPI()")
(both / "index.html").write_text("<h1>x</h1>")
svcs = ns2["plan_services"]("zz", both, "dashboard", "main.py", 8090,
                            "/products/zz/.venv/bin/python")
print("\nthe interpreter reaches the launchd arguments:")
for sp in svcs:
    print(f"  {sp['role']:8} {sp['args'][0]}")
    if sp["args"][0] != "/products/zz/.venv/bin/python":
        die(f"{sp['role']} still starts with the wrong interpreter")
if svcs[0].get("module") != "api.main":
    die(f"the API service must name its module for preflight; got "
        f"{svcs[0].get('module')!r}")
print(f"  ok   the API service carries module={svcs[0]['module']!r} for preflight")

# preflight, for real, in this container
ns3 = {"subprocess": __import__("subprocess"), "Path": Path}
exec(seg["preflight_import"], ns3)
pre = ns3["preflight_import"]
good_ok, _ = pre(sys.executable, Path(tempfile.gettempdir()), "json")
bad_ok, bad_err = pre(sys.executable, Path(tempfile.gettempdir()),
                      "a_module_that_is_not_installed_anywhere")
print("\npreflight actually runs the interpreter:")
print(f"  ok   import json → {good_ok}")
print(f"  ok   missing module → {bad_ok}, "
      f"{'ModuleNotFoundError' in bad_err and 'reports ModuleNotFoundError' or bad_err[:40]}")
if not good_ok or bad_ok or "ModuleNotFoundError" not in bad_err:
    die("preflight does not distinguish an importable module from a missing one")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Nothing to restart. Re-run the deploy:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase deploy --engine gstack --coder crewai "
      "--complexity simple")
print()
print("Expect:  🐍 ducorn-spend-status: product venv — .../.venv/bin/python")
print("         ✅ api.main imports cleanly")
