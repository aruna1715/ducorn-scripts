#!/usr/bin/env python3
"""
A RECOVER button, and advice that is computed rather than assumed.

    cd ~/DC && python3 scripts/patch_recovery_ui.py            show
    cd ~/DC && python3 scripts/patch_recovery_ui.py --apply    do it

Apply patch_recovery_api.py first.

── WHAT IT REPLACES ─────────────────────────────────────────────────────────

The failure panel ends with a fixed sentence:

    "The builder is now given this report automatically. Press RESUME to
     rebuild with it in hand. If it fails the same way twice, it needs an
     engineer."

That is true when the failing skill is the first thing a resume would re-run,
and wrong otherwise. Phase 1 of the admin rebuild failed at QA with the build
and the code review both cached as passed — so RESUME re-ran only QA, against
files nothing had changed, and failed identically. Following the dashboard's
own advice exactly produced an infinite loop.

A sentence written once cannot know which skills are cached. So it is
replaced by the plan the API computes for THIS run, and a button that carries
it out.

── THE BUTTON ───────────────────────────────────────────────────────────────

RECOVER drops the cached skills that must genuinely re-run — and only those,
never the failure record itself, which is what the retry is told about. It
does not resume: invalidating is free and resuming spends money, so the
second one stays a separate press.

After it succeeds the panel says which skills were dropped and that RESUME is
now the next step, so the sequence is visible rather than remembered.
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
TAG = "recoveryui"

OLD = '''    // The operator's next move, said plainly. A QA rejection is now carried
    // into the next build's prompt, so RESUME is usually the whole answer.
    + '<div class="mono" style="font-size:8px;color:var(--amber);margin-top:10px;'
    + 'line-height:1.6;">The builder is now given this report automatically. '
    + 'Press RESUME to rebuild with it in hand. If it fails the same way twice, '
    + 'it needs an engineer.</div>'
    + '</div>';
}'''

NEW = '''    // The operator's next move, COMPUTED for this run.
    //
    // This used to be a fixed sentence saying "press RESUME to rebuild with
    // it in hand". That is right only when the failing skill is the first
    // thing a resume re-runs. When the build and the review are cached as
    // passed — which is exactly what a QA rejection looks like — RESUME
    // re-runs only QA, against unchanged files, forever. A sentence written
    // once cannot know what is cached; the API can.
    + '<div id="recoveryBox" class="mono" style="font-size:9px;margin-top:10px;'
    + 'color:var(--muted);">Working out what to do…</div>'
    + '</div>';

  loadRecovery(slug);
}


async function loadRecovery(slug) {
  const box = document.getElementById("recoveryBox");
  if (!box) return;
  let p;
  try {
    const res = await fetch(API + "/pipeline/recovery/" + encodeURIComponent(slug),
                            {headers: HDR});
    p = await res.json();
  } catch (e) {
    box.textContent = "Could not work out a recovery plan — read the log.";
    return;
  }
  if (!p || p.error || p.state !== "failed") {
    box.textContent = (p && (p.what || p.error))
      || "No recovery plan for this run.";
    return;
  }

  box.innerHTML = "";
  const what = document.createElement("div");
  what.style.cssText = "color:var(--amber);line-height:1.6;margin-bottom:8px;";
  what.textContent = p.what || "";              /* never innerHTML */
  box.appendChild(what);

  if (!(p.invalidate || []).length) {
    const only = document.createElement("div");
    only.style.cssText = "color:var(--muted);line-height:1.6;";
    only.textContent = "Nothing is cached in the way — RESUME re-runs it.";
    box.appendChild(only);
    return;
  }

  const btn = document.createElement("button");
  btn.className = "mono";
  btn.style.cssText = "cursor:pointer;font-size:9px;letter-spacing:.14em;"
    + "padding:6px 14px;background:rgba(var(--amber-rgb,224,168,94),.14);"
    + "border:1px solid rgba(var(--amber-rgb,224,168,94),.4);border-radius:3px;"
    + "color:var(--amber);";
  btn.textContent = "RECOVER — RE-RUN SKILLS " + p.invalidate.join(", ");
  btn.onclick = () => runRecovery(slug, p, btn);
  box.appendChild(btn);

  const note = document.createElement("div");
  note.style.cssText = "color:var(--muted);margin-top:6px;line-height:1.6;";
  /* Say what it costs. This one is free; the next press is not. */
  note.textContent = "This only clears cached steps — nothing runs and "
    + "nothing is spent until you press RESUME.";
  box.appendChild(note);
}


async function runRecovery(slug, p, btn) {
  if (!confirm("Clear the cached results for skills " + p.invalidate.join(", ")
             + " of " + slug + "?\\n\\nThey will run again on the next RESUME. "
             + "The failure record is kept — it is what the retry is told "
             + "about.\\n\\nNothing runs and nothing is spent until you press "
             + "RESUME."))
    return;
  btn.disabled = true;
  btn.textContent = "CLEARING…";
  try {
    const res = await fetch(API + "/pipeline/recovery/" + encodeURIComponent(slug),
                            {method: "POST", headers: HDR});
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || ("HTTP " + res.status));
    const done = document.createElement("div");
    done.className = "mono";
    done.style.cssText = "color:var(--accent);margin-top:8px;line-height:1.6;";
    done.textContent = "Cleared: " + ((d.dropped || []).join(", ") || "nothing")
      + ". Press RESUME to rebuild — that is the step that spends money.";
    btn.replaceWith(done);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "RECOVER — RE-RUN SKILLS " + p.invalidate.join(", ");
    alert("Could not clear: " + err.message);
  }
}'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (PAGE, API):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

print("patch_recovery_ui\n")

if "/pipeline/recovery/" not in API.read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — apply patch_recovery_api.py first. The button "
             "would call an endpoint that does not exist, and it would fail "
             "only when someone pressed it.")
print("  ok  the recovery endpoints exist in the API")

src = PAGE.read_text(encoding="utf-8")
if "function loadRecovery" in src:
    sys.exit("NOTHING DONE — the recovery panel is already there.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the fixed advice block  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# loadProductFailure must receive the slug, or loadRecovery(slug) is called
# with an undefined name and the panel silently says nothing.
if "async function loadProductFailure(slug, failed)" not in src:
    sys.exit("NOTHING DONE — loadProductFailure does not take `slug`, so the "
             "new call would pass undefined. Read that function first.")
print("  ok  loadProductFailure(slug, failed) has the slug in scope")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(PAGE, PAGE.with_suffix(f".backup-{TAG}-{stamp}.html"))
PAGE.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {PAGE.name}, backup tagged {TAG}-{stamp}")

after = PAGE.read_text(encoding="utf-8")
node = shutil.which("node")
if node:
    # Just the functions this patch added, extracted by their own braces.
    i = after.find("async function loadRecovery(slug)")
    j = after.find("// ── System health")
    frag = after[i:j] if i >= 0 and j > i else ""
    if not frag:
        sys.exit("⚠️  could not locate the new functions — restore the backup.")
    r = subprocess.run([node, "--check"], input=frag, capture_output=True,
                       text=True)
    if r.returncode != 0:
        sys.exit(f"⚠️  the recovery JS does not parse — restore the backup:\n"
                 f"{r.stderr[-400:]}")
    print("verified: the recovery JS parses (node --check).")
else:
    print("NOT verified: node is not on PATH, so the JS was not parsed. "
          "Check the browser console after reloading.")

if "The builder is now given this report automatically" in after:
    sys.exit("⚠️  the old fixed advice is still on the page — restore the "
             "backup.")
if "innerHTML = p." in after or "innerHTML = d." in after:
    sys.exit("⚠️  API text is being written with innerHTML — restore the "
             "backup.")
print("          the fixed advice is gone and API text is set with "
      "textContent.")

print("""
  Hard-reload the dashboard, open the failed run, look at WHY IT FAILED.

Under the report you should now see what to do for THIS run, and a button
reading RECOVER — RE-RUN SKILLS 04, 05. Pressing it clears those two and
nothing else; RESUME is still a separate press, because that is the one that
spends money.
""")
