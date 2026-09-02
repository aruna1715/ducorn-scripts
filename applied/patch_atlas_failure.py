#!/usr/bin/env python3
"""
Let ATLAS see the failure it is being asked about — and be the model you picked.

── THE OPERATOR IS IN REX'S POSITION ────────────────────────────────────────

An hour ago IRIS wrote a precise diagnosis, three times, and REX never received
it, because nothing carried the report from where it was written to where it
was needed. We fixed that. The dashboard has the identical defect one layer up,
and this time the recipient is a person.

Today, when a pipeline fails, /chat feeds ATLAS this:

    PRODUCTS BUILT:
    - DuCorn Spend Status (ducorn-spend-status): failed, simple, $4.20 spent

That is the whole of what ATLAS knows. Not the verdict, not the numbered
issues, not a line of the log. So your operator asks "why did it fail?" and
ATLAS can only say it failed and what it cost. The 4,856-byte document naming
the exact broken line is on disk, addressed to nobody. 44 endpoints in this
file and not one mentions verdict, qa-report or skill06.

── AND IT IS THE WRONG MODEL ────────────────────────────────────────────────

    resp = await client.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3.1:latest", ...

The switcher says ATLAS=claude-sonnet. /chat calls Ollama directly with
llama3.1 hardcoded, bypassing the router and the switcher both. So the model
you chose to be your operator's debugging partner has never once answered
them. This is the same defect as the brief wizard this morning — same file,
and a comment sixty lines below this call already describes it: "was drafted
by llama3.1 whatever the switcher said". I fixed that instance and left this
one.

Combined with "2-3 sentences max", the debugging partner is a small local
model with no data and a word limit. No runbook fixes that.

── WHAT THIS CHANGES ────────────────────────────────────────────────────────

1. /chat resolves its model from load_agent_config() and goes through the
   router on :4001, billed to LITELLM_KEY_ATLAS — the same path the brief
   wizard now uses. The switcher becomes true for ATLAS as well.

2. failure_context(slug) assembles what a person needs to act: which skills
   passed and which failed, the QA report, and the tail of the flow log.
   Attached automatically when a product has failed.

3. The sentence cap lifts only when there is a failure to explain. Chit-chat
   stays short; debugging gets room.

4. GET /pipeline/failure/{slug} exposes the same assembly, so the dashboard
   panel has a route to call and does not need its own copy of this logic.

── THE JAIL APPLIES TO ATLAS TOO ────────────────────────────────────────────

failure_context reads files for exactly one product and builds every path from
a slug that has been validated twice: against a strict pattern, and against
pipeline_runs. A slug that is not a known product reads nothing. Filenames are
constructed from that slug and never from anything a caller typed, so there is
no path for one product's context to include another's.

Worth knowing, found while writing this and NOT fixed here: the existing
GET /products/{slug}/doc ignores its slug entirely and joins the caller's
filename straight onto the docs directory, so it will read any product's
document — or ../../shared/.env — under any slug. It is behind the x-api-key
middleware, so it is a defect rather than an open door, but it is precisely
the isolation rule you called a showstopper. It deserves its own patch rather
than a quiet ride on this one.

Also not fixed here: /jarvis/chat has the same hardcoded llama3.1. It calls
Ollama's native endpoint with a hand-built prompt, so moving it to the router
is a restructure, not a line. Naming it rather than half-doing it.
"""
import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
s = API.read_text(encoding="utf-8")

