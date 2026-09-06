#!/usr/bin/env python3
"""
What kind of product is this, and what does that change?

── WHY THIS FILE EXISTS ─────────────────────────────────────────────────────

Until now the pipeline answered that question in four places, four ways:

    pipeline_runs.has_ui      the founder's checkbox in the wizard
    state["product_type"]     regex over PRD prose — by TWO different
                              algorithms, one in _infer_product_type and a
                              different one in run_pipeline
    _has_ui(topic)            does APPROVED_DESIGN.html exist on disk
    ui_test_coverage(topic)   are there any .html files in the directory

For the technology-stack document the first three said "no interface". The
fourth said "interface", because REX wrote .html renderings of the documents
exactly as asked. The fourth is the only one that can fail a run, and it was
the only one nobody gated — so a finished document was failed for shipping no
Playwright tests, three times, at roughly $11.

This module is the one definition. Everything that used to decide for itself
asks here.

── THE RULE ─────────────────────────────────────────────────────────────────

A product type is a DECISION, recorded in pipeline_runs.product_type when the
run is created. It is not re-derived from prose on every resume — that is what
let two algorithms disagree about the same product between one phase and the
next.

Inference still exists, for one situation only: a manual CLI run on a topic the
dashboard has never seen. It says so out loud when it happens, and there is
exactly one algorithm.

── ADDING A TYPE ────────────────────────────────────────────────────────────

Add it to PATHWAYS. Nothing else. If you find yourself writing

    if product_type == "document":

anywhere outside this file, the thing you are branching on belongs here as a
field instead — that is the defect this module exists to end, and
prove_pathways.py fails the build when it reappears.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Optional

if "/Users/ducorn/DC/scripts" not in sys.path:
    sys.path.insert(0, "/Users/ducorn/DC/scripts")


@dataclass(frozen=True)
class Pathway:
    """Everything that differs between one kind of product and another."""

    name: str

    # ── which G-Stack skills run, in order ───────────────────────────────
    skills: tuple                  # e.g. ("01", "04", "07")
    design_skills: tuple = ()      # added when the founder asked for a UI

    # ── what the reviewers may demand ────────────────────────────────────
    runs_tests: bool = True        # is a pytest suite meaningful here?
    checks_ui: bool = True         # may ui_test_coverage fail this product?
    reviews_code: bool = True      # is "no .env.example" a real defect?

    # ── what the product IS ──────────────────────────────────────────────
    deliverable_ext: frozenset = frozenset({".py", ".js", ".html"})
    ships_interface: bool = False  # a page a person looks at

    # ── what happens after the build ─────────────────────────────────────
    deploys: bool = True           # a long-running service, or a file?
    publish_to: str = "products"   # "docs" or "products"

    # ── how much iteration is worth paying for ───────────────────────────
    max_review_iterations: int = 3

    # ── how to say it to a model ─────────────────────────────────────────
    prompt_noun: str = "software product"
    prompt_rules: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# THE PATHWAYS
# ─────────────────────────────────────────────────────────────────────────────

_DOC_RULES = """
======================================================================
THIS IS A DOCUMENT. IT SHIPS NO CODE.
======================================================================
There is no interface, no service, no test suite and no deployment. Do
NOT require Playwright, pytest, a test suite, requirements.txt,
.env.example, endpoints, auth, or a start command. None of them apply
and the pipeline does not ask for them. "No tests" is not a defect in
something that ships no code.

