#!/usr/bin/env python3
"""
Make approvals say what they release, instead of Slack guessing from prose.

Run migration 001 first:
    python3 scripts/migrate.py --status
    python3 scripts/migrate.py

Touches four files, all or nothing:

  ducorn_db.py       request_approval() records next_phase and product_slug
  langgraph_flow.py  _request_approval() takes them; each gate passes its own
  slack_bot.py       cmd_approve() reads the row instead of matching titles
  main.py            the resume whitelist stops silently defaulting to build

WHAT THIS REPLACES
------------------
cmd_approve had four near-identical branches, each keyed on a title substring
and each copy-pasting ~30 lines of subprocess.Popen. Collapsing them to one
path removes the duplication and two real bugs that were hiding in it:

  * _db_complexity is used in the Popen of two branches but only assigned
    inside `if _row:`. A product with no pipeline_runs row raises NameError
    mid-approval — the request is already marked approved by then, so the run
    is left approved and not started.

  * the "QA Passed" branch opens its log with 'w', truncating the whole log
    for that product at the moment you most want to read it. The others use
    'a'. Now there is one call and one mode.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

DB    = Path("/Users/ducorn/DC/scripts/ducorn_db.py")
FLOW  = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
SLACK = Path("/Users/ducorn/DC/scripts/slack_bot.py")
API   = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


# ── 1. ducorn_db.request_approval ────────────────────────────────────────────
d = DB.read_text(encoding="utf-8")
if "next_phase" in d:
    sys.exit("Already patched — next_phase is in ducorn_db.py.")

# Two narrow anchors rather than one block: the INSERT line in this file ends
# in a trailing space, which a pasted anchor does not reproduce. Match the parts
# that carry meaning, never the whitespace around them.
d = swap(DB, "request_approval sig", d,
'''def request_approval(requested_by, title, description, document_path=None):
    """Agent requests founder approval"""''',
'''def request_approval(requested_by, title, description, document_path=None,
                     next_phase=None, product_slug=None):
    """
    Agent requests founder approval.

    next_phase / product_slug say what granting this approval should start.
    Both are optional so existing callers keep working, but a gate that omits
    them produces an approval the Slack bot can only act on by parsing its
    title — which is the failure these columns exist to end.
    """''')

d = swap(DB, "request_approval cols", d,
'''                (requested_by, title, description, document_path)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (requested_by, title, description, document_path))''',
'''                (requested_by, title, description, document_path,
                 next_phase, product_slug)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (requested_by, title, description, document_path,
              next_phase, product_slug))''')
edits.append((DB, d, "approval"))


# ── 2. langgraph_flow._request_approval and the gates ────────────────────────
f = FLOW.read_text(encoding="utf-8")
if "next_phase" in f:
    sys.exit("Already patched — next_phase is in langgraph_flow.py.")
if "node_design" not in f:
    # Order matters and the two patches depend on each other:
    #   this patch's gate_1 calls _load_run_settings(), which patch B adds
    #   patch B's gate_2 needs the _request_approval signature this patch adds
    # So B goes first and this one finishes the wiring. Applying them the other
    # way round leaves gate_2 raising TypeError at the moment a founder
    # approves a design.
    sys.exit("Run patch_design_node.py FIRST — this patch wires gate_2, which "
             "that patch creates, and uses _load_run_settings() from it.")

f = swap(FLOW, "_request_approval", f,
'''def _request_approval(title: str, description: str) -> int:
    """Insert approval request into DB and return ID."""
    try:
        sys.path.insert(0, '/Users/ducorn/DC/scripts')
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO approval_requests (requested_by, title, description, status)
                VALUES ('atlas', %s, %s, 'pending')
                RETURNING id
            """, (title, description))''',
'''def _request_approval(title: str, description: str,
                      next_phase: str = None, topic: str = None) -> int:
    """
    Insert approval request into DB and return ID.

    next_phase is what granting this releases. Pass it. An approval without
    one can only be acted on by matching its title text, and a gate added
    later posts a title nothing matches — which is how a design gate could be
    approved in Slack and start nothing.
    """
    try:
        sys.path.insert(0, '/Users/ducorn/DC/scripts')
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO approval_requests
                    (requested_by, title, description, status,
                     next_phase, product_slug)
                VALUES ('atlas', %s, %s, 'pending', %s, %s)
                RETURNING id
            """, (title, description, next_phase, topic))''')

# Each gate declares its own successor.
f = swap(FLOW, "gate_1 call", f,
'''            f"PRD Ready — approve to build: {topic}",
            f"SAGE has completed research. PRD ready at docs/{topic}-PRD.md"
        )''',
'''            f"PRD Ready — approve to build: {topic}",
            f"SAGE has completed research. PRD ready at docs/{topic}-PRD.md",
            # A UI product is designed before it is built. Reading it here, at
            # approval time, means toggling HAS UI after starting still works.
            next_phase=("design" if _load_run_settings(topic).get("has_ui")
                        else "build"),
            topic=topic,
        )''')

# The keywords go AFTER the description, not between the two positional args —
# an earlier attempt inserted them straight after the title and produced
# "positional argument follows keyword argument". Anchor on the last positional.
f = swap(FLOW, "gate_2 call", f,
'''            f"DESIGN produced {len(variants)} variants in products/{topic}/design/"
        )''',
'''            f"DESIGN produced {len(variants)} variants in products/{topic}/design/",
            next_phase="build", topic=topic,
        )''')

f = swap(FLOW, "gate_3 call", f,
'''            f"IRIS QA passed. Ready to launch {topic}."
        )''',
'''            f"IRIS QA passed. Ready to launch {topic}.",
            next_phase="launch", topic=topic,
        )''')

f = swap(FLOW, "gate_4 call", f,
'''            f"QA passed. Ready to deploy {topic} as a live service."
        )''',
'''            f"QA passed. Ready to deploy {topic} as a live service.",
            next_phase="deploy", topic=topic,
        )''')
edits.append((FLOW, f, "flow"))


# ── 3. slack_bot.cmd_approve — one path, not four ────────────────────────────
sb = SLACK.read_text(encoding="utf-8")
if "next_phase" in sb:
    sys.exit("Already patched — next_phase is in slack_bot.py.")

sb = swap(SLACK, "select", sb,
          '''cur.execute("SELECT title, description FROM approval_requests WHERE id=%s", (approval_id,))''',
          '''cur.execute("SELECT title, description, next_phase, product_slug "
                        "FROM approval_requests WHERE id=%s", (approval_id,))''')

lines = sb.splitlines(keepends=True)
start = [i for i, l in enumerate(lines)
         if "# Detect which pipeline phase to trigger next" in l]
# cmd_approve is not the only function with `except ValueError:` — take the
# first one AFTER the dispatch comment, not the only one in the file.
if len(start) != 1:
    sys.exit(f"ANCHOR MISS [slack_bot:dispatch start]: found {len(start)}, "
             f"expected 1. NOTHING WRITTEN.")
end = [i for i, l in enumerate(lines)
       if l.startswith("    except ValueError:") and i > start[0]]
if not end:
    sys.exit("ANCHOR MISS [slack_bot:dispatch end]: no 'except ValueError:' "
             "after the dispatch block. NOTHING WRITTEN.")
end = [end[0]]

NEW_DISPATCH = '''        # What to run next is recorded on the approval by the gate that raised
        # it. Four copy-pasted branches keyed on title substrings used to live
        # here; they could not see a gate added after they were written, and a
        # reworded Slack message silently broke the pipeline.
        next_phase   = row[2]
        topic        = row[3]

        if not next_phase or not topic:
            # Approvals created before migration 001. Parse the old way, once,
            # and say so — this path should stop appearing within a day or two.
            legacy = {
                "PRD exists — reuse or redo research:": "build",
                "PRD Ready — approve to build:":        "build",
                "UI designs ready — approve to build:": "build",
                "QA Passed — approve to launch:":       "launch",
                "Deploy to production:":                "deploy",
            }
            for prefix, phase in legacy.items():
                if prefix in title:
                    next_phase = next_phase or phase
                    topic = topic or title.replace(prefix, "").strip()
                    print(f"[approve] {approval_id}: pre-migration approval, "
                          f"phase inferred from title -> {next_phase}")
                    break

        if not next_phase or not topic:
            # Loud, and NOT a guess. Defaulting to build here is how an
            # unrecognised gate used to skip straight past the work it gated.
            say(f"⚠️ Approved, but I cannot tell what `{title}` should start "
                f"(no next_phase recorded). Nothing was launched — start the "
                f"phase from the dashboard.")
            print(f"[approve] {approval_id}: no next_phase and title matched "
                  f"nothing: {title!r}")
            return

        _db_engine, _db_coder, _db_complexity = "fast", "crewai", "simple"
        try:
            from ducorn_db import get_conn as _gc
            with _gc() as _conn:
                _cur = _conn.cursor()
                _cur.execute("SELECT build_engine, coder, complexity "
                             "FROM pipeline_runs WHERE slug=%s", (topic,))
                _row = _cur.fetchone()
                if _row:
                    # Assigned together with the defaults above, so a product
                    # with no row cannot NameError halfway through a Popen the
                    # way the old build branches could.
                    _db_engine     = _row[0] or "fast"
                    _db_coder      = _row[1] or "crewai"
                    _db_complexity = _row[2] or "simple"
        except Exception as _e:
            print(f"[approve] DB read failed for {topic}: {_e} — using defaults")

        emoji = {"design": "🎨", "build": "🔨", "qa": "🔍",
                 "launch": "🚀", "deploy": "⚙️"}.get(next_phase, "▶️")
        say(f"{emoji} *ATLAS: starting `{next_phase}` for `{topic}`...*")

        import subprocess
        log_path = f"/Users/ducorn/DC/logs/flow_{topic}.log"
        subprocess.Popen(
            ["/Users/ducorn/DC/ducorn/.venv/bin/python", "-u",
             "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
             topic, "--phase", next_phase,
             "--engine", _db_engine,
             "--complexity", _db_complexity,
             "--coder", _db_coder],
            # Append. One of the old branches opened this 'w' and truncated the
            # whole log for the product at the moment you most want to read it.
            stdout=open(log_path, 'a'),
            stderr=subprocess.STDOUT,
            env={**os.environ,
                 "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
                 "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
                 "OPENAI_BASE_URL": "http://localhost:4001/v1",
                 "CREWAI_TOOLS_ALLOW_UNSAFE_PATHS": "true"}
        )

'''
lines[start[0]:end[0]] = [NEW_DISPATCH]
sb = "".join(lines)
applied.append(f"{SLACK.name}:dispatch")
edits.append((SLACK, sb, "slack"))


# ── 4. main.py resume whitelist ──────────────────────────────────────────────
a = API.read_text(encoding="utf-8")
if '"design", "gate_2"' in a:
    sys.exit("Already patched — main.py knows the design phases.")

a = swap(API, "resume phases", a,
'''                if _phase in ["research", "gate_1", "build", "qa", "gate_3", "launch", "gate_4", "deploy"]:
                    db_phase = _phase''',
'''                # Must list every node in langgraph_flow's graph. An unlisted
                # phase used to fall through to `db_phase or "build"` below,
                # which silently resumed past whatever it did not recognise.
                _known = ["research", "gate_1", "design", "gate_2", "build",
                          "qa", "qa_fix", "gate_3", "launch", "gate_4", "deploy"]
                if _phase in _known:
                    db_phase = _phase
                elif _phase:
                    print(f"[resume] {slug}: checkpoint phase {_phase!r} is not "
                          f"a known node — add it to _known rather than letting "
                          f"this default to build")''')
edits.append((API, a, "api"))


# ── Write once every anchor has hit ──────────────────────────────────────────
for path, text, tag in edits:
    backup = path.with_name(f"{path.stem}.backup-approval-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")
    print(f"backup: {backup.name}")

import ast
for path, _, _ in edits:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — restore from the backups above")

print("\napplied: " + ", ".join(applied))
print()
print("Restart the API and the Slack bot so they load the new code.")
