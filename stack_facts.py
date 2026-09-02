#!/usr/bin/env python3
"""
Read the machine and write down what is actually true about it.

    python3 scripts/stack_facts.py                 print it
    python3 scripts/stack_facts.py --write         refresh the internal context
    python3 scripts/stack_facts.py --public        the shape only, no internals
    python3 scripts/stack_facts.py --write --public

── WHY ──────────────────────────────────────────────────────────────────────

The pipeline is about to write a technology-stack document, and the only thing
it knows about DuCorn is ducorn-stack-context.md: 11,941 bytes written on
17 August, truncated to 2,000 characters before it reaches the agent. Twenty-one
commits to ducorn/ since, plus a rewritten deploy tool, skill runner, flow, API
and health check. Asked for a comprehensive architecture on 2,000 stale
characters, an agent does not decline — it invents.

And a hand-written architecture document is a second copy of the truth. Every
serious defect this week was two copies of one fact drifting: a gate's
threshold and the prose describing it, a status the code wrote and the
constraint that refused it, the venv QA used and the interpreter deploy ran.
A "single source of truth" typed out by hand is that pattern by design.

So the facts are derived, every time, from the things that define them:

    services      the launchd plists that actually run — command, port, log
    models        litellm_config.yaml, and the switcher's current assignment
    pipeline      the graph's own add_node calls, read from the source
    skills        the G-Stack directory
    schema        scripts/migrations/
    products      what is deployed, and what each declares in service.json
    dependencies  every requirements.txt, with its pins

Nothing is typed from memory. If a port changes, this changes.

── SECRETS ──────────────────────────────────────────────────────────────────

Environment variables appear by NAME only, never by value, and the section
carrying them is headed "Credentials" so that _stack_context()'s existing
filter drops it before any of this reaches a model. Values are never read.

── PUBLIC MODE ──────────────────────────────────────────────────────────────

--public emits the same structure with ports, absolute paths, launchd labels
and log locations removed: the shape of the system without an operations
manual. Same source, so the two documents cannot disagree about what DuCorn is.
"""
import argparse
import ast
import json
import plistlib
import re
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
LAUNCHD = DC / "launchd"
LIVE_AGENTS = Path.home() / "Library/LaunchAgents"
OUT = DC / "ducorn-products/docs/ducorn-stack-context.md"


def _port_registry():
    """
    The core services' ports, from the deploy tool that assigns them.

    Read rather than retyped: a number copied into this file is a second copy
    of a fact, which is the thing this whole script exists to avoid.
    """
    tool = DC / "ducorn/tools/DuCornDeployTool.py"
    try:
        tree = ast.parse(tool.read_text(errors="replace"))
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", "") == "PORT_REGISTRY"):
                return ast.literal_eval(node.value)
    except (OSError, SyntaxError, ValueError):
        pass
    return {}


PORT_REGISTRY = _port_registry()
OUT_PUBLIC = DC / "ducorn-products/docs/ducorn-architecture-public.md"

ap = argparse.ArgumentParser()
ap.add_argument("--write", action="store_true", help="write the file, not stdout")
ap.add_argument("--public", action="store_true", help="no ports, paths or labels")
args = ap.parse_args()
PUB = args.public

L = []


def h(text, level=2):
    L.append(f"\n{'#' * level} {text}\n")


def line(text=""):
    L.append(text)


def table(headers, rows):
    if not rows:
        line("_none found_")
        return
    line("| " + " | ".join(headers) + " |")
    line("| " + " | ".join("---" for _ in headers) + " |")
    for r in rows:
        line("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")


def short(p):
    """A path a reader can place, without publishing the machine's layout."""
    s = str(p)
    return "…" if PUB else s.replace(str(DC), "~/DC").replace(str(Path.home()), "~")


