#!/usr/bin/env python3
"""
Every defect we have fixed, asserted to still be fixed.

    cd ~/DC && python3 scripts/regress.py           run them all
    cd ~/DC && python3 scripts/regress.py -v        show each check's reason
    cd ~/DC && python3 scripts/regress.py --list    what is covered

Exit 0 = nothing regressed. Exit 1 = something did, and the message names it.

── WHY IT EXISTS ────────────────────────────────────────────────────────────

Every fix in this pipeline was verified once, by the patch that applied it,
and never again. Fifteen-odd defects, each protected by a check that ran for
one second in the past. Nothing stops the next patch from undoing one, and
the way we would find out is a test run failing in a way that looks new.

A recurrence that nothing detects is not closed. This is what closes them.

── WHAT IT DELIBERATELY IS AND IS NOT ───────────────────────────────────────

STDLIB ONLY, and no imports of the pipeline's heavy modules. It runs under
whichever python3 is on PATH — no venv, no pytest, no crewai, no database, no
network, no model. It takes about a second.

That is not laziness, it is the point: a check you have to set something up
to run is a check that gets skipped exactly when it matters. An earlier patch
in this project imported yaml under a python that did not have it and
reported a working config as broken.

Pure functions are EXTRACTED FROM THE SOURCE with ast and executed, so what
gets tested is the code that will run — not a copy of it living here, which
would be one more second copy of a fact, drifting.

Where behaviour cannot be reached without the pipeline, the check asserts
STRUCTURE from the parse tree: which statement an else hangs off, what order
two calls happen in, whether a call exists inside a particular function.
Never a text search — three patches in this project verified themselves
against their own explanatory comments and told the operator to restore a
correct file.

── PASS, FAIL, AND SKIP ARE THREE DIFFERENT ANSWERS ─────────────────────────

A check that cannot run SKIPS, loudly, with the reason. It never fails.
Conflating "I could not check this" with "this is broken" is how a working
config got reported as broken once already, and it is how a suite teaches you
to ignore it.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))

RUNNER = DC / "ducorn" / "skill_runner.py"
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
WRITER = DC / "ducorn" / "tools" / "DuCornWriterTool.py"
JAIL = DC / "ducorn" / "tools" / "product_jail.py"
SPEC = DC / "ducorn" / "tools" / "design_spec.py"
GEN = DC / "ducorn" / "tools" / "generate_design.py"
PROXY = DC / "scripts" / "ducorn_proxy.py"
RECOVERY = DC / "scripts" / "run_recovery.py"
PRODUCT_DIR = DC / "scripts" / "product_dir.py"


class Skip(Exception):
    """Could not be checked. Not a failure."""


class Fail(Exception):
    """A fix that is no longer in place."""


CHECKS = []


def check(defect: str):
    """Register a check. The name is the DEFECT, not the assertion."""
    def wrap(fn):
        CHECKS.append((defect, fn))
        return fn
    return wrap


# ── helpers ──────────────────────────────────────────────────────────────────

def src(path: Path) -> str:
    if not path.is_file():
        raise Skip(f"{path.relative_to(DC) if DC in path.parents else path} "
                   f"is not there")
    return path.read_text(encoding="utf-8", errors="replace")


def tree(path: Path) -> ast.Module:
    try:
        return ast.parse(src(path))
    except SyntaxError as e:
        raise Fail(f"{path.name} does not parse: line {e.lineno}: {e.msg}")


def func(t: ast.Module, name: str) -> ast.AST:
    """
    A named function, or a FAILURE — deliberately not a skip.

    Every function these checks reach for is load-bearing: it either IS a
    fix or is the scope a fix lives in. If one is gone, the fix is gone or
    the code moved, and either way nobody has verified the invariant. Skipping
    would make deleting a fix the quietest possible outcome — which is how
    three separate mutations slipped past the first draft of this suite.

    A rename shows up here as a failure too. That is the correct cost: the
    person who renamed it updates this check, and the invariant keeps its
    guard.
    """
    for node in ast.walk(t):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise Fail(f"there is no function named {name!r} any more — gone, or "
               f"renamed. If renamed, point this check at the new name.")


def calls_in(t: ast.Module, scope_name, name: str) -> list:
    """Calls to `name` inside `scope_name` (None = whole module)."""
    scope = func(t, scope_name) if scope_name else t
    out = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        called = (f.id if isinstance(f, ast.Name)
                  else f.attr if isinstance(f, ast.Attribute) else "")
        if called == name:
            out.append(node)
    return out


def ifs_in(t: ast.Module, scope_name, contains: str) -> list:
    """[(lineno, has_else)] for `if`s whose TEST mentions `contains`."""
    scope = func(t, scope_name) if scope_name else t
    return sorted((n.lineno, bool(n.orelse)) for n in ast.walk(scope)
                  if isinstance(n, ast.If) and contains in ast.dump(n.test))


def bound_name(node):
    """
    The name a top-level statement binds, or None.

    AnnAssign matters: `_WRITES: dict = {}` is an ANNOTATED assignment and
    ast.Assign does not match it. A version of this that only knew about
    Assign silently failed to find such a name and reported correct code as
    broken.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and node.targets:
        return getattr(node.targets[0], "id", None)
    if isinstance(node, ast.AnnAssign):
        return getattr(node.target, "id", None)
    return None


