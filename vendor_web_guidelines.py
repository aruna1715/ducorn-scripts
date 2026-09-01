#!/usr/bin/env python3
"""
Vendor Vercel's Web Interface Guidelines into gstack/references/, pinned.

    python3 scripts/vendor_web_guidelines.py            # fetch the current tip
    python3 scripts/vendor_web_guidelines.py --pin <sha> # a specific commit
    python3 scripts/vendor_web_guidelines.py --check     # what is vendored now

── WHY VENDOR RATHER THAN FETCH PER RUN ─────────────────────────────────────

The published skill pulls these guidelines from GitHub on every invocation. For
a coding assistant that is a feature — the rules stay current. For a build
pipeline it is a defect: a QA verdict that can change between two runs of the
same code cannot be debugged, and a network blip becomes a failed build.

So the file is downloaded once, pinned to a commit, and committed to gstack
alongside its licence. Updating is a deliberate act with a diff you can read.

── WHY DOWNLOAD RATHER THAN TYPE IT OUT ─────────────────────────────────────

I could paraphrase these rules from memory. That would give you my
approximation of someone else's checklist, drifting quietly from the original,
with no way to tell what changed. Fetching the actual MIT-licensed file gives
you their words, a commit sha, and a diff on every update.

Source: github.com/vercel-labs/web-interface-guidelines (MIT). The LICENSE is
vendored beside the guidelines, because copying someone's work into your repo
without their licence is not vendoring, it is taking.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "vercel-labs/web-interface-guidelines"
WANT = {"AGENTS.md": "web-interface-guidelines.md",
        "LICENSE": "web-interface-guidelines.LICENSE"}

REFS = Path("/Users/ducorn/DC/gstack/references")
PIN = REFS / "web-interface-guidelines.pin.json"

# A downloaded file that does not contain these is not the guidelines — a
# rate-limit page, a 404 body or a redirect stub would otherwise be written to
# disk and fed to a reviewer as criteria.
EXPECT = ("focus", "contrast", "keyboard", "motion")


def get(url, accept=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": "ducorn-vendor",
        **({"Accept": accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def resolve_sha(ref="main"):
    data = json.loads(get(f"https://api.github.com/repos/{REPO}/commits/{ref}",
                          accept="application/vnd.github+json"))
    return data["sha"], (data.get("commit", {}).get("committer", {})
                         .get("date", "unknown"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", help="commit sha or ref to vendor (default: main)")
    ap.add_argument("--check", action="store_true",
                    help="report what is vendored and exit")
    args = ap.parse_args()

    if args.check:
        if not PIN.exists():
            print("Nothing vendored yet. Run this without --check.")
            return 1
        pin = json.loads(PIN.read_text())
        print(f"source:    {pin['repo']}")
        print(f"commit:    {pin['sha']}")
        print(f"committed: {pin['commit_date']}")
        print(f"vendored:  {pin['fetched_at']}")
        for name, dest in WANT.items():
            p = REFS / dest
            print(f"  {'ok  ' if p.is_file() else 'MISS'} {dest}"
                  + (f"  {p.stat().st_size:,} bytes" if p.is_file() else ""))
        return 0

    try:
        sha, commit_date = resolve_sha(args.pin or "main")
    except urllib.error.HTTPError as e:
        return f"GitHub said {e.code} resolving {args.pin or 'main'}: {e.reason}"
    except Exception as e:
        return f"could not reach GitHub: {type(e).__name__}: {e}"

    print(f"{REPO} @ {sha[:12]}  (committed {commit_date})")

    fetched = {}
    for name in WANT:
        url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{name}"
        try:
            fetched[name] = get(url)
        except Exception as e:
            return f"could not download {name}: {type(e).__name__}: {e}"
        print(f"  fetched {name}  {len(fetched[name]):,} bytes")

    body = fetched["AGENTS.md"].lower()
    missing = [w for w in EXPECT if w not in body]
    if missing:
        return (f"AGENTS.md does not look like the guidelines — no mention of "
                f"{missing}. Refusing to write it; a reviewer would be handed "
                f"criteria that are not criteria.")

    if "MIT" not in fetched["LICENSE"]:
        return ("the LICENSE file is not the MIT licence this was vendored "
                "under — stopping rather than guessing the terms.")

    REFS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    header = (
        f"<!--\n"
        f"VENDORED — do not edit by hand.\n"
        f"\n"
        f"  source:    https://github.com/{REPO}\n"
        f"  commit:    {sha}\n"
        f"  committed: {commit_date}\n"
        f"  vendored:  {now}\n"
        f"  licence:   MIT — see web-interface-guidelines.LICENSE\n"
        f"\n"
        f"Pinned on purpose. The upstream skill re-fetches these rules on every\n"
        f"run, which means a QA verdict can change without the code changing.\n"
        f"To update: python3 scripts/vendor_web_guidelines.py, then read the\n"
        f"diff before committing it.\n"
        f"-->\n\n")

    (REFS / WANT["AGENTS.md"]).write_text(header + fetched["AGENTS.md"],
                                          encoding="utf-8")
    (REFS / WANT["LICENSE"]).write_text(fetched["LICENSE"], encoding="utf-8")
    PIN.write_text(json.dumps({
        "repo": REPO, "sha": sha, "commit_date": commit_date,
        "fetched_at": now, "files": WANT,
    }, indent=2) + "\n", encoding="utf-8")

    guidelines = REFS / WANT["AGENTS.md"]
    text = guidelines.read_text()
    heads = [l.strip() for l in text.splitlines() if l.startswith("## ")]
    print(f"\nwrote {guidelines}  ({len(text):,} bytes)")
    print(f"      {REFS / WANT['LICENSE']}")
    print(f"      {PIN}")
    if heads:
        print("\nsections vendored:")
        for h in heads:
            print(f"  {h}")
    else:
        print("\n⚠️  no '## ' headings found — check the file before relying "
              "on it as review criteria")

    print("\nSkills 03 and 05 pick this up automatically once "
          "patch_skill_guidelines.py is applied.")
    print("Commit it:  python3 scripts/commit_all.py -m \"vendor web interface "
          "guidelines\" --apply")
    return 0


if __name__ == "__main__":
    r = main()
    if isinstance(r, str):
        sys.exit(f"❌ {r}")
    sys.exit(r)
