#!/usr/bin/env python3
"""
A build that wrote nothing fails, the reader stops hiding the product, and a
superseded review leaves the jail.

    python3 scripts/patch_build_gate.py

── ONE: the build gate is dead code ─────────────────────────────────────────

    $ grep -c "build_produced_code(" skill_runner.py
    1        ← the definition. Nothing calls it.

So skill 04's verdict comes from this, and only this:

    if len(body) >= 200:
        status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"

Two hundred characters of prose. REX looked at four documents written on
2 September, wrote 7,788 characters explaining that they seemed fine, and
passed — having modified nothing. That cost about $2 and produced a PASS.

build_produced_code exists, is correct, and was never wired in. It now runs
for the build skill and requires a deliverable modified DURING THIS RUN, not
merely present. "The files exist" is satisfied by files someone else wrote
four days ago.

── TWO: the reader was hiding the product from its own author ───────────────

    return p.read_text(...)[:20000]

ducorn-tech-stack-internal.md is 33,393 characters. REX saw 20,000 and said so
in its own report:

    "The internal MD file is being truncated by the reader — I need to check
     if the file is genuinely complete on disk."

It could not tell that section 7.2 was empty because it could not reach
section 7.2. The fifth silent truncation found in two days, and the one that
directly caused the document not to be revised.

Raised, and — more importantly — it now SAYS when it truncates. A reader that
lies about completeness is worse than a small one.

── THREE: superseded reviews are still inside the jail ──────────────────────

.superseded/ lives in products/<topic>/, which the jail permits. REX read it:

    "From the QA report iteration 1: ✅ All 11 pipeline nodes..."

Moved to ducorn-products/.superseded/<topic>/ — still on disk, still the
record of why an attempt failed, and outside what any agent can reach.
"""
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
SKILL = DC / "ducorn" / "skill_runner.py"
JAILED = DC / "ducorn" / "tools" / "jailed_tools.py"

# This patch EXERCISES build_produced_code, which resolves the pathway, which
# reads the database. python3 on this Mac is 3.14 and has no psycopg2, so the
# verification died and reverted — correctly, but for a reason that has
# nothing to do with the patch. bootstrap_python exists for exactly this and
# migrate.py already uses it; third time this has bitten.
sys.path.insert(0, str(DC / "scripts"))
try:
    from bootstrap_python import ensure_modules
    ensure_modules("psycopg2")
except ImportError:
    pass

sk = SKILL.read_text(encoding="utf-8")
jt = JAILED.read_text(encoding="utf-8")

if "_RUN_STARTED" in sk and "READ_LIMIT" in jt:
    print("Already patched — a no-op build fails and the reader is honest.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ 1. the build gate runs, and asks about THIS run ═════════════════════════
sk = swap("run start recorded", sk,
          'PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products")',
          '''# When this skill process started. Each skill runs in its own subprocess, so
# module import time is the run's start — which is what "did this run write
# anything" has to be measured against.
_RUN_STARTED = datetime.now().timestamp()

PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products")''')

sk = swap("gate asks about this run", sk,
          '''def build_produced_code(topic: str):
    d = PRODUCTS_DIR / "products" / topic
    if not d.exists():
        return "fail", f"VERDICT: FAIL — {d.name}/ was never created"''',
          '''def build_produced_code(topic: str, since: float = None):
    """
    Did the build actually produce the product?

    `since` is the point this run started. Without it the check is "do
    deliverables exist", which four-day-old files satisfy — REX confirmed
    documents written on 2 September, wrote a report about them, and passed.
    """
    d = PRODUCTS_DIR / "products" / topic
    if not d.exists():
        return "fail", f"VERDICT: FAIL — {d.name}/ was never created"''')

sk = swap("nothing written is a failure", sk,
          '''    return "pass", f"VERDICT: PASS — {len(src)} source file(s) written"''',
          '''    if since is not None:
        fresh = []
        for p in src:
            try:
                if p.stat().st_mtime >= since - 5:
                    fresh.append(p.name)
            except OSError:
                continue
        if not fresh:
            newest = ""
            try:
                n = max(src, key=lambda p: p.stat().st_mtime)
                newest = (f" Newest is {n.name}, last changed "
                          f"{datetime.fromtimestamp(n.stat().st_mtime):%Y-%m-%d %H:%M}.")
            except (OSError, ValueError):
                pass
            return "fail", (
                f"VERDICT: FAIL — this build changed nothing. "
                f"{len(src)} deliverable(s) are present but every one predates "
                f"this run.{newest} If the product is already correct, say so "
                f"and revise what the reviewer asked for; do not re-confirm "
                f"files you did not write.")
        return "pass", (f"VERDICT: PASS — {len(fresh)} of {len(src)} "
                        f"deliverable(s) written this run: "
                        + ", ".join(sorted(fresh)[:6]))
    return "pass", f"VERDICT: PASS — {len(src)} source file(s) written"''')

sk = swap("wire the gate into the verdict", sk,
          '''            if len(body) >= 200:
                status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"''',
          '''            if len(body) >= 200:
                status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"

            # A build is judged by what it WROTE, not by how much it said
            # about what it read. build_produced_code has existed all along
            # and nothing ever called it.
            if skill_num == BUILD_SKILL and status == "pass":
                _bstat, _bwhy = build_produced_code(topic, since=_RUN_STARTED)
                if _bstat != "pass":
                    status, verdict = "fail", _bwhy
                else:
                    print(f"🧱 {_bwhy}", flush=True)''')

# ═══ 2. superseded reviews leave the jail ════════════════════════════════════
sk = swap("superseded outside the jail", sk,
          '''    d = PRODUCTS_DIR / "products" / topic
    if not d.is_dir():
        return []
    moved = []
    dest = d / ".superseded"''',
          '''    d = PRODUCTS_DIR / "products" / topic
    if not d.is_dir():
        return []
    moved = []
    # OUTSIDE products/<topic>/, because the jail permits everything in there
    # and REX read the superseded reports anyway — quoting "QA report
    # iteration 1" back at itself. Still on disk, still the record of why an
    # attempt failed, simply not reachable by an agent.
    dest = PRODUCTS_DIR / ".superseded" / topic''')

sk = swap("mkdir the new home", sk,
          "            dest.mkdir(exist_ok=True)",
          "            dest.mkdir(parents=True, exist_ok=True)")

# ═══ 3. the reader stops hiding the product ══════════════════════════════════
jt = swap("named, larger, honest read limit", jt,
          '            return p.read_text(encoding="utf-8", errors="replace")[:20000]',
          '''            _text = p.read_text(encoding="utf-8", errors="replace")
            if len(_text) <= READ_LIMIT:
                return _text
            # SAY SO. REX read 20,000 of a 33,393-character document, could
            # not reach section 7.2, and therefore could not tell that
            # section 7.2 was empty — then reported the file "appears
            # complete". A truncating reader that stays quiet about it makes
            # the agent confidently wrong.
            return (_text[:READ_LIMIT] +
                    f"\\n\\n[TRUNCATED BY THE READER — you have been shown "
                    f"{READ_LIMIT:,} of {len(_text):,} characters of "
                    f"'{file_path}'. The rest exists on disk. Do NOT conclude "
                    f"anything about the parts you have not seen.]")''')

jt = swap("the limit has a name", jt,
          "class JailedFileReadTool",
          '''# A product's own files are the work. 20,000 hid a third of a 33 KB document
# from the agent writing it.
READ_LIMIT = 80000


class JailedFileReadTool''')

# ═══ write both, or neither ══════════════════════════════════════════════════
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(SKILL, sk), (JAILED, jt)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-buildgate-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — both files reverted")


for path, text in targets:
    path.write_text(text, encoding="utf-8")
for path, _ in targets:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                       capture_output=True, text=True)
    u = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
    if u:
        die(f"{path.name}: " + "; ".join(u))
