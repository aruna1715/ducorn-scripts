#!/usr/bin/env python3
"""
Bring test_pipeline.py and test_integration.py back in line with the code.

Nine failures. Not nine bugs — one real gap (fixed separately in
patch_phase_choices.py) and eight tests asserting a contract that changed
today. Each one below was traced to the change that broke it before it was
touched.

── 1. FIVE FAILURES: "No founder brief found" ───────────────────────────────

    ❌ Pipeline failed at research: No founder brief found at ...-PRD.md

    Full research to gate_1 flow using Ollama
    Pipeline combo: Simple + Fast + CrewAI
    Pipeline combo: Medium + Fast + Cursor
    Pipeline combo: Medium + G-Stack + Cursor
    Pipeline combo: Complex + G-Stack + Cursor

These tests DELETE the PRD and then start research. That was correct until
this morning: research read the brief only after building its Task, so a
missing brief was invisible and SAGE researched from the product name. Making
that a hard failure was the point of patch_research_fix.py — the tests are
simply the last callers still doing the thing that is now refused.

They now seed a brief first, which also makes them better tests than they
were: an assertion that the PRD *exists* passes trivially once a file is
seeded, so they now assert the PRD GREW and that the founder's text SURVIVED
into the final document. That second one is real coverage — re-appending the
brief after research overwrites the file is exactly the step that used to be
the brief's only purpose, and nothing tested it.

── 2. ONE FAILURE: "/pipeline/stop — Process not running" ───────────────────

Same cause, one step removed. The test spawns a real langgraph_flow.py so
pgrep has something to find, sleeps 3s, and checks it is still alive. With no
brief, research now refuses and the process is gone in well under a second.
Seeding the brief puts it back to a genuine multi-minute Ollama run.

The assertion message gets to say this, because "Process not running" sent me
looking at the stop endpoint, which was fine.

── 3. TWO FAILURES: model assertions ────────────────────────────────────────

    _get_agent_models reads from dashboard API
        ATLAS_MODEL still hardcoded to claude-sonnet
    T28: _get_agent_models() returns local-fast from fresh subprocess
        NOVA_MODEL should be local-fast, got: deepseek-chat

Neither is a bug. Both assert a DASHBOARD SETTING — that no agent is on a paid
model — which was true when they were written and is deliberately false now
that the switcher is set for a production run. A test that fails when you
change a setting it does not own is a test that trains you to ignore it.

Worse, T28 does not call _get_agent_models at all. It inlines a copy of a
translation table that was deliberately REMOVED from the real function,
because that table silently downgraded every model added after it was written
— claude-opus among them — to local-fast. The test would keep passing after
the function it is named for was deleted.

Both are rewritten to assert what the code actually promises, which does not
move when a switcher does:

    DUCORN_LOCAL_ONLY set   → every agent is the local model, no exceptions.
                              This is the guarantee that test runs never bill.
    DUCORN_LOCAL_ONLY unset → the map equals /agents/config verbatim, with no
                              translation and nothing dropped.

T28 keeps its fresh-subprocess shape, which was its real value — the Slack bot
starts the pipeline with none of these variables in its environment — but now
imports and calls the real function.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DUCORN = Path("/Users/ducorn/DC/ducorn")
PIPE = DUCORN / "test_pipeline.py"
INTEG = DUCORN / "test_integration.py"

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
applied = []


def swap(path, label, text, old, new, count=1):
    n = text.count(old)
    if n != count:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {n}, expected "
                 f"{count}. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, count)


# ═══════════════════════════════════════════════════════════════════════════
# test_pipeline.py
# ═══════════════════════════════════════════════════════════════════════════
p = PIPE.read_text(encoding="utf-8")
if "def seed_brief" in p:
    sys.exit("Already patched — seed_brief exists in test_pipeline.py.")

# ── the helper ───────────────────────────────────────────────────────────────
p = swap(PIPE, "seed_brief helper", p, '''def base_env():
    """Env exactly as the pipeline's subprocesses receive it."""
    load_ducorn_env()
    return {**os.environ}''', '''def base_env():
    """Env exactly as the pipeline's subprocesses receive it."""
    load_ducorn_env()
    return {**os.environ}


BRIEF_CANARY = "CANARY-BRIEF-TEXT-d41f7b"


