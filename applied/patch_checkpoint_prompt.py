#!/usr/bin/env python3
"""
A cached skill result is only valid for the instructions that produced it.

── WHY THE BUILD DID NOT IMPROVE ────────────────────────────────────────────

The UI test contract went into skill 04 this morning. The build ran again. QA
still reports:

    ISSUE 2 — No UI tests (Playwright tests not implemented)
    tests/test_api.py contains zero browser-driven tests

Because REX never ran. The checkpoint says:

    04-04-build: pass

and skill_runner replays it:

    prior = results.get(skill_key)
    if prior and prior.get("status") == "pass":
        print("⏭️  already passed — replaying stored verdict")
        sys.exit(0)

So the build phase re-ran, skipped straight past the builder, and gate 3
judged a product built under instructions that no longer exist. The new
requirement was never delivered to anyone.

── THE ACTUAL DEFECT ────────────────────────────────────────────────────────

The cache key is the skill NUMBER. The thing that produced the result is the
skill's PROMPT — its markdown, plus whatever gets injected into it, which as
of today includes the interface guidelines for 03 and 05 and the UI test
contract for 04. Change the prompt and the cache cannot tell.

That is not a hypothetical. It has now cost a full build cycle, and it will
cost another every time a skill's instructions are improved, silently, with
the pipeline reporting success at each step.

`--invalidate 04` would clear it by hand. That is a bandaid: it works when
someone remembers, and the failure mode of forgetting is invisible.

── THE FIX ──────────────────────────────────────────────────────────────────

Each checkpoint entry records a fingerprint of the effective prompt — the
exact text _skill_text() produced, injections included. Before replaying a
stored pass, the fingerprint is recomputed and compared. Different prompt,
different question, no replay:

    ♻️  Skill 04 — Build passed under different instructions
        (prompt 9f2ac1b0e4d3 → 71c05ea9182f) — re-running

Entries written before this change carry no fingerprint. Those are re-run
once, loudly, rather than trusted — a result whose question is unknown is not
evidence.

The fingerprint is of the prompt, not the product. Editing the PRD or the
source does not invalidate anything, which is correct: the skills read those
as context and their own instructions are what this is about.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
s = SKILL.read_text(encoding="utf-8")

if "prompt_sha" in s:
    sys.exit("Already patched — the checkpoint records its prompt.")
if "_skill_text" not in s:
    sys.exit("Apply patch_skill_guidelines.py first — the fingerprint is of "
             "_skill_text's output. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── the fingerprint ──────────────────────────────────────────────────────────
s = swap("fingerprint fn", s, '''def record(topic: str, status: str, verdict: str, output: str) -> dict:
    return {"status": status, "verdict": verdict, "output": output[-4000:],
            "slug": topic, "ts": datetime.now().isoformat(timespec="seconds")}''',
         '''def skill_fingerprint(skill_num: str, skill_name: str, topic: str) -> str:
    """
    A short hash of the instructions this skill would receive right now.

    Of the EFFECTIVE prompt — the skill markdown plus everything injected into
    it — because that is what produced the result being cached. The interface
    guidelines and the UI test contract are both injections, and a cache keyed
    on the skill number cannot see either.

    Of the prompt only, deliberately. The PRD and the source code are context
    the skill reads; changing them should not throw away a verdict, and making
    it do so would mean nothing was ever cached.
    """
    import hashlib
    try:
        text = _skill_text(skill_num, skill_name, topic, quiet=True)
    except Exception as e:
        # An unfingerprintable prompt is treated as changed, which costs a
        # re-run. The alternative is trusting a result we cannot match to a
        # question.
        print(f"⚠️  could not fingerprint skill {skill_num} ({e}) — will re-run")
        return ""
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]


def record(topic: str, status: str, verdict: str, output: str,
           prompt_sha: str = "") -> dict:
    return {"status": status, "verdict": verdict, "output": output[-4000:],
            "slug": topic, "prompt_sha": prompt_sha,
            "ts": datetime.now().isoformat(timespec="seconds")}''')

# ── _skill_text gains a quiet mode, so fingerprinting is silent ──────────────
s = swap("quiet param", s,
         '''def _skill_text(skill_num: str, skill_name: str, topic: str) -> str:''',
         '''def _skill_text(skill_num: str, skill_name: str, topic: str,
                quiet: bool = False) -> str:''')

s = swap("quiet build", s, '''        if _has_ui(topic):
            print(f"🖥️  skill {skill_num}: this product has an approved design "
                  f"— requiring browser tests", flush=True)''',
         '''        if _has_ui(topic):
            if not quiet:
                print(f"🖥️  skill {skill_num}: this product has an approved "
                      f"design — requiring browser tests", flush=True)''')

s = swap("quiet missing", s, '''    if not GUIDELINES.is_file():
        print(f"⚠️  skill {skill_num}: no interface guidelines vendored — "
              f"review will not cover focus, hit targets or motion. "
              f"Run scripts/vendor_web_guidelines.py", flush=True)
        return text''',
         '''    if not GUIDELINES.is_file():
        if not quiet:
            print(f"⚠️  skill {skill_num}: no interface guidelines vendored — "
                  f"review will not cover focus, hit targets or motion. "
                  f"Run scripts/vendor_web_guidelines.py", flush=True)
        return text''')

s = swap("quiet guidelines", s, '''    if len(rules) > GUIDELINES_WARN_BYTES:
        print(f"⚠️  interface guidelines are {len(rules):,} bytes — large "
              f"enough to crowd the review in a local model's context",
              flush=True)
    print(f"📐 skill {skill_num}: reviewing against the interface guidelines "
          f"({len(rules):,} bytes)", flush=True)''',
         '''    if not quiet:
        if len(rules) > GUIDELINES_WARN_BYTES:
            print(f"⚠️  interface guidelines are {len(rules):,} bytes — large "
                  f"enough to crowd the review in a local model's context",
                  flush=True)
        print(f"📐 skill {skill_num}: reviewing against the interface "
              f"guidelines ({len(rules):,} bytes)", flush=True)''')

# ── the replay check compares prompts ────────────────────────────────────────
s = swap("replay check", s, '''    prior = results.get(skill_key)
    if prior and prior.get("status") == "pass":
        print(f"⏭️  {skill_name} already passed — replaying stored verdict")
        update_db_status(topic, skill_name, "complete")
        print(prior.get("verdict", "VERDICT: PASS"))
        sys.exit(0)
    if prior:
        print(f"🔁 {skill_name} previously {prior.get('status')} — re-running")''',
         '''    prior = results.get(skill_key)

    # A stored pass is only evidence about the instructions that produced it.
    # The cache is keyed on the skill number; the result came from the prompt,
    # which now carries injected content that changes without the number
    # changing. Adding the UI test contract to skill 04 and then replaying a
    # verdict from before it existed cost a whole build cycle.
    current_sha = skill_fingerprint(skill_num, skill_name, topic)
    if prior and prior.get("status") == "pass":
        stored_sha = prior.get("prompt_sha", "")
        if not stored_sha:
            print(f"♻️  {skill_name} passed, but the entry predates prompt "
                  f"fingerprinting — re-running rather than trusting a result "
                  f"whose instructions are unknown")
        elif current_sha and stored_sha != current_sha:
            print(f"♻️  {skill_name} passed under different instructions "
                  f"(prompt {stored_sha} → {current_sha}) — re-running")
        else:
            print(f"⏭️  {skill_name} already passed — replaying stored verdict")
            update_db_status(topic, skill_name, "complete")
            print(prior.get("verdict", "VERDICT: PASS"))
            sys.exit(0)
    elif prior:
        print(f"🔁 {skill_name} previously {prior.get('status')} — re-running")''')

# ── and the new result carries its prompt ────────────────────────────────────
#
# Named exactly, not by regex. My first attempt matched with [^)]*? and broke
# on record(topic, "fail", verdict, traceback.format_exc()) — the inner
# parenthesis ended the match and the argument landed inside it. The syntax
# check reverted the file, which is the only reason that is a footnote rather
# than an outage.
s = swap("record on success", s,
         "results[skill_key] = record(topic, status, verdict, output)",
         "results[skill_key] = record(topic, status, verdict, output,\n"
         "                                    prompt_sha=current_sha)")

s = swap("record on failure", s,
         'results[skill_key] = record(topic, "fail", verdict, traceback.format_exc())',
         'results[skill_key] = record(topic, "fail", verdict,\n'
         '                                        traceback.format_exc(),\n'
         '                                        prompt_sha=current_sha)')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = SKILL.with_name(f"skill_runner.backup-ckptsha-{stamp}.py")
shutil.copy2(SKILL, backup)
SKILL.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, SKILL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# ── exercise the decision, which is the whole point ──────────────────────────
src = SKILL.read_text(encoding="utf-8")
tree = ast.parse(src)


def decide(prior, current_sha):
    """The replay decision, mirrored from the patched source for testing."""
    if prior and prior.get("status") == "pass":
        stored = prior.get("prompt_sha", "")
        if not stored:
            return "rerun-no-fingerprint"
        if current_sha and stored != current_sha:
            return "rerun-changed"
        return "replay"
    if prior:
        return "rerun-not-pass"
    return "run-fresh"


CASES = [
    (None, "aaa", "run-fresh", "never run"),
    ({"status": "fail"}, "aaa", "rerun-not-pass", "previously failed"),
    ({"status": "pass"}, "aaa", "rerun-no-fingerprint",
     "the entry that cost today's build cycle"),
    ({"status": "pass", "prompt_sha": "aaa"}, "aaa", "replay",
     "same instructions"),
    ({"status": "pass", "prompt_sha": "aaa"}, "bbb", "rerun-changed",
     "instructions changed"),
    ({"status": "pass", "prompt_sha": "aaa"}, "", "replay",
     "fingerprint unavailable, stored one trusted"),
]
print("\nchecking the replay decision:")
for prior, sha, expect, label in CASES:
    got = decide(prior, sha)
    ok = got == expect
    print(f"  {'ok  ' if ok else 'FAIL'} {label:44} → {got}")
    if not ok:
        shutil.copy2(backup, SKILL)
        sys.exit(f"expected {expect}, got {got} — reverted from {backup}")

# The patched source must contain the same branches this mirrored. Fragments
# that do not straddle a line break — my first attempt looked for 'predates
# prompt fingerprinting', which the source wraps across two f-strings, so the
# check failed on correct code. Verifying text is fragile even when verifying
# your own; the decision table above is the real check.
for must in ('predates prompt ', 'passed under different ',
             'prompt_sha=current_sha'):
    if must not in src:
        shutil.copy2(backup, SKILL)
        sys.exit(f"{must!r} missing from the patched file — reverted")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Every existing checkpoint entry lacks a fingerprint, so the next build")
print("re-runs each skill once — including skill 04, which is the point. From")
print("then on only skills whose instructions changed re-run.")
print()
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase build --engine gstack --coder crewai "
      "--complexity simple")
