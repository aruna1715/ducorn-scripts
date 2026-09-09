#!/usr/bin/env python3
"""
What a patch is allowed to check, and how.

    from patchlib import code_only, assert_order, py_ok

Install as scripts/patchlib.py. Self-test:

    python3 scripts/patchlib.py

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

Three times in one session a patch verified itself against its own prose:

  patch_stop_siblings   searched for "title LIKE" and matched the docstring
                        describing the title-LIKE bug
  fix_epics_endpoint    searched for "SELECT" and matched the comment that
                        says "NOT a SELECT here"
  patch_phase_brief     searched for "--skill" and matched the comment that
                        says "this used to run skill_runner --skill 01"

Every one of them had applied a CORRECT patch and then told the operator to
restore the backup. A check that reads comments is checking the wrong text,
and the better the comment explains the fix, the more certainly it fails.

The first two were fixed in place, each time by writing the same three lines
again. That is the recurrence: the fix lived in a patch file that the next
patch could not see. It lives here now, so using it costs one import and
reinventing it costs more than that.

── WHAT EACH ONE IS FOR ─────────────────────────────────────────────────────

code_only     the source with comments and docstrings removed. Search THIS.
assert_order  "x happens before y" as a fact about the parse tree, not about
              where two strings sit in a file — a call moved into a comment,
              a branch, or dead code is not a call that runs.
py_ok         it parses.

None of them say anything about behaviour. A patch that wants to prove
behaviour runs the behaviour; these only stop a patch from lying about text.
"""
from __future__ import annotations

import ast
import io
import tokenize

__all__ = ["code_only", "assert_order", "calls_in", "ifs_in", "py_ok",
           "PatchCheckFailed"]


class PatchCheckFailed(AssertionError):
    """A verification that did not hold. The message names what and where."""


