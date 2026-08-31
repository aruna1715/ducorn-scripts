"""
DuCorn Google Drive Sync
========================
Converts MD files to PDF and uploads to organized Google Drive folders.
Skips files that haven't changed since last sync.

Usage:
  python3.12 gdrive_sync.py              # Sync only changed files
  python3.12 gdrive_sync.py --force      # Force sync all files
  python3.12 gdrive_sync.py --file <path> # Sync specific MD file
"""

import os
import sys
import json
import time
import glob
import argparse
import requests
from pathlib import Path
from datetime import datetime
from fnmatch import fnmatch

sys.path.insert(0, str(Path(__file__).parent))
import drive_routing

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── CONFIG ────────────────────────────────────────────────────────────────────
DOCS_DIR        = Path("/Users/ducorn/DC/ducorn-products/docs")
PDFS_DIR        = Path("/Users/ducorn/DC/ducorn-products/pdfs")

# Returned when the existing PDF was up to date and nothing was built. None
# already means "conversion failed" and has to keep meaning that, so a skip
# needs its own value rather than sharing one of the two the caller can
# already see.
REUSED = object()
DATA_DIR        = Path("/Users/ducorn/DC/ducorn-products/data")
CREDS_FILE      = "/Users/ducorn/DC/shared/gdrive-credentials.json"
TOKEN_FILE      = "/Users/ducorn/DC/shared/gdrive-token.json"
SYNC_STATE_FILE = "/Users/ducorn/DC/shared/gdrive_sync_state.json"
PDF_API_URL     = "http://localhost:8001/v1/convert"
PDF_API_KEY     = os.environ.get("PDF_API_KEY", "dk_pro_test_key_002")
DRIVE_ROOT      = "DuCorn"

# ── FOLDER MAPPING (RETIRED 2026-08-31) ───────────────────────────────────────
# FOLDER_MAP below is no longer consulted. It is kept because it explains the
# state of Drive: a hand-maintained list of P001-era filename patterns whose
# last entry was ("*", "DuCorn/Company"). Every product built after P001 matched
# nothing and fell into that catch-all, which is how ~35 PDFs — real products,
# throwaway runs and seven dashboard iterations — ended up in one flat folder
# without a single error ever being raised.
#
# Routing now derives from what the file is: see drive_routing.py.
# ── FOLDER MAPPING ────────────────────────────────────────────────────────────
FOLDER_MAP = [
    # Weekly reports
    ("Week*-Completion-Report*",        f"{DRIVE_ROOT}/Company/Weekly Reports"),
    # Board documents
    ("ATLAS-PRD-BB-*",                  f"{DRIVE_ROOT}/Company/Board Documents"),
    ("ATLAS-PRD-001-Board-Summary*",    f"{DRIVE_ROOT}/Company/Board Documents"),
    # Technical reference
    ("DuCorn-Technical-Reference*",     f"{DRIVE_ROOT}/Company/Technical Reference"),
    # P001 — Autonomy Console
    ("P001-autonomy-console*",          f"{DRIVE_ROOT}/Products/P001 - Autonomy Console"),
    ("atlas-dashboard-landing-page*",   f"{DRIVE_ROOT}/Products/P001 - Autonomy Console"),
    ("ATLAS-PRD-001*",                  f"{DRIVE_ROOT}/Products/P001 - Autonomy Console"),
    # P002+ — future products follow same pattern
    ("P002-*",                          f"{DRIVE_ROOT}/Products/P002 - TBD"),
    # Activity API (internal tool, not a product)
    ("ducorn-activity-api*",            f"{DRIVE_ROOT}/Company/Technical Reference"),
    # PDF Export Tool (internal tool)
    ("ducorn-pdf-export-tool*",         f"{DRIVE_ROOT}/Company/Technical Reference"),
    # SaaS Onboarding
    ("saas-founder-onboarding*",        f"{DRIVE_ROOT}/Products/P001 - Autonomy Console"),
    # Marketing
    ("atlas-marketing*",                f"{DRIVE_ROOT}/Marketing/P001 - Autonomy Console"),
    # Research
    ("ducorn-digest-improvements*",     f"{DRIVE_ROOT}/Research"),
    ("voice-ai-performance-test*",      f"{DRIVE_ROOT}/Research"),
    ("ducorn-gtm*",                     f"{DRIVE_ROOT}/Research/GTM"),
    # Fallback
    ("*",                               f"{DRIVE_ROOT}/Company"),
]

