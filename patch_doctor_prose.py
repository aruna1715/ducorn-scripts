#!/usr/bin/env python3
"""
Stop a check from failing because the fix is documented.

── THE FALSE POSITIVE ───────────────────────────────────────────────────────

    FAIL the smoke test tries each health path
         → python3 scripts/patch_deploy_services.py

patch_deploy_services.py IS applied — the check two lines above it proves so by
executing the real planner: "page+api -> api,web". The smoke test is fixed.

The check looks for the absence of the old buggy expression:

    "_probe(\\"/health\\") or _probe(\\"/\\")" not in src

and finds it at DuCornDeployTool.py:430 — inside the docstring of the very
function that fixed it:

    `_probe("/health") or _probe("/")`, and 404 is truthy — so the fallback
    never ran once...

So the check fails precisely because the repair is explained. Write a comment
about a bug and the health check reports the bug. That teaches people to
distrust doctor, which is worse than not having the check.

── THE CLASS, NOT THE INSTANCE ──────────────────────────────────────────────

Any check phrased as "this string is absent" has this defect: text matching
cannot tell code from prose about code. And these files are heavily commented,
deliberately, because the comments are how the reasoning survives.

Two changes:

1. _code_only(src) strips docstrings and comments before any absence check, so
   they see what runs rather than what is written about what runs.

2. The smoke check becomes a POSITIVE property, checked against the syntax tree
   rather than the text: does smoke() actually iterate spec["health"]? An
   absence proves nothing was reverted; a presence proves the behaviour is
   there. Prefer the second whenever it can be expressed.

── THE THIRD TIME TONIGHT ───────────────────────────────────────────────────

A test that supplied the missing import. A verification string that straddled a
line break. Now a grep that matched its own explanation. Every one of them was
the checking method rather than the fix — which is exactly the failure I have
spent the evening pointing at in the pipeline, arriving from the other side.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DOCTOR = Path("/Users/ducorn/DC/scripts/doctor.py")
s = DOCTOR.read_text(encoding="utf-8")

if "def _code_only" in s:
    sys.exit("Already patched — absence checks ignore prose.")
if "tries each health path" not in s:
    sys.exit("Apply patch_doctor_proof.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("code_only", s, "def check_deploy():",
         '''def _code_only(src: str) -> str:
    """
    The file with its docstrings and comments removed.

    Every "this string is absent" check needs this. These modules are heavily
    commented on purpose — the comments are how the reasoning survives — and a
    comment explaining a bug is not the bug. The smoke-test check failed
    because the docstring of the function that FIXED it quotes the expression
    it replaced.
    """
    import io
    import tokenize
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    doc_lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            first = body[0].lineno
            last = getattr(body[0], "end_lineno", first)
            doc_lines.update(range(first, last + 1))

    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.start[0] in doc_lines:
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        # Fall back to dropping docstring lines only. Better than pretending.
        return "\\n".join(l for i, l in enumerate(src.splitlines(), 1)
                          if i not in doc_lines)
    return " ".join(out)


def smoke_tries_every_path(tool_src: str) -> bool:
    """
    Does smoke() actually walk the candidate health paths?

    A positive property, read from the syntax tree. The old check asked whether
    a buggy expression was absent, which is both weaker — absence proves only
    that nobody typed it — and fragile, since prose about the bug reads as the
    bug.
    """
    try:
        tree = ast.parse(tool_src)
    except SyntaxError:
        return False
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "smoke"), None)
    if fn is None:
        return False
    for node in ast.walk(fn):
        if not isinstance(node, ast.For):
            continue
        it = node.iter
        if (isinstance(it, ast.Subscript)
                and isinstance(it.slice, ast.Constant)
                and it.slice.value == "health"):
            return True
    return False


def check_deploy():''')

s = swap("smoke check", s,
         '''    src = tool.read_text(encoding="utf-8")
    check("deploy", "the smoke test tries each health path",
          "_probe(\\"/health\\") or _probe(\\"/\\")" not in src
          and "def smoke(" in src,
          "" if "def smoke(" in src else "smoke() missing",
          "python3 scripts/patch_deploy_services.py")''',
         '''    src = tool.read_text(encoding="utf-8")
    check("deploy", "the smoke test tries each health path",
          smoke_tries_every_path(src),
          "" if "def smoke(" in src else "smoke() missing",
          "python3 scripts/patch_deploy_services.py")''')

# the remaining absence checks read code, not prose
s = swap("doc absence", s,
         '''    check("regressions", "a document is only served to its owner (wired)",
          "def doc_owner" in asrc and \'doc_path = f"{docs_dir}/{filename}"\' not in asrc,''',
         '''    check("regressions", "a document is only served to its owner (wired)",
          "def doc_owner" in asrc
          and \'doc_path = f"{docs_dir}/{filename}"\' not in _code_only(asrc),''')

s = swap("git absence", s,
         '''    check("regressions", "the build reports the push it actually made",
          "def _git_publish" in fsrc
          and "✅ Files committed to GitHub" not in fsrc,''',
         '''    check("regressions", "the build reports the push it actually made",
          "def _git_publish" in fsrc
          and "✅ Files committed to GitHub" not in _code_only(fsrc),''')

s = swap("ollama count", s,
         '''          and asrc.count("http://localhost:11434/api/generate") <= 1,
          f"{asrc.count(\'http://localhost:11434/api/generate\')} direct Ollama "
          f"call(s) left" if asrc else "",''',
         '''          and _code_only(asrc).count("http://localhost:11434/api/generate") <= 1,
          f"{_code_only(asrc).count(chr(104) + \'ttp://localhost:11434/api/generate\')}"
          f" direct Ollama call(s) left" if asrc else "",''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = DOCTOR.with_name(f"doctor.backup-prose-{stamp}.py")
shutil.copy2(DOCTOR, backup)
DOCTOR.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, DOCTOR)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

import subprocess
r = subprocess.run([sys.executable, "-m", "pyflakes", str(DOCTOR)],
                   capture_output=True, text=True)
if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
    die("doctor.py uses a name nothing defines:\\n" + r.stdout + r.stderr)

# ── run the new logic against the real file that triggered the false alarm ───
src = DOCTOR.read_text(encoding="utf-8")
t = ast.parse(src)
seg = {n.name: ast.get_source_segment(src, n) for n in t.body
       if isinstance(n, ast.FunctionDef)}
for need in ("_code_only", "smoke_tries_every_path"):
    if need not in seg:
        die(f"{need} did not land")

ns = {"ast": ast}
exec(seg["_code_only"], ns)
exec(seg["smoke_tries_every_path"], ns)
code_only, smoke_ok = ns["_code_only"], ns["smoke_tries_every_path"]

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
if not TOOL.is_file():
    die(f"{TOOL} not found — cannot verify against the real file")
tsrc = TOOL.read_text(encoding="utf-8")

print("\nagainst the real DuCornDeployTool.py:")
print(f"  ok   the old expression appears {tsrc.count(chr(96) + '_probe')} time(s) "
      f"in prose")
stripped = code_only(tsrc)
in_code = '_probe("/health") or _probe("/")' in stripped
print(f"  {'ok  ' if not in_code else 'FAIL'} "
      f"...and {'0' if not in_code else 'still'} times in code")
if in_code:
    die("the buggy expression is genuinely still in the code")
print(f"  {'ok  ' if smoke_ok(tsrc) else 'FAIL'} smoke() iterates spec['health'] "
      f"— the positive property")
if not smoke_ok(tsrc):
    die("smoke() does not walk the health paths")

# it must still fail on genuinely broken code
BROKEN = ('def smoke(spec):\n'
          '    """Tries /health then /."""\n'
          '    return _probe("/health") or _probe("/")\n')
print(f"  {'ok  ' if not smoke_ok(BROKEN) else 'FAIL'} and a smoke() that does "
      f"NOT loop still fails")
if smoke_ok(BROKEN):
    die("the positive check passes code that never loops")

# _code_only must not eat real code
sample = 'x = 1  # a comment\ndef f():\n    "doc"\n    return "kept"\n'
out = code_only(sample)
print(f"  {'ok  ' if 'kept' in out and 'a comment' not in out and 'doc' not in out else 'FAIL'}"
      f" comments and docstrings dropped, code kept")
if "kept" not in out or "a comment" in out or '"doc"' in out:
    die(f"_code_only mangled the source: {out!r}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("doctor re-execs under /opt/homebrew/bin/python3.12, so pyflakes must be")
print("installed THERE — not under the python that ran this patch:")
print("  /opt/homebrew/bin/python3.12 -m pip install pyflakes --break-system-packages")
print()
print("  cd ~/DC && python3 scripts/doctor.py")
