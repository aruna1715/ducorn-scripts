#!/usr/bin/env python3
"""
Make the design gate a real choice: viewable variants, one approval each,
and a build that implements the one you picked.

Run migration 002 first:
    python3 scripts/migrate.py --status
    python3 scripts/migrate.py

Touches three files, all or nothing:

  langgraph_flow.py  node_design registers variants with view tokens;
                     node_gate_2 raises one approval per variant and posts
                     links; node_build reads the chosen design and builds it
  main.py            GET /d/<token> serves one variant, exempt from x-api-key
  slack_bot.py       approving a variant records the choice and supersedes
                     its siblings

WHY LINKS AND NOT SCREENSHOTS
-----------------------------
A screenshot of a page is worse than the page — you cannot scroll it, resize
it, or click anything, and judging a UI from a thumbnail is how the last three
rounds of bad designs got approved in principle and rejected on sight. The
variants are self-contained HTML with inlined CSS, so a URL renders the real
thing on a phone.

WHY A TOKEN IN THE PATH
-----------------------
Every other endpoint requires an x-api-key header. A link tapped in Slack
cannot send one, and the API hostname has no Cloudflare Access policy to sit
behind. So each variant gets its own 43-character random token which grants
exactly one thing: GET on that file. It expires in 30 days. This is weaker
than authentication and is meant to be — the alternative on offer was making
the whole endpoint public.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW  = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
API   = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
SLACK = Path("/Users/ducorn/DC/scripts/slack_bot.py")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


# ── 1. langgraph_flow ────────────────────────────────────────────────────────
f = FLOW.read_text(encoding="utf-8")
if "design_variants" in f and "view_token" in f:
    sys.exit("Already patched — view_token is in langgraph_flow.py.")
if "node_design" not in f:
    sys.exit("Run patch_design_node.py first.")

# _request_approval gained next_phase/topic in the last patch; it needs
# document_path too, so a per-variant approval can say WHICH variant it is.
f = swap(FLOW, "_request_approval doc_path", f,
'''def _request_approval(title: str, description: str,
                      next_phase: str = None, topic: str = None) -> int:''',
'''def _request_approval(title: str, description: str,
                      next_phase: str = None, topic: str = None,
                      document_path: str = None) -> int:''')

f = swap(FLOW, "_request_approval insert", f,
'''                INSERT INTO approval_requests
                    (requested_by, title, description, status,
                     next_phase, product_slug)
                VALUES ('atlas', %s, %s, 'pending', %s, %s)
                RETURNING id
            """, (title, description, next_phase, topic))''',
'''                INSERT INTO approval_requests
                    (requested_by, title, description, status,
                     next_phase, product_slug, document_path)
                VALUES ('atlas', %s, %s, 'pending', %s, %s, %s)
                RETURNING id
            """, (title, description, next_phase, topic, document_path))''')

f = swap(FLOW, "register helper", f, '''def node_design(state: DuCornState) -> DuCornState:''',
'''DESIGN_LINK_BASE = os.environ.get("DUCORN_PUBLIC_API", "https://api.ducorn-hq.live")
DESIGN_LINK_TTL_DAYS = 30


def _register_variants(topic: str, variants: list) -> list:
    """
    Record each rendered variant with its own capability token.

    Returns [{name, archetype, path, token, url}] for the ones that rendered.
    A variant that failed to render is skipped rather than given a link that
    would 404 when a founder taps it.
    """
    import secrets
    from ducorn_db import get_conn

    rows = []
    with get_conn() as conn:
        cur = conn.cursor()
        # Previous attempts at this product are cleared, so an old link cannot
        # show a design that is no longer on offer.
        cur.execute("DELETE FROM design_variants WHERE slug=%s", (topic,))
        for v in variants:
            if not v.get("html") or not v.get("path"):
                continue
            spec = v.get("spec") or {}
            name = spec.get("name") or v.get("archetype") or "variant"
            token = secrets.token_urlsafe(32)
            cur.execute("""
                INSERT INTO design_variants
                    (slug, variant_name, archetype, register, path, view_token,
                     expires_at)
                VALUES (%s, %s, %s, %s, %s, %s,
                        NOW() + make_interval(days => %s))
                RETURNING id
            """, (topic, name, v.get("archetype"), spec.get("register"),
                  v["path"], token, DESIGN_LINK_TTL_DAYS))
            row = cur.fetchone()
            rows.append({
                "id": row[0] if isinstance(row, tuple) else row["id"],
                "name": name,
                "archetype": v.get("archetype"),
                "register": spec.get("register"),
                "path": v["path"],
                "url": f"{DESIGN_LINK_BASE}/d/{token}",
                "problems": v.get("problems") or [],
            })
    return rows


def node_design(state: DuCornState) -> DuCornState:''')

f = swap(FLOW, "design returns rows", f,
'''        paths = [v.get("path") for v in rendered if v.get("path")]
        print(f"✅ DESIGN: {len(rendered)}/{len(variants)} variants rendered")''',
'''        registered = _register_variants(topic, rendered)
        paths = [v["path"] for v in registered]
        print(f"✅ DESIGN: {len(rendered)}/{len(variants)} variants rendered")
        for r in registered:
            print(f"   · {r['name']}  {r['url']}")''')

# gate_2 raises one approval per variant.
f = swap(FLOW, "gate_2 body", f,
'''        variants = state.get("design_variants") or []
        print(f"\\n🔔 Gate 2: Requesting design approval for '{topic}'")

        approval_id = _request_approval(
            f"UI designs ready — approve to build: {topic}",
            f"DESIGN produced {len(variants)} variants in products/{topic}/design/",
            next_phase="build", topic=topic,
        )
        if not approval_id:
            print(f"❌ Gate 2: _request_approval returned None for {topic}")
            _post_slack(f"❌ *ATLAS Gate 2 ERROR* — `{topic}`: approval request failed")
            return {**state, "status": "failed", "error": "approval_id is None"}

        listing = "\\n".join(f"• `{Path(p).name}`" for p in variants) or "• (none)"
        _post_slack(
            f"🎨 *ATLAS Gate 2 — UI Designs Ready*\\n\\n"
            f"*Product:* `{topic}`\\n"
            f"*Model:* `{state.get('design_model', '?')}`\\n"
            f"*Variants:* in `products/{topic}/design/`\\n{listing}\\n\\n"
            f"✅ Approve: `@DuCorn approve {approval_id}`\\n"
            f"❌ Cancel: `@DuCorn reject {approval_id}`"
        )''',
'''        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, variant_name, archetype, register, path, "
                        "view_token FROM design_variants WHERE slug=%s "
                        "ORDER BY id", (topic,))
            rows = cur.fetchall()

        if not rows:
            print(f"❌ Gate 2: no design_variants rows for {topic}")
            _post_slack(f"❌ *ATLAS Gate 2 ERROR* — `{topic}`: no variants recorded")
            return {**state, "status": "failed", "error": "no design variants"}

        print(f"\\n🔔 Gate 2: Requesting design approval for '{topic}' "
              f"({len(rows)} variants)")

        # One approval per variant, so approving IS choosing. document_path
        # carries which one — the column already existed for exactly this.
        lines, ids = [], []
        for vid, name, archetype, register, path, token in rows:
            approval_id = _request_approval(
                f"UI design — approve to build: {topic}",
                f"Variant '{name}' ({archetype}) for {topic}",
                next_phase="build", topic=topic, document_path=path,
            )
            if not approval_id:
                print(f"❌ Gate 2: approval failed for variant {name}")
                _post_slack(f"❌ *ATLAS Gate 2 ERROR* — `{topic}`: could not "
                            f"raise approval for variant {name}")
                return {**state, "status": "failed",
                        "error": f"approval failed for {name}"}
            ids.append(approval_id)
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE design_variants SET approval_id=%s WHERE id=%s",
                            (approval_id, vid))
            lines.append(
                f"*{name}* — {archetype}, {register or 'balanced'}\\n"
                f"    <{DESIGN_LINK_BASE}/d/{token}|open the design>\\n"
                f"    ✅ `@DuCorn approve {approval_id}`")

        approval_id = ids[0]   # state keeps one for the existing plumbing
        _post_slack(
            f"🎨 *ATLAS Gate 2 — {len(rows)} UI Designs Ready*\\n\\n"
            f"*Product:* `{topic}`\\n"
            f"*Model:* `{state.get('design_model', '?')}`\\n\\n"
            + "\\n\\n".join(lines) +
            f"\\n\\nApprove ONE — the others are set aside and the build "
            f"implements the one you pick.\\n"
            f"❌ Reject all: `@DuCorn reject {approval_id}`"
        )''')

# node_build hands the chosen design to the builder.
f = swap(FLOW, "build reads choice", f,
'''    topic = state["topic"]
    coder = state.get("coder", "crewai")
    engine = state.get("build_engine", "fast")
    product_type = state.get("product_type", "software")''',
'''    topic = state["topic"]
    coder = state.get("coder", "crewai")
    engine = state.get("build_engine", "fast")
    product_type = state.get("product_type", "software")

    # The approved design, if this product has one. Written into the product
    # directory where the build skills already look, so the chosen variant is
    # the UI that gets implemented rather than a picture nobody reads.
    try:
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT design_choice FROM pipeline_runs WHERE slug=%s",
                        (topic,))
            row = cur.fetchone()
        chosen = row[0] if row else None
        if chosen and Path(chosen).exists():
            from tools.product_jail import resolve_in_jail
            target = resolve_in_jail(topic, "APPROVED_DESIGN.html")
            target.write_text(Path(chosen).read_text(encoding="utf-8"),
                              encoding="utf-8")
            os.environ["DUCORN_APPROVED_DESIGN"] = str(target)
            print(f"🎨 build will implement {Path(chosen).name} "
                  f"(copied to {target.name})")
        elif chosen:
            # Loud: the founder chose something and it is not there.
            print(f"⚠️  design_choice is {chosen!r} but that file does not "
                  f"exist — building without it")
    except Exception as e:
        print(f"⚠️  could not read design_choice for {topic}: {e}")''')
edits.append((FLOW, f))


# ── 2. main.py — serve one variant by token ──────────────────────────────────
a = API.read_text(encoding="utf-8")
if "/d/{token}" in a:
    sys.exit("Already patched — the design view endpoint is present.")

a = swap(API, "exempt path", a,
'''    if request.method == "OPTIONS" or request.url.path in [
        "/docs", "/openapi.json", "/redoc",
        "/digest/audio", "/chat/audio", "/digest/stream"
    ]:
        return await call_next(request)''',
'''    if request.method == "OPTIONS" or request.url.path in [
        "/docs", "/openapi.json", "/redoc",
        "/digest/audio", "/chat/audio", "/digest/stream"
    ]:
        return await call_next(request)
    # Design variants are opened from a Slack link, on a phone, by a person
    # whose browser cannot attach an x-api-key header. Each URL carries its own
    # 43-character token which grants read of exactly one HTML file and expires.
    # Narrower than making the endpoint public; weaker than real auth, and
    # deliberately so — see migration 002.
    if request.url.path.startswith("/d/"):
        return await call_next(request)''')

a = swap(API, "view endpoint", a, '''@app.post("/pipeline/approve/{slug}")''',
'''@app.get("/d/{token}")
def view_design(token: str):
    """Serve one design variant by capability token."""
    # Imported locally: this file has no top-level `re` or `Path`, and adding
    # globals for one endpoint invites a name collision with the aliased local
    # imports elsewhere in it (_Path, _PathCheck).
    import re as _re
    from pathlib import Path as _P
    from fastapi.responses import HTMLResponse

    if not _re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token or ""):
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT slug, variant_name, archetype, path,
                       expires_at < NOW() AS expired
                FROM design_variants WHERE view_token=%s
            """, (token,))
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)
    if row["expired"]:
        return HTMLResponse(
            "<h1>This design link has expired</h1>"
            "<p>Design links last 30 days. Ask ATLAS to regenerate.</p>",
            status_code=410)

    # The path came from design_variants, which only node_design writes, and
    # node_design resolves through the product jail. Re-check anyway: this
    # endpoint is the one thing on the API reachable without a key, so it does
    # not get to trust a stored string.
    p = _P(row["path"]).resolve()
    expected = (_P("/Users/ducorn/DC/ducorn-products/products")
                / row["slug"] / "design").resolve()
    if expected not in p.parents or not p.is_file():
        print(f"[view_design] refusing {row['path']!r} — outside "
              f"{expected} for slug {row['slug']!r}")
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.post("/pipeline/approve/{slug}")''')
edits.append((API, a))


# ── 3. slack_bot — approving a variant records the choice ────────────────────
s = SLACK.read_text(encoding="utf-8")
if "design_choice" in s:
    sys.exit("Already patched — design_choice is in slack_bot.py.")

s = swap(SLACK, "select doc path", s,
'''            cur.execute("SELECT title, description, next_phase, product_slug "
                        "FROM approval_requests WHERE id=%s", (approval_id,))''',
'''            cur.execute("SELECT title, description, next_phase, product_slug, "
                        "document_path FROM approval_requests WHERE id=%s",
                        (approval_id,))''')

s = swap(SLACK, "record choice", s,
'''        _db_engine, _db_coder, _db_complexity = "fast", "crewai", "simple"''',
'''        # A gate that raised one approval per option: approving this one is
        # choosing it, so record the choice and set the siblings aside. They
        # were not rejected — nobody turned them down, they lost a vote of one.
        chosen_design = row[4] if len(row) > 4 else None
        if chosen_design:
            try:
                from ducorn_db import get_conn as _gc
                with _gc() as _conn:
                    _cur = _conn.cursor()
                    _cur.execute("UPDATE pipeline_runs SET design_choice=%s "
                                 "WHERE slug=%s", (chosen_design, topic))
                    _cur.execute("""
                        UPDATE approval_requests
                        SET status='superseded', superseded_by=%s
                        WHERE product_slug=%s AND next_phase=%s
                          AND status='pending' AND id<>%s
                    """, (approval_id, topic, next_phase, approval_id))
                    setaside = _cur.rowcount
                import os.path as _op
                say(f"🎨 Building *{_op.basename(chosen_design)}*"
                    + (f" — {setaside} other variant(s) set aside."
                       if setaside else "."))
            except Exception as _e:
                # Do NOT continue: the build would start without knowing which
                # design won, which is the decorative-gate failure again.
                say(f"❌ Approved, but I could not record the design choice "
                    f"({_e}). Build not started.")
                print(f"[approve] {approval_id}: design_choice write failed: {_e}")
                return

        _db_engine, _db_coder, _db_complexity = "fast", "crewai", "simple"''')
edits.append((SLACK, s))


# ── Write once every anchor has hit ──────────────────────────────────────────
for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-variants-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")

import ast
for path, _ in edits:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — restore from "
                 f"*.backup-variants-{stamp}.*")

print("applied: " + ", ".join(applied))
print(f"backups: *.backup-variants-{stamp}.*")
print()
print("Restart the API and the Slack bot.")