def take(t: ast.Module, *names) -> dict:
    """
    Execute the named module-level functions/assignments in isolation.

    This is how a pure function gets tested without importing the module it
    lives in. What runs is the shipped source.
    """
    wanted = list(names)
    body = [n for n in t.body if bound_name(n) in wanted]
    missing = set(names) - {bound_name(n) for n in body}
    if missing:
        # A FAILURE, not a skip — see func(). Deleting repair_contrast made
        # this check go quiet in an earlier draft, which is the one outcome
        # a regression suite must never produce.
        raise Fail(f"gone from module level: {sorted(missing)} — the fix "
                   f"these implement cannot be verified, and may be gone. "
                   f"If they moved, point this check at the new location.")
    ns: dict = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "<shipped>", "exec"),
         ns)
    return ns


MODEL_CALLS = ("run_with_crewai", "run_with_cursor")


def paid_model_calls(scope) -> list:
    """
    Line numbers of calls that actually SPEND.

    main() also calls run_with_crewai(..., dry_run=True) to validate a prompt.
    That one is free, and it sits before the odometer and before the
    tests-decide guard. Counting it made one check fail on correct code and,
    worse, made another pass for the wrong reason — any earlier exit
    anywhere in main() satisfied "there is an exit before the model call".
    A check that cannot fail is not a check.
    """
    out = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = (f.id if isinstance(f, ast.Name)
                else f.attr if isinstance(f, ast.Attribute) else "")
        if name not in MODEL_CALLS:
            continue
        dry = any(k.arg == "dry_run"
                  and isinstance(k.value, ast.Constant)
                  and k.value.value is True for k in node.keywords)
        if not dry:
            out.append(node.lineno)
    return sorted(out)


def literal(t: ast.Module, name: str):
    """The value of a module-level `name = <literal>`."""
    for node in t.body:
        if isinstance(node, ast.Assign) and node.targets \
                and getattr(node.targets[0], "id", None) == name:
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                raise Skip(f"{name} is no longer a literal")
    raise Skip(f"no module-level {name}")


def env_default(t: ast.Module, name: str):
    """The default of `name = <cast>(os.environ.get('X', 'default'))`."""
    for node in ast.walk(t):
        if not (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], "id", None) == name):
            continue
        for sub in ast.walk(node.value):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get" and len(sub.args) == 2):
                try:
                    return ast.literal_eval(sub.args[1])
                except ValueError:
                    raise Skip(f"{name}'s default is not a literal")
    raise Skip(f"{name} is not read from the environment with a default")


# ═════════════════════════ the checks ═══════════════════════════════════════

@check("a skill's verdict is read only from the final answer, so a "
       "completed skill whose agent looped was recorded as failed")
