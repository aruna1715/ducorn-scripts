#!/usr/bin/env python3
"""
Make the four combination tests test the combinations.

── WHAT THEY DO NOW ─────────────────────────────────────────────────────────

Each one runs a full research phase on Ollama with a different set of flags:

    _run_pipeline_combo(topic, engine="gstack", coder="cursor", complexity="medium")
        → langgraph_flow.py <topic> --phase research --engine gstack ...
        → assert a gate_1 approval row exists

Research does not read engine, coder or complexity. Those three flags only
reach node_build, which none of these tests get anywhere near. So all four run
the identical research step, assert the identical thing, and differ only in
arguments that have no effect on what they exercise — about forty minutes of
Ollama to prove one fact the e2e test already proves.

That is why the suite times out, and it is also why the suite has not been
catching anything: it is slow in the place where it is redundant and silent in
the place where the flags actually do something.

── WHAT THEY DO AFTER THIS ──────────────────────────────────────────────────

They call node_build for real, with every subprocess replaced by a recorder,
and assert what it tried to run. No model, no network, no tokens, about a
second for all five.

    fast   + crewai + simple   → skill 04, coder crewai
    fast   + cursor + medium   → skill 04, coder cursor
    gstack + cursor + medium   → skills 01 02 03 04 05 06, coder cursor
    gstack + cursor + complex  → skills 01 02 03 04 05 06
    gstack + crewai + simple   → skills 01 04 05 06   ← 02/03 are complexity-gated

That last one is not currently asserted anywhere, and it is the behaviour most
likely to change: skills 02 and 03 are the G-Stack design pair, which now
duplicate node_design for a has_ui product. When we do skip them, this test is
what tells us we skipped exactly those two and nothing else.

Three further things each build combination now proves, none of them covered
before:

  · the coder reaches skill_runner. It is passed as --coder on every skill
    call, and a build that silently ran crewai when cursor was chosen would
    look completely normal in the logs.

  · node_build hands off to qa. The return value is checked, not just the
    absence of an exception.

  · THE AUTO-COMMIT STAGES ONLY THIS PRODUCT'S DIRECTORY. That commit runs
    `git add products/<topic>/`, and a `git add .` there would sweep every
    other product's files into one product's commit. Product isolation is a
    showstopper on this project and nothing tested this line.

Because subprocess is replaced, that commit is recorded rather than executed —
the test reads what the build WOULD have run, and nothing is pushed.

── WHAT IS NOT LOST ─────────────────────────────────────────────────────────

Two things the old tests did are kept, deliberately:

  · a real research run to gate_1 on Ollama. That still exists, once, as
    "Full research to gate_1 flow using Ollama". One is enough; four was
    three too many.

  · argparse accepting each flag combination. That was implicitly covered by
    launching the process, so it is now covered explicitly and cheaply: each
    combination is passed to the real parser with one deliberately invalid
    --phase, and argparse must reject exactly that and nothing else.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PIPE = Path("/Users/ducorn/DC/ducorn/test_pipeline.py")
src = PIPE.read_text(encoding="utf-8")

if "_build_calls" in src:
    sys.exit("Already patched — _build_calls exists.")

TARGETS = ["_run_pipeline_combo",
           "test_combo_simple_fast_crewai",
           "test_combo_medium_fast_cursor",
           "test_combo_medium_gstack_cursor",
           "test_combo_complex_gstack_cursor"]

tree = ast.parse(src)
found = {}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in TARGETS:
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        found[node.name] = (start, node.end_lineno)

missing = [t for t in TARGETS if t not in found]
if missing:
    sys.exit(f"ANCHOR MISS: these functions are not at module level in "
             f"{PIPE.name}: {missing}. NOTHING WRITTEN.")

first = min(s for s, _ in found.values())
last = max(e for _, e in found.values())

# They must be one contiguous block — if something else has been written
# between them, splicing the range would delete it.
between = {n for n in tree.body
           if getattr(n, "lineno", 0) >= first
           and getattr(n, "end_lineno", 0) <= last}
strays = [getattr(n, "name", type(n).__name__) for n in between
          if getattr(n, "name", None) not in TARGETS]
if strays:
    sys.exit(f"ANCHOR MISS: {strays} sits inside the block being replaced "
             f"(lines {first}-{last}). NOTHING WRITTEN.")

NEW = '''def _build_calls(topic, engine, coder, complexity, product_type="software"):
    """
    Run node_build for real, with every subprocess replaced by a recorder.

    Returns (returned_state, calls) where calls is the argv of everything the
    build tried to launch — skill_runner invocations and the auto-commit.

    Nothing is executed and nothing is billed: subprocess is swapped out on the
    flow module only (not globally), and DUCORN_LOCAL_ONLY is set so the model
    lookup cannot reach a paid model even if the switcher says otherwise.

    This replaces four tests that each ran a full Ollama research phase to
    assert something research does not depend on. engine, coder and complexity
    are read HERE, in node_build, and nowhere else.
    """
    import types
    import subprocess as _sp
    import flows.langgraph_flow as F

    calls = []

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def _record(argv, **kw):
        calls.append(list(argv))
        return _Done()

    saved_sp, saved_slack, saved_db = (F.subprocess, F._post_slack,
                                       F._update_db_status)
    saved_local = os.environ.get("DUCORN_LOCAL_ONLY")
    os.environ["DUCORN_LOCAL_ONLY"] = "1"
    # Only the names node_build uses. A SimpleNamespace rather than patching
    # the real subprocess module, so nothing else in this process is affected.
    F.subprocess = types.SimpleNamespace(
        run=_record,
        TimeoutExpired=_sp.TimeoutExpired,
        CalledProcessError=_sp.CalledProcessError,
        PIPE=_sp.PIPE,
        DEVNULL=_sp.DEVNULL,
    )
    F._post_slack = lambda *a, **k: None
    F._update_db_status = lambda *a, **k: None
    try:
        out = F.node_build({
            "topic": topic,
            "build_engine": engine,
            "coder": coder,
            "complexity": complexity,
            "product_type": product_type,
        })
    finally:
        F.subprocess, F._post_slack, F._update_db_status = (
            saved_sp, saved_slack, saved_db)
        if saved_local is None:
            os.environ.pop("DUCORN_LOCAL_ONLY", None)
        else:
            os.environ["DUCORN_LOCAL_ONLY"] = saved_local
    return out, calls


def _skills_and_coders(calls):
    """The skill numbers, in order, and the set of coders they were given."""
    skills = [a[a.index("--skill") + 1] for a in calls if "--skill" in a]
    coders = {a[a.index("--coder") + 1] for a in calls if "--coder" in a}
    return skills, coders


def _assert_isolated_commit(calls, topic):
    """
    The auto-commit after a build must stage this product and nothing else.

    `git add .` here would sweep every other product's working files into one
    product's commit. One product must never touch another's files — that is a
    showstopper on this project, and this line had no test.
    """
    commits = [a for a in calls if a[:2] == ["bash", "-c"]]
    assert commits, "the build did not attempt an auto-commit"
    cmd = commits[0][2]
    assert f"products/{topic}/" in cmd, (
        f"the build commit is not scoped to {topic}: {cmd}")
    for greedy in ("git add .", "git add -A", "git add --all"):
        assert greedy not in cmd, (
            f"the build commit stages everything, not just this product: {cmd}")


def _assert_build(engine, coder, complexity, expect_skills, suffix):
    topic = TEST_SLUG + suffix
    out, calls = _build_calls(topic, engine, coder, complexity)
    skills, coders = _skills_and_coders(calls)
    assert skills == expect_skills, (
        f"{engine}/{coder}/{complexity} ran skills {skills}, expected "
        f"{expect_skills}")
    assert coders == {coder}, (
        f"coder {coder!r} was chosen but skill_runner was given {coders} — a "
        f"build that quietly uses the other coder looks normal in the logs")
    assert out.get("phase") == "qa", (
        f"build should hand off to qa, returned phase={out.get('phase')!r} "
        f"status={out.get('status')!r} error={out.get('error')!r}")
    _assert_isolated_commit(calls, topic)
    print(f"  {engine}/{coder}/{complexity} → skills {skills} via {coder} ✅")


@test("Build combo: Simple + Fast + CrewAI")
def test_combo_simple_fast_crewai():
    _assert_build("fast", "crewai", "simple", ["04"], "-c1")


@test("Build combo: Medium + Fast + Cursor")
def test_combo_medium_fast_cursor():
    _assert_build("fast", "cursor", "medium", ["04"], "-c2")


@test("Build combo: Medium + G-Stack + Cursor")
def test_combo_medium_gstack_cursor():
    _assert_build("gstack", "cursor", "medium",
                  ["01", "02", "03", "04", "05", "06"], "-c3")


@test("Build combo: Complex + G-Stack + Cursor")
def test_combo_complex_gstack_cursor():
    _assert_build("gstack", "cursor", "complex",
                  ["01", "02", "03", "04", "05", "06"], "-c4")


@test("Build combo: Simple + G-Stack skips the design skills 02 and 03")
def test_combo_simple_gstack_skips_design():
    """
    The design pair is gated on complexity, and nothing asserted which two
    skills the gate drops. When we make a has_ui product skip 02/03 as well —
    they duplicate node_design — this is the test that says we skipped exactly
    those two and left 01, 04, 05 and 06 alone.
    """
    _assert_build("gstack", "crewai", "simple", ["01", "04", "05", "06"], "-c5")


@test("argparse accepts every engine/coder/complexity combination")
def test_flag_combinations_parse():
    """
    Launching four processes used to cover this by accident. Now it is checked
    on purpose: each combination goes to the real parser with one deliberately
    invalid --phase, and argparse must reject that and only that. If any of the
    other three flags were wrong, the error would name a different option.
    """
    combos = [("fast", "crewai", "simple"), ("fast", "cursor", "medium"),
              ("gstack", "cursor", "medium"), ("gstack", "cursor", "complex"),
              ("gstack", "crewai", "simple")]
    for engine, coder, complexity in combos:
        r = subprocess.run(
            [PYTHON, "/Users/ducorn/DC/ducorn/flows/langgraph_flow.py",
             "zz-parse-only", "--engine", engine, "--coder", coder,
             "--complexity", complexity, "--phase", "not-a-real-phase"],
            capture_output=True, text=True, timeout=180, env=base_env(),
            cwd="/Users/ducorn/DC/ducorn")
        err = r.stderr
        assert r.returncode == 2, (
            f"{engine}/{coder}/{complexity}: expected argparse to exit 2, got "
            f"{r.returncode}. It may have STARTED A RUN. stderr: {err[-300:]}")
        assert "--phase" in err and "not-a-real-phase" in err, (
            f"{engine}/{coder}/{complexity}: argparse rejected something other "
            f"than the bad phase: {err[-300:]}")
    print(f"  {len(combos)} combinations accepted by the parser ✅")
'''

lines = src.splitlines(keepends=True)
patched = "".join(lines[:first - 1]) + NEW + "".join(lines[last:])

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PIPE.with_name(f"test_pipeline.backup-combos-{stamp}.py")
shutil.copy2(PIPE, backup)
PIPE.write_text(patched, encoding="utf-8")

try:
    ast.parse(patched)
except SyntaxError as e:
    shutil.copy2(backup, PIPE)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# Nothing that survived should still reference the removed helper.
if "_run_pipeline_combo" in patched:
    shutil.copy2(backup, PIPE)
    sys.exit(f"_run_pipeline_combo is still referenced after the splice — "
             f"reverted from {backup}")

new_tree = ast.parse(patched)
names = [n.name for n in new_tree.body if isinstance(n, ast.FunctionDef)]
for must in ("_build_calls", "_assert_build", "_assert_isolated_commit",
             "test_combo_simple_gstack_skips_design",
             "test_flag_combinations_parse"):
    if must not in names:
        shutil.copy2(backup, PIPE)
        sys.exit(f"{must} missing after the splice — reverted from {backup}")

print(f"replaced lines {first}-{last}: 1 helper + 4 tests")
print(f"now:            3 helpers + 6 tests, no model calls")
print(f"backup:         {backup.name}")
print()
print("Runtime for these six should be about 40 seconds, almost all of it the")
print("five interpreter starts in the argparse test — down from ~40 minutes.")
