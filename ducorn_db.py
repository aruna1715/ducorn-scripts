"""
DuCorn Database Module
Handles all PostgreSQL operations for agent activity logging
Used by agents, ATLAS, and the digest script
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from contextlib import contextmanager

DB_URL = "postgresql://localhost/ducorn"

# ── status contracts ─────────────────────────────────────────────────────────
#
# Which statuses the code may write to each table. The other side of this
# contract is a CHECK constraint inside PostgreSQL, and on 1 September the two
# disagreed: gate 2 marks losing design variants 'superseded', the constraint
# allowed only pending/approved/rejected, and the mismatch surfaced as a failed
# approval on a paid run — because nothing compared them.
#
# scripts/prove_db_contracts.py does that comparison now, in both directions,
# reading the constraints out of the catalog rather than from a list.
#
# Adding a status here without a migration makes that check fail, which is the
# point. Adding one to the database without adding it here makes it report
# dead vocabulary, which is milder and also worth knowing.
STATUS_CONTRACTS = {
    "approval_requests": (
        "pending",           # raised, waiting on a founder
        "approved",          # the decision that releases next_phase
        "rejected",          # the founder said no
        "superseded",        # another variant of the same gate was chosen
    ),
    "agent_activity": (
        "started",
        "completed",
        "failed",
        "blocked",
    ),
}


@contextmanager
def get_conn():
    conn = psycopg2.connect(DB_URL)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ── Agent Activity ─────────────────────────────────────────────────────────────

def log_task_started(agent_id, task_name, model_used=None):
    """Call when an agent starts a task"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agent_activity 
                (agent_id, task_name, status, model_used, created_at)
            VALUES (%s, %s, 'started', %s, NOW())
            RETURNING id
        """, (agent_id, task_name, model_used))
        row_id = cur.fetchone()[0]
    print(f"[DuCorn DB] {agent_id} started task: {task_name} (id={row_id})")
    return row_id

def log_task_completed(activity_id, summary, tokens_used=0, cost_usd=0):
    """Call when an agent completes a task"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_activity
            SET status='completed', summary=%s, 
                tokens_used=%s, cost_usd=%s, updated_at=NOW()
            WHERE id=%s
        """, (summary, tokens_used, cost_usd, activity_id))
    print(f"[DuCorn DB] Task {activity_id} completed — {tokens_used} tokens, ${cost_usd:.4f}")

def log_task_failed(activity_id, error_summary):
    """Call when an agent task fails"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_activity
            SET status='failed', summary=%s, updated_at=NOW()
            WHERE id=%s
        """, (error_summary, activity_id))
    print(f"[DuCorn DB] Task {activity_id} failed: {error_summary}")

def log_task_blocked(activity_id, blocked_reason):
    """Call when an agent task is blocked"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_activity
            SET status='blocked', summary=%s, updated_at=NOW()
            WHERE id=%s
        """, (blocked_reason, activity_id))
    print(f"[DuCorn DB] Task {activity_id} blocked: {blocked_reason}")

def get_todays_activity():
    """Returns all agent activity from today"""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT agent_id, task_name, status, summary, 
                   tokens_used, cost_usd, model_used, created_at
            FROM agent_activity
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
        """)
        return cur.fetchall()

