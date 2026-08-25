"""
DuCorn LiteLLM Custom Router Classifier
~/DC/scripts/ducorn_classifier.py

Routing logic:
  Primary signal  — agent identity (read from system message)
  Secondary signal — prompt token count (override for very short prompts)
  Tertiary signal  — keyword detection (compression/summarization tasks)

Tier 1 — Always local/free:     ECHO, CLEO       → local-heavy (Qwen 2.5 32B)
Tier 2 — Mid-complexity/cheap:  NOVA, ARIA, OPUS  → deepseek-chat
Tier 3 — Critical reasoning:    ATLAS, SAGE, REX, IRIS → claude-sonnet

Override rules (applied after agent routing):
  - Any prompt < 80 tokens from ANY agent → local-fast (Llama 8B)
  - Compression/summarize keywords        → local-fast (fast enough for summaries)
  - ECHO or CLEO regardless of length     → local-heavy (never Claude)
"""

# ── Agent routing table ────────────────────────────────────────────────────────
AGENT_ROUTES = {
    # Tier 1 — Always free local (high volume, no quality risk)
    "echo":  "local-heavy",    # Support triage — Qwen 32B handles this well
    "cleo":  "local-heavy",    # Data processing — free, no API cost

    # Tier 2 — DeepSeek (cheap, good quality for content/docs)
    "nova":  "deepseek-chat",  # Sales copy — DeepSeek Chat is strong here
    "aria":  "deepseek-chat",  # Content creation — same
    "opus":  "deepseek-chat",  # Document generation — same

    # Tier 3 — Claude (quality critical, orchestration/research/code/QA)
    "atlas": "claude-sonnet",  # Orchestration decisions — must be best quality
    "sage":  "claude-sonnet",  # Research + PRD generation — quality critical
    "rex":   "claude-sonnet",  # Code generation — quality critical
    "iris":  "claude-sonnet",  # QA review — quality critical
}

# ── Keywords that trigger fast local routing ───────────────────────────────────
COMPRESSION_KEYWORDS = [
    "summarize", "summarise", "compress", "shorten", "tldr",
    "brief", "condense", "digest", "recap"
]

# ── Agents that must NEVER use Claude regardless of prompt ─────────────────────
LOCAL_ONLY_AGENTS = {"echo", "cleo"}

# ── Token threshold for short-prompt override ──────────────────────────────────
SHORT_PROMPT_THRESHOLD = 80


async def custom_router_pre_call_hook(user_api_key_dict, cache, data, call_type):
    """
    Called by LiteLLM before every inference request.
    Reads messages, detects agent identity, applies routing rules.
    """
    messages = data.get("messages", [])

    # Build full prompt text for analysis
    prompt = " ".join(
        m.get("content", "") for m in messages
        if isinstance(m.get("content"), str)
    ).lower()

    # Count tokens (approximate — split on whitespace)
    token_count = len(prompt.split())

    # Detect agent identity from system message
    system_msg = next(
        (m["content"] for m in messages if m.get("role") == "system"),
        ""
    ).lower()

    agent_id = next(
        (agent for agent in AGENT_ROUTES if agent in system_msg),
        None
    )

    # ── Routing decision tree ──────────────────────────────────────────────────

    # Rule 1: Local-only agents — never route to paid APIs regardless of anything
    if agent_id in LOCAL_ONLY_AGENTS:
        chosen_model = "local-heavy"
        reason = f"agent={agent_id} is local-only"

    # Rule 2: Very short prompt from any agent — local-fast is sufficient
    elif token_count < SHORT_PROMPT_THRESHOLD:
        chosen_model = "local-fast"
        reason = f"short prompt ({token_count} tokens < {SHORT_PROMPT_THRESHOLD})"

    # Rule 3: Compression/summarization keywords — local-fast handles these
    elif any(kw in prompt for kw in COMPRESSION_KEYWORDS):
        chosen_model = "local-fast"
        reason = "compression keyword detected"

    # Rule 4: Agent-specific routing from routing table
    elif agent_id:
        chosen_model = AGENT_ROUTES[agent_id]
        reason = f"agent={agent_id} routing table"

    # Rule 5: Unknown agent — default to Claude (safe fallback)
    else:
        chosen_model = "claude-sonnet"
        reason = "no agent detected — safe default"

    # Apply the routing decision
    data["model"] = chosen_model

    # Log every routing decision — visible in LiteLLM logs
    print(
        f"[DuCorn Router] "
        f"agent={agent_id or 'unknown'} | "
        f"tokens={token_count} | "
        f"reason={reason} | "
        f"→ {chosen_model}"
    )

    return data