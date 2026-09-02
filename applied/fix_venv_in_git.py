#!/usr/bin/env python3
"""
Keep product virtualenvs out of git. They are already in the last commit.

── WHAT THE PUSH TOLD YOU ───────────────────────────────────────────────────

    remote: error: File products/ducorn-spend-status/.venv/lib/python3.12/
            site-packages/playwright/driver/node is 115.35 MB;
            this exceeds GitHub's file size limit

Commit bef0427 contains 201 MB of ducorn-spend-status/.venv, plus 43 MB of
ducorn-run-history/.venv. 244 MB of installed packages, committed as source.

.gitignore covers __pycache__, *.pyc, .DS_Store and the patch backups. It has
never covered .venv, because until tonight no product had one that mattered:
QA created it, nothing else touched it, and no product with real dependencies
had ever been committed after a QA run.

This is not a historical problem. Every future product gets a venv — QA builds
it to run the tests, and deploy now runs the product from it. So every future
product would arrive in git carrying a few hundred megabytes of pip output,
and every push would fail the same way.

── WHAT THIS DOES ───────────────────────────────────────────────────────────

1. Adds .venv/, node_modules/ and the usual build detritus to .gitignore.
2. Removes them from the index — `git rm -r --cached`, so the files stay
   exactly where they are on disk and the product keeps working.
3. Amends the commit, because it has not been pushed. Amending keeps the blobs
   out of history entirely; a follow-up commit would leave 201 MB in the object
   store forever and the push would still fail.
4. Refuses to finish if anything over 50 MB is still staged.

Nothing here pushes. Look at the result, then push yourself.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/ducorn/DC/ducorn-products")
LIMIT_MB = 50

IGNORE = """
# ── Virtualenvs and installed packages ───────────────────────────────────────
# QA builds <product>/.venv to run the product's tests and deploy runs the
# product from it, so every product has one. They are pip output, not source:
# 244 MB across two products, and one file inside playwright is 115 MB, which
# is over GitHub's hard limit. requirements.txt is the thing worth versioning.
.venv/
venv/
node_modules/
*.egg-info/
.pytest_cache/
"""


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr}")
    return r


lock = REPO / ".git" / "index.lock"
if lock.exists():
    sys.exit(f"A stale {lock} is in the way. Remove it and re-run:\n"
             f"  rm -f {lock}")

gi = REPO / ".gitignore"
text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
if ".venv/" in text:
    print(".gitignore already covers .venv/")
else:
    gi.write_text(text.rstrip("\n") + "\n" + IGNORE, encoding="utf-8")
    print("✅ .gitignore now covers .venv/, node_modules/ and friends")

# What is actually tracked that should not be?
tracked = git("ls-files").stdout.splitlines()
bad = [p for p in tracked
       if "/.venv/" in p or p.startswith(".venv/")
       or "/node_modules/" in p or "/.pytest_cache/" in p]

if not bad:
    print("nothing unwanted is tracked — nothing to remove")
else:
    print(f"\n{len(bad):,} tracked files belong to a virtualenv or a cache.")
    for p in bad[:5]:
        print(f"  {p}")
    if len(bad) > 5:
        print(f"  … and {len(bad) - 5:,} more")

    # --cached: the index only. Every one of these files stays on disk, so the
    # deployed product keeps running off the venv it is running off now.
    for chunk in (bad[i:i + 500] for i in range(0, len(bad), 500)):
        git("rm", "-r", "--cached", "-q", "--", *chunk)
    print(f"\n✅ removed {len(bad):,} files from the index (all still on disk)")

    head = git("log", "-1", "--pretty=%H %s").stdout.strip()
    print(f"\namending: {head}")
    git("commit", "--amend", "--no-edit", "-q")
    print(f"✅ amended to {git('rev-parse', '--short', 'HEAD').stdout.strip()}")

# ── prove it ─────────────────────────────────────────────────────────────────
print("\nchecking what the commit now weighs:")
oversized = []
for line in git("ls-tree", "-r", "-l", "HEAD").stdout.splitlines():
    parts = line.split(None, 4)
    if len(parts) < 5 or not parts[3].isdigit():
        continue
    mb = int(parts[3]) / 1e6
    if mb > LIMIT_MB:
        oversized.append((mb, parts[4]))

if oversized:
    for mb, name in sorted(oversized, reverse=True)[:10]:
        print(f"  ❌ {mb:7.1f} MB  {name}")
    sys.exit("\nSomething over the limit is still committed — do NOT push yet.")

still = [p for p in git("ls-files").stdout.splitlines() if "/.venv/" in p]
if still:
    sys.exit(f"\n{len(still)} venv files are still tracked — do NOT push yet.")

print(f"  ok   no tracked file exceeds {LIMIT_MB} MB")
print("  ok   no virtualenv file is tracked")
print(f"  ok   HEAD is {git('rev-parse', '--short', 'HEAD').stdout.strip()}, "
      f"{len(git('ls-files').stdout.splitlines()):,} files")

print("""
Now push:
  git -C ~/DC/ducorn-products push

The other two repos failed for a different reason — ducorn and scripts have no
upstream set. Once their remotes exist:
  git -C ~/DC/ducorn push -u origin master
  git -C ~/DC/scripts push -u origin master
""")
