#!/usr/bin/env python3
"""
Posting to the DuCorn board. One place that knows how.

    import ducorn_slack as ds
    ds.post("something happened")
    reason = ds.post_images([{"file": p, "title": "Variant A"}], "3 designs")

Install as scripts/ducorn_slack.py. Check it:

    python3 scripts/ducorn_slack.py --check     resolve the channel, post nothing
    python3 scripts/ducorn_slack.py --test      the reason-phrasing rules

── THE BUG THIS EXISTS FOR ──────────────────────────────────────────────────

Gate 2 of the admin rebuild posted its message and none of its pictures:

    files.completeUploadExternal
    input must match regex ^[CGDZ][A-Z0-9]{8,}$ [json-pointer:/channel_id]

chat_postMessage accepts a channel NAME — "#duc-board" — and files_upload_v2
does not; it wants the channel ID. One literal was used for both, so every
design screenshot the pipeline has ever produced failed to upload, and the
founder has been choosing UI directions from links alone.

The second half was worse. The failure reason went into the founder's own
decision message as a truncated exception:

    ⚠️  Designs shown as links only (SlackApiError: The request to the Slack
    API failed. (url: https://slack.com/api/files.completeUploadExternal)
    The server responded with: {'ok': False, 'error': 'invalid_argume) —

cut off mid-word, at the exact moment a person is deciding something. A
reason a person reads should be a sentence, and the traceback belongs in the
log where it already is.

── HOW THE CHANNEL IS FOUND ─────────────────────────────────────────────────

    SLACK_BOARD_CHANNEL_ID   if set, used. No lookup, no scope needed.
    otherwise                resolved once from the name via conversations.list
                             and remembered for the life of the process

The lookup needs channels:read, which the app may not have. If neither works
you get a sentence saying to set the variable — not a regex from Slack.
"""
from __future__ import annotations

import os

# shared/.env, here, at import.
#
# The first version read os.environ and nothing else, so
# SLACK_BOARD_CHANNEL_ID was invisible to anything that had not already
# loaded the env file — and `python3 scripts/ducorn_slack.py` reported "the
# board channel could not be looked up" for a variable sitting in
# shared/.env. langgraph_flow happens to call load_ducorn_env at import, so
# the pipeline was fine and only the check was wrong, which is the worst way
# for a check to be wrong.
try:
    from ducorn_env import load_ducorn_env as _load_env
    _load_env()
except Exception:
    pass          # not on the path: the caller's environment is what there is

__all__ = ["post", "post_images", "board_channel", "reason_for", "SlackNotReady"]

BOARD_NAME = os.environ.get("SLACK_BOARD_CHANNEL", "#duc-board")
_resolved = None


class SlackNotReady(RuntimeError):
    """The board cannot be addressed, with a sentence saying why."""


def _client():
    try:
        from slack_sdk import WebClient
    except ImportError:
        # NOT a Slack problem, and it must not be reported as one. Running
        # this under the system python3 said "the board channel could not be
        # looked up (ModuleNotFoundError)" and advised setting a variable
        # that was already set — a diagnosis pointing at the wrong thing
        # costs more than no diagnosis.
        raise SlackNotReady(
            "slack_sdk is not installed in this interpreter — run it under "
            "ducorn/.venv/bin/python, which is what the pipeline uses") from None
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise SlackNotReady("SLACK_BOT_TOKEN is not set")
    return WebClient(token=token)


def board_channel() -> str:
    """
    The board's channel ID.

    files_upload_v2 rejects a name; chat_postMessage accepts an ID. So an ID
    is what both get, and there is one answer instead of two spellings.
    """
    global _resolved
    if _resolved:
        return _resolved

    env = os.environ.get("SLACK_BOARD_CHANNEL_ID", "").strip()
    if env:
        _resolved = env
        return _resolved

    want = BOARD_NAME.lstrip("#")
    try:
        client = _client()
        cursor = None
        for _ in range(10):                       # bounded, not while True
            r = client.conversations_list(
                types="public_channel,private_channel", limit=200,
                cursor=cursor)
            for ch in r.get("channels", []):
                if ch.get("name") == want:
                    _resolved = ch["id"]
                    return _resolved
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except SlackNotReady:
        raise
    except Exception as e:
        raise SlackNotReady(
            f"the board channel could not be looked up ({type(e).__name__}) — "
            f"set SLACK_BOARD_CHANNEL_ID in shared/.env") from e

    raise SlackNotReady(
        f"no channel named {BOARD_NAME} was visible to this bot — set "
        f"SLACK_BOARD_CHANNEL_ID in shared/.env, or invite the bot to it")


