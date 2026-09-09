#!/usr/bin/env python3
"""
Where a topic builds. The one answer, for every process that needs it.

    import product_dir
    product_dir.for_topic("ducorn-admin-rebuild-p1-config")
        -> Path(".../products/ducorn-admin-rebuild")     a phase → its epic
    product_dir.for_topic("ducorn-spend-status")
        -> Path(".../products/ducorn-spend-status")      everything else

    product_dir.rel_for_topic(topic)  ->  "products/<name>/"   for git paths

Install as scripts/product_dir.py. Self-test:

    python3 scripts/product_dir.py --test

── WHY ──────────────────────────────────────────────────────────────────────

A phase builds into its EPIC's directory. product_epics.build_dir has said so
since epics existed, and product_jail asks it. Nothing else did — eleven other
places kept deriving

    PRODUCTS_DIR / "products" / topic

which is right for a standalone product and wrong for every phase. The
consequences, found by review before the first phase's build reached them:

    skill_runner.build_produced_code   would report "…-p1-config/ was never
                                       created" and fail skill 04, after
                                       skills 01–03 had been paid for
    skill_runner.has_approved_design   would answer False, so REX would never
                                       be told to match the design you had
                                       just chosen at gate 2
    skill_runner run_with_cursor       would mkdir the phase-slug directory,
                                       creating an empty product beside the
                                       real one
    the UI check and code review       would look in an empty directory
    langgraph_flow._git_publish        would commit a path that is not there
    DuCornDeployTool                   "❌ No such product"
    view_design                        did exactly this, and every design
                                       link at gate 2 returned Not found

That is one fact with twelve copies, eleven of them stale. This module is
where it lives so the twelfth copy is not written.

── WHY NOT JUST CALL product_epics.build_dir ────────────────────────────────

Because of what must happen when it cannot answer. A machine without epics,
or with migration 009 unapplied, has no phases and every topic is standalone
— that is provable, so it is safe to answer. Any OTHER failure proves
nothing, and answering anyway would put a build in the wrong directory
silently. That three-way distinction was written once in product_jail and
would have been re-written, slightly differently, at each of the other
eleven sites.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["for_topic", "rel_for_topic", "PRODUCTS", "UnknownBuildDir"]

PRODUCTS = Path("/Users/ducorn/DC/ducorn-products/products")


class UnknownBuildDir(RuntimeError):
    """Where this topic builds could not be determined. Do not guess."""


def for_topic(topic: str) -> Path:
    """
    The directory this topic's files belong in, resolved.

    Raises rather than guessing when the epic tables exist but cannot be
    read. A wrong directory is not a degraded answer — it is a build written
    somewhere nobody looks, which passes its gates and is found empty by the
    next phase.
    """
    if not topic:
        raise UnknownBuildDir("no topic given")
    try:
        import product_epics
    except ImportError:
        # Epics are not installed here. Every topic is a standalone product,
        # which is what was true before epics existed.
        return (PRODUCTS / topic).resolve()
    try:
        return Path(product_epics.build_dir(topic)).resolve()
    except product_epics.EpicsNotInstalled:
        # Migration 009 has not run, so no epic exists and no topic is a
        # phase. Provable, so it is safe to answer.
        return (PRODUCTS / topic).resolve()
    except Exception as e:
        raise UnknownBuildDir(
            f"could not determine where {topic!r} builds: "
            f"{type(e).__name__}: {e}") from e


def rel_for_topic(topic: str) -> str:
    """
    The same directory as a repo-relative path with a trailing slash, for git.

    _git_publish takes "products/<name>/". Building that from the topic gave
    a path that does not exist for a phase, so the commit covered nothing and
    the build reported a push it had not made.
    """
    return f"products/{for_topic(topic).name}/"


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        # NO DATABASE. The first version of this called for_topic on a real
        # topic, which reaches product_epics, which opens Postgres — so the
        # test could only run where psycopg2 was installed, which is not the
        # interpreter `python3 scripts/product_dir.py` picks on this Mac. A
        # test that cannot run where it is needed is not a test.
        #
        # What is tested is this module's own logic: the three-way
        # distinction between "no epics", "epics not migrated" and "epics
        # broken". product_epics is stubbed, so each branch is reachable.
        import types

        bad = []
        real = sys.modules.pop("product_epics", None)

        def stub(build=None, raises=None, not_installed=False):
            m = types.ModuleType("product_epics")

            class EpicsNotInstalled(RuntimeError):
                pass
            m.EpicsNotInstalled = EpicsNotInstalled

            def build_dir(slug):
                if not_installed:
                    raise EpicsNotInstalled("migration 009 has not run")
                if raises:
                    raise raises
                return build(slug)
            m.build_dir = build_dir
            sys.modules["product_epics"] = m

        # A phase resolves to its epic's directory.
        stub(build=lambda s: PRODUCTS / "the-epic")
        if for_topic("the-epic-p1-thing") != (PRODUCTS / "the-epic").resolve():
            bad.append("a phase did not resolve to its epic's directory")
        if rel_for_topic("the-epic-p1-thing") != "products/the-epic/":
            bad.append("rel_for_topic did not use the resolved directory")

        # A standalone product resolves to itself.
        stub(build=lambda s: PRODUCTS / s)
        if for_topic("plain-product") != (PRODUCTS / "plain-product").resolve():
            bad.append("a standalone topic did not resolve to itself")

        # Migration not applied: provable, so answer.
        stub(not_installed=True)
        if for_topic("plain-product") != (PRODUCTS / "plain-product").resolve():
            bad.append("an unmigrated machine did not fall back")

        # Anything else proves nothing: refuse, do not guess.
        stub(raises=RuntimeError("the database is on fire"))
        try:
            for_topic("plain-product")
            bad.append("a broken lookup returned a directory anyway")
        except UnknownBuildDir:
            pass

        # No epics module at all.
        sys.modules.pop("product_epics", None)
        sys.modules["product_epics"] = None      # import raises ImportError
        try:
            if for_topic("plain-product") != (PRODUCTS / "plain-product").resolve():
                bad.append("a machine without epics did not fall back")
        except Exception as e:
            bad.append(f"a machine without epics raised {type(e).__name__}")

        sys.modules.pop("product_epics", None)
        if real is not None:
            sys.modules["product_epics"] = real

        try:
            for_topic("")
            bad.append("an empty topic was accepted")
        except UnknownBuildDir:
            pass

        print("product_dir OK" if not bad else "product_dir BAD\n  "
              + "\n  ".join(bad))
        raise SystemExit(0 if not bad else 1)

    # Resolving a REAL topic reaches product_epics, which needs psycopg2 —
    # and `python3 scripts/product_dir.py <topic>` picks python3.14 on this
    # Mac, which does not have it. bootstrap_python re-execs under one that
    # does, exactly as product_pathways does for the same reason.
    #
    # DELIBERATELY here and nowhere else. ensure_modules RE-EXECS the
    # process; at module level, any importer without psycopg2 would silently
    # restart itself mid-skill. Resolving a directory must never be able to
    # relaunch the pipeline. --test above needs none of this, because it
    # stubs product_epics and touches no database.
    try:
        from bootstrap_python import ensure_modules
        ensure_modules("psycopg2")
    except ImportError:
        pass

    for t in sys.argv[1:] or ["ducorn-admin-rebuild-p1-config"]:
        try:
            print(f"{t}\n  -> {for_topic(t)}\n  -> {rel_for_topic(t)}")
        except UnknownBuildDir as e:
            print(f"{t}\n  !! {e}")