if "def failure_context" in s:
    sys.exit("Already patched — ATLAS can see failures.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the helpers ───────────────────────────────────────────────────────────
s = swap("helpers", s, '''@app.post("/chat")''',
         '''# A product slug, as the pipeline writes them. Validated against this AND
# against pipeline_runs before any path is built from it, because everything
# below reads files whose names come from the slug.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

FAILURE_REPORT_LIMIT = 5000    # the QA report; every one so far fits
FAILURE_LOG_LINES = 60         # enough to see the traceback that ended the run


def known_slug(slug: str) -> bool:
    """Is this a real product? Pattern first, then the database."""
    if not slug or not _SLUG_RE.match(slug):
        return False
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pipeline_runs WHERE slug=%s LIMIT 1",
                        (slug,))
            return cur.fetchone() is not None
    except Exception as e:
        print(f"[failure] could not verify slug {slug!r} ({e})")
        return False
    finally:
        if conn:
            conn.close()


def failure_context(slug: str) -> str:
    """
    What a person needs to act on a failed run, for ONE product.

    Every path here is built from a slug that known_slug() has already checked
    against pipeline_runs — never from a caller's string — so this cannot reach
    another product's files or outside the products tree.

    Empty when the product is healthy, so attaching it is always safe.
    """
    if not known_slug(slug):
        return ""

    docs = Path("/Users/ducorn/DC/ducorn-products/docs")
    parts = []

    # Which skills stand, and which failed. This is the shape of the problem
    # before any of the detail.
    try:
        ck = docs / f"{slug}-gstack-checkpoint.json"
        if ck.is_file():
            data = _json.loads(ck.read_text())
            rows = [f"  {k}: {v.get('status')} — "
                    f"{str(v.get('verdict', ''))[:100]}"
                    for k, v in sorted(data.items()) if not k.startswith("_")]
            if rows:
                parts.append("SKILL RESULTS:\\n" + "\\n".join(rows))
    except Exception as e:
        parts.append(f"SKILL RESULTS: unreadable ({e})")

    # The report itself. This is the part that has never reached anyone.
    for num, what in (("06", "QA"), ("05", "code review")):
        try:
            rp = docs / f"{slug}-skill{num}-output.txt"
            if rp.is_file():
                parts.append(f"{what.upper()} REPORT (skill {num}):\\n"
                             f"{rp.read_text(errors='replace')[:FAILURE_REPORT_LIMIT]}")
                break
        except Exception as e:
            parts.append(f"{what.upper()} REPORT: unreadable ({e})")

    # How the run actually ended.
    try:
        lg = Path("/Users/ducorn/DC/logs") / f"flow_{slug}.log"
        if lg.is_file():
            tail = lg.read_text(errors="replace").splitlines()[-FAILURE_LOG_LINES:]
            parts.append("END OF THE RUN LOG:\\n" + "\\n".join(tail))
    except Exception as e:
        parts.append(f"RUN LOG: unreadable ({e})")

    if not parts:
        return ""
    return f"FAILURE DETAIL FOR {slug}:\\n\\n" + "\\n\\n".join(parts)


def failed_slug_for(message: str) -> str:
    """
    Which product is this question about?

    A slug named in the message wins. Otherwise the most recently failed run,
    because that is overwhelmingly what someone at a dashboard is asking about.
    Returns "" when nothing has failed, and ATLAS stays brief.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT slug, status FROM pipeline_runs "
                        "ORDER BY created_at DESC LIMIT 60")
            rows = cur.fetchall()
    except Exception:
        return ""
    finally:
        if conn:
            conn.close()

    low = (message or "").lower()
    for r in rows:
        if r["slug"] and r["slug"].lower() in low:
            return r["slug"]
    for r in rows:
        if str(r["status"] or "").lower() in ("failed", "error"):
            return r["slug"]
    return ""


@app.get("/pipeline/failure/{slug}")
def get_pipeline_failure(slug: str):
    """
    Why this run failed, assembled from what is already on disk.

    The dashboard's failure panel calls this. It exists so that panel does not
    grow its own copy of the assembly and drift from what ATLAS is told.
    """
    if not known_slug(slug):
        return JSONResponse({"error": "Unknown product"}, status_code=404)
    detail = failure_context(slug)
    return {"slug": slug, "has_detail": bool(detail), "detail": detail}


@app.post("/chat")''')

# ── 2. assemble the failure detail before the prompt ─────────────────────────
s = swap("assemble", s,
         '''            _products_str = "\\n".join(_products) if _products else "No products yet"''',
         '''            _products_str = "\\n".join(_products) if _products else "No products yet"

            # The report that has never reached a human. Empty when nothing has
            # failed, so this costs nothing on a healthy day.
            _failed_slug = failed_slug_for(message)
            _failure = failure_context(_failed_slug) if _failed_slug else ""
            if _failure:
                print(f"[chat] attaching failure detail for {_failed_slug} "
                      f"({len(_failure):,} chars)")''')

# ── 3. the prompt carries it, and the word limit lifts to make room ──────────
s = swap("prompt", s,
         '''PIPELINE: Research → Build → QA → Deploy (G-Stack with 6 skills)
COMMANDS: @DuCorn run, confirm, approve, reject, status, digest, kpis, pdfs, sync

You have full knowledge of all DuCorn products and operations.
Answer as ATLAS — knowledgeable, concise, direct. 2-3 sentences max."""''',
         '''PIPELINE: Research → Build → QA → Deploy (G-Stack with 6 skills)
COMMANDS: @DuCorn run, confirm, approve, reject, status, digest, kpis, pdfs, sync

{_failure}

You have full knowledge of all DuCorn products and operations.
{"Someone is asking about a pipeline run and the detail above is the "
 "evidence — read the verdict before you characterise it. If it failed, "
 "tell them what broke in plain terms, quoting the specific "
 "test or error, then what to do next: press Resume on the "
 "dashboard if the failure is one a rebuild can fix — the builder is now "
 "given the QA report automatically — or say plainly that this one needs "
 "an engineer, and why. Never invent a cause the detail does not support; "
 "if the detail does not say, say that it does not say. Be specific and "
 "as long as it takes."
 if _failure else
 "Answer as ATLAS — knowledgeable, concise, direct. 2-3 sentences max."}"""''')

# ── 4. through the router, on the model the switcher names ───────────────────
s = swap("router call", s, '''            resp = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3.1:latest",
                    "prompt": f"{_system_prompt}\\n\\nQuestion: {message}",
                    "stream": False
                }
            )
            response_text = resp.json().get("response", "").strip()''',
         '''            # From the switcher, not from a literal. Hardcoding llama3.1 here
            # meant the model you chose for ATLAS had never once answered you
            # — the same defect as the brief wizard, sixty lines below.
            _atlas_model = load_agent_config().get(
                "ATLAS", DEFAULT_AGENT_CONFIG["ATLAS"])
            print(f"[chat] ATLAS on {_atlas_model}"
                  + ("  (explaining a failure)" if _failure else ""))
            resp = await client.post(
                "http://localhost:4001/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ.get('LITELLM_KEY_ATLAS', '')}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": _atlas_model,
                    "messages": [
                        {"role": "system", "content": _system_prompt},
                        {"role": "user", "content": message}
                    ],
                    # A failure explanation needs room; a greeting does not.
                    "max_tokens": 1200 if _failure else 200,
                    "temperature": 0.3
                }
            )
            resp.raise_for_status()
            response_text = resp.json()["choices"][0]["message"]["content"].strip()''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = API.with_name(f"main.backup-atlasfail-{stamp}.py")
shutil.copy2(API, backup)
API.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, API)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

# ── exercise the jail, which is the part that must not be wrong ──────────────
src = API.read_text(encoding="utf-8")
tree = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "known_slug"), None)
if seg is None:
    die("known_slug did not land")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
if f"_SLUG_RE = re.compile(r\"{SLUG_RE.pattern}\")" not in src:
    die("the slug pattern in the patched file is not the one being tested")

print("\nchecking slug validation (pattern only — the DB check is the second gate):")
for probe, want, why in [
    ("ducorn-spend-status", True, "a real product"),
    ("../../shared/.env", False, "traversal"),
    ("..", False, "parent"),
    ("a/b", False, "a path, not a slug"),
    ("Ducorn-Spend", False, "uppercase is not how slugs are written"),
    ("-leading", False, "leading dash"),
    ("", False, "empty"),
    ("x" * 80, False, "absurd length"),
]:
    got = bool(SLUG_RE.match(probe))
    print(f"  {'ok  ' if got == want else 'FAIL'} {probe[:28]:30} → "
          f"{'accepted' if got else 'rejected'}  ({why})")
    if got != want:
        die(f"{probe!r}: expected {want}")

for must in ('"http://localhost:4001/v1/chat/completions"',
             'load_agent_config().get(', 'FAILURE_REPORT_LIMIT',
             '/pipeline/failure/'):
    if must not in src:
        die(f"{must!r} missing from the patched file")
if 'json={\n                    "model": "llama3.1:latest",\n                    "prompt"' in src:
    die("/chat still calls Ollama directly")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Restart the API, then ask ATLAS on the dashboard: 'why did "
      "ducorn-spend-status fail?'")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
print()
print("Expect in logs/activity_api.log:")
print("  [chat] attaching failure detail for <slug> (N chars)")
print("  [chat] ATLAS on claude-sonnet  (explaining a failure)")
