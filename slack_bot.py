#!/usr/bin/env python3
"""
DuCorn Slack Bolt Bot — slack_bot.py
Agent: REX (Engineering)
Purpose: Connects Vijay (CEO) and Aruna (CTO) to the DuCorn agent system via Slack.
Mode: Socket Mode (no exposed ports)
"""

import os
import sys
if "/Users/ducorn/DC/scripts" not in sys.path: sys.path.insert(0, "/Users/ducorn/DC/scripts")
from ducorn_env import load_ducorn_env
load_ducorn_env()

import sys
import subprocess
import traceback
import logging

# ── Path bootstrap ────────────────────────────────────────────────────────────
sys.path.insert(0, '/Users/ducorn/DC/scripts')
import ducorn_db  # noqa: E402

# ── Slack Bolt ────────────────────────────────────────────────────────────────
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ducorn.slack_bot")

# ── App initialisation ────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
BOARD_CHANNEL   = "#duc-board"
DIGEST_SCRIPT   = "/Users/ducorn/DC/scripts/ducorn_digest.py"

app = App(token=SLACK_BOT_TOKEN)


# ══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

def cmd_status(say):
    """Fetch today's agent activity from PostgreSQL and post a summary."""
    try:
        summary = ducorn_db.get_activity_summary()
        say(f"📊 *DuCorn Status*\n```{summary}```")
    except Exception:
        say(f"❌ Status command failed:\n```{traceback.format_exc()}```")


