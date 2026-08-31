#!/usr/bin/env python3
"""
Remove the dead dashboard approval code and stop the approve endpoint
trusting a phase from the request body.

WHY
---
The dashboard's approve/reject BUTTONS were removed some time ago — Vijay
confirmed it and renderApprovals() only prints the Slack command to copy. But
approveItem() and rejectItem() are still defined, along with the .approve-btn
/ .btn-approve / .btn-reject CSS, and approveItem still contains exactly the
title-matching dispatch that was deleted from slack_bot.py this morning:

    if (title.includes("approve to build:")) { phase = "build"; }

Nothing calls it, so nothing is broken. But it is a working, wrong
implementation of the thing we just fixed, sitting one keystroke away from
being wired back up by anyone who sees an approval card with no button and
thinks that looks like an oversight. Dead code that disagrees with live code
is worse than no code.

Separately, POST /pipeline/approve/{slug} takes `phase` from the request body:

    phase = body.get("phase", "build")

so any caller with the API key can start any phase for any product, and the
default is `build` — which for a has_ui product means skipping the design gate.
There is no caller today. It is a loaded gun sitting next to the gate we just
built, and the fix is the same one applied to Slack: read next_phase from the
approval row, because the gate that raised it already wrote down what it
releases.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

DASH = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
API  = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


def replace_block(path, label, text, start_needle, end_needle, new_text):
    """
    Replace whole lines from `start_needle` up to (not including) `end_needle`.

    Line-based on purpose. Three anchors today have missed on trailing
    whitespace inside pasted SQL — "UPDATE approval_requests " with a space
    before the newline is invisible in a diff and fatal to str.count(). Match
    the identifiers that carry meaning and let the whitespace be whatever it is.
    """
    lines = text.splitlines(keepends=True)
    s = [i for i, l in enumerate(lines) if start_needle in l]
    if len(s) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label} start]: {len(s)} matches for "
                 f"{start_needle!r}. NOTHING WRITTEN.")
    e = [i for i, l in enumerate(lines) if end_needle in l and i > s[0]]
    if not e:
        sys.exit(f"ANCHOR MISS [{path.name}:{label} end]: no {end_needle!r} "
                 f"after it. NOTHING WRITTEN.")
    lines[s[0]:e[0]] = [new_text]
    applied.append(f"{path.name}:{label}")
    return "".join(lines)


def cut(path, label, text, start_needle, end_needle):
    """Remove whole lines from the line containing start to the one before end."""
    lines = text.splitlines(keepends=True)
    s = [i for i, l in enumerate(lines) if start_needle in l]
    if len(s) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label} start]: {len(s)} matches for "
                 f"{start_needle!r}. NOTHING WRITTEN.")
    e = [i for i, l in enumerate(lines) if end_needle in l and i > s[0]]
    if not e:
        sys.exit(f"ANCHOR MISS [{path.name}:{label} end]: no {end_needle!r} "
                 f"after it. NOTHING WRITTEN.")
    del lines[s[0]:e[0]]
    applied.append(f"{path.name}:{label}")
    return "".join(lines)


# ── Dashboard ────────────────────────────────────────────────────────────────
d = DASH.read_text(encoding="utf-8")
if "async function approveItem" not in d:
    sys.exit("Already patched — approveItem is gone from the dashboard.")

d = cut(DASH, "dead approve/reject JS",
        d, "async function approveItem(id)", "async function syncToDrive()")

d = swap(DASH, "orphan css", d,
'''.approve-btn { cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.16em;padding:5px 13px;border-radius:2px;border:none;transition:all .2s; }
.btn-approve { background:rgba(var(--green-rgb),.18);color:var(--green);border:1px solid rgba(var(--green-rgb),.4); }
.btn-reject { background:rgba(var(--red-rgb),.12);color:var(--red);border:1px solid rgba(var(--red-rgb),.35); }
''', '''/* .approve-btn / .btn-approve / .btn-reject removed 2026-08-31 along with
   approveItem() and rejectItem(). Approval happens in Slack; the dashboard
   shows the pending item and the command to copy. */
''')
edits.append((DASH, d))


# ── API ──────────────────────────────────────────────────────────────────────
a = API.read_text(encoding="utf-8")
if "the gate that raised it" in a:
    sys.exit("Already patched — pipeline_approve reads next_phase.")

# Anchored on the docstring: `body = await request.json()` appears 12 times in
# this file, so the start needle has to be something only pipeline_approve has.
a = replace_block(API, "approve reads column", a,
                  '"""Approve pipeline and trigger next phase directly',
                  "# Read build_engine and coder from DB",
'''    """Approve a pipeline gate and start whatever that approval releases."""
    import subprocess

    body = await request.json()
    approval_id = body.get("approval_id")

    # The phase comes from the approval row, not the request body. The gate
    # that raised it wrote down what it releases; a caller does not get to say
    # "start build" for a product sitting at a design gate. The body's `phase`
    # is ignored — read, so a stale caller gets told rather than silently
    # having it honoured.
    if body.get("phase"):
        print(f"[pipeline/approve] ignoring phase={body['phase']!r} from the "
              f"request body — next_phase on the approval row decides")

    if not approval_id:
        return JSONResponse(
            {"error": "approval_id is required. The phase to start is read "
                      "from that approval, not from this request."},
            status_code=400)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT next_phase, product_slug, status "
                        "FROM approval_requests WHERE id=%s", (approval_id,))
            appr = cur.fetchone()
            if not appr:
                return JSONResponse({"error": f"approval {approval_id} not found"},
                                    status_code=404)
            if appr["status"] != "pending":
                return JSONResponse(
                    {"error": f"approval {approval_id} is already "
                              f"{appr['status']}"}, status_code=409)
            phase = appr["next_phase"]
            if not phase:
                return JSONResponse(
                    {"error": f"approval {approval_id} has no next_phase "
                              f"recorded, so there is nothing to start"},
                    status_code=422)
            if appr["product_slug"] and appr["product_slug"] != slug:
                return JSONResponse(
                    {"error": f"approval {approval_id} belongs to "
                              f"{appr['product_slug']}, not {slug}"},
                    status_code=409)
            cur.execute("""
                UPDATE approval_requests
                SET status='approved', decided_by='founder', decided_at=NOW()
                WHERE id=%s AND status='pending'
            """, (approval_id,))
            conn.commit()
    finally:
        conn.close()
''')
edits.append((API, a))


for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-lockapprove-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")

import ast
try:
    ast.parse(API.read_text(encoding="utf-8"))
except SyntaxError as e:
    sys.exit(f"SYNTAX ERROR in main.py ({e}) — restore from "
             f"*.backup-lockapprove-{stamp}.*")

# The dashboard is HTML, so no parser — check the obvious breakages instead.
d2 = DASH.read_text(encoding="utf-8")
for must_keep in ("function renderApprovals", "function syncToDrive",
                  "function dictateInto", "renderDesignModelPicker"):
    if must_keep not in d2:
        sys.exit(f"index.html lost {must_keep!r} — restore from "
                 f"*.backup-lockapprove-{stamp}.*")
if d2.count("<script") != DASH.with_name(
        f"index.backup-lockapprove-{stamp}.html").read_text().count("<script"):
    sys.exit("script tag count changed — restore from the backup")

print("applied: " + ", ".join(applied))
print(f"backups: *.backup-lockapprove-{stamp}.*")
print()
print("Restart the API. Hard-refresh the dashboard.")