def code_only(src: str) -> str:
    """
    Source with comments and docstrings gone.

    Tokenised, not regexed: a '#' inside a string is not a comment, and a
    regex cannot tell. Falls back to the raw text if the source does not
    tokenise — a caller checking unparseable source has a bigger problem and
    should hear about that one.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src

    out, prev_type, prev_end = [], tokenize.INDENT, (1, 0)
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            continue
        # A STRING alone on a logical line is a docstring or a stray literal;
        # either way it is prose, not code that runs.
        if (tok.type == tokenize.STRING
                and prev_type in (tokenize.INDENT, tokenize.NEWLINE,
                                  tokenize.NL, tokenize.DEDENT,
                                  tokenize.ENCODING)):
            prev_type, prev_end = tok.type, tok.end
            continue
        if tok.start[0] == prev_end[0] and tok.start[1] > prev_end[1]:
            out.append(" " * (tok.start[1] - prev_end[1]))
        elif tok.start[0] > prev_end[0]:
            out.append("\n" * (tok.start[0] - prev_end[0]))
        out.append(tok.string)
        prev_type, prev_end = tok.type, tok.end
    return "".join(out)


def py_ok(src: str, label: str = "the file") -> ast.Module:
    """Parse, or raise with the line."""
    try:
        return ast.parse(src)
    except SyntaxError as e:
        raise PatchCheckFailed(
            f"{label} does not parse: line {e.lineno}: {e.msg}") from e


def _func(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise PatchCheckFailed(f"there is no function named {name!r}")


def assert_order(src: str, func: str, first: str, then: str) -> None:
    """
    Inside `func`, `first` must appear before `then` IN THE PARSE TREE.

    Both are matched against the dump of the function body, so a mention in a
    comment or a docstring cannot satisfy either one — which is the whole
    point. Order in the tree is statement order, so "write the brief before
    launching the process" is a question this can answer and a text search
    cannot: text finds both spellings equally when the write sits after the
    launch.
    """
    dump = ast.dump(_func(py_ok(src, func), func))
    i, j = dump.find(first), dump.find(then)
    if i < 0:
        raise PatchCheckFailed(f"{func}() does not contain {first!r} as code")
    if j < 0:
        raise PatchCheckFailed(f"{func}() does not contain {then!r} as code")
    if i > j:
        raise PatchCheckFailed(
            f"in {func}(), {first!r} happens AFTER {then!r} — the order is "
            f"the thing being fixed, so this is not a pass")


def calls_in(src: str, func: str | None, name: str) -> list:
    """
    Every call to `name` inside `func`, as source text. func=None means the
    whole module.

    For counting. A patch that adds a call verified it by counting that call
    across the WHOLE FILE and asserting a total — which required guessing how
    many already existed. The guess was wrong (the existing ones passed an
    extra argument, so an exact-string count never saw them), the patch was
    correct, and the operator was told to restore a good file.

    Count what you changed, where you changed it. Scoped to one function, a
    call site you did not write cannot move your number; taken from the parse
    tree, neither can a comment.
    """
    tree = py_ok(src, func or "the module")
    scope = _func(tree, func) if func else tree
    found = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        called = (f.id if isinstance(f, ast.Name)
                  else f.attr if isinstance(f, ast.Attribute) else "")
        if called == name:
            found.append(ast.get_source_segment(src, node) or called)
    return found


def ifs_in(src: str, func: str | None, contains: str) -> list:
    """
    Every `if` inside `func` whose TEST mentions `contains`, as
    [(line, has_else)]. func=None means the whole module.

    For branch structure — which statement an `else` hangs off. No text
    search can see that: the broken and the fixed spelling contain the same
    lines in the same order, and only the tree differs.

    Scoped, for the reason calls_in is scoped. A check that walked the whole
    module for `if skill_num == BUILD_SKILL` found two — the one being fixed
    and an unrelated one seven hundred lines earlier — and reported a correct
    patch as broken. That was the second file-wide count to do that in one
    session, the first being the reason calls_in exists.
    """
    tree = py_ok(src, func or "the module")
    scope = _func(tree, func) if func else tree
    out = []
    for node in ast.walk(scope):
        if isinstance(node, ast.If) and contains in ast.dump(node.test):
            out.append((node.lineno, bool(node.orelse)))
    return sorted(out)


if __name__ == "__main__":
    FIXTURE = '''
"""A module docstring mentioning --skill and SELECT and title LIKE."""
import subprocess


def start(slug):
    """Runs skill_runner.py — or it used to."""
    # This used to run skill_runner.py --skill 01. It does not any more.
    brief = write_brief(slug)          # SELECT is not run here
    return subprocess.Popen(["x", brief])
'''
    bad = []
    code = code_only(FIXTURE)
    for ghost in ("--skill", "skill_runner.py", "SELECT", "title LIKE"):
        if ghost in code:
            bad.append(f"{ghost!r} survived into code_only()")
    if "write_brief" not in code:
        bad.append("code_only() ate real code")
    if "subprocess.Popen" not in code:
        bad.append("code_only() ate the call being checked")

    try:
        assert_order(FIXTURE, "start", "write_brief", "Popen")
    except PatchCheckFailed as e:
        bad.append(f"a correct order was rejected: {e}")

    WRONG = FIXTURE.replace(
        '    brief = write_brief(slug)          # SELECT is not run here\n'
        '    return subprocess.Popen(["x", brief])',
        '    p = subprocess.Popen(["x"])\n'
        '    brief = write_brief(slug)\n'
        '    return p')
    try:
        assert_order(WRONG, "start", "write_brief", "Popen")
        bad.append("a REVERSED order was accepted")
    except PatchCheckFailed:
        pass

    try:
        py_ok("def (:", "fixture")
        bad.append("py_ok accepted a syntax error")
    except PatchCheckFailed:
        pass

    COUNTED = '''
def other(t):
    mark(t, "failed", "skill")        # an existing call, extra argument


def start(t):
    """mark(t, "failed") in prose does not count."""
    # nor does mark(t, "failed") in a comment
    mark(t, "failed")
'''
    if len(calls_in(COUNTED, "start", "mark")) != 1:
        bad.append("calls_in miscounted the function it was asked about")
    if len(calls_in(COUNTED, None, "mark")) != 2:
        bad.append("calls_in missed a call at module scope")
    if 'mark(t, "failed", "skill")' not in calls_in(COUNTED, "other", "mark")[0]:
        bad.append("calls_in did not return the call source")

    BRANCHED = '''
def elsewhere(n):
    if n == LIMIT:
        pass


def target(n, body):
    if len(body) >= 200:
        ok = True
    else:
        ok = False
    if n == LIMIT and ok:
        ok = check()
    return ok
'''
    scoped = ifs_in(BRANCHED, "target", "LIMIT")
    if len(scoped) != 1:
        bad.append(f"ifs_in saw {len(scoped)} LIMIT tests in target, not 1 "
                   f"— it is counting the whole module again")
    if scoped and scoped[0][1]:
        bad.append("ifs_in reported an else the target does not have")
    if len(ifs_in(BRANCHED, None, "LIMIT")) != 2:
        bad.append("ifs_in missed a module-scope branch")
    length = ifs_in(BRANCHED, "target", "200")
    if not (len(length) == 1 and length[0][1]):
        bad.append("ifs_in did not see the length test's else")

    print("patchlib OK" if not bad else "patchlib BAD\n  " + "\n  ".join(bad))
    raise SystemExit(0 if not bad else 1)
