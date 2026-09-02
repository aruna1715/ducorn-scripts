#!/usr/bin/env python3
"""
Fix doctor.py's own NameError, and widen the check that failed to catch it.

── WHAT I DID ───────────────────────────────────────────────────────────────

    File "/Users/ducorn/DC/scripts/doctor.py", line 260
        tree = ast.parse(source)
    NameError: name 'ast' is not defined

In the file whose new section exists to catch NameErrors at import. Twice in
one evening, in the checker for the thing itself.

── WHY MY OWN TEST PASSED ───────────────────────────────────────────────────

    ns = {"ast": ast}
    exec(seg["unbound_at_module_level"], ns)

The test handed the function the exact name that was missing from the module.
It proved the logic was right and said nothing about whether doctor.py could
run it. A test that supplies the missing dependency cannot fail the way
production does — the namespace has to come from the file, not from me.

── AND WHY THE AUDIT COULD NOT HAVE CAUGHT IT ───────────────────────────────

unbound_at_module_level looks for MODULE-LEVEL statements using a name that is
only imported inside a function. That was the activity API's bug exactly. This
one is different in shape: `ast` is used inside a function and imported
nowhere at all. The audit is not looking there, and widening it by hand means
writing a scope resolver — module scope, function scope, comprehensions,
except-as, with-as, global and nonlocal — and every mistake in it becomes a
false alarm that teaches you to ignore doctor.

pyflakes already is that resolver, and it is not mine. On the two shapes:

    probe.py:3:12: undefined name 'ast'    ← the one I just made
    probe.py:4:7:  undefined name 're'     ← the one that killed the API

So check_imports uses pyflakes when it is available, filtered to undefined
names only — "imported but unused" is style, and a checker that reports style
is a checker people stop reading. When pyflakes is absent it falls back to the
narrow AST audit and says so, because a check that quietly does less than it
claims is worse than one that admits it.

── AND THIS TIME THE VERIFICATION RUNS THE FILE ─────────────────────────────

Not a namespace I assembled. pyflakes is run against the patched doctor.py
itself, and the patch reverts if a single undefined name remains. The tool
proving it is one I did not write and cannot accidentally accommodate.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DOCTOR = Path("/Users/ducorn/DC/scripts/doctor.py")
s = DOCTOR.read_text(encoding="utf-8")

if "def _undefined_names" in s:
    sys.exit("Already patched — undefined names are caught by pyflakes.")
if "def check_imports" not in s:
    sys.exit("Apply patch_doctor_proof.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the import that was missing ───────────────────────────────────────────
if "\nimport ast\n" not in s.split("results = []", 1)[0]:
    s = swap("import ast", s, "import argparse\n", "import argparse\nimport ast\n")

# ── 2. use a scope resolver written by someone else ──────────────────────────
s = swap("undefined names", s, "def check_imports():",
         '''def _undefined_names(path):
    """
    Every name this file uses that nothing defines, via pyflakes.

    Returns (findings, how). `how` says which check actually ran, because a
    fallback that silently does less than the real thing is how you end up
    trusting a tick that means nothing.

    Filtered to undefined names on purpose. pyflakes also reports unused
    imports and shadowed variables; those are style, and a health check that
    reports style gets skimmed and then ignored.
    """
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        return [f"line {ln}: {nm!r}"
                for ln, nm in unbound_at_module_level(
                    path.read_text(encoding="utf-8"))], "module-level only"

    r = run([sys.executable, "-m", "pyflakes", str(path)])
    out = r.stdout + r.stderr
    findings = [l.split(":", 1)[1].strip() if ":" in l else l
                for l in out.splitlines() if "undefined name" in l]
    return findings, "pyflakes"


def check_imports():''')

s = swap("use it", s, '''        try:
            hits = unbound_at_module_level(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            check("imports", path.name, False, f"SyntaxError: {e}",
                  f"the file does not parse: {path}")
            continue
        detail = ", ".join(f"line {ln} uses {nm!r}" for ln, nm in hits)
        check("imports", path.name, not hits, detail,
              f"add a module-level import to {path}" if hits else None)''',
         '''        try:
            hits, how = _undefined_names(path)
        except SyntaxError as e:
            check("imports", path.name, False, f"SyntaxError: {e}",
                  f"the file does not parse: {path}")
            continue
        detail = "; ".join(hits) if hits else (
            "" if how == "pyflakes" else "(module-level check only)")
        check("imports", path.name, not hits, detail,
              f"add the missing import to {path}" if hits else None)

    if not _HAVE_PYFLAKES:
        print("       pyflakes is not installed — only module-level uses are "
              "checked.\\n       pip3 install pyflakes --break-system-packages",
              flush=True)''')

s = swap("have flag", s, "def _undefined_names(path):",
         '''try:
    import pyflakes as _pyflakes  # noqa: F401
    _HAVE_PYFLAKES = True
except ImportError:
    _HAVE_PYFLAKES = False


def _undefined_names(path):''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = DOCTOR.with_name(f"doctor.backup-undefined-{stamp}.py")
shutil.copy2(DOCTOR, backup)
DOCTOR.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, DOCTOR)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

# ── verify with a tool I did not write, against the real file ────────────────
have = subprocess.run([sys.executable, "-c", "import pyflakes"],
                      capture_output=True).returncode == 0
if not have:
    print("installing pyflakes so this can be verified properly")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyflakes",
                    "--break-system-packages"], capture_output=True)
    have = subprocess.run([sys.executable, "-c", "import pyflakes"],
                          capture_output=True).returncode == 0
if not have:
    die("pyflakes could not be installed — refusing to claim this is verified")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(DOCTOR)],
                   capture_output=True, text=True)
undefined = [l for l in (r.stdout + r.stderr).splitlines()
             if "undefined name" in l]
print("\npyflakes on the patched doctor.py:")
if undefined:
    for l in undefined:
        print(f"  ❌ {l}")
    die("doctor.py still uses a name nothing defines")
print("  ok   no undefined names")

# and it must still catch both shapes — checked by running the file, not by
# exec'ing a fragment into a namespace I built
import tempfile
probe = Path(tempfile.mkdtemp()) / "probe.py"
probe.write_text(
    "import argparse\n"
    "def f():\n"
    "    return ast.parse('x')\n"          # imported nowhere — tonight's bug
    "_RE = re.compile('y')\n"              # module-level, re local to g()
    "def g():\n"
    "    import re\n"
    "    return re\n", encoding="utf-8")
r = subprocess.run([sys.executable, "-m", "pyflakes", str(probe)],
                   capture_output=True, text=True)
found = [l.split(":", 3)[-1].strip() for l in (r.stdout + r.stderr).splitlines()
         if "undefined name" in l]
print("\nboth failure shapes, on a file that has both:")
for want, why in [("undefined name 'ast'", "used in a function, imported nowhere"),
                  ("undefined name 're'", "module level, imported only in a function")]:
    hit = any(want in f for f in found)
    print(f"  {'ok  ' if hit else 'FAIL'} {want:26} {why}")
    if not hit:
        die(f"the check does not find {want}")

# a clean file must be quiet, or the section is noise
clean = probe.with_name("clean.py")
clean.write_text("import ast\nimport re\n_RE = re.compile('y')\n"
                 "def f():\n    return ast.parse('x')\n", encoding="utf-8")
r = subprocess.run([sys.executable, "-m", "pyflakes", str(clean)],
                   capture_output=True, text=True)
noise = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
print(f"  {'ok  ' if not noise else 'FAIL'} a correct file reports nothing")
if noise:
    die("false positives on a clean file")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("If pyflakes is not on the machine doctor runs under, install it once —")
print("otherwise the imports section quietly does less and says so:")
print("  pip3 install pyflakes --break-system-packages")
print()
print("  cd ~/DC && python3 scripts/doctor.py")
