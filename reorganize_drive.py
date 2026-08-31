#!/usr/bin/env python3
"""
Move the existing DuCorn PDFs in Google Drive into the derived structure.

DRY RUN BY DEFAULT. It prints every move with the reason for it and changes
nothing. Read the plan, argue with the classifications you disagree with, then
run again with --apply.

That is not ceremony. The classifications are inferred from filenames, and an
earlier draft of the rules confidently filed ducorn-autonomy-console-v2 under
Archive/Tests because "-v2" looked like version churn. Rules that read plausibly
can still be wrong about which of your products are real, and only you know.

Files are MOVED, not copied — Drive keeps one copy with a new parent, so links
and file ids survive. Nothing is deleted, and --apply is re-runnable: a file
already in the right folder is left alone.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import drive_routing  # noqa: E402

from google.oauth2.credentials import Credentials  # noqa: E402
from google.auth.transport.requests import Request  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

TOKEN_FILE = "/Users/ducorn/DC/shared/gdrive-token.json"
DRIVE_ROOT = "DuCorn"

_folder_cache = {}


def service():
    creds = Credentials.from_authorized_user_file(
        TOKEN_FILE, scopes=["https://www.googleapis.com/auth/drive"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(TOKEN_FILE).write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def find_root(svc):
    r = svc.files().list(
        q=f"name='{DRIVE_ROOT}' and mimeType='application/vnd.google-apps.folder' "
          f"and trashed=false", fields="files(id,name)").execute()
    files = r.get("files", [])
    if not files:
        sys.exit(f"No '{DRIVE_ROOT}' folder found in Drive.")
    return files[0]["id"]


def walk(svc, folder_id, path=DRIVE_ROOT, depth=0):
    """Every non-folder file under the DuCorn tree, with its current path."""
    if depth > 6:
        return
    page = None
    while True:
        r = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id,name,mimeType,parents)",
            pageToken=page, pageSize=200).execute()
        for f in r.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                yield from walk(svc, f["id"], f"{path}/{f['name']}", depth + 1)
            else:
                yield f, path
        page = r.get("nextPageToken")
        if not page:
            break


def ensure_folder(svc, path, apply):
    """Resolve (creating if needed) a slash path, cached."""
    if path in _folder_cache:
        return _folder_cache[path]
    parent = None
    for part in path.strip("/").split("/"):
        key = f"{parent}:{part}"
        if key in _folder_cache:
            parent = _folder_cache[key]
            continue
        q = (f"name='{part}' and mimeType='application/vnd.google-apps.folder' "
             f"and trashed=false")
        if parent:
            q += f" and '{parent}' in parents"
        found = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if found:
            parent = found[0]["id"]
        elif apply:
            meta = {"name": part, "mimeType": "application/vnd.google-apps.folder"}
            if parent:
                meta["parents"] = [parent]
            parent = svc.files().create(body=meta, fields="id").execute()["id"]
            print(f"    created folder {part}")
        else:
            parent = f"<would-create:{part}>"
        _folder_cache[key] = parent
    _folder_cache[path] = parent
    return parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually move files (default is a dry run)")
    args = ap.parse_args()

    svc = service()
    root = find_root(svc)
    environments = drive_routing.load_environments()
    if environments:
        print(f"read environment for {len(environments)} runs from pipeline_runs\n")

    plan = defaultdict(list)     # destination -> [(file, current_path, reason)]
    already, skipped = 0, []

    for f, current in walk(svc, root):
        dest, reason = drive_routing.route(f["name"], environments)
        if dest is None:
            skipped.append((f["name"], reason))
            continue
        if current == dest:
            already += 1
            continue
        plan[dest].append((f, current, reason))

    total = sum(len(v) for v in plan.values())
    mode = "APPLYING" if args.apply else "DRY RUN — nothing will change"
    print(f"{'='*70}\n{mode}\n{'='*70}")
    print(f"{total} to move | {already} already correct | {len(skipped)} skipped\n")

    unrouted = []
    for dest in sorted(plan):
        print(dest)
        for f, current, reason in sorted(plan[dest], key=lambda x: x[0]["name"]):
            print(f"    {f['name']:<48}  {reason}")
            if current != DRIVE_ROOT:
                print(f"      {'':<46}  (from {current})")
            if dest.endswith("/Inbox"):
                unrouted.append(f["name"])
            if args.apply:
                new_parent = ensure_folder(svc, dest, True)
                svc.files().update(fileId=f["id"], addParents=new_parent,
                                   removeParents=",".join(f.get("parents", [])),
                                   fields="id,parents").execute()
        print()

    if skipped:
        print("Skipped (not documents):")
        for name, reason in skipped:
            print(f"    {name:<48}  {reason}")
        print()

    if unrouted:
        print(f"⚠️  {len(unrouted)} file(s) landed in Inbox with no rule matching "
              f"them.\n    Add a rule to drive_routing.py rather than moving them "
              f"by hand,\n    or they will go back to Inbox on the next sync:")
        for n in unrouted:
            print(f"      {n}")
        print()

    if not args.apply and total:
        print("Nothing was changed. Re-run with --apply once the plan looks right.")


if __name__ == "__main__":
    main()
