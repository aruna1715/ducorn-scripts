#!/usr/bin/env python3
"""
Show RESUME when the RUN failed, not only when a SKILL failed.

    const hasFailed = data.skills && data.skills.some(s => s.status === 'failed');
    resumeBtn.style.display = hasFailed ? 'block' : 'none';

Skills are G-Stack rows in pipeline_skill_runs. A failure in a NODE —
research, design, gate_2, launch — writes no skill row, so the button stays
hidden for exactly the runs that most need resuming.

ducorn-spend-view failed at node_design on 1 Sept with an import error. Zero
skills had run, so `data.skills` was empty, so no skill was 'failed', so the
only visible control was KILL — on a run that was already dead.

The condition becomes: offer RESUME when the run is in a state a resume could
move, which is a failed or stopped run OR any failed skill.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

DASH = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
s = DASH.read_text(encoding="utf-8")

if "runIsResumable" in s:
    sys.exit("Already patched.")

OLD = '''  // Show/hide RESUME button based on any failed skills
  const hasFailed = data.skills && data.skills.some(s => s.status === 'failed');
  const resumeBtn = document.getElementById('resumeBtn');
  if (resumeBtn) resumeBtn.style.display = hasFailed ? 'block' : 'none';'''

NEW = '''  // Show RESUME whenever a resume could move this run forward.
  //
  // This used to check failed SKILLS only. Skills are G-Stack rows; a failure
  // in a node — research, design, gate_2, launch — creates none, so a run that
  // died at the design step showed no RESUME at all. The run status is the
  // thing that says whether resuming is meaningful.
  const _runStatus = (p && p.status ? String(p.status) : '').toLowerCase();
  const skillFailed = data.skills && data.skills.some(s => s.status === 'failed');
  const runIsResumable = ['failed', 'stopped', 'needs_intervention'].includes(_runStatus);
  const resumeBtn = document.getElementById('resumeBtn');
  if (resumeBtn) {
    resumeBtn.style.display = (skillFailed || runIsResumable) ? 'block' : 'none';
    resumeBtn.title = runIsResumable
      ? `Run is ${_runStatus} — resume from the last checkpoint`
      : 'A skill failed — resume from the last checkpoint';
  }
  // KILL is only meaningful while something is running.
  const killBtn = document.getElementById('killBtn');
  if (killBtn) {
    killBtn.style.display =
      ['running', 'started', 'awaiting_approval'].includes(_runStatus) ? 'block' : 'none';
  }'''

if s.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {s.count(OLD)}, expected 1. NOTHING WRITTEN.")

backup = DASH.with_name(f"index.backup-resumebtn-{datetime.now():%Y%m%d-%H%M%S}.html")
shutil.copy2(DASH, backup)
DASH.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")

d = DASH.read_text(encoding="utf-8")
for must in ("function killPipeline", "function resumePipeline",
             "function renderProductDetail", "id=\"resumeBtn\"", "id=\"killBtn\""):
    if must not in d:
        shutil.copy2(backup, DASH)
        sys.exit(f"index.html lost {must!r} — reverted from {backup}")

print("applied: RESUME shows on a failed/stopped run; KILL hides when idle")
print(f"backup:  {backup}")
print()
print("Hard-refresh the dashboard.")
