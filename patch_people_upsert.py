#!/usr/bin/env python3
"""
Record a person the first time they are seen.

THE GAP
-------
Migration 003 seeded `people` from emails already in founder_notes. Aruna's
notes were written before the identity patch, so they are attributed to "local"
and her real address never appeared. The table has two rows, neither of them
hers, and:

    UPDATE people SET display_name='Aruna' WHERE email='aruna1715@gmail.com';
    UPDATE 0

Nothing writes to `people`. So a person who has never been seeded renders as
their email local part forever, and the only way in is a hand-written INSERT
that nobody will remember to run.

I built a lookup table with no way to get into it. The fallback made it look
like it worked — "aruna1715" is what the old code produced too — which is the
failure mode of the day one more time: a control that reads correctly and never
reaches the thing it controls.

THE FIX
-------
current_user() upserts on first sight, with display_name defaulting to the local
part. So the FIRST time Aruna loads the dashboard her row appears, and setting
her name becomes a one-line UPDATE that actually matches something.

The upsert never overwrites an existing display_name — being seen again must not
undo a name someone set.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
s = API.read_text(encoding="utf-8")

if "_remember_person" in s:
    sys.exit("Already patched — _remember_person is present.")
if "display_name_for" not in s:
    sys.exit("Run patch_display_names.py first.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


swap("remember helper", '''def display_name_for(email: str) -> str:''',
'''def _remember_person(email: str) -> None:
    """
    Ensure this email has a row, so a name can be set for it later.

    DO NOTHING on conflict, never DO UPDATE: seeing someone again must not
    overwrite a display_name a human chose. The default is the email local
    part, which is exactly what is rendered without a row — so this changes
    nothing visible, it only makes the person addressable.
    """
    if not email or "@" not in email:
        return                      # the "local" fallback is not a person
    key = email.strip().lower()
    if key in _people():
        return
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO people (email, display_name) VALUES (%s, %s) "
                    "ON CONFLICT (email) DO NOTHING",
                    (key, key.split("@")[0]))
                conn.commit()
        finally:
            conn.close()
        _people_cache["ts"] = 0.0   # next read picks the new row up
        print(f"[people] first sighting of {key} — added, display_name "
              f"defaults to {key.split('@')[0]!r}")
    except Exception as e:
        # Never fatal. Not recording someone costs a nice name, not a session.
        print(f"[people] could not record {key} ({e})")


def display_name_for(email: str) -> str:''')

swap("cloudflare upsert",
     '''        return {"email": email, "name": display_name_for(email),
                "initials": initials_for(email), "source": "cloudflare"}''',
     '''        _remember_person(email)
        return {"email": email, "name": display_name_for(email),
                "initials": initials_for(email), "source": "cloudflare"}''')

swap("asserted upsert",
     '''        return {"email": asserted, "name": display_name_for(asserted),
                "initials": initials_for(asserted), "source": "client-asserted"}''',
     '''        _remember_person(asserted)
        return {"email": asserted, "name": display_name_for(asserted),
                "initials": initials_for(asserted), "source": "client-asserted"}''')

backup = API.with_name(f"main.backup-upsert-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(API, backup)
API.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, API)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup}")
print()
print("Aruna's row appears the next time she loads the dashboard. Or add it now:")
print("""  psql ducorn -c "INSERT INTO people (email, display_name) VALUES """
      """('aruna1715@gmail.com','Aruna') ON CONFLICT (email) DO UPDATE SET """
      """display_name=EXCLUDED.display_name;" """)
