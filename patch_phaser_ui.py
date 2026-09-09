#!/usr/bin/env python3
"""
The PHASER button — define a phased product from the dashboard.

    cd ~/DC && python3 scripts/patch_phaser_ui.py            show
    cd ~/DC && python3 scripts/patch_phaser_ui.py --apply    do it

Apply patch_phaser_api.py first — this calls the endpoints it adds.

── WHY ──────────────────────────────────────────────────────────────────────

Starting a phase, watching it, approving its gates and reading its log are
all on the dashboard. Creating the epic was a JSON file written by hand and a
CLI command, so every phased product needed me. This is the step that closes
that, and it is the whole reason the epic system was worth building.

── THE FLOW ─────────────────────────────────────────────────────────────────

    name · type · how many phases · the whole-product brief
        ↓  SPLIT   (one BRIEF-model call, creates nothing)
    the proposed phases, every title and brief editable
        ↓  CREATE  (POST /epics → product_epics.define)
    the epic appears in 03a / EPICS with START PHASE 1

SPLIT is skippable. Leave it alone and write the phases yourself; the form is
the same either way, because the model is a convenience and not a step.

── WHY THE MODEL'S TEXT IS NEVER innerHTML ──────────────────────────────────

Phase titles and briefs arrive from a language model and go into a page that
carries the API token in its source. They are written with .value and
.textContent, never innerHTML. That is not a theoretical worry: this page
would render whatever a model was persuaded to emit.
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
TAG = "phaserui"

BTN_ANCHOR = ('        <a class="act-btn" href="#" onclick="openBriefWizard();'
              'return false;" title="Generate a product brief with AI">'
              'BRIEF WIZARD</a>\n')

BTN_NEW = BTN_ANCHOR + (
    '        <a class="act-btn" href="#" onclick="openPhaser();return false;" '
    'title="Plan a product built over several runs">PHASER</a>\n')

JS_ANCHOR = "/* DUCORN-EPICS-JS-END */"

JS_BLOCK = '''
/* DUCORN-PHASER-JS-START */
/* ── PHASER ───────────────────────────────────────────────────────────
   Define a product built over several runs. Two steps: propose, then
   create. The proposal is a convenience — the form works with the SPLIT
   button untouched, because a model that is unavailable must not be a
   reason you cannot plan a product. */
let PHASER_PHASES = [];

function openPhaser() {
  PHASER_PHASES = [];
  ["phName", "phBrief"].forEach(id => { const e = document.getElementById(id); if (e) e.value = ""; });
  document.getElementById("phCount").value = "3";
  document.getElementById("phPhases").innerHTML = "";
  phaserSay("");
  document.getElementById("phCreate").style.display = "none";
  document.getElementById("phaserModal").style.display = "flex";
}

function closePhaser() {
  document.getElementById("phaserModal").style.display = "none";
}

function phaserSay(msg, bad) {
  const e = document.getElementById("phMsg");
  e.textContent = msg || "";                    /* never innerHTML */
  e.style.color = bad ? "#e8796b" : "var(--muted)";
}

function phaserRender() {
  const box = document.getElementById("phPhases");
  box.innerHTML = "";
  PHASER_PHASES.forEach((p, i) => {
    const wrap = document.createElement("div");
    wrap.style.cssText = "border:1px solid rgba(91,107,120,.3);border-radius:4px;padding:10px;margin-bottom:10px;";

    const head = document.createElement("div");
    head.style.cssText = "display:flex;gap:8px;align-items:center;margin-bottom:6px;";
    const seq = document.createElement("span");
    seq.className = "mono";
    seq.style.cssText = "font-size:9px;color:var(--accent);letter-spacing:.14em;white-space:nowrap;";
    seq.textContent = "PHASE " + p.seq;
    const title = document.createElement("input");
    title.value = p.title || "";                /* .value, not innerHTML */
    title.style.cssText = "flex:1;padding:6px 10px;background:var(--field);border:1px solid var(--field-border);border-radius:5px;color:var(--ink-3);font-size:11px;font-family:inherit;";
    title.oninput = () => { PHASER_PHASES[i].title = title.value; };
    head.appendChild(seq); head.appendChild(title);
    wrap.appendChild(head);

    const slug = document.createElement("div");
    slug.className = "mono";
    slug.style.cssText = "font-size:8px;color:var(--muted);margin-bottom:6px;";
    /* The slug is built by the API from the name and the sequence, and is
       shown rather than edited: it is an identity three tables and the
       filesystem jail have to agree on. */
    slug.textContent = p.slug + (p.depends_on && p.depends_on.length
        ? "  ·  after phase " + p.depends_on.join(", ") : "  ·  no dependencies");
    wrap.appendChild(slug);

    const brief = document.createElement("textarea");
    brief.value = p.brief || "";
    brief.rows = 5;
    brief.placeholder = "What THIS phase delivers, and how you would know it is done.";
    brief.style.cssText = "width:100%;padding:8px 10px;background:var(--field);border:1px solid var(--field-border);border-radius:5px;color:var(--ink-3);font-size:11px;font-family:inherit;box-sizing:border-box;resize:vertical;";
    brief.oninput = () => { PHASER_PHASES[i].brief = brief.value; };
    wrap.appendChild(brief);

    box.appendChild(wrap);
  });
  document.getElementById("phCreate").style.display =
      PHASER_PHASES.length ? "inline-block" : "none";
}

async function phaserSplit() {
  const name = document.getElementById("phName").value.trim();
  const brief = document.getElementById("phBrief").value.trim();
  const btn = document.getElementById("phSplit");
  if (!name || brief.length < 80) {
    phaserSay("A name and a brief of at least 80 characters — a two-line brief splits into two-line phases.", true);
    return;
  }
  btn.disabled = true; btn.textContent = "SPLITTING…";
  phaserSay("Asking the BRIEF model. Nothing is created.");
  try {
    const res = await fetch(API + "/epics/split", {
      method: "POST", headers: HDR,
      body: JSON.stringify({name: name, brief: brief,
                            product_type: document.getElementById("phType").value,
                            phases: parseInt(document.getElementById("phCount").value, 10)})});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
    PHASER_PHASES = data.phases || [];
    phaserRender();
    phaserSay(PHASER_PHASES.length + " phases proposed on " + (data.model || "?")
              + ". Edit anything before creating.");
  } catch (err) {
    phaserSay("Split failed: " + err.message + " — you can still write the phases yourself.", true);
  } finally {
    btn.disabled = false; btn.textContent = "SPLIT INTO PHASES";
  }
}

function phaserBlank() {
  /* The form without the model. Same shape, so an unavailable model is an
     inconvenience and not a wall. */
  const name = document.getElementById("phName").value.trim() || "epic";
  const n = Math.max(2, Math.min(parseInt(document.getElementById("phCount").value, 10) || 3, 8));
  PHASER_PHASES = [];
  for (let i = 1; i <= n; i++) {
    PHASER_PHASES.push({seq: i, title: "", brief: "",
                        slug: name + "-p" + i + "-phase",
                        depends_on: i > 1 ? [i - 1] : []});
  }
  phaserRender();
  phaserSay("Empty phases. Give each a title and a brief. The slugs are provisional until you create.");
}

async function phaserCreate() {
  const name = document.getElementById("phName").value.trim();
  const btn = document.getElementById("phCreate");
  const empty = PHASER_PHASES.filter(p => !(p.title || "").trim() || !(p.brief || "").trim());
  if (empty.length) {
    phaserSay(empty.length + " phase(s) still have no title or no brief. A phase with an empty brief builds nothing.", true);
    return;
  }
  if (!confirm("Create the epic '" + name + "' with " + PHASER_PHASES.length
             + " phases?\\n\\nThis creates the plan only. No run starts and nothing is spent."))
    return;
  btn.disabled = true; btn.textContent = "CREATING…";
  try {
    const res = await fetch(API + "/epics", {
      method: "POST", headers: HDR,
      body: JSON.stringify({
        name: name,
        product_type: document.getElementById("phType").value,
        brief: document.getElementById("phBrief").value.trim(),
        /* Slugs are rebuilt server-side from the (possibly edited) titles
           only when they were never proposed; what is sent is what was
           shown, so the row matches the screen. */
        phases: PHASER_PHASES.map(p => ({title: p.title, slug: p.slug,
                                         brief: p.brief,
                                         depends_on: p.depends_on}))})});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
    closePhaser();
    loadEpics();
  } catch (err) {
    phaserSay("Could not create: " + err.message, true);
  } finally {
    btn.disabled = false; btn.textContent = "CREATE EPIC";
  }
}
/* DUCORN-PHASER-JS-END */
'''

HTML_ANCHOR = '<div id="briefWizardModal"'

HTML_BLOCK = '''<div id="phaserModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9999;align-items:center;justify-content:center;">
  <div class="card" style="width:min(760px,92vw);max-height:88vh;overflow:auto;padding:22px;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
      <span class="mono" style="font-size:10px;letter-spacing:.22em;color:var(--accent);">PHASER — A PRODUCT BUILT OVER SEVERAL RUNS</span>
      <span class="mono" style="cursor:pointer;color:var(--muted);font-size:14px;" onclick="closePhaser()">&times;</span>
    </div>

    <div style="display:flex;gap:10px;margin-bottom:12px;">
      <div style="flex:2;">
        <label class="mono" style="font-size:8px;color:var(--muted);display:block;margin-bottom:5px;">EPIC NAME &mdash; LOWERCASE, HYPHENS</label>
        <input id="phName" placeholder="ducorn-admin-rebuild" style="width:100%;padding:8px 12px;background:var(--field);border:1px solid var(--field-border);border-radius:6px;color:var(--ink-3);font-size:11px;font-family:inherit;box-sizing:border-box;">
      </div>
      <div style="flex:1;">
        <label class="mono" style="font-size:8px;color:var(--muted);display:block;margin-bottom:5px;">TYPE</label>
        <select id="phType" style="width:100%;padding:8px 12px;background:var(--field);border:1px solid var(--field-border);border-radius:6px;color:var(--ink-3);font-size:11px;font-family:inherit;">
          <option value="webpage">Webpage</option>
          <option value="software">Software</option>
          <option value="api">API</option>
          <option value="cli">CLI</option>
          <option value="document">Document</option>
        </select>
      </div>
      <div style="width:88px;">
        <label class="mono" style="font-size:8px;color:var(--muted);display:block;margin-bottom:5px;">PHASES</label>
        <input id="phCount" type="number" min="2" max="8" value="3" style="width:100%;padding:8px 12px;background:var(--field);border:1px solid var(--field-border);border-radius:6px;color:var(--ink-3);font-size:11px;font-family:inherit;box-sizing:border-box;">
      </div>
    </div>

    <div style="margin-bottom:12px;">
      <label class="mono" style="font-size:8px;color:var(--muted);display:block;margin-bottom:5px;">THE WHOLE PRODUCT &mdash; WHAT IT IS, AND ANY CONSTRAINT THAT BINDS EVERY PHASE</label>
      <textarea id="phBrief" rows="7" placeholder="What the finished product is, who runs it, and the constraints that hold for every phase — security, where it binds, what it must never do. Every phase is shown this." style="width:100%;padding:8px 12px;background:var(--field);border:1px solid var(--field-border);border-radius:6px;color:var(--ink-3);font-size:11px;font-family:inherit;box-sizing:border-box;resize:vertical;"></textarea>
    </div>

    <div style="display:flex;gap:8px;align-items:center;margin-bottom:14px;">
      <button id="phSplit" class="mono" onclick="phaserSplit()" style="cursor:pointer;font-size:9px;letter-spacing:.14em;padding:7px 14px;background:rgba(var(--accent-rgb),.12);border:1px solid rgba(var(--accent-rgb),.35);border-radius:3px;color:var(--accent);">SPLIT INTO PHASES</button>
      <button class="mono" onclick="phaserBlank()" style="cursor:pointer;font-size:9px;letter-spacing:.14em;padding:7px 14px;background:transparent;border:1px solid rgba(91,107,120,.4);border-radius:3px;color:var(--muted);">WRITE THEM MYSELF</button>
      <span id="phMsg" class="mono" style="font-size:9px;color:var(--muted);flex:1;"></span>
    </div>

    <div id="phPhases"></div>

    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px;">
      <button class="mono" onclick="closePhaser()" style="cursor:pointer;font-size:9px;letter-spacing:.14em;padding:7px 14px;background:transparent;border:1px solid rgba(91,107,120,.4);border-radius:3px;color:var(--muted);">CANCEL</button>
      <button id="phCreate" class="mono" onclick="phaserCreate()" style="display:none;cursor:pointer;font-size:9px;letter-spacing:.14em;padding:7px 16px;background:rgba(var(--accent-rgb),.16);border:1px solid rgba(var(--accent-rgb),.45);border-radius:3px;color:var(--accent);">CREATE EPIC</button>
    </div>
  </div>
</div>

'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (PAGE, API):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

print("patch_phaser_ui\n")

if "/epics/split" not in API.read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — apply patch_phaser_api.py first. Every button "
             "here would call an endpoint that does not exist, and the page "
             "would fail only when someone pressed it.")
print("  ok  /epics/split and POST /epics exist in the API")

src = PAGE.read_text(encoding="utf-8")
if "function openPhaser" in src:
    sys.exit("NOTHING DONE — the Phaser is already on the page.")

bad = False
for label, a in [("the BRIEF WIZARD button", BTN_ANCHOR),
                 ("the epics JS block end", JS_ANCHOR),
                 ("the brief wizard modal", HTML_ANCHOR)]:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if "function loadEpics" not in src:
    sys.exit("NOTHING DONE — this page has no loadEpics(); creating an epic "
             "would show nothing afterwards. Apply patch_epic_dashboard.py "
             "first.")
print("  ok  loadEpics() is on the page, so a new epic appears immediately")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PAGE, PAGE.with_suffix(f".backup-{TAG}-{stamp}.html"))
out = src.replace(BTN_ANCHOR, BTN_NEW, 1)
out = out.replace(JS_ANCHOR, JS_BLOCK + JS_ANCHOR, 1)
out = out.replace(HTML_ANCHOR, HTML_BLOCK + HTML_ANCHOR, 1)
PAGE.write_text(out, encoding="utf-8")
print(f"\nwrote {PAGE.name}, backup tagged {TAG}-{stamp}")

after = PAGE.read_text(encoding="utf-8")
js = after[after.find("/* DUCORN-PHASER-JS-START */"):
           after.find("/* DUCORN-PHASER-JS-END */")]
if not js:
    sys.exit("⚠️  the Phaser JS markers are missing — restore the backup.")

node = shutil.which("node")
if node:
    r = subprocess.run([node, "--check"], input=js, capture_output=True,
                       text=True)
    if r.returncode != 0:
        sys.exit(f"⚠️  the Phaser JS does not parse — restore the backup:\\n"
                 f"{r.stderr[-400:]}")
    print("verified: the Phaser JS parses (node --check).")
else:
    print("NOT verified: node is not on PATH, so the JS was not parsed. "
          "Open the console after reloading before trusting it.")

# Model text must never reach innerHTML. Checked, because this page carries
# the API token and the phases come from a language model.
for hit in ("innerHTML = p.", "innerHTML = data", "innerHTML += "):
    if hit in js:
        sys.exit(f"⚠️  the Phaser writes model text with {hit!r} — restore "
                 f"the backup.")
print("          model-supplied text is written with .value/.textContent "
      "only.")

print("""
  Hard-reload the dashboard.

PHASER sits beside BRIEF WIZARD. A dry path that spends nothing:
open it, type a name, press WRITE THEM MYSELF, then CANCEL.

SPLIT costs one BRIEF-model call and creates nothing.
""")
