#!/usr/bin/env python3
"""
Say where the product is. Nobody has ever been told.

── WHAT WAS MISSING ─────────────────────────────────────────────────────────

    ✅ ducorn-spend-status deployed and serving
      api      :8093  HTTP 200 from /health  (pid 18297)
      web      :8096  HTTP 200 from /  (pid 18300)

Ports and process ids. To open the thing you just shipped you assemble
http://localhost:8096 in your head, and that address works on exactly one
machine — not from the phone the Slack message arrived on.

There is no url column on pipeline_runs, nothing in the dashboard, and the
Slack post is this same text. So the address of a deployed product exists only
in the terminal of whoever was watching. Tomorrow morning, finding a product
you shipped means reading a launchd plist.

── WHAT THIS ADDS ───────────────────────────────────────────────────────────

The LAN address, everywhere it is needed:

    ✅ ducorn-spend-status deployed and serving
    🌐 URL: http://192.168.1.24:8096
      api      :8093  HTTP 200 from /health  (pid 18297)
      web      :8096  HTTP 200 from /  (pid 18300)

    Slack:  🎉 ducorn-spend-status is LIVE!
            👉 Open ducorn-spend-status   ← a real link
    DB:     pipeline_runs.product_url, so the dashboard can show it too

The LAN address rather than localhost, because the point is to be clickable
from the device you read Slack on. A product that ships a page is linked to
its page; an API-only product is linked to its /docs, which is the only page
it has.

── PUBLIC IS OPT-IN, AND STAYS THAT WAY ─────────────────────────────────────

A product becomes reachable from outside your network only by asking, in its
own .env:

    PUBLIC_HOSTNAME=spend.ducorn-hq.live

That is deliberate. ducorn-spend-status has no authentication — its PRD says
read-only and internal, and the code review confirmed there is none — so
publishing it by default would put your LiteLLM spend history on the open web.
"Deployed" must never quietly mean "on the internet".

Even opted in, this does not touch ~/.cloudflared/config.yml. A deploy tool
that silently rewrites your tunnel is worse than one that asks. It prints the
exact ingress block to paste, and records the hostname separately from the LAN
address so the two are never confused.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")

tool_s = TOOL.read_text(encoding="utf-8")
flow_s = FLOW.read_text(encoding="utf-8")

if "def lan_ip" in tool_s:
    sys.exit("Already patched — the product's URL is published.")
if "def plan_services" not in tool_s:
    sys.exit("Apply patch_deploy_services.py first. NOTHING WRITTEN.")
if "🎉 *{topic} is LIVE!*" not in flow_s:
    sys.exit("The deploy Slack post is not where expected in langgraph_flow.py. "
             "NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ 1. the deploy tool learns the address ═══════════════════════════════════
tool_s = swap("lan_ip", tool_s, "def _used_ports() -> set:",
              '''def lan_ip() -> str:
    """
    This machine's address on the local network.

    localhost is correct and useless: the Slack message is read on a phone.
    The UDP connect sends no packets — it only asks the routing table which
    interface would be used to reach the outside, which is the address other
    devices on this network can reach us on.
    """
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.settimeout(1.0)
            sk.connect(("8.8.8.8", 80))
            return sk.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def page_reads_api_param(product_dir: Path) -> bool:
    """
    Does this page accept ?api= to locate its backend?

    REX built exactly that into ducorn-spend-status:

        // ?api=http://other-host:8765  (useful for local dev)
        const API_URL = (params.get('api') || 'http://localhost:8765') ...

    It is the product's own documented escape hatch, and it is the difference
    between a URL that opens a page and a URL that opens a working page — the
    baked-in localhost:8765 is the port the README used, not the port the
    deployer allocated, and localhost on a phone is the phone.
    """
    page = product_dir / "index.html"
    try:
        text = page.read_text(errors="replace")
    except OSError:
        return False
    return ("params.get('api')" in text or 'params.get("api")' in text
            or "get('api')" in text or 'get("api")' in text)


def product_urls(services: list, product_env: dict,
                 product_dir: Path = None) -> tuple:
    """
    (url to open, public url or "") for a deployed product.

    The page if it ships one; otherwise the API's /docs, which is the only
    thing an API-only product has that a person can look at. When the page
    accepts ?api=, the address it is told to use is carried in the link, so
    the page finds the API on the port this deploy actually chose.

    public is returned separately and only when the product asked for it. Most
    of these products have no authentication, so a public address is a decision
    somebody makes on purpose, never a side effect of deploying.
    """
    web = next((sp for sp in services if sp["role"] == "web"), None)
    api = next((sp for sp in services if sp["role"] == "api"), None)
    host = lan_ip()

    if web:
        url = f"http://{host}:{web['port']}"
        if api and product_dir is not None and page_reads_api_param(product_dir):
            url += f"/?api=http://{host}:{api['port']}"
    elif api:
        url = f"http://{host}:{api['port']}/docs"
    else:
        return "", ""

    hostname = (product_env.get("PUBLIC_HOSTNAME") or "").strip()
    public = f"https://{hostname}" if hostname else ""
    return url, public


def _used_ports() -> set:''')

# ── CORS must allow the address people actually open ─────────────────────────
#
# Without this the URL is right and the page still fails. It is served from
# http://192.168.1.24:8096 and calls the API on the same host — a different
# origin — and the allow-list only ever contained localhost and 127.0.0.1. The
# browser blocks the fetch and the page reports "Load failed", which looks like
# a dead API and is actually a missing origin.
tool_s = swap("lan origin", tool_s,
              '''            web = next((sp for sp in services if sp["role"] == "web"), None)
            if web and "ALLOWED_ORIGINS" in product_env:
                mine = (f"http://localhost:{web['port']},"
                        f"http://127.0.0.1:{web['port']}")
                if f":{web['port']}" not in product_env["ALLOWED_ORIGINS"]:
                    product_env["ALLOWED_ORIGINS"] = (
                        product_env["ALLOWED_ORIGINS"].rstrip(",") + "," + mine)
                    print(f"🔧 ALLOWED_ORIGINS          ← deployer "
                          f"(page is on :{web['port']})", flush=True)''',
              '''            web = next((sp for sp in services if sp["role"] == "web"), None)
            if web and "ALLOWED_ORIGINS" in product_env:
                _host = lan_ip()
                mine = [f"http://localhost:{web['port']}",
                        f"http://127.0.0.1:{web['port']}",
                        f"http://{_host}:{web['port']}"]
                current = [o.strip() for o in
                           product_env["ALLOWED_ORIGINS"].split(",") if o.strip()]
                added = [o for o in mine if o not in current]
                if added:
                    product_env["ALLOWED_ORIGINS"] = ",".join(current + added)
                    print(f"🔧 ALLOWED_ORIGINS          ← deployer "
                          f"(+{len(added)}: page on :{web['port']}, "
                          f"including {_host})", flush=True)''')

# the success message leads with it
tool_s = swap("success message", tool_s,
              '''            return (f"✅ {slug} deployed and serving\\n"
                    + "\\n".join(lines)
                    + f"\\nLogs: " + ", ".join(sp["log"] for sp in started))''',
              '''            url, public = product_urls(started, product_env, product_dir)
            head = f"✅ {slug} deployed and serving"
            if url:
                # This exact line is what the flow parses to store the URL and
                # to put a real link in Slack. Human-readable and machine-
                # readable at once, so there is only one of it.
                head += f"\\n🌐 URL: {url}"
            if public:
                head += f"\\n🔓 PUBLIC: {public}"
                web = next((sp for sp in started if sp["role"] == "web"), started[0])
                print("\\n⚠️  This product asked to be public. Nothing here edits "
                      "your tunnel — add this to ~/.cloudflared/config.yml and "
                      "reload cloudflared:\\n"
                      f"  - hostname: {public.replace('https://', '')}\\n"
                      f"    service: http://localhost:{web['port']}\\n",
                      flush=True)

            return (head + "\\n"
                    + "\\n".join(lines)
                    + f"\\nLogs: " + ", ".join(sp["log"] for sp in started))''')

# ═══ 2. the flow records it and puts a link in Slack ═════════════════════════
flow_s = swap("store helper", flow_s, "def _update_db_status(topic: str, status: str",
              '''def _store_product_url(topic: str, url: str, public: str = "") -> None:
    """
    Remember where the product lives.

    Best effort on purpose: a deploy that genuinely succeeded must not be
    reported as failed because a column is missing. If migration 006 has not
    been applied the warning says exactly that.
    """
    if not url:
        return
    try:
        from ducorn_db import get_conn
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE pipeline_runs SET product_url=%s, public_url=%s, "
                "updated_at=NOW() WHERE slug=%s",
                (url, public or None, topic))
        print(f"🌐 recorded {url} for {topic}", flush=True)
    except Exception as e:
        print(f"⚠️  could not record the product URL ({e}) — "
              f"run: python3 scripts/migrate.py", flush=True)


def _update_db_status(topic: str, status: str''')

flow_s = swap("slack post", flow_s,
              '''            _post_slack(f"🎉 *{topic} is LIVE!*\\n\\n{result}")''',
              '''            # The address is the point of the message. Slack renders
            # <url|text> as a link, so it is tappable from a phone — which is
            # where these are actually read.
            _m = re.search(r"🌐 URL: (\\S+)", result)
            _p = re.search(r"🔓 PUBLIC: (\\S+)", result)
            _url = _m.group(1) if _m else ""
            _public = _p.group(1) if _p else ""
            _store_product_url(topic, _url, _public)

            if _url:
                _head = (f"🎉 *{topic} is LIVE!*\\n\\n"
                         f"👉 <{_url}|Open {topic}>")
                if _public:
                    _head += f"\\n🔓 Public: <{_public}|{_public}>"
                _post_slack(f"{_head}\\n\\n{result}")
            else:
                _post_slack(f"🎉 *{topic} is LIVE!*\\n\\n{result}")''')

# ── write both, or neither ───────────────────────────────────────────────────
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backups = {}
for path, text, tag in ((TOOL, tool_s, "url"), (FLOW, flow_s, "url")):
    b = path.with_name(f"{path.stem}.backup-{tag}-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — both files reverted")


TOOL.write_text(tool_s, encoding="utf-8")
FLOW.write_text(flow_s, encoding="utf-8")

for path in (TOOL, FLOW):
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")

# `re` is used at module level in neither, but the flow's new code uses re
# inside a function — confirm the module can still reach it.
if "\nimport re\n" not in flow_s.split("def ", 1)[0]:
    seg_uses_re = "_m = re.search" in flow_s
    has_local = "    import re" in flow_s
    if seg_uses_re and not has_local:
        die("langgraph_flow uses re in the deploy node but does not import it")

print("import/syntax check: both files parse")

# ── exercise the URL choice ──────────────────────────────────────────────────
src = TOOL.read_text(encoding="utf-8")
t = ast.parse(src)
seg = {n.name: ast.get_source_segment(src, n) for n in t.body
       if isinstance(n, ast.FunctionDef)}
for need in ("lan_ip", "product_urls"):
    if need not in seg:
        die(f"{need} did not land")

import tempfile
ns = {"lan_ip": lambda: "192.168.1.24", "Path": Path,
      "page_reads_api_param": lambda d: (d / "index.html").read_text().find("get('api')") >= 0
      if (d / "index.html").is_file() else False}
exec(seg["product_urls"], ns)
urls = ns["product_urls"]

_plain = Path(tempfile.mkdtemp()); (_plain / "index.html").write_text("<h1>no param</h1>")
_smart = Path(tempfile.mkdtemp())
(_smart / "index.html").write_text("const A = params.get('api') || 'http://localhost:8765';")

WEB = {"role": "web", "port": 8096}
API = {"role": "api", "port": 8093}

print("\nwhich address gets published:")
API_Q = "http://192.168.1.24:8096/?api=http://192.168.1.24:8093"
for services, env, d, want, why in [
    ([API, WEB], {}, _smart, (API_Q, ""), "TONIGHT: the link carries the API port"),
    ([API, WEB], {}, _plain, ("http://192.168.1.24:8096", ""),
     "a page with no ?api= support gets the plain URL"),
    ([API], {}, _plain, ("http://192.168.1.24:8093/docs", ""), "API only → its /docs"),
    ([WEB], {}, _smart, ("http://192.168.1.24:8096", ""),
     "a page with no API behind it needs no parameter"),
    ([API, WEB], {"PUBLIC_HOSTNAME": "spend.ducorn-hq.live"}, _plain,
     ("http://192.168.1.24:8096", "https://spend.ducorn-hq.live"),
     "opted in → LAN *and* public, kept apart"),
    ([API, WEB], {"PUBLIC_HOSTNAME": "  "}, _plain,
     ("http://192.168.1.24:8096", ""), "blank is not opting in"),
    ([{"role": "software", "port": 1}], {}, _plain, ("", ""),
     "a plain script has no page"),
]:
    got = urls(services, env, d)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {str(got):58} {why}")
    if ok is False:
        die(f"expected {want}, got {got}")

# the flow must be able to parse what the tool writes
import re as _re
sample = ("✅ zz deployed and serving\n🌐 URL: http://192.168.1.24:8096\n"
          "🔓 PUBLIC: https://spend.ducorn-hq.live\n  web  :8096  HTTP 200")
m = _re.search(r"🌐 URL: (\S+)", sample)
p = _re.search(r"🔓 PUBLIC: (\S+)", sample)
print("\nthe flow can read what the tool writes:")
print(f"  ok   url    → {m.group(1) if m else None}")
print(f"  ok   public → {p.group(1) if p else None}")
if not m or m.group(1) != "http://192.168.1.24:8096" or not p:
    die("the flow cannot parse the tool's URL line")

# and a deploy with no URL must not crash the parse
if _re.search(r"🌐 URL: (\S+)", "✅ zz deployed and serving\n  software :1"):
    die("a product with no page must yield no URL")
print("  ok   a product with no page yields no URL and the old message stands")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print()
print("Apply the migration first — the URL is stored on pipeline_runs:")
print("  cd ~/DC && python3 scripts/migrate.py")
print()
print("Then redeploy to publish the address for the product already running:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase deploy --engine gstack --coder crewai "
      "--complexity simple")
print()
print("Slack will get:  🎉 ducorn-spend-status is LIVE!")
print("                 👉 Open ducorn-spend-status")
