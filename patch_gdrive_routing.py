#!/usr/bin/env python3
"""
Replace gdrive_sync.py's FOLDER_MAP with derived routing.

Three changes:

  1. get_drive_folder() delegates to drive_routing.route(), so the sync and the
     one-time reorganiser cannot disagree about where a file belongs. Same
     reasoning as the writer fix importing its own check: one implementation,
     or the two drift and nobody notices until a founder is looking at a mess.

  2. Files that drive_routing excludes are skipped instead of uploaded. Today
     this catches the .backup-*.md files that repair_escaped_docs.py writes
     beside their sources — DOCS_DIR.glob("*.md") would otherwise have turned
     each backup into its own PDF in Drive on the next run.

  3. The environment column is read once per sync and passed in, so a run
     marked test goes to Archive rather than sitting among real products.

FOLDER_MAP is left in the file, commented, with a note. It is the record of
what the old routing did, and deleting it would make the next person wonder
why Drive looks the way it does.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

SYNC = Path("/Users/ducorn/DC/scripts/gdrive_sync.py")
ROUTING = Path("/Users/ducorn/DC/scripts/drive_routing.py")

if not ROUTING.exists():
    sys.exit(f"MISSING: {ROUTING} — copy drive_routing.py into scripts/ first.")

s = SYNC.read_text(encoding="utf-8")
if "drive_routing" in s:
    sys.exit("Already patched — drive_routing is imported.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. Nothing written.")
    s = s.replace(old, new, 1)
    applied.append(label)


# ── 1. import ────────────────────────────────────────────────────────────────
swap("import", "from fnmatch import fnmatch\n",
     "from fnmatch import fnmatch\n\n"
     "sys.path.insert(0, str(Path(__file__).parent))\n"
     "import drive_routing\n")

# ── 2. FOLDER_MAP retired, not deleted ───────────────────────────────────────
swap("retire map", "# ── FOLDER MAPPING ─────",
     '''# ── FOLDER MAPPING (RETIRED 2026-08-31) ───────────────────────────────────────
# FOLDER_MAP below is no longer consulted. It is kept because it explains the
# state of Drive: a hand-maintained list of P001-era filename patterns whose
# last entry was ("*", "DuCorn/Company"). Every product built after P001 matched
# nothing and fell into that catch-all, which is how ~35 PDFs — real products,
# throwaway runs and seven dashboard iterations — ended up in one flat folder
# without a single error ever being raised.
#
# Routing now derives from what the file is: see drive_routing.py.
# ── FOLDER MAPPING ─────''')

# ── 3. get_drive_folder delegates ────────────────────────────────────────────
swap("get_drive_folder", '''def get_drive_folder(filename):
    for pattern, folder in FOLDER_MAP:
        if fnmatch(filename, pattern):
            return folder
    return f"{DRIVE_ROOT}/Company"''',
     '''def get_drive_folder(filename, environments=None):
    """Delegates to drive_routing so sync and reorganise agree. Returns None
    for files that should not reach Drive at all."""
    folder, reason = drive_routing.route(filename, environments)
    return folder''')

# ── 4. Skip excluded files, and pass the environments through ────────────────
swap("load environments", '''    print(f"📚 Found {len(md_files)} markdown files\\n")''',
     '''    md_files = [p for p in md_files if not drive_routing.excluded(p.name)]
    print(f"📚 Found {len(md_files)} markdown files\\n")

    # Read once; a run marked test belongs in Archive, not among real products.
    environments = drive_routing.load_environments(
        os.environ.get("DUCORN_DATABASE_URL", "postgresql://localhost/ducorn"))''')

swap("route with env", '''        drive_folder = get_drive_folder(pdf_path.name)
        print(f"  📂 Target: {drive_folder}")''',
     '''        drive_folder, why = drive_routing.route(pdf_path.name, environments)
        if drive_folder is None:
            print(f"  ⏭️  skipped — {why}")
            skipped += 1
            continue
        print(f"  📂 Target: {drive_folder}   ({why})")
        if drive_folder.endswith("/Inbox"):
            # Deliberately loud. The old catch-all made this case invisible.
            print(f"  ⚠️  UNROUTED: {pdf_path.name} has no product slug and no "
                  f"company match — add a rule in drive_routing.py")''')

backup = SYNC.with_name(f"gdrive_sync.backup-routing-{datetime.now():%Y%m%d-%H%M%S}.py")
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
print("\nDry run the routing before syncing:")
print("  ~/DC/ducorn/.venv/bin/python ~/DC/scripts/reorganize_drive.py")
