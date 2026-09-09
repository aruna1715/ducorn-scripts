#!/usr/bin/env python3
"""
The secret check blocks .env.example, which is a required deliverable.

    cd ~/DC && python3 scripts/patch_commit_env_template.py            show
    cd ~/DC && python3 scripts/patch_commit_env_template.py --apply    do it

Needs scripts/patchlib.py.

── WHAT HAPPENED ────────────────────────────────────────────────────────────

    ⛔ REFUSING — these look like secrets:
         products/ducorn-admin-rebuild/.env.example
       Add them to .gitignore, then run this again.

The file:

    UI_USERNAME=
    UI_PASSWORD=
    ENV_FILE_PATH=
    # ADMIN_PORT=8099

Every value empty or commented. It is the reference REX is required to ship,
DuCornDeployTool.resolve_product_env READS it to resolve a product's
environment, and doctor has a check named "a shipped .env.example default is
honoured". Following the advice in that message — gitignore it — would break
the deploy path and leave a fresh clone unable to run the product.

── THE CAUSE ────────────────────────────────────────────────────────────────

    SECRET = re.compile(r"(^|/)\\.env($|\\.)|\\.pem$|...")

`(^|/)\\.env($|\\.)` matches .env AND .env.anything, so every template in the
family is refused by its NAME. The risk in a .env file is its VALUES; the
name only suggests where to look.

── THE FIX ──────────────────────────────────────────────────────────────────

For a .env-family file, read it. If no line assigns a non-empty value it is a
template and may be committed; if any does, it is refused AND the offending
KEY NAMES are printed, which is more useful than the filename alone and still
prints no values.

Everything else the pattern catches — .pem, id_rsa, secret.json — is refused
by name as before. "It has no values" is not a statement you can make about a
private key.

A file that cannot be read is refused. Being unable to prove a file is safe
is not the same as proving it is.

Both check sites use the same function: the pre-stage list and the
post-stage re-check, which exists because .gitignore decides what actually
lands. Two copies of this rule would drift, and the post-stage one is the
one that matters.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
CA = DC / "scripts" / "commit_all.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "envtemplate"

HELPER = '''

# A .env-family name says where to look, not what is there. The risk is
# VALUES.
#
# `(^|/)\\.env($|\\.)` matches .env.example too, so this refused the
# environment reference every product is required to ship — the one
# DuCornDeployTool.resolve_product_env reads, and that doctor checks. The
# advice printed with the refusal was to gitignore it, which would have
# broken the deploy path.
ENVISH = re.compile(r"(^|/)\\.env($|\\.)", re.I)


def _assigned_keys(repo, f):
    """
    Keys given a non-empty value in a .env-family file.

    [] means it is a template and may be committed. A file that cannot be
    read returns a sentinel: being unable to prove a file is safe is not the
    same as proving it is.
    """
    try:
        text = (DC / repo / f).read_text(errors="replace")
    except OSError:
        return ["<unreadable>"]
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if v.strip().strip('"').strip("'"):
            out.append(k.strip())
    return out


def blocking(repo, files):
    """
    (blocked, templates, why) for a list of paths.

    One function, both call sites — the list before staging and the re-check
    after it. The post-stage one is the check that matters, because
    .gitignore decides what actually lands, and a second copy of this rule
    would be the one that drifts.
    """
    blocked, templates, why = [], [], {}
    for f in files:
        if not SECRET.search(f):
            continue
        if ENVISH.search(f):
            keys = _assigned_keys(repo, f)
            if not keys:
                templates.append(f)
                continue
            why[f] = f"{len(keys)} key(s) carry values: {', '.join(keys[:4])}"
        blocked.append(f)
    return blocked, templates, why

'''

OLD_PRE = '''        secrets = [f for f in files if SECRET.search(f)]
        if secrets:
            blocked.append((repo, secrets))
            print(f"  ⛔ REFUSING — these look like secrets:")
            for f in secrets:
                print(f"       {f}")
            print("     Add them to .gitignore, then run this again.")
            continue'''

NEW_PRE = '''        secrets, templates, why = blocking(repo, files)
        for f in templates:
            print(f"  📄 {f} — a template, no values assigned; committing it")
        if secrets:
            blocked.append((repo, secrets))
            print(f"  ⛔ REFUSING — these look like secrets:")
            for f in secrets:
                print(f"       {f}"
                      + (f"  ({why[f]})" if f in why else ""))
            print("     Add them to .gitignore, then run this again.")
            continue'''

OLD_POST = '''        late = [f for f in staged if SECRET.search(f)]
        if late:'''

NEW_POST = '''        late, _tpl, _why = blocking(repo, staged)
        if late:'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (CA, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

src = CA.read_text(encoding="utf-8")
print("patch_commit_env_template\n")

if "def blocking(" in src:
    sys.exit("NOTHING DONE — commit_all already reads .env files.")

anchor = '''def git(repo, *args, check=False):'''
bad = False
for label, a in [("the pre-stage check", OLD_PRE),
                 ("the post-stage re-check", OLD_POST),
                 ("the insertion point", anchor)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(CA, CA.with_suffix(f".backup-{TAG}-{stamp}.py"))
out = src.replace(anchor, HELPER.strip() + "\n\n\n" + anchor, 1)
out = out.replace(OLD_PRE, NEW_PRE, 1).replace(OLD_POST, NEW_POST, 1)
CA.write_text(out, encoding="utf-8")
print(f"\nwrote {CA.name}, backup tagged {TAG}-{stamp}")

after = CA.read_text(encoding="utf-8")
try:
    py_ok(after, "commit_all.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# Scoped: BOTH sites must go through blocking(), or the post-stage check —
# the one that decides what actually lands — keeps the old rule.
uses = calls_in(after, "main", "blocking")
if len(uses) != 2:
    sys.exit(f"⚠️  main() calls blocking() {len(uses)} time(s), expected 2 "
             f"— restore the backup.")
print("verified: commit_all.py parses and both check sites call blocking().")

# The behaviour, on the two files that matter.
probe = r'''
import re
SECRET = re.compile(
    r"(^|/)\.env($|\.)|\.pem$|\.p12$|id_rsa|(^|/)[^/]*(secret|credential|token)"
    r"[^/]*\.(json|ya?ml|txt|env)$", re.I)
ENVISH = re.compile(r"(^|/)\.env($|\.)", re.I)
TEMPLATE = "# note\nUI_USERNAME=\nUI_PASSWORD=\n# ADMIN_PORT=8099\n"
REAL = "UI_USERNAME=admin\nUI_PASSWORD=hunter2\n"
def keys(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k, _, v = s.partition("=")
        if v.strip().strip('"').strip("'"): out.append(k.strip())
    return out
def blocked(path, text):
    if not SECRET.search(path): return False
    if ENVISH.search(path): return bool(keys(text))
    return True
bad = []
if blocked("products/x/.env.example", TEMPLATE):
    bad.append("a template .env.example is still refused")
if not blocked("products/x/.env", REAL):
    bad.append("a .env WITH VALUES is now allowed")
if not blocked("products/x/.env.example", REAL):
    bad.append("an .env.example carrying real values is allowed")
if not blocked("keys/id_rsa", ""):
    bad.append("a private key is now allowed")
if not blocked("conf/secret.json", ""):
    bad.append("a secret.json is now allowed")
if blocked("products/x/main.py", REAL):
    bad.append("an ordinary file is refused")
print("ENVCHK_OK" if not bad else "ENVCHK_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "ENVCHK_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")
print("          a template commits, a .env with values does not, and keys "
      "are still refused by name.")

print("""
  python3 scripts/commit_all.py --apply -m "phase 1 build"

.env.example should now commit with a line saying it is a template.
""")
