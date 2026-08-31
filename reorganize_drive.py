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

def _find_interpreter_with_google():
    """
    The Google client libraries live in exactly one of the several pythons on
    this Mac, and it is not the one on PATH (3.14) nor the ducorn venv. Rather
    than tell you to try another and let you hunt, look.
    """
    import glob
    import shutil
    import subprocess

    candidates = []
    for name in ("python3.12", "python3.11", "python3.13", "python3.10"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    candidates += sorted(glob.glob("/opt/homebrew/opt/python@3.*/bin/python3.*"))
    candidates += sorted(glob.glob("/opt/homebrew/bin/python3.1*"))
    candidates.append("/usr/bin/python3")
    candidates.append("/Users/ducorn/DC/ducorn/.venv/bin/python")

    seen, working = set(), []
    for c in candidates:
        real = os.path.realpath(c) if os.path.exists(c) else c
        if real in seen or not os.path.exists(c):
            continue
        seen.add(real)
        try:
            r = subprocess.run([c, "-c", "import googleapiclient, google.oauth2"],
                               capture_output=True, timeout=20)
            if r.returncode == 0:
                working.append(c)
        except Exception:
            pass
    return working


import os  # noqa: E402

try:
    from google.oauth2.credentials import Credentials  # noqa: E402
    from google.auth.transport.requests import Request  # noqa: E402
    from googleapiclient.discovery import build  # noqa: E402
except ImportError:
    found = _find_interpreter_with_google()
    if not found:
        sys.exit(
            f"The Google API libraries are not in {sys.executable}, and I could "
            f"not find any interpreter on this Mac that has them.\n\n"
            f"Install them into the one you want to use, e.g.:\n"
            f"    python3.12 -m pip install google-api-python-client google-auth\n\n"
            f"(gdrive_sync.py needs the same libraries, so whichever interpreter "
            f"runs that one is the right target.)")

    if os.environ.get("_DUCORN_REEXEC"):
        sys.exit(f"Re-exec under {found[0]} still could not import the libraries. "
                 f"Stopping rather than looping.")

    print(f"[reorganize_drive] {os.path.basename(sys.executable)} has no Google "
          f"API libraries; re-running under {found[0]}\n")
    os.environ["_DUCORN_REEXEC"] = "1"
    os.execv(found[0], [found[0], os.path.abspath(__file__)] + sys.argv[1:])

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
            fields="nextPageToken, files(id,name,mimeType,parents,modifiedTime)",
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
        n_test = sum(1 for v in environments.values()
                     if (v or "").lower() in ("test", "testing", "dev"))
        # Shown as context, NOT used for routing — see is_test() in
        # drive_routing.py for why this column cannot answer the question.
        print(f"pipeline_runs: {len(environments)} runs, {n_test} ran on local "
              f"models (environment=test).\nThat records spend, not whether a "
              f"product is real, so it does not affect routing.\n")

    plan = defaultdict(list)     # destination -> [(file, current_path, reason)]
    already, skipped = 0, []
    by_target = defaultdict(list)

    for f, current in walk(svc, root):
        dest, reason = drive_routing.route(f["name"], environments)
        if dest is None:
            skipped.append((f["name"], reason, current))
            continue
        by_target[(dest, f["name"])].append((f, current, reason))

    # Several copies of one filename are scattered across the old folders —
    # atlas-marketing-taglines.pdf exists under both "P001 - Autonomy Console"
    # and "ATLAS Dashboard", for instance. Moving them all to one destination
    # would put two identically-named files in a single folder, which Drive
    # permits and which is worse than the mess we started with.
    #
    # So the newest copy goes to the destination and the rest go to
    # Archive/Duplicates. Nothing is trashed: an automatic delete of something
    # that merely LOOKS redundant is not a call this script gets to make.
    duplicates = []
    for (dest, name), copies in by_target.items():
        copies.sort(key=lambda c: c[0].get("modifiedTime", ""), reverse=True)
        keeper, rest = copies[0], copies[1:]
        f, current, reason = keeper
        if current == dest:
            already += 1
        else:
            plan[dest].append(keeper)
        for f2, current2, _ in rest:
            slug = dest.rsplit("/", 1)[-1]
            plan[f"{DRIVE_ROOT}/Archive/Duplicates/{slug}"].append(
                (f2, current2, f"duplicate of the copy kept in {dest}"))
            duplicates.append((name, current2, dest))

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

    if duplicates:
        print(f"{len(duplicates)} duplicate copy/copies found. The newest of each "
              f"went to its destination;\nthe others went to Archive/Duplicates "
              f"rather than colliding by name or being trashed:")
        for name, where, dest in sorted(duplicates):
            print(f"    {name:<44}  extra copy was in {where}")
        print()

    if skipped:
        print("Left untouched (not documents this router has an opinion about):")
        for name, reason, current in sorted(skipped):
            print(f"    {name:<44}  {reason}  [{current}]")
        print()

    if unrouted:
        print(f"⚠️  {len(unrouted)} file(s) landed in Inbox with no rule matching "
              f"them.\n    Add a rule to drive_routing.py rather than moving them "
              f"by hand,\n    or they will go back to Inbox on the next sync:")
        for n in unrouted:
            print(f"      {n}")
        print()

    # Folders that lose every file they hold end up as empty shells of the old
    # scheme ("Products/P001 - Autonomy Console", "Products/ATLAS Dashboard").
    # Worth naming: they are not deleted, and an empty folder still looks like
    # a place things belong.
    held, leaving = defaultdict(int), defaultdict(int)
    all_paths = set()
    for f, current in walk(svc, root):
        held[current] += 1
        all_paths.add(current)
    for dest in plan:
        for f, current, _ in plan[dest]:
            leaving[current] += 1

    emptied = sorted(p for p in leaving
                     if leaving[p] >= held.get(p, 0) and p != DRIVE_ROOT)
    if emptied:
        print("These folders will hold no more FILES afterwards:")
        for p in emptied:
            # A folder can be empty of files and still be the parent of others.
            # DuCorn/Company is the obvious case: it loses its 30-odd loose PDFs
            # but still contains Weekly Reports, Board Documents and Technical
            # Reference. Deleting it would take those with it, so say so rather
            # than listing it beside genuinely disposable folders.
            children = sorted(q for q in all_paths
                              if q.startswith(p + "/") and q != p)
            if children:
                kids = ", ".join(c.rsplit("/", 1)[-1] for c in children)
                print(f"    {p}")
                print(f"        DO NOT DELETE — still contains: {kids}")
            else:
                print(f"    {p}   (safe to remove by hand)")
        print("\n    Nothing here is deleted by this script.\n")

    if not args.apply and total:
        print("Nothing was changed. Re-run with --apply once the plan looks right.")


if __name__ == "__main__":
    main()
