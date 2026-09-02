#!/usr/bin/env python3
"""
Tell the tools apart from the changelog.

    python3 scripts/tidy_scripts.py            show what would move
    python3 scripts/tidy_scripts.py --apply    move it

── THE PROBLEM, WHICH IS AN INDEPENDENCE PROBLEM ────────────────────────────

scripts/ accumulated 119 Python files: 66 spent patches, 13 backup copies,
and the handful that actually do something. A person opening it sees a hundred
and nineteen things they might need to run, and almost all of them exit
immediately with "Already patched".

That is worse than clutter. The whole point of doctor.py and the proofs is that
somebody without me can work out what to do. A directory where the signal is 7%
undoes that. The patches are a CHANGELOG — each edited a file once, months of
reasoning in their docstrings, valuable to read and useless to run.

── AND TO ANSWER THE QUESTION DIRECTLY ──────────────────────────────────────

Nothing in scripts/ runs per pipeline. The pipeline executes exactly one of
them — gdrive_sync.py, after a deploy. Everything else is either a library the
pipeline imports (ducorn_db, ducorn_env, product_paths, bootstrap_python) or a
thing a person runs deliberately.

── WHAT MOVES ───────────────────────────────────────────────────────────────

    patch_*.py      → scripts/applied/     with a manifest of what each did
    *.backup-*.py   → scripts/_backups/    git already holds these versions

Nothing is deleted. Every patch stays runnable from its new home, and doctor's
fix hints are rewritten to the new paths in the same pass — a fix command that
points at a moved file is exactly the kind of quietly-wrong instruction this
week has been about.

── WHAT STAYS ───────────────────────────────────────────────────────────────

The tools, and a README that says when to run each. That list is short enough
to hold in your head, which is the point.
"""
import argparse
import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path("/Users/ducorn/DC/scripts")
APPLIED = SCRIPTS / "applied"
BACKUPS = SCRIPTS / "_backups"

# Everything a person or the pipeline actually invokes. Anything not here and
# not a patch or a backup is left alone and listed at the end for you to judge.
TOOLS = {
    "doctor.py": "Is this machine healthy? Run before a pipeline, after any "
                 "change, and first when something breaks.",
    "migrate.py": "Apply pending database migrations. Bare = apply; "
                  "--status to look first.",
    "commit_all.py": "Commit all four repos. Run periodically; it refuses to "
                     "commit anything that looks like a secret.",
    "create_remotes.py": "Give a repo a GitHub remote. Still needed — ducorn "
                         "and scripts have no upstream.",
    "litellm_budget.py": "Create or cap a per-agent LiteLLM key.",
    "install_playwright.py": "Put a browser where the UI gate can reach it.",
    "vendor_web_guidelines.py": "Re-vendor the interface guidelines the design "
                                "review reads.",
    "delete_run.py": "Remove a pipeline run completely — process, rows, "
                     "checkpoints. For a run you want gone, not resumed.",
    "convert_docs_to_pdf.py": "Turn product markdown into PDFs.",
    "reorganize_drive.py": "Move existing Drive PDFs into the derived folder "
                           "layout.",
    "tidy_scripts.py": "This. Keeps scripts/ readable as things accumulate.",
    # Long-running services. launchd starts these; you rarely run them by hand.
    "slack_bot.py": "The approval path. Runs as a launchd service.",
    "ducorn_proxy.py": "The model router on :4001. Runs as a launchd service.",
    "start_litellm.py": "Starts LiteLLM on :4000.",
    "gdrive_sync.py": "Markdown to PDF into Drive. The pipeline runs this "
                      "itself after a deploy — the only script it invokes.",
    "ducorn_digest.py": "The daily digest, from real agent activity.",
    "cleo_kpis.py": "CLEO's KPI pipeline.",
    "echo_support.py": "ECHO's support triage.",
}

