"""Router tests against a fake LiteLLM. No network, no models, no cost."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import ducorn_proxy as P
from fastapi.testclient import TestClient

STATE = {"models": ["claude-sonnet", "local-fast", "deepseek-chat"], "seen": []}


class FakeLiteLLM(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"data": [{"id": m} for m in STATE["models"]]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        STATE["seen"].append(json.loads(self.rfile.read(n)))
        self._send({"model": STATE["seen"][-1]["model"],
                    "choices": [{"message": {"content": "ok"}}]})

    def log_message(self, *a):
        pass


fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' — ' + str(detail)) if detail else ''}")
    if not cond:
        fails.append(name)


def main():
    srv = HTTPServer(("127.0.0.1", 0), FakeLiteLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    P.LITELLM_URL = f"http://127.0.0.1:{srv.server_port}"
    good_url = P.LITELLM_URL
    c = TestClient(P.app, raise_server_exceptions=False)

    H = {"Authorization": "Bearer sk-test"}
    M = [{"role": "user", "content": "hi"}]

    def fresh():
        P._model_cache.update(names=set(), ts=0.0)

    r = c.post("/v1/chat/completions", json={"model": "claude-sonnet", "messages": M}, headers=H)
    check("known model forwarded",
          r.status_code == 200 and STATE["seen"][-1]["model"] == "claude-sonnet")

    fresh()
    c.post("/v1/chat/completions", json={"model": "openai/claude-sonnet", "messages": M}, headers=H)
    check("provider prefix normalised", STATE["seen"][-1]["model"] == "claude-sonnet",
          STATE["seen"][-1]["model"])

    r = c.post("/v1/chat/completions", json={"model": "gpt-9", "messages": M}, headers=H)
    check("unknown model 400s", r.status_code == 400)
    check("400 names the valid models",
          set(r.json()["error"]["available_models"]) == set(STATE["models"]),
          r.json()["error"]["available_models"])

    r = c.post("/v1/chat/completions", json={"messages": M}, headers=H)
    check("missing model 400s", r.status_code == 400,
          r.json()["error"]["message"][:44])

    before = len(STATE["seen"])
    c.post("/v1/chat/completions", json={"model": "nope", "messages": M}, headers=H)
    check("rejected request never reaches litellm", len(STATE["seen"]) == before)

    r = c.post("/v1/chat/completions", json={"model": "local-fast", "messages": M},
               headers={"Authorization": "Bearer "})
    check("empty bearer tolerated", r.status_code == 200, r.status_code)

    # Upstream down: no local validation, and a named 502 rather than a bare 500.
    fresh()
    P.LITELLM_URL = "http://127.0.0.1:9"
    r = c.post("/v1/chat/completions", json={"model": "anything", "messages": M}, headers=H)
    check("upstream down returns 502", r.status_code == 502, r.status_code)
    check("502 names LiteLLM", "LiteLLM" in r.json()["error"]["message"],
          r.json()["error"]["message"][:60])
    check("502 is not a bare 500", r.status_code != 500)
    P.LITELLM_URL = good_url
    fresh()

    # The model list is cached, so a healthy path does not re-query every call.
    c.post("/v1/chat/completions", json={"model": "local-fast", "messages": M}, headers=H)
    cached = set(P._model_cache["names"])
    STATE["models"] = ["only-this-one"]
    c.post("/v1/chat/completions", json={"model": "local-fast", "messages": M}, headers=H)
    check("model list is cached", P._model_cache["names"] == cached)
    STATE["models"] = ["claude-sonnet", "local-fast", "deepseek-chat"]

    # The old opinions are gone for good. Check CODE, not the docstring that
    # explains their removal — a grep over prose is how the last two of these
    # gave false failures.
    import ast
    tree = ast.parse(open("ducorn_proxy.py").read())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    live = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            live.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            live.append(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docs:
                live.append(node.value)
    joined = " ".join(live)
    gone = [n for n in ("AGENT_ROUTES", "KNOWN_MODELS", "classify",
                        "LOCAL_HEAVY_AGENTS", "COMPRESSION_KEYWORDS")
            if n in joined]
    check("routing table and classifier removed from code", not gone, str(gone))
    check("no model name hardcoded as a value",
          not any(m in joined.lower() for m in ("claude-", "gpt-", "llama", "deepseek")),
          joined[:80])

    srv.shutdown()
    print()
    print(f"{len(fails)} failed" if fails else "all checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
