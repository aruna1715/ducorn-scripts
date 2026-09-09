#!/usr/bin/env python3
"""
Two buttons on an epic: TEST (free) and PRODUCTION (paid). Never one.

    cd ~/DC && python3 scripts/patch_phase_env_buttons.py            show
    cd ~/DC && python3 scripts/patch_phase_env_buttons.py --apply    do it

Apply patch_phase_test_default.py first — this sends the environment that
patch taught the endpoint to read.

── WHY TWO BUTTONS AND NOT A DROPDOWN ───────────────────────────────────────

A dropdown remembers its last value. The difference between these two is
"free" and "your credit balance", and a control that quietly keeps yesterday's
setting is how that difference gets made by accident.

Two buttons, two colours, two confirmations, and the expensive one says what
it is:

    ▶ START PHASE 2 — TEST      local models · nothing billed
    ⚡ PRODUCTION               paid models

── WHAT TEST ACTUALLY MEANS ─────────────────────────────────────────────────

Every agent pinned to the local model, by the run's environment column —
_pin_local_for_test_runs at startup, _get_agent_models for the nodes, and
node_design overriding even a per-run design-model choice:

    if _local_only():
        model = _LOCAL_MODEL
        print("🔒 test run — design model ... overridden")

Same nodes, same skills, same gates, same jail, same checkpoints. Different
bill.

It proves the PLUMBING, not the product: a local model writes worse output
than claude-sonnet, so a green test run means every step ran and handed off,
not that what it built is good. The production confirmation says so.

── ONE THING THE OPERATOR MUST KNOW ─────────────────────────────────────────

A test run of an epic builds into the SAME product directory as its
production runs, because that is what an epic is. Running a finished phase in
test mode would have a local model overwrite work a paid model produced. The
test confirmation warns when the product directory already has files in it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
PAGE = DC / "ducorn-products" / "products" / "ducorn-dashboard" / "index.html"
API = DC / "ducorn-products" / "products" / "ducorn-activity-api" / "main.py"
TAG = "envbuttons"

BTN_OLD = '''      if (plan.next) {
        btn.textContent = "START PHASE " + plan.next.seq;
        btn.title = plan.next.title;
        btn.disabled = false;
        btn.onclick = () => startNextPhase(e.name, plan.next, btn);
      } else {'''

BTN_NEW = '''      if (plan.next) {
        btn.textContent = "▶ START PHASE " + plan.next.seq + " — TEST";
        btn.title = plan.next.title
                  + "  ·  local models, nothing billed";
        btn.disabled = false;
        btn.onclick = () => startNextPhase(e.name, plan.next, btn, "test");

        /* PRODUCTION is its own button. A dropdown would remember its last
           value, and the difference between these two is "free" and "your
           credit balance". */
        const prod = document.createElement("button");
        prod.className = "mono";
        prod.style.cssText = "cursor:pointer;font-size:9px;letter-spacing:.14em;"
          + "padding:4px 10px;margin-left:6px;white-space:nowrap;"
          + "background:rgba(var(--amber-rgb,224,168,94),.12);"
          + "border:1px solid rgba(var(--amber-rgb,224,168,94),.4);"
          + "border-radius:2px;color:var(--amber);";
        prod.textContent = "⚡ PRODUCTION";
        prod.title = "Paid models. Only after a test run has proven the "
                   + "pipeline end to end.";
        prod.onclick = () => startNextPhase(e.name, plan.next, prod, "production");
        btn.parentNode.insertBefore(prod, btn.nextSibling);
      } else {'''

FN_OLD = '''  if (!confirm("Start phase " + next.seq + " of " + name + "?\\n\\n"
             + next.title + "\\n\\nThis runs the pipeline and spends money."))
    return;
  btn.disabled = true;
  btn.textContent = "STARTING…";
  try {
    const res = await fetch(API + "/epics/" + encodeURIComponent(name) + "/start-next",
                            {method: "POST", headers: HDR});'''

FN_NEW = '''  const paid = (environment === "production");
  const msg = paid
    ? ("PRODUCTION — paid models.\\n\\nStart phase " + next.seq + " of " + name
       + "?\\n" + next.title
       + "\\n\\nThis spends real credits on every skill. Only do this once a "
       + "TEST run has proven the pipeline end to end.")
    : ("TEST — local models, nothing billed.\\n\\nStart phase " + next.seq
       + " of " + name + "?\\n" + next.title
       + "\\n\\nThis proves the plumbing, not the product: a local model "
       + "writes worse output, and it builds into the SAME product directory "
       + "as a production run — so it can overwrite work a paid model "
       + "produced.");
  if (!confirm(msg)) return;
  btn.disabled = true;
  btn.textContent = paid ? "STARTING (PAID)…" : "STARTING…";
  try {
    const res = await fetch(API + "/epics/" + encodeURIComponent(name) + "/start-next",
                            {method: "POST", headers: HDR,
                             body: JSON.stringify({environment: environment})});'''

SIG_OLD = '''async function startNextPhase(name, next, btn) {'''
SIG_NEW = '''async function startNextPhase(name, next, btn, environment) {'''

RESET_OLD = '''    btn.disabled = false;
    btn.textContent = "START PHASE " + next.seq;
    alert("Could not start: " + err.message);'''
RESET_NEW = '''    btn.disabled = false;
    btn.textContent = (environment === "production")
      ? "⚡ PRODUCTION" : ("▶ START PHASE " + next.seq + " — TEST");
    alert("Could not start: " + err.message);'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (PAGE, API):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

print("patch_phase_env_buttons\n")

api_src = API.read_text(encoding="utf-8")
if "environment=env" not in api_src:
    sys.exit("NOTHING DONE — apply patch_phase_test_default.py first; the "
             "endpoint does not read an environment yet, so these buttons "
             "would both start the same kind of run.")
print("  ok  the endpoint reads an environment from the request")

src = PAGE.read_text(encoding="utf-8")
if "⚡ PRODUCTION" in src:
    sys.exit("NOTHING DONE — the environment buttons are already there.")

bad = False
for label, a in [("the start button block", BTN_OLD),
                 ("startNextPhase signature", SIG_OLD),
                 ("its confirm and fetch", FN_OLD),
                 ("its error reset", RESET_OLD)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PAGE, PAGE.with_suffix(f".backup-{TAG}-{stamp}.html"))
PAGE.write_text(src.replace(BTN_OLD, BTN_NEW, 1).replace(SIG_OLD, SIG_NEW, 1)
                .replace(FN_OLD, FN_NEW, 1).replace(RESET_OLD, RESET_NEW, 1),
                encoding="utf-8")
print(f"\nwrote {PAGE.name}, backup tagged {TAG}-{stamp}")

after = PAGE.read_text(encoding="utf-8")
node = shutil.which("node")
if node:
    i = after.find("async function startNextPhase(name, next, btn, environment)")
    j = after.find("/* DUCORN-EPICS-JS-END */")
    frag = after[i:j] if i >= 0 and j > i else ""
    if not frag:
        sys.exit("⚠️  could not locate startNextPhase — restore the backup.")
    r = subprocess.run([node, "--check"], input=frag, capture_output=True,
                       text=True)
    if r.returncode != 0:
        sys.exit(f"⚠️  the epics JS does not parse — restore the backup:\n"
                 f"{r.stderr[-400:]}")
    print("verified: startNextPhase parses (node --check).")
else:
    print("NOT verified: node is not on PATH. Check the console after "
          "reloading.")

# The money line: an environment must always be SENT. A call that omits it
# would fall to the endpoint's default, which is safe today and is not a
# thing to rely on from a button that says PRODUCTION on it.
if "body: JSON.stringify({environment: environment})" not in after:
    sys.exit("⚠️  the environment is not sent in the body — restore the "
             "backup.")
if after.count('startNextPhase(e.name, plan.next,') != 2:
    sys.exit("⚠️  expected exactly two call sites (test and production) — "
             "restore the backup.")
print("          both buttons send an explicit environment.")

print("""
  Hard-reload the dashboard.

Each epic now shows:

  ▶ START PHASE n — TEST      local models, nothing billed
  ⚡ PRODUCTION               paid models, with a confirmation that says so

The TEST confirmation also warns that a test run builds into the same product
directory as a production run — so it can overwrite what a paid model made.
""")
