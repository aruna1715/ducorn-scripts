#!/usr/bin/env python3
"""
The brief wizard picks its model from the switcher, like everything else.

── WHAT IT DOES TODAY ───────────────────────────────────────────────────────

    json={
        "model": "local-fast",
        "messages": [{"role": "user", "content": prompt}],

Hardcoded. The dashboard's model switcher — the single source of truth for
which model does what — does not reach this endpoint, so every brief has been
written by llama3.1 whatever the switcher says.

That is a live instance of the rule about no hardcoded models, and it is in
the worst possible place. The brief is the most load-bearing input in the
pipeline: it is fenced as BINDING in SAGE's task, research refuses to run
without it, and every artefact downstream is an expansion of it. Drafting it
on an 8B local model and then expanding it on Sonnet is backwards.

── THE CHANGE ───────────────────────────────────────────────────────────────

A BRIEF entry in DEFAULT_AGENT_CONFIG, defaulting to claude-sonnet, and
generate_brief reads its model from load_agent_config() like every pipeline
node does.

Nothing in the dashboard needs editing. renderModelSwitcher is already

    Object.entries(_agentModels).map(([agent, model]) => ...)

so a new agent in the config appears in the switcher on its own — the same
property that let DESIGN be added without touching the front end. That is the
design paying off rather than being worked around.

Two deliberate choices, both arguable:

  · IT STAYS BILLED TO LITELLM_KEY_ATLAS. The wizard is a dashboard tool, and
    ATLAS's $20 is the dashboard's budget. Billing it to SAGE would eat the
    $5 that SAGE needs for the research the brief then feeds. A separate
    LITELLM_KEY_BRIEF would be tidier and is a key that does not exist yet —
    inventing one here would fail at the first call.

  · NO FALLBACK LOGIC. load_agent_config() already layers saved choices over
    the defaults and prints a warning if the file is unreadable, so it always
    returns something sane. Adding a second fallback would be a second place
    for the answer to come from, which is how DESIGN ended up with two.

The response now carries the model that wrote the brief, so the wizard can
show it. A founder should not have to guess whether the words in front of them
came from Sonnet or from llama3.1.

── AFTER APPLYING ───────────────────────────────────────────────────────────

This needs an API restart, and that is now safe: pipelines are spawned with
start_new_session=True since yesterday, so restarting the API no longer takes
a running pipeline down with it. Your current build was started from the CLI
in any case, so it is not even a child of the API.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

MAIN = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
s = MAIN.read_text(encoding="utf-8")

if '"BRIEF"' in s:
    sys.exit("Already patched — BRIEF is in the switcher.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("config entry", s, '''    # The model used for UI design generation. Kept separate from the build
    # agents because design is where extra spend pays back — a page a founder
    # ships is worth more than a marginal token saving.
    "DESIGN": "claude-sonnet"
}''', '''    # The model used for UI design generation. Kept separate from the build
    # agents because design is where extra spend pays back — a page a founder
    # ships is worth more than a marginal token saving.
    "DESIGN": "claude-sonnet",
    # The brief wizard. Was hardcoded to local-fast, which meant every brief
    # was drafted by llama3.1 whatever the switcher said — and the brief is the
    # most load-bearing input there is: fenced as BINDING in SAGE's task,
    # required before research will run at all, and the thing every later
    # artefact expands. Drafting it small and expanding it large is backwards.
    "BRIEF": "claude-sonnet"
}''')

s = swap("model from switcher", s, '''    try:
        import requests as _req
        resp = _req.post(
            "http://localhost:4001/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ.get('LITELLM_KEY_ATLAS', '')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "local-fast",''',
         '''    # From the switcher, not from a literal. load_agent_config() layers the
    # saved choices over the defaults and warns if the file is unreadable, so
    # it always returns something usable — a second fallback here would be a
    # second place for the answer to come from.
    brief_model = load_agent_config().get("BRIEF", DEFAULT_AGENT_CONFIG["BRIEF"])
    print(f"[brief wizard] drafting {name!r} on {brief_model}")

    try:
        import requests as _req
        resp = _req.post(
            "http://localhost:4001/v1/chat/completions",
            headers={
                # Billed to ATLAS: this is a dashboard tool and ATLAS holds the
                # dashboard's budget. Billing it to SAGE would spend the $5 that
                # SAGE needs for the research this brief then feeds.
                "Authorization": f"Bearer {os.environ.get('LITELLM_KEY_ATLAS', '')}",
                "Content-Type": "application/json"
            },
            json={
                "model": brief_model,''')

s = swap("report the model", s, '''        brief = resp.json()["choices"][0]["message"]["content"].strip()
        return {"status": "ok", "brief": brief}
    except Exception as e:
        return {"status": "error", "error": str(e), "brief": ""}''',
         '''        brief = resp.json()["choices"][0]["message"]["content"].strip()
        # Say which model wrote it. A founder should not have to guess whether
        # the words in front of them came from Sonnet or from an 8B local model.
        return {"status": "ok", "brief": brief, "model": brief_model}
    except Exception as e:
        return {"status": "error", "error": str(e), "brief": "",
                "model": brief_model}''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = MAIN.with_name(f"main.backup-briefmodel-{stamp}.py")
shutil.copy2(MAIN, backup)
MAIN.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, MAIN)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# Read the config back as data. The switcher renders whatever this dict holds,
# so if BRIEF is not in it the front end will not show it and nothing else
# will say why.
tree = ast.parse(s)
node = next((n for n in tree.body if isinstance(n, ast.Assign)
             and getattr(n.targets[0], "id", "") == "DEFAULT_AGENT_CONFIG"), None)
if node is None:
    shutil.copy2(backup, MAIN)
    sys.exit(f"DEFAULT_AGENT_CONFIG not found after the edit — reverted")

config = ast.literal_eval(node.value)
if config.get("BRIEF") != "claude-sonnet":
    shutil.copy2(backup, MAIN)
    sys.exit(f"BRIEF is {config.get('BRIEF')!r}, expected 'claude-sonnet' — "
             f"reverted from {backup}")
if "local-fast" in s[s.index("async def generate_brief"):
                     s.index("async def generate_brief") + 3000]:
    shutil.copy2(backup, MAIN)
    sys.exit(f"a hardcoded local-fast survives inside generate_brief — "
             f"reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"switcher now has {len(config)} agents: {', '.join(sorted(config))}")
print(f"backup:  {backup.name}")
print()
print("Restart the API — safe now that pipelines detach:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
print()
print("Then hard-refresh the dashboard. BRIEF appears in the switcher on its")
print("own — renderModelSwitcher iterates the config, so no front-end change.")
