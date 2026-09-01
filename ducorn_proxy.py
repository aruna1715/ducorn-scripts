"""
DuCorn Smart Proxy — port 4001
Sits in front of LiteLLM (port 4000).

The router used to have opinions. It had a hardcoded KNOWN_MODELS set, an
AGENT_ROUTES table, and a classify() heuristic, and those opinions beat the
dashboard model switcher on roughly 85% of calls — 2622 of 3407 requests were
decided by "agent=sage routing table", not by the model the switcher chose.

It now has exactly one job: confirm the requested model is one LiteLLM actually
serves, and forward. LiteLLM's model_list is the single registry; the switcher
picks from it; nothing here overrides that choice. An unknown or missing model
is a 400 naming the valid options, never a silent substitution — a fallback
from a frontier model to an 8B local one is a 20x quality drop dressed as
success, and that is precisely how an unkeyed LiteLLM went unnoticed for weeks.
"""
import os
import time

import sys

import httpx
from fastapi import FastAPI, Request

# Logs go to a redirected file, which Python block-buffers — so the log
# lags reality by however long a 4-8KB buffer takes to fill. Today that
# meant tailing router.log showed the past, not the present.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
from fastapi.responses import JSONResponse, Response

app = FastAPI()

LITELLM_URL = "http://localhost:4000"
MODEL_CACHE_TTL = float(os.environ.get("DUCORN_MODEL_CACHE_TTL", "60"))

_model_cache = {"names": set(), "ts": 0.0}


async def serving_models(client, headers):
    """
    What LiteLLM actually serves, cached briefly.

    Returns an empty set if LiteLLM cannot be asked. That is deliberate: an
    empty set disables local validation and lets LiteLLM be the authority,
    rather than this proxy guessing from a stale hardcoded list.
    """
    now = time.time()
    if _model_cache["names"] and now - _model_cache["ts"] < MODEL_CACHE_TTL:
        return _model_cache["names"]

    try:
        auth = {k: v for k, v in headers.items() if k.lower() == "authorization"}
        resp = await client.get(f"{LITELLM_URL}/v1/models", headers=auth, timeout=10)
        names = {m["id"] for m in resp.json().get("data", []) if m.get("id")}
        if names:
            _model_cache.update(names=names, ts=now)
        return names
    except Exception as e:
        print(f"[DuCorn Router] could not read LiteLLM model list ({e}) — "
              f"forwarding without local validation")
        return set()


def normalise(name):
    """
    Strip a provider prefix. CrewAI and LiteLLM clients often send
    'openai/claude-sonnet' where the registry knows it as 'claude-sonnet'.
    """
    return name.split("/")[-1].strip() if name else ""


# How long to wait for an answer, by where the answer comes from.
#
# One blanket 300s meant a stalled Ollama call burned five minutes before
# anyone found out. A local model that has produced nothing in two and a half
# minutes is stuck behind a reload or a queue, not thinking — failing fast lets
# the caller retry inside its own budget. Remote models keep the long one: a
# large completion legitimately takes minutes.
LOCAL_TIMEOUT = float(os.environ.get("DUCORN_LOCAL_TIMEOUT", "150"))
REMOTE_TIMEOUT = float(os.environ.get("DUCORN_REMOTE_TIMEOUT", "300"))


# The longest answer a local model may produce.
#
# Ollama measures ~30 tok/s on this machine and the local budget is 150s, so
# anything past ~4,500 tokens cannot finish inside the timeout regardless. A
# PRD from llama3.1 is 1,000–2,500 tokens, so this is about double what the
# work needs. Raise it and you must raise DUCORN_LOCAL_TIMEOUT with it, or the
# cap just becomes a slower timeout.
LOCAL_MAX_TOKENS = int(os.environ.get("DUCORN_LOCAL_MAX_TOKENS", "4096"))


def _cap_local_output(body: dict, model: str) -> str:
    """
    Bound a local generation. Returns a note for the log, or "".

    llama3.1 fell into a repetition loop and produced 147,538 tokens on one
    request, holding Ollama's only slot for over an hour while every other
    call queued behind it and timed out. Nothing capped the length: not the
    config, not the callers. Now the router does, for everyone, whatever they
    forget to set.
    """
    if not str(model).startswith("local-"):
        return ""
    asked = body.get("max_tokens")
    if asked is None:
        body["max_tokens"] = LOCAL_MAX_TOKENS
        return f"max_tokens defaulted to {LOCAL_MAX_TOKENS}"
    try:
        asked = int(asked)
    except (TypeError, ValueError):
        body["max_tokens"] = LOCAL_MAX_TOKENS
        return f"max_tokens was {asked!r}; set to {LOCAL_MAX_TOKENS}"
    if asked > LOCAL_MAX_TOKENS:
        body["max_tokens"] = LOCAL_MAX_TOKENS
        return f"max_tokens clamped {asked} → {LOCAL_MAX_TOKENS}"
    return ""