def verdict_precedence():
    ns = take(tree(RUNNER), "resolve_review_verdict")
    r = ns["resolve_review_verdict"]
    SP, SF = ("pass", "V: PASS"), ("fail", "V: FAIL")
    WP = ("pass", "V: PASS", "review.md")
    WF = ("fail", "V: FAIL", "review.md")
    table = [
        (None, WP, "pass", "loop aborted, the document says PASS"),
        (None, WF, "fail", "loop aborted, the document says FAIL"),
        (None, None, "fail", "nothing anywhere"),
        (SP, None, "pass", "no document, the answer says PASS"),
        (SF, None, "fail", "no document, the answer says FAIL"),
        (SP, WP, "pass", "both agree on PASS"),
        (SF, WF, "fail", "both agree on FAIL"),
        (SP, WF, "fail", "answer PASS, document FAIL"),
        (SF, WP, "fail", "document PASS, answer FAIL"),
    ]
    for said, wrote, want, why in table:
        got = r(said, wrote)[0]
        if got != want:
            raise Fail(f"{why}: expected {want}, got {got}")
    return f"{len(table)} combinations, both disagreements resolve to fail"


@check("'no verdict present' and 'the verdict is FAIL' were the same answer")
def absent_is_not_fail():
    ns = take(tree(RUNNER), "explicit_verdict", "parse_verdict")
    ev, pv = ns["explicit_verdict"], ns["parse_verdict"]
    if ev("nothing to see here") is not None:
        raise Fail("explicit_verdict invents a verdict where there is none")
    if ev("blah\nVERDICT: PASS")[0] != "pass":
        raise Fail("explicit_verdict misses a real PASS")
    if ev("REVIEW VERDICT: APPROVED") is not None:
        raise Fail("'REVIEW VERDICT:' is matched as a verdict line")
    if pv("nothing")[0] != "fail":
        raise Fail("parse_verdict stopped failing on a missing verdict")
    return "absent, PASS and FAIL are three distinct answers"


@check("the deliverable lookup joined an agent-chosen filename onto the "
       "product dir, so an absolute name read another product's file")
def verdict_lookup_is_jailed():
    t = tree(RUNNER)
    if not calls_in(t, "verdict_in_deliverables", "resolve_in_jail"):
        raise Fail("verdict_in_deliverables no longer resolves through the "
                   "jail — an absolute filename would escape the product")
    if calls_in(t, "verdict_in_deliverables", "_product_dir"):
        raise Fail("_product_dir is being joined to an agent-chosen name "
                   "again; pathlib discards the left side of that join")
    return "resolved through product_jail, never joined by hand"


@check("a dangling else made every non-build skill fail — the else belonged "
       "to the length test and had attached itself to the BUILD_SKILL test")
def else_belongs_to_the_length_test():
    t = tree(RUNNER)
    length = ifs_in(t, "main", "200")
    build = ifs_in(t, "main", "BUILD_SKILL")
    if len(length) != 1:
        raise Skip(f"expected one length test in main(), found {len(length)}")
    if not length[0][1]:
        raise Fail("the length test has no else — a short output would fall "
                   "through instead of failing")
    if len(build) != 1:
        raise Skip(f"expected one BUILD_SKILL test in main(), found "
                   f"{len(build)}")
    if build[0][1]:
        raise Fail("the BUILD_SKILL test has an else again — that is the "
                   "dangling else that failed every non-build skill")
    return "the length test owns its else; the build test has none"


@check("a failing pytest still paid for a model call before the verdict "
       "logic overrode it")