print("syntax and undefined-name checks: clean on both")

# ── exercise the gate against the REAL product directory ─────────────────────
src = SKILL.read_text(encoding="utf-8")
tree = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "build_produced_code"), None)
if seg is None:
    die("build_produced_code did not survive")

import product_pathways as _pw
ns = {"PRODUCTS_DIR": DC / "ducorn-products", "Path": Path,
      "datetime": datetime, "pathways": _pw, "re": __import__("re")}
exec(seg, ns)

slug = "ducorn-technology-stack-documentation"
now = datetime.now().timestamp()
old = now - 86400 * 10            # ten days ago: everything counts as fresh
print(f"\nthe gate, against the real {slug}/:\n")
try:
    for label, since in [("as if this run just started", now),
                         ("as if the run started 10 days ago", old),
                         ("with no `since` (the old behaviour)", None)]:
        st, why = ns["build_produced_code"](slug, since=since)
        print(f"  {st:5} {label:38} {why[:78]}")

    st_now, _ = ns["build_produced_code"](slug, since=now)
    st_old, _ = ns["build_produced_code"](slug, since=old)
except Exception as e:
    # Anything raised here must revert. Without this the files stayed
    # modified when the exercise blew up — a patch that half-applies is
    # worse than one that refuses.
    die(f"the gate could not be exercised: {type(e).__name__}: {e}")
if st_now != "fail":
    die("a build that changed nothing still passes")
if st_old != "pass":
    die("a build that DID write is being failed")
print("\n  ok   a build that changed nothing now fails")
print("  ok   a build that wrote something still passes")

jt_src = JAILED.read_text(encoding="utf-8")
print()
for s2, must, why in [
    (src, "_RUN_STARTED = datetime.now().timestamp()", "the run's start is recorded"),
    (src, "build_produced_code(topic, since=_RUN_STARTED)", "the gate is actually called"),
    (src, 'dest = PRODUCTS_DIR / ".superseded" / topic',
     "superseded reviews live outside the jail"),
    (jt_src, "READ_LIMIT = 80000", "the reader can see a 33 KB document"),
    (jt_src, "TRUNCATED BY THE READER", "and says so when it cannot"),
]:
    if must not in s2:
        die(f"missing: {why}")
    print(f"  ok   {why}")

if "[:20000]" in jt_src:
    die("the bare 20000 read truncation is still there")
print("  ok   no bare truncation left in the reader")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print("""
Now look at the prompt — still free — and check skill 07's rejection is in it:

  ducorn/.venv/bin/python ducorn/skill_runner.py --skill 04 \\
      --topic ducorn-technology-stack-documentation --dry-run

Expect a line reading "📨 skill 04: carrying the previous attempt's rejection".
That is skill 07 telling REX the timestamp is wrong, the skill count is wrong,
and skill 07 is missing from both documents.
""")
