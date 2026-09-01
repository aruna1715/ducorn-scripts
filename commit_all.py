#!/usr/bin/env python3
"""
Commit and push every DuCorn repo in one go.

    python3 scripts/commit_all.py                       # what would happen
    python3 scripts/commit_all.py -m "message" --apply  # do it

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

`cd ~/DC && git add -A` fails with "not a git repository", because ~/DC is not
one. There are four, side by side:

    ~/DC/ducorn            the pipeline          NO REMOTE
    ~/DC/scripts           the tooling           NO REMOTE
    ~/DC/gstack            the skills            NO REMOTE
    ~/DC/ducorn-products   the products          github.com/aruna1715/ducorn-products
    ~/DC/shared            .env — not a repo, and should not be

So a single command at the top level commits nothing, which is how everything
written since 31 August ended up uncommitted: eight modified files in ducorn,
twenty-eight in scripts.

The more serious half is the second column. Three of the four repos have no
remote at all, so the entire pipeline — langgraph_flow, skill_runner, the
router, every patch script — exists in exactly one place: that Mac Mini's disk.
A commit protects you from a bad edit. It does not protect you from the disk.
See the note this prints at the end.

── WHAT IT DOES ─────────────────────────────────────────────────────────────

For each repo: shows what has changed, stages everything the .gitignore files
allow, commits with your message, and pushes when there is a remote. Repos with
nothing to commit are skipped quietly.

It refuses to stage a file that looks like a secret — .env, *.pem, id_rsa,
anything named *secret*/*credential* — whatever the .gitignore says. shared/.env
is outside all four repos today, and this is here so it stays that way by
accident as well as by design.

── A STALE index.lock LOOKS LIKE NOTHING TO COMMIT ──────────────────────────

v1 ran `git add -A` and never looked at its exit code, so when the add failed
it went on to find an empty staging area and reported:

    nothing staged after .gitignore — skipping

against eight plainly modified files. The real message was two lines further
down, in stderr nobody read:

    fatal: Unable to create '.git/index.lock': File exists.

Which is the exact failure mode this project keeps producing and which I have
spent the evening fixing elsewhere: a step that fails silently and a report
that describes the wrong cause. Every git command now has its exit code
checked, a lock is detected before anything is attempted, and the fix is
printed with the path already filled in.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

DC = Path("/Users/ducorn/DC")
REPOS = ["ducorn", "scripts", "gstack", "ducorn-products"]

SECRET = re.compile(
    r"(^|/)\.env($|\.)|\.pem$|\.p12$|id_rsa|(^|/)[^/]*(secret|credential|token)"
    r"[^/]*\.(json|ya?ml|txt|env)$", re.I)


def git(repo, *args, check=False):
    return subprocess.run(["git", "-C", str(DC / repo), *args],
                          capture_output=True, text=True, check=check)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-m", "--message", help="commit message (required with --apply)")
    ap.add_argument("--apply", action="store_true", help="actually commit")
    ap.add_argument("--no-push", action="store_true", help="commit but do not push")
    args = ap.parse_args()

    if args.apply and not args.message:
        ap.error("--apply needs -m/--message")

    no_remote, pushed, committed, blocked = [], [], [], []
    locked, errored = [], []

    for repo in REPOS:
        path = DC / repo
        if not (path / ".git").is_dir():
            print(f"\n═══ {repo} — not a git repository, skipping")
            continue

        status = git(repo, "status", "--porcelain").stdout.splitlines()
        remote = git(repo, "remote", "get-url", "origin").stdout.strip()
        if not remote:
            no_remote.append(repo)

        print(f"\n═══ {repo} {'' if remote else '(no remote)'}")

        # Checked before anything is attempted. A lock makes `git add` fail,
        # and a failed add is indistinguishable from an empty one unless
        # somebody looks — which is how v1 reported "nothing staged" over
        # eight modified files.
        lock = path / ".git" / "index.lock"
        if lock.exists():
            locked.append(repo)
            print(f"  ⛔ STALE LOCK — {lock}")
            print(f"     No git process is running; something was interrupted.")
            print(f"     rm -f ~/DC/{repo}/.git/index.lock")
            continue

        if not status:
            print("  nothing to commit")
            continue

        # git status --porcelain: XY <path>, and renames carry ' -> '
        files = [line[3:].split(" -> ")[-1].strip().strip('"') for line in status]
        secrets = [f for f in files if SECRET.search(f)]
        if secrets:
            blocked.append((repo, secrets))
            print(f"  ⛔ REFUSING — these look like secrets:")
            for f in secrets:
                print(f"       {f}")
            print("     Add them to .gitignore, then run this again.")
            continue

        mod = sum(1 for l in status if l[:2].strip() and not l.startswith("??"))
        new = sum(1 for l in status if l.startswith("??"))
        print(f"  {mod} modified, {new} untracked")
        for line in status[:12]:
            print(f"    {line}")
        if len(status) > 12:
            print(f"    … and {len(status) - 12} more")

        if not args.apply:
            continue

        r = git(repo, "add", "-A")
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip()
            first = err.splitlines()[0] if err else "(no message)"
            print(f"  ⛔ git add failed: {first}")
            if "index.lock" in err:
                print(f"     rm -f ~/DC/{repo}/.git/index.lock")
            errored.append(repo)
            continue

        # Re-check AFTER staging: .gitignore decides what actually lands, and
        # what git stages is the only list that matters.
        staged = git(repo, "diff", "--cached", "--name-only").stdout.split()
        late = [f for f in staged if SECRET.search(f)]
        if late:
            git(repo, "reset")
            blocked.append((repo, late))
            print(f"  ⛔ staged files look like secrets — unstaged, nothing "
                  f"committed: {late}")
            continue
        if not staged:
            print("  nothing staged after .gitignore — skipping")
            continue

        r = git(repo, "commit", "-m", args.message)
        if r.returncode != 0:
            print(f"  commit failed: {(r.stderr or r.stdout).strip()[:300]}")
            continue
        sha = git(repo, "log", "-1", "--format=%h").stdout.strip()
        print(f"  ✅ committed {sha} ({len(staged)} files)")
        committed.append(repo)

        if remote and not args.no_push:
            r = git(repo, "push")
            if r.returncode == 0:
                print(f"  ⬆️  pushed to {remote}")
                pushed.append(repo)
            else:
                print(f"  push failed: {(r.stderr or r.stdout).strip()[:300]}")

    print("\n" + "─" * 70)
    if not args.apply:
        print("Nothing was committed. Re-run with:")
        print('  python3 scripts/commit_all.py -m "your message" --apply')
    else:
        print(f"committed: {', '.join(committed) or 'nothing'}")
        print(f"pushed:    {', '.join(pushed) or 'nothing'}")

    if blocked:
        print("\n⛔ skipped for possible secrets:")
        for repo, files in blocked:
            print(f"   {repo}: {', '.join(files)}")

    if locked or errored:
        stuck = sorted(set(locked + errored))
        print(f"\n⛔ NOT COMMITTED — {', '.join(stuck)}")
        if locked:
            print("   Clear the stale locks and run this again:")
            print("     rm -f " + " ".join(f"~/DC/{r}/.git/index.lock"
                                           for r in locked))

    if no_remote:
        print(f"\n⚠️  NO REMOTE: {', '.join(no_remote)}")
        print("   These exist on this Mac and nowhere else. A commit protects "
              "you from a bad edit; it does not protect you from the disk.")
        print("   To fix, per repo (private by default):")
        for repo in no_remote:
            name = repo if repo.startswith("ducorn") else f"ducorn-{repo}"
            print(f"     cd ~/DC/{repo} && gh repo create {name} "
                  f"--private --source=. --remote=origin --push")

    return 1 if (blocked or locked or errored) else 0


if __name__ == "__main__":
    sys.exit(main())