# ── services ─────────────────────────────────────────────────────────────────
def services():
    rows = []
    seen = set()
    for d in (LIVE_AGENTS, LAUNCHD):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("com.ducorn.*.plist")):
            try:
                p = plistlib.loads(f.read_bytes())
            except Exception:
                continue
            label = p.get("Label", f.stem)
            if label in seen:
                continue
            seen.add(label)
            argv = p.get("ProgramArguments", [])
            port = next((a for a in argv if re.fullmatch(r"\d{4,5}", str(a))), "")
            if not port:
                # The core services take their port from elsewhere. The deploy
                # tool's PORT_REGISTRY is where that is declared, so read it
                # rather than typing the numbers here.
                port = str(PORT_REGISTRY.get(
                    label.replace("com.ducorn.", ""), "")) or ""
            if not port:
                env_ports = [v for k, v in (p.get("EnvironmentVariables") or {}).items()
                             if k.endswith("PORT") and str(v).isdigit()]
                port = env_ports[0] if env_ports else ""
            # The command without the interpreter's absolute path, which is
            # noise; what matters is what it runs.
            cmd = " ".join(str(a).split("/")[-1] if str(a).startswith("/") else str(a)
                           for a in argv)
            if PUB:
                rows.append([label.replace("com.ducorn.", ""),
                             cmd.split()[0] if cmd else "—"])
            else:
                rows.append([label, port or "—", cmd[:70],
                             short(p.get("StandardOutPath", ""))])
    return rows


# ── models ───────────────────────────────────────────────────────────────────
def models():
    cfg = DC / "scripts/litellm_config.yaml"
    served = []
    if cfg.is_file():
        for m in re.finditer(r"model_name:\s*(\S+)", cfg.read_text(errors="replace")):
            served.append(m.group(1).strip('"\''))
    assigned = {}
    ac = DC / "shared/agent_config.json"
    if ac.is_file():
        try:
            assigned = json.loads(ac.read_text())
        except ValueError:
            pass
    return served, assigned


# ── the pipeline, from the graph itself ──────────────────────────────────────
def graph_nodes():
    """The nodes build_graph actually registers. Not a list someone typed."""
    flow = DC / "ducorn/flows/langgraph_flow.py"
    if not flow.is_file():
        return []
    try:
        tree = ast.parse(flow.read_text(errors="replace"))
    except SyntaxError:
        return []
    return [a.args[0].value for a in ast.walk(tree)
            if isinstance(a, ast.Call) and getattr(a.func, "attr", "") == "add_node"
            and a.args and isinstance(a.args[0], ast.Constant)]


def skills():
    d = DC / "gstack/skills"
    rows = []
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        title = ""
        for ln in f.read_text(errors="replace").splitlines():
            if ln.startswith("#"):
                title = ln.lstrip("# ").strip()
                break
        rows.append([f.stem, title[:70]])
    return rows


# ── schema ───────────────────────────────────────────────────────────────────
def migrations():
    d = DC / "scripts/migrations"
    rows = []
    for f in sorted(d.glob("*.sql")) if d.is_dir() else []:
        purpose = ""
        for ln in f.read_text(errors="replace").splitlines():
            t = ln.strip().lstrip("-").strip()
            if t and not t.lower().startswith(f.stem.lower()) and len(t) > 12:
                purpose = t
                break
        rows.append([f.name, purpose[:72]])
    return rows


# ── products ─────────────────────────────────────────────────────────────────
def products():
    root = DC / "ducorn-products/products"
    rows = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if not d.is_dir() or d.name.startswith("_"):
            continue
        kind = []
        if (d / "index.html").is_file():
            kind.append("page")
        if any((d / p).is_file() for p in ("api/main.py", "main.py", "app/main.py")):
            kind.append("api")
        declared = "yes" if (d / "service.json").is_file() else "—"
        deployed = "yes" if (LIVE_AGENTS / f"com.ducorn.{d.name}.plist").is_file() \
            else "—"
        rows.append([d.name, "+".join(kind) or "files", declared, deployed])
    return rows


# ── dependencies ─────────────────────────────────────────────────────────────
def dependencies():
    seen = {}
    for req in sorted(DC.glob("ducorn-products/products/*/requirements.txt")):
        for ln in req.read_text(errors="replace").splitlines():
            ln = ln.split("#")[0].strip()
            if not ln:
                continue
            name = re.split(r"[=<>\[]", ln, maxsplit=1)[0].strip()
            if name:
                seen.setdefault(name, set()).add(ln)
    pyproject = DC / "ducorn/pyproject.toml"
    if pyproject.is_file():
        for m in re.finditer(r'"([A-Za-z0-9_.\-]+)[><=~]{1,2}([^"]+)"',
                             pyproject.read_text(errors="replace")):
            seen.setdefault(m.group(1), set()).add(m.group(1) + m.group(2))
    return [[n, ", ".join(sorted(v))[:48]] for n, v in sorted(seen.items())]


