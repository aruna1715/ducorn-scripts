#!/usr/bin/env python3
"""
An EPICS card on the product dashboard, with a Start-next-phase button.

    cd ~/DC && python3 scripts/patch_epic_dashboard.py            show
    cd ~/DC && python3 scripts/patch_epic_dashboard.py --apply    do it

Apply patch_epic_api.py first — this calls the endpoints it adds.

── WHY ──────────────────────────────────────────────────────────────────────

Phases could only be started from a terminal, and this company is operated
from the dashboard. A capability reachable only by CLI is one that does not
get used.

── WHAT IT ADDS ─────────────────────────────────────────────────────────────

One card above 03 / PRODUCTS: each epic, its phases with their status, and a
single button that starts whichever phase is next. The button asks the API
what would happen before it offers to do it, so it can say "phase 2 of 3 —
Services and housekeeping" rather than "Start", and can explain itself when
nothing may start.

Deliberately ONE button, not one per phase. Which phase runs next is decided
by dependencies in the database — offering a per-phase button would invite
starting phase 3 before phase 1, and would put that decision in the browser
where it would be a second copy of next_phase().

── SAFETY ───────────────────────────────────────────────────────────────────

Starting a phase spends money, so the button confirms with the phase name
first. Every value from the API is written with textContent, never innerHTML:
epic names and phase titles come from a plan file a person wrote, and this
page carries the API token.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
PAGE = (DC / "ducorn-products" / "products" / "ducorn-dashboard" / "index.html")
TAG = "epics"

HTML_ANCHOR = "      <!-- 03 / PRODUCTS -->"

HTML_BLOCK = """      <!-- 03a / EPICS -->
      <section class="card" style="margin-bottom:18px;" id="epicsCard">
        <div class="card-scan"></div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:12px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:var(--accent);">03a / EPICS</span>
            <span class="collapse-btn" id="btn-sec-epics" onclick="toggleSection('sec-epics');event.stopPropagation()">&#9662;</span>
            <div style="width:40px;height:1px;background:rgba(var(--accent-rgb),.3);"></div>
            <span class="mono" style="font-size:9px;color:var(--muted);">PRODUCTS BUILT IN PHASES</span>
          </div>
        </div>
        <div id="sec-epics" class="section-body">
          <div id="epicsList" style="display:flex;flex-direction:column;gap:10px;">
            <div class="mono" style="font-size:10px;color:var(--muted);text-align:center;padding:16px;">
              Loading epics...
            </div>
          </div>
        </div>
      </section>

"""

JS_ANCHOR = "async function loadProducts() {"

JS_MARK_A = "/* DUCORN-EPICS-JS-START */"
JS_MARK_B = "/* DUCORN-EPICS-JS-END */"

JS_BLOCK = JS_MARK_A + """
/* ── EPICS ────────────────────────────────────────────────────────────
   A product built over several runs. The page holds no rules about which
   phase runs next — it asks /epics/<name>, which calls the same code the
   command line calls. A second opinion in the browser is how two answers to
   one question start. */
const EPIC_COLOUR = {
  complete: "#4fd1c5", running: "#e0a85e", failed: "#e8796b",
  planned: "#5b6b78", pending: "#5b6b78", skipped: "#5b6b78",
};

async function loadEpics() {
  const box = document.getElementById("epicsList");
  if (!box) return;
  try {
    const res = await fetch(API + "/epics", {headers: HDR});
    const data = await res.json();
    box.innerHTML = "";
    const epics = (data && data.epics) || [];
    if (!epics.length) {
      const d = document.createElement("div");
      d.className = "mono";
      d.style.cssText = "font-size:10px;color:var(--muted);padding:14px;text-align:center;";
      d.textContent = "No epics yet — define one with scripts/product_epics.py --define";
      box.appendChild(d);
      return;
    }
    epics.forEach(e => box.appendChild(epicRow(e)));
  } catch (err) {
    box.innerHTML = "";
    const d = document.createElement("div");
    d.className = "mono";
    d.style.cssText = "font-size:10px;color:#e8796b;padding:14px;";
    d.textContent = "Could not load epics: " + err.message;
    box.appendChild(d);
  }
}

