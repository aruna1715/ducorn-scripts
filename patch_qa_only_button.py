#!/usr/bin/env python3
"""
RE-RUN QA ONLY — the cheap retry, from the dashboard.

    cd ~/DC && python3 scripts/patch_qa_only_button.py            show
    cd ~/DC && python3 scripts/patch_qa_only_button.py --apply    do it

── WHY ──────────────────────────────────────────────────────────────────────

Phase 1 of the admin rebuild ended with 24 of 25 tests passing and one wrong
assertion in a test file. QA said so itself: "product code is correct, test
file only". Fixing it and pressing RESUME would have re-run the build and the
code review as well — because a QA rejection is recorded against skills 04
and 05, which is right when the build is at fault and wasteful when it is
not.

Three cycles of that cost about six dollars each to change one word.

── WHAT IT ACTUALLY DOES ────────────────────────────────────────────────────

Nothing new. /pipeline/resume already accepts a phase override, and node_qa
already runs the pathway's QA skill on its own:

    _qa_name = _pwq.skill_name(_pathway.qa_skill)
    ... skill_runner --skill <qa_skill>

So this posts {"phase": "qa"} instead of {}. The capability existed; the page
had no way to ask for it.

── WHEN IT IS THE RIGHT BUTTON ──────────────────────────────────────────────

When the product has not changed and the verification has. A fixed test, a
flaky browser timeout, a QA run that died on its own. It re-runs the tests
and one report.

When it is the WRONG button: when the build genuinely needs to change. Then
RESUME is right, because it re-runs the builder with the rejection in hand.
The two sit side by side and the labels say which is which — this one is
marked with what it skips, not just what it does.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
PAGE = DC / "ducorn-products" / "products" / "ducorn-dashboard" / "index.html"
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
TAG = "qaonly"

BTN_OLD = '''          <button id="resumeBtn" onclick="resumePipeline()" class="mono"
            style="display:none;cursor:pointer;flex:1;font-size:9px;letter-spacing:.12em;padding:8px;
                   background:rgba(var(--green-rgb),.15);border:1px solid rgba(var(--green-rgb),.4);border-radius:2px;color:var(--green);">
            🔄 RESUME
          </button>'''

BTN_NEW = BTN_OLD + '''
          <button id="qaOnlyBtn" onclick="resumePipeline('qa')" class="mono"
            title="Re-run only the QA step. Skips the build and the code review — use when the product is unchanged and the tests are what moved."
            style="display:none;cursor:pointer;flex:1;font-size:9px;letter-spacing:.12em;padding:8px;
                   background:rgba(var(--accent-rgb),.12);border:1px solid rgba(var(--accent-rgb),.35);border-radius:2px;color:var(--accent);">
            🔍 QA ONLY
          </button>'''

FN_OLD = '''async function resumePipeline() {
  if (!_currentProductSlug) return;
  const btn = document.getElementById('resumeBtn');
  if (btn) {
    btn.textContent = '⏳ RESUMING...';
    btn.disabled = true;
    btn.style.opacity = '0.5';
  }
  try {
    const res = await fetch(API+"/pipeline/resume/"+_currentProductSlug, {
      method:"POST", headers:HDR,
      body: JSON.stringify({})
    });'''

FN_NEW = '''async function resumePipeline(phase) {
  if (!_currentProductSlug) return;
  /* phase === "qa" re-enters at the QA node, which runs the pathway's QA
     skill alone. The build and the code review are skipped — right when the
     product has not changed and the VERIFICATION has, and wrong when the
     build itself needs fixing. Say which one is about to happen. */
  if (phase === "qa" && !confirm(
        "Re-run QA only for " + _currentProductSlug + "?\\n\\n"
      + "Skips the build and the code review. Use this when the product is "
      + "unchanged and a test was fixed.\\n\\nIf the BUILD needs to change, "
      + "press RESUME instead — that hands the builder the rejection."))
    return;
  const btn = document.getElementById(phase === "qa" ? 'qaOnlyBtn' : 'resumeBtn');
  if (btn) {
    btn.textContent = phase === "qa" ? '⏳ RUNNING QA...' : '⏳ RESUMING...';
    btn.disabled = true;
    btn.style.opacity = '0.5';
  }
  try {
    const res = await fetch(API+"/pipeline/resume/"+_currentProductSlug, {
      method:"POST", headers:HDR,
      body: JSON.stringify(phase ? {phase: phase} : {})
    });'''

VIS_OLD = '''  if (resumeBtn) {
    resumeBtn.style.display = (skillFailed || runIsResumable) ? 'block' : 'none';'''

VIS_NEW = '''  // QA ONLY shows under the same condition as RESUME. It is only ever the
  // right choice for a product whose pathway HAS a QA step, but a run that
  // cannot resume cannot re-run QA either, so the condition is the same one.
  const qaOnlyBtn = document.getElementById('qaOnlyBtn');
  if (qaOnlyBtn) {
    qaOnlyBtn.style.display = (skillFailed || runIsResumable) ? 'block' : 'none';
    qaOnlyBtn.title = 'Re-run only the QA step — skips the build and the '
      + 'code review. Use when the product is unchanged and a test was fixed.';
  }
  if (resumeBtn) {
    resumeBtn.style.display = (skillFailed || runIsResumable) ? 'block' : 'none';'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (PAGE, FLOW):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

print("patch_qa_only_button\n")

# The capability must really be there, or this is a button that posts a phase
# nothing honours.
flow = FLOW.read_text(encoding="utf-8")
if '"qa":     "build"' not in flow and '"qa"' not in flow:
    sys.exit("NOTHING DONE — langgraph_flow has no qa phase to resume at.")
if "_pathway.qa_skill" not in flow:
    sys.exit("NOTHING DONE — node_qa does not run a QA skill on its own; "
             "resuming at qa would not do what this button claims.")
print("  ok  node_qa runs the pathway's QA skill alone")
print("  ok  'qa' is a resumable phase")

src = PAGE.read_text(encoding="utf-8")
if "qaOnlyBtn" in src:
    sys.exit("NOTHING DONE — the QA ONLY button is already there.")

bad = False
for label, a in [("the RESUME button", BTN_OLD),
                 ("resumePipeline()", FN_OLD),
                 ("the RESUME visibility rule", VIS_OLD)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PAGE, PAGE.with_suffix(f".backup-{TAG}-{stamp}.html"))
out = src.replace(BTN_OLD, BTN_NEW, 1).replace(FN_OLD, FN_NEW, 1) \
         .replace(VIS_OLD, VIS_NEW, 1)
PAGE.write_text(out, encoding="utf-8")
print(f"\nwrote {PAGE.name}, backup tagged {TAG}-{stamp}")

after = PAGE.read_text(encoding="utf-8")
node = shutil.which("node")
if node:
    i = after.find("async function resumePipeline(phase)")
    j = after.find("function closeProductDetail()")
    frag = after[i:j] if i >= 0 and j > i else ""
    if not frag:
        sys.exit("⚠️  could not locate resumePipeline — restore the backup.")
    r = subprocess.run([node, "--check"], input=frag, capture_output=True,
                       text=True)
    if r.returncode != 0:
        sys.exit(f"⚠️  resumePipeline does not parse — restore the backup:\n"
                 f"{r.stderr[-400:]}")
    print("verified: resumePipeline parses (node --check).")
else:
    print("NOT verified: node is not on PATH. Check the console after "
          "reloading.")

# RESUME must still resume the whole thing — a shared function that always
# sent a phase would silently turn every resume into a QA-only run.
if 'JSON.stringify(phase ? {phase: phase} : {})' not in after:
    sys.exit("⚠️  the body is not conditional on the phase — restore the "
             "backup.")
if "onclick=\"resumePipeline()\"" not in after:
    sys.exit("⚠️  the RESUME button no longer calls resumePipeline with no "
             "phase — restore the backup.")
print("          RESUME still sends no phase; only QA ONLY does.")

print("""
  Hard-reload the dashboard and open the run.

Two buttons now: 🔄 RESUME (rebuild with the rejection) and 🔍 QA ONLY
(re-run the tests and one report). For the masthead fix you just applied,
QA ONLY is the one — about $0.30 rather than $6.
""")