def cmd_digest(say):
    """Run the digest script and post the result."""
    try:
        say("⏳ Generating DuCorn digest — please wait...")
        result = subprocess.run(
            [sys.executable, DIGEST_SCRIPT],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout.strip() or result.stderr.strip()
        say(f"📋 *DuCorn Daily Brief*\n```{output[:3000]}```")
    except subprocess.TimeoutExpired:
        say("❌ Digest timed out after 120 seconds.")
    except Exception:
        say(f"❌ Digest command failed:\n```{traceback.format_exc()}```")

def cmd_approve(say, approval_id_str):
    """Approve a pending request — triggers next pipeline phase if applicable"""
    try:
        approval_id = int(approval_id_str)
        
        # Get the approval details before approving
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT title, description FROM approval_requests WHERE id=%s", (approval_id,))
            row = cur.fetchone()
        
        if not row:
            say(f"❌ Approval ID `{approval_id}` not found.")
            return
            
        title = row[0]
        ducorn_db.approve_request(approval_id, 'board')
        say(f"✅ *Approved:* `{title}`")
        
        # Detect which pipeline phase to trigger next
        import subprocess
        if "PRD exists — reuse or redo research:" in title:
            # Founder approved — reuse existing PRD, skip to build
            topic = title.replace("PRD exists — reuse or redo research:", "").strip()
            say(f"♻️ *ATLAS: Reusing existing PRD for `{topic}` — skipping research*")
            log_path = f"/Users/ducorn/DC/logs/flow_{topic}.log"
            _db_engine = "fast"
            _db_coder = "crewai"
            try:
                from ducorn_db import get_conn
                with get_conn() as _conn:
                    _cur = _conn.cursor()
                    _cur.execute("SELECT build_engine, coder, complexity FROM pipeline_runs WHERE slug=%s", (topic,))
                    _row = _cur.fetchone()
                    if _row:
                        _db_engine = _row[0] or "fast"
                        _db_coder = _row[1] or "crewai"
                        _db_complexity = _row[2] or "simple"
            except Exception as _e:
                print(f"DB read failed: {_e}")
            subprocess.Popen(
                ["/Users/ducorn/DC/ducorn/.venv/bin/python",
                 "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
                 topic, "--phase", "gate_1",
                 "--engine", _db_engine,
                 "--complexity", _db_complexity,
                 "--coder", _db_coder],
                stdout=open(log_path, 'a'),
                stderr=subprocess.STDOUT,
                env={**os.environ,
                     "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
                     "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
                     "OPENAI_BASE_URL": "http://localhost:4001/v1",
                     "CREWAI_TOOLS_ALLOW_UNSAFE_PATHS": "true"}
            )

        elif "PRD Ready — approve to build:" in title:
            topic = title.replace("PRD Ready — approve to build:", "").strip()
            say(f"🔨 *ATLAS: Starting build phase for `{topic}`...*")
            log_path = f"/Users/ducorn/DC/logs/flow_{topic}.log"
            # Read build_engine and coder from DB
            import sys as _sys
            _sys.path.insert(0, '/Users/ducorn/DC/scripts')
            _db_engine = "fast"
            _db_coder = "crewai"
            try:
                from ducorn_db import get_conn
                with get_conn() as _conn:
                    _cur = _conn.cursor()
                    _cur.execute("SELECT build_engine, coder, complexity FROM pipeline_runs WHERE slug=%s", (topic,))
                    _row = _cur.fetchone()
                    if _row:
                        _db_engine = _row[0] or "fast"
                        _db_coder = _row[1] or "crewai"
                        _db_complexity = _row[2] or "simple"
            except Exception as _e:
                print(f"DB read failed: {_e}")
            subprocess.Popen(
                ["/Users/ducorn/DC/ducorn/.venv/bin/python",
                 "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
                 topic, "--phase", "build",
                 "--engine", _db_engine,
                 "--complexity", _db_complexity,
                 "--coder", _db_coder],
                stdout=open(log_path, 'a'),
                stderr=subprocess.STDOUT,
                env={**os.environ,
                     "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
                     "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
                     "OPENAI_BASE_URL": "http://localhost:4001/v1",
                     "CREWAI_TOOLS_ALLOW_UNSAFE_PATHS": "true"}
            )
        elif "QA Passed — approve to launch:" in title:
            topic = title.replace("QA Passed — approve to launch:", "").strip()
            say(f"🚀 *ATLAS: Starting launch phase for `{topic}`...*")
            log_path = f"/Users/ducorn/DC/logs/flow_{topic}.log"
            subprocess.Popen(
                ["/Users/ducorn/DC/ducorn/.venv/bin/python",
                 "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
                 topic, "--phase", "launch"],
                stdout=open(log_path, 'w'),
                stderr=subprocess.STDOUT,
                env={**os.environ,
                     "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
                     "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
                     "OPENAI_BASE_URL": "http://localhost:4001/v1"}
            )
            
        elif "Deploy to production:" in title:
            topic = title.replace("Deploy to production:", "").strip()
            say(f"⚙️ *ATLAS: Deploying `{topic}` to production...*")
            log_path = f"/Users/ducorn/DC/logs/flow_{topic}.log"
            env_base = {**os.environ,
                "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
                "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
                "OPENAI_BASE_URL": "http://localhost:4001/v1",
                "CREWAI_TOOLS_ALLOW_UNSAFE_PATHS": "true"}
            subprocess.Popen(
                ["/Users/ducorn/DC/ducorn/.venv/bin/python",
                 "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
                 topic, "--phase", "deploy"],
                stdout=open(log_path, 'a'),
                stderr=subprocess.STDOUT,
                env=env_base
            )

    except ValueError:
        say(f"❌ Invalid ID: `{approval_id_str}`. Use: `@DuCorn approve <id>`")
    except Exception:
        say(f"❌ Approve failed:\n```{traceback.format_exc()}```")

def cmd_reject(say, approval_id_str):
    """Reject a pending request by ID."""
    try:
        approval_id = int(approval_id_str)
        # Get the title before rejecting to check if PRD decision
        title = ""
        try:
            import sys as _sys
            _sys.path.insert(0, '/Users/ducorn/DC/scripts')
            from ducorn_db import get_conn
            with get_conn() as _conn:
                _cur = _conn.cursor()
                _cur.execute("SELECT title FROM approval_requests WHERE id=%s", (approval_id,))
                _row = _cur.fetchone()
                if _row:
                    title = _row[0]
        except Exception:
            pass

        ducorn_db.reject_request(approval_id, 'board')
        say(f"🚫 Approval *#{approval_id}* rejected by board.")

        # If rejecting PRD reuse — start fresh research
        if "PRD exists — reuse or redo research:" in title:
            topic = title.replace("PRD exists — reuse or redo research:", "").strip()
            say(f"🔬 *ATLAS: Starting fresh research for `{topic}`*")
            import pathlib as _pl
            old_prd = _pl.Path(f"/Users/ducorn/DC/ducorn-products/docs/{topic}-PRD.md")
            if old_prd.exists():
                old_prd.unlink()
            log_path = f"/Users/ducorn/DC/logs/flow_{topic}.log"
            _db_engine = "fast"
            _db_coder = "crewai"
            try:
                from ducorn_db import get_conn
                with get_conn() as _conn:
                    _cur = _conn.cursor()
                    _cur.execute("SELECT build_engine, coder FROM pipeline_runs WHERE slug=%s", (topic,))
                    _row = _cur.fetchone()
                    if _row:
                        _db_engine = _row[0] or "fast"
                        _db_coder = _row[1] or "crewai"
            except Exception as _e:
                print(f"DB read failed: {_e}")
            subprocess.Popen(
                ["/Users/ducorn/DC/ducorn/.venv/bin/python",
                 "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
                 topic, "--phase", "research",
                 "--engine", _db_engine,
                 "--coder", _db_coder],
                stdout=open(log_path, 'a'),
                stderr=subprocess.STDOUT,
                env={**os.environ,
                     "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
                     "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
                     "OPENAI_BASE_URL": "http://localhost:4001/v1",
                     "CREWAI_TOOLS_ALLOW_UNSAFE_PATHS": "true"}
            )

    except ValueError:
        say(f"❌ Invalid approval ID: `{approval_id_str}`. Use: `@DuCorn reject <id>`")
    except Exception:
        say(f"❌ Reject command failed:\n```{traceback.format_exc()}```")


def cmd_pending(say):
    """List all pending founder approvals."""
    try:
        approvals = ducorn_db.get_pending_approvals()
        if not approvals:
            say("✅ No pending approvals.")
            return
        lines = ["*⏳ Pending Approvals*"]
        for a in approvals:
            lines.append(f"• *[{a['id']}]* {a['requested_by'].upper()}: {a['title']}")
            if a['description']:
                lines.append(f"  _{a['description'][:100]}_")
        say("\n".join(lines))
    except Exception:
        say(f"❌ Pending command failed:\n```{traceback.format_exc()}```")

def cmd_run(say, raw_input):
    if not raw_input:
        say("❌ Usage: `@DuCorn run <describe what you want built>`")
        return

    say("🧠 ATLAS is processing your request...")

    # Extract clean topic slug via Ollama — free, local
    import json, requests
    try:
        resp = requests.post('http://localhost:11434/api/generate', json={
            'model': 'qwen2.5:32b',
            'prompt': f"""Extract a short 3-5 word kebab-case topic slug from this request.
Reply with ONLY the slug. No explanation. No punctuation. Just the slug.
Examples:
- "I need a landing page for ATLAS" → atlas-landing-page
- "Build a weekly investor report tool" → weekly-investor-report
- "Create marketing content for PDF tool" → pdf-tool-marketing

Request: {raw_input}
Slug:""",
            'stream': False
        }, timeout=60)
        topic = resp.json().get('response', '').strip().lower()
        topic = ''.join(c for c in topic if c.isalnum() or c == '-')[:50]
    except Exception as e:
        # Fallback — slugify the raw input
        topic = raw_input.lower().replace(" ", "-")[:40]
        topic = ''.join(c for c in topic if c.isalnum() or c == '-')

    if not topic or len(topic) < 3:
        topic = raw_input.lower().replace(" ", "-")[:40]

    # Save pending topic
    pending = {"topic": topic, "original": raw_input}
    with open("/Users/ducorn/DC/shared/pending_run.json", "w") as f:
        json.dump(pending, f)

    say(
        f"🧠 *ATLAS understood your request:*\n"
        f"*You said:* _{raw_input}_\n"
        f"*Topic slug:* `{topic}`\n\n"
        f"✏️ Change: `@DuCorn run <different description>`"
    )
    
    # Store pending topic temporarily
    import json
    pending = {"topic": topic, "original": raw_input}
    with open("/Users/ducorn/DC/shared/pending_run.json", "w") as f:
        json.dump(pending, f)

def cmd_stop(say, topic):
    """Stop a running pipeline by slug."""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "langgraph_flow.py " + topic],
            capture_output=True, text=True
        )
        pids = [p for p in result.stdout.strip().split() if p.strip()]
        if not pids:
            say("⚠️ No running pipeline found for `" + topic + "`")
            return
        for pid in pids:
            subprocess.run(["kill", "-15", pid], capture_output=True)
        import sys as _sys
        _sys.path.insert(0, "/Users/ducorn/DC/scripts")
        try:
            from ducorn_db import get_conn
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE pipeline_runs SET status=%s, updated_at=NOW() WHERE slug=%s",
                            ("stopped", topic))
                cur.execute("UPDATE approval_requests SET status=%s WHERE status=%s AND title LIKE %s",
                            ("rejected", "pending", "%" + topic + "%"))
        except Exception as _e:
            print("DB update failed: " + str(_e))
        say("🛑 *Pipeline stopped:* `" + topic + "`\nCheckpoints preserved — `@DuCorn resume " + topic + "` to continue.")
    except Exception as e:
        say("❌ Stop failed: " + str(e)[:100])