# Run these to find out whether something is broken. Named for what they prove,
# and every one of them exits non-zero when it is not true.
TESTS = {
    "prove_deploy.py": "31 checks over the deploy path — interpreter, service "
                       "plan, config, smoke test, plist.",
    "prove_db_contracts.py": "Code and schema agree on every status value.",
    "prove_ui_gate.py": "The UI gate really does reject a UI with no tests.",
    "verify_design_wiring.py": "The design wiring, without running a pipeline.",
    "test_regressions_sept1.py": "The failures of 31 Aug – 1 Sept, kept honest.",
    "test_ducorn_proxy.py": "The router, against a fake LiteLLM. No network.",
    "test_screenshot.py": "The screenshot tool, against a real browser.",
    "test_writer_done.py": "The writer tool ends a task instead of looping.",
    "test_writer_escapes.py": "The writer-tool escape check.",
    "test_voice_ai.py": "Voice AI performance.",
}

# Ran once, did their job, kept for the reasoning. Same status as a patch.
SPENT = {
    "fix_venv_in_git.py", "fix_product_history.py", "repair_escaped_docs.py",
    "repair_gate2_choice.py", "cleanup_repo_artifacts.py",
}

LIBRARIES = {
    "ducorn_db.py", "ducorn_env.py", "product_paths.py", "bootstrap_python.py",
    "ducorn_classifier.py", "drive_routing.py",
}

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="actually move the files")
args = ap.parse_args()

patches = sorted(SCRIPTS.glob("patch_*.py"))
backups = sorted(p for p in SCRIPTS.glob("*.backup-*.py"))
everything = sorted(SCRIPTS.glob("*.py"))
other = [p for p in everything
         if p not in patches and p not in backups
         and p.name not in TOOLS and p.name not in LIBRARIES
         and p.name not in TESTS and p.name not in SPENT]


def first_line(path):
    """The one-line purpose from the module docstring."""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, OSError):
        return ""
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


print(f"scripts/ holds {len(everything)} Python files\n")
print(f"  {len(patches):3} patch_*.py      → applied/     (spent; each guards "
      f"itself and exits)")
print(f"  {len(backups):3} *.backup-*.py   → _backups/    (git already has "
      f"these versions)")
print(f"  {len(TOOLS):3} tools           stay, with a README saying when to run them")
print(f"  {len(TESTS):3} tests           stay — run these when something is wrong")
print(f"  {len(SPENT):3} spent one-shots → applied/     (ran once, did their job)")
print(f"  {len(LIBRARIES):3} libraries       stay (imported, never run)")
print(f"  {len(other):3} unclassified    stay, listed below for you to judge")

if other:
    print("\nunclassified — I have not decided what these are:")
    for p in other:
        print(f"    {p.name:38} {first_line(p)[:60]}")

if not args.apply:
    print(f"\nNothing moved. Re-run with --apply.")
    sys.exit(0)

# ── move ─────────────────────────────────────────────────────────────────────
APPLIED.mkdir(exist_ok=True)
BACKUPS.mkdir(exist_ok=True)

moved_patches = []
for p in patches:
    dest = APPLIED / p.name
    if dest.exists():
        print(f"  skip {p.name} — already in applied/")
        continue
    shutil.move(str(p), str(dest))
    moved_patches.append(dest)

for name in sorted(SPENT):
    src_p = SCRIPTS / name
    if src_p.is_file() and not (APPLIED / name).exists():
        shutil.move(str(src_p), str(APPLIED / name))
        moved_patches.append(APPLIED / name)

moved_backups = []
for p in backups:
    dest = BACKUPS / p.name
    if not dest.exists():
        shutil.move(str(p), str(dest))
        moved_backups.append(dest)

print(f"\nmoved {len(moved_patches)} patches and {len(moved_backups)} backups")

# ── the manifest: what each patch did, so it reads as history ────────────────
lines = ["# Applied patches",
         "",
         "Each of these edited a file once and is now inert — every one guards",
         "itself and exits with \"Already patched\". They are kept because their",
         "docstrings explain WHY the code is the way it is, which is the part",
         "that does not survive in a diff.",
         "",
         "Nothing here runs per pipeline. Nothing here needs running at all on a",
         "machine that is already patched. To understand a decision, read one.",
         "",
         f"_Archived {datetime.now():%Y-%m-%d}._",
         "",
         "| patch | what it did |",
         "| --- | --- |"]
