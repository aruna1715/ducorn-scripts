#!/usr/bin/env python3
"""
Put the health report where the operator already is.

── WHY ──────────────────────────────────────────────────────────────────────

Fifty-one checks that answer "is this machine healthy", and the only way to
read them is a terminal. The person who most needs them — an operator with no
shell, working through the dashboard, which is the only interface you have said
you want humans using — cannot.

This adds a SYSTEM HEALTH panel to the intelligence column: the last report,
its age, every failure with the exact command that fixes it, and a RUN button.

── ON "ONE PANEL", WHICH I SAID AND AM NOW QUALIFYING ───────────────────────

I said I would combine system health and pipeline-failure detail into one
panel. Building it, that is wrong, and it is worth saying why rather than
quietly doing something else.

System health is about the MACHINE and belongs in the global column. A
pipeline's failure detail is about ONE PRODUCT — which QA rejected it, what the
report said — and belongs beside that product, in the detail view where its log
and docs already are. Putting per-product detail in a global panel means the
panel has to choose a product on the operator's behalf, and it will choose
wrong whenever more than one thing has failed.

So: this patch is the health panel. The failure block goes into the product
overview tab, next to the pipeline status it explains, in the next patch. Two
places because they answer questions asked in two places — which is not the
same as the two-panels-because-nobody-decided that I was arguing against.

── THE RUN BUTTON DOES NOT BLOCK ────────────────────────────────────────────

RUN posts to /health/run and returns immediately; the panel polls every three
seconds while a run is in flight and stops when it finishes. The last report
stays on screen throughout, labelled with its age. A stale answer you can read
beats a spinner you cannot.
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PAGE = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
s = PAGE.read_text(encoding="utf-8")

if "panel-health" in s:
    sys.exit("Already patched — the dashboard shows system health.")
for need in ('<div class="intel-sec" id="panel-kpi">', "async function pollAll() {"):
    if s.count(need) != 1:
        sys.exit(f"ANCHOR MISS: {need!r} found {s.count(need)} times. "
                 f"NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


PANEL = '''      <!-- System health -->
      <div class="intel-sec" id="panel-health">
        <section class="card" style="padding:18px 20px;">
          <div class="card-scan"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:var(--accent);">SYSTEM HEALTH</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="healthAge" class="mono" style="font-size:8px;letter-spacing:.14em;color:var(--muted);">—</span>
              <button id="healthRunBtn" onclick="runHealth();event.stopPropagation()" class="mono"
                style="cursor:pointer;padding:3px 8px;font-size:8px;letter-spacing:.14em;
                       background:rgba(var(--accent-rgb),.15);border:1px solid rgba(var(--accent-rgb),.4);
                       border-radius:2px;color:var(--accent);">RUN</button>
              <span class="collapse-btn" id="btn-sec-health" onclick="toggleSection('sec-health');event.stopPropagation()">&#9662;</span>
            </div>
          </div>
          <div id="sec-health" class="section-body">
            <div id="healthSummary" style="margin-bottom:10px;"></div>
            <div id="healthFailures" style="display:flex;flex-direction:column;gap:8px;"></div>
            <div id="healthSections" style="display:grid;grid-template-columns:repeat(2,1fr);gap:3px 20px;margin-top:12px;padding-top:10px;border-top:1px solid rgba(var(--muted-rgb),.15);"></div>
          </div>
        </section>
      </div>

'''

SCRIPT = '''
// ── System health ────────────────────────────────────────────────────────────
// Reads the report the API caches. Never triggers the checks by itself: they
// take 15-30s and a panel that runs them on every poll would keep a browser
// launching in the background forever.
let _healthPoll = null;

function _healthAge(sec) {
  if (sec === null || sec === undefined) return "never run";
  if (sec < 60) return "just now";
  if (sec < 3600) return Math.floor(sec/60) + "m ago";
  if (sec < 86400) return Math.floor(sec/3600) + "h ago";
  return Math.floor(sec/86400) + "d ago";
}

function _esc(t) {
  return String(t == null ? "" : t)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}

function renderHealth(d) {
  const ageEl = document.getElementById("healthAge");
  const sumEl = document.getElementById("healthSummary");
  const failEl = document.getElementById("healthFailures");
  const secEl = document.getElementById("healthSections");
  if (!sumEl) return;

  if (ageEl) ageEl.textContent = d.running ? "RUNNING…" : _healthAge(d.age_seconds);

  const btn = document.getElementById("healthRunBtn");
  if (btn) { btn.textContent = d.running ? "RUNNING" : "RUN"; btn.disabled = !!d.running; }

  if (d.error) {
    sumEl.innerHTML = '<span class="mono" style="font-size:9px;color:var(--red);">'
      + _esc(d.error) + '</span>';
    return;
  }
  const r = d.report;
  if (!r) {
    sumEl.innerHTML = '<span class="mono" style="font-size:9px;letter-spacing:.14em;color:var(--muted);">'
      + 'NO REPORT YET — PRESS RUN</span>';
    failEl.innerHTML = ""; secEl.innerHTML = "";
    return;
  }

  const healthy = r.failed === 0;
  const colour = healthy ? "var(--green)" : "var(--red)";
  sumEl.innerHTML =
    '<div style="display:flex;align-items:baseline;gap:8px;">'
    + '<span class="mono" style="font-size:22px;color:' + colour + ';">'
    + (healthy ? r.total : r.failed) + '</span>'
    + '<span class="mono" style="font-size:9px;letter-spacing:.16em;color:var(--muted);">'
    + (healthy ? 'CHECKS PASSING' : 'OF ' + r.total + ' CHECKS FAILING') + '</span></div>';

  // Every failure carries the command that fixes it. That is the whole point:
  // an operator with no shell still knows exactly what to ask for.
  const bad = (r.checks || []).filter(function(c) { return !c.ok; });
  failEl.innerHTML = bad.map(function(c) {
    return '<div style="padding:8px 10px;background:rgba(var(--red-rgb),.06);'
      + 'border-left:2px solid rgba(var(--red-rgb),.5);border-radius:2px;">'
      + '<div class="mono" style="font-size:9px;letter-spacing:.1em;color:var(--red);">'
      + _esc(c.name) + '</div>'
      + (c.detail ? '<div class="mono" style="font-size:8px;color:var(--muted);margin-top:3px;">'
          + _esc(c.detail) + '</div>' : '')
      + (c.fix ? '<div class="mono" style="font-size:8px;color:var(--amber);margin-top:4px;'
          + 'word-break:break-all;">$ ' + _esc(c.fix) + '</div>' : '')
      + '</div>';
  }).join("");

  const bySec = {};
  (r.checks || []).forEach(function(c) {
    if (!bySec[c.section]) bySec[c.section] = {ok:0, total:0};
    bySec[c.section].total++;
    if (c.ok) bySec[c.section].ok++;
  });
  secEl.innerHTML = Object.keys(bySec).sort().map(function(k) {
    const v = bySec[k];
    const good = v.ok === v.total;
    return '<div class="mono" style="font-size:8px;letter-spacing:.1em;display:flex;'
      + 'justify-content:space-between;padding:2px 0;color:var(--muted);">'
      + '<span>' + _esc(k.toUpperCase()) + '</span>'
      + '<span style="color:' + (good ? 'var(--green)' : 'var(--red)') + ';">'
      + v.ok + '/' + v.total + '</span></div>';
  }).join("");
}

async function loadHealth() {
  try {
    const res = await fetch(API + "/health/report", {headers: HDR});
    const d = await res.json();
    renderHealth(d);
    if (d.running && !_healthPoll) {
      _healthPoll = setInterval(loadHealth, 3000);
    } else if (!d.running && _healthPoll) {
      clearInterval(_healthPoll); _healthPoll = null;
    }
  } catch (e) {
    const sumEl = document.getElementById("healthSummary");
    if (sumEl) sumEl.innerHTML =
      '<span class="mono" style="font-size:9px;color:var(--red);">API unreachable</span>';
  }
}

async function runHealth() {
  const btn = document.getElementById("healthRunBtn");
  if (btn) { btn.textContent = "RUNNING"; btn.disabled = true; }
  try {
    await fetch(API + "/health/run", {method: "POST", headers: HDR});
  } catch (e) { /* loadHealth surfaces it */ }
  setTimeout(loadHealth, 800);
}

'''

s = swap("panel", s, '''      <!-- Approvals -->''', PANEL + '''      <!-- Approvals -->''')
s = swap("script", s, "async function pollAll() {", SCRIPT + "async function pollAll() {")
s = swap("poll", s, '''async function pollAll() {
  // Update budget display''',
         '''async function pollAll() {
  // Cheap: reads the cached report, never runs the checks.
  loadHealth();

  // Update budget display''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PAGE.with_name(f"index.backup-health-{stamp}.html")
shutil.copy2(PAGE, backup)
PAGE.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, PAGE)
    sys.exit(f"{msg} — reverted from {backup.name}")


# ── the JavaScript must actually parse ───────────────────────────────────────
tmp = Path("/tmp/_health_panel_check.js")
tmp.write_text("const API='';const HDR={};" + SCRIPT, encoding="utf-8")
node = shutil.which("node")
if node:
    r = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"the panel's JavaScript does not parse:\n{r.stderr[:600]}")
    print("javascript: parses (node --check)")
else:
    print("javascript: node not found — could not parse-check. Install node or "
          "verify in the browser console.")

# ── the markup must be balanced ──────────────────────────────────────────────
from html.parser import HTMLParser


class Balance(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.bad = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.bad.append(tag)


p = Balance()
p.feed(PANEL)
if p.bad or p.stack:
    die(f"the panel markup is unbalanced: unclosed={p.stack}, stray={p.bad}")
print(f"markup: balanced ({PANEL.count('<div')} divs, all closed)")

# the ids the script reaches for must exist in the markup it was written beside
ids = set(re.findall(r'id="([\w-]+)"', PANEL))
needed = set(re.findall(r'getElementById\("([\w-]+)"\)', SCRIPT))
missing = needed - ids
if missing:
    die(f"the script reads ids the panel does not define: {sorted(missing)}")
print(f"wiring: every getElementById target exists ({len(needed)} of them)")

unused = ids - needed - {"panel-health", "btn-sec-health", "sec-health"}
if unused:
    print(f"        (declared but unread: {sorted(unused)})")

# and the page as a whole must still be the page
after = PAGE.read_text(encoding="utf-8")
if len(after) - len(backup.read_text(encoding="utf-8")) != len(PANEL) + len(SCRIPT) + len(
        "  // Cheap: reads the cached report, never runs the checks.\n  loadHealth();\n\n"):
    print("        (size delta differs from the inserted text — check the diff)")
for must in ("panel-health", "function renderHealth", "loadHealth();"):
    if must not in after:
        die(f"{must!r} is not in the written page")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("The dashboard is served as a static file — just reload the page.")
print("The panel appears under the KPI cards in the INTELLIGENCE column.")
print()
print("First load shows NO REPORT YET — press RUN. It takes 15-30s; the button")
print("says RUNNING and the panel polls until it finishes.")