def cmd_confirm(say, topic):
    """Confirm and start the pipeline for a topic"""
    import json, os, subprocess
    
    # Check if there's a pending topic
    pending_path = "/Users/ducorn/DC/shared/pending_run.json"
    if not topic and os.path.exists(pending_path):
        with open(pending_path) as f:
            pending = json.load(f)
        topic = pending.get("topic", "")
    
    if not topic:
        say("❌ No pending topic found. Use `@DuCorn run <description>` first.")
        return

    say(f"🚀 *ATLAS Pipeline starting for `{topic}`*\nResearch → Build → QA → Launch\n\nUpdates will appear in #duc-board as each gate completes.")
    
    log_path = f"/Users/ducorn/DC/logs/flow_{topic.replace(' ', '_')}.log"
    subprocess.Popen(
        ["/Users/ducorn/DC/ducorn/.venv/bin/python",
         "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
         topic, "--phase", "research"],
        stdout=open(log_path, 'w'),
        stderr=subprocess.STDOUT,
        env={**os.environ,
             "PYTHONPATH": "/Users/ducorn/DC/scripts:/Users/ducorn/DC/ducorn",
             "OPENAI_API_KEY": os.environ.get("LITELLM_KEY_ATLAS", ""),
             "OPENAI_BASE_URL": "http://localhost:4001/v1"}
    )
    
    # Clean up pending file
    if os.path.exists(pending_path):
        os.remove(pending_path)

