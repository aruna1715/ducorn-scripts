#!/usr/bin/env python3
"""
"Already patched" is a success. Sixty-four scripts report it as a failure.

    python3 scripts/fix_patch_exit_codes.py            show what would change
    python3 scripts/fix_patch_exit_codes.py --apply    change it

── THE PAPERCUT, WHICH I KEEP HANDING YOU ───────────────────────────────────

    cd ~/DC && sed -i '' ... shared/.env && python3 scripts/patch_doctor_budget.py \\
      && launchctl kickstart ... && python3 scripts/doctor.py --quiet

    DUCORN_DAILY_BUDGET=50.0
    Already patched — doctor asks the endpoint that decides.
    $

The budget was raised and the API was never restarted, because the patch had
already been applied and said so by exiting 1. Everything after the && was
skipped. The visible outcome was a command that looked like it worked.

Every one of these scripts is idempotent on purpose — you can run it twice and
it declines the second time. That is a designed success, and it should exit 0.
Reserving a non-zero exit for genuine problems is what makes chaining them
safe, and I have been chaining them all evening.

── WHAT CHANGES, AND WHAT DOES NOT ──────────────────────────────────────────

    sys.exit("Already patched — ...")   →  print(...); sys.exit(0)

Only that. These stay non-zero, because they are real refusals and stopping the
chain is exactly right:

    sys.exit("Apply patch_x.py first ...")     a prerequisite is missing
    sys.exit("ANCHOR MISS ...")                the file is not what was expected
    sys.exit("SYNTAX ERROR ... reverted")      it broke something and undid it

── VERIFICATION ─────────────────────────────────────────────────────────────

Each edited file is re-parsed, and then actually RUN — every one of these is
already applied on this machine, so running it must print its message and exit
0 without touching anything. A file that does something on the second run would
fail that, which is the property worth checking anyway.
"""
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path("/Users/ducorn/DC/scripts")
PATTERN = re.compile(
    r'^(?P<indent>[ \t]*)sys\.exit\((?P<f>f?)"(?P<msg>Already patched[^"]*)"\)[ \t]*$',
    re.M)

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--run", action="store_true",
                help="also run each edited script to prove it exits 0")
args = ap.parse_args()

targets = sorted(list(SCRIPTS.glob("*.py")) + list((SCRIPTS / "applied").glob("*.py")))
hits = []
for p in targets:
    try:
        src = p.read_text(encoding="utf-8")
    except OSError:
        continue
    found = PATTERN.findall(src)
    if found:
        hits.append((p, len(PATTERN.findall(src))))

print(f"{len(hits)} script(s) exit non-zero on a successful no-op\n")
for p, n in hits[:8]:
    rel = p.relative_to(SCRIPTS)
    print(f"  {str(rel):48} {n} guard(s)")
if len(hits) > 8:
    print(f"  … and {len(hits) - 8} more")

if not hits:
    sys.exit(0)
if not args.apply:
    print("\nRe-run with --apply.")
    sys.exit(0)

changed, failed = [], []
for p, _ in hits:
    src = p.read_text(encoding="utf-8")

    def repl(m):
        i, f, msg = m.group("indent"), m.group("f"), m.group("msg")
        # print, then exit 0: a designed no-op is a success and must not stop
        # a && chain.
        return (f'{i}print({f}"{msg}")\n'
                f'{i}sys.exit(0)')

    new = PATTERN.sub(repl, src)
    if new == src:
        continue
    try:
        ast.parse(new)
    except SyntaxError as e:
        failed.append((p, f"would not parse: {e}"))
        continue
    p.write_text(new, encoding="utf-8")
    changed.append(p)

print(f"\nrewrote {len(changed)} file(s)")
for p, why in failed:
    print(f"  SKIPPED {p.name}: {why}")

# ── they must still parse, and still decline ─────────────────────────────────
bad = []
for p in changed:
    r = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        bad.append((p, r.stderr.strip()[:120]))
if bad:
    for p, e in bad:
        print(f"  FAIL {p.name}: {e}")
    sys.exit(f"\n{len(bad)} file(s) no longer compile — restore them from git:\n"
             f"  git -C {SCRIPTS} checkout -- .")
print(f"  ok   all {len(changed)} still compile")

if args.run:
    # Every one of these is already applied here, so running it must print and
    # exit 0 without doing anything. A script that acts on a second run would
    # fail this, which is worth knowing regardless.
    print("\nrunning each one — they are all already applied, so each must "
          "decline and exit 0:")
    wrong = 0
    for p in changed:
        r = subprocess.run([sys.executable, str(p)], capture_output=True,
                           text=True, timeout=120)
        first = (r.stdout or r.stderr).strip().splitlines()
        first = first[0][:56] if first else "(no output)"
        ok = r.returncode == 0
        wrong += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {p.name:44} exit {r.returncode}  "
              f"{first}")
    if wrong:
        sys.exit(f"\n{wrong} script(s) still exit non-zero when declining.")
    print(f"\n  all {len(changed)} decline cleanly and exit 0")

print("""
Chained commands now behave:

  python3 scripts/patch_x.py && launchctl kickstart -k ... && doctor.py

A patch that has already been applied no longer swallows everything after it.""")
