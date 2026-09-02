#!/usr/bin/env python3
"""
Repair markdown documents that were written with JSON escape sequences intact.

Run this AFTER patch_writer_escapes.py — it imports the check from the tool so
the two can never disagree about what counts as broken.

Sweeps ducorn-products/docs/, repairs what is unambiguously broken, refuses to
touch anything ambiguous, and backs up every file it changes. As of the survey
on 31 Aug 2026 exactly one file qualifies (ducorn-run-history-launch.md), but
the sweep is worth having: it will find any that predate the fix, and it is the
cheapest way to prove that only one does.

Then delete the stale PDFs so gdrive_sync rebuilds them — the sync skips
conversion when the PDF is newer than the MD, so a repaired source with an old
PDF beside it would silently keep publishing the broken one.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/ducorn")
try:
    from tools.DuCornWriterTool import looks_escaped, unescape
except ImportError as e:
    sys.exit(f"Cannot import the writer tool ({e}).\n"
             f"Apply patch_writer_escapes.py first, and run this with the "
             f"venv python: ~/DC/ducorn/.venv/bin/python")

DOCS = Path("/Users/ducorn/DC/ducorn-products/docs")
PDFS = Path("/Users/ducorn/DC/ducorn-products/pdfs")
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"

repaired, refused = [], []

for md in sorted(DOCS.glob("*.md")):
    raw = md.read_text(encoding="utf-8")
    verdict = looks_escaped(raw)
    if verdict == "repair":
        fixed = unescape(raw)
        backup = md.with_name(f"{md.stem}.backup-escapes-{stamp}.md")
        shutil.copy2(md, backup)
        md.write_text(fixed, encoding="utf-8")
        print(f"repaired {md.name}: {raw.count(chr(10))} -> "
              f"{fixed.count(chr(10))} lines  (backup: {backup.name})")
        repaired.append(md)

        # The stale PDF must go, or convert_md_to_pdf() skips it on mtime.
        pdf = PDFS / f"{md.stem}.pdf"
        if pdf.exists():
            pdf.rename(pdf.with_name(f"{pdf.stem}.stale-{stamp}.pdf"))
            print(f"         set aside stale PDF: {pdf.name}")
    elif verdict == "refuse":
        print(f"AMBIGUOUS {md.name} — not touched. Inspect by hand.")
        refused.append(md)

print()
print(f"{len(repaired)} repaired, {len(refused)} left alone, "
      f"{len(list(DOCS.glob('*.md')))} scanned")
if repaired:
    print("\nNext: re-sync so the PDFs are rebuilt from the repaired sources:")
    print("  ~/DC/ducorn/.venv/bin/python ~/DC/scripts/gdrive_sync.py")
