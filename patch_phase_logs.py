#!/usr/bin/env python3
"""
Open a phase's log from the epic card.

    cd ~/DC && python3 scripts/patch_phase_logs.py            show
    cd ~/DC && python3 scripts/patch_phase_logs.py --apply    do it

── THE COMPLAINT ────────────────────────────────────────────────────────────

"I am not able to see any logs or anything in the dashboard for the phased
build."

── WHAT IS ACTUALLY TRUE ────────────────────────────────────────────────────

The log exists and is already reachable in two places:

  · the product dashboard's PRODUCTS list, because /products returns every
    pipeline_runs row and a phase has one — it is sitting there as
    ducorn-admin-rebuild-p1-config, and clicking it opens the detail panel
    with the live LOG tab
  · the admin dashboard's RUNS tab, which lists logs/flow_<slug>.log

Nothing was missing. Nothing POINTED at it. The epic card shows a phase's
status and then leaves you to work out that the phase is also a product row
under a name you never typed. That is a navigation failure, and telling you
where to look instead of fixing it would be the same failure with a manual.

── THE FIX ──────────────────────────────────────────────────────────────────

A phase row that has a run becomes clickable, and opens the existing product
detail panel on its LOG tab.

No new log viewer. The panel already polls every three seconds, colours the
lines, shows cost and the failure block, and has the stop button. A second
viewer beside it would be a second thing to fix each time the first changes.

A phase with no run yet — pending, planned, skipped — stays inert, because
there is nothing behind it to open.
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
TAG = "phaselogs"

OLD = '''  (e.phases || []).forEach(p => {
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
  });'''

NEW = '''  (e.phases || []).forEach(p => {
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

    /* A phase IS a pipeline run, so its log is the product detail panel's
       LOG tab — live, coloured, with the cost and the stop button already on
       it. The card just never pointed at it, and a phase sits in the product
       list under a slug nobody typed.

       Only a phase that HAS a run is clickable. pending / planned / skipped
       have no pipeline_runs row, so there would be nothing behind it. */
    if (["running", "complete", "failed"].includes(p.status) && p.slug) {
      row.style.cursor = "pointer";
      row.title = "Open the log for " + p.slug;
      const go = document.createElement("span");
      go.className = "mono";
      go.style.cssText = "font-size:9px;color:var(--accent);opacity:.75;letter-spacing:.12em;";
      go.textContent = "LOG \\u203a";
      row.appendChild(go);
      row.onmouseenter = () => row.style.background = "rgba(var(--accent-rgb),.07)";
      row.onmouseleave = () => row.style.background = "transparent";
      row.onclick = () => {
        /* finally, not then: the panel must land on the log even if the
           product fetch behind it fails. */
        Promise.resolve(openProductDetail(p.slug))
               .finally(() => switchProductTab("log"));
      };
    }
    wrap.appendChild(row);
  });'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not PAGE.is_file():
    sys.exit(f"NOTHING DONE — {PAGE} is not there")

src = PAGE.read_text(encoding="utf-8")
print("patch_phase_logs\n")

if "Open the log for" in src:
    sys.exit("NOTHING DONE — the phase rows already open their logs.")

# This calls two functions that must exist on the page. The epics card was
# added by a patch; the detail panel was not. Checked, not assumed — a click
# handler that calls a function nobody defined fails silently in a browser.
missing = [f for f in ("function openProductDetail", "function switchProductTab")
           if f not in src]
if missing:
    sys.exit(f"NOTHING DONE — this page has no {', '.join(missing)}. "
             f"The phase row would call a function that does not exist and "
             f"the click would do nothing at all.")
print("  ok  openProductDetail() and switchProductTab() are both on the page")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the phase-row block  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PAGE, PAGE.with_suffix(f".backup-{TAG}-{stamp}.html"))
PAGE.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {PAGE.name}, backup tagged {TAG}-{stamp}")

after = PAGE.read_text(encoding="utf-8")

# The page has no build step, so a syntax error here is a blank dashboard.
# node is used if it is there; if it is not, that is reported rather than
# quietly skipped — an unrun check that prints nothing is how the admin page
# shipped broken.
js = after[after.find("/* DUCORN-EPICS-JS-START */"):
           after.find("/* DUCORN-EPICS-JS-END */")]
if not js:
    sys.exit("⚠️  the epics JS markers are gone — restore the backup.")
node = shutil.which("node")
if node:
    r = subprocess.run([node, "--check"], input=js, capture_output=True,
                       text=True)
    if r.returncode != 0:
        sys.exit(f"⚠️  the epics JS does not parse — restore the backup:\n"
                 f"{r.stderr[-400:]}")
    print("verified: the epics JS parses (node --check).")
else:
    print("NOT verified: node is not on PATH, so the JS was not parsed. "
          "Reload the dashboard and check the console before trusting it.")

print("""
  Reload the dashboard (hard reload — the page is cached).

A phase row with a run now shows LOG › and opens the live log panel.
The failed phase 1 row should open on the research failure.
""")
