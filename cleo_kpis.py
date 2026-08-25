"""
CLEO KPI Data Pipeline
Reads from PostgreSQL and produces structured KPI data
Powers the morning digest and future dashboard
"""
import sys
import json
from datetime import datetime, timedelta
sys.path.insert(0, '/Users/ducorn/DC/scripts')
from ducorn_db import get_conn

def get_kpis() -> dict:
    with get_conn() as conn:
        cur = conn.cursor()

        # Total tasks and spend
        cur.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                SUM(cost_usd) as total_spend,
                SUM(tokens_used) as total_tokens
            FROM agent_activity
            WHERE status = 'completed'
        """)
        totals = cur.fetchone()

        # Tasks by agent
        cur.execute("""
            SELECT agent_id, COUNT(*) as tasks, SUM(cost_usd) as spend
            FROM agent_activity
            WHERE status = 'completed'
            GROUP BY agent_id
            ORDER BY tasks DESC
        """)
        by_agent = cur.fetchall()

        # Last 24 hours activity
        cur.execute("""
            SELECT COUNT(*) as tasks_24h, SUM(cost_usd) as spend_24h
            FROM agent_activity
            WHERE status = 'completed'
            AND created_at >= NOW() - INTERVAL '24 hours'
        """)
        recent = cur.fetchone()

        # Pending approvals
        cur.execute("""
            SELECT COUNT(*) FROM approval_requests WHERE status = 'pending'
        """)
        pending = cur.fetchone()[0]

        # Tasks this week
        cur.execute("""
            SELECT COUNT(*) FROM agent_activity
            WHERE status = 'completed'
            AND created_at >= NOW() - INTERVAL '7 days'
        """)
        week_tasks = cur.fetchone()[0]

        # Most active agent today
        cur.execute("""
            SELECT agent_id, COUNT(*) as tasks
            FROM agent_activity
            WHERE created_at >= CURRENT_DATE
            GROUP BY agent_id
            ORDER BY tasks DESC
            LIMIT 1
        """)
        most_active = cur.fetchone()

        # Documents produced
        cur.execute("SELECT COUNT(*) FROM documents")
        doc_count = cur.fetchone()[0]

    kpis = {
        "generated_at": datetime.now().isoformat(),
        "all_time": {
            "total_tasks": int(totals[0] or 0),
            "total_spend_usd": float(totals[1] or 0),
            "total_tokens": int(totals[2] or 0),
        },
        "last_24h": {
            "tasks": int(recent[0] or 0),
            "spend_usd": float(recent[1] or 0),
        },
        "last_7_days": {
            "tasks": int(week_tasks or 0),
        },
        "pending_approvals": int(pending),
        "documents_produced": int(doc_count),
        "most_active_today": most_active[0] if most_active else "none",
        "by_agent": [
            {
                "agent": row[0],
                "tasks": int(row[1]),
                "spend_usd": float(row[2] or 0)
            }
            for row in by_agent
        ]
    }
    return kpis

def print_kpi_report(kpis: dict):
    print("\n" + "="*50)
    print("CLEO KPI REPORT — DuCorn")
    print(f"Generated: {kpis['generated_at']}")
    print("="*50)
    print(f"\n📊 ALL TIME")
    print(f"  Tasks completed:  {kpis['all_time']['total_tasks']}")
    print(f"  Total spend:      ${kpis['all_time']['total_spend_usd']:.4f}")
    print(f"  Total tokens:     {kpis['all_time']['total_tokens']:,}")
    print(f"  Documents:        {kpis['documents_produced']}")
    print(f"\n📅 LAST 24 HOURS")
    print(f"  Tasks:            {kpis['last_24h']['tasks']}")
    print(f"  Spend:            ${kpis['last_24h']['spend_usd']:.4f}")
    print(f"\n📅 LAST 7 DAYS")
    print(f"  Tasks:            {kpis['last_7_days']['tasks']}")
    print(f"\n⏳ PENDING APPROVALS: {kpis['pending_approvals']}")
    print(f"\n🤖 BY AGENT")
    for a in kpis['by_agent']:
        print(f"  {a['agent'].upper():8} — {a['tasks']} tasks | ${a['spend_usd']:.4f}")

if __name__ == "__main__":
    kpis = get_kpis()
    print_kpi_report(kpis)
    
    # Save to file for dashboard
    import os
    os.makedirs("/Users/ducorn/DC/ducorn-products/data", exist_ok=True)
    with open("/Users/ducorn/DC/ducorn-products/data/kpis.json", "w") as f:
        json.dump(kpis, f, indent=2)
    print(f"\n✅ KPIs saved to ducorn-products/data/kpis.json")
