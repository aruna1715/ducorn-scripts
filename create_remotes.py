#!/usr/bin/env python3
"""
Give ducorn, scripts and gstack a remote, without needing the gh CLI.

    python3 scripts/create_remotes.py                     dry run
    python3 scripts/create_remotes.py --apply             create and push
    python3 scripts/create_remotes.py --remote-only NAME --apply
                                                          they already exist

Note the absence of trailing # comments. zsh does not treat # as a comment in
an interactive shell unless interactive_comments is set, so a copied line with
one on the end becomes an argument and argparse rejects the whole command.

── WHY NOT gh ───────────────────────────────────────────────────────────────

    zsh: command not found: gh

It is not installed, and installing a CLI plus authenticating it is a longer
road than the one already paved: GITHUB_TOKEN and GITHUB_USERNAME are in
shared/.env, and ducorn-products already pushes over SSH to
git@github.com:aruna1715/ducorn-products.git — so the keys work and the
account is known. This creates the repositories through the REST API and then
uses ordinary git.

If the token turns out to be dead — which it was, 401 — there is a third route
that needs no token and no CLI at all: create the three empty repositories in
the GitHub web UI, then run this with --remote-only. SSH already works, so the
wiring and the push are the same either way.

Worth knowing: nothing else on this machine uses GITHUB_TOKEN. Every push,
including node_build's auto-commit, goes over SSH. So the token has been dead
for some unknown length of time and nothing noticed, because nothing asked.

── WHAT IT DOES, PER REPO ───────────────────────────────────────────────────

  1. skips it if it already has a remote
  2. creates a PRIVATE repository under the token's own account
  3. adds it as origin over SSH, matching how ducorn-products already pushes
  4. pushes the current branch and sets upstream
  5. confirms with git ls-remote that the commits are actually there

A repository that already exists is not an error — it adds the remote and
pushes to it, which is what you want on a second run.

The token is read from the environment and never printed. If GitHub refuses,
the message says which step failed and leaves the repo untouched.
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from ducorn_env import load_ducorn_env  # noqa

import os

DC = Path("/Users/ducorn/DC")
# Local directory → repository name. ducorn-products already has a remote and
# is here only so the script reports on all four.
REPOS = {"ducorn": "ducorn",
         "scripts": "ducorn-scripts",
         "gstack": "ducorn-gstack",
         "ducorn-products": "ducorn-products"}

API = "https://api.github.com"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(DC / repo), *args],
                          capture_output=True, text=True)


def api(path, token, method="GET", body=None):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "ducorn-create-remotes",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--remote-only", metavar="OWNER",
                    help="skip creating anything; the repositories already "
                         "exist under OWNER. Wires up origin over SSH and "
                         "pushes. No token needed.")
    args = ap.parse_args()

    load_ducorn_env()

    if args.remote_only:
        owner, token = args.remote_only, None
        print(f"--remote-only: assuming {owner}/<name> already exists on "
              f"GitHub; nothing will be created\n")
    else:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not token:
            return ("GITHUB_TOKEN is not in shared/.env. Either add one with "
                    "'repo' scope, or create the repositories yourself and "
                    "use --remote-only <owner>.")
        try:
            me = api("/user", token)
        except urllib.error.HTTPError as e:
            return (f"GitHub rejected the token ({e.code} {e.reason}).\n"
                    f"   Nothing else on this machine uses GITHUB_TOKEN — every "
                    f"push goes over SSH — so it can be dead without anything "
                    f"noticing.\n"
                    f"   Either: a new token with 'repo' scope in shared/.env,\n"
                    f"   or:     create the three repos at github.com/new and "
                    f"re-run with --remote-only <your-username>")
        except Exception as e:
            return f"could not reach GitHub: {type(e).__name__}: {e}"
        owner = me.get("login")
        print(f"authenticated as {owner}\n")

    # The account that owns the repo we already push to. A mismatch is worth
    # saying out loud rather than quietly creating repos somewhere else.
    existing = git("ducorn-products", "remote", "get-url", "origin").stdout.strip()
    if existing and owner and owner not in existing:
        whose = ("you named" if token is None
                 else "this token belongs to")
        print(f"⚠️  ducorn-products pushes to {existing}, but {whose} "
              f"{owner!r}. The new remotes will point at {owner!r}.\n")

    todo = []
    for path, name in REPOS.items():
        if not (DC / path / ".git").is_dir():
            print(f"  skip  {path} — not a git repository")
            continue
        branch = git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        commits = git(path, "rev-list", "--count", "HEAD").stdout.strip()
        remote = git(path, "remote", "get-url", "origin").stdout.strip()

        if remote:
            # Having a remote is not the same as having pushed to one. An
            # earlier run of this script added the remote and then failed to
            # push, and the version before this one called that "ok" and
            # skipped it — leaving the repo looking safe while still existing
            # in exactly one place.
            probe = git(path, "ls-remote", "--heads", "origin", branch)
            if probe.returncode == 0 and probe.stdout.strip():
                print(f"  ok    {path} → {remote}")
                continue
            reason = ("branch not on the remote" if probe.returncode == 0
                      else "remote unreachable")
            print(f"  TODO  {path} → {remote}  ({commits} commits on "
                  f"{branch}, {reason})")
            todo.append((path, name, branch, remote))
            continue

        print(f"  TODO  {path} → {owner}/{name}  ({commits} commits on {branch})")
        todo.append((path, name, branch, None))

    if not todo:
        print("\nEvery repository already has a remote.")
        return 0

    if not args.apply:
        what = (f"wire up to {owner}" if token is None
                else f"create, private, under {owner}")
        print(f"\n{len(todo)} repositor{'y' if len(todo) == 1 else 'ies'} to "
              f"{what}. Re-run with --apply.")
        return 1

    print()
    failures = []
    for path, name, branch, remote in todo:
        url = remote or f"git@github.com:{owner}/{name}.git"
        print(f"═══ {path} → {url}")

        if remote:
            print("  remote already set — this is a push, nothing is created")
        else:
            if token is None:
                print("  --remote-only: not creating, wiring up what is there")
            try:
                if token is not None:
                    api("/user/repos", token, "POST", {
                        "name": name, "private": True,
                        "description": f"DuCorn — {path}",
                        "has_issues": True, "has_wiki": False,
                        "auto_init": False})
                    print("  created (private)")
            except urllib.error.HTTPError as e:
                if e.code == 422:
                    # Already exists. Fine — that is the second-run case.
                    print("  already exists on GitHub — adding the remote to it")
                else:
                    detail = ""
                    try:
                        detail = json.loads(e.read()).get("message", "")
                    except Exception:
                        pass
                    print(f"  ⛔ create failed: {e.code} {e.reason} {detail}")
                    failures.append(path)
                    continue

            r = git(path, "remote", "add", "origin", url)
            if r.returncode != 0 and "already exists" not in r.stderr:
                print(f"  ⛔ could not add remote: {r.stderr.strip()[:200]}")
                failures.append(path)
                continue
            print(f"  origin = {url}")

        # Before the push, and for EVERY path through this loop — including the
        # one where the remote was already configured. The first version only
        # probed when creating, so a repo left with a remote by an earlier
        # failed run skipped the check and got "Repository not found" again:
        # a message that reads like a permissions problem and is not one.
        probe = subprocess.run(["git", "ls-remote", url],
                               capture_output=True, text=True)
        if probe.returncode != 0:
            print(f"  ⛔ {url} is not reachable — the repository does not "
                  f"exist yet, or SSH cannot see it.")
            print(f"     Create it EMPTY (no README, no .gitignore, private):")
            print(f"       https://github.com/new?name={name}&visibility=private")
            print(f"     then run this command again.")
            failures.append(path)
            continue

        r = git(path, "push", "-u", "origin", branch)
        if r.returncode != 0:
            print(f"  ⛔ push failed: {(r.stderr or r.stdout).strip()[-300:]}")
            failures.append(path)
            continue

        # Confirm rather than assume: a push that printed nothing and a push
        # that worked look identical from here otherwise.
        r = git(path, "ls-remote", "--heads", "origin", branch)
        if r.returncode != 0 or not r.stdout.strip():
            print(f"  ⛔ pushed, but {branch} is not on the remote — check "
                  f"manually")
            failures.append(path)
            continue
        sha = r.stdout.split()[0][:12]
        print(f"  ⬆️  pushed {branch} — remote is at {sha}")

    print("\n" + "─" * 70)
    if failures:
        print(f"failed: {', '.join(failures)}")
        print("Nothing was lost — every commit is still on this machine.")
        print("Create the empty private repositories listed above, then:")
        print("  python3 scripts/create_remotes.py --remote-only "
              f"{owner} --apply")
        return 1
    print("All three repositories now exist off this machine.")
    print("From here, commit_all.py pushes them automatically.")
    return 0


if __name__ == "__main__":
    r = main()
    if isinstance(r, str):
        sys.exit(f"❌ {r}")
    sys.exit(r)