def tests_decide_before_paying():
    t = tree(RUNNER)
    m = func(t, "main")
    paid = paid_model_calls(m)
    if not paid:
        raise Skip("main() no longer calls the model directly")

    # The specific guard, not "some exit somewhere earlier". It has to be the
    # branch that reads the test result, and it has to leave.
    guard = None
    for node in ast.walk(m):
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "test_status" in test and "ui_status" in test:
            leaves = any(isinstance(n, ast.Call)
                         and getattr(n.func, "attr", getattr(n.func, "id", ""))
                         == "exit" for n in ast.walk(node))
            if leaves:
                guard = node
                break
    if guard is None:
        raise Fail("no branch in main() reads test_status/ui_status and exits "
                   "— a failing test suite would reach the paid call and be "
                   "billed for an outcome it cannot change")
    if guard.lineno > paid[0]:
        raise Fail(f"the tests-decide guard is at line {guard.lineno}, after "
                   f"the paid call at {paid[0]} — it can no longer prevent "
                   f"the spend")
    return (f"the guard at line {guard.lineno} exits before the paid call at "
            f"{paid[0]}")


@check("cost_so_far was never populated — no odometer around the paid call")
def cost_is_measured_around_the_call():
    t = tree(RUNNER)
    m = func(t, "main")
    paid = paid_model_calls(m)
    if not paid:
        raise Skip("main() no longer calls the model directly")
    spend = [n.lineno for n in calls_in(t, "main", "_spend_now")]
    if not spend:
        raise Fail("_spend_now is not called in main() — per-skill cost is "
                   "unmeasured again, which is what made cost_so_far a lie")
    lo, hi = paid[0], paid[-1]
    if not any(s < lo for s in spend):
        raise Fail(f"nothing reads the odometer before the paid call at {lo}")
    if not any(s > hi for s in spend):
        raise Fail(f"nothing reads the odometer after the paid call at {hi}")
    return f"read at {min(spend)} and {max(spend)}, bracketing {lo}-{hi}"


@check("the local model was a literal, so a test run could not be pointed at "
       "a model capable of finishing a skill")
def local_model_is_a_setting():
    t = tree(FLOW)
    assign = next((n for n in t.body
                   if isinstance(n, ast.Assign) and n.targets
                   and getattr(n.targets[0], "id", None) == "_LOCAL_MODEL"),
                  None)
    if assign is None:
        raise Skip("there is no module-level _LOCAL_MODEL any more")
    # A LITERAL here is the regression itself, not something unmeasurable.
    #
    # The first version of this check asked env_default() for the fallback
    # and let a missing os.environ.get SKIP. Reverting the fix therefore made
    # the check go quiet instead of red — the precise confusion between "I
    # could not check" and "this is broken" that the header of this file
    # warns about, committed one function below the warning.
    if isinstance(assign.value, ast.Constant):
        raise Fail(f"_LOCAL_MODEL is hardcoded to "
                   f"{assign.value.value!r} again — the dashboard switcher "
                   f"stops being the single source of truth for the model")
    default = env_default(t, "_LOCAL_MODEL")
    if not default:
        raise Fail("_LOCAL_MODEL has no fallback — a machine without the "
                   "setting would pin agents to nothing")
    return f"read from DUCORN_LOCAL_MODEL, default {default!r}"


@check("the router's timeout was shorter than the render budget it carried, "
       "so the inner budget could never be reached")
def router_outlasts_what_it_carries():
    pt = tree(PROXY)
    # Read the timeout the client is ACTUALLY given, not a constant that may
    # no longer be wired to it. A hardcoded number here is the original bug.
    given = None
    for node in ast.walk(pt):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "AsyncClient"):
            continue
        for k in node.keywords:
            if k.arg != "timeout":
                continue
            if isinstance(k.value, ast.Constant):
                raise Fail(f"the router hardcodes timeout="
                           f"{k.value.value} again — it was 300s while a "
                           f"render is allowed 900s, so the outer limit cut "
                           f"off a call the caller still considered live")
            given = getattr(k.value, "id", None)
    if given is None:
        raise Skip("no AsyncClient(timeout=...) found in ducorn_proxy")
    router = env_default(pt, given)
    render = literal(tree(GEN), "RENDER_TIMEOUT")
    if float(router) < float(render):
        raise Fail(f"the router allows {router}s but a render is given "
                   f"{render}s — the outer limit is shorter than the inner "
                   f"one again")
    return f"router {router}s >= render {render}s"


