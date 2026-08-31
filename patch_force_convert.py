#!/usr/bin/env python3
"""
Make --force actually reconvert, and stop counting skips as conversions.

THE BUG
-------
    python3 scripts/gdrive_sync.py --force --file docs/ducorn-cost-tracker-PRD.md
    ...
    📄 Converted: 1

and the PDF on disk was still the one from 18 August. Nothing was converted.

`force` reaches the sync LOOP, where it bypasses the sync-state check, but
convert_md_to_pdf has a second, independent guard:

    if pdf_path.exists() and pdf_path.stat().st_mtime > md_path.stat().st_mtime:
        return pdf_path

with no force parameter to switch it off. So a forced run re-uploads the stale
PDF, and `converted += 1` fires anyway because the counter increments on the
function returning a path, not on it having produced one.

That matters beyond tidiness: --force is what you reach for after changing the
PDF ENGINE, when the markdown has not changed and never will. It is the exact
case the mtime check gets wrong, and the success counter hid it.

THE FIX
-------
  * convert_md_to_pdf takes force and honours it
  * the skip path is distinguishable from the conversion path, so `converted`
    counts conversions and a new `reused` counter reports the rest
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

SYNC = Path("/Users/ducorn/DC/scripts/gdrive_sync.py")
s = SYNC.read_text(encoding="utf-8")

if "def convert_md_to_pdf(md_path: Path, force: bool = False)" in s:
    sys.exit("Already patched — convert_md_to_pdf takes force.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


swap("signature", "def convert_md_to_pdf(md_path: Path) -> Path:",
     "def convert_md_to_pdf(md_path: Path, force: bool = False) -> Path:")

swap("mtime guard",
     '''    # Skip if PDF is newer than MD
    if pdf_path.exists() and pdf_path.stat().st_mtime > md_path.stat().st_mtime:
        return pdf_path  # Already up to date, no new conversion needed''',
     '''    # Skip if the PDF is newer than the MD — unless forced. Without the
    # force check, `--force` after a PDF ENGINE change does nothing at all:
    # the markdown has not moved, so every document looks up to date and the
    # stale PDF is re-uploaded while the run reports a conversion.
    if (not force and pdf_path.exists()
            and pdf_path.stat().st_mtime > md_path.stat().st_mtime):
        print(f"  ⏭️  PDF is newer than the markdown — reusing "
              f"{pdf_path.name} (pass --force to rebuild)")
        return REUSED''')

swap("sentinel", '''PDFS_DIR        = Path("/Users/ducorn/DC/ducorn-products/pdfs")''',
     '''PDFS_DIR        = Path("/Users/ducorn/DC/ducorn-products/pdfs")

# Returned when the existing PDF was up to date and nothing was built. None
# already means "conversion failed" and has to keep meaning that, so a skip
# needs its own value rather than sharing one of the two the caller can
# already see.
REUSED = object()''')

swap("call site", '''        pdf_path = convert_md_to_pdf(md_path)
        if not pdf_path:
            errors += 1
            continue
        converted += 1''',
     '''        pdf_path = convert_md_to_pdf(md_path, force=force)
        if pdf_path is REUSED:
            pdf_path = PDFS_DIR / md_path.with_suffix(".pdf").name
            reused += 1
        elif not pdf_path:
            errors += 1
            continue
        else:
            converted += 1''')

swap("counter init", "    converted = uploaded = skipped = errors = 0",
     "    converted = uploaded = skipped = errors = reused = 0")

swap("summary", '''    print(f"  📄 Converted: {converted}")''',
     '''    print(f"  📄 Converted: {converted}")
    print(f"  ♻️  Reused:    {reused}   (PDF already newer than the markdown)")''')

backup = SYNC.with_name(f"gdrive_sync.backup-force-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(SYNC, backup)
SYNC.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, SYNC)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup}")