def _timeout_for(model: str) -> float:
    return LOCAL_TIMEOUT if str(model).startswith("local-") else REMOTE_TIMEOUT


def _bad_request(message, available):
    return JSONResponse(
        {"error": {
            "type": "invalid_request_error",
            "message": message,
            "available_models": sorted(available) if available else [],
            "hint": ("Pick a model in the dashboard model switcher. This proxy "
                     "does not substitute a different model — a silent "
                     "downgrade is worse than a failed run."),
        }},
        status_code=400,
    )


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    requested = body.get("model")

    headers = dict(request.headers)
    headers.pop("content-length", None)
    headers.pop("host", None)
    auth = (headers.get("authorization") or "").strip()
    if auth.lower() in ("", "bearer"):
        # An empty bearer crashes httpx downstream and surfaces as a bare 500.
        headers.pop("authorization", None)

    async with httpx.AsyncClient(timeout=300) as client:
        available = await serving_models(client, headers)

        if not requested:
            print(f"[DuCorn Router] REJECTED — no model specified "
                  f"({len(messages)} messages)")
            return _bad_request(
                "No model specified. Every caller must name a model; this "
                "proxy no longer guesses one from the prompt.", available)

        chosen = normalise(requested)
        if available and chosen not in available:
            print(f"[DuCorn Router] REJECTED — requested={requested!r} "
                  f"not served by LiteLLM", flush=True)
            return _bad_request(
                f"Model {requested!r} is not served by LiteLLM. Add it to "
                f"litellm_config.yaml, or pick one that exists.", available)

        body["model"] = chosen
        note = "" if chosen == requested else f" (normalised from {requested!r})"
        capped = _cap_local_output(body, chosen)
        print(f"[DuCorn Router] → {chosen}{note}"
              + (f"  [{capped}]" if capped else ""), flush=True)

        budget = _timeout_for(chosen)
        started = time.monotonic()
        try:
            resp = await client.post(f"{LITELLM_URL}/v1/chat/completions",
                                     json=body, headers=headers, timeout=budget)
        except httpx.TimeoutException as e:
            waited = time.monotonic() - started
            print(f"[DuCorn Router] upstream timeout after {waited:.0f}s "
                  f"(budget {budget:.0f}s) serving {chosen!r}: {e}", flush=True)
            return JSONResponse(
                {"error": {"type": "upstream_timeout",
                           "message": f"LiteLLM at {LITELLM_URL} did not respond "
                                      f"within {budget:.0f}s serving {chosen!r}.",
                           "waited_seconds": round(waited, 1),
                           "budget_seconds": budget,
                           "hint": "For a local model this usually means Ollama "
                                   "is reloading or queued behind another run. "
                                   "Raise DUCORN_LOCAL_TIMEOUT only after "
                                   "checking the router's ⏱ lines."}},
                status_code=504)
        except httpx.HTTPError as e:
            # "LiteLLM is down", "your request was malformed" and "the empty
            # bearer crashed httpx" were all indistinguishable bare 500s. Name
            # the upstream so the next person does not have to guess.
            print(f"[DuCorn Router] upstream unreachable: {e}", flush=True)
            return JSONResponse(
                {"error": {"type": "upstream_unavailable",
                           "message": f"Cannot reach LiteLLM at {LITELLM_URL}: {e}",
                           "hint": "Check: launchctl list | grep litellm, and "
                                   "tail ~/DC/logs/litellm.log. LiteLLM will not "
                                   "start without PostgreSQL."}},
                status_code=502)

    # The number nobody was writing down. Every "is it looping / is Ollama
    # overloaded / is the context too long" question this week was one line of
    # timing data away from an answer.
    elapsed = time.monotonic() - started
    if elapsed > budget * 0.5:
        print(f"[DuCorn Router] ⏱ SLOW {chosen} {elapsed:.0f}s of a "
              f"{budget:.0f}s budget", flush=True)
    else:
        print(f"[DuCorn Router] ⏱ {chosen} {elapsed:.1f}s", flush=True)

    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception:
        return Response(content=resp.content, status_code=resp.status_code,
                        media_type=resp.headers.get("content-type", "application/json"))


@app.post("/chat/completions")
async def chat_no_prefix(request: Request):
    """CrewAI internal calls arrive without the /v1 prefix."""
    return await chat(request)


@app.get("/v1/models")
async def models(request: Request):
    headers = dict(request.headers)
    headers.pop("host", None)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{LITELLM_URL}/v1/models", headers=headers)
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


@app.get("/health")
async def health():
    return {"status": "ok", "router": "DuCorn Smart Proxy", "port": 4001}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4001)
