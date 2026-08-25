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
AGENT_ROUTES = {
    "echo":  "local-heavy",
    "cleo":  "local-heavy",
    "nova":  "deepseek-chat",
    "aria":  "deepseek-chat",
    "opus":  "deepseek-chat",
    "atlas": "claude-sonnet",
    "sage":  "claude-sonnet",
    "rex":   "claude-sonnet",
    "iris":  "claude-sonnet",
}
LOCAL_ONLY = {"echo", "cleo"}
COMPRESSION_KEYWORDS = ["summarize","summarise","compress","shorten","tldr","brief","condense"]
SHORT_THRESHOLD = 30

def classify(messages):
    prompt = " ".join(
        m.get("content","") for m in messages
        if isinstance(m.get("content"), str)
    ).lower()
    token_count = len(prompt.split())
    system_msg = next(
        (m["content"] for m in messages if m.get("role") == "system"), ""
    ).lower()
    agent_id = next((a for a in AGENT_ROUTES if a in system_msg), None)

    # Rule 1: Local-only agents — never route to paid APIs
    if agent_id in LOCAL_ONLY:
        chosen_model = "local-heavy"
        reason = f"agent={agent_id} local-only"

    # Rule 2: Known agent — always use routing table (ignore token count)
    elif agent_id:
        chosen_model = AGENT_ROUTES[agent_id]
        reason = f"agent={agent_id} routing table"

    # Rule 3: Unknown agent — short prompt goes local-fast
    elif token_count < SHORT_THRESHOLD:
        chosen_model = "local-fast"
        reason = f"unknown agent short prompt ({token_count} tokens)"

    # Rule 4: Compression keywords
    elif any(kw in prompt for kw in COMPRESSION_KEYWORDS):
        chosen_model = "local-fast"
        reason = "compression keyword"

    # Rule 5: Default fallback
    else:
        chosen_model = "claude-sonnet"
        reason = "default fallback"

    print(f"[DuCorn Router] agent={agent_id or 'unknown'} | tokens={token_count} | {reason} | → {chosen_model}")
    return chosen_model

@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    body["model"] = classify(messages)

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