for p in sorted(APPLIED.glob("patch_*.py")):
    lines.append(f"| `{p.name}` | {first_line(p) or '—'} |")
(APPLIED / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote applied/MANIFEST.md ({len(list(APPLIED.glob('patch_*.py')))} entries)")

# ── every reference to a moved patch must move with it ───────────────────────
#
# doctor prints "→ python3 scripts/patch_X.py" for a failing check. Moving the
# file without rewriting that turns a working instruction into a confidently
# wrong one, which is the exact failure mode this week has been about.
moved_names = {p.name for p in APPLIED.glob("patch_*.py")}
rewritten = []
for f in list(SCRIPTS.glob("*.py")) + [
        Path("/Users/ducorn/DC/ducorn/skill_runner.py"),
        Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")]:
    if not f.is_file():
        continue
    src = f.read_text(encoding="utf-8")
    new = re.sub(r"scripts/(patch_[\w]+\.py)",
                 lambda m: (f"scripts/applied/{m.group(1)}"
                            if m.group(1) in moved_names else m.group(0)), src)
    if new != src:
        f.write_text(new, encoding="utf-8")
        rewritten.append(f.name)
        try:
            ast.parse(new)
        except SyntaxError as e:
            sys.exit(f"rewriting {f} broke it ({e}) — restore it from git")
if rewritten:
    print(f"rewrote patch paths in: {', '.join(rewritten)}")

# ── the map ──────────────────────────────────────────────────────────────────
readme = ["# scripts/",
          "",
          "## What runs when",
          "",
          "**Nothing here runs per pipeline.** The pipeline executes exactly one",
          "of these — `gdrive_sync.py`, after a deploy. Everything else is a",
          "library it imports, or a tool a person runs deliberately.",
          "",
          "| run this | when |",
          "| --- | --- |"]
for name in sorted(TOOLS):
    if (SCRIPTS / name).is_file():
        readme.append(f"| `python3 scripts/{name}` | {TOOLS[name]} |")
readme += [
    "",
    "## What to run when something is wrong",
    "",
    "| run this | what it proves |",
    "| --- | --- |"]
for name in sorted(TESTS):
    if (SCRIPTS / name).is_file():
        readme.append(f"| `python3 scripts/{name}` | {TESTS[name]} |")
readme += [
    "",
    "### The short version",
    "",
    "```",
    "python3 scripts/doctor.py          # before a pipeline, and when anything breaks",
    "python3 scripts/commit_all.py -m \"...\" --apply",
    "```",
    "",
    "`doctor.py` prints the command that fixes every check it fails. That is the",
    "intended entry point for someone who does not know this machine.",
    "",
    "## Libraries",
    "",
    "Imported, never run: " + ", ".join(f"`{n}`" for n in sorted(LIBRARIES)) + ".",
    "",
    "## applied/",
    "",
    "Spent patches. Each edited a file once, guards itself, and now exits",
    "immediately. Kept for the reasoning in their docstrings — see",
    "`applied/MANIFEST.md`. Not a toolkit.",
    "",
    "## _backups/",
    "",
    "Timestamped copies written by patches before they edited a file. Git holds",
    "every one of these versions already; the folder is safe to delete once you",
    "trust the commits.",
    ""]
(SCRIPTS / "README.md").write_text("\n".join(readme), encoding="utf-8")
print("wrote scripts/README.md")

gi = SCRIPTS / ".gitignore"
text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
if "_backups/" not in text:
    gi.write_text(text.rstrip("\n") + "\n\n"
                  "# Timestamped copies written before a patch edits a file.\n"
                  "# Git is the version history; these are not.\n"
                  "_backups/\n*.backup-*\n", encoding="utf-8")
    print("added _backups/ to scripts/.gitignore")

left = sorted(p.name for p in SCRIPTS.glob("*.py"))
print(f"\nscripts/ now holds {len(left)} Python files, down from {len(everything)}:")
for n in left:
    tag = ("tool" if n in TOOLS else "test" if n in TESTS
           else "lib" if n in LIBRARIES else "?")
    print(f"  {tag:5} {n}")
print("\nCommit it:")
print('  python3 scripts/commit_all.py -m "tidy scripts: tools, applied, backups" --apply')
