#!/usr/bin/env python3
"""
Wire the design skill into the pipeline.

WHAT IS MISSING TODAY
---------------------
has_ui and design_model are collected by the brief wizard, validated by the
API and stored on pipeline_runs. Nothing reads them. generate_design.py runs
standalone from a terminal. So the toggle and the picker are two more controls
that exist, read correctly in isolation, and never reach the thing they are
supposed to control — the pattern we have been pulling out of this stack all
week, and it would have been embarrassing to leave one behind while fixing the
others.

WHAT THIS ADDS

    research -> gate_1 -> [design -> gate_2] -> build -> qa -> ...
                            (only when has_ui)

  node_design   generates three variants into the product's own directory
  node_gate_2   posts them for founder approval, exactly like the other gates

gate_2 is the name main_flow.py already used for the slot between PRD approval
and build, so the numbering stays continuous rather than inventing a gate_5
that sorts after everything it precedes.

DESIGN DECISIONS WORTH ARGUING WITH

  * Settings are read from pipeline_runs at node time, not carried in state.
    The dashboard writes that table, and a checkpoint resumed after an approval
    could otherwise replay a stale choice from hours earlier.

  * The output directory goes through resolve_in_jail, so a design lands in
    products/<topic>/design/ and cannot be written or read across products.

  * On a test run the design model is forced local like every other agent. The
    picker records intent; DUCORN_LOCAL_ONLY still wins. Spend control is not
    something a per-run dropdown gets to override.

  * If has_ui is set and design generation fails, the pipeline FAILS rather
    than falling through to build. A founder who asked for a UI and silently
    got none is the exact shape of bug this whole exercise has been about.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "node_design" in s:
    sys.exit("Already patched — node_design is present.")
if "_LOCAL_MODEL" not in s:
    sys.exit("Run patch_agent_models.py first — this patch needs _local_only() "
             "and DESIGN_MODEL from it.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


# ── 1. State ─────────────────────────────────────────────────────────────────
swap("state", '''    # Approval
    approval_id:    Optional[int]
    approved:       bool''',
     '''    # UI design
    has_ui:          bool
    design_model:    Optional[str]
    design_variants: Optional[list]   # paths written, for the gate message

    # Approval
    approval_id:    Optional[int]
    approved:       bool''')

# ── 2. Run settings come from the table the dashboard writes ─────────────────
swap("run settings", '''def _pin_local_for_test_runs(topic: str) -> None:''',
     '''def _load_run_settings(topic: str) -> dict:
    """
    has_ui / design_model / environment for this run, from pipeline_runs.

    Read at node time rather than carried in state: a run pauses at a gate,
    the process exits, and a Slack approval starts a new one hours later. The
    dashboard is the source of truth for these, and a checkpoint is a snapshot
    of what they were, not what they are.
    """
    try:
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT has_ui, design_model, environment "
                        "FROM pipeline_runs WHERE slug=%s", (topic,))
            row = cur.fetchone()
        if not row:
            print(f"⚠️  No pipeline_runs row for '{topic}' — assuming no UI")
            return {"has_ui": False, "design_model": None, "environment": "test"}
        return {"has_ui": bool(row[0]),
                "design_model": row[1],
                "environment": row[2] or "test"}
    except Exception as e:
        # Deliberately NOT defaulting has_ui to True. Generating designs nobody
        # asked for costs money; skipping them is visible and recoverable.
        print(f"⚠️  Could not read run settings for '{topic}' ({e}) — assuming no UI")
        return {"has_ui": False, "design_model": None, "environment": "test"}


def _pin_local_for_test_runs(topic: str) -> None:''')

# ── 3. The design node ───────────────────────────────────────────────────────
swap("nodes", '''def node_gate_1(state: DuCornState) -> DuCornState:''',
     '''def node_design(state: DuCornState) -> DuCornState:
    """DESIGN generates UI variants for founder review."""
    topic = state["topic"]
    settings = _load_run_settings(topic)

    model = settings.get("design_model") or _get_agent_models().get("DESIGN_MODEL")
    if _local_only():
        # The picker records what the founder wanted; the environment decides
        # what actually runs. A per-run dropdown does not get to spend money on
        # a run marked test.
        model = _LOCAL_MODEL
        print(f"🔒 test run — design model {settings.get('design_model')!r} "
              f"overridden to {model}")

    print(f"\\n🎨 DESIGN: generating UI variants for '{topic}' on {model}")
    _update_db_status(topic, "running", "DESIGN — UI Variants")

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.generate_design import generate_designs
        from tools.product_jail import resolve_in_jail

        # Inside the jail, so one product can never write into another's folder.
        out_dir = resolve_in_jail(topic, "design")

        prd_path = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"
        if not prd_path.exists():
            raise FileNotFoundError(f"No PRD at {prd_path} — design needs a brief")
        brief = prd_path.read_text(encoding="utf-8")

        variants, report = generate_designs(brief, n=3, model=model,
                                            out_dir=str(out_dir))
        rendered = [v for v in variants if v.get("html")]
        if not rendered:
            # has_ui was set. Falling through to build would hand the founder a
            # product with no UI and no explanation.
            raise RuntimeError(
                f"all {len(variants)} variants failed to render: "
                f"{report.get('render_failures')}")

        paths = [v.get("path") for v in rendered if v.get("path")]
        print(f"✅ DESIGN: {len(rendered)}/{len(variants)} variants rendered")
        for v in rendered:
            print(f"   · {v['archetype']}: {len(v.get('testids', []))} test ids"
                  + (f"  ⚠️  {v['problems']}" if v.get("problems") else ""))

        return {**state, "phase": "gate_2", "status": "running",
                "has_ui": True, "design_model": model, "design_variants": paths}

    except Exception as e:
        print(f"❌ Design failed: {e}")
        import traceback; traceback.print_exc()
        _post_slack(f"❌ *ATLAS DESIGN FAILED* — `{topic}`\\n{str(e)[:300]}")
        return {**state, "status": "failed", "error": f"design: {e}"}


def node_gate_2(state: DuCornState) -> DuCornState:
    """Gate 2 — founder approves the UI direction before anything is built."""
    topic = state["topic"]
    try:
        variants = state.get("design_variants") or []
        print(f"\\n🔔 Gate 2: Requesting design approval for '{topic}'")

        approval_id = _request_approval(
            f"UI designs ready — approve to build: {topic}",
            f"DESIGN produced {len(variants)} variants in products/{topic}/design/"
        )
        if not approval_id:
            print(f"❌ Gate 2: _request_approval returned None for {topic}")
            _post_slack(f"❌ *ATLAS Gate 2 ERROR* — `{topic}`: approval request failed")
            return {**state, "status": "failed", "error": "approval_id is None"}

        listing = "\\n".join(f"• `{Path(p).name}`" for p in variants) or "• (none)"
        _post_slack(
            f"🎨 *ATLAS Gate 2 — UI Designs Ready*\\n\\n"
            f"*Product:* `{topic}`\\n"
            f"*Model:* `{state.get('design_model', '?')}`\\n"
            f"*Variants:* in `products/{topic}/design/`\\n{listing}\\n\\n"
            f"✅ Approve: `@DuCorn approve {approval_id}`\\n"
            f"❌ Cancel: `@DuCorn reject {approval_id}`"
        )

        _update_db_status(topic, "awaiting_approval", "Gate 2 — Design Approval")
        return {**state, "phase": "gate_2", "status": "awaiting_approval",
                "approval_id": approval_id, "approved": False}

    except Exception as e:
        print(f"❌ node_gate_2 failed: {e}")
        import traceback; traceback.print_exc()
        _post_slack(f"❌ *ATLAS Gate gate_2 ERROR* — {topic}: {str(e)[:200]}")
        return {**state, "status": "failed", "error": str(e)}


def node_gate_1(state: DuCornState) -> DuCornState:''')

# ── 4. Routing ───────────────────────────────────────────────────────────────
swap("route fn", '''def route_after_launch(state: DuCornState) -> str:''',
     '''def route_after_gate_1(state: DuCornState) -> str:
    """
    A UI product gets designed before it gets built. Read from the table rather
    than from state: the founder may have toggled HAS UI after starting, and
    this node runs in a fresh process after a Slack approval anyway.
    """
    topic = state["topic"]
    if _load_run_settings(topic).get("has_ui"):
        print(f"🎨 has_ui set for '{topic}' — routing to design before build")
        return "design"
    return "build"


def route_after_design(state: DuCornState) -> str:
    if state.get("status") == "failed":
        return END
    return "gate_2"


def route_after_launch(state: DuCornState) -> str:''')

# ── 5. Graph ─────────────────────────────────────────────────────────────────
swap("add nodes", '''    graph.add_node("gate_1",   node_gate_1)''',
     '''    graph.add_node("gate_1",   node_gate_1)
    graph.add_node("design",   node_design)
    graph.add_node("gate_2",   node_gate_2)''')

swap("edges", '''    graph.add_edge("gate_1",   "build")''',
     '''    graph.add_conditional_edges("gate_1", route_after_gate_1,
                                {"design": "design", "build": "build"})
    graph.add_conditional_edges("design", route_after_design,
                                {"gate_2": "gate_2", END: END})
    graph.add_edge("gate_2",   "build")''')

# ── 6. Runner ────────────────────────────────────────────────────────────────
swap("initial state", '''        "approval_id":  None,
        "approved":     False,''',
     '''        "has_ui":          _run_settings.get("has_ui", False),
        "design_model":    _run_settings.get("design_model"),
        "design_variants": None,
        "approval_id":  None,
        "approved":     False,''')

swap("load settings in runner", '''    _pin_local_for_test_runs(topic)''',
     '''    _pin_local_for_test_runs(topic)
    _run_settings = _load_run_settings(topic)''')

swap("phase choices",
     '''choices=["research","gate_1","build","qa","gate_3","launch","gate_4","deploy"])''',
     '''choices=["research","gate_1","design","gate_2","build","qa","gate_3",
                             "launch","gate_4","deploy"])''')

backup = FLOW.with_name(f"langgraph_flow.backup-design-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, FLOW)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup}")
print()
print("NOTE: the Slack approval handler must map gate_2 -> --phase build,")
print("      or an approved design will never start the build.")