def seed_brief(topic, extra=""):
    """
    Write the founder's brief a research run starts from, and return it.

    Research refuses to run without one — deliberately, since researching from
    the product name alone is how a dashboard rebuild came back as a generic
    analytics tool. Every test that starts a run has to provide one, exactly
    as the API does when a founder submits a product.

    The canary is here so a test can prove the brief SURVIVED into the finished
    PRD. Research overwrites the file; the flow re-appends the brief
    afterwards, and nothing covered that until now.
    """
    prd_path = PRODUCTS_DIR / "docs" / (topic + "-PRD.md")
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    seed = (f"# {topic}\\n\\n"
            f"A small internal tool used only by the DuCorn test suite. "
            f"It reads one CSV and prints a total. No UI, no users, no "
            f"integrations. {BRIEF_CANARY}\\n{extra}\\n")
    prd_path.write_text(seed, encoding="utf-8")
    return seed''')

# ── the end-to-end research test ─────────────────────────────────────────────
p = swap(PIPE, "e2e seed", p, '''    topic = TEST_SLUG + "-e2e"
    prd_path = PRODUCTS_DIR / "docs" / (topic + "-PRD.md")
    prd_path.unlink(missing_ok=True)''', '''    topic = TEST_SLUG + "-e2e"
    prd_path = PRODUCTS_DIR / "docs" / (topic + "-PRD.md")
    # Research refuses to run with no brief. This used to delete the PRD.
    seed = seed_brief(topic)''')

p = swap(PIPE, "e2e assertions", p,
         '''    assert prd_path.exists(), "PRD not created by research"
    assert prd_path.stat().st_size > 100, "PRD too small: " + str(prd_path.stat().st_size)''',
         '''    assert prd_path.exists(), "PRD not created by research"
    written = prd_path.read_text()
    # `exists` is now trivially true — the brief was seeded. What matters is
    # that research REPLACED it with more than it was given...
    assert written != seed, ("PRD is still the seeded brief — research wrote "
                             "nothing. Last line: " +
                             output.strip().split("\\n")[-1][:200])
    assert len(written) > len(seed) + 200, (
        "PRD barely grew: " + str(len(written)) + " vs seed " + str(len(seed)))
    # ...and that the founder's own words survived being overwritten.
    assert BRIEF_CANARY in written, (
        "the founder's brief was lost when research overwrote the PRD")''')

# ── the four combination tests ───────────────────────────────────────────────
p = swap(PIPE, "combo seed", p, '''    prd_path = PRODUCTS_DIR / "docs" / (topic + "-PRD.md")
    prd_path.unlink(missing_ok=True)
    # Clear checkpoints and approvals''', '''    prd_path = PRODUCTS_DIR / "docs" / (topic + "-PRD.md")
    seed = seed_brief(topic)          # research refuses without a brief
    # Clear checkpoints and approvals''')

p = swap(PIPE, "combo assertions", p,
         '''    assert prd_path.exists(), f"PRD not created for {topic}"''',
         '''    assert prd_path.exists(), f"PRD not created for {topic}"
    _written = prd_path.read_text()
    assert _written != seed, (
        f"PRD for {topic} is still the seeded brief — research wrote nothing. "
        f"Last line: " + (result.stdout + result.stderr).strip().split("\\n")[-1][:200])
    assert BRIEF_CANARY in _written, f"brief lost from {topic}'s PRD"''')

# ── the stop-API test ────────────────────────────────────────────────────────
p = swap(PIPE, "stop seed", p, '''    dummy_slug = TEST_SLUG + "-stop-test"
    env = {''', '''    dummy_slug = TEST_SLUG + "-stop-test"
    # A brief, or research refuses in under a second and there is no process
    # left for pgrep to find three seconds later.
    seed_brief(dummy_slug)
    env = {''')

p = swap(PIPE, "stop assertion", p,
         '''    assert proc.poll() is None, "Process not running"''',
         '''    assert proc.poll() is None, (
        "the pipeline process exited within 3s, so there is nothing for the "
        "stop endpoint to find. That is a problem with the RUN, not with stop "
        "— check the brief was seeded and Ollama is up.")''')

