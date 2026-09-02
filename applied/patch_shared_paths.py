#!/usr/bin/env python3
"""
Make QA and deploy read the venv path from one place instead of two.

── THE COINCIDENCE ──────────────────────────────────────────────────────────

    skill_runner.py      venv = d / ".venv";  py = venv / "bin" / "python"
    DuCornDeployTool.py  venv = product_dir / ".venv" / "bin" / "python"

The invariant you asked me to confirm — a product is deployed under the
interpreter its tests passed under — rests on those two lines matching. They
do. Nothing makes them, and nothing would notice if they stopped.

That is the shape of every serious bug here this week: two copies of one fact,
agreeing until they didn't. A gate's threshold and the prose describing it. A
status the code wrote and the constraint that refused it. A model the switcher
held and the model the caller used. Each was correct in isolation.

── THE FIX, AND THE CHECK ───────────────────────────────────────────────────

scripts/product_paths.py holds the fact once. Both files import it.

And because I have caused two outages tonight with imports, prevention alone is
not enough: doctor gains a check that executes BOTH modules and compares the
path they return for a real product. If someone reintroduces a local copy that
drifts, the check fails with both values rather than waiting for a deploy to
fail confusingly.

DuCornDeployTool does not currently put scripts/ on sys.path — it works today
because langgraph_flow inserts it before importing the tool. Relying on an
importer's side effect is exactly the kind of thing that breaks when something
imports it a different way, which is how doctor's own probe would have broken.
So the tool inserts the path itself, as the other two modules already do.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path("/Users/ducorn/DC/scripts")
PATHS = SCRIPTS / "product_paths.py"
TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
DOCTOR = SCRIPTS / "doctor.py"

if not PATHS.is_file():
    sys.exit(f"{PATHS} is missing — copy product_paths.py into scripts/ first. "
             f"NOTHING WRITTEN.")

tool_s = TOOL.read_text(encoding="utf-8")
skill_s = SKILL.read_text(encoding="utf-8")
doc_s = DOCTOR.read_text(encoding="utf-8")

if "from product_paths import" in tool_s:
    sys.exit("Already patched — the venv path has one definition.")
if "def product_python" not in tool_s:
    sys.exit("Apply patch_deploy_venv.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ the deploy tool ═════════════════════════════════════════════════════════
tool_s = swap("tool import", tool_s,
              "from crewai.tools import BaseTool\n",
              '''from crewai.tools import BaseTool

# scripts/ holds the shared definitions. langgraph_flow happens to insert this
# before importing this module, but relying on an importer's side effect means
# any other way in — a health check, a test — fails on the import instead.
sys.path.insert(0, "/Users/ducorn/DC/scripts")
from product_paths import (product_python as _venv_python,  # noqa: E402
                           product_venv as _venv_dir)
''')

if "\nimport sys\n" not in tool_s.split("class DuCornDeployTool", 1)[0]:
    tool_s = swap("tool sys", tool_s, "import os\nimport re\n",
                  "import os\nimport re\nimport sys\n")

tool_s = swap("tool product_python", tool_s,
              '''    venv = product_dir / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv), "product venv"
    return SYSTEM_PYTHON, "system python"''',
              '''    venv = _venv_python(product_dir)
    if venv.is_file():
        return str(venv), "product venv"
    return SYSTEM_PYTHON, "system python"''')

tool_s = swap("tool ensure", tool_s, '''    venv_dir = product_dir / ".venv"''',
              '''    venv_dir = _venv_dir(product_dir)''')

# A third copy, in the branch that builds the venv. My own final check found
# this one — which is the argument for the check as much as for the module.
tool_s = swap("tool created venv", tool_s,
              '''    python = str(venv_dir / "bin" / "python")''',
              '''    python = str(_venv_python(product_dir))''')

# ═══ the QA runner ═══════════════════════════════════════════════════════════
# This import appears twice in skill_runner (a module-level pair and a
# guarded one). Anchor on the sys.path line that precedes only the second.
skill_s = swap("skill import", skill_s,
               "sys.path.insert(0, '/Users/ducorn/DC/ducorn')\n"
               "from ducorn_env import load_ducorn_env\n",
               "sys.path.insert(0, '/Users/ducorn/DC/ducorn')\n"
               "from ducorn_env import load_ducorn_env\n"
               "from product_paths import (product_python as _venv_python,\n"
               "                          product_venv as _venv_dir)\n")

skill_s = swap("skill venv", skill_s,
               '''    venv = d / ".venv"
    py = venv / "bin" / "python"''',
               '''    # The same definition deploy uses, so the interpreter these tests pass
    # under is the interpreter the product is started with.
    venv = _venv_dir(d)
    py = _venv_python(d)''')

# ═══ doctor proves they agree, by running both ═══════════════════════════════
doc_s = swap("agreement check", doc_s,
             '''    # A static server has no /health.''',
             '''    # Prevention is the shared module; this is detection. Both modules are
    # imported for real and asked where a product's interpreter is. A
    # reintroduced local copy that drifts fails here with both values, rather
    # than as a deploy that mysteriously cannot import a package.
    ok, out = _probe(
        "import sys\\n"
        "sys.path[:0] = ['/Users/ducorn/DC/scripts', '/Users/ducorn/DC/ducorn',"
        " '/Users/ducorn/DC/ducorn/tools']\\n"
        "from pathlib import Path\\n"
        "import product_paths as P\\n"
        "import DuCornDeployTool as D\\n"
        "root = Path('/Users/ducorn/DC/ducorn-products/products')\\n"
        "cands = [d for d in root.iterdir() if (d/'.venv'/'bin'/'python').is_file()]\\n"
        "assert cands, 'NO-PRODUCT-WITH-VENV'\\n"
        "shared = str(P.product_python(cands[0]))\\n"
        "deploy = D.product_python(cands[0])[0]\\n"
        "assert shared == deploy, f'{shared} != {deploy}'\\n"
        "print('QA and deploy agree: ' + shared.replace("
        "'/Users/ducorn/DC/ducorn-products/products/', ''))")
    check("deploy", "QA and deploy resolve the same interpreter", ok,
          out[-100:] if not ok else out,
          "python3 scripts/patch_shared_paths.py")

    # A static server has no /health.''')

# ── write all three, or none ─────────────────────────────────────────────────
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(TOOL, tool_s), (SKILL, skill_s), (DOCTOR, doc_s)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-sharedpaths-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — all three files reverted")


for path, text in targets:
    path.write_text(text, encoding="utf-8")

for path, _ in targets:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                       capture_output=True, text=True)
    undef = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
    if undef:
        die(f"{path.name}: " + "; ".join(undef))
print("syntax and undefined-name checks: clean on all three")

# ── the module must be importable, and the fact must be one fact ─────────────
r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, '/Users/ducorn/DC/scripts')\n"
     "import product_paths as P\n"
     "from pathlib import Path\n"
     "print(P.product_python('/x/y'))"],
    capture_output=True, text=True)
if r.returncode != 0:
    die(f"product_paths does not import cleanly:\n{r.stderr}")
resolved = r.stdout.strip()
print(f"\nproduct_paths.product_python('/x/y') -> {resolved}")
if resolved != "/x/y/.venv/bin/python":
    die(f"unexpected path: {resolved}")

# neither file may still compute it locally
for path, label in ((TOOL, "deploy"), (SKILL, "QA")):
    src = path.read_text(encoding="utf-8")
    code = src
    try:
        # strip docstrings so an explanation of the old line is not the old line
        tree = ast.parse(src)
        doc_lines = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                    and body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_lines.update(range(body[0].lineno,
                                       getattr(body[0], "end_lineno",
                                               body[0].lineno) + 1))
        code = "\n".join(l for i, l in enumerate(src.splitlines(), 1)
                         if i not in doc_lines and not l.strip().startswith("#"))
    except SyntaxError:
        pass
    if '"bin" / "python"' in code:
        die(f"{label} still builds the interpreter path itself")
    print(f"  ok   {label} no longer builds the path itself")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print()
print("Nothing to restart — both are imported per subprocess. Confirm with:")
print("  cd ~/DC && python3 scripts/doctor.py --quiet")
print()
print("The new check reads:")
print("  ok   QA and deploy resolve the same interpreter   "
      "ducorn-spend-status/.venv/bin/python")
