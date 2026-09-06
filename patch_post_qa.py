#!/usr/bin/env python3
"""
The three sites that still speak the old vocabulary — including my regression.

    python3 scripts/patch_post_qa.py

── WHAT IS WRONG RIGHT NOW ──────────────────────────────────────────────────

Three places decide what happens after QA by testing a literal list:

    langgraph_flow.py:1538   node_launch      → gate_4, or straight to deploy
    langgraph_flow.py:1587   node_deploy      → start a service, or don't
    langgraph_flow.py:1685   route_after_launch

    product_type in ["software", "api", "dashboard"]

That list still says "dashboard". product_pathways renamed that concept to
"webpage" on 3 September, and I did not update these three. So since that
patch, a WEB PRODUCT skips gate 4 and skips deployment entirely — a regression
I introduced hours after writing up a census whose subject is exactly this.

And for a document the list was always wrong in the other direction:

    qa → gate_3 → launch (NOVA, Sales Director, writes a launch announcement
                          for an internal engineering document) → deploy

── WHAT REPLACES IT ─────────────────────────────────────────────────────────

Two fields on Pathway, and the three sites ask.

    deploys    is there a long-running service to start? Also decides whether
               gate 4 — the approval to deploy — means anything.
    launches   does NOVA write launch content? False for a document: nobody
               announces an internal reference to the market.

node_deploy keeps doing the rest of its job for every product. It is named
"deploy" but it also runs the Drive sync and marks the run complete, and a
document needs both — so only the service-start half is gated. That distinction
is the reason this is not simply `if pathway.deploys: return`.

── AND THE SCAFFOLDING ──────────────────────────────────────────────────────

deployment_contract() is appended to skill 04 for every product, which is why
your document shipped a .env.example, a requirements.txt and a service.json —
and why commit_all refused the whole ducorn-products repo over a placeholder
env file REX had no reason to write. A product that does not deploy is not
told how deployment works.
"""
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
SKILL = DC / "ducorn" / "skill_runner.py"
PW = DC / "scripts" / "product_pathways.py"

sys.path.insert(0, str(DC / "scripts"))
try:
    import product_pathways as _pw
except Exception as e:
    sys.exit(f"NOTHING WRITTEN — product_pathways will not import: {e}")

pwsrc = PW.read_text(encoding="utf-8")
fl = FLOW.read_text(encoding="utf-8")
sk = SKILL.read_text(encoding="utf-8")