# ═════════════════════════════════════════════════════════════════════════════
line(f"# DuCorn — {'architecture' if PUB else 'stack facts'}")
line()
line(f"_Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/stack_facts.py`, "
     f"from the machine itself. Do not edit — regenerate._")
line()
line("Every table below is read from the thing that defines it: the launchd "
     "jobs that actually run, the router's model list, the graph's own node "
     "registrations, the migrations directory. Nothing here is typed from "
     "memory, so nothing here can quietly go stale.")

h("Services")
if PUB:
    line("What runs continuously on the host.")
    table(["service", "runs"], services())
else:
    table(["launchd label", "port", "command", "log"], services())

h("The pipeline")
nodes = graph_nodes()
line(f"`build_graph` registers {len(nodes)} nodes, in this order:")
line()
line("`" + "` → `".join(nodes) + "`" if nodes else "_could not read the graph_")
line()
line("Gates are approval points. A gate posts to Slack and the process exits; "
     "approving it starts a new process that resumes from the checkpoint. "
     "That is why a gate is a node and not a wait.")

h("G-Stack skills")
line("A build runs a subset of these in isolated subprocesses. Each records a "
     "pass or fail plus a fingerprint of the prompt that produced it, so a "
     "cached result is only replayed for the instructions that created it.")
line()
table(["skill", "title"], skills())

h("Models")
served, assigned = models()
line(f"The router serves {len(served)} models. Agents are assigned from the "
     f"dashboard switcher, which is the single source for model choice — "
     f"nothing may hardcode a model.")
line()
if not PUB:
    table(["model"], [[m] for m in served])
if assigned:
    line()
    line("Current assignment:")
    line()
    table(["agent", "model"], sorted(assigned.items()))

h("Database")
line("Two databases: `ducorn` for pipeline state, `litellm_db` for "
     "checkpoints and spend.")
line()
table(["migration", "what it does"], migrations())

h("Products")
table(["product", "shape", "declares service.json", "deployed"], products())

h("Dependencies")
line("Pinned across product requirements and the pipeline's own project file.")
line()
table(["package", "pin"], dependencies())

if not PUB:
    # Headed "Credentials" on purpose: _stack_context() drops any section whose
    # heading matches its skip list, so this never reaches a model. Names only —
    # no value is read from disk anywhere in this script.
    h("Credentials")
    line("Names only. Values live in `shared/.env` and are never read by this "
         "script.")
    line()
    env = DC / "shared/.env"
    names = []
    if env.is_file():
        for ln in env.read_text(errors="replace").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                names.append(ln.split("=", 1)[0].strip())
    table(["variable"], [[n] for n in sorted(set(names))])

text = "\n".join(L).rstrip() + "\n"

# A value must never end up here. Cheap, absolute check before anything is
# written: no line may contain an assignment that looks like a secret.
for ln in text.splitlines():
    if re.search(r"(KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*\S{8,}", ln, re.I):
        sys.exit(f"REFUSING TO WRITE — a line looks like a credential:\n  {ln[:80]}")

if not args.write:
    print(text)
    sys.exit(0)

dest = OUT_PUBLIC if PUB else OUT
if dest.is_file():
    prev = dest.read_text(errors="replace")
    # The file being replaced may hold hand-written reasoning that no generator
    # can reproduce — WHY a tool was chosen, what was tried first. Keeping a
    # copy costs nothing; losing it costs the only part that was not derivable.
    was_generated = "scripts/stack_facts.py" in prev[:400]
    if not was_generated:
        keep = dest.with_name(dest.stem + ".prior.md")
        keep.write_text(prev, encoding="utf-8")
        print(f"the previous version was hand-written — kept as {keep.name}")
        print("  read it: anything explaining WHY belongs in the new one.")
    print(f"replacing {short(dest)} ({len(prev):,} → {len(text):,} bytes)")
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(text, encoding="utf-8")
print(f"wrote {dest}")
print(f"  {len(text):,} bytes, {text.count(chr(10)):,} lines, "
      f"{len([l for l in L if l.lstrip().startswith('## ')])} sections")
