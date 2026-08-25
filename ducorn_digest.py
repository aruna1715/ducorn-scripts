"""
DuCorn Daily Digest — powered by real agent activity data
Reads from PostgreSQL, generates brief via LiteLLM, saves for delivery
"""
import subprocess
import sys
import os
from datetime import datetime
from cleo_kpis import get_kpis

sys.path.insert(0, '/Users/ducorn/DC/scripts')
from ducorn_db import get_activity_summary, get_pending_approvals, save_document

def generate_brief():
    activity = get_activity_summary()
    approvals = get_pending_approvals()
    kpis = get_kpis()  # ← add this

    approval_text = ""
    if approvals:
        approval_text = "\n\nPENDING FOUNDER APPROVAL:\n"
        for a in approvals:
            approval_text += f"- [{a['id']}] {a['requested_by'].upper()}: {a['title']}\n"
    else:
        approval_text = "\n\nPENDING FOUNDER APPROVAL:\n- None"

    kpi_text = f"""

KEY METRICS (last 24h):
- Tasks completed: {kpis['last_24h']['tasks']}
- Spend: ${kpis['last_24h']['spend_usd']:.4f}
- Pending approvals: {kpis['pending_approvals']}
- All-time spend: ${kpis['all_time']['total_spend_usd']:.4f}"""

    prompt = f"""You are ATLAS, DuCorn's chief orchestrator.
Based on this real data, produce a concise DuCorn Board Brief under 200 words.

DATA:
{activity}
{approval_text}
{kpi_text}

Format as:
DUCORN BOARD BRIEF — {datetime.now().strftime('%A, %B %d, %Y')}

COMPLETED TODAY:
[list from data]

IN PROGRESS:
[list from data]

PENDING FOUNDER APPROVAL:
[list from data or None]

KEY METRICS:
[from kpi_text]
"""
    result = subprocess.run(
        ["jarvis", "ask", prompt],
        capture_output=True, text=True
    )
    output = result.stdout
    banner_end = output.find("Personal AI, On Personal Devices")
    if banner_end > -1:
        output = output[banner_end + 34:].strip()
    return output

def deliver_brief(text):
    os.makedirs("/Users/ducorn/DC/digests", exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    filepath = f"/Users/ducorn/DC/digests/{date}.txt"
    audio_path = f"/Users/ducorn/DC/digests/{date}.m4a"

    # Save text
    with open(filepath, "w") as f:
        f.write(text)

    # Save to DB
    save_document(f"Daily Digest — {date}", "digest", filepath, "atlas", "approved")

    # Generate audio via macOS TTS
    try:
        import subprocess
        # Generate as AIFF first, then convert to MP3
        subprocess.run([
            "/usr/bin/say", text,
            "--file-format=mp4f",
            "--data-format=alac",
            "-o", audio_path
        ], check=True)

        print(f"🔊 Audio saved to: {audio_path}")
    except Exception as e:
        print(f"Audio generation failed: {e}")

    print(text)
    print(f"\n✅ Saved to: {filepath}")
    post_to_slack(text)
    
def post_to_slack(text):
    try:
        import os
        from slack_sdk import WebClient
        client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])
        date = datetime.now().strftime('%B %d, %Y')
        msg = f"📋 *DuCorn Daily Brief — {date}*\n\n```{text}```"
        client.chat_postMessage(channel='#duc-board', text=msg)
        print("✅ Posted to #duc-board")
    except Exception as e:
        print(f"Slack post failed: {e}")
        

if __name__ == "__main__":
    print("Generating DuCorn Board Brief from real data...\n")
    brief = generate_brief()
    deliver_brief(brief)
