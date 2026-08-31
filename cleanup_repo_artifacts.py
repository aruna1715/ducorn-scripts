#!/usr/bin/env python3
"""
Stop committing my patch backups into your repositories.

DRY RUN BY DEFAULT — prints what it would untrack and changes nothing.
    python3 scripts/cleanup_repo_artifacts.py
    python3 scripts/cleanup_repo_artifacts.py --apply

THE PROBLEM I CREATED
---------------------
Every patch script I have written today backs the file up beside itself first:

    main.backup-approval-20260831-112231.py
    index.backup-designpicker-20260829-195721.html
    ducorn-run-history-launch.stale-20260831-091446.pdf

Backing up before an in-place edit is right. Leaving them next to the source
is not, because `git add -A` then commits them: 21 of these are now tracked
across two repos, and today's three commits carried 27,000 insertions, most of
which are copies of files already in the same commit.

Git is the backup. Once a change is committed, a timestamped copy of the
previous version is strictly worse than `git show HEAD~1:path` — it is
unversioned, it never gets deleted, and it turns every future diff into noise.

WHAT THIS DOES
--------------
  * writes a .gitignore in each repo covering *.backup-* and *.stale-*
  * untracks any that are already committed (git rm --cached — the files stay
    on disk, so nothing you might still want to compare against is lost)

It does NOT delete anything from disk, and it does not touch the PDFs — see
the note at the end of the run for that, because it is your call, not mine.
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPOS = [Path("/Users/ducorn/DC/scripts"),
         Path("/Users/ducorn/DC/ducorn"),
         Path("/Users/ducorn/DC/ducorn-products")]

IGNORE_BLOCK = """
# ── Patch backups ────────────────────────────────────────────────────────────
# Written by the patch scripts in scripts/ before they edit a file in place.
# Useful for an hour, harmful in a commit: git already holds the previous
# version, and these are unversioned copies that never get cleaned up.
*.backup-*
*.stale-*
"""


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {repo.name}:\n{r.stderr}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("DRY RUN — nothing will change\n" if not args.apply
          else "APPLYING\n")

    total = 0
    for repo in REPOS:
        if not (repo / ".git").exists():
            print(f"{repo.name}: not a git repo, skipping")
            continue

        tracked = [l for l in git(repo, "ls-files").splitlines()
                   if ".backup-" in l or ".stale-" in l]
        gi = repo / ".gitignore"
        has_rule = gi.exists() and "*.backup-*" in gi.read_text(encoding="utf-8")

        print(f"{repo.name}:")
        print(f"    .gitignore rule: {'present' if has_rule else 'MISSING'}")
        print(f"    tracked backups: {len(tracked)}")
        for t in tracked[:6]:
            print(f"        {t}")
        if len(tracked) > 6:
            print(f"        ... and {len(tracked) - 6} more")
        total += len(tracked)

        if args.apply:
            if not has_rule:
                with gi.open("a", encoding="utf-8") as f:
                    f.write(IGNORE_BLOCK)
                git(repo, "add", ".gitignore")
                print("    wrote .gitignore")
            for t in tracked:
                # --cached: untrack, keep the file on disk.
                git(repo, "rm", "--cached", "--quiet", t)
            if tracked:
                print(f"    untracked {len(tracked)} file(s) — still on disk")
        print()

    if not args.apply:
        print(f"{total} backup file(s) tracked across {len(REPOS)} repos.")
        print("Re-run with --apply to add the ignore rules and untrack them.")
        return

    print("Done. Commit the result:")
    for repo in REPOS:
        print(f"    git -C {repo} commit -m 'Stop tracking patch backups'")

    print("\nSEPARATELY, AND YOUR CALL:")
    print("  ducorn-products tracks 63 generated PDFs. They are rebuilt from")
    print("  docs/*.md by gdrive_sync.py and average ~400KB, so they are a")
    print("  derived artifact in version control — every regeneration is a")
    print("  binary diff nobody can read. The .md sources are what matter.")
    print("  I have not touched them: they are also your only local copy of")
    print("  some older documents, and that is a decision to make deliberately")
    print("  rather than have a cleanup script make for you.")


if __name__ == "__main__":
    main()
