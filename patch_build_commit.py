#!/usr/bin/env python3
"""
Stop printing "✅ Files committed to GitHub" when nothing was.

── THE LINE ─────────────────────────────────────────────────────────────────

    commit_cmd = f"cd {PRODUCTS_DIR} && git add products/{topic}/ && "
                 f"git commit -m 'feat(rex): {topic} initial build' && "
                 f"git push origin main"
    subprocess.run(["bash", "-c", commit_cmd], timeout=60, capture_output=True)
    print(f"✅ Files committed to GitHub")

The result is captured and discarded. The print is unconditional. So the
message is not a report of what happened — it is a constant.

Tonight it was false. That push failed, because git add had just swept up
products/ducorn-spend-status/.venv (QA builds it to run the tests) and one file
inside playwright is 115 MB, over GitHub's hard limit. The pipeline printed
"✅ Files committed to GitHub", carried on to QA, gate 3, launch, gate 4 and
deploy, and reported a complete run. You found out from a push you ran by hand,
hours later.

It is also false in three quieter ways: git add failing, nothing to commit, and
no upstream configured all produce the same tick.

This is the same defect as every other one this week, in its purest form: a
control that exists, reads correctly in isolation, and never reaches the thing
it is supposed to report on. The others at least tried and failed. This one
never looked.

── THE FIX ──────────────────────────────────────────────────────────────────

The three steps are run separately, because they fail differently and only one
of them is really a failure:

    git add      failing is a problem
    git commit   returning "nothing to commit" is normal — a re-run of a phase
                 that already committed, and not worth a scary message
    git push     failing is worth saying out loud, but must NOT fail the build:
                 the work is committed locally and a pipeline that has produced
                 a good product should not be marked failed because a remote is
                 unreachable

So: committed and pushed, committed but not pushed with the reason, or add
failed and the reason. Three outcomes, three messages, each true.

The commit stays scoped to products/<topic>/ — one product's files, never
another's — which is the isolation rule and is unchanged here.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "def _git_publish" in s:
    sys.exit("Already patched — the commit reports what happened.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("helper", s, "def _update_db_status(topic: str, status: str",
         '''def _git_publish(paths: str, message: str) -> str:
    """
    Commit one product's files and push, and say which of those happened.

    Each step separately, because they mean different things. The previous
    version ran all three joined by && , discarded the result, and printed a
    tick — so a push rejected for a 115 MB file inside a virtualenv looked
    exactly like a successful one, and the pipeline ran to completion on top of
    a lie.

    A failed push does not fail the build. The product is committed locally and
    is not less finished because GitHub is unreachable.
    """
    import subprocess as _sp

    def run(*args):
        return _sp.run(["git", "-C", str(PRODUCTS_DIR), *args],
                       capture_output=True, text=True, timeout=120)

    add = run("add", "--", paths)
    if add.returncode != 0:
        note = (add.stderr or add.stdout).strip()[-300:]
        print(f"⚠️  git add {paths} failed — nothing committed:\\n{note}",
              flush=True)
        return "add-failed"

    commit = run("commit", "-m", message)
    if commit.returncode != 0:
        out = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in out or "no changes added" in out:
            print(f"ℹ️  nothing new to commit for {paths}", flush=True)
            return "nothing-to-commit"
        note = (commit.stderr or commit.stdout).strip()[-300:]
        print(f"⚠️  git commit failed:\\n{note}", flush=True)
        return "commit-failed"

    sha = run("rev-parse", "--short", "HEAD").stdout.strip()
    push = run("push", "origin", "HEAD")
    if push.returncode != 0:
        note = (push.stderr or push.stdout).strip()[-400:]
        # Said plainly and not fatal. The commit is on disk; the remote is a
        # separate problem with a separate fix.
        print(f"✅ committed {sha} locally\\n"
              f"⚠️  push FAILED — the work is committed but not on GitHub:\\n"
              f"{note}", flush=True)
        return "committed-not-pushed"

    print(f"✅ committed {sha} and pushed to GitHub", flush=True)
    return "pushed"


def _update_db_status(topic: str, status: str''')

s = swap("call site", s, '''        if product_type == 'document':
            commit_cmd = f"cd {PRODUCTS_DIR} && git add docs/ && git commit -m 'docs(rex): {topic}' && git push origin main"
        else:
            commit_cmd = f"cd {PRODUCTS_DIR} && git add products/{topic}/ && git commit -m 'feat(rex): {topic} initial build' && git push origin main"
        subprocess.run(["bash", "-c", commit_cmd], timeout=60, capture_output=True)
        print(f"✅ Files committed to GitHub")''',
         '''        # Scoped to this product's own files, as before — one product's
        # commit never carries another's.
        if product_type == 'document':
            _git_publish("docs/", f"docs(rex): {topic}")
        else:
            _git_publish(f"products/{topic}/",
                         f"feat(rex): {topic} initial build")''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FLOW.with_name(f"langgraph_flow.backup-gitreport-{stamp}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, FLOW)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

src = FLOW.read_text(encoding="utf-8")
if "✅ Files committed to GitHub" in src:
    die("the unconditional success message is still there")
if "&& git push origin main" in src:
    die("the && chain survived — a failing push would still be invisible")

# ── exercise the four outcomes ───────────────────────────────────────────────
t = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in t.body
            if isinstance(n, ast.FunctionDef) and n.name == "_git_publish"), None)
if seg is None:
    die("_git_publish did not land")

import types
from unittest import mock


class FakeRun:
    """Answers git calls from a script of (returncode, stdout, stderr)."""

    def __init__(self, plan):
        self.plan = plan

    def __call__(self, args, **kw):
        cmd = args[3] if len(args) > 3 else ""
        rc, out, err = self.plan.get(cmd, (0, "", ""))
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


print("\nwhat gets reported, for each thing that can happen:")
CASES = [
    ({}, "pushed", "everything worked"),
    ({"push": (1, "", "remote: error: File ... is 115.35 MB; this exceeds")},
     "committed-not-pushed", "TONIGHT: push rejected, and it now says so"),
    ({"commit": (1, "nothing to commit, working tree clean", "")},
     "nothing-to-commit", "a re-run of a phase that already committed"),
    ({"add": (1, "", "fatal: pathspec did not match")},
     "add-failed", "add failed — nothing was committed"),
    ({"push": (1, "", "fatal: The current branch has no upstream branch")},
     "committed-not-pushed", "no upstream — committed, not pushed"),
]
for plan, want, why in CASES:
    ns = {"PRODUCTS_DIR": Path("/tmp"), "Path": Path}
    exec(seg, ns)
    with mock.patch("subprocess.run", FakeRun(plan)):
        got = ns["_git_publish"]("products/zz/", "feat: zz")
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {got:22} {why}")
    if not ok:
        die(f"expected {want}, got {got}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Nothing to restart. The next build will say one of:")
print("  ✅ committed 5a4a5ae and pushed to GitHub")
print("  ✅ committed 5a4a5ae locally")
print("  ⚠️  push FAILED — the work is committed but not on GitHub: <reason>")
