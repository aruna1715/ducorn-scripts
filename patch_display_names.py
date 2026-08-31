#!/usr/bin/env python3
"""
Resolve display names server-side, and stop the dashboard inventing its own.

Run migration 003 first:
    python3 scripts/migrate.py

Two files:

  main.py      display_name_for() reads the people table; current_user() uses
               it; /founder-notes returns created_by_name and done_by_name
  index.html   _who() displays the name the API sent instead of splitting the
               email itself

WHY SERVER-SIDE
---------------
The dashboard could look names up too, but then two implementations would have
to agree about caching, about what happens to an unknown email, and about
which field wins. The API already knows who everyone is; it should answer the
question rather than hand out raw emails and hope.

The email is still sent, and still shown on hover. A display name is a
convenience, not a replacement for knowing which account did something.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

API  = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
DASH = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


# ── API ──────────────────────────────────────────────────────────────────────
a = API.read_text(encoding="utf-8")
if "display_name_for" in a:
    sys.exit("Already patched — display_name_for is present.")

a = swap(API, "resolver", a, '''def current_user(request: Request) -> dict:''',
'''_people_cache = {"data": {}, "ts": 0.0}
_PEOPLE_TTL = 60


def _people() -> dict:
    """{email: (display_name, initials)}, cached briefly."""
    import time
    now = time.time()
    if _people_cache["data"] and now - _people_cache["ts"] < _PEOPLE_TTL:
        return _people_cache["data"]
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT email, display_name, initials FROM people "
                            "WHERE active")
                data = {r["email"].lower(): (r["display_name"], r["initials"])
                        for r in cur.fetchall()}
        finally:
            conn.close()
        _people_cache.update(data=data, ts=now)
        return data
    except Exception as e:
        # Not fatal: an unknown email falls back to its local part, which is
        # what every caller did before this table existed.
        print(f"[people] could not read the people table ({e}) — "
              f"falling back to email local parts")
        return {}


def display_name_for(email: str) -> str:
    """
    What to call this person.

    The ONLY place an email becomes a name. current_user, the founder notes
    and the user chip all come through here, so a name cannot render one way
    in one panel and another way in the next.
    """
    if not email:
        return "-"
    return _people().get(email.strip().lower(), (None, None))[0] \\
        or email.split("@")[0]


def initials_for(email: str) -> str:
    if not email:
        return "-"
    ini = _people().get(email.strip().lower(), (None, None))[1]
    return ini or (display_name_for(email)[:1] or "-").upper()


def current_user(request: Request) -> dict:''')

# current_user has three return points, each building name from the local part.
for label, old, new in [
    ("cloudflare name",
     '''        return {"email": email, "name": email.split("@")[0], "source": "cloudflare"}''',
     '''        return {"email": email, "name": display_name_for(email),
                "initials": initials_for(email), "source": "cloudflare"}'''),
    ("asserted name",
     '''        return {"email": asserted, "name": asserted.split("@")[0],
                "source": "client-asserted"}''',
     '''        return {"email": asserted, "name": display_name_for(asserted),
                "initials": initials_for(asserted), "source": "client-asserted"}'''),
    ("local name",
     '''    return {"email": fallback, "name": fallback.split("@")[0], "source": "local"}''',
     '''    return {"email": fallback, "name": display_name_for(fallback),
            "initials": initials_for(fallback), "source": "local"}'''),
]:
    a = swap(API, label, a, old, new)

a = swap(API, "notes names", a,
'''    return {"notes": [dict(r) for r in rows], "me": current_user(request)}''',
'''    notes = []
    for r in rows:
        n = dict(r)
        # Resolved here rather than in the browser: the dashboard used to split
        # these emails itself, which is how the same person could appear as
        # "aruna1715" in one panel and by name in another.
        n["created_by_name"] = display_name_for(n.get("created_by"))
        if n.get("done_by"):
            n["done_by_name"] = display_name_for(n["done_by"])
        notes.append(n)
    return {"notes": notes, "me": current_user(request)}''')
edits.append((API, a))


# ── Dashboard ────────────────────────────────────────────────────────────────
d = DASH.read_text(encoding="utf-8")
if "created_by_name" in d:
    sys.exit("Already patched — the dashboard reads created_by_name.")

d = swap(DASH, "_who", d,
'''  function _who(email) { return String(email || '').split('@')[0] || '-'; }''',
'''  // Display the name the API resolved. Splitting the email here was the
  // second of three implementations of "what is this person called"; the
  // fallback stays only for a note that predates the people table.
  function _who(note) {
    if (note && typeof note === 'object') {
      return note.created_by_name || String(note.created_by || '').split('@')[0] || '-';
    }
    return String(note || '').split('@')[0] || '-';
  }''')

d = swap(DASH, "note render", d,
'''              <span title="${_esc(n.created_by)}">${_esc(_who(n.created_by))}</span>''',
'''              <span title="${_esc(n.created_by)}">${_esc(_who(n))}</span>''')

d = swap(DASH, "chip initials", d,
'''    const label = _me.name || '-';
    name.textContent = label.toUpperCase();
    ini.textContent  = (label[0] || '-').toUpperCase();''',
'''    const label = _me.name || '-';
    name.textContent = label.toUpperCase();
    // The API supplies initials when someone goes by them; first letter only
    // as a fallback.
    ini.textContent  = (_me.initials || label[0] || '-').toUpperCase();''')
edits.append((DASH, d))


for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-names-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")

import ast
try:
    ast.parse(API.read_text(encoding="utf-8"))
except SyntaxError as e:
    sys.exit(f"SYNTAX ERROR in main.py ({e}) — restore from *.backup-names-{stamp}.*")

d2 = DASH.read_text(encoding="utf-8")
for must in ("function renderApprovals", "function syncToDrive", "function _who"):
    if must not in d2:
        sys.exit(f"index.html lost {must!r} — restore from *.backup-names-{stamp}.*")

print("applied: " + ", ".join(applied))
print(f"backups: *.backup-names-{stamp}.*")
print()
print("Restart the API, hard-refresh the dashboard, then set the real names:")
print("""  psql ducorn -c "UPDATE people SET display_name='Aruna' WHERE email LIKE 'aruna%';" """)
print("""  psql ducorn -c "SELECT email, display_name FROM people ORDER BY email;" """)
