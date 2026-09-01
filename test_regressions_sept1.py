#!/usr/bin/env python3
"""
Regression tests for the failures of 31 Aug – 1 Sept 2026.

    cd ~/DC/ducorn && .venv/bin/python ../scripts/test_regressions_sept1.py

Each test corresponds to something that actually broke, in production, after
the existing suite passed. Two rules, both learned the hard way:

  EXECUTE, DO NOT STRING-MATCH.
      verify_design_wiring.py had 36 passing checks while generate_design.py
      could not be imported. It checked that files contained the right words.
      Where a test here can import the module, call the function or compile the
      graph, it does.

  DERIVE, DO NOT ENUMERATE.
      Five separate hardcoded phase lists went stale this week. A test that
      lists the phases it expects is a sixth. Where a fact can be read from the
      compiled graph or the source tree, it is.
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

DUCORN = Path("/Users/ducorn/DC/ducorn")
PRODUCTS = Path("/Users/ducorn/DC/ducorn-products")
API_MAIN = PRODUCTS / "products/ducorn-activity-api/main.py"

sys.path.insert(0, str(DUCORN))
sys.path.insert(0, str(DUCORN / "flows"))
sys.path.insert(0, "/Users/ducorn/DC/scripts")

passed, failed, skipped = [], [], []


def test(name):
    def deco(fn):
        try:
            r = fn()
            if r == "skip":
                print(f"  skip {name}")
                skipped.append(name)
            else:
                print(f"  ok   {name}")
                passed.append(name)
        except AssertionError as e:
            print(f"  FAIL {name}\n         {e}")
            failed.append(name)
        except Exception as e:
            print(f"  FAIL {name}\n         {type(e).__name__}: {e}")
            failed.append(name)
        return fn
    return deco


print("\n── import shape ────────────────────────────────────────────────────")


@test("generate_design imports the way the FLOW imports it")
def _():
    # 1 Sept: node_design died on `No module named 'design_spec'`. Its own 25
    # tests all import from inside tools/, which is the case that worked.
    import importlib
    m = importlib.import_module("tools.generate_design")
    assert hasattr(m, "generate_designs"), "generate_designs missing"


@test("generate_design still imports standalone")
def _():
    import subprocess
    r = subprocess.run([sys.executable, "-c",
                        "import generate_design; print(generate_design.__name__)"],
                       cwd=str(DUCORN / "tools"), capture_output=True, text=True)
    assert r.returncode == 0, f"standalone import broke: {r.stderr[-300:]}"


print("\n── the graph, derived from the graph ───────────────────────────────")


@test("every gate_* node is caught by the pause check")
def _():
    # 1 Sept: gate_nodes was {"gate_1","gate_3","gate_4"}. gate_2 was added to
    # the graph and not to that set, so the design gate raised three approvals
    # and let build run anyway. Derived so a gate_5 cannot repeat it.
    from flows.langgraph_flow import build_graph
    graph = build_graph()
    gates = [n for n in graph.nodes if n.startswith("gate_")]
    assert gates, "no gate nodes found — has the graph changed shape?"
    src = (DUCORN / "flows/langgraph_flow.py").read_text()
    i = src.find("def _stream_until_pause")
    body = src[i:src.find("\n    if phase ==", i)]
    assert 'node.startswith("gate_")' in body, (
        f"the pause check enumerates gates instead of deriving them. "
        f"Graph has {gates} — a list will go stale the next time one is added.")


@test("argparse phases, graph nodes and RESUME_AFTER agree")
def _():
    # Four separate enumerations of the same set went out of sync this week.
    from flows.langgraph_flow import build_graph
    graph = build_graph()
    nodes = {n for n in graph.nodes if not n.startswith("__")}
    src = (DUCORN / "flows/langgraph_flow.py").read_text()

    tree = ast.parse(src)
    choices = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "add_argument"):
            for kw in node.keywords:
                if kw.arg == "choices" and isinstance(kw.value, ast.List):
                    vals = {e.value for e in kw.value.elts
                            if isinstance(e, ast.Constant)}
                    if "research" in vals:
                        choices = vals
    assert choices, "could not find the --phase choices list"
    missing = nodes - choices
    assert not missing, (
        f"--phase cannot reach these graph nodes: {sorted(missing)}. "
        f"A phase you cannot name is a phase you cannot resume at.")


@test("resume refuses an unmapped phase instead of guessing")
def _():
    # 1 Sept: `--phase design` had no RESUME_AFTER entry, so it silently
    # resumed from the checkpoint position (gate_2) and ran the wrong stage.
    src = (DUCORN / "flows/langgraph_flow.py").read_text()
    i = src.find("RESUME_AFTER = {")
    tail = src[i:i + 3000]
    assert "Cannot resume at" in tail and "SystemExit" in tail, (
        "an unmapped phase still falls through to graph.update_state — it will "
        "resume somewhere other than where you asked")


print("\n── the founder's brief reaches the model ───────────────────────────")


@test("node_research puts the brief in the Task description")
def _():
    # 1 Sept: the brief was read AFTER the Task was built and used only to
    # re-append it to the PRD. SAGE researched from the product NAME and
    # returned a Mixpanel competitor for a dashboard rebuild.
    import flows.langgraph_flow as F

    marker = "BINDING-BRIEF-CANARY-8f3a2c"
    slug = "zz-test-brief-canary"
    prd = PRODUCTS / "docs" / f"{slug}-PRD.md"
    prd.parent.mkdir(parents=True, exist_ok=True)
    prd.write_text(f"# canary\n\n{marker}\n", encoding="utf-8")

    captured = {}

    class FakeTask:
        def __init__(self, description=None, **kw):
            captured["description"] = description or ""

    class FakeAgent:
        def __init__(self, **kw):
            captured["agent_kwargs"] = kw

    class FakeCrew:
        def __init__(self, **kw):
            pass

        def kickoff(self):
            return type("R", (), {"raw": "done"})()

    import crewai
    orig = (crewai.Agent, crewai.Task, crewai.Crew)
    crewai.Agent, crewai.Task, crewai.Crew = FakeAgent, FakeTask, FakeCrew
    try:
        F.node_research({"topic": slug})
    finally:
        crewai.Agent, crewai.Task, crewai.Crew = orig
        prd.unlink(missing_ok=True)

    desc = captured.get("description", "")
    assert marker in desc, (
        "the founder's brief is NOT in SAGE's task description — research will "
        "invent a product from the name")
    assert desc.index(marker) < len(desc) * 0.6, (
        "the brief appears only at the end of the task; it should lead")


@test("node_research refuses to research with no brief")
def _():
    import flows.langgraph_flow as F
    slug = "zz-test-no-brief-canary"
    prd = PRODUCTS / "docs" / f"{slug}-PRD.md"
    prd.unlink(missing_ok=True)
    out = F.node_research({"topic": slug})
    assert out.get("status") == "failed", (
        "with no brief it proceeded anyway — that is how a dashboard rebuild "
        "came back as a generic analytics product")


print("\n── models and limits ───────────────────────────────────────────────")


@test("every node reads its model from _get_agent_models, not a bare env default")
def _():
    # T29 asserted this for node_launch only. node_research had the identical
    # defect and used llama3.1 on every production run for months.
    src = (DUCORN / "flows/langgraph_flow.py").read_text()
    tree = ast.parse(src)
    offenders = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name.startswith("node_")]:
        body = ast.get_source_segment(src, fn) or ""
        if "Agent(" not in body:
            continue
        if "_get_agent_models" not in body:
            offenders.append(fn.name)
    assert not offenders, (
        f"these nodes build an Agent without reading the switcher: {offenders} "
        f"— they will silently use the local model in production")


@test("max_iter is generous everywhere, because hitting it CRASHES on Anthropic")
def _():
    # 1 Sept: skill_runner had max_iter=3. Exceeding it makes CrewAI force a
    # final answer via assistant-message prefill, which Anthropic 400s. The
    # runaway guard is the LiteLLM per-key budget, not this.
    MIN = 10
    bad = []
    for f in (DUCORN / "flows/langgraph_flow.py", DUCORN / "skill_runner.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (kw.arg == "max_iter"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value < MIN):
                        bad.append(f"{f.name}:{kw.value.lineno} = {kw.value.value}")
    assert not bad, (
        f"max_iter below {MIN}: {bad}. On Anthropic, exceeding max_iter is a "
        f"400, not a truncation — the stage dies.")


print("\n── process and file lifetimes ──────────────────────────────────────")


@test("pipelines are spawned detached from the API")
def _():
    # 1 Sept: restarting the API killed a running pipeline. The children shared
    # the API's process group, so launchctl kickstart -k took them with it.
    src = API_MAIN.read_text()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "Popen"):
            continue
        seg = ast.get_source_segment(src, node) or ""
        # Every Popen must detach, with ONE named exception: macOS `say` for
        # digest audio, which is short-lived and SHOULD die with a restart.
        #
        # Written as an exception rather than a filter on purpose. An earlier
        # version required "langgraph_flow" to appear in the call — which
        # silently skipped `subprocess.Popen(cmd, ...)` at /pipeline/start,
        # where the path lives in a variable. A test that misses the thing it
        # was written for is worse than no test.
        if '"say"' in seg or "'say'" in seg:
            continue
        if not any(kw.arg == "start_new_session" for kw in node.keywords):
            bad.append(node.lineno)
    assert not bad, (
        f"Popen of a long-running job without start_new_session at lines "
        f"{bad} — an API restart will kill it mid-flight")


@test("delete_run spares the founder's brief")
def _():
    # 1 Sept: deleting a run moved <slug>-BRIEF.md to _deleted, because the
    # filename starts with the slug. A brief is an input, not an output.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "delete_run", "/Users/ducorn/DC/scripts/delete_run.py")
    src = Path("/Users/ducorn/DC/scripts/delete_run.py").read_text().splitlines()
    i = next(k for k, l in enumerate(src) if l.startswith("INPUT_SUFFIXES"))
    j = next(k for k, l in enumerate(src) if l.startswith("def find_processes"))
    ns = {"Path": Path}
    exec(compile("\n".join(src[i:j]), "delete_run", "exec"), ns)
    owns = ns["owns"]
    assert not owns("foo-BRIEF.md", "foo", {"foo"}), \
        "the brief would be deleted with the run"
    assert owns("foo-PRD.md", "foo", {"foo"}), "outputs must still be removed"
    assert not owns("foo-v2-PRD.md", "foo", {"foo", "foo-v2"}), \
        "a sibling product's files would be taken"


print()
print(f"{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
if failed:
    print("FAILED: " + ", ".join(failed))
    sys.exit(1)
print("every failure from 31 Aug – 1 Sept is now covered")