# ── SYNC STATE ────────────────────────────────────────────────────────────────
def load_sync_state():
    """Load last sync timestamps per file."""
    if os.path.exists(SYNC_STATE_FILE):
        with open(SYNC_STATE_FILE) as f:
            return json.load(f)
    return {}

def save_sync_state(state):
    """Save sync timestamps."""
    with open(SYNC_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ── GOOGLE DRIVE AUTH ─────────────────────────────────────────────────────────
def get_drive_service():
    creds = Credentials.from_authorized_user_file(
        TOKEN_FILE,
        scopes=['https://www.googleapis.com/auth/drive']
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

# ── FOLDER MANAGEMENT ─────────────────────────────────────────────────────────
_folder_cache = {}

def get_or_create_folder(service, name, parent_id=None):
    cache_key = f"{parent_id}:{name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if files:
        folder_id = files[0]['id']
    else:
        metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id:
            metadata['parents'] = [parent_id]
        folder = service.files().create(body=metadata, fields='id').execute()
        folder_id = folder['id']
        print(f"  📁 Created folder: {name}")

    _folder_cache[cache_key] = folder_id
    return folder_id

def get_folder_id_for_path(service, path):
    parts = path.strip('/').split('/')
    parent_id = None
    for part in parts:
        parent_id = get_or_create_folder(service, part, parent_id)
    return parent_id

def get_drive_folder(filename, environments=None):
    """Delegates to drive_routing so sync and reorganise agree. Returns None
    for files that should not reach Drive at all."""
    folder, reason = drive_routing.route(filename, environments)
    return folder

# ── PDF CONVERSION ────────────────────────────────────────────────────────────
def convert_md_to_pdf(md_path: Path, force: bool = False) -> Path:
    pdf_path = PDFS_DIR / md_path.with_suffix('.pdf').name

    # Skip if the PDF is newer than the MD — unless forced. Without the
    # force check, `--force` after a PDF ENGINE change does nothing at all:
    # the markdown has not moved, so every document looks up to date and the
    # stale PDF is re-uploaded while the run reports a conversion.
    if (not force and pdf_path.exists()
            and pdf_path.stat().st_mtime > md_path.stat().st_mtime):
        print(f"  ⏭️  PDF is newer than the markdown — reusing "
              f"{pdf_path.name} (pass --force to rebuild)")
        return REUSED

    print(f"  📄 Converting: {md_path.name}")
    content = md_path.read_text(encoding='utf-8')

    try:
        resp = requests.post(
            PDF_API_URL,
            headers={"Content-Type": "application/json", "X-API-Key": PDF_API_KEY},
            json={"source_type": "markdown", "content": content, "filename": pdf_path.name},
            timeout=60
        )
        if resp.status_code == 200:
            pdf_path.write_bytes(resp.content)
            print(f"  ✅ PDF created: {pdf_path.name} ({len(resp.content):,} bytes)")
            return pdf_path
        else:
            # The endpoint puts the real cause in the body. Print it: a bare
            # status code sends you to a log that may not have the traceback.
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = (resp.text or "")[:500]
            print(f"  ❌ Conversion failed: {resp.status_code}"
                  + (f"\n     {detail}" if detail else "  (no detail returned)"))
            return None
    except Exception as e:
        print(f"  ❌ Conversion error: {e}")
        return None

# ── DRIVE UPLOAD ──────────────────────────────────────────────────────────────
def upload_to_drive(service, file_path: Path, folder_id: str):
    filename = file_path.name
    mimetype = 'application/pdf' if filename.endswith('.pdf') else 'application/json'

    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    existing = results.get('files', [])

    media = MediaFileUpload(str(file_path), mimetype=mimetype)

    if existing:
        service.files().update(fileId=existing[0]['id'], media_body=media).execute()
        print(f"  ♻️  Updated: {filename}")
    else:
        metadata = {'name': filename, 'parents': [folder_id]}
        service.files().create(body=metadata, media_body=media, fields='id').execute()
        print(f"  ☁️  Uploaded: {filename}")

# ── MAIN SYNC ─────────────────────────────────────────────────────────────────
def sync(force=False, specific_file=None):
    print(f"\n{'='*60}")
    print(f"DuCorn Google Drive Sync")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'FORCE ALL' if force else 'CHANGED ONLY'}")
    print(f"{'='*60}\n")

    PDFS_DIR.mkdir(exist_ok=True)

    # Load sync state
    sync_state = load_sync_state()

    # Connect to Drive
    print("🔐 Connecting to Google Drive...")
    try:
        service = get_drive_service()
        about = service.about().get(fields='user').execute()
        print(f"✅ Connected as: {about['user']['emailAddress']}\n")
    except Exception as e:
        print(f"❌ Drive connection failed: {e}")
        return {"converted": 0, "uploaded": 0, "skipped": 0, "errors": 1}

    # Get files to process
    if specific_file:
        md_files = [Path(specific_file)]
    else:
        md_files = sorted(DOCS_DIR.glob("*.md"))

    md_files = [p for p in md_files if not drive_routing.excluded(p.name)]
    print(f"📚 Found {len(md_files)} markdown files\n")

    # Read once; a run marked test belongs in Archive, not among real products.
    environments = drive_routing.load_environments(
        os.environ.get("DUCORN_DATABASE_URL", "postgresql://localhost/ducorn"))

    converted = uploaded = skipped = errors = reused = 0

    for md_path in md_files:
        # Check if file has changed since last sync
        md_mtime = md_path.stat().st_mtime
        last_synced = sync_state.get(str(md_path), 0)

        if not force and last_synced > md_mtime:
            # File unchanged since last sync — skip entirely
            skipped += 1
            continue

        print(f"Processing: {md_path.name}")

        # Convert MD to PDF
        pdf_path = convert_md_to_pdf(md_path, force=force)
        if pdf_path is REUSED:
            pdf_path = PDFS_DIR / md_path.with_suffix(".pdf").name
            reused += 1
        elif not pdf_path:
            errors += 1
            continue
        else:
            converted += 1

        # Upload to correct Drive folder
        drive_folder, why = drive_routing.route(pdf_path.name, environments)
        if drive_folder is None:
            print(f"  ⏭️  skipped — {why}")
            skipped += 1
            continue
        print(f"  📂 Target: {drive_folder}   ({why})")
        if drive_folder.endswith("/Inbox"):
            # Deliberately loud. The old catch-all made this case invisible.
            print(f"  ⚠️  UNROUTED: {pdf_path.name} has no product slug and no "
                  f"company match — add a rule in drive_routing.py")

        try:
            folder_id = get_folder_id_for_path(service, drive_folder)
            upload_to_drive(service, pdf_path, folder_id)
            uploaded += 1
            # Record this file as synced
            sync_state[str(md_path)] = time.time()
        except Exception as e:
            print(f"  ❌ Upload failed: {e}")
            errors += 1

        print()

    # Sync KPIs JSON
    kpi_path = DATA_DIR / "kpis.json"
    if kpi_path.exists():
        kpi_mtime = kpi_path.stat().st_mtime
        kpi_last_synced = sync_state.get(str(kpi_path), 0)

        if force or kpi_last_synced <= kpi_mtime:
            print("Processing: kpis.json")
            try:
                folder_id = get_folder_id_for_path(service, f"{DRIVE_ROOT}/KPIs")
                upload_to_drive(service, kpi_path, folder_id)
                uploaded += 1
                sync_state[str(kpi_path)] = time.time()
                print()
            except Exception as e:
                print(f"  ❌ KPI upload failed: {e}")
                errors += 1
        else:
            skipped += 1

    # Save updated sync state
    save_sync_state(sync_state)

    print(f"\n{'='*60}")
    print(f"SYNC COMPLETE")
    print(f"  📄 Converted: {converted}")
    print(f"  ♻️  Reused:    {reused}   (PDF already newer than the markdown)")
    print(f"  ☁️  Uploaded:  {uploaded}")
    print(f"  ⏭️  Skipped:   {skipped}")
    print(f"  ❌ Errors:    {errors}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    return {"converted": converted, "uploaded": uploaded, "skipped": skipped, "errors": errors}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DuCorn Google Drive Sync")
    parser.add_argument("--force", action="store_true", help="Force sync all files")
    parser.add_argument("--file", type=str, help="Sync specific MD file path")
    args = parser.parse_args()
    sync(force=args.force, specific_file=args.file)