# ── the switcher test ────────────────────────────────────────────────────────
p = swap(PIPE, "agent models test", p, '''@test("_get_agent_models reads from dashboard API")
def test_agent_models_from_dashboard():
    from flows.langgraph_flow import _get_agent_models
    models = _get_agent_models()
    print("  models=" + str(models))
    assert "SAGE_MODEL" in models, "SAGE_MODEL missing"
    assert "REX_MODEL" in models, "REX_MODEL missing"
    assert "IRIS_MODEL" in models, "IRIS_MODEL missing"
    assert "NOVA_MODEL" in models, "NOVA_MODEL missing"
    for k, v in models.items():
        assert v not in ["claude-sonnet", "deepseek-chat", "deepseek-reasoner"], \\
            f"{k} still hardcoded to {v} — should be local-fast or local-heavy"''',
         '''@test("_get_agent_models reflects the switcher, and local-only overrides it")
def test_agent_models_from_dashboard():
    """
    This used to assert no agent was on a paid model — a fact about the
    DASHBOARD, not the code, so setting the switcher for a production run made
    it fail. It now asserts the two things the function actually promises.
    """
    import os
    import urllib.request
    import json as _json
    from flows.langgraph_flow import _get_agent_models, _AGENTS, _LOCAL_MODEL

    _saved = os.environ.get("DUCORN_LOCAL_ONLY")
    try:
        # 1. A local-only run pins EVERY agent, whatever the switcher says.
        #    This is the guarantee that a test run cannot bill.
        os.environ["DUCORN_LOCAL_ONLY"] = "1"
        pinned = _get_agent_models()
        stray = {k: v for k, v in pinned.items() if v != _LOCAL_MODEL}
        assert not stray, f"local-only run would still bill: {stray}"
        for a in _AGENTS:
            assert f"{a}_MODEL" in pinned, f"{a} missing from a pinned run"

        # 2. Otherwise it passes the switcher through verbatim. There is no
        #    translation table any more — the one that used to live here
        #    silently downgraded every model added after it was written.
        os.environ.pop("DUCORN_LOCAL_ONLY", None)
        models = _get_agent_models()
        print("  models=" + str(models))
        for a in _AGENTS:
            assert f"{a}_MODEL" in models, f"{a}_MODEL missing"

        req = urllib.request.Request(
            "http://localhost:8000/agents/config",
            headers={"x-api-key": "ducorn-api-2026-secure"})
        live = _json.loads(urllib.request.urlopen(req, timeout=5).read())
        for name, chosen in (live.get("agents") or {}).items():
            if not chosen:
                continue
            got = models.get(f"{name}_MODEL")
            assert got == chosen, (
                f"{name}: switcher says {chosen!r} but the pipeline would use "
                f"{got!r} — a model picked in the dashboard must be the model "
                f"that runs")
    finally:
        if _saved is None:
            os.environ.pop("DUCORN_LOCAL_ONLY", None)
        else:
            os.environ["DUCORN_LOCAL_ONLY"] = _saved''')

# ═══════════════════════════════════════════════════════════════════════════
# T28 — identical in both files
# ═══════════════════════════════════════════════════════════════════════════
OLD_T28 = '''@test("T28: _get_agent_models() returns local-fast from fresh subprocess (Slack-like env)")
def test_agent_models_no_hardcoded():
    """Simulate Slack bot environment — no NOVA_MODEL set — verify local-fast."""
    env = base_env()
    # Remove any NOVA_MODEL from env (simulates Slack bot env)
    env.pop("NOVA_MODEL", None)
    env.pop("SAGE_MODEL", None)
    env.pop("REX_MODEL", None)
    env.pop("IRIS_MODEL", None)

    result = subprocess.run(
        [PYTHON, "-c", """
import sys
sys.path.insert(0, '/Users/ducorn/DC/scripts')
sys.path.insert(0, '/Users/ducorn/DC/ducorn')
import importlib.util, os, json

# Load langgraph_flow just enough to call _get_agent_models
spec = importlib.util.spec_from_file_location(
    "flow", "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
# Instead, inline the function call
import urllib.request, json as _json
req = urllib.request.Request(
    "http://localhost:8000/agents/config",
    headers={"x-api-key": "ducorn-api-2026-secure"}
)
resp = urllib.request.urlopen(req, timeout=3)
data = _json.loads(resp.read())
agents = data.get("agents", {})
model_map = {
    "claude-sonnet": "claude-sonnet",
    "deepseek-chat": "deepseek-chat",
    "deepseek-reasoner": "deepseek-reasoner",
    "local-fast": "local-fast",
    "local-heavy": "local-heavy",
}
nova = model_map.get(agents.get("NOVA", "local-fast"), "local-fast")
print(json.dumps({"NOVA_MODEL": nova, "SAGE_MODEL": model_map.get(agents.get("SAGE","local-fast"),"local-fast")}))
"""],
        env=env,
        capture_output=True,
        text=True,
        timeout=15
    )

    assert result.returncode == 0, f"Subprocess failed: {result.stderr[:200]}"
    try:
        models = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        raise AssertionError(f"Could not parse output: {result.stdout[:200]}")

    nova = models.get("NOVA_MODEL", "")
    assert nova == "local-fast", \\
        f"NOVA_MODEL should be local-fast, got: {nova} — dashboard may have wrong setting"
    assert "deepseek" not in nova.lower(), f"deepseek leaked into NOVA_MODEL: {nova}"
    print(f"  NOVA_MODEL from fresh subprocess: {nova} ✅")'''

