#!/usr/bin/env python3
"""
Make the live log show something, and add a way to stop a running pipeline.

APPLY AFTER THE CURRENT RUN FINISHES — it restarts the API, and the running
flow polls /agents/config.

── 1. THE LIVE LOG SHOWS NOTHING ────────────────────────────────────────────

    for line in all_lines[-lines:]:      # slice the last 100 RAW lines
        if any(c in line for c in ['─', '│', ...]): continue
        if len(line) < 4: continue

It slices FIRST and filters after. CrewAI renders in box-drawing characters,
so the last 100 raw lines of a healthy run are almost always a rendered panel
— every one dropped as decoration.

Measured against the live ducorn-spend-view log while it was running:

    raw lines in the file : 1096
    what the viewer showed:    0

Not "sometimes sparse". Zero, on a working pipeline. The window was counted in
raw lines and spent on decoration before any content was reached.

FIXED, in the order that matters:

  * mode=raw is the DEFAULT — everything, ANSI escape codes stripped. tail -f.
    Verbose and readable beats clean and empty; not knowing whether anything
    is happening is the failure that actually cost time.
  * mode=full  raw minus the box drawing and tracing noise
  * mode=steps only the pipeline's own milestones, for watching stages
  * the window is applied AFTER filtering in every mode, so `lines` counts
    lines you will see
  * a filtered mode that matches nothing FALLS BACK to raw. Empty must mean
    "the file is empty", never "my filter was too aggressive".

── 2. THERE IS NO WAY TO STOP A RUN ─────────────────────────────────────────

Stopping a pipeline currently means finding the PID by hand, or running
delete_run.py — which also deletes it. Those are different needs: a runaway
loop wants stopping AND keeping, so you can read what it did.

POST /pipeline/kill/{slug} terminates the process, marks the run stopped,
cancels its pending approvals so they do not sit in Slack forever, and removes
nothing.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
s = API.read_text(encoding="utf-8")

if "pipeline_kill" in s:
    sys.exit("Already patched — pipeline_kill is present.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


# ── 1. Replace the whole filter head ─────────────────────────────────────────
swap("log head",
'''def pipeline_log(slug: str, lines: int = 100):
    """Return last N lines of pipeline log file — cleaned for dashboard display"""
    import re
    log_path = f"/Users/ducorn/DC/logs/flow_{slug}.log"
    if not os.path.exists(log_path):
        return {"lines": [], "exists": False}

    with open(log_path, 'r', errors='ignore') as f:
        all_lines = f.readlines()

    parsed = []
    for line in all_lines[-lines:]:
        line = line.strip()
        if not line:
            continue
        # Skip box-drawing characters and decorative lines
        if any(c in line for c in ['─', '│', '╭', '╰', '├', '└', '┌', '┐', '┘', '┤', '╮', '╯', '▰', '▱']):
            continue
        # Skip pure whitespace or separator lines
        if re.match(r'^[\\s\\-=\\*\\.]+$', line):
            continue
        # Skip very short lines
        if len(line) < 4:
            continue
        # Skip tracing/debug noise
        if any(x in line for x in ['Tracing', 'telemetry', 'opentelemetry', 'OPENTELEMETRY']):
            continue
''',
'''def pipeline_log(slug: str, lines: int = 200, mode: str = "raw"):
    """
    Pipeline log for the dashboard.

    mode=raw    everything, ANSI codes stripped. tail -f. THE DEFAULT.
    mode=full   raw minus CrewAI box drawing and tracing noise
    mode=steps  only the pipeline's own milestone lines

    raw is the default because the failure that mattered was showing NOTHING.
    On a live run with 1,096 lines in the file, the previous code returned 0
    rows: it took the last 100 RAW lines and dropped every one as decoration.
    A verbose log you can read beats a tidy one that leaves you wondering
    whether anything is happening at all.

    The window is applied AFTER filtering in every mode, so `lines` counts
    lines you will actually see — not lines that were considered.
    """
    import re
    log_path = f"/Users/ducorn/DC/logs/flow_{slug}.log"
    if not os.path.exists(log_path):
        return {"lines": [], "exists": False}

    with open(log_path, 'r', errors='ignore') as f:
        all_lines = f.readlines()

    ANSI = re.compile(r"\\x1b\\[[0-9;]*[A-Za-z]")
    BOX = ['─', '│', '╭', '╰', '├', '└', '┌', '┐', '┘', '┤', '╮', '╯', '▰', '▱']

    # Lines the PIPELINE prints about itself, as opposed to CrewAI's rendering
    # of a prompt. These markers are what langgraph_flow and skill_runner emit.
    STEP_MARKERS = ("💳", "🔒", "🔑", "🧠", "📋", "🔬", "🎨", "🔨", "🔍", "🚀",
                    "⚙", "🔔", "▶", "❌", "⚠", "✅", "🎛")
    STEP_PHRASES = ("Gate ", "Skill 0", "VERDICT:", "FAILED", "Approval request",
                    "routing to design", "billed to", "variants rendered",
                    "complete")

    parsed = []
    for line in all_lines:
        line = ANSI.sub("", line).rstrip()
        if not line.strip():
            continue

        if mode != "raw":
            # Tidying only applies when tidiness was asked for. In raw mode
            # nothing is hidden — that is the entire point of raw.
            if any(c in line for c in BOX):
                continue
            if re.match(r'^[\\s\\-=\\*\\.]+$', line):
                continue
            if len(line) < 4:
                continue
            if any(x in line for x in ['Tracing', 'telemetry', 'opentelemetry',
                                       'OPENTELEMETRY']):
                continue

        if mode == "steps":
            head = line.lstrip()[:8]
            if not (any(m in head for m in STEP_MARKERS)
                    or any(p in line for p in STEP_PHRASES)):
                continue
''')

# ── 2. Window after filtering, plus the never-empty guarantee ────────────────
swap("tail and fallback", '''        parsed.append({"text": line, "color": color})

    return {
        "lines": parsed,
        "exists": True,
        "total_lines": len(all_lines),
        "log_path": log_path
    }''',
'''        parsed.append({"text": line, "color": color})

    # A filter that matched nothing, on a file that has content, is a bug in
    # the filter — not an empty log. Fall back rather than show a blank panel
    # and let someone wonder whether the pipeline died.
    fell_back = False
    if not parsed and all_lines and mode != "raw":
        fell_back = True
        for line in all_lines:
            line = ANSI.sub("", line).rstrip()
            if line.strip():
                parsed.append({"text": line, "color": "#8a9ba8"})

    # NOW take the window — of lines that survived, not raw ones.
    shown = parsed[-lines:] if lines and lines > 0 else parsed

    return {
        "lines": shown,
        "exists": True,
        "mode": ("raw (fell back — no lines matched)" if fell_back else mode),
        "shown": len(shown),
        "matched": len(parsed),
        "total_lines": len(all_lines),
        "log_path": log_path
    }''')


# ── 3. Kill endpoint ─────────────────────────────────────────────────────────
swap("kill endpoint", '''# ── BUDGET CHECK ──────''',
'''@app.post("/pipeline/kill/{slug}")
def pipeline_kill(slug: str):
    """
    Stop a running pipeline without deleting anything.

    Deliberately distinct from scripts/delete_run.py: a runaway loop needs
    stopping AND keeping, so the log and partial output survive for reading.
    Nothing here is removed.
    """
    import re as _re
    import signal
    import subprocess as _sp
    import time as _t

    if not _re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", slug or ""):
        return JSONResponse({"error": "bad slug"}, status_code=400)

    try:
        out = _sp.run(["pgrep", "-fl", "langgraph_flow.py"],
                      capture_output=True, text=True, timeout=10).stdout
    except Exception as e:
        return JSONResponse({"error": f"could not list processes: {e}"},
                            status_code=500)

    pids = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        # Whole-argument match: stopping 'foo' must not kill a run of 'foo-v2'.
        if any(a == slug for a in " ".join(parts[1:]).split()):
            pids.append(int(parts[0]))

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if pids:
        _t.sleep(3)

    killed, forced = [], []
    for pid in pids:
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            forced.append(pid)
        except ProcessLookupError:
            killed.append(pid)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE pipeline_runs SET status='stopped', "
                        "updated_at=NOW() WHERE slug=%s", (slug,))
            # A stopped run's pending approvals would otherwise sit in Slack
            # forever, and approving one would start a phase of a dead run.
            cur.execute("UPDATE approval_requests SET status='cancelled' "
                        "WHERE product_slug=%s AND status='pending'", (slug,))
            conn.commit()
    finally:
        conn.close()

    if not pids:
        return {"status": "not_running", "slug": slug, "killed": [],
                "message": f"No process found for {slug}. The run is marked "
                           f"stopped and any pending approvals cancelled."}

    return {"status": "stopped", "slug": slug,
            "killed": killed, "force_killed": forced,
            "message": f"Stopped {len(pids)} process(es). Nothing was deleted "
                       f"— use scripts/delete_run.py to remove the run."}


# ── BUDGET CHECK ──────''')

backup = API.with_name(f"main.backup-logkill-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(API, backup)
API.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, API)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup}")
print()
print("After restarting the API:")
print("  curl -s -H \"x-api-key: $DUCORN_API_TOKEN\" "
      "'localhost:8000/pipeline/log/<slug>?lines=40' | python3 -m json.tool | head")
print("  curl -s -X POST -H \"x-api-key: $DUCORN_API_TOKEN\" "
      "localhost:8000/pipeline/kill/<slug>")