def cmd_pdfs(say):
    """Convert all docs to PDF"""
    say("📄 Converting all documents to PDF...")
    import subprocess
    result = subprocess.run(
        ["python3.12", "/Users/ducorn/DC/scripts/convert_docs_to_pdf.py"],
        capture_output=True, text=True, env={**os.environ}
    )
    lines = [l for l in result.stdout.split('\n') if '✅' in l or 'Done' in l]
    say("📄 *PDF Conversion Complete*\n" + "\n".join(lines))

def cmd_pipeline_status(say):
    """Show current pipeline status from DB and flow logs"""
    try:
        import sys
        sys.path.insert(0, '/Users/ducorn/DC/scripts')
        import ducorn_db
        from ducorn_db import get_conn
        import glob
        import os

        # Get recent activity
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT agent_id, task_name, status, created_at 
                FROM agent_activity 
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY id DESC LIMIT 10
            """)
            rows = cur.fetchall()

        if not rows:
            say("📋 No pipeline activity in the last 24 hours.")
            return

        lines = ["📋 *DuCorn Pipeline Status*\n"]
        for row in rows:
            agent, task, status, created = row
            emoji = "✅" if status == "completed" else "🔄" if status == "started" else "❌"
            lines.append(f"{emoji} *{agent.upper()}*: {task} — `{status}`")

        # Check latest flow log
        flow_logs = sorted(glob.glob("/Users/ducorn/DC/logs/flow_*.log"), key=os.path.getmtime, reverse=True)
        if flow_logs:
            latest = flow_logs[0]
            topic = os.path.basename(latest).replace("flow_", "").replace(".log", "")
            lines.append(f"\n🌊 *Active flow:* `{topic}`")

        say("\n".join(lines))
    except Exception as e:
        say(f"❌ Status check failed: {e}")

def cmd_support(say, question):
    if not question:
        say("❌ Usage: `@DuCorn support <question>`")
        return
    say("🎧 *ECHO* is reviewing your support request...")
    import subprocess
    result = subprocess.run(
        ["python3.12", "/Users/ducorn/DC/scripts/echo_support.py"] + question.split(),
        capture_output=True, text=True, timeout=180,
        env={**os.environ}
    )
    if result.stdout:
        say(f"🎧 *ECHO Support Response*\n\n{result.stdout.strip()}")
    else:
        say(f"❌ ECHO error: {result.stderr[:200]}")

def cmd_kpis(say):
    """Show CLEO KPI report"""
    import subprocess
    result = subprocess.run(
        ["python3.12", "/Users/ducorn/DC/scripts/cleo_kpis.py"],
        capture_output=True, text=True, env={**os.environ}
    )
    if result.stdout:
        # Extract just the report section
        lines = result.stdout.strip().split('\n')
        report = '\n'.join(lines[:-2])  # exclude the JSON save line
        say(f"📊 *CLEO KPI Report*\n```{report}```")
    else:
        say(f"❌ CLEO error: {result.stderr[:200]}")

def cmd_sync(say):
    """Sync all docs to Google Drive"""
    say("☁️ *Syncing DuCorn documents to Google Drive...*")
    import subprocess
    result = subprocess.run(
        ["python3.12", "/Users/ducorn/DC/scripts/gdrive_sync.py"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        timeout=300
    )
    output = result.stdout + result.stderr
    lines = [l for l in output.split('\n')
             if any(x in l for x in ['Converted', 'Uploaded', 'Errors', 'COMPLETE'])]
    if lines:
        say(f"☁️ *Google Drive Sync Complete*\n```{''.join(lines)}```")
    else:
        say(f"☁️ *Google Drive Sync Complete*\nAll files synced successfully.")
        
def cmd_help(say):
    """List all available commands."""
    say(
        "*🤖 DuCorn Bot Commands*\n"
        "• `@DuCorn status` — Today's agent activity summary\n"
        "• `@DuCorn digest` — Generate and display daily board brief\n"
        "• `@DuCorn pending` — List all items awaiting founder approval\n"
        "• `@DuCorn approve <id>` — Approve a pending request\n"
                "• `@DuCorn stop <slug>` — Stop a running pipeline\n"
        "• `@DuCorn reject <id>` — Reject a pending request\n"
        "• `@DuCorn help` — Show this message\n"
        "• `@DuCorn run <topic>` — Run full autonomous pipeline (Research→Build→QA→Launch)\n"
        "• `@DuCorn ps` — Show current pipeline status\n"
        "• `@DuCorn pdfs` — Convert all documents to PDF\n"
        "• `@DuCorn support <question>` — Route support request to ECHO (free, local AI)\n"
        "• `@DuCorn kpis` — Show CLEO KPI report\n"
        "• `@DuCorn run <description>` — Describe what you want built in plain English\n"
                "• `@DuCorn sync` — Sync all documents to Google Drive\n"
    )

# ══════════════════════════════════════════════════════════════════════════════
# EVENT ROUTER
# ══════════════════════════════════════════════════════════════════════════════

@app.event("app_mention")
def handle_mention(event, say):
    """Route @DuCorn mentions to the correct command handler."""
    try:
        text = event.get("text", "")
        # Strip the bot mention (e.g. <@U12345>) from the front
        parts = text.split()
        tokens = [t.lower() for t in parts if not t.startswith("<@")]

        if not tokens:
            cmd_help(say)
            return

        command = tokens[0]

        if command == "status":
            cmd_status(say)
        elif command == "digest":
            cmd_digest(say)
        elif command == "pending":
            cmd_pending(say)
        elif command == "approve":
            arg = tokens[1] if len(tokens) > 1 else ""
            cmd_approve(say, arg)
        elif command == "reject":
            arg = tokens[1] if len(tokens) > 1 else ""
            cmd_reject(say, arg)
        elif command == "help":
            cmd_help(say)
        elif command == "run":
            topic = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            cmd_run(say, topic)
        elif command in ["pipeline", "pipeline-status", "ps"]:
            cmd_pipeline_status(say)
        elif command == "pdfs":
            cmd_pdfs(say)
        elif command == "support":
            question = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            cmd_support(say, question)
        elif command in ["kpis", "kpi"]:
            cmd_kpis(say)
        elif command == "stop":
            arg = tokens[1] if len(tokens) > 1 else ""
            cmd_stop(say, arg)
        elif command == "confirm":
            topic = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            cmd_confirm(say, topic)
        elif command == "sync":
            cmd_sync(say)
        else:
            say(
                f"❓ Unknown command: `{command}`\n"
                "Type `@DuCorn help` to see available commands."
            )

    except Exception:
        say(f"❌ Unexpected error:\n```{traceback.format_exc()}```")
        log.error("Unhandled exception in handle_mention", exc_info=True)

@app.event("message")
def handle_file_upload(event, say, client):
    """Monitor #duc-requirements for file uploads"""
    import json
    import requests as http
    from pdfminer.high_level import extract_text as pdf_extract

    channel_id = event.get("channel", "")
    files = event.get("files", [])

    if not files:
        return

    # Check if this is #duc-requirements
    try:
        channel_info = client.conversations_info(channel=channel_id)
        channel_name = channel_info["channel"]["name"]
        if channel_name != "duc-requirements":
            return
    except Exception:
        return

    for file_info in files:
        filename = file_info.get("name", "unknown")
        filetype = file_info.get("filetype", "")
        file_url = file_info.get("url_private", "")

        client.chat_postMessage(
            channel="#duc-requirements",
            text=f"📥 *Requirement received:* `{filename}`\nATLAS is reading it..."
        )

        try:
            headers = {"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}
            download = http.get(file_url, headers=headers, timeout=30)

            if filetype == "pdf":
                with open("/tmp/ducorn_requirement.pdf", "wb") as tmp:
                    tmp.write(download.content)
                content = pdf_extract("/tmp/ducorn_requirement.pdf")[:3000]
            else:
                content = download.text[:3000]

            # Extract topic via Ollama
            ollama = http.post('http://localhost:11434/api/generate', json={
                'model': 'qwen2.5:32b',
                'prompt': f"Extract a 3-5 word kebab-case topic slug. Reply ONLY with the slug.\nContent: {content[:500]}\nSlug:",
                'stream': False
            }, timeout=60)

            topic = ollama.json().get('response', '').strip().lower()
            topic = ''.join(c for c in topic if c.isalnum() or c == '-')[:50]

            if not topic or len(topic) < 3:
                topic = filename.lower().replace(".", "-").replace(" ", "-")[:40]

            # Save pending
            pending = {"topic": topic, "original": f"Document: {filename}", "context": content[:2000]}
            with open("/Users/ducorn/DC/shared/pending_run.json", "w") as pf:
                json.dump(pending, pf)

            client.chat_postMessage(
                channel="#duc-board",
                text=(
                    f"📋 *ATLAS: Requirement Document Received*\n\n"
                    f"*File:* `{filename}`\n"
                    f"*Extracted topic:* `{topic}`\n\n"
                                f"✏️ Change: `@DuCorn run <different description>`"
                )
            )

        except Exception as e:
            client.chat_postMessage(
                channel="#duc-requirements",
                text=f"❌ Could not read `{filename}`: {str(e)[:200]}"
            )
 
@app.event("file_shared")
def handle_file_shared(event, client):
    print(f"[DuCorn] file_shared event received: {event}")
    """Handle file shared in any channel"""
    import os, json, requests as http
    
    file_id = event.get("file_id")
    channel_id = event.get("channel_id", "")
    
    # Check if it's #duc-requirements
    try:
        channel_info = client.conversations_info(channel=channel_id)
        channel_name = channel_info["channel"]["name"]
        if channel_name != "duc-requirements":
            return
    except Exception:
        return
    
    # Get file info
    try:
        file_info = client.files_info(file=file_id)["file"]
        filename = file_info.get("name", "unknown")
        filetype = file_info.get("filetype", "")
        file_url = file_info.get("url_private", "")
        
        client.chat_postMessage(
            channel="#duc-requirements",
            text=f"📥 *Requirement received:* `{filename}`\nATLAS is reading it..."
        )
        
        headers = {"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}
        download = http.get(file_url, headers=headers, timeout=30)
        
        if filetype == "pdf":
            with open("/tmp/ducorn_requirement.pdf", "wb") as tmp:
                tmp.write(download.content)
            from pdfminer.high_level import extract_text as pdf_extract
            content = pdf_extract("/tmp/ducorn_requirement.pdf")[:3000]
        else:
            content = download.text[:3000]

        # Extract topic via Ollama
        ollama = http.post('http://localhost:11434/api/generate', json={
            'model': 'qwen2.5:32b',
            'prompt': f"Extract a 3-5 word kebab-case topic slug. Reply ONLY with the slug.\nContent: {content[:500]}\nSlug:",
            'stream': False
        }, timeout=60)

        topic = ollama.json().get('response', '').strip().lower()
        topic = ''.join(c for c in topic if c.isalnum() or c == '-')[:50]

        if not topic or len(topic) < 3:
            topic = filename.lower().replace(".", "-").replace(" ", "-")[:40]

        pending = {"topic": topic, "original": f"Document: {filename}", "context": content[:2000]}
        with open("/Users/ducorn/DC/shared/pending_run.json", "w") as pf:
            json.dump(pending, pf)

        client.chat_postMessage(
            channel="#duc-board",
            text=(
                f"📋 *ATLAS: Requirement Document Received*\n\n"
                f"*File:* `{filename}`\n"
                f"*Extracted topic:* `{topic}`\n\n"
                        f"✏️ Change: `@DuCorn run <different description>`"
            )
        )
    except Exception as e:
        client.chat_postMessage(
            channel="#duc-requirements",
            text=f"❌ Error reading file: {str(e)[:200]}"
        ) 
 
# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)

    # Post startup message to board channel
    try:
        app.client.chat_postMessage(
            channel=BOARD_CHANNEL,
            text=(
                "🚀 *DuCorn Bot online*\n"
                "I'm connected and ready. Type `@DuCorn help` to see available commands."
            )
        )
    except Exception:
        log.warning(
            "Could not post startup message to %s:\n%s",
            BOARD_CHANNEL,
            traceback.format_exc(),
        )

    log.info("DuCorn Slack bot starting in Socket Mode …")
    handler.start()
