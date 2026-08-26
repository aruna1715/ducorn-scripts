"""
DuCorn Smart Proxy — port 4001
Sits in front of LiteLLM (port 4000)
Applies routing classifier then forwards to LiteLLM
"""
import httpx
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()

LITELLM_URL = "http://localhost:4000"

# ── Routing table ──────────────────────────────────────────
import os

# One local model for test runs — loading a second evicts the first and costs
# minutes per swap on a 48GB box.
LOCAL_TEST_MODEL = os.environ.get("DUCORN_LOCAL_MODEL", "local-fast")

KNOWN_MODELS = {"claude-sonnet", "local-fast",
                "deepseek-chat", "deepseek-reasoner"}

AGENT_ROUTES = {
    "echo":  "local-fast",   "cleo":  "local-fast",
    "nova":  "deepseek-chat","aria":  "deepseek-chat", "opus": "deepseek-chat",
    "atlas": "claude-sonnet","sage":  "claude-sonnet",
    "rex":   "claude-sonnet","iris":  "claude-sonnet",
}

LOCAL_HEAVY_AGENTS = {"atlas", "sage", "rex", "iris"}
COMPRESSION_KEYWORDS = ["summarize","summarise","compress","shorten","tldr","brief","condense"]
SHORT_THRESHOLD = 30


def _local_only() -> bool:
    """Read per-request, not at import — the flow sets this per run."""
    return os.environ.get("DUCORN_LOCAL_ONLY", "").lower() in ("1", "true", "yes")


def detect_agent(messages):
    system_msg = next((m["content"] for m in messages
                       if m.get("role") == "system" and isinstance(m.get("content"), str)), "").lower()
    return next((a for a in AGENT_ROUTES if a in system_msg), None)


def classify(messages, agent_id):
    """Fallback routing for calls that named no model."""
    prompt = " ".join(m.get("content", "") for m in messages
                      if isinstance(m.get("content"), str)).lower()
    token_count = len(prompt.split())
    if agent_id:
        return AGENT_ROUTES[agent_id], f"agent={agent_id} routing table"
    if token_count < SHORT_THRESHOLD:
        return "local-fast", f"unknown agent, short prompt ({token_count} tokens)"
    if any(kw in prompt for kw in COMPRESSION_KEYWORDS):
        return "local-fast", "compression keyword"
    return "claude-sonnet", "default fallback"


def choose_model(body, messages):
    """Precedence: test-run lock > the model the caller asked for > classifier.

    The dashboard model switcher is the single source of truth for production
    runs; it reaches us as body["model"]. We honour it rather than overriding it.
    """
    agent_id = detect_agent(messages)

    if _local_only():
        return LOCAL_TEST_MODEL, "test run — local only"

    requested = body.get("model")
    if requested in KNOWN_MODELS:
        return requested, "model switcher"

    return classify(messages, agent_id)
    
@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    chosen, reason = choose_model(body, messages)
    body["model"] = chosen
    print(f"[DuCorn Router] agent={detect_agent(messages) or 'unknown'} | {reason} | → {chosen}")
    
    headers = dict(request.headers)
    headers.pop("content-length", None)
    headers.pop("host", None)

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{LITELLM_URL}/v1/chat/completions",
            json=body,
            headers=headers
        )
    
    # Handle empty or non-JSON responses
    try:
        content = resp.json()
        return JSONResponse(content=content, status_code=resp.status_code)
    except Exception:
        # Return raw response if JSON parsing fails
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json")
        )
        
@app.post("/chat/completions")
async def chat_no_prefix(request: Request):
    """Handle requests without /v1/ prefix — CrewAI internal calls"""
    return await chat(request)

@app.get("/v1/models")
async def models(request: Request):
    headers = dict(request.headers)
    headers.pop("host", None)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{LITELLM_URL}/v1/models", headers=headers)
    return JSONResponse(content=resp.json())

@app.get("/health")
async def health():
    return {"status": "ok", "router": "DuCorn Smart Proxy", "port": 4001}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4001)