NEW_T28 = '''@test("T28: a fresh subprocess with a bare env still pins local on a test run")
def test_agent_models_no_hardcoded():
    """
    The Slack bot starts pipelines with none of the *_MODEL variables in its
    environment. This proves a run marked local-only still reaches the local
    model from that bare environment — in a fresh interpreter, because the
    failure this covers was a module-level default resolved at import time.

    Rewritten 1 Sept. The old version inlined a copy of a translation table
    that had been deliberately REMOVED from _get_agent_models (it silently
    downgraded any model added after it was written, claude-opus included), so
    it tested a copy of deleted code and would have passed if the real
    function were gone. It also asserted NOVA was local-fast, which is a
    dashboard setting, so it failed the moment the switcher was set for a
    production run.
    """
    env = base_env()
    for _v in ("NOVA_MODEL", "SAGE_MODEL", "REX_MODEL", "IRIS_MODEL",
               "DESIGN_MODEL"):
        env.pop(_v, None)
    env["DUCORN_LOCAL_ONLY"] = "1"

    result = subprocess.run(
        [PYTHON, "-c", """
import sys, json
sys.path.insert(0, '/Users/ducorn/DC/scripts')
sys.path.insert(0, '/Users/ducorn/DC/ducorn')
from flows.langgraph_flow import _get_agent_models, _LOCAL_MODEL, _AGENTS
print("RESULT " + json.dumps({"models": _get_agent_models(),
                              "local": _LOCAL_MODEL,
                              "agents": list(_AGENTS)}))
"""],
        env=env,
        capture_output=True,
        text=True,
        timeout=60
    )

    assert result.returncode == 0, f"Subprocess failed: {result.stderr[-400:]}"
    line = next((l for l in result.stdout.splitlines()
                 if l.startswith("RESULT ")), None)
    assert line, f"no RESULT line in output: {result.stdout[-300:]}"
    payload = json.loads(line[len("RESULT "):])

    models, local, agents = payload["models"], payload["local"], payload["agents"]
    for a in agents:
        got = models.get(f"{a}_MODEL")
        assert got == local, (
            f"{a}_MODEL is {got!r} on a local-only run — it must be {local!r}. "
            f"A test run that reaches a paid model bills real money.")
    print(f"  all {len(agents)} agents pinned to {local} from a bare env ✅")'''

p = swap(PIPE, "T28", p, OLD_T28, NEW_T28)

i = INTEG.read_text(encoding="utf-8")
if "a bare env still pins local" in i:
    print("note: test_integration.py already has the new T28 — skipping it")
    integ_new = None
else:
    integ_new = swap(INTEG, "T28", i, OLD_T28, NEW_T28)

# ═══════════════════════════════════════════════════════════════════════════
for path, text in [(PIPE, p)] + ([(INTEG, integ_new)] if integ_new else []):
    backup = path.with_name(f"{path.stem}.backup-sept1-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")
    try:
        ast.parse(text)
    except SyntaxError as e:
        shutil.copy2(backup, path)
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — reverted from {backup}")

print("applied:")
for a in applied:
    print(f"  {a}")
print(f"backups: *.backup-sept1-{stamp}.py")
print()
print("Run the suites:")
print("  cd ~/DC/ducorn && .venv/bin/python test_pipeline.py")
print("  cd ~/DC/ducorn && .venv/bin/python test_integration.py")
print()
print("The five research tests each do a real Ollama run — allow ~10 minutes.")
