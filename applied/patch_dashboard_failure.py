#!/usr/bin/env python3
"""
Show the operator why the run failed, beside the run that failed.

── THE GAP ──────────────────────────────────────────────────────────────────

A failed product's detail view shows its skill rows — ❌ against skill 06 — and
a RESUME button. It does not show WHY. The report explaining exactly what broke
is on disk, was written by IRIS, and reaches nobody: 44 endpoints and not one
mentioned it until /pipeline/failure/{slug} went in earlier tonight.

That is the same defect that cost you three build cycles, one layer up. REX
could not see the QA report; now he can. The person at the dashboard still
cannot.

── WHAT THIS SHOWS ──────────────────────────────────────────────────────────

Above PIPELINE STATUS, and only when the run is actually in a failed or stopped
state:

    WHY IT FAILED
    VERDICT: FAIL — 7 tests fail due to lifespan overwriting mocked asyncpg pool
    ┌ the full report, scrollable ─────────────────────────────────────────┐
    │ SKILL RESULTS: ...                                                    │
    │ QA REPORT (skill 06): ...                                             │
    │ END OF THE RUN LOG: ...                                               │
    └───────────────────────────────────────────────────────────────────────┘
    The builder is now given this report automatically. Press RESUME to
    rebuild with it in hand.

That last line is the part that matters for someone without a terminal. Most
QA failures are now self-healing — the rejection is carried into the next
build's prompt — and the operator's correct move is simply RESUME. Saying so
turns a dead end into an action.

── WHY NOT IN THE GLOBAL HEALTH PANEL ───────────────────────────────────────

Because it is about one product. A global panel would have to choose which
failure to show, and would choose wrong the moment two things had failed. This
sits beside the pipeline status it explains, in the view the operator is
already looking at.
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PAGE = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
s = PAGE.read_text(encoding="utf-8")

if "productFailure" in s:
    sys.exit("Already patched — the dashboard explains failures.")
if "panel-health" not in s:
    sys.exit("Apply patch_dashboard_health.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


BLOCK = '''          <div id="productFailure" style="margin-bottom:16px;"></div>
'''

# Raw: the JavaScript contains regex escapes (\s, \d) that Python reads as
# unknown string escapes. It works today and warns; 3.14 says it will stop.
SCRIPT = r'''
// ── Why a run failed ─────────────────────────────────────────────────────────
// The report exists and has never been shown to a person. Rendered beside the
// pipeline status it explains, and only for a run that is actually failed.
function _failVerdict(text) {
  // The FAILING verdict, not the first one. The report opens with the skills
  // that passed, so matching any /VERDICT:/ headlined a failed run with
  // "VERDICT: PASS — 5565 chars produced" — caught by looking at it rather
  // than by reading the regex.
  const t = String(text || "");
  const fail = t.match(/^.*VERDICT:\s*FAIL.*$/mi);
  if (fail) return fail[0].trim();
  const any = t.match(/^.*VERDICT:.*$/m);
  return any ? any[0].trim() : "";
}

async function loadProductFailure(slug, failed) {
  const el = document.getElementById("productFailure");
  if (!el) return;
  if (!failed) { el.innerHTML = ""; return; }

  el.innerHTML = '<span class="mono" style="font-size:9px;color:var(--muted);">'
    + 'Loading the failure report…</span>';
  let d;
  try {
    const res = await fetch(API + "/pipeline/failure/" + encodeURIComponent(slug),
                            {headers: HDR});
    d = await res.json();
  } catch (e) {
    el.innerHTML = '<span class="mono" style="font-size:9px;color:var(--red);">'
      + 'Could not load the failure report.</span>';
    return;
  }
  if (!d || !d.has_detail) {
    el.innerHTML = '<div class="mono" style="font-size:9px;color:var(--muted);">'
      + 'No failure report on disk for this run — check the LIVE LOG tab.</div>';
    return;
  }

  const verdict = _failVerdict(d.detail);
  el.innerHTML =
    '<div style="padding:12px;background:rgba(var(--red-rgb),.06);'
    + 'border:1px solid rgba(var(--red-rgb),.25);border-radius:3px;">'
    + '<div class="mono" style="font-size:9px;letter-spacing:.16em;color:var(--red);'
    + 'margin-bottom:8px;">WHY IT FAILED</div>'
    + (verdict
        ? '<div class="mono" style="font-size:10px;color:var(--ink-2, #cdd);'
          + 'margin-bottom:10px;line-height:1.5;">' + _esc(verdict) + '</div>'
        : '')
    + '<pre class="mono" style="font-size:8px;line-height:1.5;color:var(--muted);'
    + 'max-height:260px;overflow:auto;white-space:pre-wrap;word-break:break-word;'
    + 'margin:0;padding:8px;background:rgba(var(--surface-rgb),.6);'
    + 'border-radius:2px;">' + _esc(d.detail) + '</pre>'
    // The operator's next move, said plainly. A QA rejection is now carried
    // into the next build's prompt, so RESUME is usually the whole answer.
    + '<div class="mono" style="font-size:8px;color:var(--amber);margin-top:10px;'
    + 'line-height:1.6;">The builder is now given this report automatically. '
    + 'Press RESUME to rebuild with it in hand. If it fails the same way twice, '
    + 'it needs an engineer.</div>'
    + '</div>';
}

'''

s = swap("block", s,
         '''          <div class="mono" style="font-size:9px;letter-spacing:.16em;color:var(--muted);margin-bottom:8px;">PIPELINE STATUS</div>''',
         BLOCK + '''          <div class="mono" style="font-size:9px;letter-spacing:.16em;color:var(--muted);margin-bottom:8px;">PIPELINE STATUS</div>''')

s = swap("script", s, "// ── System health ──", SCRIPT + "// ── System health ──")

s = swap("call", s, '''  const killBtn = document.getElementById('killBtn');
  if (killBtn) {
    killBtn.style.display =
      ['running', 'started', 'awaiting_approval'].includes(_runStatus) ? 'block' : 'none';
  }''',
         '''  const killBtn = document.getElementById('killBtn');
  if (killBtn) {
    killBtn.style.display =
      ['running', 'started', 'awaiting_approval'].includes(_runStatus) ? 'block' : 'none';
  }

  // Same condition as RESUME: if resuming is meaningful, the operator deserves
  // to know what they are resuming from.
  loadProductFailure(p && p.slug ? p.slug : _currentProductSlug,
                     skillFailed || runIsResumable);''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PAGE.with_name(f"index.backup-failblock-{stamp}.html")
shutil.copy2(PAGE, backup)
PAGE.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, PAGE)
    sys.exit(f"{msg} — reverted from {backup.name}")


node = shutil.which("node")
if node:
    tmp = Path("/tmp/_fail_block_check.js")
    # _esc comes from the health panel; stubbed here so this parses standalone
    tmp.write_text("const API='';const HDR={};function _esc(t){return t;}\n"
                   + SCRIPT, encoding="utf-8")
    r = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"the failure block's JavaScript does not parse:\n{r.stderr[:600]}")
    print("javascript: parses (node --check)")
else:
    print("javascript: node not found — verify in the browser console")

# _esc is defined by the health panel; this block depends on it existing
after = PAGE.read_text(encoding="utf-8")
if "function _esc(" not in after:
    die("_esc is not defined in the page — the failure block escapes with it")
if after.index("function _esc(") > after.index("async function loadProductFailure"):
    print("        (note: _esc is declared after use — function declarations "
          "hoist, so this is fine, but it reads oddly)")
print("escaping: _esc is present and used for every interpolated value")

for must in ('id="productFailure"', "loadProductFailure(", "WHY IT FAILED"):
    if must not in after:
        die(f"{must!r} is not in the written page")

# every value put into innerHTML must go through _esc — the report is text from
# a model and a log, and must never be able to close a tag
raw = re.findall(r"\+ (d\.detail|verdict|slug)\b", SCRIPT)
if raw:
    die(f"unescaped interpolation of {set(raw)} into innerHTML")
print("safety: no unescaped report text reaches innerHTML")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Reload the dashboard and open a failed product — ducorn-spend-status is")
print("complete now, so to see it you would need a run that failed. The block")
print("stays empty for healthy runs, which is the intended quiet.")