function epicRow(e) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "border:1px solid rgba(91,107,120,.3);border-radius:3px;padding:12px 14px;";

  const head = document.createElement("div");
  head.style.cssText = "display:flex;align-items:center;gap:10px;margin-bottom:10px;";

  const dot = document.createElement("span");
  dot.style.cssText = "width:7px;height:7px;border-radius:50%;flex:none;background:"
                    + (EPIC_COLOUR[e.status] || "#5b6b78");
  head.appendChild(dot);

  const name = document.createElement("span");
  name.className = "mono";
  name.style.cssText = "font-size:11px;color:var(--fg);letter-spacing:.06em;";
  name.textContent = e.name;                       /* never innerHTML */
  head.appendChild(name);

  const done = (e.phases || []).filter(p => p.status === "complete").length;
  const meta = document.createElement("span");
  meta.className = "mono";
  meta.style.cssText = "font-size:9px;color:var(--muted);letter-spacing:.1em;";
  meta.textContent = e.status.toUpperCase() + " · " + done + "/"
                   + (e.phases || []).length + " PHASES · " + (e.product_type || "?");
  head.appendChild(meta);

  const spacer = document.createElement("span");
  spacer.style.flex = "1";
  head.appendChild(spacer);

  const btn = document.createElement("button");
  btn.className = "mono";
  btn.style.cssText = "cursor:pointer;font-size:9px;letter-spacing:.14em;padding:4px 12px;"
                    + "background:rgba(var(--accent-rgb),.12);border:1px solid rgba(var(--accent-rgb),.35);"
                    + "border-radius:2px;color:var(--accent);white-space:nowrap;";
  btn.textContent = "CHECKING…";
  btn.disabled = true;
  head.appendChild(btn);
  wrap.appendChild(head);

  (e.phases || []).forEach(p => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:10px;padding:3px 0 3px 17px;";
    const s = document.createElement("span");
    s.className = "mono";
    s.style.cssText = "font-size:9px;letter-spacing:.1em;width:74px;color:"
                    + (EPIC_COLOUR[p.status] || "#5b6b78");
    s.textContent = p.status.toUpperCase();
    const t = document.createElement("span");
    t.className = "mono";
    t.style.cssText = "font-size:10px;color:var(--muted);";
    t.textContent = p.seq + ". " + p.title;
    row.appendChild(s); row.appendChild(t);
    wrap.appendChild(row);
  });

  /* Ask what would happen BEFORE offering to do it, so the button can name
     the phase and can explain itself when nothing may start. */
  fetch(API + "/epics/" + encodeURIComponent(e.name), {headers: HDR})
    .then(r => r.json())
    .then(plan => {
      if (plan.next) {
        btn.textContent = "START PHASE " + plan.next.seq;
        btn.title = plan.next.title;
        btn.disabled = false;
        btn.onclick = () => startNextPhase(e.name, plan.next, btn);
      } else {
        btn.textContent = "NOTHING TO START";
        btn.title = plan.blocked || "";
        btn.style.opacity = ".5";
        const why = document.createElement("div");
        why.className = "mono";
        why.style.cssText = "font-size:9px;color:var(--muted);padding:6px 0 0 17px;";
        why.textContent = plan.blocked || "";
        if (plan.blocked) wrap.appendChild(why);
      }
    })
    .catch(() => { btn.textContent = "UNAVAILABLE"; btn.style.opacity = ".5"; });

  return wrap;
}

