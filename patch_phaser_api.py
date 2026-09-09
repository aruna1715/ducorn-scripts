#!/usr/bin/env python3
"""
Define an epic from the dashboard. The Phaser's two endpoints.

    cd ~/DC && python3 scripts/patch_phaser_api.py            show
    cd ~/DC && python3 scripts/patch_phaser_api.py --apply    do it

Needs scripts/product_epics.py, scripts/product_pathways.py, patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

Everything about a phased product can be done from the dashboard except the
one step that creates it. That step was a JSON file I hand-wrote and a CLI
command, which makes every future phased product depend on me being in the
room. This is the half that closes it.

    POST /epics/split    propose phases from a whole-product brief
    POST /epics          create the epic from the phases you approved

── WHAT SPLIT DOES AND DOES NOT DECIDE ──────────────────────────────────────

It proposes. Nothing is created, nothing is spent beyond one BRIEF-model
call, and the operator edits every field before /epics is called. A model
that splits a product badly costs a re-read of a form, not a run.

Two things it is NOT allowed to decide, because they are rules rather than
judgement:

  SLUGS         built here from the epic name and the sequence, so they
                always match the shape the jail and pipeline_runs accept. A
                model-invented slug is a slug nobody validated.
  DEPENDENCIES  default to "the phase before", written out by
                product_epics.define. The model may only propose earlier
                phases, and define refuses anything else.

── AND /epics ───────────────────────────────────────────────────────────────

It calls product_epics.define and adds no logic. define already refuses a
duplicate name, a phase without a slug, duplicate slugs, and a dependency
that points forward — an endpoint that re-checked those would be a second,
staler copy of the rules.

Billing follows the brief wizard: LITELLM_KEY_ATLAS, because this is a
dashboard tool and ATLAS holds the dashboard's budget. Spending SAGE's key
here takes it out of the research the brief then feeds.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
API = DC / "ducorn-products" / "products" / "ducorn-activity-api" / "main.py"
NEEDED = [DC / "scripts" / "product_epics.py",
          DC / "scripts" / "product_pathways.py",
          DC / "scripts" / "patchlib.py"]
TAG = "phaserapi"

ANCHOR = '''@app.get("/epics")
def epics_list():'''

BLOCK = '''SPLIT_PROMPT = """You are planning how to build one product over several runs.

The whole product:
{brief}

Product type: {ptype}
Build it in {n} phases.

RULES
- Every phase builds into the SAME product directory. A later phase EXTENDS
  what an earlier one produced; it never starts again and never renames what
  is already there.
- Phase 1 must stand up on its own — something a person can run at the end of
  it, not scaffolding.
- Each phase must be independently reviewable: it has its own acceptance
  criteria that can be checked without the later phases existing.
- Order by dependency, not by importance.

Return ONLY a JSON object, no prose around it:

{{"phases": [
  {{"title": "short name, 2-5 words",
    "brief": "what THIS phase delivers, 60-150 words, written as an
              instruction to the builder, including its acceptance criteria",
    "depends_on": [1]}}
]}}