Judge what this actually is: accurate, complete against the brief, well
organised, and honest about what it does not know. A document that
invents a fact is the only real failure mode here.
======================================================================
"""

_API_RULES = """
======================================================================
THIS PRODUCT HAS NO USER INTERFACE
======================================================================
It is a service with endpoints, not a page. Do NOT require browser
tests, Playwright, focus states, hit targets, or any interface
convention — there is nothing to render. Test the endpoints.
======================================================================
"""

_CLI_RULES = """
======================================================================
THIS IS A COMMAND-LINE TOOL
======================================================================
No interface and no long-running service. Do NOT require browser tests
or a deployment. It is correct when running it does the right thing and
its exit codes and messages are honest.
======================================================================
"""


PATHWAYS = {
    # ── prose. the reason this module exists. ────────────────────────────
    "document": Pathway(
        name="document",
        skills=("01", "04", "07"),
        runs_tests=False,
        checks_ui=False,
        reviews_code=False,
        deliverable_ext=frozenset({".md", ".html", ".pdf", ".txt"}),
        ships_interface=False,
        deploys=False,
        publish_to="docs",
        max_review_iterations=1,
        prompt_noun="document",
        prompt_rules=_DOC_RULES,
    ),

    # ── a page a person opens ────────────────────────────────────────────
    "webpage": Pathway(
        name="webpage",
        skills=("01", "04", "05", "06"),
        design_skills=("02", "03"),
        runs_tests=True,
        checks_ui=True,
        reviews_code=True,
        deliverable_ext=frozenset({".html", ".css", ".js", ".jsx", ".ts",
                                   ".tsx", ".vue", ".svelte", ".py"}),
        ships_interface=True,
        deploys=True,
        publish_to="products",
        prompt_noun="web product",
    ),

    # ── endpoints, no page ───────────────────────────────────────────────
    "api": Pathway(
        name="api",
        skills=("01", "04", "05", "06"),
        design_skills=(),          # nothing to design; there is no page
        runs_tests=True,
        checks_ui=False,
        reviews_code=True,
        deliverable_ext=frozenset({".py", ".js", ".ts", ".go", ".rs", ".sql"}),
        ships_interface=False,
        deploys=True,
        publish_to="products",
        prompt_noun="API service",
        prompt_rules=_API_RULES,
    ),

    # ── a command you run ────────────────────────────────────────────────
    "cli": Pathway(
        name="cli",
        skills=("01", "04", "05", "06"),
        runs_tests=True,
        checks_ui=False,
        reviews_code=True,
        deliverable_ext=frozenset({".py", ".js", ".ts", ".go", ".rs", ".sh"}),
        ships_interface=False,
        deploys=False,             # a tool is not a service
        publish_to="products",
        prompt_noun="command-line tool",
        prompt_rules=_CLI_RULES,
    ),

    # ── the honest default ───────────────────────────────────────────────
    "software": Pathway(
        name="software",
        skills=("01", "04", "05", "06"),
        design_skills=("02", "03"),
        runs_tests=True,
        checks_ui=True,
        reviews_code=True,
        deliverable_ext=frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".go",
                                   ".rs", ".rb", ".java", ".html", ".css",
                                   ".sh", ".sql", ".vue", ".svelte"}),
        ships_interface=False,
        deploys=True,
        publish_to="products",
        prompt_noun="software product",
    ),
}

# Names people and models actually use, mapped to the five real ones. A model
# writing "**Type:** dashboard" in a PRD must not create a sixth pathway by
# accident.
ALIASES = {
    "dashboard": "webpage", "web": "webpage", "webapp": "webpage",
    "web app": "webpage", "website": "webpage", "site": "webpage",
    "page": "webpage", "ui": "webpage", "frontend": "webpage",
    "doc": "document", "docs": "document", "documentation": "document",
    "report": "document", "guide": "document", "spec": "document",
    "writeup": "document", "write-up": "document", "paper": "document",
    "service": "api", "backend": "api", "rest": "api", "endpoint": "api",
    "command line": "cli", "command-line": "cli", "tool": "cli",
    "script": "cli", "utility": "cli",
    "app": "software", "application": "software", "product": "software",
}

DEFAULT = "software"
TYPES = tuple(PATHWAYS)


class UnknownPathway(KeyError):
    """A type nobody defined. Better than silently becoming 'software'."""


def normalise(value: Optional[str]) -> Optional[str]:
    """'Dashboard ' → 'webpage'. Unknown or empty → None."""
    if not value:
        return None
    v = str(value).strip().lower().replace("_", " ")
    if v in PATHWAYS:
        return v
    return ALIASES.get(v)


def get(product_type: Optional[str]) -> Pathway:
    """The pathway for a type. Raises rather than guessing."""
    n = normalise(product_type)
    if n is None:
        raise UnknownPathway(
            f"{product_type!r} is not a product type. Known: "
            f"{', '.join(TYPES)} (plus aliases). Add it to PATHWAYS in "
            f"product_pathways.py rather than branching on it at the call site."
        )
    return PATHWAYS[n]


# ─────────────────────────────────────────────────────────────────────────────
# ONE inference algorithm — used only when nothing was recorded
# ─────────────────────────────────────────────────────────────────────────────

# Was two functions: _infer_product_type's regex plus run_pipeline's literal
# "Type: x" match, iterating a different list in a different order. They could
# and did disagree about the same PRD between one phase and the next.
_MARKER = re.compile(
    r"\*{0,2}type\*{0,2}\W{0,6}([a-z][a-z \-]{1,20})", re.I)


# Every word that names a type, including the type names themselves. Built
# once, from the two dicts above, so adding a pathway or an alias extends the
# vocabulary automatically — a second hand-maintained word list here would be
# the very defect this module exists to remove.
_VOCAB = {w: w for w in PATHWAYS}
_VOCAB.update(ALIASES)
_WORD_RE = {
    w: re.compile(r"(?<![\w-])" + re.escape(w) + r"s?(?![\w-])", re.I)
    for w in _VOCAB
}


def infer_from_text(text: str) -> Optional[str]:
    """
    Read the type out of a PRD. Returns None when it genuinely cannot tell —
    the caller decides what to do about that, out loud.
    """
    if not text:
        return None

    # 1. An explicit marker wins — but the captured phrase is rarely a bare
    #    type name. Real PRDs on this machine say:
    #
    #        **Type:** CLI tool                 → the head word is the type
    #        **Type:** SaaS Web Dashboard …     → the TAIL word is the type
    #
    #    so try every contiguous sub-phrase, longest first. Matching the
    #    marker and then resolving to nothing is worse than not matching at
    #    all: it skips the word-count fallback that would have got it right.
    for m in _MARKER.finditer(text[:8000]):
        words = m.group(1).split()
        for size in range(len(words), 0, -1):
            for start in range(0, len(words) - size + 1):
                n = normalise(" ".join(words[start:start + size]))
                if n:
                    return n

    # 2. No marker: count type words as WORDS, not substrings. Substring
    #    counting made 'api' match 'rapid' and 'capital', which is why short
    #    words had to be excluded, which in turn made 'api' invisible — the
    #    exclusion papered over the matching bug.
    scores = {}
    for w, target in _VOCAB.items():
        c = len(_WORD_RE[w].findall(text))
        if c:
            scores[target] = scores.get(target, 0) + c
    if not scores:
        return None

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if ranked[0][1] < 2:
        return None                      # one passing mention is not a type
    # A clear winner, or nothing. "Document the API stack" mentions both; the
    # old code took whichever it checked first and called it an API.
    if len(ranked) > 1 and ranked[0][1] < ranked[1][1] * 2:
        return None
    return ranked[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Resolving a live run
# ─────────────────────────────────────────────────────────────────────────────

def recorded_type(topic: str) -> Optional[str]:
    """
    What the dashboard recorded for this run, or None if it has no row.

    A missing row is information — a manual CLI run on a fresh topic. A failed
    READ is the absence of information, and this raises rather than answering,
    for the same reason _pin_local_for_test_runs does: guessing here silently
    changes which skills run and how much the run costs.
    """
    from ducorn_db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT product_type FROM pipeline_runs WHERE slug=%s",
                    (topic,))
        row = cur.fetchone()
    if not row:
        return None
    return normalise(row[0])


def for_topic(topic: str, override: Optional[str] = None,
              quiet: bool = False) -> Pathway:
    """
    The pathway for a live run, in priority order:

        1. an explicit --type on the command line
        2. pipeline_runs.product_type      ← the recorded decision
        3. the PRD, inferred, said out loud
        4. software, said out loud

    Note what is NOT here: no silent fallback. Every step below the recorded
    decision announces itself, so a run that quietly took the wrong lane is
    visible in the log rather than in the invoice.
    """
    n = normalise(override)
    if n:
        if not quiet:
            print(f"📐 pathway: {n} (--type)", flush=True)
        return PATHWAYS[n]

    try:
        n = recorded_type(topic)
    except Exception as e:
        raise RuntimeError(
            f"Could not read the product type for '{topic}': {e}\n"
            f"Refusing to guess — this decides which skills run and what the "
            f"run costs.\n"
            f"  python3 scripts/doctor.py --quiet\n"
            f"  or force it:  --type document"
        ) from e

    if n:
        if not quiet:
            print(f"📐 pathway: {n}", flush=True)
        return PATHWAYS[n]

    prd = _read_prd(topic)
    n = infer_from_text(prd) if prd else None
    if n:
        if not quiet:
            print(f"📐 pathway: {n} — inferred from the PRD; no product_type "
                  f"recorded for '{topic}'. A dashboard run records one.",
                  flush=True)
        return PATHWAYS[n]

    if not quiet:
        print(f"📐 pathway: {DEFAULT} (default) — nothing recorded for "
              f"'{topic}' and the PRD does not say. Pass --type to be sure.",
              flush=True)
    return PATHWAYS[DEFAULT]


def _read_prd(topic: str) -> str:
    from pathlib import Path
    p = Path("/Users/ducorn/DC/ducorn-products/docs") / f"{topic}-PRD.md"
    try:
        return p.read_text(errors="replace") if p.is_file() else ""
    except OSError:
        return ""


def skills_for(pw: Pathway, has_ui: bool = False,
               complexity: str = "simple") -> list:
    """
    The skill sequence for a run.

    Design skills are added when the founder asked for an interface AND this
    kind of product can have one — a document with has_ui set by accident does
    not get a design consultation, and an API never does.

    Complexity still matters, but it no longer DECIDES: it used to be the only
    input, which is why a document got code review and QA.
    """
    core = list(pw.skills)
    if has_ui and pw.design_skills and complexity in ("medium", "complex"):
        i = core.index("04") if "04" in core else len(core)
        core[i:i] = list(pw.design_skills)
    return core


if __name__ == "__main__":
    # ── run as a script: find an interpreter that can reach the database ─────
    #
    # This Mac has four pythons and psycopg2 is in some of them. bootstrap_
    # python exists for exactly this and says so in its own docstring: "Two
    # copies drift". migrate.py uses it; this did not, so `python3
    # scripts/product_pathways.py <topic>` died on ModuleNotFoundError under
    # python3.14.
    #
    # DELIBERATELY inside __main__ and nowhere else. ensure_modules RE-EXECS
    # the process. skill_runner.py and langgraph_flow.py import this module
    # and already run under ducorn/.venv, which has psycopg2 — but a
    # module-level call would mean that any importer lacking it silently
    # restarts itself under a different interpreter, mid-skill. A pathway
    # lookup must never be able to relaunch the pipeline.
    from bootstrap_python import ensure_modules
    ensure_modules("psycopg2")

    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("──")[0].strip())
    ap.add_argument("topic", nargs="?")
    ap.add_argument("--type")
    a = ap.parse_args()

    if not a.topic:
        print(f"{'type':10} {'skills':28} tests  ui   review deploy  publish")
        print("─" * 78)
        for k, pw in PATHWAYS.items():
            sk = ",".join(skills_for(pw, has_ui=True, complexity="medium"))
            print(f"{k:10} {sk:28} "
                  f"{'yes' if pw.runs_tests else ' no ':5}  "
                  f"{'yes' if pw.checks_ui else ' no':4} "
                  f"{'yes' if pw.reviews_code else ' no':6} "
                  f"{'yes' if pw.deploys else ' no':6}  {pw.publish_to}")
        print(f"\n{len(ALIASES)} aliases map onto these {len(PATHWAYS)}.")
        raise SystemExit(0)

    pw = for_topic(a.topic, a.type)
    print(f"\n{a.topic} → {pw.name}")
    print(f"  skills   {', '.join(skills_for(pw, has_ui=True, complexity='medium'))}")
    print(f"  tests    {pw.runs_tests}")
    print(f"  ui gate  {pw.checks_ui}")
    print(f"  deploys  {pw.deploys}")
    print(f"  publish  {pw.publish_to}/")
