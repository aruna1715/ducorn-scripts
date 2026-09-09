#!/usr/bin/env python3
"""
Point the flow's two Slack posters at the one module that knows the board.

    cd ~/DC && python3 scripts/patch_slack_one_board.py            show
    cd ~/DC && python3 scripts/patch_slack_one_board.py --apply    do it

Needs scripts/ducorn_slack.py and scripts/patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

langgraph_flow has two Slack functions and each carries its own copy of the
channel:

    _post_slack         chat_postMessage(channel='#duc-board')     works
    _post_slack_images  files_upload_v2(channel="#duc-board")      does not

files_upload_v2 requires the channel ID. Same literal, two APIs, one of them
silently broken since it was written — every design screenshot the pipeline
has produced failed to upload, and gate 2 has been asking the founder to pick
a UI direction from links alone.

Fixing the literal in place would leave two copies of it, and the next Slack
call added would be a coin flip on which spelling it copied.

── AND THE MESSAGE THE FOUNDER READS ────────────────────────────────────────

The reason went into the gate message raw and truncated:

    ⚠️  Designs shown as links only (SlackApiError: The request to the Slack
    API failed. (url: https://slack.com/api/files.completeUploadExternal)
    The server responded with: {'ok': False, 'error': 'invalid_argume) —

ducorn_slack.reason_for turns that into "the board channel id was not
accepted by Slack". The traceback still goes to the run log, where it is
useful, and out of the decision, where it is not.

── AFTER THIS ───────────────────────────────────────────────────────────────

If the bot cannot list channels, set SLACK_BOARD_CHANNEL_ID in shared/.env
and no lookup happens at all. python3 scripts/ducorn_slack.py says which.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
DS = DC / "scripts" / "ducorn_slack.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "oneboard"

OLD_POST = '''def _post_slack(msg: str):
    try:
        from slack_sdk import WebClient
        client = WebClient(token=os.environ.get('SLACK_BOT_TOKEN', ''))
        client.chat_postMessage(channel='#duc-board', text=msg)
    except Exception as e:
        print(f"Slack error: {e}")'''

NEW_POST = '''def _post_slack(msg: str):
    # The board is addressed in one place. This function and
    # _post_slack_images each used to carry the literal '#duc-board', and
    # files_upload_v2 rejects a name where chat_postMessage accepts one — so
    # one of the two copies was broken from the day it was written.
    import ducorn_slack as _ds
    reason = _ds.post(msg)
    if reason:
        print(f"Slack error: {reason}")'''

OLD_IMG = '''    if not uploads:
        return "no images to post"
    try:
        from slack_sdk import WebClient
        client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))
        client.files_upload_v2(
            channel="#duc-board",
            initial_comment=comment,
            file_uploads=[{"file": str(u["file"]), "title": u["title"]}
                          for u in uploads],
        )
        return ""
    except Exception as e:
        # files:write is a separate scope from chat:write. If this is the
        # first upload the app has ever attempted, that is the likely cause.
        print(f"Slack image upload failed: {type(e).__name__}: {e}")
        return f"{type(e).__name__}: {str(e)[:160]}"'''

NEW_IMG = '''    # One board, one addressing rule, and a reason a person can read.
    #
    # This used to pass channel="#duc-board" to files_upload_v2, which wants
    # an ID and rejects a name — so no design screenshot has ever reached
    # Slack. It also returned str(e)[:160], and that string goes into the
    # gate-2 message, so the founder chose a UI direction underneath a Slack
    # error cut off mid-word.
    import ducorn_slack as _ds
    return _ds.post_images(uploads, comment)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (FLOW, DS, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

r = subprocess.run([sys.executable, str(DS), "--test"],
                   capture_output=True, text=True)
if "ducorn_slack OK" not in r.stdout:
    sys.exit(f"NOTHING DONE — ducorn_slack fails its own tests:\n{r.stdout}"
             f"{r.stderr[-300:]}")
print("patch_slack_one_board\n")
print("  ok  ducorn_slack passes its self-test")

src = FLOW.read_text(encoding="utf-8")
if "import ducorn_slack" in src:
    sys.exit("NOTHING DONE — the flow already uses ducorn_slack.")

bad = False
for label, a in [("_post_slack", OLD_POST), ("_post_slack_images body", OLD_IMG)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(FLOW, FLOW.with_suffix(f".backup-{TAG}-{stamp}.py"))
FLOW.write_text(src.replace(OLD_POST, NEW_POST, 1).replace(OLD_IMG, NEW_IMG, 1),
                encoding="utf-8")
print(f"\nwrote {FLOW.name}, backup tagged {TAG}-{stamp}")

after = FLOW.read_text(encoding="utf-8")
try:
    py_ok(after, "langgraph_flow.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# The literal must be gone from CODE. Both new comments name it, which is
# exactly the trap that has caught four checks in this repo.
code = code_only(after)
if "duc-board" in code:
    sys.exit("⚠️  a '#duc-board' literal is still in the code — restore the "
             "backup.")
if "files_upload_v2" in code:
    sys.exit("⚠️  the flow still uploads directly — restore the backup.")
print("verified: it parses; no board literal and no direct upload remain in "
      "code.")

print("""
  python3 scripts/ducorn_slack.py

That resolves the channel and posts NOTHING. If it cannot resolve it, add the
id to shared/.env and re-run:

  SLACK_BOARD_CHANNEL_ID=C0XXXXXXXXX

The current gate-2 message is already sent and will not gain its pictures —
this is for the next gate. The three design links in it work.
""")