@check("eleven sites derived products/<topic>/ independently, and they "
       "disagreed once the epic layout arrived")
def one_resolver_for_the_product_dir():
    if not PRODUCT_DIR.is_file():
        raise Fail("scripts/product_dir.py is gone — the single resolver")
    offenders = []
    roots = [DC / "ducorn", DC / "scripts"]
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(DC).as_posix()
            if (".venv" in rel or "/applied/" in rel or ".backup-" in rel
                    or rel.endswith("product_dir.py")
                    or "test_" in p.name or p.name.startswith("patch_")):
                continue
            try:
                t = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(t):
                # Path(f"...products/{topic}...") — a path BUILT from the
                # topic. A prompt string that merely mentions the directory
                # is not path construction and must not be flagged.
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "Path" and node.args):
                    continue
                arg = node.args[0]
                if not isinstance(arg, ast.JoinedStr):
                    continue
                text = "".join(v.value for v in arg.values
                               if isinstance(v, ast.Constant)
                               and isinstance(v.value, str))
                names = {n.id for v in arg.values
                         if isinstance(v, ast.FormattedValue)
                         for n in ast.walk(v.value) if isinstance(n, ast.Name)}
                if "products/" in text and "topic" in names:
                    offenders.append(f"{rel}:{node.lineno}")
    if offenders:
        raise Fail("a product path is built from the topic instead of asking "
                   "product_dir.for_topic:\n      " + "\n      ".join(offenders))
    return "no live module derives the product directory itself"


@check("a design was thrown away for missing a contrast threshold by 0.2, "
       "and a paid model was asked to guess the number again")
def contrast_is_repaired_by_arithmetic():
    t = tree(SPEC)
    ns = take(t, "_rgb", "_luminance", "contrast_ratio", "_nudge",
              "repair_contrast")
    repair, ratio = ns["repair_contrast"], ns["contrast_ratio"]
    spec = {"dark_palette": {"bg": "#12161a", "surface": "#1b2026",
                             "ink": "#e6edf3", "ink_muted": "#585e66",
                             "accent": "#4fd1c5"}}
    before = ratio(spec["dark_palette"]["ink_muted"],
                   spec["dark_palette"]["bg"])
    if before >= 3.0:
        raise Skip("the fixture palette no longer fails the threshold")
    reps = repair(spec)
    after = ratio(spec["dark_palette"]["ink_muted"],
                  spec["dark_palette"]["bg"])
    if after < 3.0:
        raise Fail(f"the repair left it at {after:.2f}:1")
    if not reps:
        raise Fail("the repair was silent — it must say what it changed")
    hopeless = {"palette": {"bg": "#808080", "ink": "#8a8a8a",
                            "ink_muted": "#858585", "accent": "#999999"}}
    keep = hopeless["palette"]["ink_muted"]
    repair(hopeless)
    if hopeless["palette"]["ink_muted"] != keep:
        raise Fail("an unrepairable palette was altered anyway — when even "
                   "full ink fails, the background is the problem")
    return f"{before:.2f}:1 -> {after:.2f}:1, and an unrepairable one is left alone"


@check("the build gate scraped a prose sentence about future phases instead "
       "of reading what was built")
def build_is_judged_by_what_it_wrote():
    t = tree(RUNNER)
    inside = calls_in(t, "main", "build_produced_code")
    if not inside:
        raise Fail("main() no longer calls build_produced_code — a build "
                   "would be judged by how much it said, not what it wrote")
    build = ifs_in(t, "main", "BUILD_SKILL")
    if len(build) == 1 and build[0][1]:
        raise Fail("the build check grew an else; it may only downgrade a "
                   "pass, never decide anything for other skills")
    return "the build gate reads the files, and can only downgrade"


@check("run_recovery kept its own idea of which skills a QA rejection "
       "re-runs, free to drift from skill_runner's")