def get_activity_summary():
    """Returns a text summary of last 24 hours activity for the digest"""
    rows = get_todays_activity()
    if not rows:
        return "No agent activity recorded today."

    completed = [r for r in rows if r['status'] == 'completed']
    in_progress = [r for r in rows if r['status'] == 'started']
    blocked = [r for r in rows if r['status'] == 'blocked']
    failed = [r for r in rows if r['status'] == 'failed']

    total_tokens = sum(r['tokens_used'] or 0 for r in rows)
    total_cost = sum(float(r['cost_usd'] or 0) for r in rows)

    lines = [f"DuCorn Activity Summary — {datetime.now().strftime('%B %d, %Y')}"]
    lines.append(f"Total: {len(rows)} tasks | {total_tokens:,} tokens | ${total_cost:.4f}")
    lines.append("")

    if completed:
        lines.append("COMPLETED:")
        for r in completed:
            lines.append(f"  {r['agent_id'].upper()}: {r['task_name']}")
            if r['summary']:
                lines.append(f"    → {r['summary'][:100]}")

    if in_progress:
        lines.append("IN PROGRESS:")
        for r in in_progress:
            lines.append(f"  {r['agent_id'].upper()}: {r['task_name']}")

    if blocked:
        lines.append("BLOCKED:")
        for r in blocked:
            lines.append(f"  {r['agent_id'].upper()}: {r['task_name']} — {r['summary']}")

    if failed:
        lines.append("FAILED:")
        for r in failed:
            lines.append(f"  {r['agent_id'].upper()}: {r['task_name']} — {r['summary']}")

    return "\n".join(lines)

# ── Approval Requests ──────────────────────────────────────────────────────────

def request_approval(requested_by, title, description, document_path=None,
                     next_phase=None, product_slug=None):
    """
    Agent requests founder approval.

    next_phase / product_slug say what granting this approval should start.
    Both are optional so existing callers keep working, but a gate that omits
    them produces an approval the Slack bot can only act on by parsing its
    title — which is the failure these columns exist to end.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO approval_requests 
                (requested_by, title, description, document_path,
                 next_phase, product_slug)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (requested_by, title, description, document_path,
              next_phase, product_slug))
        row_id = cur.fetchone()[0]
    print(f"[DuCorn DB] Approval requested by {requested_by}: {title} (id={row_id})")
    return row_id

def get_pending_approvals():
    """Returns all pending founder approvals"""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, requested_by, title, description, document_path, created_at, status
            FROM approval_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        return cur.fetchall()

def approve_request(approval_id, decided_by):
    """Founder approves a request"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE approval_requests
            SET status='approved', decided_by=%s, decided_at=NOW()
            WHERE id=%s
        """, (decided_by, approval_id))
    print(f"[DuCorn DB] Approval {approval_id} approved by {decided_by}")

def reject_request(approval_id, decided_by):
    """Founder rejects a request"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE approval_requests
            SET status='rejected', decided_by=%s, decided_at=NOW()
            WHERE id=%s
        """, (decided_by, approval_id))
    print(f"[DuCorn DB] Approval {approval_id} rejected by {decided_by}")

# ── Documents ──────────────────────────────────────────────────────────────────

def save_document(title, doc_type, file_path, created_by, status='draft'):
    """Save a document reference to the library"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO documents (title, doc_type, file_path, created_by, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (title, doc_type, file_path, created_by, status))
        row_id = cur.fetchone()[0]
    print(f"[DuCorn DB] Document saved: {title} (id={row_id})")
    return row_id

# ── Quick test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing DuCorn DB module...")

    # Log the PRD run from yesterday
    task_id = log_task_started("sage", "Market Research — AI Analytics Dashboard", "claude-sonnet")
    log_task_completed(task_id, "Produced ATLAS-PRD-BB-001. Market fit score 87/100. UNCONDITIONAL GO.", 1048670, 4.13)

    task_id2 = log_task_started("atlas", "Go/No-Go Decision — ATLAS-PRD-001", "claude-sonnet")
    log_task_completed(task_id2, "UNCONDITIONAL GO. 12/12 criteria passed. Development phase open.", 50000, 0.20)

    task_id3 = log_task_started("opus", "Board Summary — ATLAS-PRD-001", "deepseek-chat")
    log_task_completed(task_id3, "One-page executive board summary produced for Vijay.", 15000, 0.05)

    # Save the PRD document
    save_document("ATLAS-PRD-BB-001 — AI Analytics Dashboard", "PRD", 
                  "/Users/ducorn/DC/ducorn/outputs/ATLAS-PRD-BB-001-FULL.md", "sage", "approved")

    print("\n" + get_activity_summary())