async function startNextPhase(name, next, btn) {
  /* This spends money. Name the phase in the confirmation — "are you sure"
     with no subject is a question nobody reads. */
  if (!confirm("Start phase " + next.seq + " of " + name + "?\\n\\n"
             + next.title + "\\n\\nThis runs the pipeline and spends money."))
    return;
  btn.disabled = true;
  btn.textContent = "STARTING…";
  try {
    const res = await fetch(API + "/epics/" + encodeURIComponent(name) + "/start-next",
                            {method: "POST", headers: HDR});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
    btn.textContent = "STARTED";
    setTimeout(() => { loadEpics(); loadProducts(); }, 1500);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "START PHASE " + next.seq;
    alert("Could not start: " + err.message);
  }
}
""" + JS_MARK_B + "\n\n"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not PAGE.is_file():
    sys.exit(f"NOTHING DONE — {PAGE} is not there")

src = PAGE.read_text(encoding="utf-8")
print("patch_epic_dashboard\n")

if "loadEpics" in src:
    sys.exit("NOTHING DONE — the dashboard already has the epics card.")

checks = [("the 03 / PRODUCTS anchor", HTML_ANCHOR),
          ("loadProducts(), to insert the JS before", JS_ANCHOR),
          ("the API constant", 'const API = ')]
ok = True
for what, needle in checks:
    n = src.count(needle)
    print(f"  {'ok ' if n == 1 else '!! '}{what}  ({n} match)")
    ok = ok and n == 1

# The card is loaded where the products list is loaded. Find those call sites
# rather than guessing at a boot function name.
boots = len(re.findall(r"\bloadProducts\(\);", src))
print(f"  {'ok ' if boots else '!! '}loadProducts() call sites  ({boots} found)")
ok = ok and boots > 0

if not ok:
    sys.exit("\nNOTHING DONE — the page is not in the shape this patch expects.")

if not args.apply:
    print(f"\n  the card goes above 03 / PRODUCTS; loadEpics() is called "
          f"beside each of the {boots} loadProducts() calls")
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PAGE, PAGE.with_suffix(f".backup-{TAG}-{stamp}.html"))

# ORDER MATTERS, and the first version got it wrong.
#
# Refresh the epics wherever the products refresh — but substitute on the
# ORIGINAL page first. Doing it after the insert rewrote loadProducts()
# inside my own block too, producing "loadEpics(); loadProducts();
# loadEpics();" and, worse, meaning the block could no longer be found by
# its own text — so the syntax check silently skipped and the script printed
# "verified ... parses" having checked nothing.
out = re.sub(r"\bloadProducts\(\);", "loadProducts(); loadEpics();", src)
out = out.replace(HTML_ANCHOR, HTML_BLOCK + HTML_ANCHOR, 1)
out = out.replace(JS_ANCHOR, JS_BLOCK + JS_ANCHOR, 1)

PAGE.write_text(out, encoding="utf-8")
print(f"\nwrote {PAGE.name}, backup tagged {TAG}-{stamp}")

# The page is served as a static file — a syntax error is a blank dashboard.
# Located by MARKER, not by matching the block's own text: anything that
# edits the page can change that text, and a check that cannot find what it
# is checking must say so rather than pass.
import subprocess

checked = False
try:
    a = out.index(JS_MARK_A)
    b = out.index(JS_MARK_B) + len(JS_MARK_B)
except ValueError:
    sys.exit("⚠️  the inserted block cannot be found by its markers — "
             f"restore {PAGE.name}.backup-{TAG}-{stamp}.html and tell me.")

node = shutil.which("node")
if node:
    tmp = PAGE.with_suffix(".epiccheck.js")
    tmp.write_text(out[a:b], encoding="utf-8")
    r = subprocess.run([node, "--check", str(tmp)], capture_output=True,
                       text=True)
    tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        sys.exit("⚠️  the added JavaScript does not parse — restore "
                 f"{PAGE.name}.backup-{TAG}-{stamp}.html:\n"
                 + r.stderr.strip()[:400])
    checked = True

calls = len(re.findall(r"loadProducts\(\); loadEpics\(\);", out))
print(f"  {calls} refresh point(s) now load the epics too")
print(f"  the block is {b - a:,} bytes, located by marker")

print(f"""
{'verified: the added JavaScript parses.' if checked else
 'INSERTED, BUT NOT SYNTAX CHECKED — node is not on PATH. Open the dashboard '
 'and check the browser console before trusting it.'}

The dashboard is a static file, so just reload it:
  https://dashboard.ducorn-hq.live   (or http://localhost:8080)

You should see 03a / EPICS above 03 / PRODUCTS, with ducorn-admin-rebuild
and a START PHASE 1 button.
""")