def recovery_defers_to_the_runner():
    t = tree(RECOVERY)
    own = [n for n in t.body if isinstance(n, ast.Assign) and n.targets
           and getattr(n.targets[0], "id", None) == "FEEDBACK_SKILLS"]
    if own:
        raise Fail("run_recovery defines its own FEEDBACK_SKILLS — two copies "
                   "of one fact; it must read skill_runner's")
    body = src(RECOVERY)
    if "FEEDBACK_SKILLS" not in body:
        raise Skip("run_recovery no longer mentions FEEDBACK_SKILLS")
    if not re.search(r"\bsr\.FEEDBACK_SKILLS\b|"
                     r"skill_runner\.FEEDBACK_SKILLS", body):
        raise Fail("run_recovery reads FEEDBACK_SKILLS from somewhere other "
                   "than skill_runner")
    return "the one definition lives in skill_runner"


@check("an agent could write outside its own product, so one product could "
       "reach another's files")
def the_jail_still_refuses():
    t = tree(JAIL)
    if not any(isinstance(n, ast.ClassDef) and n.name == "PathEscape"
               for n in ast.walk(t)):
        raise Skip("PathEscape is not a class in product_jail any more")
    r = func(t, "resolve_in_jail")
    raises = [n for n in ast.walk(r) if isinstance(n, ast.Raise)]
    if not raises:
        raise Fail("resolve_in_jail no longer raises — it must refuse a path "
                   "outside the product, not resolve it somewhere")
    wt = tree(WRITER)
    if not calls_in(wt, "_run", "resolve_in_jail"):
        raise Fail("the writer tool no longer resolves through the jail")
    return "resolve_in_jail refuses, and the writer goes through it"


@check("the write-loop guard has to survive CrewAI's own exception handling")
def write_loop_guard_passes_through_crewai():
    t = tree(WRITER)
    cls = next((n for n in ast.walk(t) if isinstance(n, ast.ClassDef)
                and n.name == "WriteLoopAborted"), None)
    if cls is None:
        raise Skip("WriteLoopAborted is gone")
    bases = {b.id for b in cls.bases if isinstance(b, ast.Name)}
    if "BaseException" not in bases:
        raise Fail(f"WriteLoopAborted derives from {bases or '{}'} — CrewAI "
                   f"catches Exception around a tool call and feeds it back "
                   f"to the agent as another turn in the loop, so it must be "
                   f"a BaseException to escape")
    return "a BaseException, so it passes through the framework"


# ═════════════════════════ runner ════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for i, (defect, fn) in enumerate(CHECKS, 1):
            print(f"{i:2}. {fn.__name__}\n    {defect}\n")
        return 0

    if not DC.is_dir():
        print(f"{DC} is not there. Set DUCORN_ROOT if the stack moved.")
        return 1

    print(f"regress — {len(CHECKS)} fixed defects, checked against {DC}\n")
    passed, failed, skipped = 0, [], []

    for defect, fn in CHECKS:
        try:
            note = fn()
        except Skip as e:
            skipped.append((fn.__name__, str(e)))
            print(f"  ⏭  {fn.__name__:<38} {e}")
        except Fail as e:
            failed.append((fn.__name__, defect, str(e)))
            print(f"  ❌ {fn.__name__:<38} REGRESSED")
        except Exception as e:                      # noqa: BLE001
            failed.append((fn.__name__, defect,
                           f"the check itself broke: {type(e).__name__}: {e}"))
            print(f"  ❌ {fn.__name__:<38} the check itself broke")
        else:
            passed += 1
            print(f"  ✅ {fn.__name__:<38}" + (f" {note}" if a.verbose else ""))

    print()
    if failed:
        print(f"{len(failed)} REGRESSION(S):\n")
        for name, defect, why in failed:
            print(f"  {name}")
            print(f"    the defect: {defect}")
            print(f"    now:        {why}\n")

    if skipped and not a.verbose:
        print(f"{len(skipped)} skipped (could not be checked — not failures). "
              f"-v for detail.\n")

    print(f"{passed} held, {len(failed)} regressed, {len(skipped)} skipped.")
    if not failed:
        print("Nothing we have fixed has come undone.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
