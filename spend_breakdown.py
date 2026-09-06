#!/usr/bin/env python3
"""
Where the money actually went.

    python3 scripts/spend_breakdown.py                 today
    python3 scripts/spend_breakdown.py --hours 2       the last 2 hours
    python3 scripts/spend_breakdown.py --hours 2 --calls 20

── WHY ──────────────────────────────────────────────────────────────────────

"The document run cost about $11" is a number you can see on a credits page and
nowhere else. doctor prints a daily total and a per-model split, which tells you
Sonnet was involved and nothing about which agent, which skill, or whether the
tokens went into the work or into the same context being re-sent forty times.

A per-call breakdown answers the question that matters: is this what the work
costs, or is it what a loop costs.

── WHAT TO LOOK FOR ─────────────────────────────────────────────────────────

Two very different shapes produce the same total.

  Many calls, each with a large PROMPT and a small completion
      An agent loop. CrewAI re-sends the whole context on every iteration, so
      thinking twenty times about a 30,000-token context costs twenty times.
      This is the expensive shape and it is usually reducible.

  Few calls, large completions
      Actual writing. 100 KB of documents is roughly 25,000 output tokens and
      that is simply what it costs.

The ratio at the bottom is the tell: input tokens per output token. Writing a
document should be in the low tens. In the hundreds means the context is being
re-read far more than it is being added to.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from bootstrap_python import ensure_modules  # noqa: E402

ensure_modules("psycopg2")
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DB = "postgresql://ducorn@localhost/litellm_db"

ap = argparse.ArgumentParser()
ap.add_argument("--hours", type=float, default=None,
                help="look back this many hours (default: since midnight)")
ap.add_argument("--calls", type=int, default=10,
                help="how many of the priciest single calls to list")
args = ap.parse_args()

WHERE = ('"startTime" >= now() - interval \'%s hours\''
         % args.hours if args.hours else '"startTime" >= date_trunc(\'day\', now())')
LABEL = f"the last {args.hours:g}h" if args.hours else "today"

conn = psycopg2.connect(DB)
cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

cur.execute("""SELECT column_name FROM information_schema.columns
               WHERE table_name = 'LiteLLM_SpendLogs'""")
cols = {r[0] for r in cur.fetchall()}
TOK_IN = '"prompt_tokens"' if "prompt_tokens" in cols else "0"
TOK_OUT = '"completion_tokens"' if "completion_tokens" in cols else "0"
KEYCOL = '"api_key"' if "api_key" in cols else "NULL"

cur.execute(f"""
    SELECT count(*) n, COALESCE(sum(spend),0) s,
           COALESCE(sum({TOK_IN}),0) tin, COALESCE(sum({TOK_OUT}),0) tout
    FROM "LiteLLM_SpendLogs" WHERE {WHERE}
""")
tot = cur.fetchone()
if not tot["n"]:
    sys.exit(f"no calls in {LABEL}.")

print(f"DuCorn spend — {LABEL}\n")
print(f"  ${float(tot['s']):,.2f}   {tot['n']:,} calls   "
      f"{int(tot['tin']):,} in / {int(tot['tout']):,} out tokens")

print("\n── by model " + "─" * 56)
cur.execute(f"""
    SELECT COALESCE(model,'(none)') m, count(*) n, COALESCE(sum(spend),0) s,
           COALESCE(sum({TOK_IN}),0) tin, COALESCE(sum({TOK_OUT}),0) tout
    FROM "LiteLLM_SpendLogs" WHERE {WHERE}
    GROUP BY 1 ORDER BY 3 DESC
""")
for r in cur.fetchall():
    share = float(r["s"]) / float(tot["s"]) * 100 if float(tot["s"]) else 0
    per = float(r["s"]) / r["n"] if r["n"] else 0
    print(f"  {r['m'][:30]:32} {r['n']:5} calls  ${float(r['s']):7.2f}  "
          f"{share:4.0f}%   ${per:.3f}/call")

if KEYCOL != "NULL":
    print("\n── by key (which agent) " + "─" * 44)
    cur.execute(f"""
        SELECT COALESCE({KEYCOL},'(none)') k, count(*) n,
               COALESCE(sum(spend),0) s,
               COALESCE(sum({TOK_IN}),0) tin, COALESCE(sum({TOK_OUT}),0) tout
        FROM "LiteLLM_SpendLogs" WHERE {WHERE}
        GROUP BY 1 ORDER BY 3 DESC LIMIT 12
    """)
    for r in cur.fetchall():
        ratio = (float(r["tin"]) / float(r["tout"])) if float(r["tout"]) else 0
        print(f"  …{str(r['k'])[-12:]:14} {r['n']:5} calls  "
              f"${float(r['s']):7.2f}   {int(r['tin']):>9,} in / "
              f"{int(r['tout']):>7,} out   {ratio:5.0f}:1")

print(f"\n── the {args.calls} priciest single calls " + "─" * 34)
cur.execute(f"""
    SELECT to_char("startTime",'HH24:MI:SS') t, COALESCE(model,'?') m,
           spend s, {TOK_IN} tin, {TOK_OUT} tout
    FROM "LiteLLM_SpendLogs" WHERE {WHERE}
    ORDER BY spend DESC NULLS LAST LIMIT {args.calls}
""")
for r in cur.fetchall():
    print(f"  {r['t']}  {r['m'][:22]:24} ${float(r['s'] or 0):6.3f}  "
          f"{int(r['tin'] or 0):>8,} in / {int(r['tout'] or 0):>6,} out")

ratio = float(tot["tin"]) / float(tot["tout"]) if float(tot["tout"]) else 0
avg_in = float(tot["tin"]) / tot["n"]
print("\n── the shape of it " + "─" * 49)
print(f"  input : output       {ratio:,.0f} : 1")
print(f"  average prompt       {avg_in:,.0f} tokens per call")
if ratio > 60:
    print(f"""
  That ratio means the same context is being re-read far more than it is
  being added to — the signature of an agent loop, not of writing. Each
  iteration re-sends the whole prompt, so a 30,000-token context thought
  about twenty times is 600,000 input tokens for one skill.

  Worth checking: CrewAI max_iter on the agents, and how much of the
  context each skill actually needs. A skill that only writes does not
  need the previous skill's full output.""")
elif ratio > 25:
    print("""
  Normal for a review or QA step, which reads much more than it writes.
  A writing step should be lower.""")
else:
    print("""
  This is work, not looping — the tokens went into output. If the total is
  still higher than you want, the lever is scope or model, not efficiency.""")

conn.close()