depends_on lists EARLIER phase numbers only, and may be empty for phase 1."""


def _phase_slug(epic_name: str, seq: int, title: str) -> str:
    """
    A slug the jail and pipeline_runs will accept.

    Built here, never taken from the model. A slug is an identity that three
    tables and one filesystem jail agree on; letting a language model invent
    one means a value nobody validated becomes a directory name.
    """
    import re as _re
    short = _re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    short = "-".join([w for w in short.split("-") if w][:2]) or "phase"
    slug = f"{epic_name}-p{seq}-{short}"
    return _re.sub(r"-+", "-", slug)[:100].strip("-")


@app.post("/epics/split")
async def epics_split(request: Request):
    """
    Propose phases for a brief. Creates nothing.

    One model call. The operator edits the result before anything is created,
    so a bad split costs a re-read of a form rather than a run.
    """
    body = await request.json()
    name = (body.get("name") or "").strip()
    brief = (body.get("brief") or "").strip()
    ptype = (body.get("product_type") or "software").strip()
    try:
        n = max(2, min(int(body.get("phases") or 3), 8))
    except (TypeError, ValueError):
        n = 3

    if not name or len(brief) < 80:
        return JSONResponse(
            {"error": "a name and a brief of at least 80 characters are "
                      "needed — a two-line brief splits into two-line phases"},
            status_code=400)

    model = load_agent_config().get("BRIEF", DEFAULT_AGENT_CONFIG["BRIEF"])
    print(f"[phaser] splitting {name!r} into {n} phases on {model}")

    try:
        import requests as _req
        resp = _req.post(
            "http://localhost:4001/v1/chat/completions",
            headers={
                # ATLAS, as the brief wizard does: a dashboard tool spends the
                # dashboard's budget, not the research budget it feeds.
                "Authorization": f"Bearer {os.environ.get('LITELLM_KEY_ATLAS', '')}",
                "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "user",
                                "content": SPLIT_PROMPT.format(
                                    brief=brief[:6000], ptype=ptype, n=n)}],
                  "max_tokens": 2000, "temperature": 0.2},
            timeout=180)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return JSONResponse({"error": f"the model call failed: {e}"},
                            status_code=502)

    import json as _json
    import re as _re
    m = _re.search(r"\\{.*\\}", text, _re.S)
    if not m:
        # The raw text goes back so the operator can paste the phases in by
        # hand rather than being told only that it did not work.
        return JSONResponse({"error": "the model did not return JSON",
                             "raw": text[:2000]}, status_code=502)
    try:
        phases = _json.loads(m.group(0)).get("phases") or []
    except Exception as e:
        return JSONResponse({"error": f"the JSON did not parse: {e}",
                             "raw": text[:2000]}, status_code=502)

    out = []
    for i, p in enumerate(phases[:n], start=1):
        deps = [d for d in (p.get("depends_on") or [])
                if isinstance(d, int) and 1 <= d < i]
        title = (p.get("title") or f"Phase {i}").strip()
        out.append({"seq": i, "title": title,
                    "slug": _phase_slug(name, i, title),
                    "brief": (p.get("brief") or "").strip(),
                    "depends_on": deps or ([i - 1] if i > 1 else [])})
    if not out:
        return JSONResponse({"error": "the model proposed no phases",
                             "raw": text[:2000]}, status_code=502)
    return {"name": name, "product_type": ptype, "model": model,
            "phases": out}


@app.post("/epics")
async def epics_create(request: Request):
    """
    Create an epic from phases the operator has reviewed.

    No rules here. product_epics.define already refuses a duplicate name, a
    phase with no slug, duplicate slugs and a dependency pointing forward; a
    copy of those checks in this endpoint would be a second set to keep in
    step.
    """
    try:
        pe, _ = _epic_tools()
    except ImportError as e:
        return JSONResponse({"error": f"epics are not installed: {e}"},
                            status_code=501)

    body = await request.json()
    name = (body.get("name") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", name or ""):
        return JSONResponse(
            {"error": "the name must be lowercase letters, digits and "
                      "hyphens — it becomes a directory and three slugs"},
            status_code=400)

    try:
        import product_pathways as _pw
        ptype = _pw.normalise(body.get("product_type")) or _pw.DEFAULT
    except ImportError:
        ptype = (body.get("product_type") or "software").strip()

    spec = {"name": name,
            "product_slug": (body.get("product_slug") or name).strip(),
            "product_type": ptype,
            "brief": (body.get("brief") or "").strip(),
            "phases": [{"title": p.get("title"),
                        "slug": (p.get("slug") or "").strip(),
                        "brief": p.get("brief"),
                        "depends_on": p.get("depends_on")}
                       for p in (body.get("phases") or [])]}
    try:
        epic = pe.define(spec)
    except Exception as e:
        # An EpicError is the operator's mistake stated plainly — a duplicate
        # name, a forward dependency. It is a 400, not a server fault.
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"epic": epic["name"],
                         "phases": len(epic["phases"])}, status_code=201)


'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in NEEDED + [API]:
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, calls_in, py_ok, PatchCheckFailed  # noqa: E402

src = API.read_text(encoding="utf-8")
print("patch_phaser_api\n")

if "/epics/split" in src:
    sys.exit("NOTHING DONE — the Phaser endpoints are already there.")

n = src.count(ANCHOR)
print(f"  {'ok ' if n == 1 else '!! '}the insertion point  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# Everything this block leans on, checked rather than assumed. A route that
# calls a helper that is not there fails at request time, in a browser, with
# a 500 and no clue.
need = {"_epic_tools": "def _epic_tools",
        "load_agent_config": "def load_agent_config",
        "DEFAULT_AGENT_CONFIG": "DEFAULT_AGENT_CONFIG",
        "Request": "Request",
        "JSONResponse": "JSONResponse",
        "re (module)": "\nimport re",
        "os (module)": "\nimport os"}
missing = [k for k, v in need.items() if v not in src]
if missing:
    sys.exit(f"NOTHING DONE — main.py has no {', '.join(missing)}. "
             f"The endpoints would fail at request time.")
print("  ok  _epic_tools, load_agent_config, re and os are all in main.py")

if "async def" not in src:
    sys.exit("NOTHING DONE — this does not look like an async FastAPI app.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
API.write_text(src.replace(ANCHOR, BLOCK + ANCHOR, 1), encoding="utf-8")
print(f"\nwrote {API.name}, backup tagged {TAG}-{stamp}")

after = API.read_text(encoding="utf-8")
try:
    py_ok(after, "main.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# Scoped checks, from the parse tree.
if len(calls_in(after, "epics_create", "define")) != 1:
    sys.exit("⚠️  epics_create does not call define exactly once — restore "
             "the backup.")
if len(calls_in(after, "epics_split", "_phase_slug")) != 1:
    sys.exit("⚠️  epics_split does not build its slugs here — restore the "
             "backup.")
code = code_only(after)
body = code[code.find("def epics_create"):code.find("def epics_list")]
if "INSERT" in body.upper() or "SELECT" in body.upper():
    sys.exit("⚠️  epics_create contains SQL — restore the backup.")
print("verified: main.py parses; epics_create calls define once and holds no "
      "SQL,\n          and split builds its own slugs.")

print("""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api
  curl -s localhost:8000/epics -H "x-api-key: $DUCORN_API_TOKEN" | head -5

Then apply patch_phaser_ui.py for the button that calls these.
""")
