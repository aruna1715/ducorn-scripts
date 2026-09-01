#!/usr/bin/env python3
"""
Add a KILL button to the pipeline panel, and a log mode selector.

Apply after patch_log_and_kill.py, which adds the endpoint this calls.

WHY A CONFIRM STEP
------------------
Stopping a pipeline mid-build throws away whatever that stage has spent. That
is sometimes exactly right — a loop burning REX's budget should be stopped
immediately — but it is not a thing to do by mis-clicking next to RESUME. The
button asks once, naming the product, and says what will and will not be lost.

WHY IT IS NOT "DELETE"
----------------------
Kill stops the process and leaves everything: rows, log, partial output. That
is the whole point — a run worth stopping is usually a run worth reading.
Removal stays a separate, deliberate act via scripts/delete_run.py.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

DASH = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
s = DASH.read_text(encoding="utf-8")

if "killPipeline" in s:
    sys.exit("Already patched — killPipeline is present.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


# ── 1. The button, beside RESUME ─────────────────────────────────────────────
swap("kill button", '''          <button id="resumeBtn" onclick="resumePipeline()" class="mono"''',
'''          <button id="killBtn" onclick="killPipeline()" class="mono"
            title="Stop the running pipeline. Nothing is deleted."
            style="cursor:pointer;flex:1;font-size:9px;letter-spacing:.12em;padding:8px;
                   background:rgba(var(--red-rgb),.12);border:1px solid rgba(var(--red-rgb),.4);border-radius:2px;color:var(--red);">
            ✋ KILL
          </button>
          <button id="resumeBtn" onclick="resumePipeline()" class="mono"''')


# ── 2. Log mode selector, above the log container ────────────────────────────
swap("log mode selector", '''          <div id="pipelineLogContainer"''',
'''          <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;">
            <span class="mono" style="font-size:8px;letter-spacing:.16em;color:var(--muted);">LOG</span>
            <select id="logMode" onchange="loadPipelineLog()" class="mono"
              style="font-size:9px;padding:3px 6px;background:var(--field);color:var(--ink-2);
                     border:1px solid var(--field-border);border-radius:2px;cursor:pointer;">
              <option value="raw" selected>RAW — everything</option>
              <option value="full">FILTERED — no box drawing</option>
              <option value="steps">STEPS — milestones only</option>
            </select>
            <span id="logCount" class="mono" style="font-size:8px;color:var(--muted);"></span>
          </div>
          <div id="pipelineLogContainer"''')


# ── 3. loadPipelineLog honours the selector and reports what it got ──────────
swap("log fetch", '''    const res = await fetch(API+"/pipeline/log/"+_currentProductSlug+"?lines=100", {headers:HDR});
    const data = await res.json();''',
'''    const _modeEl = document.getElementById("logMode");
    const _mode = _modeEl ? _modeEl.value : "raw";
    const res = await fetch(API+"/pipeline/log/"+_currentProductSlug
                            +"?lines=300&mode="+_mode, {headers:HDR});
    const data = await res.json();

    // Say how many lines of how many. An empty panel used to be ambiguous
    // between "nothing has happened" and "the filter ate everything".
    const _c = document.getElementById("logCount");
    if (_c) _c.textContent = data.exists
      ? `${data.shown || 0} of ${data.matched || 0} shown · ${data.total_lines || 0} in file`
      : "no log file yet";''')


# ── 4. killPipeline() ────────────────────────────────────────────────────────
swap("kill function", '''async function resumePipeline() {''',
'''async function killPipeline() {
  if (!_currentProductSlug) return;
  // Confirm, because stopping mid-stage discards what that stage has spent.
  // Deliberate is the point; this sits next to RESUME.
  const ok = confirm(
    `Stop the pipeline for "${_currentProductSlug}"?\\n\\n` +
    `The running process is terminated and any pending approvals are ` +
    `cancelled.\\n\\nNothing is deleted — the log, the PRD and any partial ` +
    `output stay. Spend already incurred is not recovered.`);
  if (!ok) return;

  const btn = document.getElementById("killBtn");
  if (btn) { btn.textContent = "STOPPING..."; btn.disabled = true; }
  try {
    const res = await fetch(API+"/pipeline/kill/"+_currentProductSlug,
                            {method:"POST", headers:HDR});
    const data = await res.json();
    addChatMsg("ATLAS", data.message || `Stopped ${_currentProductSlug}.`);
  } catch(e) {
    addChatMsg("ATLAS", "❌ Could not stop the pipeline: " + e.message);
  }
  if (btn) { btn.textContent = "✋ KILL"; btn.disabled = false; }
  loadPipelineLog();
  pollPipelineStatus();
}

async function resumePipeline() {''')

backup = DASH.with_name(f"index.backup-killbtn-{datetime.now():%Y%m%d-%H%M%S}.html")
shutil.copy2(DASH, backup)
DASH.write_text(s, encoding="utf-8")

# HTML has no parser here — check the things that would break instead.
d = DASH.read_text(encoding="utf-8")
for must in ("function killPipeline", "function resumePipeline",
             "function loadPipelineLog", "function renderApprovals",
             "id=\"pipelineLogContainer\""):
    if must not in d:
        shutil.copy2(backup, DASH)
        sys.exit(f"index.html lost {must!r} — reverted from {backup}")
if d.count("<script") != DASH.with_name(backup.name).read_text().count("<script"):
    shutil.copy2(backup, DASH)
    sys.exit(f"script tag count changed — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup}")
print()
print("Hard-refresh the dashboard (Cmd-Shift-R).")
