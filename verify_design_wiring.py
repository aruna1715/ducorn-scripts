#!/usr/bin/env python3
"""
Check the design wiring without running a pipeline.

    ~/DC/ducorn/.venv/bin/python ~/DC/scripts/verify_design_wiring.py [slug]

Read-only: it calls the real functions in the real modules and prints what
they return. It does not start a run, insert an approval, or spend a token.

The point is to catch the class of failure this whole day has been about — a
control that reads correctly in isolation and never reaches what it controls —
BEFORE a live run, rather than by watching a log and wondering why the design
step did not happen.

Each check names what would be broken in production if it fails.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
sys.path.insert(0, "/Users/ducorn/DC/ducorn")
sys.path.insert(0, "/Users/ducorn/DC/ducorn/flows")

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"   {detail}" if detail else ""))
    if not ok:
        failures.append(name)


print("\n── schema ──────────────────────────────────────────────────────────")
import psycopg2  # noqa: E402
DB = os.environ.get("DUCORN_DATABASE_URL", "postgresql://localhost/ducorn")
with psycopg2.connect(DB) as c, c.cursor() as cur:
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name='approval_requests'""")
    approval_cols = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name='pipeline_runs'""")
    run_cols = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    migrations = cur.fetchall()

check("approval_requests.next_phase exists", "next_phase" in approval_cols,
      "without it Slack falls back to matching titles")
check("approval_requests.product_slug exists", "product_slug" in approval_cols)
check("pipeline_runs.has_ui exists", "has_ui" in run_cols,
      "the HAS UI toggle has nowhere to land")
check("pipeline_runs.design_model exists", "design_model" in run_cols)
print(f"       migrations applied: {', '.join(n for _, n in migrations)}")

print("\n── model selection ─────────────────────────────────────────────────")
import langgraph_flow as F  # noqa: E402

os.environ.pop("DUCORN_LOCAL_ONLY", None)
models = F._get_agent_models()
check("DESIGN_MODEL is present", "DESIGN_MODEL" in models,
      f"got {sorted(models)}")
check("no agent silently fell back to local",
      not all(v == F._LOCAL_MODEL for v in models.values())
      or "local" in str(models.get("SAGE_MODEL", "")),
      f"SAGE={models.get('SAGE_MODEL')} DESIGN={models.get('DESIGN_MODEL')}")

os.environ["DUCORN_LOCAL_ONLY"] = "1"
pinned = F._get_agent_models()
check("local-only pins every agent",
      set(pinned.values()) == {F._LOCAL_MODEL},
      f"got {sorted(set(pinned.values()))}")
os.environ.pop("DUCORN_LOCAL_ONLY", None)

print("\n── run settings and routing ────────────────────────────────────────")
slug = sys.argv[1] if len(sys.argv) > 1 else None
if not slug:
    with psycopg2.connect(DB) as c, c.cursor() as cur:
        cur.execute("SELECT slug FROM pipeline_runs WHERE has_ui IS TRUE "
                    "ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            slug = row[0]
        else:
            cur.execute("SELECT slug FROM pipeline_runs ORDER BY created_at "
                        "DESC LIMIT 1")
            row = cur.fetchone()
            slug = row[0] if row else None

if not slug:
    print("  (no pipeline_runs rows — skipping; pass a slug to test one)")
else:
    settings = F._load_run_settings(slug)
    print(f"       slug={slug}  {settings}")
    check("_load_run_settings returns the three keys",
          {"has_ui", "design_model", "environment"} <= set(settings))

    route = F.route_after_gate_1({"topic": slug})
    expected = "design" if settings.get("has_ui") else "build"
    check(f"gate_1 routes to {expected!r}", route == expected,
          f"got {route!r}")

    # An unknown slug must not silently become a UI product.
    safe = F._load_run_settings("definitely-not-a-real-slug-xyz")
    check("unknown slug does not default to has_ui",
          safe.get("has_ui") is False,
          "a wrong default here generates designs nobody asked for")

print("\n── design variants ─────────────────────────────────────────────────")
with psycopg2.connect(DB) as c, c.cursor() as cur:
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name='design_variants'""")
    dv_cols = {r[0] for r in cur.fetchall()}
check("design_variants table exists", bool(dv_cols),
      "gate 2 has nowhere to record the variants it offers")
check("view_token column exists", "view_token" in dv_cols,
      "no capability URL means no way to see a design from Slack")
check("pipeline_runs.design_choice exists", "design_choice" in run_cols
      or "design_choice" in {r for r in run_cols},
      "the build cannot know which variant won")
check("approval_requests.superseded_by exists",
      "superseded_by" in approval_cols)

# The interval expression is the kind of thing that only fails at insert time,
# so exercise it rather than trusting that it parses.
with psycopg2.connect(DB) as c, c.cursor() as cur:
    try:
        cur.execute("SELECT NOW() + make_interval(days => %s)", (30,))
        cur.fetchone()
        check("expiry interval expression is valid SQL", True)
    except Exception as e:
        check("expiry interval expression is valid SQL", False, str(e)[:80])
    c.rollback()

print("\n── graph ───────────────────────────────────────────────────────────")
graph_src = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py").read_text()
for node in ("design", "gate_2"):
    check(f"{node!r} is a graph node", f'add_node("{node}"' in graph_src)
check("gate_1 routes conditionally",
      'add_conditional_edges("gate_1"' in graph_src,
      "a plain edge here means design is unreachable")
check("gate_2 leads to build", 'add_edge("gate_2",   "build")' in graph_src
      or 'add_edge("gate_2", "build")' in graph_src)

api_src = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/"
               "main.py").read_text()
check("resume knows the design phases", '"design", "gate_2"' in api_src,
      "otherwise a run paused at gate_2 resumes at build, skipping the gate")

check("/d/<token> is exempt from x-api-key", 'startswith("/d/")' in api_src,
      "founders open design links from a phone, with no header to send")
check("view endpoint re-checks the path", "refusing" in api_src
      and "design" in api_src,
      "the one keyless endpoint must not trust a stored path")

slack_src = Path("/Users/ducorn/DC/scripts/slack_bot.py").read_text()
check("slack reads next_phase", "next_phase" in slack_src)
check("slack records the design choice", "design_choice" in slack_src)
check("slack sets siblings aside", "superseded" in slack_src)
check("slack no longer branches on the PRD title",
      'elif "PRD Ready — approve to build:" in title:' not in slack_src,
      "the old title-matching dispatch is still there")

flow_src = graph_src
check("gate 2 raises one approval per variant",
      "for vid, name, archetype, register, path, token in rows" in flow_src,
      "one approval for all three means approving is not choosing")
check("build implements the chosen design",
      "DUCORN_APPROVED_DESIGN" in flow_src,
      "without this the gate is decorative — you pick, the builder ignores it")

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed — the wiring is connected end to end")
print("Still unproven: that a real run produces designs a founder likes.")