if "launches" in pwsrc and "pathway.deploys" in fl:
    print("Already patched — the three sites ask the pathway.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ 1. the field ════════════════════════════════════════════════════════════
pwsrc = swap("launches field", pwsrc,
             '''    # ── what happens after the build ─────────────────────────────────────
    deploys: bool = True           # a long-running service, or a file?''',
             '''    # ── what happens after the build ─────────────────────────────────────
    deploys: bool = True           # a long-running service, or a file?
    launches: bool = True          # does NOVA write launch content?''')

# document is the only one that does not get announced to a market.
pwsrc = swap("document does not launch", pwsrc,
             '''        deploys=False,
        publish_to="docs",
        max_review_iterations=1,''',
             '''        deploys=False,
        launches=False,            # NOVA is the Sales Director. An internal
                                   # engineering reference is not launched.
        publish_to="docs",
        max_review_iterations=1,''')

# ═══ 2. node_launch ══════════════════════════════════════════════════════════
fl = swap("launch asks the pathway", fl,
          '''        product_type = state.get("product_type", "software")
        if product_type in ["software", "api", "dashboard"]:
            return {**state, "phase": "gate_4", "status": "awaiting_approval"}
        else:
            return {**state, "phase": "deploy", "status": "running"}''',
          '''        # Gate 4 is the approval to DEPLOY. A product with nothing to
        # deploy has nothing to approve, so it goes straight on. This tested
        # a literal list containing "dashboard" — a name product_pathways no
        # longer produces — so every web product was skipping gate 4.
        import product_pathways as _pwm
        _pathway = _pwm.for_topic(topic, override=state.get("product_type"),
                                  quiet=True)
        if _pathway.deploys:
            return {**state, "phase": "gate_4", "status": "awaiting_approval"}
        return {**state, "phase": "deploy", "status": "running"}''')

# NOVA does not write a launch announcement for a document.
fl = swap("NOVA is skipped for a document", fl,
          '''    topic = state["topic"]
    _use_key("NOVA")
    print(f"\\n🚀 NOVA: Launching '{topic}'")
    _update_db_status(topic, "running", "NOVA Launch")''',
          '''    topic = state["topic"]

    # An internal engineering reference does not get a launch announcement
    # from the Sales Director. This ran for every product type and wrote
    # marketing copy for a technology-stack document.
    import product_pathways as _pwm
    _pathway = _pwm.for_topic(topic, override=state.get("product_type"),
                              quiet=True)
    if not _pathway.launches:
        print(f"\\n⏭️  no launch content for a {_pathway.prompt_noun} — "
              f"skipping NOVA", flush=True)
        _update_db_status(topic, "running", "Launch skipped")
        return {**state,
                "phase": "gate_4" if _pathway.deploys else "deploy",
                "status": "awaiting_approval" if _pathway.deploys else "running"}

    _use_key("NOVA")
    print(f"\\n🚀 NOVA: Launching '{topic}'")
    _update_db_status(topic, "running", "NOVA Launch")''')

# ═══ 3. node_deploy — only the service half is gated ═════════════════════════
fl = swap("deploy asks the pathway", fl,
          '''    try:
        if product_type in ["software", "api", "dashboard"]:
            from tools.DuCornDeployTool import DuCornDeployTool
            tool = DuCornDeployTool()
            if product_type == "api":''',
          '''    try:
        # Only the service-start half is gated. This node is named "deploy"
        # but it also runs the Drive sync and marks the run complete, and a
        # document needs both — which is why this is a branch and not an
        # early return.
        import product_pathways as _pwm
        _pathway = _pwm.for_topic(topic, override=product_type, quiet=True)
        if _pathway.deploys:
            from tools.DuCornDeployTool import DuCornDeployTool
            tool = DuCornDeployTool()
            if product_type == "api":''')

fl = swap("deploy says what it skipped", fl,
          '''            else:
                _post_slack(f"🎉 *{topic} is LIVE!*\\n\\n{result}")

        # Sync to Google Drive''',
          '''            else:
                _post_slack(f"🎉 *{topic} is LIVE!*\\n\\n{result}")
        else:
            print(f"📄 nothing to deploy for a {_pathway.prompt_noun} — "
                  f"publishing and syncing instead", flush=True)

        # Sync to Google Drive''')

# ═══ 4. route_after_launch ═══════════════════════════════════════════════════
fl = swap("routing asks the pathway", fl,
          '''def route_after_launch(state: DuCornState) -> str:
    product_type = state.get("product_type", "software")
    if product_type in ["software", "api", "dashboard"]:
        return "gate_4"
    return "deploy"''',
          '''def route_after_launch(state: DuCornState) -> str:
    import product_pathways as _pwm
    _pathway = _pwm.for_topic(state["topic"],
                              override=state.get("product_type"), quiet=True)
    return "gate_4" if _pathway.deploys else "deploy"''')

# ═══ 5. no deployment contract for a product that does not deploy ════════════
sk = swap("no scaffolding for a document", sk,
          '''    if skill_num == BUILD_SKILL:
        # Every product is deployed, so every build is told how deployment
        # works. The UI contract is additional, for products that ship a page.
        text = text + deployment_contract(topic)''',
          '''    if skill_num == BUILD_SKILL:
        # NOT every product is deployed. Telling a document how deployment
        # works is why yours shipped a .env.example, a requirements.txt and a
        # service.json — and why commit_all refused the whole products repo
        # over a placeholder env file REX had no reason to write.
        if pathways.for_topic(topic, quiet=True).deploys:
            text = text + deployment_contract(topic)''')

# ═══ write all three, or none ════════════════════════════════════════════════
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(PW, pwsrc), (FLOW, fl), (SKILL, sk)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-postqa-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — all three files reverted")


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
print("syntax and undefined-name checks: clean on all three")

# ── the routing table, from the reloaded definitions ─────────────────────────
import importlib
importlib.reload(_pw)

print("\nwhat happens after QA, per pathway:\n")
print(f"  {'type':10} {'NOVA':6} {'gate 4':8} {'service':9} {'drive sync':11} scaffolding")
print("  " + "─" * 62)
for name, pw in _pw.PATHWAYS.items():
    print(f"  {name:10} "
          f"{'yes' if pw.launches else 'no':6} "
          f"{'yes' if pw.deploys else 'no':8} "
          f"{'yes' if pw.deploys else 'no':9} "
          f"{'yes':11} "
          f"{'yes' if pw.deploys else 'no'}")

fl_src = FLOW.read_text(encoding="utf-8")
sk_src = SKILL.read_text(encoding="utf-8")
print()
for src, must, why in [
    (fl_src, "if _pathway.deploys:", "gate 4 and the service ask the pathway"),
    (fl_src, "if not _pathway.launches:", "NOVA is skipped where it makes no sense"),
    (fl_src, 'return "gate_4" if _pathway.deploys else "deploy"',
     "routing asks the pathway"),
    (sk_src, "if pathways.for_topic(topic, quiet=True).deploys:",
     "no deployment contract for a document"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

stale = fl_src.count('["software", "api", "dashboard"]')
if stale:
    die(f"{stale} site(s) still test the old vocabulary")
print("  ok   no site tests the old ['software','api','dashboard'] list")

if not _pw.PATHWAYS["webpage"].deploys:
    die("webpage still does not deploy")
print("  ok   webpage reaches gate 4 and deploys again (my regression, closed)")
if _pw.PATHWAYS["document"].launches:
    die("a document still gets a launch announcement")
print("  ok   a document gets no launch announcement")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print("""
The document pathway after QA is now:

  qa → gate_3 → (no NOVA) → deploy node: publish, PDF, Drive sync, complete

Nothing to restart. Test G7 in the matrix — no product-type branch outside
product_pathways.py — has one fewer reason to be red.
""")
