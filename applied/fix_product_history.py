#!/usr/bin/env python3
"""
Take the virtualenv out of the commit REX made, not just the one I made.

── WHY THE PUSH STILL FAILS ─────────────────────────────────────────────────

Amending fixed the commit at the top. The blob is one commit further down:

    e0725db  deploy: venv, multi-service, product URL ...   ← amended, clean
    5a4a5ae  deploy: venv, multi-service, product URL ...   ← clean
    6c7952f  feat(rex): ducorn-spend-status initial build   ← CARRIES 115 MB

6c7952f is the pipeline's own commit. node_build runs:

    git add products/{topic}/ && git commit -m 'feat(rex): ...' && git push

and at that moment products/ducorn-spend-status/.venv had already been built
by QA. So REX committed 201 MB of pip output, and git refuses the push because
one file inside playwright is 115 MB — over GitHub's hard limit. A later commit
deleting it changes nothing: the push carries every object in the history it
sends, including ones already deleted.

All three commits are unpushed, which makes this simple. They are collapsed
into one clean commit against origin/main. Nothing published is rewritten and
no file on disk is touched — the deployed product keeps running off the venv it
is running off right now.

── WHAT THIS DOES NOT DO ────────────────────────────────────────────────────

origin/main already carries 1,323 .venv files — ducorn-run-history's, at 43 MB,
small enough that it pushed cleanly some time ago. Removing those means
rewriting history that other clones may already have, and that is a decision
with consequences rather than a cleanup. This script leaves them alone and
tells you they are there.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/ducorn/DC/ducorn-products")
UPSTREAM = "origin/main"
LIMIT_MB = 50
MESSAGE = ("deploy: venv, multi-service, product URL; QA feedback loop; "
           "doc isolation; ducorn-spend-status")


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr}")
    return r


lock = REPO / ".git" / "index.lock"
if lock.exists():
    sys.exit(f"A stale lock is in the way:\n  rm -f {lock}")

if ".venv/" not in (REPO / ".gitignore").read_text(encoding="utf-8"):
    sys.exit("Run fix_venv_in_git.py first — .gitignore must exclude .venv/ "
             "or the recommit puts it straight back.")

unpushed = [l for l in git("log", "--oneline",
                           f"{UPSTREAM}..HEAD").stdout.splitlines() if l.strip()]
if not unpushed:
    sys.exit("Nothing unpushed — there is nothing here to repair.")

print(f"{len(unpushed)} unpushed commit(s) will become one:")
for line in unpushed:
    print(f"  {line}")

# Anything on the remote is not ours to rewrite. Confirm every commit we are
# about to collapse is genuinely local.
if git("rev-list", "--count", f"{UPSTREAM}..HEAD").stdout.strip() != str(len(unpushed)):
    sys.exit("commit count disagrees with the log — refusing to rewrite.")

before = git("rev-parse", "HEAD").stdout.strip()
print(f"\nHEAD before: {before[:12]}")
print(f"(if anything goes wrong: git -C {REPO} reset --hard {before[:12]})")

# --soft: history moves, the index and every file on disk stay exactly as they
# are. The deployed product does not notice.
git("reset", "--soft", UPSTREAM)

tracked = git("ls-files").stdout.splitlines()
bad = [p for p in tracked
       if "/.venv/" in p or p.startswith(".venv/")
       or "/node_modules/" in p or "/.pytest_cache/" in p]
if bad:
    print(f"\nremoving {len(bad):,} virtualenv/cache files from the index")
    for chunk in (bad[i:i + 500] for i in range(0, len(bad), 500)):
        git("rm", "-r", "--cached", "-q", "--", *chunk)

staged = git("diff", "--cached", "--name-only").stdout.splitlines()
if not staged:
    sys.exit("Nothing staged after the reset — refusing to make an empty "
             f"commit. Restore with: git reset --hard {before[:12]}")

git("commit", "-q", "-m", MESSAGE)
head = git("rev-parse", "--short", "HEAD").stdout.strip()
print(f"✅ one commit: {head}  ({len(staged):,} files)")

# ── prove the push will be accepted ──────────────────────────────────────────
print("\nchecking every object this push would carry:")
oversized = []
for commit in git("rev-list", f"{UPSTREAM}..HEAD").stdout.split():
    for line in git("ls-tree", "-r", "-l", commit).stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5 or not parts[3].isdigit():
            continue
        mb = int(parts[3]) / 1e6
        if mb > LIMIT_MB:
            oversized.append((mb, parts[4], commit[:8]))

if oversized:
    for mb, name, c in sorted(oversized, reverse=True)[:10]:
        print(f"  ❌ {mb:7.1f} MB  {name}  (in {c})")
    sys.exit(f"\nStill oversized. Restore with: git reset --hard {before[:12]}")

venvs = [p for p in git("ls-files").stdout.splitlines() if "/.venv/" in p]
print(f"  ok   no object over {LIMIT_MB} MB in any commit being pushed")
print(f"  ok   {len(venvs)} virtualenv files tracked at HEAD")

remote_venvs = len([p for p in git("ls-tree", "-r", UPSTREAM, "--name-only").stdout
                    .splitlines() if "/.venv/" in p])
if remote_venvs:
    print(f"\n⚠️  {remote_venvs:,} .venv files are already on origin/main from an "
          f"older push (ducorn-run-history, ~43 MB). Small enough that GitHub "
          f"accepted them. Removing those rewrites published history — say so "
          f"and I will, but it is not a cleanup, it is a force-push.")

print(f"""
Now push:
  git -C {REPO} push
""")