def reason_for(e: Exception) -> str:
    """
    A failure as a SENTENCE, for a message a person reads.

    The traceback still goes to the log. What goes in front of the founder at
    a gate is the one thing they can act on.
    """
    if isinstance(e, SlackNotReady):
        return str(e)
    text = str(e)
    if "missing_scope" in text or "not_allowed_token_type" in text:
        return "the bot is missing the files:write scope"
    if "channel_not_found" in text or "channel_id" in text:
        return "the board channel id was not accepted by Slack"
    if "invalid_auth" in text or "token_revoked" in text:
        return "the Slack token was rejected — it may need rotating"
    if "ratelimited" in text:
        return "Slack rate-limited the upload"
    # Unknown: name it, do not paste it. A truncated exception in a decision
    # message is what this function exists to stop.
    return f"the upload failed ({type(e).__name__}) — see the run log"


def post(text: str) -> str:
    """Post a message. Returns "" or a one-line reason."""
    try:
        _client().chat_postMessage(channel=board_channel(), text=text)
        return ""
    except Exception as e:
        print(f"Slack post failed: {type(e).__name__}: {e}", flush=True)
        return reason_for(e)


def post_images(uploads, comment: str = "") -> str:
    """
    Post images. uploads: [{"file": path, "title": str}].

    Returns "" on success or a one-line reason the caller can show a person.
    """
    if not uploads:
        return "there were no images to post"
    try:
        _client().files_upload_v2(
            channel=board_channel(),
            initial_comment=comment,
            file_uploads=[{"file": str(u["file"]), "title": u["title"]}
                          for u in uploads],
        )
        return ""
    except Exception as e:
        print(f"Slack image upload failed: {type(e).__name__}: {e}", flush=True)
        return reason_for(e)


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        class Fake(Exception):
            pass

        bad = []
        long_slack = Fake(
            "The request to the Slack API failed. (url: https://slack.com/"
            "api/files.completeUploadExternal) The server responded with: "
            "{'ok': False, 'error': 'invalid_arguments', 'response_metadata': "
            "{'messages': ['[ERROR] input must match regex pattern: "
            "^[CGDZ][A-Z0-9]{8,}$ [json-pointer:/channel_id]']}}")
        r = reason_for(long_slack)
        if len(r) > 90:
            bad.append(f"a reason is still {len(r)} chars long")
        if "http" in r or "{" in r:
            bad.append("a reason still pastes the raw API response")
        if reason_for(Fake("missing_scope")) != \
                "the bot is missing the files:write scope":
            bad.append("a missing scope is not named plainly")
        if reason_for(SlackNotReady("SLACK_BOT_TOKEN is not set")) != \
                "SLACK_BOT_TOKEN is not set":
            bad.append("a SlackNotReady sentence was rewritten")
        # A missing library must not be reported as a Slack failure.
        import builtins as _b
        _real = _b.__import__

        def _no_sdk(name, *a, **k):
            if name == "slack_sdk":
                raise ImportError("no slack_sdk")
            return _real(name, *a, **k)
        _b.__import__ = _no_sdk
        try:
            _client()
            bad.append("a missing slack_sdk did not raise")
        except SlackNotReady as ex:
            if "slack_sdk is not installed" not in str(ex):
                bad.append(f"a missing library is misreported as {ex!s}")
        except Exception as ex:
            bad.append(f"a missing library raised {type(ex).__name__}")
        finally:
            _b.__import__ = _real
        if not post_images([], "x").startswith("there were no images"):
            bad.append("an empty upload does not explain itself")
        print("ducorn_slack OK" if not bad else "ducorn_slack BAD\n  "
              + "\n  ".join(bad))
        raise SystemExit(0 if not bad else 1)

    try:
        print(f"board {BOARD_NAME} resolves to {board_channel()}")
        print("Nothing was posted. files_upload_v2 will accept this id.")
    except SlackNotReady as e:
        raise SystemExit(f"NOT READY — {e}")
