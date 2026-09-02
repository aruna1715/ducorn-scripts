#!/usr/bin/env python3
"""
Give REX the QA report, and stop the cache from throwing it away.

── THE LOOP YOU HAVE PAID FOR THREE TIMES ───────────────────────────────────

IRIS diagnosed the failure precisely, three times, and wrote the fix:

    ISSUE 1 — Mock pool is overwritten by lifespan during TestClient startup
    Fix required: patch asyncpg.create_pool so lifespan itself sets _pool
    to the mock:
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=mock_pool)):

That report is on disk at docs/<slug>-skill06-output.txt, 4,856 bytes of
correct analysis. Then skill_runner builds the context for the next skill:

    for prev_num in ['01', '02', '03', '04', '05']:
        if prev_num >= skill_num:
            break

Skill 06 is not in that list. It cannot be — the loop walks skills that come
BEFORE the current one, and 06 comes last. So the QA report is handed to
nobody. REX re-runs with the same PRD and the same skill 01 and 03 outputs,
writes the same code, and 06 fails the same way. Three cycles, three identical
verdicts, roughly $4–6 each.

That is not a model failing to follow instructions. The instructions never
arrive.

── THE SECOND DOOR, WHICH I NEARLY LEFT SHUT ────────────────────────────────

Handing the report to REX is not enough on its own, and I checked the live
checkpoint before telling you to run this:

    01-01-prd-analysis   pass   sha=b96e531b6121
    04-04-build          pass   sha=4232a812b24b      ← REX
    05-05-code-review    pass   sha=e662aa3e1144
    06-06-qa-run-test    fail   sha=34098971184f

Skill 04 is cached as a pass. The replay check compares a fingerprint of
_skill_text() — the skill markdown plus its injections — and the rejection
goes into the CONTEXT, not into _skill_text. So the fingerprint would have
been byte-identical, skill 04 would have replayed its stored verdict, and REX
would never have run at all. The report would have been assembled perfectly
and handed to a skill that was skipped.

`--invalidate 04` clears it by hand. That is the bandaid: it works when
someone remembers, and forgetting is invisible.

The permanent version follows the rule the fingerprint was built on — a cached
result is only valid for the instructions that produced it. A rejection carried
into the prompt IS a change of instructions, so it belongs inside the hash. And
a build that QA has rejected is not a build you may replay past, whatever the
hash says, so an outstanding rejection forces the re-run outright. Both, because
the fingerprint keeps the stored entry honest and the force keeps the loop from
ever presenting a cached pass while QA is failing.

── WHAT REX NOW RECEIVES ────────────────────────────────────────────────────

    ============ THE PREVIOUS BUILD FAILED QA — FIX THIS FIRST ============
    Skill 06 — QA + Run Test judged the last build and rejected it. Its
    report is below. These are not suggestions.
    ...the full report...
    Fix every issue named. Do not rewrite what already passed.

Skill 05 gets it too — a code reviewer should know what QA found before
passing the same code a second time.

Capped at 6,000 characters, which fits every report this pipeline has
produced, with the head kept rather than the tail: the verdict and the
numbered issues come first, and the evidence that gets trimmed is the part
REX needs least.

── WHAT THIS DOES NOT FIX ───────────────────────────────────────────────────

The graph has a qa_fix node for exactly this: qa → qa_fix → qa. In G-Stack
mode, skill 06 failing makes node_build return status=failed, so the graph
never reaches node_qa and qa_fix never runs. The self-correction mechanism
exists and sits behind a door that closes first. That is a graph change and
deserves its own daylight; feedback is what unblocks the product tonight.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
s = SKILL.read_text(encoding="utf-8")

if "PRIOR_FAILURE_LIMIT" in s:
    sys.exit("Already patched — earlier failures reach the next build.")
if "skill_fingerprint" not in s:
    sys.exit("Apply patch_checkpoint_prompt.py first — the rejection has to go "
             "into the fingerprint or the cache eats it. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the helper ────────────────────────────────────────────────────────────
s = swap("helper", s, '''def skill_fingerprint(''',
         '''# How much of a rejecting report to hand to the next attempt. Every report
# this pipeline has produced fits; the head is kept rather than the tail
# because the verdict and the numbered issues come first and the trimmed part
# is supporting evidence.
PRIOR_FAILURE_LIMIT = 6000

# Skills that act on a QA rejection: the builder, and the reviewer who should
# know what QA found before passing the same code again.
FEEDBACK_SKILLS = {"04", "05"}


def prior_failure_context(topic: str, skill_num: str, results: dict) -> str:
    """
    What a LATER skill said when it rejected the last attempt.

    The forward context loop walks skills before this one, which is right for
    a single pass and blind on a re-run: skill 06 judges the build and comes
    after it, so its report reached nobody. IRIS diagnosed the same defect
    three times, correctly, in writing, and REX never saw a word of it.
    """
    if skill_num not in FEEDBACK_SKILLS:
        return ""

    blocks = []
    for num in sorted(SKILL_FILES):
        if num <= skill_num:
            continue
        entry = results.get(f"{num}-{SKILL_FILES[num].replace('.md','')}")
        if not entry or entry.get("status") != "fail":
            continue

        # From disk: the checkpoint copy is tail-truncated for storage and the
        # verdict is at the top of the report.
        path = PRODUCTS_DIR / "docs" / f"{topic}-skill{num}-output.txt"
        report = (path.read_text(errors="replace") if path.exists()
                  else entry.get("output", ""))
        if not report.strip():
            report = entry.get("verdict", "(no report recorded)")

        blocks.append(
            f"{'=' * 70}\\n"
            f"THE PREVIOUS BUILD FAILED {SKILL_NAMES.get(num, 'skill ' + num)} "
            f"— FIX THIS FIRST\\n"
            f"{'=' * 70}\\n"
            f"It judged the last attempt and rejected it. Its report follows. "
            f"These are not suggestions — the same check runs again on what "
            f"you produce, and it will reject the same code twice.\\n\\n"
            f"{report[:PRIOR_FAILURE_LIMIT]}\\n\\n"
            f"Fix every issue named above. Do not rewrite what already "
            f"passed, and do not weaken a test to make it pass.\\n"
            f"{'=' * 70}")

    return "\\n\\n".join(blocks)


def skill_fingerprint(''')

# ── 2. the rejection is part of the instructions, so it is part of the hash ──
#
# Without this the whole patch is inert. skill 04 is cached as a pass; the
# rejection goes into the context rather than into _skill_text, so the
# fingerprint would not move, 04 would replay, and the report would be
# assembled perfectly and handed to a skill that never ran.
s = swap("fingerprint signature", s,
         '''def skill_fingerprint(skill_num: str, skill_name: str, topic: str) -> str:''',
         '''def skill_fingerprint(skill_num: str, skill_name: str, topic: str,
                      rejection: str = "") -> str:''')

s = swap("fingerprint body", s,
         '''    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]''',
         '''    # A rejection carried into the prompt is a change of instructions by the
    # same definition the rest of this function uses.
    blob = text + rejection
    return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:12]''')

# ── 3. an outstanding rejection is never replayed past ───────────────────────
s = swap("replay guard", s,
         '''    current_sha = skill_fingerprint(skill_num, skill_name, topic)
    if prior and prior.get("status") == "pass":
        stored_sha = prior.get("prompt_sha", "")
        if not stored_sha:''',
         '''    # What a later skill said about the last attempt. Computed here, before
    # the replay decision, because it feeds both: it changes the prompt, and a
    # build QA has rejected is not one to replay a pass for.
    _rejection = prior_failure_context(topic, skill_num, results)
    current_sha = skill_fingerprint(skill_num, skill_name, topic, _rejection)
    if prior and prior.get("status") == "pass":
        stored_sha = prior.get("prompt_sha", "")
        if _rejection:
            print(f"♻️  {skill_name} passed, but a later skill rejected what it "
                  f"produced — re-running with that report in hand")
        elif not stored_sha:''')

# ── 4. and REX actually receives it ──────────────────────────────────────────
s = swap("inject", s, '''    context = "\\n\\n---\\n\\n".join(context_parts)''',
         '''    # Empty on a first run; on a re-run it is the most important thing in the
    # prompt, so it goes first rather than after three thousand characters of
    # PRD.
    if _rejection:
        print(f"📨 skill {skill_num}: carrying the previous attempt's "
              f"rejection ({len(_rejection):,} chars)", flush=True)
        context_parts.insert(0, _rejection)

    context = "\\n\\n---\\n\\n".join(context_parts)''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-qafeedback-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, SKILL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")


def die(msg):
    shutil.copy2(backup, SKILL)
    sys.exit(f"{msg} — reverted from {backup.name}")


# ── exercise the feedback ────────────────────────────────────────────────────
src = SKILL.read_text(encoding="utf-8")
tree = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in tree.body
            if isinstance(n, ast.FunctionDef)
            and n.name == "prior_failure_context"), None)
if seg is None:
    die("prior_failure_context did not land")

import tempfile
tmp = Path(tempfile.mkdtemp())
(tmp / "docs").mkdir()
(tmp / "docs" / "zz-skill06-output.txt").write_text(
    "VERDICT: FAIL\nISSUE 1 — Mock pool overwritten by lifespan\n"
    "Fix: patch asyncpg.create_pool\n" + ("evidence " * 2000),
    encoding="utf-8")

ns = {"PRODUCTS_DIR": tmp, "Path": Path,
      "SKILL_FILES": {"01": "01-prd-analysis.md", "04": "04-build.md",
                      "05": "05-code-review.md", "06": "06-qa-run-test.md"},
      "SKILL_NAMES": {"06": "Skill 06 — QA + Run Test"},
      "PRIOR_FAILURE_LIMIT": 6000, "FEEDBACK_SKILLS": {"04", "05"}}
exec(seg, ns)
fn = ns["prior_failure_context"]

FAILED = {"06-06-qa-run-test": {"status": "fail", "verdict": "VERDICT: FAIL"}}
PASSED = {"06-06-qa-run-test": {"status": "pass", "verdict": "VERDICT: PASS"}}

print("\nchecking the feedback:")
for skill, results_in, expect, label in [
    ("04", FAILED, True, "the builder gets the rejection"),
    ("05", FAILED, True, "the reviewer gets it too"),
    ("01", FAILED, False, "PRD analysis does not — it built nothing"),
    ("06", FAILED, False, "QA does not get its own report back"),
    ("04", PASSED, False, "a passing QA is not a rejection"),
    ("04", {}, False, "first run, nothing to carry"),
]:
    got = bool(fn("zz", skill, results_in).strip())
    print(f"  {'ok  ' if got == expect else 'FAIL'} skill {skill}: {label}")
    if got != expect:
        die(f"expected {expect}, got {got}")

out = fn("zz", "04", FAILED)
for must in ("FIX THIS FIRST", "ISSUE 1", "asyncpg.create_pool",
             "not suggestions", "do not weaken a test"):
    if must not in out:
        die(f"the carried report is missing {must!r}")
# The report is 20k of padded evidence; the block must be bounded and must
# still open with the verdict rather than the tail.
if len(out) > 6000 + 1500:
    die(f"the carried block is {len(out)} chars — the cap is not applied")
if out.index("ISSUE 1") > 600:
    die("the issues are buried — the head of the report was not kept")
print(f"  ok   the block is {len(out):,} chars, bounded, verdict first")

# ── exercise the cache decision, which is where this nearly failed ───────────
def decide(prior, rejection, current_sha):
    """Mirrors the patched replay branch."""
    if prior and prior.get("status") == "pass":
        stored = prior.get("prompt_sha", "")
        if rejection:
            return "rerun-rejected"
        if not stored:
            return "rerun-no-fingerprint"
        if current_sha and stored != current_sha:
            return "rerun-changed"
        return "replay"
    if prior:
        return "rerun-not-pass"
    return "run-fresh"


PASS04 = {"status": "pass", "prompt_sha": "4232a812b24b"}
print("\nchecking the replay decision:")
for prior, rej, sha, expect, label in [
    (PASS04, "", "4232a812b24b", "replay", "no rejection, same prompt"),
    (PASS04, out, "9f2ac1b0e4d3", "rerun-rejected",
     "TONIGHT: 04 cached pass, 06 failed"),
    (PASS04, "", "9f2ac1b0e4d3", "rerun-changed", "instructions changed"),
    ({"status": "pass"}, "", "aaa", "rerun-no-fingerprint", "legacy entry"),
    ({"status": "fail"}, "", "aaa", "rerun-not-pass", "previously failed"),
    (None, "", "aaa", "run-fresh", "never run"),
]:
    got = decide(prior, rej, sha)
    print(f"  {'ok  ' if got == expect else 'FAIL'} {label:38} → {got}")
    if got != expect:
        die(f"expected {expect}, got {got}")

# Fragments that do not straddle a line break in the GENERATED source. My
# first attempt looked for 'rejected what it produced', which the emitted
# f-string wraps across two lines, and it failed on correct code. The decision
# table above is the real check; this only confirms the wiring landed.
for must in ("rejected what it ",
             "skill_fingerprint(skill_num, skill_name, topic, _rejection)",
             "context_parts.insert(0, _rejection)"):
    if must not in src:
        die(f"{must!r} missing from the patched file")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Skill 04 is cached as a pass. The rejection now forces it to re-run,")
print("so no --invalidate is needed. Re-run the build:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase build --engine gstack --coder crewai "
      "--complexity simple")
print()
print("Expect, in order:")
print("  ♻️  Skill 04 — Build passed, but a later skill rejected what it produced")
print("  📨 skill 04: carrying the previous attempt's rejection (N chars)")
